"""Leg B step 6 gate evidence: every passing arc-length label on presidio (labels.json, kind "arc", ok
true), label box (red) and the measured arc (blue), 3 per row -- same crop machinery as leg4_crops.py,
so the orchestrator can confirm attempt 1's widened arc-match radius (5 glyph heights -> 160 pt) put each
label on the right arc, not a nearby wrong one.
usage: python spike/legB_arcs.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
from leg4_crops import tile  # noqa: E402


def main():
    page = pymupdf.open(PDF)[0]
    labels = json.loads((OUT / "labels.json").read_text(encoding="utf-8"))
    cands = [l for l in labels if l["kind"] == "arc" and l["ok"] and l.get("region")]
    print(f"{len(cands)} passing arc-length labels with a region on this sheet")
    n = len(cands)
    rows = (n + 2) // 3
    tiles = [tile(page, l["region"], l["line"]) for l in cands]
    H = max(t.shape[0] for t in tiles)
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, W - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    blank = np.full((H, W, 3), 255, np.uint8)
    tiles += [blank] * (rows * 3 - n)
    grid = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, rows * 3, 3)])
    cv2.imwrite(str(OUT / "legB_arcs.png"), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    print(f"wrote {OUT / 'legB_arcs.png'} ({grid.shape[1]}x{grid.shape[0]})")
    for l in cands:
        print(f"  {l['printed']:>10}  drawn arc has {len(l['line'])} pts  region {l['region']}")


if __name__ == "__main__":
    main()
