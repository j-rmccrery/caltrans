"""Loop18 leg 5, lever 1 gate evidence: the three named misfit cases from loop18-4's own gate note.
1. R-10434.1 R=245.0' L=289.24': refused -- the drawn curve is cut by the sheet's own MATCHLINE, only
   243.01 of its 289.24 ft printed length drawn on THIS sheet (the rest continues onto R-10434.2).
2. R-10434.3 C26: refused -- the drawn curve is cut by a "SEE DETAIL A" callout (cross-sheet reference
   to sheet 46825-5, loop18 leg 6 scope), only 244.10 of its 328.02 ft printed length drawn here.
3. Presidio "L=184.70'(T) + L=130.56'": accepted (fixed) -- traverse.py's build_edges pass 2 used to
   merge these two DIFFERENT, adjacent curves into one edge (sharing an endpoint, an ordinary PCC/PRC
   join) just because their drawn ends coincide; merge_endpoint_pairs() now refuses an arc-arc merge, so
   each keeps its own record L/R/delta and its own drawn span.
usage: python spike/leg185_lever1_crops.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from recon import OUT_RECON  # noqa: E402


def crop(pdf_path, region, out_name, pad=90, z=3.0):
    page = pymupdf.open(pdf_path)[0]
    x0, y0, x1, y1 = region
    R = pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad) & page.rect
    zz = min(z, 900 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zz, zz), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    out_path = OUT_RECON / out_name
    cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    print("wrote", out_path)


def main():
    root = Path(__file__).parent.parent / "Sample Data" / "d4"

    # 1. R-10434.1's R=245.0' L=289.24' -- the arc's own matched piece runs from (1051.5,1352.9) to
    # (969.5,1206.5) (checks.py's labels.json), the MATCHLINE sits just past it (measured, leg 5 crop).
    crop(root / "r_10434_001_2020-09-16.pdf", [943, 1150, 1080, 1360],
         "l18_5_lever1_r10434_1_R245_matchline_refused.png", pad=110)

    # 2. R-10434.3's C26 -- own matched piece runs from (1448.6,596.4) to (1276.9,559.8), "SEE DETAIL A"
    # sits just past its far (PCC) end.
    crop(root / "r_10434_003_2020-09-16.pdf", [1150, 540, 1950, 680],
         "l18_5_lever1_r10434_3_C26_detailA_refused.png", pad=60)

    # 3. Presidio's "L=184.70'(T)" / "L=130.56'" -- both labels' own region boxes (checks.py's exceptions/
    # labels.json for the default sheet).
    labels = json.loads((Path(__file__).parent / "out" / "labels.json").read_text(encoding="utf-8"))
    r1 = next(l["region"] for l in labels if l.get("printed") == "L=184.70'(T)")
    r2 = next(l["region"] for l in labels if l.get("printed") == "L=130.56'")
    x0 = min(r1[0], r2[0]); y0 = min(r1[1], r2[1]); x1 = max(r1[2], r2[2]); y1 = max(r1[3], r2[3])
    crop(root.parent / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf", [x0, y0, x1, y1],
         "l18_5_lever1_presidio_L184_70_L130_56_unmerged.png", pad=80)


if __name__ == "__main__":
    main()
