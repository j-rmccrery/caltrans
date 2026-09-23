"""Leg 4 gate evidence: 12 random PASSING distance labels on the default sheet, label box (red) and
the measured line (blue) both drawn, 3 per row, so the orchestrator can confirm none passes on a wrong
line. Reads spike/out/labels.json (checks.py; each entry now carries its label "region").
usage: python spike/leg4_crops.py
"""
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

Z = 3
PAD = 20


def tile(page, region, line):
    x0, y0, x1, y1 = region
    if line:  # widen so the measured line is in view (capped: a long line does not fit)
        lx, ly = zip(*line)
        x0, y0, x1, y1 = max(x0 - 90, min(lx)), max(y0 - 60, min(ly)), min(x1 + 90, max(lx)), min(y1 + 60, max(ly))
        x0, y0, x1, y1 = min(x0, region[0]), min(y0, region[1]), max(x1, region[2]), max(y1, region[3])
    R = pymupdf.Rect(x0 - PAD, y0 - PAD, x1 + PAD, y1 + PAD) & page.rect
    z = min(Z, 380 / max(R.width, R.height, 1))  # tiles stay a comparable size in the 3-per-row grid
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    if line:
        cv2.polylines(im, [np.array([f(x, y) for x, y in line], np.int32)], False, (0, 90, 220), 3)
    cv2.rectangle(im, f(region[0], region[1]), f(region[2], region[3]), (220, 0, 0), 2)
    return im


def main():
    page = pymupdf.open(PDF)[0]
    labels = json.loads((OUT / "labels.json").read_text(encoding="utf-8"))
    cands = [l for l in labels if l["kind"] == "distance" and l["ok"] and l.get("region")]
    print(f"{len(cands)} passing distance labels with a region on this sheet")
    random.seed(4)  # reproducible pick
    picks = random.sample(cands, min(12, len(cands)))
    tiles = [tile(page, l["region"], l["line"]) for l in picks]
    H = max(t.shape[0] for t in tiles)
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, W - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    rows = [np.hstack(tiles[i:i + 3]) for i in range(0, 12, 3)]
    grid = np.vstack(rows)
    cv2.imwrite(str(OUT / "leg4_crops.png"), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    print(f"wrote {OUT / 'leg4_crops.png'} ({grid.shape[1]}x{grid.shape[0]})")
    for l in picks:
        print(f"  {l['printed']:>10}  drawn line has {len(l['line'])} pts  region {l['region']}")


if __name__ == "__main__":
    main()
