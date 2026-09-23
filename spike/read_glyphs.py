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
import re
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
    """row: glyph dicts sorted along u. Returns (text, labels): '?' where a glyph does not read; labels =
    [(glyph, char, cap height used)] for the capitals, so a row that parses can teach the alphabet."""
    big = [g for g in row if eff_h(g, n) > SMALL * gh]
    small = [g for g in row if eff_h(g, n) <= SMALL * gh]
    if not big:
        return "?" * len(row), []
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
        if among:  # a slot names its few candidates (N|S, E|W, R|T): the nearer wins if it wins clearly, however far the seed font sits
            others = d[ok & (M.Y != M.Y[k])]
            return str(M.Y[k]) if d[k] < COARSE or (len(others) and others.min() > 1.3 * d[k]) else "?"
        if d[k] < JUNK:
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
    suffix, suffix_lab = "", []
    if len(big) >= 3 and tall(big[-3]) and tall(big[-1]) and not tall(big[-2]):
        suffix = "(" + read(big[-2], "RT") + ")"
        suffix_lab = [(big[-2], suffix[1], gh)]
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
    # by structure: the low mark with exactly two capitals after it (and none after those) is the decimal
    # point, whatever its size in this font; one with three after it before the next mark is a thousands comma
    low = sorted([g for g in bases if not g["single"]], key=lambda g: (g["c"] - c0) @ u)
    for j, g in enumerate(low):
        after = [h for h in big if (h["c"] - g["c"]) @ u > 0 and (j + 1 >= len(low) or (h["c"] - low[j + 1]["c"]) @ u < 0)]
        if j + 1 == len(low) and (len(after) == 2 or (len(after) == 3 and len(low) == 1)):  # 48.55 or a metric 48.620
            sym[id(g)] = "."
        elif len(after) == 3:
            sym[id(g)] = ","
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
    return out + suffix, [(g, chars[id(g)], gh) for g in big] + suffix_lab


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
    validated = (OUT / "tables.json").exists() and len(json.loads((OUT / "tables.json").read_text(encoding="utf-8"))) > 1
    X, Y, S = list(z["X"]), list(z["Y"]), list(z["S"]) if "S" in z else [0] * len(z["Y"])
    if not validated:  # the slot letters the seed-only alphabet lacks, from the font: a slot read is relative, so a poor fit still decides
        from alphabet import seed_exemplars
        sx, sy = seed_exemplars("NSEWRT")
        for x, y in zip(sx, sy):
            if y not in Y:
                X.append(x); Y.append(y); S.append(0)
        seed = Matcher(sx, sy)
        M = Matcher(np.array(X), np.array(Y), np.array(S))
        sX, sY, sS, slots0 = structure_seed(blocks, G, tree, votes, M, Matcher(*seed_exemplars("0123456789")))
        if sX:
            X, Y, S = X + sX, Y + sY, S + sS
            resolve_slots(slots0, seed, X, Y, S)
            M = Matcher(np.array(X), np.array(Y), np.array(S))
    for round_ in range(1 if validated else 4):
        out, unread, learned, slots = read_all(page, blocks, G, tree, votes, M, X, Y, S)
        if not validated:
            learned += resolve_slots(slots, seed, X, Y, S)
        if validated or not learned:
            break
        # a row that parses as a whole token is right with the odds of a chance parse: its glyphs are exact exemplars
        print(f"  round {round_ + 1}: {sum(1 for b in out if b['conf'] == 1.0)} blocks read, {learned} glyphs learned from rows that parse")
        M = Matcher(np.array(X), np.array(Y), np.array(S))
    (OUT / "read_glyph.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    full = sum(1 for b in out if b["conf"] == 1.0)
    print(f"read {len(out)} blocks by glyph: {full} fully read, {unread} unread glyphs")


VALID = re.compile(r"^(?:[NS]\d{1,2}°\d{2}'\d{2}\"[EW](?:\(R\))?|\d{1,4}\.\d{2,3}'?(?:\(T\))?|[NE]?\d{1,3}(?:,\d{3})+\.\d{2,3}|[RL]=\d{1,5}\.\d{2}'?|Δ=\d{1,3}°\d{2}'\d{2}\"|\d{1,4}\+\d{2}(?:\.\d{2})?)$")


SHAPE = re.compile(r"^([NS?])\d{1,2}°\d{2}'\d{2}\"([EW?])(?:\(R\))?$")  # a bearing whose letter slots may be unread


def resolve_slots(slots, seed, X, Y, S):
    """The first glyph of a bearing is an N or an S, the last an E or a W. Pool the unread slot glyphs of
    every bearing-shaped row, cluster them by bitmap (two shapes at most), and let the seed font say
    which cluster is which: a relative call it can make even where its absolute distances are poor."""
    added = 0
    for pair, pool in slots.items():
        if len(pool) < 3:
            continue
        B = np.array([b for b, _, _ in pool])
        D = np.sqrt(np.maximum((B ** 2).sum(1)[:, None] + (B ** 2).sum(1)[None, :] - 2 * B @ B.T, 0))
        left, clusters = set(range(len(B))), []
        while left:
            k = max(left, key=lambda i: (D[i, list(left)] < 3.0).sum())
            members = [i for i in left if D[k, i] < 3.0]
            clusters.append(members); left -= set(members)
        clusters = [c for c in sorted(clusters, key=len, reverse=True)[:2] if len(c) >= 2]
        if not clusters:
            continue
        a, b = pair
        sa, sb = seed.X[seed.Y == a], seed.X[seed.Y == b]
        lean = [float(np.median(seed.dist(B[c])[:, seed.Y == a].min(1)) - np.median(seed.dist(B[c])[:, seed.Y == b].min(1))) for c in clusters]
        labels = [a if l < 0 else b for l in lean]
        if len(clusters) == 2 and labels[0] == labels[1]:  # both lean one way: the one leaning more is it, the other is the other letter
            labels = [a, b] if lean[0] < lean[1] else [b, a]
        for c, lab in zip(clusters, labels):
            for i in c:
                X.append(B[i]); Y.append(lab); S.append(pool[i][2]); added += 1
        print(f"  slot {pair}: {len(pool)} glyphs, clusters {[len(c) for c in clusters]} -> {labels}")
    return added


def block_rows(b, G, tree, votes, M):
    """A block's glyphs at its refined reading angle, as rows of merged glyphs sorted along the line.
    Returns (angle, u, n, centre, glyph height, rows) or None when the block holds no glyph."""
    u0, n0 = axes(b["angle"])
    c = np.array([b["cx"], b["cy"]])
    ids = [i for i in tree.query_ball_point(c, b["w"] / 2 + b["h"] + b["glyph_h"])
           if abs((G[i]["c"] - c) @ u0) < b["w"] / 2 + 0.6 * b["glyph_h"] and abs((G[i]["c"] - c) @ n0) < b["h"] / 2 + 0.4 * b["glyph_h"]
           and not G[i].get("arrow") and not (G[i].get("connected") and not G[i]["single"]) and 0.3 < G[i]["h"] < 2.0 * b["glyph_h"]]  # a box's corner arcs touch its lines; characters touch nothing
    if not ids:
        return None
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
        return angle, u, n, c, gh, []
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
    return angle, u, n, c, gh, [m for m in (merge_pieces(row, c, u, n, gh) for row in rows) if m]


def structure_seed(blocks, G, tree, votes, M, seed):
    """An alphabet's digits with no font to trust: the rows shaped like a bearing (eight capitals round
    three raised marks) or a distance (capitals, one low mark, two capitals after it) say which glyphs
    are digits. Those glyphs are clustered by bitmap; the ten biggest clusters are matched one-to-one
    to the seed font's digits (an assignment, not ten absolute calls), and the members become
    exemplars. The letter slots of the bearing rows go to resolve_slots. Returns (X, Y, S, slots)."""
    pool, slots = [], {"NS": [], "EW": []}
    for b in blocks:
        br = block_rows(b, G, tree, votes, M)
        if br is None:
            continue
        angle, u, n, c, gh, rows = br
        for row in rows:
            big = [g for g in row if eff_h(g, n) > SMALL * gh]
            small = [g for g in row if eff_h(g, n) <= SMALL * gh]
            if len(big) < 3:
                continue
            hs = sorted(g["h"] for g in big)
            ghr = float(np.median(hs[: max(1, int(0.8 * len(hs)))]))
            c0 = np.median([g["c"] for g in big], axis=0)
            tops = [g for g in small if (g["c"] - c0) @ n < -0.35 * ghr]
            bases = [g for g in small if (g["c"] - c0) @ n > 0.35 * ghr]
            tall = lambda g: g["h"] > 1.2 * ghr
            if len(big) >= 3 and tall(big[-3]) and tall(big[-1]) and not tall(big[-2]):
                big = big[:-3]  # (R)
            digits = []
            if len(big) == 8 and 3 <= len(tops) <= 4 and not bases:  # N dd ° dd ' dd " E
                digits = big[1:7]
                slots["NS"].append((bitmap(big[0], angle, ghr), big[0], len(big[0]["strokes"])))
                slots["EW"].append((bitmap(big[7], angle, ghr), big[7], len(big[7]["strokes"])))
            elif len(bases) == 1 and len(tops) <= 1 and 3 <= len(big) <= 6 and sum(1 for g in big if (g["c"] - bases[0]["c"]) @ u > 0) == 2:  # ddd.dd'
                digits = big
            for g in digits:
                pool.append((bitmap(g, angle, ghr), len(g["strokes"])))
    if len(pool) < 10:
        return [], [], [], slots
    B = np.array([x for x, _ in pool]); ST = np.array([k for _, k in pool])
    D = np.maximum((B ** 2).sum(1)[:, None] + (B ** 2).sum(1)[None, :] - 2 * B @ B.T, 0)
    left, clusters = set(range(len(B))), []
    while left:
        k = max(left, key=lambda i: (D[i, list(left)] < 2.0).sum())
        members = [i for i in left if D[k, i] < 2.0]
        clusters.append(members); left -= set(members)
    clusters = [cl for cl in sorted(clusters, key=len, reverse=True) if len(cl) >= 2][:12]
    dig = [ch for ch in "0123456789" if ch in seed.Y]
    cost = np.array([[float(np.median(seed.dist(B[cl])[:, seed.Y == ch].min(1))) for ch in dig] for cl in clusters])
    # each cluster takes its nearest digit, but only if it is that digit's best cluster or nearly (a digit at two
    # sizes makes two clusters; a wrong cluster claiming a digit costs far more than the true one)
    X, Y, S = [], [], []
    named = []
    for r, cl in enumerate(clusters):
        k = int(cost[r].argmin())
        if cost[r, k] > 1.3 * cost[:, k].min():
            continue
        for i in cl:
            X.append(B[i]); Y.append(dig[k]); S.append(int(ST[i]))
        named.append((dig[k], len(cl), round(float(cost[r, k]), 1)))
    print(f"  structure seed: {len(pool)} digit-slot glyphs in {len(clusters)} clusters -> {sorted(named)}")
    return X, Y, S, slots


def read_all(page, blocks, G, tree, votes, M, X, Y, S):
    """Every block read with M. Rows whose text matches VALID add their capitals to X/Y/S (exemplars at
    the row's angle and cap height); the unread letter slots of bearing-shaped rows are pooled for
    resolve_slots. Returns (blocks read, unread glyph count, exemplars added, slot pools)."""
    out = []
    unread = 0
    learned = 0
    slots = {"NS": [], "EW": []}
    seen = {tuple(np.round(x, 2)) for x in X}
    for b in blocks:
        br = block_rows(b, G, tree, votes, M)
        if br is None:
            out.append({**b, "text": "", "conf": 0.0}); continue
        angle, u, n, c, gh, rows = br
        if not rows:
            out.append({**b, "angle": round(angle, 2), "text": "", "conf": 0.0}); continue
        texts = []
        for merged in rows:
            if merged:
                t, lab = read_row(merged, u, n, gh, M)
                texts.append(t)
                if VALID.match(t):
                    for g, ch, ghr in lab:
                        if ch and ch != "?":
                            x = bitmap(g, angle, ghr)
                            if tuple(np.round(x, 2)) not in seen:
                                seen.add(tuple(np.round(x, 2))); X.append(x); Y.append(ch); S.append(len(g["strokes"])); learned += 1
                elif SHAPE.match(t) and lab:
                    m = SHAPE.match(t)
                    if m[1] == "?":
                        slots["NS"].append((bitmap(lab[0][0], angle, lab[0][2]), lab[0][0], len(lab[0][0]["strokes"])))
                    if m[2] == "?":
                        k = -2 if t.endswith("(R)") else -1
                        slots["EW"].append((bitmap(lab[k][0], angle, lab[k][2]), lab[k][0], len(lab[k][0]["strokes"])))
        text = "|".join(t for t in texts if t)
        unread += text.count("?")
        out.append({**b, "angle": round(angle, 2), "text": text, "conf": 1.0 if "?" not in text and text else 0.0})
    return out, unread, learned, slots


if __name__ == "__main__":
    main()
