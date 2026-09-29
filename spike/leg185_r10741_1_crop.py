"""Loop18 leg 5, orchestrator gate evidence: R-10741.1's "L=660.20'" curve, which used to get its R only
via traverse.py's share_curve_radius() borrowing from the (already-FAILED, off 4.52 ft) "R=1169.9'
L=319.73'" sub-total row -- and lost that donor once build_edges() correctly stopped walking FAILED
labels (loop18 leg 5, lever 1). Fixed in checks.py: the SAME curve's own printed "R=1169.90'
delta=15d39'31" L=319.73' delta=32d20'00" L=660.20'" annotation (one shared R, two delta/L pairs on one
reading line) is matched by VALUE (L=660.20' -> the label already carrying that exact record length) and
verified by chord fit, attaching directly.
usage: python spike/leg185_r10741_1_crop.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from recon import OUT_RECON  # noqa: E402


def main():
    root = Path(__file__).parent.parent / "Sample Data" / "d4"
    pdf_path = root / "r_10741_001_2017-02-10.pdf"
    page = pymupdf.open(pdf_path)[0]
    x0, y0, x1, y1 = 1750, 850, 2100, 1000  # the shared-R annotation block, both delta/L pairs
    pad = 60
    R = pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad) & page.rect
    z = min(3.0, 900 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    out_path = OUT_RECON / "l18_5_r10741_1_L660_20_shared_R_accepted.png"
    cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    print("wrote", out_path)

    d = json.loads((Path(__file__).parent / "out" / "r_10741_001_2017-02-10" / "traverse.json").read_text(encoding="utf-8"))
    for route in d:
        for e in route["edges"]:
            if "660.20" in e.get("edge", ""):
                print(e["edge"], "misfit", e["misfit_ft"], "chord_source", e.get("chord_source"))


if __name__ == "__main__":
    main()
