"""Leg 5 exception-page evidence: crops of the 8 exceptions plus 4 unassociated-but-parsing labels
on R-10741.2, and (after the fix) 8 newly-passing labels. Red box on the label, blue on the line/arc
the reader measured (if any). 300 dpi, ~140pt pad around the label (widened to keep a long line in view).
usage: python spike/leg5_crops.py {misses|passes}
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

Z = 300 / 72  # 300 dpi
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


def main(mode):
    page = pymupdf.open(PDF)[0]
    items = []  # (label, region, line)
    if mode == "misses":
        exc = json.loads((OUT / "exceptions.json").read_text(encoding="utf-8"))
        for e in exc:
            items.append((e["text"], e["region"], e.get("line")))
        extra = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))  # [[label, region], ...]
        for label, region in extra:
            items.append((label, region, None))
        out = OUT / "leg5_misses.png"
        ncol = 4
    else:
        picks = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))  # [[label, region, line], ...]
        items = [(p[0], p[1], p[2]) for p in picks]
        out = OUT / "leg5_passes.png"
        ncol = 4
    tiles = [tile(page, region, line) for _, region, line in items]
    im = grid(tiles, ncol)
    cv2.imwrite(str(out), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    print(f"wrote {out} ({im.shape[1]}x{im.shape[0]}), {len(items)} tiles")
    for label, region, line in items:
        print(f"  {label!r:>20}  region {region}  line pts {len(line) if line else 0}")


if __name__ == "__main__":
    main(sys.argv[1])
