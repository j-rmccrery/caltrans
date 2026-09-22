"""Text spike step 1: find text blocks (box + angle) from vector glyph strokes.

The sheet's annotation is stroked CAD glyphs, one small path per character.
Rasterise only the small paths, dilate so neighbouring characters merge,
take each blob's min-area rectangle -> text block with exact orientation.
Outputs spike/out/blocks.json and an overlay PNG for eyeballing.
"""
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf"
PDF = Path(os.environ.get("SHEET", DEFAULT))  # SHEET=<pdf> runs another sheet; its outputs go to out/<stem>/
OUT = Path(__file__).parent / "out" / (PDF.stem if "SHEET" in os.environ else "")

S = 4            # mask pixels per PDF point
GLYPH_MAX = 12   # pt; paths larger than this are linework, not characters
GLYPH_MIN = 0.2  # pt; keep commas and decimal points, they hold numbers together
DILATE = 2.2     # pt; merge radius. ponytail: single global radius, go per-font-size if tables merge rows
MIN_GLYPHS = 1  # "R-1", "L1": one multi-stroke letter plus one-stroke characters


def glyph_paths(page):
    for d in page.get_drawings():
        r = d["rect"]
        m = max(r.width, r.height)
        c = d.get("color")
        black = c is not None and max(c) < 0.2  # gray = R/W hatch stipple, white = masks
        # a lone straight segment is a tick mark or hatch line far more often than a "1" or "-";
        # crops are padded later so edge characters made of one stroke are still captured
        stroke = len(d["items"]) > 1 or m < 2.5
        if GLYPH_MIN <= m <= GLYPH_MAX and d["type"] != "f" and black and stroke:
            yield d
        elif m > GLYPH_MAX and min(r.width, r.height) <= GLYPH_MAX and d["type"] != "f" and black and text_run(d):
            yield d  # some drafters export a whole number or word as one path


def text_run(d):
    """A path that is a run of characters: many short segments in many directions, not a dashed line."""
    segs = [(it[1], it[2]) for it in d["items"] if it[0] == "l"]
    if len(segs) < 6:
        return False
    v = np.array([[b.x - a.x, b.y - a.y] for a, b in segs])
    ln = np.hypot(*v.T)
    if ln.max() > GLYPH_MAX:
        return False
    v = v[ln > 0.2] / ln[ln > 0.2, None]
    return len(v) >= 6 and np.abs(v @ v[np.argmax(ln[ln > 0.2])]).mean() < 0.85  # directions are spread out


def single_strokes(page):
    """One-segment black paths: '1', 'I', '-', '/', apostrophes ... and also ticks. (x, y, length) in pt."""
    out = []
    for d in page.get_drawings():
        c = d.get("color")
        if len(d["items"]) == 1 and d["items"][0][0] == "l" and c is not None and max(c) < 0.2:
            a, b = d["items"][0][1], d["items"][0][2]
            ln = float(np.hypot(a.x - b.x, a.y - b.y))
            if 0.2 <= ln <= GLYPH_MAX:
                out.append(((a.x + b.x) / 2, (a.y + b.y) / 2, ln, (a.x, a.y), (b.x, b.y)))
    return out


def _frame(b):
    t = np.radians(b["angle"])
    return np.array([b["cx"], b["cy"]]), np.array([np.cos(t), np.sin(t)]), np.array([-np.sin(t), np.cos(t)])


def _corners(b):
    c, u, n = _frame(b)
    return [c + sx * u * b["w"] / 2 + sy * n * b["h"] / 2 for sx in (-1, 1) for sy in (-1, 1)]


def _refit(b, pts):
    """Re-box a block around pts, keeping its reading axis."""
    c, u, n = _frame(b)
    P = np.array(pts) - c
    al, pe = P @ u, P @ n
    b["cx"], b["cy"] = (c + u * (al.max() + al.min()) / 2 + n * (pe.max() + pe.min()) / 2).tolist()
    b["w"], b["h"] = float(al.max() - al.min()), float(pe.max() - pe.min())


def assemble(blocks, singles):
    """Pass 2. The dilation pass drops one-stroke characters (they look like tick marks), which
    splits words and numbers. Put them back where they sit on a block's text line, then join
    blocks that continue each other along the reading axis. Multi-line blocks are left alone."""
    for b in blocks:
        b["pts"] = _corners(b)
    one_line = lambda b: b["h"] < 2.3 * b["glyph_h"]  # commas, periods and whole-word paths fatten a one-line box

    for _ in range(3):  # a few rounds: "11", "1-1"
        C = np.array([[b["cx"], b["cy"]] for b in blocks])
        for x, y, ln, p0, p1 in singles:
            near = np.nonzero(np.hypot(C[:, 0] - x, C[:, 1] - y) < 400)[0]
            best, best_perp = None, 1e9
            for i in near:
                b = blocks[i]
                if not one_line(b) or ln > 1.3 * b["glyph_h"]:
                    continue
                c, u, n = _frame(b)
                al, pe = abs((np.array([x, y]) - c) @ u), abs((np.array([x, y]) - c) @ n)
                if pe < 0.6 * b["glyph_h"] and b["w"] / 2 < al < b["w"] / 2 + 0.9 * b["glyph_h"] and pe < best_perp:
                    best, best_perp = i, pe
            if best is not None:
                b = blocks[best]
                b["pts"] += [np.array(p0), np.array(p1)]
                b["glyphs"] += 1
                _refit(b, b["pts"])

    # join collinear neighbours (union-find)
    parent = list(range(len(blocks)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    order = sorted(range(len(blocks)), key=lambda i: -blocks[i]["glyphs"])
    for i in order:
        a = blocks[i]
        if not one_line(a):
            continue
        c, u, n = _frame(a)
        for j in range(len(blocks)):
            b = blocks[j]
            if j == i or not one_line(b) or not 0.7 < b["glyph_h"] / a["glyph_h"] < 1.4:
                continue
            P = np.array(b["pts"]) - c
            al, pe = P @ u, P @ n
            gap = max(al.min() - a["w"] / 2, -a["w"] / 2 - al.max())
            if -1.5 * a["glyph_h"] < gap < 1.2 * a["glyph_h"] and abs(pe).max() < 0.5 * a["h"] + 0.4 * a["glyph_h"]:
                parent[find(j)] = find(i)
    groups = {}
    for i in range(len(blocks)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for root, members in groups.items():
        lead = max(members, key=lambda i: blocks[i]["glyphs"])
        b = dict(blocks[lead])
        if len(members) > 1:
            pts = [p for i in members for p in blocks[i]["pts"]]
            b["glyphs"] = sum(blocks[i]["glyphs"] for i in members)
            _refit(b, pts)
        b.pop("pts")
        out.append(b)
    return out


def split_rows(b, pts, gh):
    """Stacked lines (an N over an E callout) merge into one blob. Split by the gaps between rows of
    glyph centres measured across the reading axis; keep the parent's angle."""
    if b["h"] < 1.9 * gh or len(pts) < 4:
        return [b]
    t = np.radians(b["angle"])
    u, nrm = np.array([np.cos(t), np.sin(t)]), np.array([-np.sin(t), np.cos(t)])
    c = np.array([b["cx"], b["cy"]])
    al, pe = (pts - c) @ u, (pts - c) @ nrm
    order = np.argsort(pe)
    rows, cur = [], [order[0]]
    for i, j in zip(order, order[1:]):
        if pe[j] - pe[i] > 0.7 * gh:
            rows.append(cur); cur = []
        cur.append(j)
    rows.append(cur)
    if len(rows) < 2:
        return [b]
    out = []
    for r in rows:
        r = np.array(r)
        if len(r) < 2:
            continue
        cc = c + u * (al[r].max() + al[r].min()) / 2 + nrm * pe[r].mean()
        out.append({"cx": float(cc[0]), "cy": float(cc[1]), "w": float(al[r].max() - al[r].min() + gh), "h": float(1.3 * gh),
                    "angle": b["angle"], "glyphs": int(len(r)), "glyph_h": b["glyph_h"]})
    return out or [b]


def main():
    page = pymupdf.open(PDF)[0]
    W, H = int(page.rect.width * S), int(page.rect.height * S)
    mask = np.zeros((H, W), np.uint8)
    centers = []
    for d in glyph_paths(page):
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                cv2.line(mask, (int(a.x * S), int(a.y * S)), (int(b.x * S), int(b.y * S)), 255, 2)
            elif it[0] == "c":
                pts = np.array([[p.x * S, p.y * S] for p in it[1:5]], np.int32)
                cv2.polylines(mask, [pts], False, 255, 2)
            elif it[0] in ("qu", "re"):  # decimal points and periods are often tiny quads
                q = it[1]
                pts = np.array([[q.ul.x * S, q.ul.y * S], [q.ur.x * S, q.ur.y * S], [q.lr.x * S, q.lr.y * S], [q.ll.x * S, q.ll.y * S]], np.int32) if it[0] == "qu" else                     np.array([[q.x0 * S, q.y0 * S], [q.x1 * S, q.y0 * S], [q.x1 * S, q.y1 * S], [q.x0 * S, q.y1 * S]], np.int32)
                cv2.polylines(mask, [pts], True, 255, 2)
        r = d["rect"]
        # a character's height is its larger side; a whole-word path is wider than tall, so its smaller side
        gh = max(r.width, r.height) if max(r.width, r.height) <= GLYPH_MAX else min(r.width, r.height)
        centers.append(((r.x0 + r.x1) / 2 * S, (r.y0 + r.y1) / 2 * S, gh))

    k = int(DILATE * S) * 2 + 1
    merged = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels = cv2.connectedComponents(merged)

    counts = np.zeros(n, int)
    heights = [[] for _ in range(n)]
    members = [[] for _ in range(n)]
    for x, y, h in centers:
        lab = labels[min(int(y), H - 1), min(int(x), W - 1)]
        counts[lab] += 1
        heights[lab].append(h)
        members[lab].append((x, y))

    blocks = []
    for lab in range(1, n):
        if counts[lab] < MIN_GLYPHS or max(heights[lab]) < 3:  # all-tiny blob = ticks, not text
            continue
        ys, xs = np.nonzero((labels == lab) & (mask > 0))
        if len(xs) < 5:
            continue
        (cx, cy), (w, h), ang = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        if w < h:  # make w the long (reading) axis
            w, h, ang = h, w, ang + 90
        ang = (ang + 90) % 180 - 90  # text reads left-to-right: keep angle in (-90, 90]
        gh = float(np.median(heights[lab]))
        b = {"cx": cx / S, "cy": cy / S, "w": w / S, "h": h / S, "angle": round(float(ang), 2),
             "glyphs": int(counts[lab]), "glyph_h": round(gh, 2)}
        blocks += split_rows(b, np.array(members[lab]) / S, gh)

    for i, b in enumerate(blocks):
        b["id"] = i

    blocks = assemble(blocks, single_strokes(page))
    for i, b in enumerate(blocks):
        b["id"] = i

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "blocks.json").write_text(json.dumps(blocks, indent=1))

    pix = page.get_pixmap(matrix=pymupdf.Matrix(S, S), alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    for b in blocks:
        box = cv2.boxPoints(((b["cx"] * S, b["cy"] * S), (b["w"] * S + 6, b["h"] * S + 6), b["angle"]))
        rot = abs(b["angle"]) > 3
        cv2.polylines(img, [box.astype(np.int32)], True, (0, 0, 255) if rot else (0, 160, 0), 2)
    cv2.imwrite(str(OUT / "blocks_overlay.png"), img)

    ang = np.array([b["angle"] for b in blocks])
    g = np.array([b["glyphs"] for b in blocks])
    print(f"glyph paths {len(centers)} | blocks {len(blocks)} | rotated(>3deg) {(abs(ang) > 3).sum()}")
    print("glyphs/block percentiles 50/90/99/max:", np.percentile(g, [50, 90, 99, 100]))
    print("biggest blocks (likely merged tables):", sorted(g.tolist())[-8:])
    assert len(blocks) > 100, "too few blocks: clustering is broken"
    assert g.sum() > 0.8 * len(centers), "most glyphs unassigned"


if __name__ == "__main__":
    sys.exit(main())
