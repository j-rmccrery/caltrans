"""Loop6 leg B gate evidence.
1. leg6B_leaders.png: the 7 busy-vertex bearing crops named in leg5A_bearings.md, before (pre-fix,
   /tmp/before_labels_*.json) and after (current spike/out/*/labels.json) side by side. Red = label,
   blue = the line checks.py measured.
2. leg6B_passes.png: labels newly passing after the at_tip busy-vertex fix (from the before/after
   labels.json pass-set diff).
Ad hoc, not part of the pipeline.
usage: python spike/leg6B_crops.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
SCRATCH = Path(r"C:\Users\johnr\AppData\Local\Temp\claude\C--Users-johnr-projects-caltrans\15afd8cb-a5d8-49e1-b455-d593a7ee390b\scratchpad")
Z = 300 / 72
PAD = 90

SHEETS = {
    "presidio": (None, "presidio"),
    "r10434_1": (ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf", "r10434_1"),
    "r10434_3": (ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf", "r10434_3"),
}

# the 7 "leader to a different line" crops from leg5A_bearings.md, one per (sheet, printed text)
BUSY = [
    ("presidio", "N67°37'21\"W"),
    ("presidio", "N8°43'35\"W"),
    ("presidio", "S67°59'11\"E"),
    ("r10434_1", "S66°02'28\"W"),
    ("r10434_1", "N31°17'48\"E"),
    ("r10434_1", "N63°37'29\"W"),
    ("r10434_3", "S9°39'21\"E"),
]


def find(labels, text):
    return next((la for la in labels if la["kind"] == "bearing" and la["printed"] == text), None)


def tile(page, la, caption, color=(0, 90, 220)):
    region = la["region"] if la else None
    pts = la["line"] if la else []
    xs = ([region[0], region[2]] if region else []) + [p[0] for p in pts]
    ys = ([region[1], region[3]] if region else []) + [p[1] for p in pts]
    if not xs:
        return np.full((200, 260, 3), 255, np.uint8)
    R = pymupdf.Rect(min(xs) - PAD, min(ys) - PAD, max(xs) + PAD, max(ys) + PAD) & page.rect
    z = min(Z, 700 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    if pts:
        cv2.polylines(im, [np.array([f(x, y) for x, y in pts], np.int32)], False, color, 4)
    if region:
        cv2.rectangle(im, f(region[0], region[1]), f(region[2], region[3]), (0, 0, 220), 3)
    im = cv2.copyMakeBorder(im, 0, 24, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, caption, (8, im.shape[0] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def hstack_pad(tiles):
    h = max(t.shape[0] for t in tiles)
    out = []
    for t in tiles:
        if t.shape[0] < h:
            t = cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        out.append(t)
    return np.hstack(out)


def vstack_pad(rows):
    w = max(r.shape[1] for r in rows)
    out = []
    for r in rows:
        if r.shape[1] < w:
            r = cv2.copyMakeBorder(r, 0, 0, 0, w - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))
        out.append(r)
    return np.vstack(out)


def main():
    pages = {}

    def page_for(sheet):
        if sheet not in pages:
            pdf, _ = SHEETS[sheet]
            pdf = pdf or (ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf")
            pages[sheet] = pymupdf.open(pdf)[0]
        return pages[sheet]

    rows = []
    for sheet, text in BUSY:
        before = json.loads((SCRATCH / f"before_labels_{sheet}.json").read_text(encoding="utf-8"))
        page = page_for(sheet)
        lb = find(before, text)
        after_path = (ROOT / "spike" / "out" / "labels.json") if sheet == "presidio" else (ROOT / "spike" / "out" / Path(str(SHEETS[sheet][0])).stem / "labels.json")
        after_data = json.loads(after_path.read_text(encoding="utf-8"))
        la = find(after_data, text)
        t_before = tile(page, lb, f"{sheet} {text} BEFORE", color=(0, 0, 220))
        t_after = tile(page, la, f"{sheet} {text} AFTER", color=(220, 90, 0))
        rows.append(hstack_pad([t_before, t_after]))
    grid = vstack_pad(rows)
    out = ROOT / "spike" / "out" / "leg6B_leaders.png"
    cv2.imwrite(str(out), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    print("wrote", out, grid.shape)


if __name__ == "__main__":
    main()
