"""Loop6 leg B gate evidence: the labels newly passing after the at_tip busy-vertex fix (from the
before/after labels.json pass-set diff -- only 2 label-passes gained, both from the same printed block
S86 deg 03' 39" W | 62.27' at one busy vertex near curve tags C7/C8, presidio). Red = label, blue = the
line checks.py now measures. Ad hoc, not part of the pipeline.
usage: python spike/leg6B_passes_crops.py
"""
import json
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from leg6B_crops import tile, ROOT

PDF = ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf"


def main():
    page = pymupdf.open(PDF)[0]
    labels = json.loads((ROOT / "spike" / "out" / "labels.json").read_text(encoding="utf-8"))
    bearing = next(la for la in labels if la["kind"] == "bearing" and la["printed"] == "S86°03'39\"W")
    dist = next(la for la in labels if la["kind"] == "distance" and la["printed"] == "62.27'")
    im = tile(page, bearing, "presidio: S86°03'39\"W + 62.27' -- newly passing (1 vertex, 2 label passes)", color=(220, 90, 0))
    out = ROOT / "spike" / "out" / "leg6B_passes.png"
    cv2.imwrite(str(out), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    print("wrote", out, im.shape)
    print("bearing:", bearing)
    print("distance:", dist)


if __name__ == "__main__":
    main()
