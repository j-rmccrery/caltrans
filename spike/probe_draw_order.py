"""Loop17 leg E: READ-ONLY probe -- does the PDF's own structure link a printed label to its drawn
line? Three measurements, all on spike/gold's gold-confirmed PASS pairs (verdict_by_code == "pass"
and correct_line == "true", id "label:N" only -- tag: ids skipped, see the docstring on gold_assoc.py
for the id scheme):

  1. draw-order adjacency: |order-key(label) - seqno(matched line's path)| vs the same for the
     2nd..5th nearest candidate paths.
  2. grouping: BDC/EMC /OC membership, form XObjects, annot /OC, and whether a course split by tick
     marks comes out as seqno-consecutive same-layer/width/color paths.
  3. label geometry vs line (leg F's feature): rotation diff, perpendicular offset (text heights),
     position along the line, side -- calibrated per sheet, scored as a candidate-picking rule against
     a naive nearest-distance-from-anchor baseline.

Never opens spike/out/checks.py machinery (forbidden by the brief) -- candidate lines are raw
pymupdf get_drawings() paths, not the pipeline's stitched-chain pool. That's a real simplification:
see the ceiling note in rank_candidates(). Reads only: spike/gold/*.json, spike/out*/labels.json,
spike/out*/blocks.json (all tracked, never written to), and the sheets' own PDFs.

Usage: .venv/Scripts/python.exe spike/probe_draw_order.py
Output: spike/out_probe/<sheet>_q1.csv, _q2.json, _q3.csv, _q3_wrong.csv, and a summary.md.
"""
import csv
import json
import math
import re
from pathlib import Path

import numpy as np
import pymupdf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_PROBE = HERE / "out_probe"
OUT_PROBE.mkdir(exist_ok=True)

# sheet key -> (pdf path, labels/blocks dir under spike/out) -- mirrors bench.SHEETS / gold_assoc.sheet_pdf,
# restricted to the 3 sheets spike/gold actually has a keyed set for (r10741 sheets have none: ls spike/gold/).
SHEETS = {
    "presidio": (ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf", HERE / "out"),
    "r10434_1": (ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf", HERE / "out" / "r_10434_001_2020-09-16"),
    "r10434_3": (ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf", HERE / "out" / "r_10434_003_2020-09-16"),
}

_QUOTE_SINGLE = re.compile(r"[’‘`′´]")
_QUOTE_DOUBLE = re.compile(r"[”“″]")
_DEGREE = re.compile(r"Â?°|deg\.?")


def norm_text(s):
    """Collapse quote/degree glyph variants + whitespace so annot content can be compared to labels.json
    printed strings byte-for-byte (same spirit as checks.normalize_quotes, reimplemented here so this
    probe never imports checks.py -- see module docstring)."""
    s = _QUOTE_SINGLE.sub("'", s)
    s = _QUOTE_DOUBLE.sub('"', s)
    s = _DEGREE.sub("°", s)
    return re.sub(r"\s+", "", s.strip())


def az_compass(p0, p1):
    """Undirected compass-style azimuth (0-180), matching labels.json's own "az" field / checks.py's
    bearing sense (0 = up the page). For reporting only -- NOT for comparing against blocks.json's
    glyph "angle", which uses the other convention (see az_reading)."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    return math.degrees(math.atan2(dx, -dy)) % 180


def az_reading(p0, p1):
    """Undirected reading-direction azimuth (0-180): 0 = horizontal, standard atan2(dy,dx). This is
    the convention blocks.json's "angle" (glyph-read text rotation) uses -- confirmed by hand: a
    "beside" label's block angle and its true line's az_compass differ by a near-constant ~90 deg
    (e.g. block angle -11.51 vs az_compass 78.18 -- a fixed axis offset, not label/line disagreement),
    while az_reading of the same line lands within a degree of the block angle. All rotation-vs-line
    comparisons (PathRec.azimuth, Q3's rot_diff) must use this, not az_compass, or "beside" labels
    (which really do run parallel to their line) read as if rotated ~90 deg off it."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    return math.degrees(math.atan2(dy, dx)) % 180


def poly_length_point(pts, frac):
    """Point at fraction `frac` (0=start,1=end) along a polyline's cumulative arc length."""
    pts = np.asarray(pts, float)
    seglens = np.hypot(*(pts[1:] - pts[:-1]).T)
    total = seglens.sum()
    if total <= 0:
        return pts[0]
    target = frac * total
    acc = 0.0
    for i, L in enumerate(seglens):
        if acc + L >= target or i == len(seglens) - 1:
            t = 0 if L <= 0 else (target - acc) / L
            return pts[i] + t * (pts[i + 1] - pts[i])
        acc += L
    return pts[-1]


# ---------------------------------------------------------------------------
# drawing-path index
# ---------------------------------------------------------------------------

class PathRec:
    __slots__ = ("seqno", "layer", "width", "color", "segs", "x0", "y0", "x1", "y1", "verts")

    def __init__(self, seqno, layer, width, color, segs):
        self.seqno, self.layer, self.width, self.color = seqno, layer, width, color
        self.segs = segs  # list of (p0, p1) np arrays
        xs = [p[0] for s in segs for p in s]
        ys = [p[1] for s in segs for p in s]
        self.x0, self.y0, self.x1, self.y1 = min(xs), min(ys), max(xs), max(ys)
        self.verts = np.array(xs).reshape(-1, 1), np.array(ys).reshape(-1, 1)

    def dist_to(self, pt):
        best = math.inf
        for a, b in self.segs:
            ab = b - a
            denom = ab @ ab
            t = 0.0 if denom < 1e-9 else np.clip(((pt - a) @ ab) / denom, 0, 1)
            d = np.hypot(*(pt - (a + t * ab)))
            if d < best:
                best = d
        return best

    def azimuth(self):
        """Principal direction: the two vertices farthest apart (mostly-straight courses/dash trains)."""
        xs = self.verts[0].ravel()
        ys = self.verts[1].ravel()
        pts = np.stack([xs, ys], axis=1)
        if len(pts) < 2:
            return 0.0
        # farthest pair by brute force -- paths from get_drawings have few items (leg budget, not a hot loop)
        best, bi, bj = -1, 0, 0
        for i in range(len(pts)):
            d = np.hypot(*(pts[i] - pts).T)
            j = int(np.argmax(d))
            if d[j] > best:
                best, bi, bj = d[j], i, j
        return az_reading(pts[bi], pts[bj])


def build_paths(page):
    """All stroked (type s/fs) drawing paths on the page, as PathRec, in content-stream (seqno) order."""
    drawings = page.get_drawings(extended=True)
    recs = []
    for d in drawings:
        if d["type"] not in ("s", "fs") or d.get("seqno") is None:
            continue
        segs = []
        for item in d["items"]:
            op = item[0]
            if op == "l":
                segs.append((np.array(item[1]), np.array(item[2])))
            elif op == "c":
                segs.append((np.array(item[1]), np.array(item[4])))  # bezier chord approx -- fine for "which path is near here"
        if not segs:
            continue
        recs.append(PathRec(d["seqno"], d.get("layer") or "", d.get("width"), d.get("color"), segs))
    recs.sort(key=lambda r: r.seqno)
    return recs


def is_course_layer(layer):
    """True for a real boundary/alignment linework layer -- excludes per-label decoration (leader
    ticks, witness marks, wipeout masks) and sheet furniture. Found empirically (debug on r10434_1):
    layers named "*-LBL-*" outnumber labels ~20-35x (2570 paths under RW-ALGN-LBL-NEW-NRA against ~72
    labels on that sheet) -- clearly per-label graphic boilerplate, not boundary lines -- and one of
    them routinely sat closer to a label's anchor than its actual line, making "nearest path to anchor"
    pick the label's own decoration instead of any course, on every "beside" label tried before this
    filter (rank-1 hit rate 0/54 -> 19/54 on r10434_1 once LBL layers are excluded). "*-LNWK-*" and
    "*-PARCEL-SEG-*" are the real boundary/alignment linework layers."""
    l = (layer or "").upper()
    if "LBL" in l:
        return False
    return ("LNWK" in l) or ("PARCEL-SEG" in l) or ("LNDNT" in l)


def nearby(recs, pt, radius=300.0):
    """Course-layer PathRecs whose bbox (expanded by radius) contains pt -- a coarse prefilter before
    exact dist_to."""
    x, y = pt
    return [r for r in recs if is_course_layer(r.layer)
            and r.x0 - radius <= x <= r.x1 + radius and r.y0 - radius <= y <= r.y1 + radius]


def rank_candidates(recs, pt, k=8, radius=500.0):
    """Top-k distinct paths nearest `pt`, ascending distance. Candidate pool = raw drawn paths, not the
    pipeline's stitched-chain pool (checks.build_pool/split_chains): a real ceiling -- a course drawn as
    N dash segments shows up here as N separate candidates at ~the same distance/azimuth instead of one,
    so this undercounts how distinctive the true "chain" is and can only make the rule's job *harder*
    than the real candidate pool would (more near-duplicate candidates to confuse it), not easier."""
    cand = nearby(recs, pt, radius)
    scored = sorted(((r.dist_to(np.array(pt)), r) for r in cand), key=lambda t: t[0])
    return scored[:k]


# ---------------------------------------------------------------------------
# annot index (Civil3D SHX-text labels live as page annotations, not content-stream text -- verified
# by hand: printed bearing strings are absent from page.get_text() but present in annot.info["content"])
# ---------------------------------------------------------------------------

class AnnotRec:
    __slots__ = ("xref", "order", "rect", "content")

    def __init__(self, xref, order, rect, content):
        self.xref, self.order, self.rect, self.content = xref, order, rect, content


def build_annots(page):
    out = []
    for i, a in enumerate(page.annots()):
        content = a.info.get("content", "")
        out.append(AnnotRec(a.xref, i, a.rect, content))
    return out


def match_annot(annots, printed, region):
    """The annot whose (quote/degree-normalized) content equals `printed`, nearest to `region`'s center."""
    want = norm_text(printed)
    cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
    best, bd = None, math.inf
    for a in annots:
        if norm_text(a.content) != want:
            continue
        acx, acy = (a.rect.x0 + a.rect.x1) / 2, (a.rect.y0 + a.rect.y1) / 2
        d = math.hypot(acx - cx, acy - cy)
        if d < bd:
            best, bd = a, d
    return best, bd


def content_index(labels):
    """(kind, normalized-printed) -> labels.json index, for joining gold ids that no longer line up
    with the live file's positions (see process_sheet). Ambiguous keys (text repeated on the sheet)
    are flagged, not guessed at."""
    by_content, ambiguous = {}, set()
    for i, lb in enumerate(labels):
        key = (lb["kind"], norm_text(lb["printed"]))
        if key in by_content:
            ambiguous.add(key)
        else:
            by_content[key] = i
    return by_content, ambiguous


def resolve_label(labels, by_content, ambiguous, g):
    key = (g["kind"], norm_text(g["printed"]))
    if key in ambiguous or key not in by_content:
        return None
    return labels[by_content[key]]


def match_block(blocks, region):
    """Nearest blocks.json entry (glyph-read text block: cx,cy,w,h,angle,glyph_h) to a label's region
    center -- gives real per-glyph rotation, which an annot's always-axis-aligned Rect cannot."""
    cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
    best, bd = None, math.inf
    for b in blocks:
        d = math.hypot(b["cx"] - cx, b["cy"] - cy)
        if d < bd:
            best, bd = b, d
    return best, bd


# ---------------------------------------------------------------------------
# per-sheet processing
# ---------------------------------------------------------------------------

def fold180(a):
    """Fold an angle difference to [0,90] (undirected-line rotation diff)."""
    return abs((a + 90) % 180 - 90)


def process_sheet(key, pdf_path, out_dir):
    gold = json.loads((ROOT / "spike" / "gold" / f"{key}_assoc.json").read_text(encoding="utf-8"))
    labels = json.loads((out_dir / "labels.json").read_text(encoding="utf-8"))
    blocks = json.loads((out_dir / "blocks.json").read_text(encoding="utf-8"))

    doc = pymupdf.open(str(pdf_path))
    page = doc[0]
    recs = build_paths(page)
    annots = build_annots(page)

    is_label_idx = re.compile(r"^label:\d+$")  # excludes loop13 leg H's "label:legH:<printed>" bare-(T) ids -- not a labels.json index
    passes = [g for g in gold if is_label_idx.match(g["id"]) and g["verdict_by_code"] == "pass" and g["correct_line"] == "true"]
    wrongs = [g for g in gold if is_label_idx.match(g["id"]) and g["correct_line"] == "false"]

    # labels.json is a live pipeline output another agent is rewriting right now (brief's warning) --
    # measured: on presidio, 91/98 gold "label:N" indices no longer point at the label gold keyed
    # (reordered/inserted, not just appended). A (kind, normalized-printed) content join recovers
    # 97/98 uniquely (1 ambiguous, 0 vanished) -- use that instead of trusting the index.
    by_content, ambiguous_keys = content_index(labels)

    q1_rows, q3_rows = [], []

    unmatched_annot = unmatched_true = drifted = 0
    for g in passes:
        lb = resolve_label(labels, by_content, ambiguous_keys, g)
        if lb is None:
            drifted += 1
            continue
        line = lb["line"]
        region = lb["region"]

        # --- annot (label's own order key) ---
        annot, adist = match_annot(annots, g["printed"], region)
        if annot is None or adist > 80:
            unmatched_annot += 1
            continue

        # --- true line's path: nearest raw path to the label-line's own midpoint (by arc length) ---
        mid = poly_length_point(line, 0.5)
        true_cands = rank_candidates(recs, mid, k=1, radius=150)
        if not true_cands or true_cands[0][0] > 3.0:
            unmatched_true += 1
            continue
        true_dist, true_rec = true_cands[0]

        # --- candidate pool from the LABEL's own anchor point (region center) -- no leakage of `mid` ---
        cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
        pool = rank_candidates(recs, (cx, cy), k=8, radius=400)
        pool_seqnos = [r.seqno for _, r in pool]
        true_rank = pool_seqnos.index(true_rec.seqno) + 1 if true_rec.seqno in pool_seqnos else None

        offs = [abs(annot.order - r.seqno) for _, r in pool]
        offs_xref = [abs(annot.xref - r.seqno) for _, r in pool]
        row = {
            "id": g["id"], "kind": g["kind"], "printed": g["printed"], "how": lb["how"],
            "annot_xref": annot.xref, "annot_order": annot.order,
            "true_seqno": true_rec.seqno, "true_dist_pt": round(true_dist, 3),
            "true_rank_in_pool": true_rank, "pool_size": len(pool),
            "off_order_true": abs(annot.order - true_rec.seqno),
            "off_xref_true": abs(annot.xref - true_rec.seqno),
        }
        for r_i in range(1, 6):  # ranks 1..5 by distance from anchor (1 may or may not be the true line)
            if r_i <= len(pool):
                _, r = pool[r_i - 1]
                row[f"off_order_rank{r_i}"] = abs(annot.order - r.seqno)
                row[f"off_xref_rank{r_i}"] = abs(annot.xref - r.seqno)
                row[f"is_true_rank{r_i}"] = (r.seqno == true_rec.seqno)
        q1_rows.append(row)

        # --- Q3: label geometry vs the true line ---
        block, bdist = match_block(blocks, region)
        angle = block["angle"] if (block and bdist < 60) else None
        gh = block["glyph_h"] if (block and bdist < 60) else max(region[3] - region[1], 1.0)
        true_az = az_reading(line[0], line[-1])  # blocks.json angle's own convention -- see az_reading docstring
        p0, p1 = np.array(line[0]), np.array(line[-1])
        u = (p1 - p0) / max(np.hypot(*(p1 - p0)), 1e-9)
        n = np.array([-u[1], u[0]])
        anchor = np.array([cx, cy])
        along = (anchor - p0) @ u
        line_len = np.hypot(*(p1 - p0))
        perp = (anchor - p0) @ n
        rot_diff = fold180(angle - true_az) if angle is not None else None

        # naive baseline pick = nearest-by-distance-from-anchor (rank 1 of the pool)
        naive_pick = pool[0][1] if pool else None
        q3_rows.append({
            "id": g["id"], "kind": g["kind"], "how": lb["how"], "printed": g["printed"],
            "angle": angle, "true_az": true_az, "rot_diff": rot_diff,
            "perp_offset_pt": round(float(perp), 2), "perp_offset_th": round(float(perp) / gh, 3) if gh else None,
            "along_frac": round(float(along / line_len), 3) if line_len > 1e-6 else None,
            "side": 1 if perp >= 0 else -1,
            "true_seqno": true_rec.seqno, "pool_seqnos": pool_seqnos,
            "naive_pick_seqno": naive_pick.seqno if naive_pick else None,
            "gh": gh, "region": region,  # region kept for the rule-scoring pass below (no re-lookup by id needed)
        })

    # ---- rule vs naive top-1 accuracy, calibrated per (sheet, how) bucket ----
    # (calibration uses the bucket's own medians, not leave-one-out -- a small optimism bias toward the
    # rule the report calls out; medians over ~30-100 points barely move if one point is excluded)
    by_how = {}
    for r in q3_rows:
        by_how.setdefault(r["how"], []).append(r)
    rule_correct = naive_correct = scored_n = 0
    for how, rows in by_how.items():
        rotd = [r["rot_diff"] for r in rows if r["rot_diff"] is not None]
        offd = [r["perp_offset_th"] for r in rows if r["perp_offset_th"] is not None]
        if not rotd or not offd:
            continue
        med_rot, med_off = float(np.median(rotd)), float(np.median(offd))
        mad_rot = float(np.median(np.abs(np.array(rotd) - med_rot))) + 1.0
        mad_off = float(np.median(np.abs(np.array(offd) - med_off))) + 0.2
        for r in rows:
            if r["angle"] is None or not r["pool_seqnos"]:
                continue
            gh = r["gh"]
            # recompute per-candidate features using the SAME label anchor against each pool member's own line
            region = r["region"]
            cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
            anchor = np.array([cx, cy])
            best_c, best_score = None, math.inf
            for seq in r["pool_seqnos"]:
                rec = next((rc for rc in recs if rc.seqno == seq), None)
                if rec is None:
                    continue
                az = rec.azimuth()
                rd = fold180(r["angle"] - az)
                # perpendicular offset using this candidate's own principal axis through its nearest point
                d = rec.dist_to(anchor) / gh if gh else rec.dist_to(anchor)
                score = abs(rd - med_rot) / mad_rot + abs(d - med_off) / mad_off
                if score < best_score:
                    best_score, best_c = score, seq
            if best_c is None:
                continue
            scored_n += 1
            rule_correct += int(best_c == r["true_seqno"])
            naive_correct += int(r["naive_pick_seqno"] == r["true_seqno"])

    # ---- Q2: grouping ----
    contents = page.get_contents()
    bdc_oc, bdc_other = 0, 0
    for xref in contents:
        raw = doc.xref_stream(xref)
        n_oc = len(re.findall(rb"/OC\s*/\w+\s+BDC", raw))
        n_total = len(re.findall(rb"BDC", raw))
        bdc_oc += n_oc
        bdc_other += n_total - n_oc
    n_xobjects = len(page.get_xobjects())
    annot_with_oc = sum(1 for a in page.annots() if "/OC" in doc.xref_object(a.xref))

    # re-merge check: within each (layer, width, rounded color) group, sorted by seqno, what fraction of
    # seqno-adjacent pairs have touching endpoints (<=1.0 pt) -- "could tick-marked pieces be re-glued
    # exactly by seqno order alone"
    groups = {}
    for r in recs:
        key = (r.layer, r.width, tuple(round(c, 3) for c in r.color) if r.color else None)
        groups.setdefault(key, []).append(r)
    touch_pairs = touch_total = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda r: r.seqno)
        for a, b in zip(members, members[1:]):
            touch_total += 1
            # endpoints: last vertex of a vs first vertex of b (both directions checked)
            a_pts = [p for s in a.segs for p in s]
            b_pts = [p for s in b.segs for p in s]
            d = min(np.hypot(*(ap - bp)) for ap in (a_pts[0], a_pts[-1]) for bp in (b_pts[0], b_pts[-1]))
            if d <= 1.0:
                touch_pairs += 1

    q2 = {
        "n_content_streams": len(contents),
        "bdc_with_oc": bdc_oc, "bdc_other": bdc_other,
        "n_xobjects": n_xobjects,
        "n_annots": len(annots), "annots_with_oc": annot_with_oc,
        "n_stroked_paths": len(recs),
        "n_layer_width_color_groups": len(groups),
        "seqno_adjacent_same_group_pairs": touch_total,
        "seqno_adjacent_touching_le_1pt": touch_pairs,
        "touch_rate": round(touch_pairs / touch_total, 3) if touch_total else None,
        "unmatched_annot": unmatched_annot, "unmatched_true_line": unmatched_true,
        "drifted_index": drifted,
    }

    return {
        "key": key, "n_gold_pass": len(passes), "n_wrong": len(wrongs),
        "q1_rows": q1_rows, "q3_rows": q3_rows, "q2": q2,
        "rule_correct": rule_correct, "naive_correct": naive_correct, "scored_n": scored_n,
        "recs": recs, "labels": labels, "annots": annots, "wrongs": wrongs, "page": page,
    }


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in keys})


def wrong_line_probe(res):
    """For each gold-keyed WRONG-line fail: candidate pool from the label's own anchor + rule-picked
    top candidate's diagnostics, for eyeballing against the gold note (no ground-truth line coords
    exist for these -- notes are the only description of "the right line")."""
    labels, recs = res["labels"], res["recs"]
    by_content, ambiguous_keys = content_index(labels)
    out = []
    for g in res["wrongs"]:
        lb = resolve_label(labels, by_content, ambiguous_keys, g)
        if lb is None:
            continue
        region = lb["region"]
        cx, cy = (region[0] + region[2]) / 2, (region[1] + region[3]) / 2
        pool = rank_candidates(recs, (cx, cy), k=5, radius=400)
        out.append({
            "id": g["id"], "kind": g["kind"], "printed": g["printed"], "how": lb["how"],
            "note": g["note"],
            "pipeline_line": lb["line"],
            "candidates": [{"seqno": r.seqno, "dist_pt": round(d, 2), "layer": r.layer,
                             "azimuth": round(r.azimuth(), 1)} for d, r in pool],
        })
    return out


def main():
    summary_lines = ["# probe_draw_order.py -- Loop17 leg E\n"]
    for key, (pdf_path, out_dir) in SHEETS.items():
        if not pdf_path.exists() or not (out_dir / "labels.json").exists():
            print(f"{key}: SKIP (missing pdf or labels.json)")
            continue
        res = process_sheet(key, pdf_path, out_dir)
        write_csv(OUT_PROBE / f"{key}_q1.csv", res["q1_rows"])
        write_csv(OUT_PROBE / f"{key}_q3.csv", res["q3_rows"])
        (OUT_PROBE / f"{key}_q2.json").write_text(json.dumps(res["q2"], indent=1), encoding="utf-8")
        wrong = wrong_line_probe(res)
        (OUT_PROBE / f"{key}_q3_wrong.json").write_text(json.dumps(wrong, indent=1, default=str), encoding="utf-8")

        n = len(res["q1_rows"])
        offs_true = [r["off_order_true"] for r in res["q1_rows"]]
        offs_r2_5 = [r[f"off_order_rank{i}"] for r in res["q1_rows"] for i in range(2, 6)
                     if f"off_order_rank{i}" in r and not r.get(f"is_true_rank{i}")]
        rank1_is_true = sum(1 for r in res["q1_rows"] if r.get("true_rank_in_pool") == 1)
        line = (f"\n## {key}\n"
                f"- gold pass (label:N, distinct-line proximity match ok): {n} / {res['n_gold_pass']} "
                f"({res['q2']['unmatched_annot']} annot no-match, {res['q2']['unmatched_true_line']} true-line no-match, "
                f"{res['q2']['drifted_index']} labels.json index past current file end -- live pipeline drift)\n"
                f"- true line's own annot-order-key offset: median {np.median(offs_true):.0f}, "
                f"IQR [{np.percentile(offs_true,25):.0f}, {np.percentile(offs_true,75):.0f}]\n"
                f"- ranks 2-5 candidate offset: median {np.median(offs_r2_5):.0f} (n={len(offs_r2_5)})\n"
                f"- true line is rank-1 by raw distance from label anchor: {rank1_is_true}/{n}\n"
                f"- Q2: {res['q2']['bdc_with_oc']} OC-tagged BDC groups, {res['q2']['bdc_other']} other BDC, "
                f"{res['q2']['n_xobjects']} form XObjects, {res['q2']['annots_with_oc']}/{res['q2']['n_annots']} annots carry /OC, "
                f"tick-mark re-merge touch rate {res['q2']['touch_rate']}\n"
                f"- Q3 rule vs naive top-1 (leave-one-out per how-bucket, scored n={res['scored_n']}): "
                f"rule {res['rule_correct']}/{res['scored_n']}, naive {res['naive_correct']}/{res['scored_n']}\n"
                f"- wrong-line fails probed: {len(res['wrongs'])} -> {key}_q3_wrong.json\n")
        summary_lines.append(line)
        print(line)
    (OUT_PROBE / "summary.md").write_text("".join(summary_lines), encoding="utf-8")
    print(f"\nwritten to {OUT_PROBE}")


if __name__ == "__main__":
    main()
