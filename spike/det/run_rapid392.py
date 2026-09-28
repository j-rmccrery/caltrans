"""rapidocr 3.9.2 (project .venv, package name "rapidocr") reproduction of the 32/32 paddle
result: PP-OCRv5 server det, page rendered directly from the PDF with pymupdf at 190.75 dpi
(long side 4000px), no CLAHE, thresh 0.2 / box_thresh 0.3 / unclip_ratio 1.3. Boxes are scaled
back x 6291/4000 to page300.png pixel coords (the det_score.py / gt_scan.py coordinate space).

Two clamps stand between rapidocr and the raw image, both worked around here (see run_rapid2.py
for the venv_rapid2 version of this same finding):
  1. Global.use_preprocess_img (default True) downscales the WHOLE image to Global.max_side_len
     (default 2000) before Det ever runs. Disabled outright -- we already control the render size.
  2. TextDetector.get_preprocess ignores the configured Det.limit_side_len whenever
     Det.limit_type == "max" and substitutes a hardcoded ladder topping out at 2000. Only
     limit_type == "min" with limit_side_len <= min(h, w) leaves ratio == 1.0 (native res,
     rounded to the nearest 32px).

usage: .venv/Scripts/python spike/det/run_rapid392.py
"""
import json
import time
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from rapidocr import RapidOCR
from rapidocr.ch_ppocr_det.utils import DetPreProcess
from rapidocr.utils.typings import ModelType, OCRVersion

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
STEM = "r_00065_002_1969-09-01_sn-02048"
PDF = next((SPIKE.parent / "Sample Data").rglob(STEM + ".pdf"))
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

LONG_SIDE = 4000
DPI = 300.0 * LONG_SIDE / 6291.0  # 190.75, matches sweep_scale.py cmd_render's render_c recipe
# unclip_ratio lowered from the paddle recipe's 1.3: rapidocr's DBPostProcess expands boxes more
# for the same ratio (paddle's 1.3 gave 3 fused here; a small sweep found 1.1-1.15 clean, see
# spike/det/LOOP.md). box_thresh only changes box count in this range, not the 32 keyed verdicts.
TUNED = dict(thresh=0.2, box_thresh=0.3, unclip_ratio=1.15)


def render_page():
    page = pymupdf.open(PDF)[0]
    z = DPI / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def main():
    img = render_page()
    h, w = img.shape[:2]
    print(f"render at {DPI:.2f}dpi: shape (h,w)={h},{w}  (target long side {LONG_SIDE})")

    _orig_resize = DetPreProcess.resize
    seen = {}

    def _traced_resize(self, im):
        ih, iw = im.shape[:2]
        out = _orig_resize(self, im)
        if out is not None:
            seen["in"] = (ih, iw)
            seen["out"] = out.shape[:2]
        return out

    DetPreProcess.resize = _traced_resize

    engine = RapidOCR(
        params={
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.SERVER,
            "Det.limit_side_len": min(h, w),  # <= min(h,w) with limit_type="min" -> ratio 1.0
            "Det.limit_type": "min",
            "Det.thresh": TUNED["thresh"],
            "Det.box_thresh": TUNED["box_thresh"],
            "Det.unclip_ratio": TUNED["unclip_ratio"],
            "Global.use_preprocess_img": False,  # skip the Global.max_side_len=2000 pre-clamp entirely
            "Global.use_cls": False,
            "EngineConfig.onnxruntime.use_cuda": False,
        }
    )

    t0 = time.time()
    result = engine(img, use_det=True, use_cls=False, use_rec=False)
    dt = time.time() - t0

    print(f"model input (h,w) actually fed to onnx: {seen.get('in')} -> {seen.get('out')} "
          f"(rounded to nearest 32px; ratio should be 1.0)")
    print(f"predict seconds: {dt:.1f}")

    scale = 6291.0 / LONG_SIDE
    dets = []
    if result.boxes is not None:
        for box in result.boxes:
            dets.append({"px": [[float(x) * scale, float(y) * scale] for x, y in box]})
    print(f"boxes: {len(dets)}")

    out_path = OUT / "rapid392_render_dets.json"
    json.dump(dets, open(out_path, "w"))
    print(f"wrote {out_path}")

    import sys
    sys.path.insert(0, str(HERE))
    from det_score import score
    score(dets, name="rapid392_render")


if __name__ == "__main__":
    main()
