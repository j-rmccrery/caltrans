"""Score readers on the keyed scan boxes (gt_scan.py): RapidOCR's line read, and the local vision model
on a levelled crop of each box. Digits must match exactly. No example values in any prompt.
usage: python spike/scan_readers.py [--vlm]
"""
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "det"))
from gt_scan import TRUTH, digits  # noqa: E402

STEM = "r_00065_002_1969-09-01_sn-02048"
OUT = Path(__file__).parent / "out" / STEM
PDF = next((Path(__file__).parent.parent / "Sample Data").rglob(STEM + ".pdf"))
READS = os.environ.get("READS", "read_rapid.json")  # READS=read_v5.json scores the new detector's boxes instead
PROMPT = ("This is a small crop of a hand-lettered land survey map. Transcribe the text exactly as written, "
          "character for character, including any letter prefix, decimal point, degree, minute and second marks. "
          "Reply with the transcription only.")


def crop_of(img, b, z):
    q = np.array(b["px"], np.float32)
    (cx, cy), (w, h), ang = cv2.minAreaRect(q)
    if w < h:
        w, h, ang = h, w, ang + 90
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_CUBIC, borderValue=255)
    c = cv2.getRectSubPix(rot, (int(w * 1.1) + 16, int(h * 1.15) + 8), (cx, cy))  # tight: the neighbouring line must not come along
    return cv2.resize(c, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


def vlm(png):
    req = {"model": "qwen2.5vl:7b", "stream": False, "options": {"temperature": 0}, "prompt": PROMPT, "images": [base64.b64encode(png).decode()]}
    r = urllib.request.urlopen(urllib.request.Request("http://localhost:11434/api/generate", json.dumps(req).encode(), {"Content-Type": "application/json"}), timeout=180)
    out = json.load(r)["response"].strip()
    return out.splitlines()[0] if out else ""


def main():
    dets = json.load(open(OUT / READS, encoding="utf-8"))
    if READS == "read_rapid.json":
        reads = {b["id"]: b for b in dets}  # truth keys ARE this file's own ids
    else:
        from det_score import match_truth  # different detector: ids differ, map by best overlap
        matches = match_truth(dets)
        reads = {k: dets[i] for k, (i, cov) in matches.items() if i is not None}
    page = pymupdf.open(PDF)[0]
    z = 300 / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    ok_r = ok_v = 0
    rows = []
    for k, v in TRUTH.items():
        if k not in reads:
            print(f"  {k:4} truth {v!r:24} -- no matching box in {READS}"); continue
        b = reads[k]
        r_hit = digits(b["text"]) == digits(v)
        v_txt = ""
        if "--vlm" in sys.argv:
            _, png = cv2.imencode(".png", crop_of(img, b, z))
            try:
                v_txt = vlm(png.tobytes())
            except Exception as e:
                v_txt = f"<{type(e).__name__}>"
        v_hit = digits(v_txt) == digits(v)
        ok_r += r_hit; ok_v += v_hit
        rows.append((k, v, b["text"], v_txt, r_hit, v_hit))
        print(f"  {k:4} truth {v!r:24} rapid {b['text']!r:16} {'ok' if r_hit else '--'}   vlm {v_txt[:26]!r:28} {'ok' if v_hit else '--'}")
    print(f"digits exact: RapidOCR {ok_r}/{len(TRUTH)}" + (f", vision model {ok_v}/{len(TRUTH)}, either {sum(1 for r in rows if r[4] or r[5])}/{len(TRUTH)}, both agree and right {sum(1 for r in rows if r[4] and r[5])}" if "--vlm" in sys.argv else ""))


if __name__ == "__main__":
    main()
