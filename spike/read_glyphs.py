"""Read every text block on a stroked sheet with the sheet's own alphabet: no OCR on vector sheets.

Each block from blocks.py is read glyph by glyph against alphabet.npz (alphabet.py). The block's
reading angle is re-estimated from its glyphs (the dilation blocks beside the R/W line absorb ticks
and leader pieces, which skew their box). Rows are split by height, a small path inside a capital
is that capital's bar, and the symbols are named by where they sit: top of the line = ° ' " in
order, baseline = . or , by size, mid-line = - or =. A letter slot is read among the letters it can
hold (N|S, E|W, R|L, R|T in parens). What does not read is '?', never a guess.

Output: spike/out[/<sheet>]/read_glyph.json, the same block records ocr.py writes (text, conf).
usage: [SHEET=<pdf>] python spike/read_glyphs.py   (after blocks.py and alphabet.py)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from blocks import OUT, PDF  # noqa: E402
from tags import COARSE, JUNK, STEP, Matcher, axes, bitmap, characters, glyphs  # noqa: E402

SMALL = 0.45


def eff_h(g, n):
    """A glyph's height across the reading axis: a hyphen or an = is small however long it is."""
    P = np.vstack(g["strokes"]) @ n
    return float(P.max() - P.min())


def read_row(row, u, n, gh, M):
    """row: glyph dicts sorted along u. Returns text; '?' where a glyph does not read."""
    big = [g for g in row if eff_h(g, n) > SMALL * gh]
    small = [g for g in row if eff_h(g, n) <= SMALL * gh]
    if not big:
        return "?" * len(row)
    hs = sorted(g["h"] for g in big)
    gh = float(np.median(hs[: max(1, int(0.8 * len(hs)))]))  # the cap height of this row (parens are taller, (T) rows smaller)
    c0 = np.median([g["c"] for g in big], axis=0)  # the line itself, not pulled up by the symbols
    ang = np.degrees(np.arctan2(u[1], u[0]))
    # a 24-px bitmap is angle-sensitive (2 deg costs 1-4): each glyph takes the best of a few angles about the row's
    dist = {id(g): np.min([M.dist(bitmap(g, ang + da, gh)[None, :])[0] for da in (-3, -1.5, 0, 1.5, 3)], axis=0) for g in big}

    def read(g, among=None):
        d = dist[id(g)]
        ok = np.isin(M.Y, list(among)) if among else np.ones(len(M.Y), bool)
        if not ok.any():
            return "?"
        k = int(np.where(ok)[0][d[ok].argmin()])
        if d[k] < (COARSE if among else JUNK):  # a slot's letters come from the seed font: looser
            return str(M.Y[k])
        if M.S is not None and not among:  # a bolder variant of the same character: same stroke count, looser bitmap
            same = ok & (M.S == len(g["strokes"]))
            if same.any():
                k2 = int(np.where(same)[0][d[same].argmin()])
                if d[k2] < 2 * JUNK:
                    return str(M.Y[k2])
        return "?"

    tall = lambda g: g["h"] > 1.2 * gh
    # (R) / (T): two tall parens round one capital, at the end
    suffix = ""
    if len(big) >= 3 and tall(big[-3]) and tall(big[-1]) and not tall(big[-2]):
        suffix = "(" + read(big[-2], "RT") + ")"
        big = big[:-3]
    chars = {id(g): read(g) for g in big}
    letters = [g for g in big if not chars[id(g)].isdigit()]
    tops = [g for g in small if (g["c"] - c0) @ n < -0.35 * gh]
    bases = [g for g in small if (g["c"] - c0) @ n > 0.35 * gh]
    mids = [g for g in small if abs((g["c"] - c0) @ n) <= 0.35 * gh]
    sym = {}
    if len(tops) >= 4:
        names = ["°", "'", '"', ""] + [""] * (len(tops) - 4)  # the seconds mark is two ticks: one symbol
    elif len(tops) == 3:
        names = ["°", "'", '"']
    elif len(tops) == 2:
        names = ["°", "'"]
    else:
        names = ["'"] * len(tops)
    for g, s in zip(sorted(tops, key=lambda g: (g["c"] - c0) @ u), names):
        sym[id(g)] = s
    for g in bases:
        sym[id(g)] = "." if g["h"] < 1.0 else ("-" if g["single"] else ",")
    mids.sort(key=lambda g: (g["c"] - c0) @ u)
    k = 0
    while k < len(mids):
        if k + 1 < len(mids) and abs((mids[k + 1]["c"] - mids[k]["c"]) @ u) < 0.4 * gh:
            sym[id(mids[k])], sym[id(mids[k + 1])] = "=", ""; k += 2
        else:
            sym[id(mids[k])] = "-"; k += 1
    # letter slots: a bearing is N|S ... E|W; curve data starts R= or L=
    has_deg = any(s == "°" for s in sym.values())
    if letters and has_deg and letters[0] is big[0]:
        chars[id(big[0])] = read(big[0], "NS")
        if len(letters) >= 2 and letters[-1] is big[-1]:
            chars[id(big[-1])] = read(big[-1], "EW")
    if len(big) >= 2 and mids and not chars[id(big[0])].isdigit() and big[0]["c"] @ u < mids[0]["c"] @ u < big[1]["c"] @ u:  # R= L= Δ=
        chars[id(big[0])] = read(big[0], "RL") if not has_deg else "Δ"
    if len(big) >= 4 and sum(1 for s in sym.values() if s == ",") >= 1 and not chars[id(big[0])].isdigit() and all(chars[id(g)].isdigit() for g in big[1:]):
        chars[id(big[0])] = read(big[0], "NE")  # a coordinate callout: N 2,120,414.20
        if chars[id(big[0])] == "?":
            chars[id(big[0])] = ""  # the N/E letter is lettering the alphabet lacks; the pairing rule (E is the larger) still applies
        for g in mids:  # an E's loose bars in front of the digits go with the letter
            if (g["c"] - big[1]["c"]) @ u < 0:
                sym[id(g)] = ""
    out = "".join(chars.get(id(g), sym.get(id(g), "?")) for g in sorted(big + small, key=lambda g: (g["c"] - c0) @ u))
    return out + suffix


def merge_pieces(row, c, u, n, gh):
    """Characters from the paths in one row of a block: a path inside another's width (an E's bars) or
    overlapping it along the line (a drafter's font that draws an N as three paths) joins it. Drops
    stray ticks. Each glyph gets al/x0/x1 along the reading axis u from the block centre c."""
    for g in row:
        P = np.vstack(g["strokes"]); ext = ((P - c) @ u)
        g["x0"], g["x1"] = ext.min(), ext.max()
        g["al"] = float((g["c"] - c) @ u)
    row = sorted(row, key=lambda g: g["al"])
    merged = []
    for g in row:
        small_g = eff_h(g, n) <= SMALL * gh
        inside = merged and g["x0"] >= merged[-1]["x0"] - 0.1 * gh and g["x1"] <= merged[-1]["x1"] + 0.1 * gh  # a bar within a letter's width
        if merged and (inside or (g["x0"] < merged[-1]["x1"] - 0.15 * gh and not (small_g and eff_h(merged[-1], n) <= SMALL * gh))):
            m = merged[-1]; m["strokes"] = m["strokes"] + g["strokes"]; Q = np.vstack(m["strokes"])
            m["c"] = (Q.min(0) + Q.max(0)) / 2; m["h"] = float((Q.max(0) - Q.min(0)).max()); m["x1"] = max(m["x1"], g["x1"]); m["single"] = False
        else:
            merged.append(g)
    return [g for g in merged if not (g["single"] and g["h"] < 0.5 * gh and eff_h(g, n) > 0.3 * gh)]  # a stray tick (short, across the line) is not a character


def main():
    page = pymupdf.open(PDF)[0]
    W, H = page.rect.width, page.rect.height
    blocks = json.loads((OUT / "blocks.json").read_text(encoding="utf-8"))
    z = np.load(OUT / "alphabet.npz")
    if len(z["Y"]) < 12:
        (OUT / "read_glyph.json").write_text("[]", encoding="utf-8"); print("no alphabet for this sheet: nothing read by glyph"); return
    M = Matcher(z["X"], z["Y"], z["S"] if "S" in z else None)
    G = glyphs(page)
    tree = cKDTree(np.array([g["c"] for g in G]))
    votes = characters(G, M, 0, 0, W, H)  # coarse best angle per multi-stroke glyph
    out = []
    unread = 0
    for b in blocks:
        u0, n0 = axes(b["angle"])
        c = np.array([b["cx"], b["cy"]])
        ids = [i for i in tree.query_ball_point(c, b["w"] / 2 + b["h"] + b["glyph_h"])
               if abs((G[i]["c"] - c) @ u0) < b["w"] / 2 + 0.6 * b["glyph_h"] and abs((G[i]["c"] - c) @ n0) < b["h"] / 2 + 0.4 * b["glyph_h"]
               and not G[i].get("arrow") and not (G[i].get("connected") and not G[i]["single"]) and 0.3 < G[i]["h"] < 2.0 * b["glyph_h"]]  # a box's corner arcs touch its lines; characters touch nothing
        if not ids:
            out.append({**b, "text": "", "conf": 0.0}); continue
        gh = b["glyph_h"]
        # reading angle: the members' votes (mod 180), refined by total match cost, both senses
        va = [votes[i][1] for i in ids if i in votes]
        base = float(np.degrees(np.arctan2(np.sin(np.radians(2 * np.array(va))).mean(), np.cos(np.radians(2 * np.array(va))).mean())) / 2) if va else b["angle"]
        bigs = [i for i in ids if not G[i]["single"] and G[i]["h"] > SMALL * gh]
        best = None
        for sense in (base, base + 180):
            for a in np.arange(sense - 2 * STEP, sense + 2 * STEP + 1, 2.0):
                cost = sum(M.dist(bitmap(G[i], a, gh)[None, :])[0].min() for i in bigs[:12]) if bigs else 0
                if best is None or cost < best[0]:
                    best = (cost, float((a + 180) % 360 - 180))
        angle = best[1]
        u, n = axes(angle)
        gs = [dict(G[i]) for i in ids]
        for g in gs:
            g["al"], g["pe"] = (g["c"] - c) @ u, (g["c"] - c) @ n
        # rows by height, then within a row merge a small path inside a capital (an E's bars)
        caps = sorted([g for g in gs if eff_h(g, n) > SMALL * gh], key=lambda g: g["pe"])
        syms = [g for g in gs if eff_h(g, n) <= SMALL * gh]
        if not caps:
            out.append({**b, "angle": round(angle, 2), "text": "", "conf": 0.0}); continue
        rows, cur = [], [caps[0]]
        for g in caps[1:]:
            if g["pe"] - cur[-1]["pe"] > 0.6 * gh:
                rows.append(cur); cur = []
            cur.append(g)
        rows.append(cur)
        centres = [float(np.median([g["pe"] for g in r_])) for r_ in rows]
        for g in syms:  # a symbol belongs to the line it sits on; one with no capitals near it is a stray
            k = int(np.argmin([abs(g["pe"] - cpe) for cpe in centres]))
            if abs(g["pe"] - centres[k]) < 0.8 * gh:
                rows[k].append(g)
        texts = []
        for row in rows:
            merged = merge_pieces(row, c, u, n, gh)
            if merged:
                texts.append(read_row(merged, u, n, gh, M))
        text = "|".join(t for t in texts if t)
        unread += text.count("?")
        out.append({**b, "angle": round(angle, 2), "text": text, "conf": 1.0 if "?" not in text and text else 0.0})
    (OUT / "read_glyph.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    full = sum(1 for b in out if b["conf"] == 1.0)
    print(f"read {len(out)} blocks by glyph: {full} fully read, {unread} unread glyphs")


if __name__ == "__main__":
    main()
