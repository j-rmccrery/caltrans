"""Scratch: calibrate qwen2.5vl bbox_2d coord space against a known box before tiling the page."""
import base64
import json
import time
import urllib.request

import cv2
import numpy as np

PAGE = "../out/r_00065_002_1969-09-01_sn-02048/page300.png"
img = cv2.imread(PAGE, cv2.IMREAD_GRAYSCALE)
print("page", img.shape)

# known box 186 (text "996.26", part of truth N9996.26): px [2724,647]-[2842,667]
x0, y0, size = 2500, 500, 1200
tile = img[y0:y0 + size, x0:x0 + size]
print("tile", tile.shape)
ok, buf = cv2.imencode(".png", tile)
b64 = base64.b64encode(buf.tobytes()).decode()

PROMPT = ('Detect all text in this image of a hand-lettered survey drawing. '
          'Output a JSON list of objects with "bbox_2d": [x1,y1,x2,y2] in pixel coordinates '
          'of this image, and "text": the transcription. Reply with JSON only.')

req = {"model": "qwen2.5vl:7b", "stream": False, "options": {"temperature": 0},
       "prompt": PROMPT, "images": [b64]}
t0 = time.time()
r = urllib.request.urlopen(urllib.request.Request(
    "http://localhost:11434/api/generate", json.dumps(req).encode(), {"Content-Type": "application/json"}),
    timeout=180)
dt = time.time() - t0
out = json.load(r)["response"]
print(f"seconds {dt:.1f}")
print("raw response:")
print(out.encode("ascii", "replace").decode())

known_local = (2724 - x0, 647 - y0, 2842 - x0, 667 - y0)
print("known box in tile-local px (expected model output near this):", known_local)
