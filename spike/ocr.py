"""Text spike steps 3-5: level each text block, read it, score table values against gt.py.

usage: python spike/ocr.py rapid        (reader name; results -> spike/out/read_<reader>.json)
"""
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from gt import TABLES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf"
PDF = Path(os.environ.get("SHEET", DEFAULT))  # SHEET=<pdf> runs another sheet; its outputs go to out/<stem>/
OUT = Path(__file__).parent / "out" / (PDF.stem if "SHEET" in os.environ else "")
Z = 5  # render pixels per PDF point


def level_crop(page_img, b):
    """Rotate the block to horizontal and cut it out, padded so one-stroke edge characters survive."""
    gh = b["glyph_h"]
    w, h = (b["w"] + 1.2 * gh) * Z, (b["h"] + 0.9 * gh) * Z
    cx, cy = b["cx"] * Z, b["cy"] * Z
    half = int(np.hypot(w, h) / 2) + 4
    x0, y0 = int(cx) - half, int(cy) - half
    win = page_img[max(y0, 0):y0 + 2 * half, max(x0, 0):x0 + 2 * half]
    c = (cx - max(x0, 0), cy - max(y0, 0))
    M = cv2.getRotationMatrix2D(c, b["angle"], 1.0)
    rot = cv2.warpAffine(win, M, (win.shape[1], win.shape[0]), flags=cv2.INTER_CUBIC, borderValue=255)
    return cv2.getRectSubPix(rot, (int(w), int(h)), c)


def norm(s):
    s = s.replace(" ", "").replace("|", "")
    s = re.sub(r"[’‘`′´]", "'", s)
    s = re.sub(r"[”“″]|''", '"', s)
    s = re.sub(r"[º˚]", "°", s)
    s = s.upper().strip("[]")  # table grid lines read as brackets
    s = re.sub(r"^\$(?=\d)", "S", s)  # S read as $ at the start of a bearing
    # survey notation is rigid, so parse it instead of trusting every symbol:
    # bearing  N dd°mm'ss" E (suffix)   /   angle  ddd°mm'ss" (suffix)
    m = re.match(r"^([NS])(\d{1,2}?)[°*.O'\"]?(\d{2})['*°]?(\d{2})[\"'*]*([EW])(\(.\))?$", s)
    if m:
        return f"{m[1]}{int(m[2])}°{m[3]}'{m[4]}\"{m[5]}{m[6] or ''}"
    m = re.match(r"^(\d{1,3}?)[°*.O'\"]?(\d{2})['*°]?(\d{2})[\"'*]+(\(.\))?$", s)
    if m and "." not in s[-5:]:
        return f"{int(m[1])}°{m[2]}'{m[3]}\"{m[4] or ''}"
    m = re.match(r"^([\d,]*\d\.\d{2})'?(\(.\))?$", s)  # distance / coordinate: foot mark optional
    if m:
        return f"{m[1]}{m[2] or ''}"
    return s


def reader_rapid():
    from rapidocr_onnxruntime import RapidOCR
    eng = RapidOCR()

    def read(img, one_line):
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        # det + rec only for the 2-3 line callouts; on a single line the detector returns
        # overlapping boxes and characters get read twice
        res = None if one_line else eng(bgr)[0]
        if not res:
            res, _ = eng(bgr, use_det=False, use_cls=False)  # tiny crops: recognise as a single line
            res = [(None, t, s) for t, s in (res or [])]
        return "|".join(r[1] for r in res), float(min((float(r[2]) for r in res), default=0.0))
    return read


READERS = {"rapid": reader_rapid}


def main(name):
    page = pymupdf.open(PDF)[0]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(Z, Z), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    blocks = json.loads((OUT / "blocks.json").read_text(encoding="utf-8"))
    read = None if "rescore" in sys.argv else READERS[name]()

    cache = OUT / f"read_{name}.json"
    t0 = time.time()
    if "rescore" in sys.argv:
        blocks = json.loads(cache.read_text(encoding="utf-8"))
    else:
        for b in blocks:
            b["text"], b["conf"] = read(level_crop(img, b), b["h"] < 1.9 * b["glyph_h"])
        cache.write_text(json.dumps(blocks, indent=1, ensure_ascii=False), encoding="utf-8")
    secs = time.time() - t0

    print(f"reader={name} blocks={len(blocks)} time={secs:.0f}s ({secs / len(blocks) * 1000:.0f} ms/block)")
    print(f"{'table':12} {'gt':>4} {'hit':>4} {'recall':>7}   misses (gt value -> nearest unmatched reads)")
    tot = hit_tot = 0
    rows = []
    for tname, ((x0, y0, x1, y1), values) in TABLES.items():
        inside = [b for b in blocks if x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1]
        got = Counter(norm(b["text"]) for b in inside)
        want = Counter(norm(v) for v in values)
        hits = sum((got & want).values())
        miss = list((want - got).elements())
        extra = [t for t in (got - want).elements() if t]
        tot += len(values); hit_tot += hits
        print(f"{tname:12} {len(values):4} {hits:4} {hits / len(values):7.1%}   {miss[:6]} | unmatched reads: {extra[:8]}")
        conf_by = {norm(b["text"]): b["conf"] for b in inside}
        rows += [(conf_by[k], True) for k in (got & want).elements()] + [(conf_by.get(k, 0), False) for k in extra]
    print(f"{'ALL TABLES':12} {tot:4} {hit_tot:4} {hit_tot / tot:7.1%}")
    ok = [c for c, good in rows if good]; bad = [c for c, good in rows if not good]
    if ok and bad:
        print(f"confidence: correct median {np.median(ok):.3f} (p5 {np.percentile(ok, 5):.3f}) | wrong median {np.median(bad):.3f} (max {max(bad):.3f})")
    return hit_tot / tot


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "rapid")
