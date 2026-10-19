# /// script
# dependencies = ["httpx", "pillow"]
# ///
"""Does GPT-6 Luna Decisions judge painting stages the way the artist did?

Sends downscaled moonlit-canal stage images (never the reference photos) to
OpenRouter's Decisions API and compares Luna's answers with the recorded human
verdicts in docs/REFERENCE_BRUSH_RECONSTRUCTION.md and
docs/CONTOUR_CONSTRUCTION_LESSONS.md.

Run from the repo root:
    doppler run -- uv run krita-creative-agent/scripts/evaluate-luna-critic.py

A synthetic orange/green control runs first: if Luna cannot tell them apart the
image is not reaching the model and the run stops (other image shapes return
HTTP 200 while silently ignoring the picture).
"""
import base64, io, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from project_dir import project_dir
import httpx
from PIL import Image

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "openai/gpt-6-luna-decisions"
MAX_SIDE = 512
ROOT = project_dir()          # the artwork folder the images below live in
PROJECT = ROOT / "projects/moonlit-canal"

# Recorded human verdicts; "expect" is what an aligned critic should report.
STAGES = [
    ("stage-01-structure", ".painting-process/stage-01-structure.png",
     "early manual block-in", {"finished": False}),
    ("stage-04-light-edges", ".painting-process/stage-04-light-edges.png",
     "REJECTED: graphic/stylized, edges too hard, ribbon-like hair, unfinished",
     {"finished": False, "hard_graphic": True}),
    ("07-tonal-reconstruction", ".painting-process/07-tonal-reconstruction.png",
     "coarse reference-sampled reconstruction (intermediate)", {"finished": False}),
    ("09-faces-and-hands", ".painting-process/09-faces-and-hands.png",
     "focal finish pass", {}),
    ("faces-and-shawl-finished", "faces-and-shawl-finished.png",
     "ACCEPTED final", {"finished": True, "hard_graphic": False}),
]

CONTEXT = ("A stage of a Krita painting of figures in shawls and coats on a "
           "moonlit canal, aiming for a realistic oil-painting finish. Judge only "
           "what is visible in the image.")

QUESTIONS = {
    "finished": {
        "type": "noul",
        "instructions": "Is this painting finished enough to deliver as a realistic oil-painting study?",
        "criteria": {"true": "Readable figures and faces, resolved edges and materials; ready to deliver.",
                     "false": "Still a block-in, construction or visibly incomplete stage."}},
    "hard_graphic": {
        "type": "noul",
        "instructions": "Does the image look graphic or stylized, with hard cut-out edges and flat shapes, rather than painterly?",
        "criteria": {"true": "Hard flat shapes, poster/vector-like edges, ribbon-like strokes.",
                     "false": "Soft, varied painterly edges and blended transitions."}},
    "finish_level": {
        "type": "score",
        "instructions": "How far along is this painting toward a realistic finished oil study?",
        "criteria": ["Abstract block-in", "Construction with basic shapes",
                     "Developed but rough", "Nearly finished", "Finished realistic study"]},
    "next_action": {
        "type": "choice",
        "instructions": "Which single next step would most improve this painting?",
        "criteria": {"soften_edges": "Soften hard edges and integrate shapes.",
                     "rebuild_structure": "Fix drawing, proportions and silhouettes first.",
                     "refine_faces_hands": "Refine focal faces and hands.",
                     "add_material_texture": "Add fabric, hair and surface texture.",
                     "leave_unchanged": "It is done; stop painting.",
                     "request_review": "Too uncertain; ask the art director."}},
}


def data_url(img: Image.Image) -> str:
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def decide(key, image, questions, text=CONTEXT):
    # Only the chat-style image_url part is seen by the model on OpenRouter.
    state = [{"type": "text", "text": text},
             {"type": "image_url", "image_url": {"url": image}}]
    t = time.perf_counter()
    r = httpx.post(URL, headers={"Authorization": f"Bearer {key}"}, timeout=60,
                   json={"model": MODEL, "state": state, "questions": questions})
    elapsed = time.perf_counter() - t
    body = r.json()
    if r.status_code != 200:
        sys.exit(f"HTTP {r.status_code}: {body.get('error', body)}")
    return body, elapsed


def control(key):
    q = {"lower_warm": {"type": "noul", "instructions": "Is the lower half of the image warm orange?",
                        "criteria": {"true": "Lower half is warm orange.", "false": "Lower half is not orange."}}}
    probs = {}
    for name, rgb in (("orange", (235, 140, 60)), ("green", (60, 170, 80))):
        im = Image.new("RGB", (256, 256), (40, 70, 160))
        im.paste(Image.new("RGB", (256, 128), rgb), (0, 128))
        probs[name] = decide(key, data_url(im), q, "Synthetic test image.")[0]["answers"]["lower_warm"]["noul"]
    print(f"control: orange={probs['orange']:.2f} green={probs['green']:.2f}")
    if not (probs["orange"] > 0.8 and probs["green"] < 0.2):
        sys.exit("Control failed: the image is not reaching the model. Stopping.")


def main():
    key = os.environ.get("OPENROUTER_API_KEY") or sys.exit("Set OPENROUTER_API_KEY (doppler run --).")
    control(key)
    rows, total_cost = [], 0.0
    for name, rel, verdict, expect in STAGES:
        body, elapsed = decide(key, data_url(Image.open(PROJECT / rel)), QUESTIONS)
        a, cost = body["answers"], body["usage"].get("cost", 0) or 0
        total_cost += cost
        checks = {q: (a[q]["noul"] > 0.5) == want for q, want in expect.items()}
        rows.append({"stage": name, "human_verdict": verdict, "answers": a,
                     "expected": expect, "agrees": checks, "seconds": round(elapsed, 2), "cost": cost})
        print(f"\n{name}  [{verdict}]")
        print(f"  finished={a['finished']['noul']:.2f}  hard_graphic={a['hard_graphic']['noul']:.2f}  "
              f"finish_level={a['finish_level']['score']:.2f}/4 (conf {a['finish_level'].get('confidence', 0):.2f})")
        top = sorted(a["next_action"]["probabilities"].items(), key=lambda kv: -kv[1])[:3]
        print(f"  next_action={a['next_action']['choice']}  top3={top}")
        if checks:
            print("  agrees with human: " + ", ".join(f"{q}={'yes' if ok else 'NO'}" for q, ok in checks.items()))
        print(f"  {elapsed:.2f}s  ${cost:.6f}")

    agree = [ok for r in rows for ok in r["agrees"].values()]
    levels = [r["answers"]["finish_level"]["score"] for r in rows]
    print(f"\nAgreement with recorded verdicts: {sum(agree)}/{len(agree)}")
    print(f"finish_level by stage order: {[round(x, 2) for x in levels]} "
          f"(rejected stage-04 {levels[1]:.2f} vs accepted final {levels[-1]:.2f})")
    print(f"Total cost ${total_cost:.6f}")

    out = Path(__file__).resolve().parents[1] / "output/luna-critic"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps({"model": MODEL, "max_side": MAX_SIDE, "rows": rows}, indent=2))
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
