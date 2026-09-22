"""Read the short segment tags on the drawing (L8, C16, L14(T)) without OCR.

The sheet's characters are stroked CAD glyphs: the same character is the same path everywhere on
the sheet. The tables carry keyed truth (gt.py), so every glyph inside a table cell whose read
matches the truth is a labelled exemplar. Every character-sized path on the drawing is rasterised
at 36 rotations and matched to the nearest exemplar: the match says which character it is, at
what angle, and whether it is a character at all (leader pieces and arrowheads match nothing).
Characters are clustered at one pitch, the cluster's reading angle is refined from its members,
one-stroke '1's are attached by geometry, and a run that spells [LC]<n>(T)? is a tag.
The OCR text blocks are not used: beside the R/W line they absorb stationing ticks and leader
arrowheads, which skews their angle and buries the tag.

Output: spike/out/tags.json — [{tag, cx, cy, angle, score}] for tags inside the map area.
usage: [SHEET=<pdf>] python spike/tags.py
"""
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from blocks import OUT, PDF, glyph_paths, single_strokes  # noqa: E402
from gt import TABLES  # noqa: E402
from ocr import norm  # noqa: E402
from overlay import FURNITURE, MAP_AREA, bezier  # noqa: E402

TAG = re.compile(r"^([LC]\d{1,2})(\(T\))?$")
PX = 24       # bitmap side
CAP = 18.0    # px per glyph height: punctuation stays small, letters fill the box
PITCH = 1.25  # max centre spacing between neighbouring characters, in glyph heights
LINK = 2.3    # two multi-stroke glyphs this far apart still link when a one-stroke '1' sits between them
STEP = 10     # degrees between trial rotations
JUNK = 5.0    # bitmap distance beyond which a path is not a character: exact matches are 0-0.9, a 2 deg
              # axis error costs 1-4, leader pieces and arrowheads sit at 6-17
COARSE = 6.5  # same, for the rotation sweep where the nearest trial angle can be STEP/2 off
MIN_SCORE = 1.4  # nearest other character must be this much farther than the match; false tags sit at 1.0-1.15
ALNUM = set("0123456789LCT()")


def glyphs(page):
    """Character-sized paths as stroke point lists (pt) with centre and height; one-stroke paths flagged."""
    out = []
    for d in glyph_paths(page):
        pts = []
        for it in d["items"]:
            if it[0] == "l":
                pts.append([(it[1].x, it[1].y), (it[2].x, it[2].y)])
            elif it[0] == "c":
                pts.append([tuple(p) for p in bezier(*[np.array([p.x, p.y]) for p in it[1:5]], n=6)])
            elif it[0] == "qu":
                q = it[1]; pts.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)])
            elif it[0] == "re":
                q = it[1]; pts.append([(q.x0, q.y0), (q.x1, q.y0), (q.x1, q.y1), (q.x0, q.y1), (q.x0, q.y0)])
        r = d["rect"]
        out.append({"strokes": pts, "c": np.array([(r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2]), "h": max(r.width, r.height), "single": False,
                    "arrow": d["type"] != "s" and len(d["items"]) <= 4})  # leader arrowhead: a small filled triangle
    for x, y, ln, p0, p1 in single_strokes(page):  # '1', '-', apostrophes: dropped by glyph_paths as tick-like
        out.append({"strokes": [[p0, p1]], "c": np.array([x, y]), "h": ln, "single": True, "arrow": False})
    # a character is one path touching nothing; the pieces of a leader touch each other end to end
    ends, owner = [], []
    for pid, d in enumerate(page.get_drawings()):
        for it in d["items"]:
            if it[0] in ("l", "c"):
                ends += [(it[1].x, it[1].y), (it[-1].x, it[-1].y)]; owner += [pid, pid]
    ends, owner = np.array(ends), np.array(owner)
    etree = cKDTree(ends)
    for g in out:
        own = etree.query_ball_point(g["strokes"][0][0], 0.05)
        me = {owner[j] for j in own}
        g["connected"] = any(owner[j] not in me for s in g["strokes"] for p in (s[0], s[-1]) for j in etree.query_ball_point(p, 0.3))
    return out


def bitmap(g, angle, gh):
    """Upright glyph on a PX x PX canvas, scaled by the text's glyph height, centred."""
    t = np.radians(-angle)
    R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    strokes = [(np.array(s) - g["c"]) @ R.T for s in g["strokes"]]
    allp = np.vstack(strokes)
    s = CAP / gh
    off = np.array([PX / 2, PX / 2]) - s * (allp.min(0) + allp.max(0)) / 2
    img = np.zeros((PX, PX), np.uint8)
    for st in strokes:
        cv2.polylines(img, [(st * s + off).round().astype(np.int32)], False, 255, 1)
    return cv2.GaussianBlur(img, (3, 3), 0).astype(np.float32).ravel() / 255


def axes(angle):
    t = np.radians(angle)
    return np.array([np.cos(t), np.sin(t)]), np.array([-np.sin(t), np.cos(t)])


def exemplars(G, blocks):
    """Labelled glyph bitmaps from table cells read correctly (a double quote is two strokes), deduplicated."""
    truth = {norm(v): v for vals in TABLES.values() for v in vals[1]}
    tree = cKDTree(np.array([g["c"] for g in G]))
    X, Y = [], []
    for b in blocks:
        if not any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for (x0, y0, x1, y1), _ in TABLES.values()):
            continue
        text = truth.get(norm(b["text"]))
        if text is None:
            continue
        text = text.replace(" ", "").replace('"', '""')
        u, n = axes(b["angle"])
        c = np.array([b["cx"], b["cy"]])
        ids = [i for i in tree.query_ball_point(c, b["w"] / 2 + b["h"]) if abs((G[i]["c"] - c) @ u) < b["w"] / 2 + 0.6 * b["glyph_h"] and abs((G[i]["c"] - c) @ n) < b["h"] / 2 + 0.3 * b["glyph_h"]]
        ids.sort(key=lambda i: (G[i]["c"] - c) @ u)
        if len(ids) != len(text):
            continue
        for i, ch in zip(ids, text):
            X.append(bitmap(G[i], b["angle"], b["glyph_h"])); Y.append(ch)
    X, Y = np.array(X), np.array(Y)
    _, keep = np.unique(X.round(2), axis=0, return_index=True)
    return X[keep], Y[keep]


class Matcher:
    def __init__(self, X, Y):
        self.X, self.Y, self.n2 = X, Y, (X ** 2).sum(1)

    def dist(self, B):
        """Squared distances, rows of B against every exemplar."""
        return np.maximum(self.n2[None, :] - 2 * B @ self.X.T + (B ** 2).sum(1)[:, None], 0)

    def classify(self, bits):
        d = self.dist(bits[None, :])[0]
        k = int(d.argmin())
        if d[k] > JUNK:
            return "?", 0.0
        return self.Y[k], float(d[self.Y != self.Y[k]].min() / max(d[k], 1e-6))


def characters(G, M, x0, y0, x1, y1):
    """Rotation-invariant pass: for each multi-stroke path in the map area, the best exemplar over all
    trial rotations. Returns {glyph index: (char, angle, distance)} for the ones that are characters."""
    ids = [i for i, g in enumerate(G) if not g["single"] and 3 <= g["h"] <= 12 and x0 < g["c"][0] < x1 and y0 < g["c"][1] < y1
           and not any(fx0 <= g["c"][0] <= fx1 and fy0 <= g["c"][1] <= fy1 for fx0, fy0, fx1, fy1 in FURNITURE)]
    angles = np.arange(0, 360, STEP)
    out = {}
    for start in range(0, len(ids), 256):
        chunk = ids[start:start + 256]
        B = np.array([bitmap(G[i], a, G[i]["h"]) for i in chunk for a in angles])
        d = M.dist(B).reshape(len(chunk), len(angles), -1)
        best = d.min(2)                      # per glyph, per angle
        for k, i in enumerate(chunk):
            a = int(best[k].argmin())
            if best[k, a] < COARSE:
                out[i] = (M.Y[int(d[k, a].argmin())], float(angles[a]), float(best[k, a]))
    return out


def clusters(G, chars):
    """Character glyphs linked when closer than a pitch (or a '1'-stroke apart): each group is a word or number."""
    ids = list(chars)
    C = np.array([G[i]["c"] for i in ids])
    H = np.array([G[i]["h"] for i in ids])
    ones = cKDTree(np.array([g["c"] for g in G if g["single"] and 4 <= g["h"] <= 10]))
    parent = list(range(len(ids)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    A = np.array([chars[i][1] for i in ids])
    for i, j in cKDTree(C).query_pairs(LINK * 12):
        gh, d = max(H[i], H[j]), np.hypot(*(C[i] - C[j]))
        if min(H[i], H[j]) < 0.5 * gh or abs((A[i] - A[j] + 90) % 180 - 90) > 35:
            continue  # different size or different reading angle (mod 180: 0/8/S/N vote either way; an
            # upside-down L reads as 7 a step or two off, so the agreement is loose)
        if d < PITCH * gh or (d < LINK * gh and ones.query((C[i] + C[j]) / 2)[0] < 0.4 * gh):
            parent[find(i)] = find(j)
    groups = {}
    for k, i in enumerate(ids):
        groups.setdefault(find(k), []).append(i)
    return list(groups.values())


def read_cluster(G, members, singles_tree, singles, angle, gh, M, paths_tree=None, paths=()):
    """Classify the glyphs at this reading angle, attach upright one-stroke '1's, then split into text
    rows and runs at one character pitch. Returns the runs that spell a tag. A run with another
    character-sized path right next to it on the text line is a piece of a longer word or number
    (L20 with its 0 unread, the CK in TIEBACK): it is reported with '?' and never as a tag."""
    u, n = axes(angle)
    c0 = np.mean([G[i]["c"] for i in members], 0)
    mset = set(members)

    def neighbour(g, sign):
        """A character-sized path beside g along the reading axis (sign -1 before, +1 after)."""
        for j in (paths_tree.query_ball_point(g["c"], 1.5 * gh) if paths_tree is not None else []):
            k = paths[j]
            if k in mset:
                continue
            d = G[k]["c"] - g["c"]
            if 0.4 * gh < sign * (d @ u) < 1.5 * gh and abs(d @ n) < 0.5 * gh and 0.85 * gh < G[k]["h"] < 1.35 * gh and len(G[k]["strokes"]) <= 20:
                return True  # cap-height, up to ~16 strokes (a 0 is 16 segments): a character; a leader's squiggle is shorter or has dozens
        return False
    keep = [(G[i], *M.classify(bitmap(G[i], angle, gh))) for i in members]
    keep = [(g, ch, mg) for g, ch, mg in keep if ch in ALNUM or ch == "?"]  # an unread glyph stays: it marks a run as incomplete
    if not keep:
        return []
    if "1" not in set(M.Y):  # a font whose '1' is a bare stroke: attach upright one-stroke paths on the text line
        al = np.array([(g["c"] - c0) @ u for g, _, _ in keep])
        lo, hi = al.min(), al.max()
        for j in singles_tree.query_ball_point(c0, (hi - lo) / 2 + 3 * gh):
            g = singles[j]
            d = g["c"] - c0
            p0, p1 = np.array(g["strokes"][0])
            v = (p1 - p0) / max(np.hypot(*(p1 - p0)), 1e-9)
            if lo - PITCH * gh < d @ u < hi + PITCH * gh and 0.6 * gh < g["h"] < 1.15 * gh and abs(v @ u) < 0.26 \
                    and any(abs((g["c"] - k["c"]) @ n) < 0.35 * gh for k, _, _ in keep):
                keep.append((g, "1", 9.9))  # ponytail: stationing ticks beside a lone C read as C1; unverified path
    keep.sort(key=lambda t: (t[0]["c"] - c0) @ n)
    rows, cur = [], [keep[0]]
    for a, b in zip(keep, keep[1:]):
        if ((b[0]["c"] - a[0]["c"]) @ n) > 0.6 * gh:
            rows.append(cur); cur = []
        cur.append(b)
    rows.append(cur)
    out = []
    for row in rows:
        row.sort(key=lambda t: (t[0]["c"] - c0) @ u)
        runs, cur = [], [row[0]]
        for a, b in zip(row, row[1:]):
            if ((b[0]["c"] - a[0]["c"]) @ u) > 1.5 * gh:
                runs.append(cur); cur = []
            cur.append(b)
        runs.append(cur)
        for run in runs:
            s = ("?" if neighbour(run[0][0], -1) else "") + "".join(ch for _, ch, _ in run) + ("?" if neighbour(run[-1][0], 1) else "")
            if 2 <= len(run) <= 6 and (TAG.match(s) or ("?" in s and TAG.match(s.replace("?", "")))):
                cs = np.array([g["c"] for g, _, _ in run])
                out.append({"tag": s, "cx": float(cs[:, 0].mean()), "cy": float(cs[:, 1].mean()), "angle": round(float(angle), 2), "gh": round(gh, 2),
                            "score": round(float(min(mg for _, _, mg in run)), 2)})  # "L1?" = an unread glyph on the run: never a tag, goes to the queue
    return out


def main():
    page = pymupdf.open(PDF)[0]
    blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8"))
    G = glyphs(page)
    if (OUT / "alphabet.npz").exists():  # the sheet's own alphabet, bootstrapped from its tables (alphabet.py)
        z = np.load(OUT / "alphabet.npz"); X, Y = z["X"], z["Y"]
        keep = np.isin(Y, list("0123456789LCT"))  # tags carry no symbols; parens and quotes only catch leader pieces
        X, Y = X[keep], Y[keep]
        if len(X) < 12:
            (OUT / "tags.json").write_text("[]", encoding="utf-8"); print("no alphabet for this sheet: no tags read"); return []
    else:
        X, Y = exemplars(G, blocks)
    M = Matcher(X, Y)
    print(f"exemplars {len(X)} distinct over {len(set(Y))} characters: {''.join(sorted(set(Y)))}")
    chars = characters(G, M, *MAP_AREA)
    print(f"character paths on the drawing {len(chars)}")

    singles = [g for g in G if g["single"]]
    stree = cKDTree(np.array([g["c"] for g in singles]))
    paths = [i for i, g in enumerate(G) if not g["single"] and not g["arrow"] and not g["connected"] and 3 <= g["h"] <= 12]
    ptree = cKDTree(np.array([G[i]["c"] for i in paths]))
    tags = []
    furniture = list(FURNITURE) + (json.loads((OUT / "tables.json").read_text(encoding="utf-8")).get("_regions", []) if (OUT / "tables.json").exists() else [])
    for members in clusters(G, chars):
        cm = np.mean([G[i]["c"] for i in members], 0)
        if any(x0 <= cm[0] <= x1 and y0 <= cm[1] <= y1 for x0, y0, x1, y1 in furniture):
            continue  # inside a table: the record, not a tag on the drawing
        if len(members) > 16:
            continue
        gh = float(np.median([G[i]["h"] for i in members]))
        # reading angle: the members' best rotations agree up to the trial step (and up to 180 deg for
        # symmetric characters); refine around the vote by total match distance, both senses
        votes = np.array([chars[i][1] for i in members])
        base = float(np.degrees(np.arctan2(np.sin(np.radians(2 * votes)).mean(), np.cos(np.radians(2 * votes)).mean())) / 2)
        best = []
        for sense in (base, base + 180):
            fine = np.arange(sense - 2 * STEP, sense + 2 * STEP + 1, 2.0)  # the vote can sit a step off (an L reads as 7 upside down)
            cost = [sum(M.dist(bitmap(G[i], a, gh)[None, :])[0].min() for i in members) for a in fine]
            angle = (float(fine[int(np.argmin(cost))]) + 180) % 360 - 180
            t = [x for x in read_cluster(G, members, stree, singles, angle, gh, M, ptree, paths) if x["score"] >= MIN_SCORE or "?" in x["tag"]]
            if (len(t), sum(x["score"] for x in t)) > (len(best), sum(x["score"] for x in best)):
                best = t
        tags += best
    tags.sort(key=lambda t: (t["tag"][0], int(re.sub(r"\D", "", t["tag"]) or 0)))
    (OUT / "tags.json").write_text(json.dumps(tags, indent=1, ensure_ascii=False), encoding="utf-8")
    if (OUT / "tables.json").exists():  # the sheet's own tables as read by alphabet.py
        table = {k for k in json.loads((OUT / "tables.json").read_text(encoding="utf-8")) if not k.startswith("_")}
    else:
        table = {re.sub(r"\(T\)", "", v) for name in ("line", "curve1", "curve2") for v in TABLES[name][1][::4 if "curve" in name else 3]}
    partial = [t for t in tags if "?" in t["tag"]]
    seen = {t["tag"].replace("(T)", "") for t in tags if "?" not in t["tag"]}
    print(f"drawing tags {len(tags) - len(partial)} ({len(seen)} distinct) of {len(table)} table rows, {len(partial)} partial (queued); "
          f"not seen: {sorted(table - seen, key=lambda s: (s[0], int(s[1:])))}")
    print("  " + " ".join(f"{t['tag']}@{t['cx']:.0f},{t['cy']:.0f}/{t['score']}" for t in tags))
    if table and len(seen) < 0.5 * len(table):
        print(f"WARNING: only {len(seen)} of {len(table)} table rows are seen on the drawing")
    return tags


if __name__ == "__main__":
    main()
