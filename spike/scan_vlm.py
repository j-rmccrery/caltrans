"""Scratch: can a local vision model read the hand-lettered coordinates RapidOCR garbles? (qwen2.5vl:7b via Ollama)"""
import base64
import json
import re
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

z = 300 / 72
page = pymupdf.open(PDF)[0]
pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8"))
sel = [b for b in blocks if re.match(r"^[NE][.:]?\d{4,8}", b["text"].replace(" ", "").upper())]
print(len(sel), "letter-prefixed numeric reads")
for b in sel:
    q = np.array(b["px"], np.float32)
    (cx, cy), (w, h), ang = cv2.minAreaRect(q)
    if w < h:
        w, h, ang = h, w, ang + 90
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    rot = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_CUBIC, borderValue=255)
    crop = cv2.getRectSubPix(rot, (int(w * 1.15) + 20, int(h * 1.6) + 12), (cx, cy))
    crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", crop)
    req = {"model": "qwen2.5vl:7b", "stream": False, "options": {"temperature": 0},
           "prompt": "Transcribe exactly the hand-lettered survey coordinate in this image. It is a letter N or E, then a number with two decimal places, e.g. N.10018.76. Reply with only the transcription.",
           "images": [base64.b64encode(buf.tobytes()).decode()]}
    r = urllib.request.urlopen(urllib.request.Request("http://localhost:11434/api/generate", json.dumps(req).encode(), {"Content-Type": "application/json"}), timeout=300)
    out = json.load(r)["response"].strip()
    print(f"  rapid {b['text']:>14}  |  vlm {out}")
