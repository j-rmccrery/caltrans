"""Trial: PaddleOCR text DETECTOR on the 1969 scan page (spike/det, isolated — see gate script).

Runs several det variants with paddlex's standalone TextDetection module (det-only, fast) plus
one full PaddleOCR pipeline (det+rec, fills "text" for digits scoring). Writes each variant's
JSON to spike/det/out/<name>.json, scores it with det_score.py's score(), and keeps the best as
spike/det/paddle_dets.json / spike/det/out/paddle_overlay.png.

usage: X:\\venv_paddle\\Scripts\\python.exe spike/det/run_paddle.py
"""
import json
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "out" / "r_00065_002_1969-09-01_sn-02048" / "page300.png"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

img = cv2.imread(str(PAGE))
print("page shape", img.shape)


def polys_to_dets(polys, texts=None):
    dets = []
    for i, p in enumerate(polys):
        d = {"px": [[float(x), float(y)] for x, y in p]}
        if texts is not None:
            d["text"] = texts[i]
        dets.append(d)
    return dets


def run_det(name, model_name, **kw):
    from paddleocr import TextDetection
    t0 = time.time()
    det = TextDetection(model_name=model_name, **kw)
    init_s = time.time() - t0
    t0 = time.time()
    res = list(det.predict(img))
    pred_s = time.time() - t0
    polys = res[0]["dt_polys"]
    dets = polys_to_dets(polys)
    path = OUT / f"{name}.json"
    json.dump(dets, open(path, "w"))
    print(f"{name}: model={model_name} params={kw} init={init_s:.1f}s predict={pred_s:.1f}s boxes={len(dets)} -> {path}")
    return path, pred_s


def run_full_ocr(name, model_name, **kw):
    from paddleocr import PaddleOCR
    t0 = time.time()
    ocr = PaddleOCR(
        text_detection_model_name=model_name,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        **kw,
    )
    init_s = time.time() - t0
    t0 = time.time()
    res = list(ocr.predict(img))
    pred_s = time.time() - t0
    polys = res[0]["rec_polys"]
    texts = res[0]["rec_texts"]
    dets = polys_to_dets(polys, texts)
    path = OUT / f"{name}.json"
    json.dump(dets, open(path, "w"))
    print(f"{name}: model={model_name} params={kw} init={init_s:.1f}s predict={pred_s:.1f}s boxes={len(dets)} -> {path}")
    return path, pred_s


TUNED = dict(limit_side_len=6300, limit_type="max", thresh=0.2, box_thresh=0.3, unclip_ratio=1.3)

variants = {}
variants["a_default_mobile_v4"] = run_det("a_default_mobile_v4", "PP-OCRv4_mobile_det")
variants["b_tuned_mobile_v4"] = run_det("b_tuned_mobile_v4", "PP-OCRv4_mobile_det", **TUNED)
variants["c_tuned_server_v4"] = run_det("c_tuned_server_v4", "PP-OCRv4_server_det", **TUNED)
variants["e_tuned_mobile_v5"] = run_det("e_tuned_mobile_v5", "PP-OCRv5_mobile_det", **TUNED)
variants["f_tuned_server_v5"] = run_det("f_tuned_server_v5", "PP-OCRv5_server_det", **TUNED)

print(json.dumps({k: v[1] for k, v in variants.items()}, indent=2))
