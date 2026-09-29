"""Loop18 leg 3 (retry): "(T)" run totals as whole record courses.

JR ruling (2026-09-28): a "(T)" total counts for every drawn piece it spans when those pieces form ONE
straight line (or one arc) under one printed bearing (or R) and sum to the total within 0.5 ft.

Orchestrator correction (first attempt was wrong): a (T) total spans a whole COURSE between two real
vertices -- most of that course is very often ALREADY covered or simply undimensioned elsewhere, not
sitting in recon_ceiling's own "uncovered leftover" (c_T) pool near the label. Pooling only c_T runs
within a fixed radius of the token (the first attempt) missed exactly this: Presidio's 860.77'(T) spans
~860 ft from a printed callout coordinate to a real drawn corner, most of it already a clean record edge
under "Presidio main line 2" (N74d18'38"W); only a handful of small uncovered slivers near the token
itself were ever visible to the old method.

Method (per (T) token):
  1. Governing bearing/R: a plain (non-radial) bearing/R= in the SAME annotation block wins outright;
     failing that, EVERY non-radial bearing (or R=) printed anywhere on the sheet is tried in turn (not
     a fixed search radius around the token -- "search along the line", see chains_for_bearing below).
  2. For a candidate bearing az0: every ELEMENTARY segment on the sheet (recon's own post-contamination-
     removal boundary, covered AND uncovered -- NOT recon_ceiling's c_T-only pool) whose own az sits
     within LINE_TOL_DEG of az0 is a candidate piece. chains_for_bearing() links them into maximal
     chains by nearest-endpoint proximity (<= CHAIN_GAP_TOL_FT, a monument tick/label wipeout); a second
     pass, merge_families(), merges chains that sit on the exact SAME infinite line (perpendicular
     offset agrees within COURSE_PERP_TOL_FT) even across a much bigger gap -- a course is one straight
     line, not one physically-touching stroke, and two sub-totals of one long line (Presidio's own
     860.77'(T) then 241.32'(T)) sit tens to hundreds of feet apart with other record material between.
  3. The token must actually belong to this line: within COURSE_PERP_TOL_FT-ish of it (TOKEN_PERP_FT,
     looser -- a label sits off to the side) and not wildly past its drawn extent (TOKEN_PAD_FT).
  4. Vertices along the family: every chain's own two extreme drawn points, PLUS every printed
     coordinate (inverse.py's own callout_points/table_points -- an on-map coordinate callout or a
     COORDINATES/ALIGNMENT table row) that snaps onto the same line within COORD_SNAP_FT. Every PAIR of
     vertices is a candidate course; the one whose end-to-end straight distance (not a sum of fragment
     lengths -- gaps are part of the course) matches the printed total within SUM_TOL_FT is the span.
  5. Arc totals (own-block RADIAL bearing, or no line match) fall back to the original co-circular
     pooling over recon_ceiling's own c_T runs near the token (arc_cluster/test_arc) -- a full sheet-wide
     "walk the whole circle" rebuild was out of scope for this retry; every arc total on the 3 sheets
     with any (T) material still gets a real geometric test, just a narrower one than the line path.

Accept: ONE new traverse row spanning vertex A to vertex B, az/R = the governing value, ft = the PRINTED
total (the record value, same convention every other clean row uses); misfit_ft = the drawn-vs-printed
span gap (<= SUM_TOL_FT by construction). recon.load_rec_edges()/dedupe_segments() handle any overlap
with already-clean rows already covering part of this span -- this module never subtracts or edits them.

usage: python spike/t_total.py <presidio|r10434_1|r10434_3|r10741_1|r10741_2|r10741_3>   (report + crops)
       python spike/t_total.py --selftest
"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT  # noqa: E402
from checks import BEAR, DIST, TOKEN, RAD_TOK, azimuth, fmt_bearing  # noqa: E402
import recon  # noqa: E402
from recon import OUT_RECON  # noqa: E402
import recon_attrib  # noqa: E402
from recon_ceiling import (SHORT2STEM, STEM2SHORT, NEIGHBORS, PLAUSIBLE_FT, BEND_CONTAM_DEG,  # noqa: E402
                            build_runs, classify_run, token_candidates, note_candidates,
                            titleblock_box, in_box, load_neighbor_rec)
from traverse import fit_circle_lsq, COCURVE_CENTER_TOL_FT, COCURVE_RADIUS_TOL_FT  # noqa: E402
import inverse  # noqa: E402

LINE_TOL_DEG = 2.0            # deg mod 180: a segment's own az vs the governing printed bearing -- see
# traverse.COCURVE_* docstring-style precedent; every genuine straight run measured on these sheets
# sits under 0.3 deg, a real corner turns tens of degrees.
CORRIDOR_GAP_TOL_FT = 30.0    # ft: the FINAL accept/refuse continuity check (corridor_continuous) gets
# a wider allowance than CHAIN_GAP_TOL_FT below -- measured directly on Presidio's own 860.77'(T) (the
# orchestrator's worked example): the true printed endpoint sits behind one real, single interruption of
# 26.8 ft in the drawn line (no other drawn material anywhere near that stretch, not a discretization
# artifact -- a driveway apron or curb-return symbol most likely replaces the boundary stroke there for
# a stretch, same real-world cause as a label wipeout, just physically longer). 30 ft clears that one
# measured case with room to spare while staying two orders of magnitude under PLAUSIBLE_FT (250);
# SUM_TOL_FT's own 0.5 ft exactness (B is COMPUTED, never fitted) keeps a coincidental false accept rare
# even at this width.
CHAIN_GAP_TOL_FT = 15.0       # ft: bracketed endpoint gap two segments may still be "touching" over --
# a monument circle or a label wipeout interrupts the drawn stroke far short of this.
COURSE_PERP_TOL_FT = 3.0      # ft: two chains (or a segment and a chain) sit on the SAME infinite line
# when their perpendicular offset agrees within this -- same order as checks.py's own SAME (1.5 pt).
TOKEN_PERP_FT = 15.0          # ft: how far off a family's own line the (T) label itself may sit and
# still be considered "labeling this course" (a label is offset to the side of its line, not sitting
# exactly on it).
TOKEN_PAD_FT = 200.0          # ft: how far past a family's own drawn extent the token's t-projection
# may fall and still count -- a total's own label is not always drawn between its own two vertices.
COORD_SNAP_FT = 3.0           # ft: a printed coordinate counts as a vertex of a family's line when its
# own perpendicular offset from that line is within this.
VERTEX_PAD_FT = 80.0          # ft: how far past a family's own chain extents a snapped coordinate may
# sit and still be kept as one of ITS vertices (a corner's own drawn tick can sit well past the last
# elementary segment recon.py's own contamination trim kept).
SUM_TOL_FT = 0.5              # JR's own ruling
BEARING_SEARCH_TOL_DEG = 1.0  # legacy arc-path tolerance (see arc fallback below)
GOV_SEARCH_FT = 600.0         # legacy arc-path search radius (see arc fallback below)


def az_diff180(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


def line_unit(az0):
    r = math.radians(az0)
    u = np.array([math.sin(r), math.cos(r)])
    n = np.array([u[1], -u[0]])
    return u, n


def run_endpoints(P_f, Q_f, members):
    pts = np.vstack([P_f[members], Q_f[members]])
    d = np.hypot(*(pts[:, None, :] - pts[None, :, :]).transpose(2, 0, 1))
    a, b = np.unravel_index(np.argmax(d), d.shape)
    return pts[a], pts[b]


def block_tokens(block_text):
    """Every bearing (with its radial flag) and R= value literally inside ONE annotation's own text."""
    bearings, radii = [], []
    for tok in TOKEN.findall(block_text):
        m = BEAR.match(tok)
        if m:
            bearings.append((azimuth(tok), bool(m[6])))
    for m in RAD_TOK.finditer(block_text):
        radii.append(float(m[1].replace(",", "")))
    return bearings, radii


# --- sheet-wide bootstrap -----------------------------------------------------------------------------

def full_pool(sheet_name):
    """Everything a (T) total might need, computed once per sheet: the FULL post-contamination-removal
    elementary-segment boundary (covered and uncovered alike -- the fix this retry makes), every printed
    bearing/R/total token, and every printed coordinate (callout or table row) snapped near the drawn
    boundary. Also keeps recon_ceiling's own c_T pool (arc fallback only, see module docstring)."""
    short_key = STEM2SHORT.get(sheet_name)
    if short_key is None:
        return None
    recon.make_figure = lambda *a, **k: None
    recon.make_zoom_figure = lambda *a, **k: None
    result, internals = recon.run(sheet_name, return_internals=True)
    inv, ground, buffer_ft = internals["inv"], internals["ground"], internals["buffer_ft"]
    remaining = internals["remaining"]
    P = internals["P"][remaining]
    Q = internals["Q"][remaining]
    seg_len = internals["seg_len"][remaining]
    seg_az = internals["seg_az"][remaining]
    mid_f = internals["mid"][remaining]
    cov_f = internals["cov_mask_full"][remaining]
    dim_f = internals["dim_mask_full"][remaining]

    blocks = internals["blocks"]
    tok_cands = token_candidates(blocks, ground)
    total_tokens = [c for c in tok_cands if c["kind"] == "distance" and c["total"]]
    bearing_tokens = [c for c in tok_cands if c["kind"] == "bearing" and not c["radial"]]

    g = json.loads((OUT / "georef.json").read_text(encoding="utf-8"))
    coord_pts = inverse.callout_points(g, short_key) + inverse.table_points(blocks, short_key)
    inverse.snap_all(coord_pts, P, Q)
    coord_pts = [c for c in coord_pts if c["snap_ft"] <= 5.0]

    # arc fallback's own c_T pool (unchanged from the first attempt) -----------------------------------
    note_cands = note_candidates(blocks, ground)
    rows = recon_attrib.load_all_rows()
    rP, rQ, raz, ridx = recon_attrib.row_segments(rows)
    uncov_mask = dim_f & ~cov_f
    any_match, _ = recon.covered_mask(mid_f, seg_az, rP, rQ, raz, buffer_ft, recon.PARALLEL_TOL_DEG)
    notrav_mask = uncov_mask & ~any_match
    idx_pool = np.nonzero(notrav_mask)[0]
    runs = build_runs(idx_pool, P, Q, seg_len, seg_az)
    contam_pts_ground = (ground(np.array(recon_attrib.PRESIDIO_CONTAM_PT))
                          if sheet_name == "presidio" else np.zeros((0, 2)))
    contam_tol_ground = recon_attrib.PRESIDIO_CONTAM_TOL_PT * internals["scale"]
    tb_box = titleblock_box(blocks, ground)
    neighbor_recs = {nk: load_neighbor_rec(nk) for nk in NEIGHBORS.get(short_key, [])}
    c_t_runs = []
    for r in runs:
        if r["bend_deg"] >= BEND_CONTAM_DEG:
            continue
        if len(contam_pts_ground) and np.hypot(*(contam_pts_ground - r["mid"]).T).min() <= contam_tol_ground:
            continue
        cls, ev = classify_run(r, tok_cands, note_cands, neighbor_recs, buffer_ft)
        if cls == "d" and in_box(r["mid"], tb_box):
            continue
        if cls != "c_T":
            continue
        cands = [(math.hypot(c["gx"] - r["mid"][0], c["gy"] - r["mid"][1]), c) for c in total_tokens
                  if math.hypot(c["gx"] - r["mid"][0], c["gy"] - r["mid"][1]) <= PLAUSIBLE_FT]
        if not cands:
            continue
        _, tok = min(cands, key=lambda t: t[0])
        p0, p1 = run_endpoints(P, Q, r["members"])
        c_t_runs.append({**r, "token": tok, "p0": p0, "p1": p1})

    return {"internals": internals, "blocks": blocks, "ground": ground, "inv": inv,
            "P": P, "Q": Q, "seg_len": seg_len, "seg_az": seg_az, "covered": cov_f,
            "tok_cands": tok_cands, "total_tokens": total_tokens, "bearing_tokens": bearing_tokens,
            "coord_pts": coord_pts, "c_t_runs": c_t_runs, "short_key": short_key}


# --- line path: chain -> family -> vertices -> span ----------------------------------------------------

def chains_for_bearing(az0, P, Q, seg_az, az_tol=LINE_TOL_DEG, perp_tol=COURSE_PERP_TOL_FT,
                        gap_tol=CHAIN_GAP_TOL_FT):
    """Every maximal, physically-touching, collinear run of elementary segments at az0 -- the perp
    reference is each chain's OWN seed (a genuinely different parallel line at the same bearing, e.g.
    the two sides of a road, must never merge here); merge_families() below then unions chains that
    turn out to sit on the identical line even where they never physically touch."""
    diffs = np.abs((seg_az - az0 + 90) % 180 - 90)
    idx = list(np.nonzero(diffs <= az_tol)[0])
    remaining = idx
    chains = []
    while remaining:
        seed = remaining.pop(0)
        p0 = P[seed]
        _, n = line_unit(az0)

        def perp(pt):
            return abs(float((pt - p0) @ n))
        chain = [seed]
        ends = [P[seed], Q[seed]]
        changed = True
        while changed:
            changed = False
            for j, cand in enumerate(remaining):
                if perp(P[cand]) > perp_tol or perp(Q[cand]) > perp_tol:
                    continue
                for ei, end in enumerate(ends):
                    for cend, oend in ((P[cand], Q[cand]), (Q[cand], P[cand])):
                        if np.hypot(*(cend - end)) <= gap_tol:
                            chain.append(cand); ends[ei] = oend; remaining.pop(j); changed = True; break
                    if changed:
                        break
                if changed:
                    break
        chains.append(chain)
    return chains


def merge_families(chains, az0, P):
    """Union-find merge of chains sharing a perpendicular offset (same infinite line), any distance
    apart along it -- a course's own two sub-totals (Presidio's 860.77'(T) then, ~15 ft further on
    after a small jog that itself breaks the chain, 241.32'(T)) are two DIFFERENT families here on
    purpose (the jog is a real, if small, deflection) -- see module docstring."""
    _, n = line_unit(az0)
    reps = [P[c[0]] for c in chains]
    parent = list(range(len(chains)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i in range(len(chains)):
        for j in range(i + 1, len(chains)):
            if abs(float((reps[j] - reps[i]) @ n)) <= COURSE_PERP_TOL_FT:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
    fams = {}
    for i in range(len(chains)):
        fams.setdefault(find(i), []).append(chains[i])
    return list(fams.values())


def chain_extremes(chain, P, Q):
    idxs = np.array(chain)
    pts = np.vstack([P[idxs], Q[idxs]])
    d = np.hypot(*(pts[:, None, :] - pts[None, :, :]).transpose(2, 0, 1))
    a, b = np.unravel_index(np.argmax(d), d.shape)
    return pts[a], pts[b]


def family_vertices(family, az0, P, Q, coord_pts):
    u, n = line_unit(az0)
    pts = []
    for chain in family:
        e0, e1 = chain_extremes(chain, P, Q)
        pts.append(e0); pts.append(e1)
    ref = pts[0]
    ts = [float((p - ref) @ u) for p in pts]
    t_lo, t_hi = min(ts), max(ts)
    verts = [(t, p, "corner") for t, p in zip(ts, pts)]
    for cp in coord_pts:
        pt = np.array([cp["E"], cp["N"]])
        perp = float((pt - ref) @ n)
        if abs(perp) > COORD_SNAP_FT:
            continue
        t = float((pt - ref) @ u)
        if t_lo - VERTEX_PAD_FT <= t <= t_hi + VERTEX_PAD_FT:
            verts.append((t, pt, f"coord {cp['id']}"))
    verts.sort(key=lambda v: v[0])
    dedup = []
    for v in verts:
        if dedup and abs(v[0] - dedup[-1][0]) < 1.0:
            continue
        dedup.append(v)
    return dedup


def block_has_own_distance(block_text):
    """True when a bearing's own annotation ALSO prints its own distance ("N74d16'42"W|220.16'") --
    that bearing already governs ITS OWN paired course and is never a free-floating candidate for some
    OTHER, bare (T) total nearby (Presidio's own trap: two such paired bearings, 285.72 and 285.77 deg,
    sit within LINE_TOL_DEG of the real 285.689 deg "N74d18'38"W" -- itself printed ALONE, no distance
    of its own -- and their own corridors coincidentally also fit 860.77'(T) to within the same
    perpendicular tolerance over an 860 ft run; excluding paired bearings removes the false ambiguity)."""
    for t in TOKEN.findall(block_text):
        if DIST.match(t):
            return True
    return False


BEARING_LABEL_PERP_FT = 30.0   # ft: how far a candidate bearing's OWN printed position may sit off a
# family's line and still be considered "labeling THIS course" -- see find_line_spans: without this, a
# textually-similar bearing sitting on a totally unrelated, far-away line (Presidio's own trap: "N74d13'
# 41"W", 2600+ ft away and 286 ft off this corridor, happens to measure marginally closer to the drawn
# corridor's own average az than the REAL, correctly-positioned "N74d18'38"W") can out-rank the real one
# on az residual alone -- printed field bearings round to the nearest second and a real drafted vector is
# never bit-exact to its own printed value, so "closest numeric match" is not a safe tie-break by itself.
BEARING_LABEL_PAD_FT = 30.0    # ft: how far past a family's own drawn extent that position may fall


def bearing_candidates(tok, bearing_tokens):
    """Own-block bearing wins outright (returned alone, no position check needed); else every distinct
    printed bearing anywhere on the sheet that is NOT already paired with its own distance (see
    block_has_own_distance) -- returned WITH its own ground position so find_line_spans can additionally
    require it to actually sit near the specific corridor being tested (see BEARING_LABEL_PERP_FT)."""
    bs, _ = block_tokens(tok["block"])
    plain = [az for az, radial in bs if not radial]
    if plain:
        return [(plain[0], f"same annotation \"{tok['block']}\"", None)]
    seen, out = set(), []
    for bt in bearing_tokens:
        if block_has_own_distance(bt["block"]):
            continue
        key = round(bt["az"], 2)
        if key in seen:
            continue
        seen.add(key)
        out.append((bt["az"], f"printed \"{bt['text']}\" in \"{bt['block']}\"", (bt["gx"], bt["gy"])))
    return out


def corridor_continuous(A, B, P, Q, seg_len, seg_az=None, perp_tol=COURSE_PERP_TOL_FT, gap_tol=CORRIDOR_GAP_TOL_FT):
    """Same interval-union continuity test as inverse.corridor_test (a real bend or a genuine gap
    breaks the single merged interval before it spans [0, L]), but with THIS module's own, wider gap
    tolerance -- the orchestrator's own retry instructions ("allowing gaps up to ~15 ft, label wipeouts/
    ticks") -- rather than inverse.py's 10 ft (calibrated for a DIFFERENT, tighter job: two printed
    COORDINATES, not a bare total). Presidio's own 860.77'(T) has one real 13.35 ft gap right at its own
    printed distance's own endpoint (a label sits on the line there) -- under inverse.py's own 10 ft this
    total refuses; under the orchestrator's stated 15 ft it is exactly what "one straight course" means.
    seg_az, if given, also returns the length-weighted mean DRAWN az of the matched segments (used to
    pick between two printed bearings both close enough to pass, see find_line_spans/evaluate_token).
    -> (True, boundary_ft, mean_az_or_None) or (False, None, None)."""
    d = B - A
    L = float(np.hypot(*d))
    if L < 1.0 or len(P) == 0:
        return False, None, None
    u = d / L
    n = np.array([-u[1], u[0]])
    mid = (P + Q) / 2
    t = (mid - A) @ u
    perp = (mid - A) @ n
    sel = (t >= -gap_tol) & (t <= L + gap_tol) & (np.abs(perp) <= perp_tol)
    if not sel.any():
        return False, None, None
    tp = (P[sel] - A) @ u
    tq = (Q[sel] - A) @ u
    lo = np.minimum(tp, tq); hi = np.maximum(tp, tq)
    order = np.argsort(lo)
    lo, hi = lo[order], hi[order]
    merged = [[lo[0], hi[0]]]
    for lv, hv in zip(lo[1:], hi[1:]):
        if lv - merged[-1][1] <= gap_tol:
            merged[-1][1] = max(merged[-1][1], hv)
        else:
            merged.append([lv, hv])
    if len(merged) != 1:
        return False, None, None
    m_lo, m_hi = merged[0]
    if m_lo > gap_tol or m_hi < L - gap_tol:
        return False, None, None
    mean_az = None
    if seg_az is not None:
        w = seg_len[sel]
        if w.sum() > 0:
            # circular mean mod 180 (an elementary segment's own P->Q winding is arbitrary -- half the
            # matched segments can read ~285 deg, the other half their own reverse ~105 deg, for the
            # IDENTICAL physical line; a naive linear average of a mix lands ~195 deg away from either,
            # which is exactly why the first cut at this picked the wrong bearing every time).
            ang2 = np.radians(seg_az[sel] * 2)
            mean_az = (math.degrees(math.atan2(np.average(np.sin(ang2), weights=w),
                                                np.average(np.cos(ang2), weights=w))) / 2) % 180
    return True, float(seg_len[sel].sum()), mean_az


def find_line_spans(tok, full):
    """-> (list of {az0, source, v0, v1, span, geo} candidate accepted spans, n_families_reached).

    The FIRST retry required an existing drawn vertex/chain-break to sit at the printed total's own
    exact distance from a known point -- wrong: a real drafted stroke often runs on, unbroken, straight
    through a course boundary that has no visible tick at all (the record's own printed bearing+distance
    is the ONLY thing marking that corner -- verified on Presidio's own 860.77'(T): the true endpoint
    sits ~13 ft into an otherwise UNBROKEN ~27 ft stretch of drawn line, no chain boundary anywhere near
    it). So instead: for every KNOWN point on the candidate line (a printed coordinate, or the whole
    line's own two overall extremes) as anchor A, COMPUTE B = A +/- total_ft * u (the point the record
    itself implies), then hand (A, B) to inverse.corridor_test() -- the same continuous-drawn-material
    test inverse.py's own printed-coordinate courses already use -- to confirm the whole computed span
    is actually drawn, gaps no bigger than inverse.GAP_TOL_FT. No requirement that B itself coincide
    with any other detected vertex: the record, not the drawing, supplies the corner."""
    P, Q, seg_len, seg_az = full["P"], full["Q"], full["seg_len"], full["seg_az"]
    tok_pt = np.array([tok["gx"], tok["gy"]])
    out = []
    n_reached = 0
    for az0, source, label_pos in bearing_candidates(tok, full["bearing_tokens"]):
        chains = chains_for_bearing(az0, P, Q, seg_az)
        if not chains:
            continue
        for fam in merge_families(chains, az0, P):
            u, n = line_unit(az0)
            ref = P[fam[0][0]]
            perp = abs(float((tok_pt - ref) @ n))
            if perp > TOKEN_PERP_FT:
                continue
            all_idx = [i for c in fam for i in c]
            pts = np.vstack([P[all_idx], Q[all_idx]])
            ts = [float((p - ref) @ u) for p in pts]
            t_lo, t_hi = min(ts), max(ts)
            t_tok = float((tok_pt - ref) @ u)
            if not (t_lo - TOKEN_PAD_FT <= t_tok <= t_hi + TOKEN_PAD_FT):
                continue
            if label_pos is not None:
                # the CANDIDATE BEARING's own printed position must sit near THIS family's line, not just
                # somewhere within reach of the token -- see BEARING_LABEL_PERP_FT's own docstring.
                lp = np.array(label_pos)
                lperp = abs(float((lp - ref) @ n))
                lt = float((lp - ref) @ u)
                if lperp > BEARING_LABEL_PERP_FT or not (t_lo - BEARING_LABEL_PAD_FT <= lt <= t_hi + BEARING_LABEL_PAD_FT):
                    continue
            n_reached += 1
            anchors = [pts[int(np.argmin(ts))], pts[int(np.argmax(ts))]]  # the family's own two extremes
            for cp in full["coord_pts"]:
                cpt = np.array([cp["E"], cp["N"]])
                if abs(float((cpt - ref) @ n)) <= COORD_SNAP_FT:
                    anchors.append(cpt)
            for A in anchors:
                for direction in (1.0, -1.0):
                    B = A + direction * tok["ft"] * u
                    ok, boundary_ft, mean_az = corridor_continuous(A, B, P, Q, seg_len, seg_az)
                    if not ok:
                        continue
                    az_resid = az_diff180(az0, mean_az) if mean_az is not None else 99.0
                    out.append({"az0": az0, "source": source, "v0": (float((A - ref) @ u), A, "anchor"),
                                "v1": (float((B - ref) @ u), B, "record"), "span": float(np.hypot(*(B - A))),
                                "boundary_ft": boundary_ft, "az_resid": az_resid})
    # de-dupe near-identical accepts (several anchors/directions landing on the same physical span)
    uniq = {}
    for c in out:
        # az0 rounded the SAME way bearing_candidates() itself dedupes distinct printed bearings (2
        # decimal deg) -- rounding coarser here previously collapsed two genuinely different printed
        # bearings that happen to round alike (285.689 and 285.722 both "285.7" at 1 decimal) into one,
        # silently dropping the correct candidate whenever the wrong one was inserted first.
        key = (round(c["az0"], 2), round(min(c["v0"][0], c["v1"][0]), 0))
        if key not in uniq:
            uniq[key] = c
    return list(uniq.values()), n_reached


# --- arc fallback (unchanged from the first attempt, restricted to recon_ceiling's own c_T pool) -------

def cluster_by_az(pool, tol_deg):
    remaining = list(pool)
    clusters = []
    while remaining:
        seed = remaining.pop(0)
        cluster = [seed]
        changed = True
        while changed:
            changed = False
            for j, cand in enumerate(remaining):
                if az_diff180(cand["az"], cluster[0]["az"]) <= tol_deg:
                    cluster.append(cand); remaining.pop(j); changed = True; break
        clusters.append(cluster)
    return clusters


def arc_cluster(pool):
    if len(pool) < 2:
        return []
    pts = np.vstack([np.vstack([r["p0"], r["p1"]]) for r in pool])
    if len(pts) < 3:
        return []
    try:
        c, r = fit_circle_lsq(pts)
    except Exception:
        return []
    return [r_ for r_ in pool if max(abs(np.hypot(*(r_["p0"] - c)) - r), abs(np.hypot(*(r_["p1"] - c)) - r))
            <= COCURVE_CENTER_TOL_FT]


def test_arc(runs, R0):
    pts = np.vstack([np.vstack([r["p0"], r["p1"]]) for r in runs])
    if len(pts) < 3:
        return [], runs, None
    try:
        c, r_fit = fit_circle_lsq(pts)
    except Exception:
        return [], runs, None
    ok, bad = [], []
    for r in runs:
        d0 = abs(np.hypot(*(r["p0"] - c)) - r_fit)
        d1 = abs(np.hypot(*(r["p1"] - c)) - r_fit)
        (ok if max(d0, d1) <= COCURVE_CENTER_TOL_FT else bad).append(r)
    if abs(r_fit - R0) > COCURVE_RADIUS_TOL_FT:
        return [], runs, r_fit
    return ok, bad, r_fit


def arc_governing(tok, blocks, ground):
    bs, rs = block_tokens(tok["block"])
    radial = [az for az, r_flag in bs if r_flag]
    if radial and rs:
        return rs[0], f"same annotation \"{tok['block']}\" (radial bearing + R=)"
    cx, cy = tok["gx"], tok["gy"]
    cands = []
    for b in blocks:
        if b["text"] == tok["block"]:
            continue
        gp = ground(np.array([[b["cx"], b["cy"]]]))[0]
        if math.hypot(gp[0] - cx, gp[1] - cy) > GOV_SEARCH_FT:
            continue
        _, rs2 = block_tokens(b["text"])
        for R in rs2:
            cands.append((R, b["text"]))
    cands = list({(round(R, 2), t) for R, t in cands})
    if len(cands) == 1:
        return cands[0][0], f"nearby \"{cands[0][1]}\""
    if len(cands) > 1:
        return None, f"ambiguous span: {len(cands)} nearby R= candidates"
    return None, "no governing bearing: nothing printed nearby matches"


def try_arc(tok, full):
    pool = [r for r in full["c_t_runs"] if r["token"] is tok or
            (r["token"]["text"] == tok["text"] and r["token"]["gx"] == tok["gx"] and r["token"]["gy"] == tok["gy"])]
    if not pool:
        return {"verdict": "refused", "reason": "no governing bearing: nothing printed nearby matches", "kind": None}
    R0, source = arc_governing(tok, full["blocks"], full["ground"])
    if R0 is None:
        return {"verdict": "refused", "reason": source, "kind": None}
    ac = arc_cluster(pool)
    if not ac:
        return {"verdict": "refused", "reason": f"no single circle fits any nearby piece for printed R={R0:.2f}'",
                "kind": "arc", "governing": R0, "source": source}
    ok, bad, r_fit = test_arc(ac, R0)
    if not ok:
        reason = (f"no single circle fits within tolerance of printed R={R0:.2f}'" if r_fit is None else
                  f"fitted radius {r_fit:.2f}' vs printed R={R0:.2f}' off by {abs(r_fit-R0):.2f}'")
        return {"verdict": "refused", "reason": reason, "kind": "arc", "governing": R0, "source": source}
    piece_sum = sum(r["ft"] for r in ok)
    diff = piece_sum - tok["ft"]
    if abs(diff) > SUM_TOL_FT:
        return {"verdict": "refused",
                "reason": f"sum mismatch: {len(ok)} co-circular piece(s) sum {piece_sum:.2f}' vs "
                           f"printed {tok['ft']:.2f}' (diff {diff:+.2f}')",
                "kind": "arc", "governing": R0, "source": source, "sum": piece_sum}
    return {"verdict": "accepted", "kind": "arc", "governing": R0, "source": source,
            "pieces": ok, "sum": piece_sum, "diff": diff, "R_fit": r_fit}


# --- per-token evaluation --------------------------------------------------------------------------

def evaluate_token(tok, full):
    bs, _ = block_tokens(tok["block"])
    own_radial = any(radial for _, radial in bs)
    if not own_radial:
        spans, n_family = find_line_spans(tok, full)
        if len(spans) == 1:
            s = spans[0]
            return {"verdict": "accepted", "kind": "line", "governing": s["az0"], "source": s["source"],
                    "v0": s["v0"], "v1": s["v1"], "sum": s["span"], "diff": s["span"] - tok["ft"]}
        if len(spans) > 1:
            by_az = {}
            for s in spans:
                by_az.setdefault(round(s["az0"], 2), s)
            if len(by_az) == 1:
                s = spans[0]
                return {"verdict": "accepted", "kind": "line", "governing": s["az0"], "source": s["source"],
                        "v0": s["v0"], "v1": s["v1"], "sum": s["span"], "diff": s["span"] - tok["ft"]}
            # More than one DISTINCT printed bearing produced a valid corridor of the exact right length
            # (Presidio's own trap: two other bare bearings sit within LINE_TOL_DEG of the true one over
            # an 860 ft run) -- pick whichever bearing's OWN value is actually closest to the drawn
            # material's own measured az (az_resid, from corridor_continuous), not just "within tolerance"
            # -- and only if it has a clear margin over the next-best (real printed bearings measured this
            # close together differ by hundredths of a degree in residual, never thousandths).
            ranked = sorted(by_az.values(), key=lambda s: s["az_resid"])
            best, second = ranked[0], ranked[1]
            if best["az_resid"] <= 0.05 and second["az_resid"] - best["az_resid"] >= 0.02:
                s = best
                return {"verdict": "accepted", "kind": "line", "governing": s["az0"], "source": s["source"],
                        "v0": s["v0"], "v1": s["v1"], "sum": s["span"], "diff": s["span"] - tok["ft"],
                        "note": f"{len(by_az)} bearings fit the corridor length; picked by closest az "
                                 f"residual ({best['az_resid']:.4f} vs next {second['az_resid']:.4f} deg)"}
            return {"verdict": "refused",
                    "reason": f"ambiguous span: {len(spans)} different vertex pairs (over {len(by_az)} "
                               f"distinct bearings/spans) all match {tok['ft']:.2f}' within {SUM_TOL_FT}', "
                               f"no clear best az residual ({best['az_resid']:.4f} vs {second['az_resid']:.4f} deg)",
                    "kind": "line"}
        if n_family:
            return {"verdict": "refused",
                    "reason": f"sum mismatch: {n_family} candidate line(s) pass near this total but no "
                               f"vertex pair spans {tok['ft']:.2f}' within {SUM_TOL_FT}'",
                    "kind": "line"}
    # arc fallback (own-block radial bearing, or no line family reached the token at all)
    return try_arc(tok, full)


def as_traverse_row(tok, verdict):
    if verdict["kind"] == "line":
        v0, v1 = verdict["v0"], verdict["v1"]
        p0, p1 = v0[1], v1[1]
        az = verdict["governing"]
        misfit = round(abs(verdict["sum"] - tok["ft"]) if "sum" in verdict else abs(verdict["diff"]), 2)
        name = f"T-total {tok['text']}: {fmt_bearing(az)} {tok['ft']:.2f}' ({v0[2]} -> {v1[2]})"
        row = {"edge": name, "kind": "line", "az": az, "ft": round(tok["ft"], 2),
               "misfit_ft": misfit, "chain_misfit_ft": misfit, "flags": [],
               "E": round(float(p1[0]), 2), "N": round(float(p1[1]), 2),
               "pts": [[round(float(p0[0]), 2), round(float(p0[1]), 2)],
                       [round(float(p1[0]), 2), round(float(p1[1]), 2)]],
               "source": f"by (T) total {tok['text']}"}
    else:
        pieces = verdict["pieces"]
        p0, p1 = pieces[0]["p0"], pieces[-1]["p1"]
        az = float(recon.azimuth_arr((p1 - p0)[None, :])[0])
        misfit = round(abs(verdict["diff"]), 2)
        name = f"T-total {tok['text']}: R={verdict['governing']:.2f}' {tok['ft']:.2f}'"
        row = {"edge": name, "kind": "line", "az": az, "ft": round(tok["ft"], 2),
               "misfit_ft": misfit, "chain_misfit_ft": misfit, "flags": [],
               "E": round(float(p1[0]), 2), "N": round(float(p1[1]), 2),
               "pts": [[round(float(p0[0]), 2), round(float(p0[1]), 2)],
                       [round(float(p1[0]), 2), round(float(p1[1]), 2)]],
               "source": f"by (T) total {tok['text']}"}
    return {"closed": False, "n_edges": 1, "full_record": 1, "misfit_max_ft": misfit, "misfit_end_ft": misfit,
            "edges": [row]}


def render_crops(sheet_name, page, inv, results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    W, H = page.rect.width, page.rect.height
    px = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(px.samples, dtype=np.uint8).reshape(px.height, px.width)
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    n_ref = 0
    for tok, res in results:
        if res["verdict"] == "accepted":
            pass
        elif res["verdict"] == "refused":
            n_ref += 1
            if n_ref > 3:
                continue
        else:
            continue
        if res.get("kind") == "line" and "v0" in res:
            pts = np.vstack([res["v0"][1], res["v1"][1]])
        elif res.get("pieces"):
            pts = np.vstack([np.vstack([r["p0"], r["p1"]]) for r in res["pieces"]])
        else:
            pts = np.array([[tok["gx"], tok["gy"]]])
        pg = inv(pts)
        cx, cy = pg.mean(0)
        span = max(float(np.hypot(*(pg.max(0) - pg.min(0)))), 40) * 0.6
        x0, x1 = max(0, cx - span), min(W, cx + span)
        y0, y1 = max(0, cy - span), min(H, cy + span)
        fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
        ax.imshow(img, cmap="gray", extent=(0, W, H, 0))
        color = "#2ca02c" if res["verdict"] == "accepted" else "#e03030"
        seg = inv(pts)
        ax.plot(seg[:, 0], seg[:, 1], color=color, lw=2.2, marker="o", ms=4)
        ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_aspect("equal")
        ax.set_title(f"{sheet_name}: {tok['text']} ({res['verdict']})", fontsize=8)
        ax.axis("off")
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", tok["text"])
        fig.savefig(OUT_RECON / f"l18_3b_{sheet_name}_{safe}.png")
        plt.close(fig)


def analyze(sheet_name):
    full = full_pool(sheet_name)
    if full is None:
        return [], None
    results = [(tok, evaluate_token(tok, full)) for tok in full["total_tokens"]]
    return results, full


def add_t_total_chains(sheet_name):
    """Called from traverse.py's own main(), right after inverse.add_inverse_chains()."""
    short_key = STEM2SHORT.get(sheet_name)
    if short_key is None:
        return []
    results, full = analyze(sheet_name)
    accepted = [(t, r) for t, r in results if r["verdict"] == "accepted"]
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    dumped = [{"token": t["text"], "verdict": r["verdict"], "kind": r.get("kind"),
               "governing": r.get("governing"), "reason": r.get("reason"),
               "sum_ft": r.get("sum"), "diff_ft": r.get("diff")} for t, r in results]
    (OUT_RECON / f"l18_3_{short_key}.json").write_text(json.dumps(dumped, indent=1, ensure_ascii=False), encoding="utf-8")
    if results:
        render_crops(short_key, full["internals"]["page"], full["inv"], results)
    print(f"(T) totals ({short_key}): {len(accepted)} accepted, "
          f"{sum(1 for _, r in results if r['verdict'] == 'refused')} refused, of {len(results)} tokens")
    return [as_traverse_row(t, r) for t, r in accepted]


def report(key):
    sheet_name = SHORT2STEM[key]
    import os
    if key != "presidio":
        os.environ["SHEET"] = str(next((Path(__file__).parent.parent / "Sample Data" / "d4").glob(f"{sheet_name}.pdf")))
    else:
        os.environ.pop("SHEET", None)
    import importlib
    import georef as _g
    importlib.reload(_g)
    importlib.reload(recon)
    results, full = analyze(sheet_name)
    for tok, r in results:
        extra = ""
        if r["verdict"] == "accepted":
            extra = f" [{r['kind']} {r['governing']}] {tok['ft']:.2f}' ({r['v0'][2]} -> {r['v1'][2]})" if r["kind"] == "line" \
                else f" [{r['kind']} R={r['governing']:.2f}'] {tok['ft']:.2f}'"
        print(f"{key}: {tok['text']} -> {r['verdict']}{extra}" + (f" -- {r['reason']}" if r.get("reason") else ""))
    return results


def selftest():
    """One: a total whose true span crosses a gap bigger than CHAIN_GAP_TOL_FT (so chains_for_bearing
    never physically bridges it -- two separate chains) still accepts, because merge_families() puts
    both chains in the same line FAMILY and the span is measured end to end across the whole family, gap
    included -- this is the exact bug the orchestrator's retry flagged (Presidio's 860.77'(T): most of
    its own course sits far from the token, joined only by "same line", never by physical touching).
    One: a total whose own annotation prints a plain bearing but whose drawn material never reaches
    anywhere near the printed value is refused, not guessed (the line+curve trap)."""
    az0 = 0.0
    # two chains on the SAME line (x=0, due north), 200 ft apart (past CHAIN_GAP_TOL_FT=15) -- chains_
    # for_bearing must keep them separate; merge_families must still join them (same perpendicular offset).
    P = np.array([[0.0, 0.0], [0.0, 250.0]])
    Q = np.array([[0.0, 50.0], [0.0, 300.0]])
    seg_az = np.array([0.0, 0.0])
    chains = chains_for_bearing(az0, P, Q, seg_az)
    assert len(chains) == 2, f"a 200 ft gap must NOT physically bridge into one chain: {chains}"
    fams = merge_families(chains, az0, P)
    assert len(fams) == 1, "two chains on the identical line must merge into one family regardless of gap"
    verts = family_vertices(fams[0], az0, P, Q, [])
    span = abs(verts[-1][0] - verts[0][0])
    assert abs(span - 300.0) <= SUM_TOL_FT, f"end-to-end span must be 300.00 ft (gap included): got {span}"

    # find_line_spans itself: a SMALL (5 ft, under inverse.corridor_test's own 10 ft gap tolerance) break
    # so the drawn material is genuinely continuous end to end -- computes B = A + total_ft*u from a
    # known anchor (here a "printed coordinate" standing in for CO4) and confirms the corridor, exactly
    # Presidio's 860.77'(T) case (the true endpoint sits mid-stroke, no vertex of its own at all).
    P2 = np.array([[0.0, 0.0], [0.0, 145.0]])
    Q2 = np.array([[0.0, 140.0], [0.0, 300.0]])
    seg_len2 = np.hypot(*(Q2 - P2).T)
    seg_az2 = np.array([0.0, 0.0])
    covered2 = np.zeros(2, bool)
    tok = {"text": "300.00'(T)", "block": "N0°00'00\"E|300.00'(T)", "ft": 300.00, "gx": 0.0, "gy": 150.0, "total": True}
    coord = [{"E": 0.0, "N": 0.0, "id": "CO-test", "snap_ft": 0.0}]
    full = {"P": P2, "Q": Q2, "seg_len": seg_len2, "seg_az": seg_az2, "covered": covered2,
            "bearing_tokens": [], "coord_pts": coord}
    spans, n_reached = find_line_spans(tok, full)
    assert n_reached >= 1 and len(spans) >= 1 and abs(spans[0]["span"] - 300.0) <= SUM_TOL_FT, (spans, n_reached)

    # mixed line+curve: a total whose own annotation prints a plain bearing, but the token itself sits
    # nowhere near this line's own drawn extent (a curve elsewhere, not a continuation of the line) --
    # no family even reaches it, refused, not guessed.
    tok2 = {"text": "235.42'(T)", "block": "N0°00'00\"E|235.42'(T)", "ft": 235.42, "gx": 0.0, "gy": 5000.0,
            "total": True}
    spans2, n_reached2 = find_line_spans(tok2, full)
    assert len(spans2) == 0 and n_reached2 == 0, (spans2, n_reached2)

    print("t_total.selftest OK: find_line_spans computes the record endpoint and confirms it by drawn-"
          "material continuity (no pre-existing vertex required, the retry's fix); "
          "a total whose token sits off this line's own extent refuses")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif len(sys.argv) > 1 and sys.argv[1] in SHORT2STEM:
        report(sys.argv[1])
    else:
        raise SystemExit(__doc__)
