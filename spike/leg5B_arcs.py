"""Loop5 legB arc-length attribution crops: up to 12 non-passing "arc length" labels per south sheet
(checks.csv result != pass, plus exceptions.json unmatched L=/(T) labels), red box on the label, blue on
the drawn piece the reader measured (if any). 300 dpi tiled grid, matches leg5_crops.py's tile()/grid().
usage: SHEET=<pdf or blank for presidio> python spike/leg5B_arcs.py <outdir-name-for-print>
"""
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

Z = 300 / 72
PAD = 140


def tile(page, region, line=None):
    x0, y0, x1, y1 = region
    if line:
        lx, ly = zip(*line)
        x0, y0, x1, y1 = min(x0, *lx), min(y0, *ly), max(x1, *lx), max(y1, *ly)
    R = pymupdf.Rect(x0 - PAD, y0 - PAD, x1 + PAD, y1 + PAD) & page.rect
    z = min(Z, 900 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    if line:
        cv2.polylines(im, [np.array([f(x, y) for x, y in line], np.int32)], False, (0, 90, 220), 3)
    cv2.rectangle(im, f(region[0], region[1]), f(region[2], region[3]), (220, 0, 0), 3)
    return im


def grid(tiles, ncol):
    H = max(t.shape[0] for t in tiles)
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, W - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    rows = [np.hstack(tiles[i:i + ncol]) for i in range(0, len(tiles), ncol)]
    W2 = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 0, 0, W2 - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for r in rows]
    return np.vstack(rows)


def main(tag, n=12):
    page = pymupdf.open(PDF)[0]
    exc = json.loads((OUT / "exceptions.json").read_text(encoding="utf-8"))
    arc_exc = [e for e in exc if e.get("kind") == "arc length"]
    rows = list(csv.DictReader(open(OUT / "checks.csv", encoding="utf-8")))
    fails = [r for r in rows if r["check"] == "arc length" and r["result"] == "FAIL"]
    items = []  # (label, region, line)
    seen = set()
    for e in arc_exc[:n]:
        items.append((e["text"], e["region"], e.get("line")))
        seen.add(e["text"])
    for r in fails:
        if len(items) >= n:
            break
        if r["printed"] in seen:
            continue
        m = next((e for e in exc if e.get("text") == r["printed"] and e.get("kind") == "arc length"), None)
        if m:
            items.append((r["printed"], m["region"], m.get("line")))
            seen.add(r["printed"])
    items = items[:n]
    tiles = [tile(page, region, line) for _, region, line in items]
    im = grid(tiles, 4)
    out = OUT / "leg5B_arcs.png"
    cv2.imwrite(str(out), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    print(f"[{tag}] wrote {out} ({im.shape[1]}x{im.shape[0]}), {len(items)} tiles")
    for label, region, line in items:
        print(f"  {label!r:>28}  region {region}  line pts {len(line) if line else 0}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sheet")
