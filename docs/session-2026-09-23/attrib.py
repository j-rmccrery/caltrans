"""Why does no candidate match a distance label's printed length? One cause per label:
  noise        the token is not a line length (stationing 65+48.80, R=60.00, table cell)
  filtered     a right-length chain lies beside the label in the raw linework but sheet_lines dropped it
  cut          the right length exists as a whole raw chain beside the label but the split pieces / spans miss it
  angle        a right-length chain lies beside the label but more than 4 deg off its box angle
  none         no chain of that length lies within 5 glyph heights at any angle
usage: [SHEET=..] python attrib.py
"""
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, r"C:\Users\johnr\projects\caltrans\spike")
import checks  # noqa: E402
from georef import OUT, PDF, READS, frame, real_text_blocks, segments  # noqa: E402
from overlay import FURNITURE  # noqa: E402

page = pymupdf.open(PDF)[0]
g = json.loads((OUT / "georef.json").read_text()); a, bb = g["params"][:2]; scale = math.hypot(a, bb)
blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
checks.set_decimals(blocks)
chains, circles, paths, segs = checks.sheet_lines(page, blocks)          # filtered + split (what the checks use)
_, circ = segments(page)
raw_segs = checks.linework_segments(page, max_gray=0.2)
raw = checks.lines_on_sheet(raw_segs, circ)                                 # nothing filtered, unsplit
filt_unsplit = [c for c in checks.lines_on_sheet(segs, circ)]              # leaders removed, unsplit, before the stub/underline filters


def near(b, pool, want, tol_deg, r=5.0):
    c, u, n = frame(b)
    out = []
    for ln in pool:
        if abs(ln["dir"] @ n) > math.sin(math.radians(tol_deg)):
            continue
        lo, hi = sorted(((ln["p0"] - c) @ u, (ln["p1"] - c) @ u))
        if hi < -b["w"] / 2 - 2 * b["glyph_h"] or lo > b["w"] / 2 + 2 * b["glyph_h"]:
            continue
        if abs((ln["p0"] - c) @ n) < r * b["glyph_h"] and abs(ln["len_pt"] * scale - want) < 1.0:
            out.append(ln)
    return out


tally, examples = Counter(), {}
for b in blocks:
    if any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in FURNITURE):
        continue
    raw_text = b["text"].replace(" ", "")
    lines = raw_text.split("|")
    curve = any(checks.ANG.match(t) or checks.RAD.match(t) or checks.LEN.match(t) for t in lines)
    parts = [m.group(0) for t in lines for m in checks.TOKEN.finditer(t)] or lines
    for part in parts:
        m = checks.DIST.match(part)
        if not m or m[2] or curve:
            continue
        want = float(m[1])
        c, u, n = frame(b)
        cs = []
        for ln in chains:
            if abs(ln["dir"] @ n) > math.sin(math.radians(4.0)):
                continue
            lo, hi = sorted(((ln["p0"] - c) @ u, (ln["p1"] - c) @ u))
            if hi < -b["w"] / 2 - 2 * b["glyph_h"] or lo > b["w"] / 2 + 2 * b["glyph_h"]:
                continue
            if abs((ln["p0"] - c) @ n) < 5.0 * b["glyph_h"]:
                cs.append(ln)
        if not cs:
            continue
        if any(abs(ln["len_pt"] * scale - want) < 1.0 for ln in cs) or any(checks.span_for(ln, want, scale, chains) is not ln for ln in cs):
            continue
        if re.search(r"[+=]" + re.escape(part), raw_text) or re.search(r"\d\+\d", raw_text):
            cause = "noise"
        elif near(b, filt_unsplit, want, 4.0):
            cause = "cut"
        elif near(b, raw, want, 4.0):
            cause = "filtered"
        elif near(b, raw, want, 15.0):
            cause = "angle"
        else:
            cause = "none"
        tally[cause] += 1
        examples.setdefault(cause, []).append(part)
print(PDF.stem, dict(tally))
for k, v in examples.items():
    print("  ", k, v[:10])
