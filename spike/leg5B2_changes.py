"""Loop5 legB2 evidence: 8 arc-length labels whose result changed between leg5A-check and legB2 (a
fake arc fail removed by cause 1's tighter DIST-branch arc-fallback gate, a fillet recovered by cause 2's
radius match, or the one offsetting side effect). Red box = the label, blue = the drawn piece (when the
current state measures one), caption states before -> after.
usage: SHEET=<pdf or blank for presidio> python spike/leg5B2_changes.py <tag> <region_json>
where region_json is a small JSON file: [[caption, [x0,y0,x1,y1], line_or_null], ...] for this sheet.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

Z = 300 / 72
PAD = 130


def tile(page, region, line, caption):
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
    words = caption.split(" ")
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) > 46:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    bar = 22 * len(lines) + 10
    im = cv2.copyMakeBorder(im, 0, bar, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    for i, ln in enumerate(lines):
        cv2.putText(im, ln, (6, im.shape[0] - bar + 18 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def grid(tiles, ncol):
    H = max(t.shape[0] for t in tiles)
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, H - t.shape[0], 0, W - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    rows = [np.hstack(tiles[i:i + ncol]) for i in range(0, len(tiles), ncol)]
    W2 = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 0, 0, 0, W2 - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for r in rows]
    return np.vstack(rows)


def main(tag, items_path):
    page = pymupdf.open(PDF)[0]
    items = json.loads(Path(items_path).read_text(encoding="utf-8"))
    tiles = [tile(page, region, line, caption) for caption, region, line in items]
    return tiles


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
