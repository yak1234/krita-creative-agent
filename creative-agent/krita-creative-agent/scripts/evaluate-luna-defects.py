# /// script
# dependencies = ["httpx", "pillow", "numpy"]
# ///
"""Can GPT-6 Luna Decisions detect the failure modes our painting runs produced?

Paired, labelled test: crops of finished paintings are judged clean and with one
injected defect taken from recorded failures (the lower-house, contour and stage-one studies of September 2026):

  splice      hard horizontal join from rectangle-to-rectangle reference transfer
  duplicate   repeated architecture/content band from a misaligned transfer
  flat_block  flat speckled rectangular block from toolbox reconstruction
  stripes     regular stripe/ladder marks (porch stripes, texture ladders)
  ellipses    generic overlapping hard ellipses instead of drawn forms

Run from the repo root:
    doppler run -- uv run krita-creative-agent/scripts/evaluate-luna-defects.py

Generated images and per-image answers are saved under
krita-creative-agent/output/luna-defects/<timestamp>/ for inspection.
"""
import base64, io, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from project_dir import project_dir
import httpx
import numpy as np
from PIL import Image, ImageDraw

URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "openai/gpt-6-luna-decisions"
SIDE = 512
ROOT = project_dir()          # the artwork folder the images below live in
BASES = ["projects/moonlit-canal/faces-and-shawl-finished.png", "warm_color_fields.png",
         "memileo_portrait_practice.png", "christmas_full_scene.png"]
CROPS = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)]  # relative crop anchors per base
DEFECTS = ["splice", "duplicate", "flat_block", "stripes", "ellipses"]

CONTEXT = ("A crop of a digital oil painting made in Krita. Judge only what is "
           "visible in the image.")
QUESTIONS = {
    "splice": {"type": "noul",
               "instructions": "Is there a hard, straight horizontal seam where the image above and below do not line up, as if two pictures were joined?",
               "criteria": {"true": "A visible straight join with misaligned content across it.",
                            "false": "Content continues naturally; no such join."}},
    "duplicate": {"type": "noul",
                  "instructions": "Is a band of the image repeated, so the same content appears twice, stacked?",
                  "criteria": {"true": "The same shapes or details repeat in a stacked copy.",
                               "false": "No repeated band of content."}},
    "flat_block": {"type": "noul",
                   "instructions": "Is there a flat, rectangular block of nearly uniform or speckled colour that does not belong to the painted forms?",
                   "criteria": {"true": "A rectangular patch of flat or noisy colour breaks the painting.",
                                "false": "No such rectangular patch."}},
    "stripes": {"type": "noul",
                "instructions": "Are there regular, evenly spaced parallel stripes that look mechanical rather than painted?",
                "criteria": {"true": "Mechanical, evenly spaced stripes or a ladder pattern.",
                             "false": "No mechanical stripe pattern."}},
    "ellipses": {"type": "noul",
                 "instructions": "Are there flat, hard-edged ellipses or circles pasted over the painting instead of painted forms?",
                 "criteria": {"true": "Flat hard-edged ellipse shapes sit on top of the painting.",
                              "false": "No pasted ellipse shapes."}},
    "reject": {"type": "noul",
               "instructions": "Would a professional painter reject this crop because of a visible artifact or construction error?",
               "criteria": {"true": "A visible artifact or error makes it unacceptable.",
                            "false": "Acceptable; no artifact demands correction."}},
}


def crop(path, anchor):
    im = Image.open(ROOT / path).convert("RGB")
    if min(im.size) < SIDE:
        im = im.resize((max(SIDE, round(im.width * SIDE / min(im.size))),
                        max(SIDE, round(im.height * SIDE / min(im.size)))))
    x = round((im.width - SIDE) * anchor[0]); y = round((im.height - SIDE) * anchor[1])
    return im.crop((x, y, x + SIDE, y + SIDE))


def inject(im, kind, rng):
    a = np.asarray(im).astype(np.float32)
    h, w, _ = a.shape
    if kind == "splice":
        y = int(h * 0.55)
        a[y:] = np.roll(a[y:], int(w * 0.12), axis=1) * 1.12
    elif kind == "duplicate":
        band = a[int(h * 0.2):int(h * 0.45)].copy()
        a[int(h * 0.5):int(h * 0.5) + band.shape[0]] = band
    elif kind == "flat_block":
        y0, x0 = int(h * 0.35), int(w * 0.3)
        y1, x1 = y0 + int(h * 0.3), x0 + int(w * 0.35)
        mean = a[y0:y1, x0:x1].reshape(-1, 3).mean(0)
        a[y0:y1, x0:x1] = mean + rng.normal(0, 10, (y1 - y0, x1 - x0, 1))
    elif kind == "stripes":
        y0, x0 = int(h * 0.55), int(w * 0.25)
        y1, x1 = y0 + int(h * 0.3), x0 + int(w * 0.5)
        mean = a[y0:y1, x0:x1].reshape(-1, 3).mean(0)
        cols = np.arange(x1 - x0)
        stripe = np.where((cols // 10) % 2 == 0, 70.0, -50.0)[None, :, None]
        a[y0:y1, x0:x1] = 0.15 * a[y0:y1, x0:x1] + 0.85 * (mean + stripe)
    elif kind == "ellipses":
        out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(out)
        for _ in range(4):
            cx, cy = rng.integers(w // 5, 4 * w // 5), rng.integers(h // 5, 4 * h // 5)
            rx, ry = rng.integers(w // 12, w // 6), rng.integers(h // 12, h // 6)
            colour = tuple(int(c) for c in np.asarray(im)[rng.integers(0, h), rng.integers(0, w)])
            d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=colour)
        return out
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def data_url(im):
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def decide(key, im, questions, text=CONTEXT):
    """Returns the reply body plus a "refused" list of question names.

    OpenAI may decline a single question; OpenRouter then fails the whole request
    with 502 'refused to answer question "<name>"'. Drop that question and ask
    the rest again, so one refusal does not discard the other answers.
    """
    # Only the chat-style image_url part is seen by the model on OpenRouter.
    state = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": data_url(im)}}]
    questions, refused, attempt = dict(questions), [], 0
    while attempt < 3:
        r = httpx.post(URL, headers={"Authorization": f"Bearer {key}"}, timeout=60,
                       json={"model": MODEL, "state": state, "questions": questions})
        if r.status_code == 200:
            body = r.json()
            body["refused"] = refused + [q for q, a in body["answers"].items() if a.get("type") == "refusal"]
            return body
        m = re.search(r'refused to answer question \\?"([^"\\]+)', r.text)
        if r.status_code == 502 and m and m.group(1) in questions and len(questions) > 1:
            refused.append(m.group(1))
            del questions[m.group(1)]
            continue
        if r.status_code not in (429, 500, 502, 503, 524, 529):
            break
        attempt += 1
        time.sleep(2 * attempt)
    sys.exit(f"HTTP {r.status_code}: {r.text[:300]}")


def control(key):
    q = {"lower_warm": {"type": "noul", "instructions": "Is the lower half of the image warm orange?",
                        "criteria": {"true": "Lower half is warm orange.", "false": "Lower half is not orange."}}}
    probs = {}
    for name, rgb in (("orange", (235, 140, 60)), ("green", (60, 170, 80))):
        im = Image.new("RGB", (256, 256), (40, 70, 160))
        im.paste(Image.new("RGB", (256, 128), rgb), (0, 128))
        probs[name] = decide(key, im, q, "Synthetic test image.")["answers"]["lower_warm"]["noul"]
    print(f"control: orange={probs['orange']:.2f} green={probs['green']:.2f}")
    if not (probs["orange"] > 0.8 and probs["green"] < 0.2):
        sys.exit("Control failed: the image is not reaching the model. Stopping.")


def main():
    key = os.environ.get("OPENROUTER_API_KEY") or sys.exit("Set OPENROUTER_API_KEY (doppler run --).")
    control(key)
    out = Path(__file__).resolve().parents[1] / f"output/luna-defects/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    rng = np.random.default_rng(7)
    items = []
    for b, base in enumerate(BASES):
        for c, anchor in enumerate(CROPS):
            clean = crop(base, anchor)
            for kind in [None] + DEFECTS:
                im = clean if kind is None else inject(clean, kind, rng)
                name = f"b{b}c{c}-{kind or 'clean'}"
                im.save(out / f"{name}.jpg", quality=90)
                items.append({"name": name, "base": base, "crop": c, "defect": kind, "image": im})

    t0 = time.perf_counter()
    with ThreadPoolExecutor(1) as pool:
        replies = list(pool.map(lambda it: decide(key, it["image"], QUESTIONS), items))
    elapsed = time.perf_counter() - t0
    cost = 0.0
    for it, rep in zip(items, replies):
        it["p"] = {q: a["noul"] for q, a in rep["answers"].items() if a.get("type") == "noul"}
        it["refused"] = rep["refused"]
        cost += rep["usage"].get("cost", 0) or 0
        del it["image"]

    def mean(values):
        values = [v for v in values if v is not None]
        return float(np.mean(values)) if values else float("nan")

    def above(item, q):
        return None if item["p"].get(q) is None else item["p"][q] > 0.5

    clean = {(i["base"], i["crop"]): i for i in items if i["defect"] is None}
    refusals = {q: sum(q in i["refused"] for i in items) for q in QUESTIONS}
    print(f"\n{len(items)} images ({len(clean)} clean twins), {elapsed:.1f}s wall, ${cost:.5f}")
    print("refused questions: " + (", ".join(f"{q}={n}" for q, n in refusals.items() if n) or "none") + "\n")
    print(f"{'defect':<11}{'detect':>8}{'false+':>8}{'mean p inj':>12}{'mean p clean':>14}{'paired win':>12}")
    summary = {}
    for kind in DEFECTS:
        inj = [i for i in items if i["defect"] == kind]
        det = mean([above(i, kind) for i in inj])
        fp = mean([above(c, kind) for c in clean.values()])
        pairs = [(i["p"].get(kind), clean[(i["base"], i["crop"])]["p"].get(kind)) for i in inj]
        wins = mean([pi > pc for pi, pc in pairs if pi is not None and pc is not None])
        p_inj = mean([i["p"].get(kind) for i in inj]); p_clean = mean([c["p"].get(kind) for c in clean.values()])
        summary[kind] = {"detect": det, "false_pos": fp, "paired_win": wins, "p_inj": p_inj, "p_clean": p_clean}
        print(f"{kind:<11}{det:>8.0%}{fp:>8.0%}{p_inj:>12.2f}{p_clean:>14.2f}{wins:>12.0%}")
    rej_inj = mean([above(i, "reject") for i in items if i["defect"]])
    rej_clean = mean([above(c, "reject") for c in clean.values()])
    print(f"\nreject question: flags {rej_inj:.0%} of defective crops, {rej_clean:.0%} of clean crops "
          f"(answered {sum('reject' in i['p'] for i in items)}/{len(items)})")

    # Cross-talk: does each injected defect light up the right question or a generic one?
    print("\nhighest-probability defect question per injected defect (count):")
    for kind in DEFECTS:
        tops = [max((q for q in DEFECTS if q in i["p"]), key=lambda q: i["p"][q])
                for i in items if i["defect"] == kind and any(q in i["p"] for q in DEFECTS)]
        print(f"  {kind:<11}" + ", ".join(f"{q}={tops.count(q)}" for q in DEFECTS if tops.count(q)))

    (out / "results.json").write_text(json.dumps(
        {"model": MODEL, "side": SIDE, "bases": BASES, "items": items,
         "summary": summary, "reject": {"defective": rej_inj, "clean": rej_clean},
         "refusals": refusals, "cost": cost},
        indent=2, default=float))
    print(f"\nSaved {out}/ (images + results.json)")


if __name__ == "__main__":
    main()
