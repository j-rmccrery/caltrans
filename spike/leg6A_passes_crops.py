"""Loop6 legA gate evidence: crops of the newly-passing standalone L=/(T) labels (the fitted-run-sum
rule added to checks.py's build_pool/standalone-L branch). Red box = the label; blue = every piece the
rule summed to match it (each its own drawn length in ft).
usage: SHEET=<pdf> python spike/leg6A_passes_crops.py <out_dir>
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, READS, real_text_blocks  # noqa: E402
import checks  # noqa: E402

Z = 300 / 72
PAD = 120

TARGETS = {
    "r_10434_002_2020-09-16.pdf": [  # presidio
        ("L=573.93'(T)", [1556, 609, 1618, 625]),
        ("L=60.39'", [1396, 809, 1436, 823]),
        ("L=184.70'(T)", [1779, 807, 1839, 821]),
    ],
    "r_10434_003_2020-09-16.pdf": [
        ("L=577.57'", [597, 628, 647, 643]),
        ("L=129.96'", [1629, 580, 1670, 595]),
        ("L=124.05'", [1686, 251, 1743, 273]),
    ],
}


def tile(page, region, pieces, label_text, out_path):
    xs = [region[0], region[2]] + [p[0] for pts, _ in pieces for p in pts]
    ys = [region[1], region[3]] + [p[1] for pts, _ in pieces for p in pts]
    R = pymupdf.Rect(min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD) & page.rect
    z = min(Z, 1100 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    for pts, ft in pieces:
        cv2.polylines(im, [np.array([f(x, y) for x, y in pts], np.int32)], False, (0, 90, 220), 4)
        mx, my = pts[len(pts) // 2]
        cv2.putText(im, f"{ft:.2f}'", f(mx, my), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 90, 220), 2, cv2.LINE_AA)
    cv2.rectangle(im, f(region[0], region[1]), f(region[2], region[3]), (220, 0, 0), 3)
    im = cv2.copyMakeBorder(im, 0, 26, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, label_text, (10, im.shape[0] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))


def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    checks.set_decimals(blocks)
    pool = checks.build_pool(page, blocks)
    arcs, tips = pool["arcs"], pool["tips"]
    targets = TARGETS.get(PDF.name)
    if not targets:
        print(f"no targets for {PDF.name}"); return
    for i, (text, region) in enumerate(targets):
        m = checks.LEN.match(text)
        want = float(m[1])
        c = np.array([(region[0] + region[2]) / 2, (region[1] + region[3]) / 2])
        # re-run the same seed/window search build_pool's caller uses, to recover which pieces passed
        led, arc = False, None
        for bi, b in enumerate(blocks):
            if b["text"].replace(" ", "") == text:
                led = bi in tips
        seed_at = tips[bi][0] if led and bi in tips else c
        wide = sorted((x for x in arcs if checks.poly_dist(seed_at, x["pts"]) < 160.0 and "seq" in x),
                      key=lambda x: checks.poly_dist(seed_at, x["pts"]))
        tol = checks.DIST_TOL + 0.0005 * want
        group_arc = None
        for seed in wide[:20]:
            run = sorted((x for x in arcs if x.get("parent") == seed["parent"] and "seq" in x), key=lambda x: x["seq"])
            k = next(j for j, x in enumerate(run) if x is seed)
            hits = [(p, q) for p in range(0, k + 1) for q in range(k, len(run))
                    if abs(sum(x["len_pt"] for x in run[p:q + 1]) * scale - want) <= tol]
            if len(hits) == 1 and hits[0] != (k, k):
                p, q = hits[0]
                group_arc = run[p:q + 1]
                break
        if group_arc is None:
            print(f"{text}: no group found (unexpected)"); continue
        pieces = [(x["pts"].tolist(), x["len_pt"] * scale) for x in group_arc]
        out_path = out_dir / f"{PDF.stem}_{i}.png"
        tile(page, region, pieces, f"{PDF.stem}: {text} = " + " + ".join(f"{ft:.2f}" for _, ft in pieces), out_path)
        print(f"{PDF.stem} {text}: run of {len(pieces)} -> {[round(ft,2) for _, ft in pieces]}")


if __name__ == "__main__":
    main()
