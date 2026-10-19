# /// script
# dependencies = ["httpx", "pillow", "numpy"]
# ///
"""Labelled evaluation of the shipped Luna visual checks (src/visual-checks.ts).

Uses the same question file (src/visual-check-questions.json) and request shapes:
  pass check   BEFORE/AFTER with one noul per failure type, then 3x3 location on
               AFTER for flagged types (threshold from the question file)
  progress     PREVIOUS/CURRENT with one score per failing check

Labelled cases built from crops of finished paintings:
  positives    clean -> clean + one injected failure (6 types)
  negatives    clean -> identical; clean -> ordinary brushwork;
               failure already in BEFORE and unchanged in AFTER (must not count)
  progress     defect -> unchanged / half-corrected / corrected (scores must rise)

Run from the repo root (OpenRouter only):
    doppler run -- uv run krita-creative-agent/scripts/evaluate-visual-checks.py
"""
import importlib.util, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location("defects", HERE / "evaluate-luna-defects.py")
defects = importlib.util.module_from_spec(spec); spec.loader.exec_module(defects)
Q = json.loads((HERE.parent / "src/visual-check-questions.json").read_text())
FAILURES = Q["pass"]["failures"]; THRESHOLD = Q["pass"]["threshold"]
# Cells where each injection is visible (see inject() in evaluate-luna-defects.py).
ACCEPT = {"splice": {"middle_left", "center", "middle_right", "bottom_left", "bottom_center", "bottom_right"},
          "duplicate": {"middle_left", "center", "middle_right", "bottom_left", "bottom_center", "bottom_right"},
          "flat_block": {"center", "middle_left", "middle_right"},
          "stripes": {"center", "bottom_center", "bottom_left", "bottom_right"},
          "hard_graphic": None, "ellipses": None}


def inject(im, kind, rng):
    if kind != "hard_graphic":
        return defects.inject(im, kind, rng)
    # Poster/vector look: few flat colour levels with hard edges over the whole crop.
    return im.filter(ImageFilter.ModeFilter(9)).quantize(6).convert("RGB")


def brushwork(im, rng):
    """Ordinary soft painted marks in local colours: a pass that should not be flagged."""
    out = im.copy(); d = ImageDraw.Draw(out, "RGBA"); a = np.asarray(im)
    for _ in range(60):
        x, y = rng.integers(0, im.width), rng.integers(0, im.height)
        c = tuple(int(v) for v in a[y, x]) + (90,)
        d.ellipse((x - 10, y - 4, x + 10, y + 4), fill=c)
    return out.filter(ImageFilter.GaussianBlur(0.8))


def parts(*items):
    return [{"type": "text", "text": i} if isinstance(i, str) else {"type": "image_url", "image_url": {"url": defects.data_url(i)}} for i in items]


def decide(key, state, questions):
    import httpx
    for attempt in range(3):
        r = httpx.post(defects.URL, headers={"Authorization": f"Bearer {key}"}, timeout=60,
                       json={"model": defects.MODEL, "state": state, "questions": questions})
        if r.status_code == 200:
            return r.json()
        if r.status_code == 502 and "refused to answer" in r.text:
            return {"refused": True}
        if r.status_code not in (429, 500, 502, 503, 524, 529):
            sys.exit(f"HTTP {r.status_code}")  # body omitted: upstream errors can echo key fragments
        time.sleep(2 * (attempt + 1))
    sys.exit(f"HTTP {r.status_code} after retries")


def pass_check(key, before, after):
    questions = {k: {"type": "noul", "instructions": v["instructions"], "criteria": v["criteria"]} for k, v in FAILURES.items()}
    first = decide(key, parts("BEFORE (canvas before this paint pass):", before, "AFTER (canvas after this paint pass):", after), questions)
    if first.get("refused"):
        return {"refused": True, "cost": 0}
    p = {k: first["answers"][k]["noul"] for k in FAILURES}
    flagged = [k for k in FAILURES if p[k] >= THRESHOLD]
    locations, cost = {}, first["usage"].get("cost", 0) or 0
    if flagged:
        loc = Q["pass"]["location"]
        second = decide(key, parts("AFTER (canvas after this paint pass):", after),
                        {k: {"type": "choice", "instructions": loc["instructions"].replace("{label}", FAILURES[k]["label"]), "criteria": loc["cells"]} for k in flagged})
        if not second.get("refused"):
            locations = {k: second["answers"][k]["choice"] for k in flagged}
            cost += second["usage"].get("cost", 0) or 0
    return {"p": p, "flagged": flagged, "locations": locations, "cost": cost}


def progress_check(key, previous, current, text):
    pr = Q["progress"]
    reply = decide(key, parts("PREVIOUS (canvas at the previous review):", previous, "CURRENT (canvas now):", current),
                   {"check_0": {"type": "score", "instructions": pr["instructions"].replace("{check}", text), "criteria": pr["scale"]}})
    return None if reply.get("refused") else reply["answers"]["check_0"]["score"]


def main():
    key = os.environ.get("OPENROUTER_API_KEY") or sys.exit("Set OPENROUTER_API_KEY (doppler run --). No requests were made.")
    defects.control(key)
    out = ROOT / f"output/visual-checks/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out.mkdir(parents=True)
    rng = np.random.default_rng(11)
    cases, progress, cost = [], [], 0.0
    for b, base in enumerate(defects.BASES):
        for c, anchor in enumerate(defects.CROPS):
            clean = defects.crop(base, anchor); tag = f"b{b}c{c}"
            clean.save(out / f"{tag}-clean.jpg", quality=90)
            labelled = [("unchanged", clean, clean, None), ("brushwork", clean, brushwork(clean, rng), None)]
            striped = inject(clean, "stripes", rng)
            labelled.append(("preexisting_stripes", striped, striped, None))
            for kind in FAILURES:
                after = inject(clean, kind, rng); after.save(out / f"{tag}-{kind}.jpg", quality=90)
                labelled.append((kind, clean, after, kind))
            for name, before, after, expect in labelled:
                r = pass_check(key, before, after); cost += r["cost"]
                cases.append({"case": f"{tag}-{name}", "kind": name, "expect": expect, **{k: v for k, v in r.items() if k != "cost"}})
            # Progress: a stripe defect left unchanged, half corrected, corrected.
            half = Image.blend(striped, clean, 0.5)
            text = "The area has no mechanical stripe pattern; it reads as painted."
            scores = {lvl: progress_check(key, striped, img, text) for lvl, img in (("unchanged", striped), ("half", half), ("fixed", clean))}
            progress.append({"case": tag, **scores})

    pos = [x for x in cases if x["expect"]]; neg = [x for x in cases if not x["expect"]]
    print(f"\n{len(cases)} pass checks + {len(progress) * 3} progress checks, ${cost:.4f} (pass checks)\n")
    print(f"{'failure':<14}{'detected':>10}{'located':>10}")
    summary = {"by_type": {}}
    for kind in FAILURES:
        rows = [x for x in pos if x["kind"] == kind and not x.get("refused")]
        det = [x for x in rows if kind in x["flagged"]]
        acc = ACCEPT[kind]
        loc = f"{sum(x['locations'].get(kind) in acc for x in det)}/{len(det)}" if acc else "n/a"
        summary["by_type"][kind] = {"detected": len(det), "cases": len(rows), "located": loc}
        print(f"{kind:<14}{len(det):>4}/{len(rows):<5}{loc:>10}")
    print("\nfalse flags (any type) on negatives:")
    for kind in ("unchanged", "brushwork", "preexisting_stripes"):
        rows = [x for x in neg if x["kind"] == kind and not x.get("refused")]
        flagged = [x for x in rows if x["flagged"]]
        summary[kind] = {"flagged": len(flagged), "cases": len(rows), "types": sorted({t for x in flagged for t in x["flagged"]})}
        print(f"  {kind:<20}{len(flagged)}/{len(rows)}  {summary[kind]['types'] or ''}")
    ordered = [p for p in progress if None not in (p["unchanged"], p["half"], p["fixed"])]
    mono = sum(p["unchanged"] < p["half"] < p["fixed"] for p in ordered)
    mean = {lvl: float(np.mean([p[lvl] for p in ordered])) for lvl in ("unchanged", "half", "fixed")} if ordered else {}
    summary["progress"] = {"strictly_ordered": mono, "cases": len(ordered), "mean": mean}
    print(f"\nprogress ordering unchanged < half < fixed: {mono}/{len(ordered)}; mean scores {({k: round(v, 2) for k, v in mean.items()})}")
    refused = sum(1 for x in cases if x.get("refused"))
    if refused: print(f"refused pass checks: {refused}")
    (out / "results.json").write_text(json.dumps({"model": defects.MODEL, "threshold": THRESHOLD, "question_version": Q["version"],
                                                  "summary": summary, "cases": cases, "progress": progress, "cost": cost}, indent=2))
    print(f"\nSaved {out.relative_to(ROOT)}/ (images + results.json)")


if __name__ == "__main__":
    main()
