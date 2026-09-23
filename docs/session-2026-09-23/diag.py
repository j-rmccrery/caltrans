"""For every distance label picked 'beside' and wrong: is a right-length line among the candidates at all?
usage: [SHEET=..] python diag.py
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pymupdf

sys.path.insert(0, r"C:\Users\johnr\projects\caltrans\spike")
import checks  # noqa: E402
from georef import OUT, PDF, READS, frame, real_text_blocks  # noqa: E402

page = pymupdf.open(PDF)[0]
g = json.loads((OUT / "georef.json").read_text()); a, bb = g["params"][:2]; scale = math.hypot(a, bb)
blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
checks.set_decimals(blocks)
chains, circles, paths, segs = checks.sheet_lines(page, blocks)
from overlay import FURNITURE  # noqa: E402


def az_of(ln):
    dx, dy = ln["dir"][0], -ln["dir"][1]
    return math.degrees(math.atan2(a * dx - bb * dy, bb * dx + a * dy)) % 360


def cands_for(b, tol_deg=4.0):
    c, u, n = frame(b)
    out = []
    for ln in chains:
        if abs(ln["dir"] @ n) > math.sin(math.radians(tol_deg)):
            continue
        lo, hi = sorted(((ln["p0"] - c) @ u, (ln["p1"] - c) @ u))
        if hi < -b["w"] / 2 - 2 * b["glyph_h"] or lo > b["w"] / 2 + 2 * b["glyph_h"]:
            continue
        perp = abs((ln["p0"] - c) @ n)
        if perp < 5.0 * b["glyph_h"]:
            out.append((perp, ln))
    return out


def spans(piece, want):
    if "run" not in piece:
        return []
    run = sorted((c for c in chains if c.get("run") == piece["run"]), key=lambda c: c["s0"])
    hits = []
    for i in range(len(run)):
        for j in range(i, len(run)):
            L = (run[j]["s1"] - run[i]["s0"]) * scale
            if abs(L - want) <= 1.0 + 0.001 * want:
                hits.append((i, j))
    return hits


detail = {"span": [], "anywhere": [], "nowhere": []}
tally = {"exact_cand": 0, "span_on_cand_run": 0, "nowhere_near": 0, "anywhere_on_sheet": 0}
n = 0
for b in blocks:
    if any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in FURNITURE):
        continue
    lines = b["text"].replace(" ", "").split("|")
    curve = any(checks.ANG.match(t) or checks.RAD.match(t) or checks.LEN.match(t) for t in lines)
    parts = [m.group(0) for t in lines for m in checks.TOKEN.finditer(t)] or lines
    for part in parts:
        m = checks.DIST.match(part)
        if not m or m[2] or curve:
            continue
        want = float(m[1])
        cs = cands_for(b)
        if not cs:
            continue
        pick = min(cs, key=lambda t: t[0])[1]
        close = [ln for p, ln in cs if abs(ln["len_pt"] * scale - want) < 1.0]
        if close:
            continue  # the rule would already pick a right-length line
        n += 1
        same = sum(1 for o in blocks if o is not b and part in o["text"].replace(" ", ""))
        hits = [(ln, spans(ln, want)) for p, ln in cs if spans(ln, want)]
        if hits:
            uniq = sum(1 for ln, h in hits if len(h) == 1)
            tally["span_on_cand_run"] += 1
            detail["span"].append((len(hits), uniq))
        else:
            near = [ln for ln in chains if abs(ln["len_pt"] * scale - want) < 1.0]
            if near:
                tally["anywhere_on_sheet"] += 1
                c, u, nn = frame(b)
                best = min(near, key=lambda ln: checks.seg_dist(c, ln["p0"], ln["p1"]))
                d = checks.seg_dist(c, best["p0"], best["p1"]) / b["glyph_h"]
                ang = math.degrees(math.asin(min(1, abs(best["dir"] @ nn))))
                detail["anywhere"].append((round(d, 1), round(ang, 1), same))
            else:
                tally["nowhere_near"] += 1
                detail["nowhere"].append((part, same))
print(PDF.stem, "distance labels with no right-length candidate:", n, tally)
print("  span hits (n candidates with a span, n unique):", sorted(detail["span"]))
print("  anywhere (dist in glyph_h, angle deg, same value printed elsewhere):", sorted(detail["anywhere"]))
print("  nowhere:", detail["nowhere"][:12])
