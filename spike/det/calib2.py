"""Scratch: calibrate qwen2.5vl bbox_2d coord space with a synthetic marker, isolated from OCR difficulty."""
import base64
import json
import time
import urllib.request

import cv2
import numpy as np

canvas = np.full((1200, 1200), 255, np.uint8)
# synthetic text box at known coords
x0, y0, x1, y1 = 700, 300, 950, 350
cv2.putText(canvas, "N9996.26", (x0 + 10, y1 - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0,), 3)
cv2.rectangle(canvas, (x0, y0), (x1, y1), (0,), 1)  # faint box so we know ground truth only (not given to model)
ok, buf = cv2.imencode(".png", canvas)
b64 = base64.b64encode(buf.tobytes()).decode()
cv2.imwrite("calib2_input.png", canvas)

PROMPT = ('Detect all text in this image. '
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
print("raw:", out)
print("ground truth text box (not sent to model, drawn only for reference):", (x0, y0, x1, y1))
