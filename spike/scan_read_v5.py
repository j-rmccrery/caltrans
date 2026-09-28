"""Scan detector, PP-OCRv5-server variant (spike leg; trials and sweep in spike/det/, see
spike/det/run_rapid392.py). Detection: rapidocr 3.9.2 (package "rapidocr", project .venv) with
the PP-OCRv5 server det model on the page rendered directly from the PDF at long-side-4000px
(no CLAHE) -- the setting that lands 31/32 of the keyed scan truth boxes, vs scan_read.py's
tiled RapidOCR-1.4.4 det. Recognition: the pipeline's own RapidOCR rec (rapidocr_onnxruntime,
rec-only) on a CLAHE-levelled 300dpi crop of each box, same crop recipe as scan_readers.crop_of.

Output has the same shape as scan_read.py's read_rapid.json (px, cx, cy, w, h, angle, glyph_h,
glyphs, text, conf, id) but is written to read_v5.json alongside it, NOT over it, so the old
RapidOCR-1.4.4 boxes stay for comparison. gt_scan.py's TRUTH keys are RapidOCR-1.4.4 ids and do
not line up with this detector's own box ids -- use spike/det/det_score.match_truth (best
overlap against read_rapid.json) rather than treating a TRUTH key as an id into this file.

usage: SHEET=<scan.pdf> python spike/scan_read_v5.py
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
from scan_read import repair  # noqa: E402

DET_LONG_SIDE = 4000        # spike/det's tuned recipe: 31/32 landed, 0 cut, 0 fused on R-65.2
REC_DPI = 300                # recognition crops at the pipeline's usual 300dpi (read_rapid.json's space)
TUNED = dict(thresh=0.2, box_thresh=0.3, unclip_ratio=1.15)


def render_gray(dpi, clahe):
    page = pymupdf.open(PDF)[0]
    z = dpi / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    if clahe:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX)
        img = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16)).apply(img)
    return img, z


def detect(det_dpi):
    """PP-OCRv5 server det at native render resolution; returns quads in det-render pixel coords."""
    from rapidocr import RapidOCR
    from rapidocr.utils.typings import ModelType, OCRVersion
    gray, _ = render_gray(det_dpi, clahe=False)
    img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    h, w = img.shape[:2]
    engine = RapidOCR(params={
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Det.model_type": ModelType.SERVER,
        "Det.limit_side_len": min(h, w),  # with limit_type="min" this keeps ratio == 1.0 (native res)
        "Det.limit_type": "min",
        "Det.thresh": TUNED["thresh"],
        "Det.box_thresh": TUNED["box_thresh"],
        "Det.unclip_ratio": TUNED["unclip_ratio"],
        "Global.use_preprocess_img": False,  # skip the Global.max_side_len=2000 pre-clamp
        "Global.use_cls": False,
        "EngineConfig.onnxruntime.use_cuda": False,
    })
    result = engine(img, use_det=True, use_cls=False, use_rec=False)
    return [np.array(box, np.float64) for box in (result.boxes if result.boxes is not None else [])]


def box_geom(q):
    (cx, cy), (w, h), ang = cv2.minAreaRect(q.astype(np.float32))
    if w < h:
        w, h, ang = h, w, ang + 90
    ang = (ang + 90) % 180 - 90
    return cx, cy, w, h, ang


def crop_variants(img, q):
    """Candidate rec crops for one box (loop16 send-back): the pad/margin sweep's best single
    config, pad(4,2), truncates the tail on wide-but-loose boxes (e.g. ids 228/229's "21 00'11""
    -- the box itself isn't short, verified by eye, so a tighter-height second candidate is
    offered instead of just widening) and a 90/270 near-vertical box (ids 97/249, "E.12000"
    written top-to-bottom) can come out upside-down from minAreaRect's 180-degree ambiguity --
    both get a second, 180-rotated candidate. main() picks among these, not truth."""
    (cx, cy), (w0, h0), ang = cv2.minAreaRect(q.astype(np.float32))
    was_vertical = h0 > 1.4 * w0
    if w0 < h0:
        w, h, ang = h0, w0, ang + 90
    else:
        w, h = w0, h0
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_CUBIC, borderValue=255)

    def sub(wf, hf, padw, padh):
        c = cv2.getRectSubPix(rot, (int(w * wf) + padw, int(h * hf) + padh), (cx, cy))
        return cv2.resize(c, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    std = sub(1.1, 1.15, 4, 2)    # the pad/margin sweep's best single config
    tight = sub(1.1, 0.9, 4, 0)   # less vertical slack -- recovers 228/229's truncated tail
    variants = [std, tight]
    if was_vertical:
        variants += [cv2.rotate(std, cv2.ROTATE_180), cv2.rotate(tight, cv2.ROTATE_180)]
    return variants


def main():
    t0 = time.time()
    # dpi that renders this sheet's long side at DET_LONG_SIDE px (spike/det/run_rapid392.py used a
    # dpi fixed to R-65.2's known page300 size; this derives it per-sheet from the PDF's own rect)
    page0 = pymupdf.open(PDF)[0]
    long_side_pts = max(page0.rect.width, page0.rect.height)
    det_dpi = DET_LONG_SIDE / (long_side_pts / 72.0)

    quads = detect(det_dpi)
    rec_img, z = render_gray(REC_DPI, clahe=True)  # same recipe as scan_read.py / scan_alphabet.page_img
    det_to_rec = z / (det_dpi / 72)  # scale factor: det-render px -> rec-render (300dpi) px

    from rapidocr_onnxruntime import RapidOCR as RapidOCRRec
    eng = RapidOCRRec()

    def digit_count(s):
        return sum(ch.isdigit() for ch in s)

    found = []
    for q in quads:
        q300 = q * det_to_rec
        cx, cy, w, h, ang = box_geom(q300)
        cands = []
        for crop in crop_variants(rec_img, q300):
            rec = eng(cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR), use_det=False, use_cls=False, use_rec=True)
            txts = rec[0] if rec and rec[0] else []
            t, c = (txts[0][0], float(txts[0][1])) if txts else ("", 0.0)
            cands.append((repair(t), c))
        text, conf = max(cands, key=lambda tc: (digit_count(tc[0]), tc[1]))
        found.append({"cx": cx / z, "cy": cy / z, "w": w / z, "h": h / z, "angle": round(float(ang), 2),
                      "glyphs": len(text), "glyph_h": h / z * 0.75, "text": text, "conf": conf,
                      "px": q300.tolist()})

    found.sort(key=lambda b: (b["cy"], b["cx"]))
    for i, b in enumerate(found):
        b["id"] = i

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "read_v5.json").write_text(json.dumps(found, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"det_dpi={det_dpi:.2f} boxes={len(found)} | {time.time() - t0:.0f}s -> {OUT / 'read_v5.json'}")


if __name__ == "__main__":
    main()
