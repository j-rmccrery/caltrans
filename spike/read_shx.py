"""Reads from AutoCAD SHX Text annotations: one block per annotation (same block format as
read_glyph.json: cx, cy, w, h, angle, glyph_h, id, text with '|' between lines, conf 1.0, plus src).
blocks.py's own dilated clusters are used only to look up a containing label's angle, never as text
containers -- pouring annotation text into those clusters merges unrelated labels (a distance next
to an R=/L=/delta curve callout, three stacked NO. cells), and checks.py skips every distance in a
block that also carries curve data anywhere in it, so that merge silently dropped real distances.
The one deliberate join left in: a bearing next to its own distance becomes one "bearing|distance"
block (see build_blocks). AutoCAD control codes are decoded: %%D degree, %%P plus-minus, %%C
diameter, %%U (underline toggle) dropped.

Second reader: where read_glyph.json exists, texts are compared per block id (spaces stripped) and
disagreements written to reads_disagree.json.

--tables: also rebuild tables.json from the annotation text (a NO. cell is an annotation matching
[LC]<n>(T)? inside a table region — an existing tables.json's _regions if present, else a run of
>=4 consecutive NO. cells in one column; a row's cells are the other annotations in the same row
band to its right, in x order, a cell with two internal spaces being two cells).

usage: [SHEET=<pdf>] python spike/read_shx.py [--tables]
"""
import json
import math
import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from blocks import glyph_paths  # noqa: E402 -- the same glyph-sized-stroke filter blocks.py fits labels with

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf"
PDF = Path(os.environ.get("SHEET", DEFAULT))  # SHEET=<pdf> runs another sheet; its outputs go to out/<stem>/
OUT = Path(__file__).parent / "out" / (PDF.stem if "SHEET" in os.environ else "")
NO_RE = re.compile(r"^([LC])(\d+)(\(T\))?$")


def decode(t):
    return (t.replace("%%D", "°").replace("%%d", "°").replace("%%P", "±").replace("%%p", "±")
             .replace("%%C", "Ø").replace("%%c", "Ø").replace("%%U", "").replace("%%u", ""))


def frame(b):
    th = math.radians(b["angle"])
    return np.array([b["cx"], b["cy"]]), np.array([math.cos(th), -math.sin(th)]), np.array([math.sin(th), math.cos(th)])


def inside(b, x, y):
    c, u, n = frame(b)
    d = np.array([x - c[0], y - c[1]])
    return abs(d @ u) <= b["w"] / 2 + 2 and abs(d @ n) <= b["h"] / 2 + 2


def bbox(b):
    c, u, n = frame(b)
    pts = [c + sx * u * b["w"] / 2 + sy * n * b["h"] / 2 for sx in (-1, 1) for sy in (-1, 1)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]


def read_annotations(page):
    ann = [(a.info.get("content", "").strip(), a.rect) for a in page.annots() if a.info.get("title") == "AutoCAD SHX Text"]
    return [(decode(t), r) for t, r in ann if decode(t)]


BEAR_PAIR = re.compile(r"^[NS]\d{1,2}°\d{2}'\d{2}\"[EW](\(R\))?$")
DIST_PAIR = re.compile(r"^\d{1,4}\.\d{2,3}'?(\(T\))?$")


def containing_block(glyph_blocks, r):
    """The glyph block (blocks.py, unmerged with any annotation) whose box holds this rect's centre,
    else the nearest one within the rect's own size (a "bearing  distance" annotation with two words
    and no join pipe has its rect centre in the whitespace between two glyph clusters, inside neither --
    the nearest cluster still carries the label's true angle, which the annotation's own PDF rect never
    does: an Annot.rect is always axis-aligned, so a rotated label with no containing or nearby cluster
    fell back to a 0/90 guess and failed every downstream parallel-to-the-line test by 5-10 deg)."""
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    # a near-90deg sliver fragment (a stray tick/leader mark, or a mis-fit minAreaRect over cramped
    # multi-line text, blocks.py clustered with a near-zero glyph_h) can pass inside()'s rotated +2pt
    # pad from several pt away in plain x/y -- its tiny h axis is nearly horizontal at that angle, so
    # the pad alone "contains" an unrelated rect (R-71.70's "PID: AE9850" label, 58x14pt, snapped a
    # 2x2.5pt fragment this way, both as an "inside" hit and, unfiltered, as the "near" fallback too).
    # The actual sliver measured 1.92pt tall (checked directly): a 4pt floor (leg C's original fix)
    # excludes that, but also every genuinely small-but-real glyph cluster blocks.py's own per-character
    # dilation produces (single digits, short tags), which is most of them -- on the six-sheet baseline
    # that reroutes 462 of ~1400 annotations on R-10434.3 alone to a worse container and cost 4 passes
    # across three sheets never gated against this change (loop 4 leg D found it). 3pt keeps the sliver
    # excluded (checked: still None, both fragments 1.92pt) without reaching real lettering.
    trustworthy = [gb for gb in glyph_blocks if gb["glyph_h"] >= 3]
    for gb in trustworthy:
        if inside(gb, cx, cy):
            return gb
    near = [gb for gb in trustworthy if math.hypot(gb["cx"] - cx, gb["cy"] - cy) < max(r.width, r.height, 10)]
    return min(near, key=lambda gb: math.hypot(gb["cx"] - cx, gb["cy"] - cy)) if near else None


def ink_box(glyph_paths_idx, r):
    """Last resort, for an annotation with no containing or nearby blocks.json cluster: its own reading
    angle and box, fit the way blocks.py fits a whole label -- cv2.minAreaRect over the points of the
    glyph-sized strokes (page.get_drawings(), blocks.glyph_paths' own character filter) whose bbox lies
    inside the annotation's rect padded by 1 pt. An Annot.rect is always axis-aligned even when the text
    is rotated, so this is the only place left to measure the true angle from. None (falls back to the
    old 0/90 guess) when fewer than 2 glyph paths lie in the rect -- not enough ink to fit a direction."""
    x0, y0, x1, y1 = r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1
    found = [d for d in glyph_paths_idx if x0 <= d["rect"].x0 and d["rect"].x1 <= x1 and y0 <= d["rect"].y0 and d["rect"].y1 <= y1]
    if len(found) < 2:
        return None
    pts = [(p.x, p.y) for d in found for it in d["items"] for p in (it[1:3] if it[0] == "l" else it[1:5] if it[0] == "c" else ())]
    if len(pts) < 4:
        return None
    (cx, cy), (w, h), ang = cv2.minAreaRect(np.array(pts, dtype=np.float32))
    if w < h:  # long side = reading axis, as in blocks.py
        w, h, ang = h, w, ang + 90
    ang = (ang + 90) % 180 - 90
    return {"w": float(w), "h": float(max(h, 1.0)), "angle": float(ang), "glyph_h": float(max(h, 1.0))}


def ann_box(t, r, containing, glyph_paths_idx=None):
    """One annotation's own box. angle: the containing glyph block's (blocks.py fits a single
    label's rotation well), else fit directly from its own ink (ink_box), else level/vertical from
    the rect's own aspect. w, h: a level or vertical angle trusts the rect's own sides; any other
    angle from a containing block means the rect is only an axis-aligned bound on a rotated label, so
    the box is rebuilt from the text length along that angle instead, capped at the rect diagonal so a
    long line never overruns its own box; an ink-fit box already has its own w/h and needs neither."""
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    if containing is None:
        ink = ink_box(glyph_paths_idx, r) if glyph_paths_idx is not None else None
        if ink is not None:
            return {"cx": cx, "cy": cy, **ink}
    angle = containing["angle"] if containing is not None else (0.0 if r.width >= r.height else 90.0)
    if angle in (0.0, 90.0):
        w, h = (r.width, r.height) if angle == 0.0 else (r.height, r.width)
    else:
        h = containing["glyph_h"]
        w = min(len(t) * 0.62 * h, math.hypot(r.width, r.height))
    return {"cx": cx, "cy": cy, "w": w, "h": h, "angle": angle, "glyph_h": h}


def corners(b):
    c, u, n = frame(b)
    return [c + u * sx * b["w"] / 2 + n * sy * b["h"] / 2 for sx in (-1, 1) for sy in (-1, 1)]


def union_box(angle, boxes):
    ref = {"cx": boxes[0]["cx"], "cy": boxes[0]["cy"], "angle": angle}
    c, u, n = frame(ref)
    pts = [p for b in boxes for p in corners(b)]
    al, pe = [(p - c) @ u for p in pts], [(p - c) @ n for p in pts]
    mid = c + u * (max(al) + min(al)) / 2 + n * (max(pe) + min(pe)) / 2
    return {"cx": float(mid[0]), "cy": float(mid[1]), "w": float(max(al) - min(al)), "h": float(max(pe) - min(pe)),
            "angle": angle, "glyph_h": max(b["glyph_h"] for b in boxes)}


def near(A, B):
    """B's centre within 1.6*A.h along A's normal and 0.6*A.w along A's reading direction."""
    c, u, n = frame(A)
    d = np.array([B["cx"] - c[0], B["cy"] - c[1]])
    return abs(d @ n) <= 1.6 * A["h"] and abs(d @ u) <= 0.6 * A["w"]


def dedupe_twins(ann, boxes, pool):
    """Same-text annotations in `pool` (indices into ann/boxes) whose centres sit within one glyph
    height of each other on both axes get folded into one -- a CAD annotation drawn twice on top
    of itself (the "50.22'" bug: two identical distance annotations ~14pt apart, i.e. one glyph_h,
    with near-identical rects). Two real labels of the same value farther apart than that stay
    separate (e.g. a bearing shared by two nearby, genuinely distinct courses).

    Restricted to the bearing/distance pool (not every annotation on the sheet): elsewhere the same
    text legitimately repeats at the very same ~14pt line pitch across real, distinct rows (a legal-
    description table with several parcels sharing one owner name, TCE flag, or execution date) --
    geometry alone can't tell a real duplicate from a real repeat there, so this only touches the
    pool that actually feeds checks.py's distance/bearing counts. Returns {dup index: kept index}."""
    seen, dup_of = {}, {}
    for i in sorted(pool):
        t, b = ann[i][0], boxes[i]
        keep = next((k for k in seen.get(t, []) if abs(b["cx"] - boxes[k]["cx"]) <= boxes[k]["h"]
                     and abs(b["cy"] - boxes[k]["cy"]) <= boxes[k]["h"]), None)
        if keep is None:
            seen.setdefault(t, []).append(i)
        else:
            dup_of[i] = keep
            boxes[keep] = union_box(boxes[keep]["angle"], [boxes[keep], b])
    return dup_of


def build_blocks(glyph_blocks, ann, glyph_paths_idx=None):
    """One block per annotation -- not blocks.py's dilated clusters. Those merge unrelated labels
    (a distance next to an unrelated R=/L=/delta curve callout, three stacked NO. cells) into one
    block, and checks.py skips every distance in a block that also carries curve data anywhere in
    it: that merge was silently dropping real distances, not just misreading them. Geometry per
    annotation comes from ann_box(). The one deliberate join: a bearing next to its own distance
    (read together everywhere else downstream) becomes one "bearing|distance" block; nothing else
    merges -- not curve data with a distance, not a tag with its neighbour. Twin annotations (see
    dedupe_twins) are folded away first so a duplicated distance or bearing isn't counted twice."""
    boxes = [ann_box(t, r, containing_block(glyph_blocks, r), glyph_paths_idx) for t, r in ann]
    bearings = [i for i, (t, r) in enumerate(ann) if BEAR_PAIR.match(t.replace(" ", ""))]
    dists = {i for i, (t, r) in enumerate(ann) if DIST_PAIR.match(t.replace(" ", ""))}
    twins = dedupe_twins(ann, boxes, set(bearings) | dists)
    bearings = [i for i in bearings if i not in twins]
    dists = {i for i in dists if i not in twins}
    used, pairs = set(), {}
    for i in bearings:
        cands = [j for j in dists if j not in used and abs(boxes[i]["angle"] - boxes[j]["angle"]) <= 5 and near(boxes[i], boxes[j])]
        if cands:
            j = min(cands, key=lambda j: math.hypot(boxes[j]["cx"] - boxes[i]["cx"], boxes[j]["cy"] - boxes[i]["cy"]))
            pairs[i] = j
            used |= {i, j}
    out = []
    for i, (t, r) in enumerate(ann):
        if i in twins:
            continue  # duplicate annotation: folded into its twin's (unioned) box above
        if i in used and i not in pairs:
            continue  # the distance half of a pair: folded into its bearing's block below
        if i in pairs:
            j = pairs[i]
            b = union_box(boxes[i]["angle"], [boxes[i], boxes[j]])
            b["text"] = t + "|" + ann[j][0]
        else:
            b = dict(boxes[i])
            b["text"] = t
        b["glyphs"] = len(b["text"].replace("|", ""))
        b["conf"], b["src"], b["id"] = 1.0, "shx", len(out)
        out.append(b)
    return out


def disagreements(shx_blocks):
    """Per block id (spaces stripped), where read_glyphs.py's read differs from the annotation's."""
    gp = OUT / "read_glyph.json"
    if not gp.exists():
        return []
    glyph = {b["id"]: b.get("text", "") for b in json.loads(gp.read_text(encoding="utf-8"))}
    out = []
    for b in shx_blocks:
        if b["id"] not in glyph or not b.get("text"):
            continue
        shx, gl = b["text"].replace(" ", ""), glyph[b["id"]].replace(" ", "")
        if shx != gl:
            out.append({"id": b["id"], "shx": b["text"], "glyph": glyph[b["id"]], "region": bbox(b)})
    return out


def build_tables(ann):
    """NO. cells and their rows, from the raw annotations (ground truth, no glyph matching needed).
    Works off ann, not the merged blocks: blocks.py's dilation clustering sometimes merges two
    adjacent cells (a stacked "L1"+"L2", or a bearing run into its distance) into one block, which
    would corrupt a table read; the annotations themselves are never merged.
    ponytail: a NO. column is found by its own run (>=4 consecutive, aligned in x, even pitch) over
    every annotation on the sheet, not scoped to an existing tables.json's _regions first -- those
    regions are alphabet.py's own (imperfect) table boxes and on this sheet clip C1 the same way
    alphabet.py misses it (under the header, its region starts a row too low). A stray look-alike
    elsewhere (a drawing tag "L8") never chains: real rows are consecutive integers at one x and
    one row pitch, which a scattered tag cannot fake four times running."""
    items = [(t, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, r.x1) for t, r in ann]
    cands = [(t, cx, cy, m[1], int(m[2])) for t, cx, cy, _ in items for m in [NO_RE.match(t)] if m]
    used, cols = set(), []
    for k in range(len(cands)):
        if k in used:
            continue
        _, x0, y0, letter0, num0 = cands[k]
        col, x, pitch = [(k, x0, y0, num0)], x0, None
        while True:
            by = col[-1][2]
            nxt = [(j, cx, cy, nj) for j, (t, cx, cy, lj, nj) in enumerate(cands)
                   if j not in used and j not in {c[0] for c in col} and lj == letter0 and nj == num0 + len(col)
                   and abs(cx - x) < 8 and 6 < cy - by < 30 and (pitch is None or abs(cy - by - pitch) < 4)]
            if not nxt:
                break
            j, cx, cy, nj = nxt[0]
            pitch = pitch or (cy - by)
            col.append((j, cx, cy, nj))
        if len(col) >= 4:
            used.update(c[0] for c in col)
            cols.append((letter0, col, pitch or 14))

    # cap how far right a row reaches at the next column's own x, so a row never picks up a
    # neighbouring table's cells (curve1 and curve2 sit only ~200pt apart on this sheet)
    anchors = sorted(min(c[1] for c in col) for _, col, _ in cols)

    def x_max(x0):
        nxt = min((a for a in anchors if a > x0 + 5), default=None)
        return x0 + (min(250, nxt - 10 - x0) if nxt else 250)

    rows, out_regions = {}, []
    for letter, col, pitch in cols:
        kind = "line" if letter == "L" else "curve"
        n_expected = 2 if kind == "line" else 3
        band = max(6.0, 0.6 * pitch)
        reach = []
        xcap = x_max(min(c[1] for c in col))
        for _, cx0, cy0, num in col:
            row = [(t, cx, x1) for t, cx, cy, x1 in items if not NO_RE.match(t) and cx > cx0 and cx < xcap and abs(cy - cy0) < band]
            row.sort(key=lambda z: z[1])
            cells = [c.replace("(R)", "") for t, _, _ in row for c in re.split(r"\s{2,}", t.strip()) if c][:n_expected]  # (R) a radial tie: alphabet.py's own reader never carries it
            if row:
                reach.append(max(x1 for _, _, x1 in row))
            rows[f"{letter}{num}"] = {"kind": kind, "cells": cells}
        xs = [c[1] for c in col]; ys = [c[2] for c in col]
        out_regions.append([round(min(xs) - 20), round(min(ys) - 16), round((max(reach) if reach else max(xs) + 200) + 12), round(max(ys) + 16)])
    rows["_regions"] = out_regions
    return rows


def score_vs_keyed(rows):
    try:
        from gt import TABLES
    except ImportError:
        return
    truth = {}
    L = TABLES["line"][1]
    for k in range(0, len(L), 3):
        truth[L[k].replace("(T)", "")] = [L[k + 1], L[k + 2]]
    for name in ("curve1", "curve2"):
        C = TABLES[name][1]
        for k in range(0, len(C), 4):
            truth[C[k].replace("(T)", "")] = [C[k + 1], C[k + 2], C[k + 3]]
    ok = tot = 0
    for tag, r in rows.items():
        if tag.startswith("_") or tag not in truth:
            continue
        for got, want in zip(r["cells"], truth[tag]):
            tot += 1
            ok += got == want.replace("(R)", "")
    if tot:
        print(f"vs keyed tables: {ok}/{tot} cells exact ({len(truth) - len(set(rows) & set(truth))} truth rows not found)")


def main():
    page = pymupdf.open(PDF)[0]
    glyph_blocks = json.loads((OUT / "blocks.json").read_text(encoding="utf-8"))
    ann = read_annotations(page)
    glyph_paths_idx = list(glyph_paths(page))
    blocks = build_blocks(glyph_blocks, ann, glyph_paths_idx)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "read_shx.json").write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    paired = sum(1 for b in blocks if "|" in b["text"])
    print(f"annotations {len(ann)}, blocks written {len(blocks)} (bearing|distance pairs {paired}), blocks with text {sum(1 for b in blocks if b['text'])} of {len(blocks)}")

    dis = disagreements(blocks)
    (OUT / "reads_disagree.json").write_text(json.dumps(dis, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"reads_disagree: {len(dis)}")

    if "--tables" in sys.argv:
        rows = build_tables(ann)
        (OUT / "tables.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
        t = {k: v for k, v in rows.items() if not k.startswith("_")}
        clean = sum(1 for r in t.values() if r["cells"] and not any("?" in c for c in r["cells"][:3]))
        print(f"tables from annotations: {len(t)} rows, {clean} clean ({len(rows['_regions'])} regions)")
        score_vs_keyed(rows)


if __name__ == "__main__":
    main()
