"""Trial: rapidocr 3.9.2 (package name "rapidocr", not rapidocr-onnxruntime) with the
PP-OCRv5 server DET onnx model, full resolution, on the 1969 scan page (spike/det, isolated).

Two clamps stand between the 6291x4369 page and the detector, both in rapidocr's own code,
not ours:
  1. Global.max_side_len (default 2000) downscales the WHOLE image before det ever runs
     (main.py RapidOCR.preprocess_img -> resize_image_within_bounds). Must be raised >= 6291.
  2. TextDetector.get_preprocess (ch_ppocr_det/main.py): when Det.limit_type == "max" it
     IGNORES the configured Det.limit_side_len and substitutes a hardcoded ladder that tops
     out at 2000 for any image with max side >= 1500. So limit_type="max" silently reclamps
     to 2000 regardless of what limit_side_len is set to -- rapidocr's own analogue of the
     paddlex max_side_limit trap from the paddle trial. The only way to keep native
     resolution is limit_type="min" (the default) with limit_side_len <= min(h, w) = 4369,
     which then computes ratio = 1.0 (no resize) and only rounds to the nearest 32px.

usage: <venv_rapid2>\\Scripts\\python.exe spike/det/run_rapid2.py
"""
import json
import time
from pathlib import Path

import cv2

from rapidocr import RapidOCR
from rapidocr.ch_ppocr_det.utils import DetPreProcess
from rapidocr.utils.typings import ModelType, OCRVersion

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "out" / "r_00065_002_1969-09-01_sn-02048" / "page300.png"
OUT = HERE / "rapid2_v5_dets.json"

img = cv2.imread(str(PAGE))
print("page shape (h, w, c):", img.shape)

# capture the actual resize DetPreProcess computes, without changing behavior
_orig_resize = DetPreProcess.resize
_seen = {}


def _traced_resize(self, img):
    h, w = img.shape[:2]
    out = _orig_resize(self, img)
    if out is not None:
        _seen["in"] = (h, w)
        _seen["out"] = out.shape[:2]
    return out


DetPreProcess.resize = _traced_resize

engine = RapidOCR(
    params={
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.SERVER,
        "Det.limit_side_len": 4000,  # <= min(h, w)=4369 so limit_type="min" leaves ratio=1.0
        "Det.limit_type": "min",
        "Det.thresh": 0.2,
        "Det.box_thresh": 0.3,
        "Det.unclip_ratio": 1.3,
        "Global.max_side_len": 7000,  # raise the pre-det global clamp above the page's 6291
        "Global.use_cls": False,
        "EngineConfig.onnxruntime.use_cuda": False,
    }
)

t0 = time.time()
result = engine(str(PAGE), use_cls=False, use_rec=True)
dt = time.time() - t0

print("det input into onnx (h, w) before/after round-to-32:", _seen.get("in"), "->", _seen.get("out"))
print(f"predict seconds: {dt:.1f}  device: CPUExecutionProvider")

dets = []
if result.boxes is not None:
    for box, txt in zip(result.boxes, result.txts or [""] * len(result.boxes)):
        dets.append({"px": [[float(x), float(y)] for x, y in box], "text": txt})

print(f"boxes: {len(dets)}")
json.dump(dets, open(OUT, "w"))
print(f"wrote {OUT}")
