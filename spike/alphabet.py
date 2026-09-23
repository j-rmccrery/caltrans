"""A sheet's own alphabet and its tables, with no keying: the tables' NO. column is a known sequence.

Seed: the public-domain Hershey simplex font (parent of AutoCAD's txt/simplex), close to this
lettering but not exact. With it, find NO.-column cells that read as L<n> / C<n>, validate that they
run 1, 2, 3 ... down a column, and take those cells' glyphs as exact exemplars for digits, L and C.
Second pass with the exact glyphs finds the columns the seed misread. Then the cells to the right in
each row are labelled by structure: cap-height glyphs are digits or letters, the small glyphs are the
symbols in a fixed order (° ' " in a bearing or delta; . and ' in a distance). Everything downstream
reads against the sheet's exact glyphs. On the Presidio sheet the hand-keyed tables (gt.py) become a
validation set, not an input.

Writes spike/out[/<sheet>]/alphabet.npz (bitmaps X, labels Y) and tables.json ({tag: row}).
usage: [SHEET=<pdf>] python spike/alphabet.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from HersheyFonts import HersheyFonts
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from blocks import OUT, PDF  # noqa: E402
from read_glyphs import merge_pieces  # noqa: E402
from tags import Matcher, axes, bitmap, glyphs  # noqa: E402

SEED_JUNK = 9.0   # the font is close, not exact: the sheet's 0 and 6 sit at 5-7 from Hershey's
EXACT_JUNK = 5.0
FREE_JUNK = 14.0  # without tables to validate against, the seed's pick per character is the closest third under this; other fonts sit at 10-13
SMALL = 0.45      # of glyph height: ° ' " . are 1.3-2.0 pt beside 6.5-pt capitals


def seed_exemplars(chars="0123456789LCNSEWRT()"):
    f = HersheyFonts(); f.load_default_font("futural"); f.normalize_rendering(10.0)
    X, Y = [], []
    for ch in chars:
        strokes = [[(x0, -y0), (x1, -y1)] for (x0, y0), (x1, y1) in f.lines_for_text(ch)]
        P = np.vstack(strokes)
        g = {"strokes": strokes, "c": (P.min(0) + P.max(0)) / 2, "h": (P.max(0) - P.min(0)).max()}
        X.append(bitmap(g, 0.0, g["h"])); Y.append(ch)
    return np.array(X), np.array(Y)


def cells(G, blocks, tree, upright=True):
    """Upright text blocks as ordered glyph lists (multi-stroke glyphs; a lone stroke is an E's middle bar).
    upright=False takes every block along its own axis, single strokes included so a letter's bars merge
    into it (bitmaps then need the block's angle)."""
    out = []
    for b in blocks:
        if upright and abs(b["angle"]) > 2:
            continue
        u, n = axes(0.0 if upright else b["angle"])
        c = np.array([b["cx"], b["cy"]])
        ids = [i for i in tree.query_ball_point(c, b["w"] / 2 + b["h"]) if (upright and not G[i]["single"]) or (not upright and 0.3 < G[i]["h"] < 2.0 * b["glyph_h"])
               and abs((G[i]["c"] - c) @ u) < b["w"] / 2 + 0.6 * b["glyph_h"] and abs((G[i]["c"] - c) @ n) < b["h"] / 2 + 0.3 * b["glyph_h"]]
        gs = merge_pieces([dict(G[i]) for i in ids], c, u, n, b["glyph_h"]) if ids else []  # a font that draws a letter as several paths
        if gs:
            out.append({"b": b, "ids": gs})
    return out


def read(M, G, cell, junk):
    s = ""
    for i in cell["ids"]:
        d = M.dist(bitmap(i, 0.0, cell["b"]["glyph_h"])[None, :])[0]
        k = int(d.argmin())
        s += M.Y[k] if d[k] < junk else "?"
    return s


def free_alphabet(seed, G, cs):
    """Alphabet for a sheet without line/curve tables: the font seed picks each character's closest
    sheet glyphs, those become the exemplars, and a second pass with them widens the set. Nothing
    validates it here; the georeference's control-point consensus does (a misread coordinate is
    an outlier there, not a fit)."""
    B = [(bitmap(i, c["b"]["angle"], c["b"]["glyph_h"]), len(i["strokes"])) for c in cs for i in c["ids"]]  # rotated blocks too: grid labels run along the border
    if not B:
        return np.zeros((0, 576), np.float32), np.array([], dtype="<U1"), np.array([], int)
    bits = np.array([b for b, _ in B]); strokes = np.array([s for _, s in B])
    X, Y, S = [], [], []
    for M, junk, share in ((seed, FREE_JUNK, 0.3), (None, 3.0, 1.0)):
        M = M or Matcher(np.array(X), np.array(Y))
        d = M.dist(bits); k = d.argmin(1); best = d[np.arange(len(bits)), k]
        X, Y, S = [], [], []
        for ch in set(M.Y):
            hit = np.where((M.Y[k] == ch) & (best < junk))[0]
            hit = hit[np.argsort(best[hit])][:max(3, int(share * len(hit)))]  # pass 1: only the closest third of each character
            X += list(bits[hit]); Y += [ch] * len(hit); S += list(strokes[hit])
        if not X:
            break
    X, Y, S = np.array(X), np.array(Y), np.array(S)
    _, keep = np.unique(X.round(2), axis=0, return_index=True) if len(X) else (None, np.array([], int))
    return X[keep], Y[keep], S[keep]


def no_columns(M, G, cs, junk, taken):
    """Runs of L<n> / C<n> cells one below the other, numbered consecutively: the tables' NO. columns.
    A cell whose read disagrees with its position is relabelled from the position as long as most of
    the column agrees."""
    tagged = [(c, read(M, G, c, junk)) for c in cs if 2 <= len(c["ids"]) <= 6 and id(c) not in taken]
    tagged = [(c, s[:-3] if len(s) > 3 else s) for c, s in tagged if re.match(r"^[LC0O?][\d?]{1,2}([?A-Z()]{3})?$", s)]  # L14(T) too
    cols, used = [], set()
    for k, (c, s) in enumerate(tagged):
        if k in used:
            continue
        col, x, pitch = [(k, c, s)], c["b"]["cx"], None
        while True:
            last = col[-1][1]["b"]
            nxt = [(j, cj, sj) for j, (cj, sj) in enumerate(tagged) if j not in used and j not in {q[0] for q in col}
                   and abs(cj["b"]["cx"] - x) < 12 and 6 < cj["b"]["cy"] - last["cy"] < 30 and (pitch is None or abs(cj["b"]["cy"] - last["cy"] - pitch) < 3)]
            if not nxt:
                break
            j, cj, sj = min(nxt, key=lambda t: t[1]["b"]["cy"])
            pitch = pitch or cj["b"]["cy"] - last["cy"]
            col.append((j, cj, sj))
        if len(col) < 4:
            continue
        letter = "L" if sum(s[0] == "L" for _, _, s in col) > len(col) / 2 else "C"
        nums = [(i, int(re.sub(r"\D", "", s))) for i, (_, _, s) in enumerate(col) if re.sub(r"\D", "", s).isdigit()]
        if not nums:
            continue
        starts = [n - i for i, n in nums]
        start = max(set(starts), key=starts.count)
        if sum(n == start + i for i, n in nums) < 0.6 * len(col):
            continue
        # the rows above the first read cell (L1, L2 sit under the header and read badly): by position
        first = col[0][1]["b"]
        above = []
        while start - len(above) > 1 and pitch:
            y = first["cy"] - (len(above) + 1) * pitch
            cand = [c2 for c2 in cs if id(c2) not in taken and abs(c2["b"]["cx"] - x) < 12 and abs(c2["b"]["cy"] - y) < 3 and 2 <= len(c2["ids"]) <= 6]
            if not cand:
                break
            above.append(cand[0])
        used.update(q[0] for q in col)
        cols.append({"letter": letter, "start": start - len(above), "cells": above[::-1] + [c for _, c, _ in col]})
    return cols


def row_cells(G, tree, b, rules=(), x_max=420):
    """The glyphs in a table row to the right of its NO. cell, as cells split at column gaps. Paths that
    overlap in x are one character (an E is a two-stroke path plus its middle bar)."""
    gh = b["glyph_h"]
    c = np.array([b["cx"] + x_max / 2, b["cy"]])
    ids = [i for i in tree.query_ball_point(c, x_max / 2 + gh) if G[i]["c"][0] > b["cx"] + 0.8 * gh and abs(G[i]["c"][1] - b["cy"]) < 0.6 * b["h"] + 1
           and 0.3 < G[i]["h"] < 2.0 * gh]
    ids.sort(key=lambda i: G[i]["c"][0])
    glyphs_ = []
    for i in ids:
        P = np.vstack(G[i]["strokes"]); x0, x1 = P[:, 0].min(), P[:, 0].max()
        small_i, small_last = G[i]["h"] <= SMALL * gh, bool(glyphs_) and glyphs_[-1]["h"] <= SMALL * gh
        if glyphs_ and x0 < glyphs_[-1]["x1"] - 0.15 * gh and not (small_i and small_last):  # a path inside a capital: an E's bars
            g = glyphs_[-1]
            g["strokes"] = g["strokes"] + G[i]["strokes"]; Q = np.vstack(g["strokes"])
            g["c"] = (Q.min(0) + Q.max(0)) / 2; g["h"] = float((Q.max(0) - Q.min(0)).max()); g["x1"] = max(g["x1"], x1); g["single"] = False
        else:
            glyphs_.append({"strokes": list(G[i]["strokes"]), "c": G[i]["c"].copy(), "h": G[i]["h"], "single": G[i]["single"], "x1": x1})
    # split at the table's vertical rules through this row, else at wide gaps
    xs = sorted(x for x, y0, y1 in rules if y0 - 1 < b["cy"] < y1 + 1 and b["cx"] < x < b["cx"] + x_max)
    cells_, cur = [], []
    for g in glyphs_:
        if cur and (g["c"][0] - cur[-1]["x1"] > 1.6 * gh or any(cur[-1]["x1"] < x < g["c"][0] for x in xs)):
            cells_.append(cur); cur = []
        cur.append(g)
    if cur:
        cells_.append(cur)
    return [c_ for c_ in cells_ if not (len(c_) == 1 and c_[0]["single"])]


def label_row_cell(gs, gh, kind_hint, M):
    """Label a table cell's glyphs by structure. Returns (value string, [(glyph, char)]) or None.
    big = cap-height glyph (digit or letter), small = symbol; order decides which symbol."""
    big = [g for g in gs if g["h"] > SMALL * gh]
    small = [g for g in gs if g["h"] <= SMALL * gh]
    if not big:
        return None
    gh = float(np.median([g["h"] for g in big if g["h"] < 1.4 * gh] or [gh]))  # the cell's own cap height: (T) rows are set smaller
    reads = {}
    for g in big:
        d = M.dist(bitmap(g, 0.0, gh)[None, :])[0]; k = int(d.argmin())
        reads[id(g)] = M.Y[k] if d[k] < EXACT_JUNK else "?"
    r = lambda g: reads[id(g)]
    suffix, suffix_lab = "", []
    if len(big) >= 6 and big[-3]["h"] > 1.25 * gh and big[-1]["h"] > 1.25 * gh and big[-2]["h"] < 1.25 * gh:  # (T): two tall parens round a capital
        d = M.dist(bitmap(big[-2], 0.0, gh)[None, :])[0]; ok = np.isin(M.Y, list("RT"))
        letter = str(M.Y[ok][int(d[ok].argmin())]) if ok.any() else "T"
        suffix, suffix_lab = f"({letter})", list(zip(big[-3:], f"({letter})"))
        big = big[:-3]
    nb, ns = len(big), len(small)

    def among(g, letters):  # nearest of a few letters, for the N|S and E|W slots of a bearing
        d = M.dist(bitmap(g, 0.0, gh)[None, :])[0]
        ok = np.isin(M.Y, list(letters))
        return str(M.Y[ok][int(d[ok].argmin())])
    if nb >= 7 and ns in (4, 5) and all(r(g).isdigit() for g in big[1:-1]) and not r(big[0]).isdigit() and not r(big[-1]).isdigit():  # bearing: N dd° mm' ss" E
        reads[id(big[0])], reads[id(big[-1])] = among(big[0], "NS"), among(big[-1], "EW")
        digits = big[1:-1]
        if len(digits) not in (5, 6) or not all(r(g).isdigit() for g in digits):
            return None
        nd = len(digits) - 4
        text = r(big[0]) + "".join(r(g) for g in digits[:nd]) + "°" + "".join(r(g) for g in digits[nd:nd + 2]) + "'" + "".join(r(g) for g in digits[nd + 2:]) + '"' + r(big[-1])
        lab = [(g, r(g)) for g in big] + list(zip(small, ["°", "'", '"', '"', '"']))
        return text + suffix, lab + suffix_lab
    if nb >= 5 and all(r(g).isdigit() for g in big) and ns in (4, 5):  # delta: ddd° mm' ss"
        nd = nb - 4
        text = "".join(r(g) for g in big[:nd]) + "°" + "".join(r(g) for g in big[nd:nd + 2]) + "'" + "".join(r(g) for g in big[nd + 2:]) + '"'
        return text + suffix, [(g, r(g)) for g in big] + list(zip(small, ["°", "'", '"', '"', '"'])) + suffix_lab
    if nb >= 3 and all(r(g).isdigit() for g in big) and ns in (1, 2):  # distance: d+ . dd '
        dot = max(small, key=lambda g: g["c"][1])  # the lowest small glyph is the point
        k = sum(1 for g in big if g["c"][0] < dot["c"][0])
        text = "".join(r(g) for g in big[:k]) + "." + "".join(r(g) for g in big[k:]) + ("'" if ns == 2 else "")
        return text + suffix, [(g, r(g)) for g in big] + [(dot, ".")] + [(g, "'") for g in small if g is not dot] + suffix_lab
    return None


def main():
    page = pymupdf.open(PDF)[0]
    blocks = json.loads((OUT / "blocks.json").read_text(encoding="utf-8"))
    G = glyphs(page)
    tree = cKDTree(np.array([g["c"] for g in G]))
    cs = cells(G, blocks, tree)
    seed = Matcher(*seed_exemplars())
    from checks import linework_segments
    rules = [(float(a[0]), float(min(a[1], b_[1])), float(max(a[1], b_[1]))) for a, b_, w, _ in linework_segments(page, 0.7) if abs(a[0] - b_[0]) < 0.5 and abs(a[1] - b_[1]) > 8]

    X, Y, S, taken, cols = [], [], [], set(), []
    M = seed
    for junk in (SEED_JUNK, EXACT_JUNK):  # pass 1 with the font, pass 2 with the sheet's own digits
        new = no_columns(M, G, cs, junk, taken)
        for col in new:
            for i, c in enumerate(col["cells"]):
                taken.add(id(c))
                t = f"{col['letter']}{col['start'] + i}"
                t = t + "(T)" if len(c["ids"]) == len(t) + 3 else t
                if len(c["ids"]) == len(t):
                    for gi, ch in zip(c["ids"], t):
                        X.append(bitmap(gi, 0.0, c["b"]["glyph_h"])); Y.append(ch); S.append(len(gi["strokes"]))
        cols += new
        if not X:
            X, Y, S = free_alphabet(seed, G, cells(G, blocks, tree, upright=False))
            np.savez(OUT / "alphabet.npz", X=X, Y=Y, S=S)
            (OUT / "tables.json").write_text("{}", encoding="utf-8")
            print(f"no NO. column: no tables; alphabet from the font seed alone, {len(Y)} exemplars over {''.join(sorted(set(Y)))}"); return
        M = Matcher(np.array(X + list(seed.X[np.isin(seed.Y, list("NSEWRT"))])), np.array(Y + [y for y in seed.Y if y in "NSEWRT"]))
    print("NO. columns:", [(c["letter"], c["start"], len(c["cells"])) for c in cols])

    # rows: cells to the right of each NO. cell, labelled by structure; their glyphs join the alphabet
    rows, lab_all = {}, []
    for col in cols:
        kind = "line" if col["letter"] == "L" else "curve"
        for i, c in enumerate(col["cells"]):
            tag = f"{col['letter']}{col['start'] + i}"
            b = c["b"]
            vals = []
            for k, gs in enumerate(row_cells(G, tree, b, rules)):
                if len(vals) < (2 if kind == "line" else 3):  # the table's own columns; a neighbouring table shares the rows
                    col["x1"] = max(col.get("x1", 0), max(g["x1"] for g in gs))
                r = label_row_cell(gs, b["glyph_h"], "", M)
                if r is None and len(gs) <= 1:
                    continue  # a stray piece in the row (a rule end, a tick), not a cell
                if r is None and k == 0 and len(gs) in (2, 3) and not vals:  # the "(T)" after a total's tag, split from it
                    if len(gs) == 3:
                        lab_all += [(g, ch, b["glyph_h"]) for g, ch in zip(gs, "(T)")]
                    continue
                vals.append(r[0] if r else "?" * len(gs))
                if r:
                    lab_all += [(g, ch, b["glyph_h"]) for g, ch in r[1]]
            rows[tag] = {"kind": kind, "cells": vals}
    for g, ch, gh in lab_all:
        X.append(bitmap(g, 0.0, gh)); Y.append(ch); S.append(len(g["strokes"]))
    # widen: every upright glyph on the sheet that matches the alphabet almost exactly joins it, so
    # the drawing's slightly different renderings of a character (size, spacing) are covered too
    M = Matcher(np.array(X), np.array(Y))
    added = 0
    for c in cs:
        for i in c["ids"]:
            b_ = bitmap(i, 0.0, c["b"]["glyph_h"])
            d = M.dist(b_[None, :])[0]; k = int(d.argmin())
            if d[k] < 1.5 and M.Y[k] in "0123456789LC":
                X.append(b_); Y.append(M.Y[k]); S.append(len(i["strokes"])); added += 1
    X, Y, S = np.array(X), np.array(Y), np.array(S)
    _, keep = np.unique(X.round(2), axis=0, return_index=True)
    np.savez(OUT / "alphabet.npz", X=X[keep], Y=Y[keep], S=S[keep])
    # where the tables sit (so the drawing's tag reader leaves them alone): each NO. column with its rows
    regions = []
    for col in cols:
        ys = [c["b"]["cy"] for c in col["cells"]]; x0 = min(c["b"]["cx"] for c in col["cells"]) - 20
        regions.append([round(x0), round(min(ys) - 30), round(col.get("x1", x0 + 200) + 12), round(max(ys) + 14)])
    rows["_regions"] = regions
    (OUT / "tables.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"alphabet: {len(keep)} distinct exemplars over {''.join(sorted(set(Y)))} ({added} self-matched); rows read: {len(rows)}")

    # validation where keyed truth exists (the Presidio sheet)
    try:
        from gt import TABLES
        truth = {}
        L = TABLES["line"][1]
        for k in range(0, len(L), 3):
            truth[L[k].replace("(T)", "")] = [L[k + 1], L[k + 2]]
        for name in ("curve1", "curve2"):
            C = TABLES[name][1]
            for k in range(0, len(C), 4):
                truth[C[k].replace("(T)", "")] = [C[k + 1], C[k + 2], C[k + 3]]
        ok = tot = 0
        wrong = []
        for tag, r in rows.items():
            if tag not in truth:
                continue
            for got, want in zip(r["cells"], truth[tag]):
                tot += 1
                w = want.replace("(R)", "")
                if got == w:
                    ok += 1
                else:
                    wrong.append((tag, got, w))
        print(f"vs keyed tables: {ok}/{tot} cells exact ({len(truth) - len(set(rows) & set(truth))} truth rows not found: {sorted(set(truth) - set(rows), key=lambda s: (s[0], int(s[1:])))})")
        for w in wrong[:12]:
            print("   ", w)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
