"""Two unused sources of truth, checked (does NOT edit checks.py/solve.py/tables.py, does NOT change
the solver): (1) each sheet's own ALIGNMENT DATA / coordinate table (STATION/NORTHING/EASTING rows,
currently only masked as noise by checks.alignment_table_regions) against station arithmetic and
against the georef.py fit; (2) the L#/C# line/curve tables' own internal consistency (L = R*delta,
tangency, chord), currently only spot-checked by hand in gt.py for one sheet.

Reads ONLY from the frozen snapshot (--snap) plus the read-only sheet PDFs under Sample Data/.
Never touches spike/out (another agent owns it).

usage: python spike/record_checks.py --snap <dir>
outputs: spike/out_record/<sheet>_record_checks.json, spike/out_record/summary.md, crops for
failing table self-checks in spike/out_record/crops/
"""
import argparse
import itertools
import json
import math
import re
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).parent / "out_record"
CROPS = OUT / "crops"

# (label, snapshot subdir ("" = top level), sheet pdf path relative to Sample Data)
SHEETS = [
    ("R-10434.2", "", "Right-of-Way Map Record/r_10434_002_2020-09-16.pdf"),
    ("R-10434.1", "r_10434_001_2020-09-16", "d4/r_10434_001_2020-09-16.pdf"),
    ("R-10434.3", "r_10434_003_2020-09-16", "d4/r_10434_003_2020-09-16.pdf"),
    ("R-10741.1", "r_10741_001_2017-02-10", "d4/r_10741_001_2017-02-10.pdf"),
    ("R-10741.2", "r_10741_002_2017-02-10", "d4/r_10741_002_2017-02-10.pdf"),
    ("R-10741.3", "r_10741_003_2017-02-10", "d4/r_10741_003_2017-02-10.pdf"),
]

NUM = re.compile(r"^([NEXY])?[:.]?(\d[\d,]{2,9}\.\d{2,4})$")
STATION_ROW = re.compile(r"^(\d{1,4})\+(\d{2}\.\d{2})\s*([A-Z]{2,4}(?:\(\w+\))?)?$")
STATION_ANY = re.compile(r"\d\+\d")
CURVE_TAGS = {"BC", "EC", "PC", "PT", "TC", "CT", "CC"}
BEAR = re.compile(r"^([NS])(\d{1,2})°(\d{2})'(\d{2})\"([EW])(?:\(\w\))?$")
DIST = re.compile(r"^([\d,]{1,7}\.\d{2,3})'?(?:\(\w\))?$")
DMS = re.compile(r"(\d{1,3})°(\d{2})'(\d{2})\"")
NO_TAG_RE = re.compile(r"^([LC])(\d+)(\(T\))?$")


def number(text):
    m = NUM.match(text.replace(" ", "").upper())
    if not m or not 4 <= len(m[2].split(".")[0].replace(",", "")) <= 8:
        return None
    return {"N": "N", "Y": "N", "E": "E", "X": "E"}.get(m[1]), float(m[2].replace(",", ""))


def clean_num(s):
    return float(re.sub(r"[^\d.]", "", s.split("(")[0]))


def dms_to_deg(s):
    m = DMS.search(s)
    d, mi, se = (float(x) for x in m.groups())
    return d + mi / 60 + se / 3600


# --- copied, read-only, from georef.py / checks.py (not imported: importing georef.py touches the
# live spike/out at module load via its READS/_validated globals, which we must not read) ---

def segments(page):
    segs, circles = [], []
    for pid, d in enumerate(page.get_drawings()):
        r = d["rect"]
        kinds = {i[0] for i in d["items"]}
        if "c" in kinds and 2 < r.width < 9 and abs(r.width - r.height) < 1:
            circles.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
        for it in d["items"]:
            if it[0] == "l":
                a, b = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
                if np.hypot(*(a - b)) > 3:
                    segs.append((a, b, round(d.get("width") or 0, 2), pid))
    return segs, np.array(circles)


def thin_ticks(page, lo=5.0, hi=10.0, max_w=0.8):
    """Short thin stroke segments: candidate stationing ticks (checks.py: 'ticks are 7.2-pt stubs')."""
    out = []
    for d in page.get_drawings():
        w = d.get("width") or 0
        if w >= max_w:
            continue
        for it in d["items"]:
            if it[0] != "l":
                continue
            a, b = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
            ln = np.hypot(*(a - b))
            if lo < ln < hi:
                out.append((a + b) / 2)
    return np.array(out) if out else np.zeros((0, 2))


def alignment_table_regions(blocks, gap=30):
    """checks.alignment_table_regions, copied (not edited): bbox of each STATION/NORTHING/EASTING table."""
    headers = [b for b in blocks if b["text"].strip() in ("STATION", "NORTHING", "EASTING")]
    regions = []
    for st in (h for h in headers if h["text"].strip() == "STATION"):
        row = [st] + [h for h in headers if h is not st and abs(h["cy"] - st["cy"]) < 15 and h["cx"] > st["cx"]]
        x0 = min(h["cx"] - h.get("w", 40) / 2 for h in row) - 60
        x1 = max(h["cx"] + h.get("w", 60) / 2 for h in row) + 20
        col = sorted((b for b in blocks if x0 <= b["cx"] <= x1 and b["cy"] > st["cy"]), key=lambda b: b["cy"])
        y1 = st["cy"] + 15
        for b in col:
            if b["cy"] - y1 > gap:
                break
            y1 = max(y1, b["cy"] + 15)
        regions.append({"box": (round(x0), round(st["cy"] - 25), round(x1), round(y1)),
                         "headers": {h["text"].strip(): h["cx"] for h in row}})
    return regions


def load_blocks(snap_dir):
    """georef.py's READS choice (shx > glyph > rapid), against the frozen snapshot."""
    def has_text(p):
        if not p.exists() or p.stat().st_size < 2:
            return False
        try:
            return any(b.get("text") for b in json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            return False
    rs, rg, rr = snap_dir / "read_shx.json", snap_dir / "read_glyph.json", snap_dir / "read_rapid.json"
    p = rs if has_text(rs) else (rg if has_text(rg) else rr)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else [], p.name


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# --- Part A: alignment coordinate table ---

def read_alignment_rows(blocks, region):
    box, headers = region["box"], region["headers"]
    if "NORTHING" not in headers or "EASTING" not in headers:
        return []
    x0, y0, x1, y1 = box
    n_x, e_x = headers["NORTHING"], headers["EASTING"]
    st_x = headers["STATION"]
    inside = [b for b in blocks if x0 <= b["cx"] <= x1 and y0 + 20 <= b["cy"] <= y1]
    # cluster into rows by cy
    inside.sort(key=lambda b: b["cy"])
    rows, cur = [], []
    for b in inside:
        if cur and b["cy"] - cur[-1]["cy"] > 8:
            rows.append(cur)
            cur = []
        cur.append(b)
    if cur:
        rows.append(cur)
    out = []
    for row in rows:
        st_b = min((b for b in row if abs(b["cx"] - st_x) < 60), key=lambda b: abs(b["cx"] - st_x), default=None)
        n_b = min((b for b in row if abs(b["cx"] - n_x) < 60), key=lambda b: abs(b["cx"] - n_x), default=None)
        e_b = min((b for b in row if abs(b["cx"] - e_x) < 60), key=lambda b: abs(b["cx"] - e_x), default=None)
        if st_b is None or n_b is None or e_b is None:
            continue
        m = STATION_ROW.match(st_b["text"].strip())
        nv, ev = number(n_b["text"]), number(e_b["text"])
        if not m or not nv or not ev:
            continue
        sta_ft = int(m[1]) * 100 + float(m[2])
        out.append({"station_text": st_b["text"].strip(), "station_ft": sta_ft, "point_type": m[3],
                    "N": nv[1], "E": ev[1], "cy": st_b["cy"]})
    return out  # print order (row letter order), NOT sorted by station: these tables are not always monotonic


def crop_alignment_row(blocks, page, region_box, station_text, slug, tag):
    x0, y0, x1, y1 = region_box
    hit = [b for b in blocks if b["text"].strip() == station_text and x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1]
    if not hit:
        return None
    tb = hit[0]
    row = [b for b in blocks if x0 <= b["cx"] <= x1 and abs(b["cy"] - tb["cy"]) < 8]
    rx0 = min(b["cx"] - b.get("w", 20) / 2 for b in row) - 15
    rx1 = max(b["cx"] + b.get("w", 20) / 2 for b in row) + 15
    ry0 = min(b["cy"] - b.get("h", 14) / 2 for b in row) - 8
    ry1 = max(b["cy"] + b.get("h", 14) / 2 for b in row) + 8
    CROPS.mkdir(parents=True, exist_ok=True)
    out_png = CROPS / f"{slug}_align_{tag}.png"
    page.get_pixmap(clip=pymupdf.Rect(rx0, ry0, rx1, ry1), matrix=pymupdf.Matrix(4, 4)).save(out_png)
    return str(out_png)


def part_a(blocks, regions, page, georef, slug=""):
    align_regions = [r for r in regions if "NORTHING" in r["headers"] and "EASTING" in r["headers"] and "STATION" in r["headers"]]
    if not align_regions:
        return {"found": False}
    tables_rows = [read_alignment_rows(blocks, r) for r in align_regions]
    rows = [r for tr in tables_rows for r in tr]
    if not rows:
        return {"found": True, "rows_read": 0, "note": "STATION/NORTHING/EASTING header found but no rows parsed"}

    # (a) station diff vs N/E chord distance, consecutive as PRINTED (row-letter order) within each
    # physical table -- these tables are not always monotonic in station (BC/EC pairs of different
    # curves interleave), so pairing is per-table, never across two separate table boxes.
    pairs = []
    for tr in tables_rows:
        for r0, r1 in zip(tr, tr[1:]):
            dist = math.hypot(r1["N"] - r0["N"], r1["E"] - r0["E"])
            sta_diff = r1["station_ft"] - r0["station_ft"]
            is_curve = (r0["point_type"] in CURVE_TAGS) or (r1["point_type"] in CURVE_TAGS)
            # two different outlier shapes: chord huge but station step small -> a dropped/garbled N or E
            # digit (misread); station step huge but chord small -> these two rows are physically close
            # points on what must be a DIFFERENT reference line/stationing than the row before (two
            # alignments sharing one coordinate table), not an error at all
            misread = dist > 5000 and abs(sta_diff) < 1000
            multi_alignment = abs(sta_diff) > 1000 and dist < 2000
            pairs.append({"a": r0["station_text"], "b": r1["station_text"], "station_diff_ft": round(sta_diff, 2),
                          "chord_ft": round(dist, 2), "diff_ft": round(dist - abs(sta_diff), 2), "curve": is_curve,
                          "non_monotonic": sta_diff < 0, "likely_misread": misread, "different_alignment": multi_alignment})
            if misread:
                box = next(rg["box"] for rg, tr2 in zip(align_regions, tables_rows) if r0 in tr2 or r1 in tr2)
                for txt in (r0["station_text"], r1["station_text"]):
                    crop_alignment_row(blocks, page, box, txt, slug, txt.split()[0])

    # (b) row N/E through the georef fit -> residual to nearest drawn vertex
    residuals = []
    if georef and georef.get("params"):
        a, b, tx, ty = georef["params"]
        scale = georef["scale_ft_per_pt"]
        M = np.array([[a, -b], [b, a]])
        segs, circles = segments(page)
        verts = [np.array([q[0], -q[1]]) for s0, s1, _, _ in segs for q in (s0, s1)]
        if len(circles):
            verts += [np.array([cx, -cy]) for cx, cy in circles]
        tree = cKDTree(np.array(verts)) if verts else None
        for r in rows:
            if tree is None:
                break
            sxy = np.linalg.solve(M, np.array([r["E"] - tx, r["N"] - ty]))
            d, _ = tree.query(sxy)
            residuals.append({"station": r["station_text"], "residual_ft": round(float(d) * scale, 2),
                              "likely_misread": float(d) * scale > 1000})

    # (c) alt fit from alignment rows only (vertex-matched proxy control -- see note), vs the callout fit
    alt_fit = None
    if georef and georef.get("params") and residuals:
        a, b, tx, ty = georef["params"]
        scale = georef["scale_ft_per_pt"]
        M = np.array([[a, -b], [b, a]])
        segs, circles = segments(page)
        verts = np.array([[q[0], -q[1]] for s0, s1, _, _ in segs for q in (s0, s1)] +
                          [[cx, -cy] for cx, cy in circles])
        tree = cKDTree(verts)
        good_src, good_dst = [], []
        for r in rows:
            sxy = np.linalg.solve(M, np.array([r["E"] - tx, r["N"] - ty]))
            d, j = tree.query(sxy)
            if d * scale < 5.0:  # ponytail: fixed 5 ft gate on the vertex-snap distance, not tuned per sheet
                good_src.append(verts[j])
                good_dst.append([r["E"], r["N"]])
        if len(good_src) >= 2:
            src, dst = np.array(good_src), np.array(good_dst)
            A = np.zeros((2 * len(src), 4)); L = dst.reshape(-1)
            A[0::2] = np.c_[src[:, 0], -src[:, 1], np.ones(len(src)), np.zeros(len(src))]
            A[1::2] = np.c_[src[:, 1], src[:, 0], np.zeros(len(src)), np.ones(len(src))]
            pa, pb, ptx, pty = np.linalg.lstsq(A, L, rcond=None)[0]
            alt_scale, alt_rot = float(np.hypot(pa, pb)), float(np.degrees(np.arctan2(pb, pa)))
            pred = np.c_[pa * src[:, 0] - pb * src[:, 1] + ptx, pb * src[:, 0] + pa * src[:, 1] + pty]
            res = np.hypot(*(pred - dst).T)
            alt_fit = {"n_points": len(good_src), "scale_ft_per_pt": alt_scale, "rotation_deg": alt_rot,
                       "tx": float(ptx), "ty": float(pty), "rms_ft": float(np.sqrt((res ** 2).mean())),
                       "vs_callout_fit": {"scale_diff": alt_scale - scale, "rotation_diff_deg": alt_rot - (georef["rotation_deg"] if georef else None)}}

    return {"found": True, "rows_read": len(rows), "pairs": pairs, "residuals": residuals, "alt_fit": alt_fit}


# --- Part B: station labels on the drawing vs their tick on the centreline ---

def nearest_on_segments(p, segs, seg_tree_pts=None):
    """Point on the nearest drawn segment to p (any weight). ponytail: no leader/hatch/table exclusion
    like checks.sheet_lines() has -- same 'nearest line' ambiguity Known Traps already documents for
    this codebase (wrong-line rate); good enough for a measure-only spike check, not a solver input."""
    P = np.array(p)
    best = None
    for a, b, w, pid in segs:
        ab = b - a
        t = np.clip(np.dot(P - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
        proj = a + t * ab
        d = np.hypot(*(proj - P))
        if best is None or d < best[0]:
            best = (d, proj)
    return best


def part_b(blocks, table_boxes, page, georef):
    labels = [b for b in blocks if STATION_ANY.search(b["text"]) and not any(
        x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in table_boxes)]
    parsed = []
    for b in labels:
        m = re.search(r"(\d{1,4})\+(\d{2}\.?\d{0,2})", b["text"])
        if not m:
            continue
        try:
            sta_ft = int(m[1]) * 100 + float(m[2])
        except ValueError:
            continue
        parsed.append({"text": b["text"].strip(), "sta_ft": sta_ft, "p": np.array([b["cx"], b["cy"]])})
    if not parsed:
        return {"labels_found": 0}
    segs, _ = segments(page)
    scale = georef["scale_ft_per_pt"] if georef else 1.0
    matched = []
    for lb in parsed:
        d, proj = nearest_on_segments(lb["p"], segs)
        if d < 15:  # the label sits right beside the line/tick it names, not across the sheet
            matched.append({**lb, "point": proj, "snap_dist_pt": float(d)})
    matched.sort(key=lambda r: r["sta_ft"])
    pairs = []
    for r0, r1 in zip(matched, matched[1:]):
        d_ft = float(np.hypot(*(r1["point"] - r0["point"]))) * scale
        sta_diff = r1["sta_ft"] - r0["sta_ft"]
        if sta_diff <= 0:
            continue
        pairs.append({"a": r0["text"], "b": r1["text"], "station_diff_ft": round(sta_diff, 2),
                      "line_dist_ft": round(d_ft, 2), "diff_ft": round(d_ft - sta_diff, 2)})
    return {"labels_found": len(parsed), "snapped_to_a_line": len(matched), "pairs": pairs,
            "note": "line_dist is straight-line ft between the two labels' nearest-segment points, not "
                    "arc-traced along curves, and 'nearest segment' can pick the wrong parallel line "
                    "(same ambiguity STATE.md's Known Traps already documents for this codebase)"}


# --- Part C: the L#/C# tables' own consistency ---

def part_c(tables, blocks, page, sheet_snap, sheet_slug):
    if not tables:
        return {"found": False}
    rows = {k: v for k, v in tables.items() if k != "_regions"}
    regions = tables.get("_regions", [])
    if not rows:
        return {"found": False}

    def in_region(b, pad=0):
        return any(x0 - pad <= b["cx"] <= x1 + pad and y0 - pad <= b["cy"] <= y1 + pad for x0, y0, x1, y1 in regions)

    fails = []
    curve_results = []
    for tag, row in rows.items():
        if row["kind"] != "curve" or len(row["cells"]) != 3:
            if row["kind"] == "curve":
                fails.append({"tag": tag, "check": "L=R*delta", "reason": f"only {len(row['cells'])} cells read", "cells": row["cells"]})
            continue
        try:
            R = clean_num(row["cells"][0])
            delta = dms_to_deg(row["cells"][1])
            L = clean_num(row["cells"][2])
        except (ValueError, AttributeError, TypeError) as e:
            fails.append({"tag": tag, "check": "L=R*delta", "reason": f"unparsable: {e}", "cells": row["cells"]})
            continue
        calc = R * math.radians(delta)
        # 2-decimal rounding on R, delta(seconds) and L: ~R*1e-2 rad plus 0.01 ft slack
        tol = max(0.03, R * math.radians(1 / 3600) + 0.01)
        ok = abs(calc - L) < tol
        curve_results.append({"tag": tag, "R": R, "delta_deg": round(delta, 6), "L_printed": L,
                              "L_calc": round(calc, 3), "diff": round(calc - L, 3), "pass": ok})
        if not ok:
            fails.append({"tag": tag, "check": "L=R*delta", "reason": f"calc {calc:.2f} vs printed {L:.2f}", "cells": row["cells"]})

    line_results = []
    for tag, row in rows.items():
        if row["kind"] != "line":
            continue
        if len(row["cells"]) != 2:
            fails.append({"tag": tag, "check": "line row", "reason": f"only {len(row['cells'])} cells read (expected bearing+distance)", "cells": row["cells"]})
            continue
        line_results.append({"tag": tag, "bearing": row["cells"][0], "distance": row["cells"][1]})

    # chord: never printed as a 4th cell on any sheet seen (curve rows are always R, delta, L)
    chord_note = "no chord column printed in this sheet's curve tables (cells are always R, delta, L)"

    # tangency, informational: adjacency from tag_labels.json's traced drawn endpoints (topology only);
    # the actual check compares PRINTED az (tag_labels' `az`, parsed off the same bearing text as
    # tables.json) against PRINTED delta -- a record self-check, geometry is only used to say which
    # rows are neighbours.
    tang = tangency_check(sheet_snap, rows)

    # crops for every failure + every curve-table row whose cell count is wrong, to classify misread vs
    # real record inconsistency
    crops = []
    for f in fails:
        tag = f["tag"]
        m = NO_TAG_RE.match(tag)
        if not m:
            continue
        cand = [b for b in blocks if b["text"].strip() == tag and in_region(b, pad=2)]
        if not cand:
            continue
        tb = cand[0]
        row_blocks = [b for b in blocks if in_region(b) and abs(b["cy"] - tb["cy"]) < 8]
        x0 = min(b["cx"] - b.get("w", 20) / 2 for b in row_blocks) - 15
        x1 = max(b["cx"] + b.get("w", 20) / 2 for b in row_blocks) + 15
        y0 = min(b["cy"] - b.get("h", 14) / 2 for b in row_blocks) - 8
        y1 = max(b["cy"] + b.get("h", 14) / 2 for b in row_blocks) + 8
        CROPS.mkdir(parents=True, exist_ok=True)
        out_png = CROPS / f"{sheet_slug}_{tag}.png"
        pix = page.get_pixmap(clip=pymupdf.Rect(x0, y0, x1, y1), matrix=pymupdf.Matrix(4, 4))
        pix.save(out_png)
        crops.append({"tag": tag, "png": str(out_png)})

    return {"found": True, "n_curve_rows": len(curve_results), "n_line_rows": len(line_results),
            "curve_self_check": curve_results, "fails": fails, "chord_note": chord_note,
            "tangency": tang, "crops": crops}


def tangency_check(sheet_snap, table_rows):
    p = sheet_snap / "tag_labels.json"
    tl = load_json(p)
    if not tl:
        return {"available": False}
    # endpoints of each tag's traced drawn polyline (topology only)
    ends = {}
    for e in tl:
        line = e.get("line") or []
        if len(line) < 2:
            continue
        ends[e["tag"]] = (np.array(line[0]), np.array(line[-1]))
    by_az = {e["tag"]: e["az"] for e in tl if e["kind"] == "line"}
    # topology only, informational: how many tag-to-tag endpoint adjacencies exist at all in the
    # traced subset (tag_labels.json only covers the tags a leader/beside association resolved, not
    # every L#/C#), split by kind-pair, before attempting the line-curve-line triple below
    adjacency = {"line-line": 0, "line-curve": 0, "curve-curve": 0}
    all_tags = list(ends)
    for i, t1 in enumerate(all_tags):
        for t2 in all_tags[i + 1:]:
            k1, k2 = next(e["kind"] for e in tl if e["tag"] == t1), next(e["kind"] for e in tl if e["tag"] == t2)
            for p1 in ends[t1]:
                for p2 in ends[t2]:
                    if np.hypot(*(p1 - p2)) < 5.0:
                        adjacency["line-curve" if k1 != k2 else f"{k1}-{k1}"] += 1
    checks_done, matches = [], 0
    curve_tags = [e["tag"] for e in tl if e["kind"] == "curve"]
    for ctag in curve_tags:
        if ctag not in ends or ctag not in table_rows or len(table_rows[ctag]["cells"]) != 3:
            continue
        c0, c1 = ends[ctag]
        neighbours = []
        for ltag, (l0, l1) in ends.items():
            if ltag not in by_az:
                continue
            for cend, cname in ((c0, "0"), (c1, "1")):
                for lend in (l0, l1):
                    if np.hypot(*(cend - lend)) < 3.0:
                        neighbours.append((cname, ltag))
        sides = {n[0]: n[1] for n in neighbours}
        if "0" in sides and "1" in sides and sides["0"] != sides["1"]:
            az0, az1 = by_az[sides["0"]], by_az[sides["1"]]
            delta_printed = dms_to_deg(table_rows[ctag]["cells"][1])
            turn = abs(((az1 - az0 + 180) % 360) - 180)
            ok = abs(turn - delta_printed) < (1 / 3600) * 50  # ~50" slack for two roundings + digitizing
            checks_done.append({"curve": ctag, "line_a": sides["0"], "line_b": sides["1"],
                                "turn_from_az_deg": round(turn, 4), "printed_delta_deg": round(delta_printed, 4),
                                "match_within_tol": ok})
            matches += ok
    return {"available": True, "n_tags_traced": len(ends), "adjacency": adjacency,
            "n_line_curve_line_joins_found": len(checks_done),
            "n_tangent_within_tol": matches, "detail": checks_done,
            "note": "info only, and only a direct line-curve-line join is checked (a curve bracketed by "
                    "two more curves -- a compound-curve chain or a corner where several pieces meet, both "
                    "common here per STATE.md/loop notes on curve stitching -- is not chained through); a "
                    "non-tangent join is legal record either way, not a fail"}


def run_sheet(snap_root, label, subdir, pdf_rel):
    sheet_snap = snap_root / subdir if subdir else snap_root
    pdf_path = ROOT / "Sample Data" / pdf_rel
    slug = subdir or "r_10434_002_2020-09-16"
    print(f"=== {label} ({slug}) ===")
    if not pdf_path.exists():
        print("  PDF missing:", pdf_path)
        return {"label": label, "error": f"pdf missing: {pdf_path}"}
    blocks, src = load_blocks(sheet_snap)
    page = pymupdf.open(pdf_path)[0]
    regions = alignment_table_regions(blocks)
    tables = load_json(sheet_snap / "tables.json")
    georef = load_json(sheet_snap / "georef.json")

    a = part_a(blocks, regions, page, georef, slug)
    table_boxes = [r["box"] for r in regions] + [tuple(r) for r in (tables or {}).get("_regions", [])]
    b = part_b(blocks, table_boxes, page, georef)
    c = part_c(tables, blocks, page, sheet_snap, slug)

    result = {"label": label, "snap_subdir": subdir, "read_source": src, "part_a": a, "part_b": b, "part_c": c}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}_record_checks.json").write_text(json.dumps(result, indent=1, default=float))
    return result


def summarize(results):
    lines = ["# record_checks.py summary", ""]
    for r in results:
        lines.append(f"## {r['label']}")
        if r.get("error"):
            lines.append(f"- ERROR: {r['error']}")
            lines.append("")
            continue
        a, b, c = r["part_a"], r["part_b"], r["part_c"]
        if not a["found"]:
            lines.append("- Part A: no ALIGNMENT DATA table (no STATION/NORTHING/EASTING header) on this sheet.")
        else:
            lines.append(f"- Part A: {a['rows_read']} alignment rows read.")
            if a.get("pairs"):
                clean = [p for p in a["pairs"] if not p["likely_misread"] and not p["different_alignment"]]
                misreads = [p for p in a["pairs"] if p["likely_misread"]]
                multi = [p for p in a["pairs"] if p["different_alignment"]]
                straight = [p for p in clean if not p["curve"]]
                curved = [p for p in clean if p["curve"]]
                if straight:
                    diffs = [abs(p["diff_ft"]) for p in straight]
                    lines.append(f"  - straight pairs ({len(straight)}): |chord - station diff| median {np.median(diffs):.2f} ft, max {max(diffs):.2f} ft")
                if curved:
                    diffs = [abs(p["diff_ft"]) for p in curved]
                    lines.append(f"  - curve-flagged pairs ({len(curved)}, chord vs arc expected to differ): median {np.median(diffs):.2f} ft, max {max(diffs):.2f} ft")
                nm = sum(1 for p in clean if p["non_monotonic"])
                if nm:
                    lines.append(f"  - {nm}/{len(clean)} row pairs are non-monotonic in station (table is not one single ascending traverse; expected where curves/points interleave)")
                if misreads:
                    lines.append(f"  - {len(misreads)} pair(s) with a huge chord but a plausible station step: OCR/SHX misread N or E digit, not a record fact -- crops rendered: {', '.join(sorted(set(t for p in misreads for t in (p['a'], p['b']))))}")
                if multi:
                    lines.append(f"  - {len(multi)} pair(s) with a huge station jump but a small, plausible chord: these rows sit on a DIFFERENT reference line/stationing than their table neighbour (two alignments sharing one coordinate table), not an error")
            if a.get("residuals"):
                clean = [x for x in a["residuals"] if not x["likely_misread"]]
                bad = [x for x in a["residuals"] if x["likely_misread"]]
                if clean:
                    res = [x["residual_ft"] for x in clean]
                    lines.append(f"  - vs georef fit -> nearest vertex: median {np.median(res):.2f} ft, max {max(res):.2f} ft over {len(res)} rows")
                if bad:
                    lines.append(f"  - {len(bad)} row(s) off by >1000 ft vs the fit: same misread rows as above, excluded from the stat")
            if a.get("alt_fit"):
                af = a["alt_fit"]
                lines.append(f"  - alt fit from alignment rows only ({af['n_points']} vertex-matched points): "
                              f"scale {af['scale_ft_per_pt']:.5f} ft/pt (callout fit {af['vs_callout_fit']['scale_diff']:+.5f} diff), "
                              f"rotation diff {af['vs_callout_fit']['rotation_diff_deg']:+.4f} deg, rms {af['rms_ft']:.2f} ft")
            elif a.get("residuals"):
                lines.append("  - alt fit: not enough rows landed within 5 ft of a drawn vertex to try one")
        if b.get("labels_found", 0) == 0:
            lines.append("- Part B: no drawn station labels found outside table regions.")
        else:
            lines.append(f"- Part B: {b['labels_found']} station labels on the drawing, {b['snapped_to_a_line']} within 15 pt of a drawn segment.")
            if b.get("pairs"):
                diffs = [abs(p["diff_ft"]) for p in b["pairs"]]
                lines.append(f"  - along-line distance (straight-line proxy) vs station diff, {len(b['pairs'])} consecutive pairs: median |diff| {np.median(diffs):.1f} ft, max {max(diffs):.1f} ft")
                lines.append(f"  - {b['note']}")
        if not c["found"]:
            lines.append("- Part C: no L#/C# line/curve table found on this sheet.")
        else:
            n_curve_fail = sum(1 for f in c["fails"] if f["check"] == "L=R*delta")
            n_row_fail = sum(1 for f in c["fails"] if f["check"] != "L=R*delta")
            lines.append(f"- Part C: {c['n_curve_rows']} curve rows (L=R*delta fails: {n_curve_fail}), {c['n_line_rows']} line rows (bad cell count: {n_row_fail}).")
            lines.append(f"  - chord check: {c['chord_note']}")
            t = c["tangency"]
            if t.get("available"):
                lines.append(f"  - tangency (info): {t['n_tags_traced']} tags have traced geometry; adjacent-endpoint pairs found {t['adjacency']}; "
                             f"{t['n_tangent_within_tol']}/{t['n_line_curve_line_joins_found']} direct line-curve-line joins match printed delta within tolerance")
            else:
                lines.append("  - tangency: tag_labels.json not on this sheet (no traced tag geometry) -> adjacency unavailable")
            if c["crops"]:
                lines.append(f"  - crops rendered for classification: {', '.join(x['tag'] for x in c['crops'])}")
        lines.append("")
    (OUT / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", required=True)
    args = ap.parse_args()
    snap_root = Path(args.snap)
    results = [run_sheet(snap_root, label, subdir, pdf_rel) for label, subdir, pdf_rel in SHEETS]
    summarize(results)


if __name__ == "__main__":
    main()
