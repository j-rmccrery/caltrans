"""Loop6 legF evidence: every fired not-to-scale detail inset (circle in green) with its queued labels
(red boxes) across the two sheets with a real inset, one tile per inset.
usage: python spike/leg6F_crops.py  -> spike/out/leg6F_insets.png
"""
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))

Z = 3.0
PAD = 40
SHEETS = {
    "r10741_2": Path("Sample Data/d4/r_10741_002_2017-02-10.pdf"),
    "r10434_1": Path("Sample Data/d4/r_10434_001_2020-09-16.pdf"),
}


def tiles_for(pdf):
    os.environ["SHEET"] = str(pdf)
    for m in list(sys.modules):
        if m in ("georef", "checks"):
            del sys.modules[m]
    import georef
    import checks
    page = pymupdf.open(str(georef.PDF))[0]
    blocks = json.loads(georef.READS.read_text(encoding="utf-8")) + georef.real_text_blocks(page)
    checks.set_decimals(blocks)
    gh_med = float(np.median([b["glyph_h"] for b in blocks]))
    regions, report = checks.detail_insets(blocks, page, gh_med)
    out = []
    for c in regions:
        cx, cy, r, gh = c["cx"], c["cy"], c["r"], c["gh"]
        R = pymupdf.Rect(cx - r - PAD, cy - r - PAD, cx + r + PAD, cy + r + PAD) & page.rect
        pix = page.get_pixmap(matrix=pymupdf.Matrix(Z, Z), clip=R, alpha=False)
        im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
        f = lambda x, y: (int((x - R.x0) * Z), int((y - R.y0) * Z))
        cv2.circle(im, f(cx, cy), int(r * Z), (0, 200, 0), 3)
        for b in blocks:
            if ((b["cx"] - cx) ** 2 + (b["cy"] - cy) ** 2) ** 0.5 < r + 2 * gh:
                x0, y0 = f(b["cx"] - b["w"] / 2 - 3, b["cy"] - b["h"] / 2 - 3)
                x1, y1 = f(b["cx"] + b["w"] / 2 + 3, b["cy"] + b["h"] / 2 + 3)
                cv2.rectangle(im, (x0, y0), (x1, y1), (0, 0, 220), 2)
        label = f"{pdf.stem}  r={r:.1f}pt ({r / gh:.1f} gh)  cov ok  r={r:.0f}"
        bar = np.full((36, im.shape[1], 3), 255, np.uint8)
        cv2.putText(bar, f"{pdf.stem}  radius {r:.0f}pt ({r / gh:.1f} gh)", (8, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
        out.append(np.vstack([bar, im]))
    return out


def main():
    tiles = []
    for name, pdf in SHEETS.items():
        tiles += tiles_for(pdf)
    if not tiles:
        print("no fired insets found")
        return
    h = max(t.shape[0] for t in tiles)
    w = max(t.shape[1] for t in tiles)
    padded = []
    for t in tiles:
        canvas = np.full((h, w, 3), 255, np.uint8)
        canvas[: t.shape[0], : t.shape[1]] = t
        padded.append(canvas)
    cols = min(3, len(padded))
    rows = -(-len(padded) // cols)
    grid = np.full((rows * h, cols * w, 3), 255, np.uint8)
    for i, t in enumerate(padded):
        r, c = divmod(i, cols)
        grid[r * h : r * h + h, c * w : c * w + w] = t
    out_path = Path(__file__).parent / "out" / "leg6F_insets.png"
    cv2.imwrite(str(out_path), grid)
    print(f"{len(tiles)} fired insets -> {out_path}")


if __name__ == "__main__":
    main()
