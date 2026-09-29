"""Loop19 leg 1: coordinate-anchored rebuild -- walk the RECORD between printed coordinates, the way a
surveyor closes a traverse. See spike/LOOP.md "Loop 18"/"Loop 19", docs/tickets/T-001-record-first-
traverse.md, spike/inverse.py (anchor inventory), spike/traverse.py (edges/record numbers), spike/recon.py
(the "reconstructed edge" definition this leg's course graph reuses).

Anchors (leg 1): every printed coordinate on the boundary -- inverse.py's own inventory
(callout_points() + table_points()), snapped within inverse.SNAP_FT of the FULL drawn boundary (loop19
leg 0's own fix: recon_segments.json's post-removal set can genuinely be missing a stretch a real vertex
sits on -- see corridor_test()'s own docstring). A point's own snapped/drawn position is used only to
place it on the graph; every misclosure below is measured against its PRINTED coordinate.

Course graph (leg 2): nodes = drawn boundary vertices (every reconstructed edge's own drawn endpoint,
clustered within NODE_FT); edges = recon.load_rec_edges(traverse.json)'s own reconstructed-edge set
(kind in line/arc, flags == [], misfit_ft <= 0.5 -- recon.py's own definition, which already covers
clean line rows, clean arc rows, (T)-total rows and inverse rows alike: loop18 built all four flag-free
once fully record-backed). The drawing decides which course follows which (a shared node) -- never a
value; every course's own bearing/distance (or chord az + 2R sin(delta/2)) already came from
traverse.py's own record-first resolution (traverse.walk()), reused verbatim here, never re-derived.

Record walk (leg 3): from each anchor, in each direction its node offers, walk courses end to end --
single unambiguous continuation only, the same rule traverse.py's own chain-builder uses (a branch, same
as a dead end, stops the walk). Each corner comes from the record alone (apply_record()): a line steps by
its own bearing+distance, an arc by its own chord az + 2R sin(delta/2) (both already resolved into
az/ft, never re-derived from R/delta directly -- traverse.py's own record_vector_misfit() judges a curve
edge exactly the same way). Reaching a node within ARRIVE_FT of a DIFFERENT anchor ends the walk:
misclosure = |walked position - that anchor's own PRINTED coordinate|; <= CLOSURE_MAX_FT (recon.py's own
face-closure threshold, reused) is a CLOSED anchored chain, otherwise FAILED (its own worst-misfit course
flagged as most likely at fault). Running out of an unambiguous next course (branch or dead end) leaves
it OPEN.

Output (leg 4): spike/out_recon/anchored_<sheet>.json + spike/out_recon/anchored.md (closed/failed/open
per sheet, ft, misclosures) + spike/out_recon/l19_1_<sheet>_<chain>.png crops (the 3 longest closed
chains and every failed one) via render_crop(). MEASURES only -- recon.py's own counting is untouched;
loop19 leg 2 scores anchored chains as their own column.

Leg 2 (branch resolution + scoring):
- recon_anchored: boundary ft covered by a reconstructed edge whose own name belongs to a CLOSED
  anchored chain -- a stronger claim than recon_all (every clean record edge), same denominator
  (recon.py's own `remaining`, post contamination-removal). anchored_coverage() re-runs
  recon.covered_mask() (recon.py's own run() discards the per-segment matched-edge index; this leg
  needs it to test chain membership) and patches recon_segments.json with an "anchored" bool column
  so recon_set.py can dedupe/pool it across sheets exactly like covered/dimensioned.
- Branches: walk_one() used to stop ("open", reason "branch") the instant a node offered more than one
  unused clean course. Now it tries EACH candidate via a bounded recursive search (_dfs(),
  BRANCH_MAX_DEPTH nested branch decisions, BRANCH_MAX_PATHS total path-explorations, shared across one
  resolution): exactly one candidate path reaching a closed chain resolves the branch (the closure IS
  the proof); more than one closing leaves it open ("ambiguous"); none closing leaves it open, same as
  before, with a fuller reason.
- Solvable-by-closure (unchecked): an OPEN chain (still "ran out of record courses" after branch
  resolution) that stops one course short of a half-recorded traverse row (record gave a bearing XOR a
  distance, never both -- traverse.py's own "bearing from drawing"/"distance from drawing" flags) whose
  OTHER element, completed from the two printed anchors' own coordinates, closes within tolerance:
  reported (value, course, vs. the drawing) in anchored.md, never scored -- a single half-recorded
  course carries zero redundancy, no independent check confirms it.
- Anchored parcels: a named (AREAS-table) face whose WHOLE ring sits on reconstructed edges that are
  ALL members of a closed anchored chain, vs. its own record area (areas_table.py).

usage: python spike/anchored.py <presidio|r10434_1|r10434_3>   (SHEET env already set for this process
                                                                  for r10434_1/r10434_3 -- see --all)
       python spike/anchored.py --all       (drives all three sheets, one subprocess each, like bench.py)
       python spike/anchored.py --selftest
"""
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
import recon  # noqa: E402
import inverse  # noqa: E402
from recon import OUT_RECON  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
SHEET_PDF = {
    "presidio": None,
    "r10434_1": ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf",
    "r10434_3": ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf",
}

NODE_FT = 2.0        # course-graph vertex clustering, ground ft -- recon.py's own BUFFER_FT (~2 ft),
# the "on the same point/line" tolerance this whole project already uses, reused here for "same drawn
# vertex" rather than fit fresh per sheet.
ARRIVE_FT = 0.5      # JR's own number: "reaches a node within 0.5 ft of another anchor's position"
CLOSURE_MAX_FT = 1.0  # closed vs failed -- recon.py's own CLOSURE_MAX_FT (face closure), reused: this
# is the SAME kind of check (does the record close where it should), just anchored on a printed
# coordinate instead of a ring's own start point.
MAX_COURSES = 400    # loop-guard: no real chain on these sheets runs anywhere near this many courses
BRANCH_MAX_DEPTH = 6   # leg 2: bounded nested branch decisions one resolution may explore -- no real
                        # chain on these sheets needs anywhere near this many branch points
BRANCH_MAX_PATHS = 200  # leg 2: bounded total recursive path-explorations, shared across every nested
                        # branch inside ONE resolution -- headroom over the 2-4 candidates any node here
                        # actually offers
BEARING_TOL_DEG = 1.0   # leg 2, solvable-by-closure only: how far a half-recorded row's own RECORD
                        # bearing may sit from the bearing closure needs and still count as "this course
                        # reaches that anchor" -- closed chains measured 0.007-0.011 ft misclosure over
                        # hundreds of ft, so a real match sits far under this
AGREE_FT_TOL = 0.1      # leg 3: two independent anchor pairs' own computed DISTANCE fill must agree
                        # within this to accept without a third-anchor continuation (JR's own number)
AGREE_DEG_TOL = 0.01    # leg 3: same, for a computed BEARING/chord-direction fill (JR's own number)


# --- anchors (leg 1) -----------------------------------------------------------------------------------

def load_anchors(sheet_name, key):
    import pymupdf
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text(encoding="utf-8"))
    blocks = inverse.load_blocks(page)
    _, internals = recon.run(sheet_name, return_internals=True, make_figures=False)
    P, Q = internals["P"], internals["Q"]
    pts = inverse.callout_points(g, key) + inverse.table_points(blocks, key)
    inverse.snap_all(pts, P, Q)
    anchors = []
    for p in pts:
        if p["snap_ft"] > inverse.SNAP_FT:
            continue
        anchors.append({"id": p["id"], "E": p["E"], "N": p["N"], "pt": np.array([p["E"], p["N"]], float),
                         "source": p["source"], "snap_ft": p["snap_ft"]})
    return anchors, g, internals


# --- course graph (leg 2) -------------------------------------------------------------------------------

def build_graph(rec_edges, node_tol=NODE_FT):
    """nodes = clustered drawn endpoints of every reconstructed edge; edges = rec_edges themselves,
    each tagged with its own n0/n1 (mutated in place).

    recon.load_rec_edges()'s own "az" is only the direction of whichever chain traverse.py's own walk
    happened to build it FROM (p0/p1 come from build_edges()'s fixed, as-digitized "pts", never
    reordered for that walk's own fwd) -- it can just as easily describe e["q"]->e["p"] as e["p"]->
    e["q"]. recon.face_closure() resolves this exact ambiguity per ring piece by picking whichever of
    az/az+180 agrees with THAT piece's own drawn direction; here every edge has one fixed p/q, so it is
    resolved once, the same way, into "the record az from p to q" -- apply_record()'s own fwd/+180
    logic is only correct once this has run."""
    if not rec_edges:
        return {}, {}
    for e in rec_edges:
        drawn_az = float(recon.azimuth_arr((e["q"] - e["p"])[None, :])[0])
        if abs((e["az"] - drawn_az + 180) % 360 - 180) >= 90:
            e["az"] = (e["az"] + 180) % 360
    pts = np.array([pt for e in rec_edges for pt in (e["p"], e["q"])])
    tree = cKDTree(pts)
    node_of = {}
    for i in range(len(pts)):
        if i in node_of:
            continue
        for j in tree.query_ball_point(pts[i], node_tol):
            node_of.setdefault(int(j), i)
    groups = {}
    for i, n in node_of.items():
        groups.setdefault(n, []).append(i)
    node_pos = {n: pts[idx].mean(axis=0) for n, idx in groups.items()}
    adj = {}
    for k, e in enumerate(rec_edges):
        n0, n1 = node_of[2 * k], node_of[2 * k + 1]
        e["n0"], e["n1"] = n0, n1
        adj.setdefault(n0, []).append(k)
        adj.setdefault(n1, []).append(k)
    return adj, node_pos


def nearest_node(node_pos, pt, tol):
    best_n, best_d = None, None
    for n, p in node_pos.items():
        d = float(np.hypot(*(p - pt)))
        if best_d is None or d < best_d:
            best_n, best_d = n, d
    if best_d is not None and best_d <= tol:
        return best_n, best_d
    return None, best_d


# --- record walk (leg 3) --------------------------------------------------------------------------------

def apply_record(pos, e, fwd):
    """Next corner from the record alone: e["az"]/e["ft"] are ALREADY the record's own chord/line
    az+distance (traverse.walk()'s own resolution -- a line's bearing+distance, or an arc's chord az +
    2R sin(delta/2)), reversed 180 deg when walked back-to-front."""
    az = e["az"] if fwd else (e["az"] + 180) % 360
    rad = math.radians(az)
    return pos + np.array([e["ft"] * math.sin(rad), e["ft"] * math.cos(rad)])


def _course_of(e):
    return {"name": e["name"], "kind": e["kind"], "ft": e["ft"], "misfit_ft": e["misfit_ft"]}


def _open(start_id, courses, reason):
    return {"start": start_id, "end": None, "status": "open", "reason": reason, "misclosure_ft": None,
            "length_ft": round(sum(c["ft"] for c in courses), 2), "n_courses": len(courses), "courses": courses}


def _finish_at_anchor(start_id, other, pos, courses):
    misclosure = float(np.hypot(*(pos - other["pt"])))
    status = "closed" if misclosure <= CLOSURE_MAX_FT else "failed"
    worst = max(courses, key=lambda c: c["misfit_ft"])
    return {"start": start_id, "end": other["id"], "status": status,
            "misclosure_ft": round(misclosure, 3), "length_ft": round(sum(c["ft"] for c in courses), 2),
            "n_courses": len(courses), "courses": courses,
            "worst_course": worst["name"], "worst_misfit_ft": worst["misfit_ft"]}


def _dfs(pos, n, used, courses, rec_edges, adj, node_anchors, anchors_by_id, start_id, depth_left, budget):
    """leg 2: unlike the old walk_one loop, a real branch (>1 unused candidate) does not stop the walk --
    it recurses into EVERY candidate (budget permitting) and collects every terminal reached (closed/
    failed/open dead-end/open depth-or-budget-exceeded). An unambiguous single-candidate step costs no
    depth (only an actual branch DECISION does) and is walked in a loop, same as the old code, so a long
    clean run between two branches never burns the depth budget. Returns a list of terminal result dicts,
    each carrying the FULL course list from start_id (pre-branch courses + whatever this path added)."""
    if len(courses) > MAX_COURSES:
        return [_open(start_id, courses, "loop-guard")]
    hits = [aid for aid in node_anchors.get(n, []) if aid != start_id]
    if hits:
        return [_finish_at_anchor(start_id, anchors_by_id[hits[0]], pos, courses)]
    cands = [j for j in adj.get(n, []) if j not in used]
    while len(cands) == 1:
        k = cands[0]
        e = rec_edges[k]
        fwd = e["n0"] == n
        pos = apply_record(pos, e, fwd)
        used = used | {k}
        courses = courses + [_course_of(e)]
        n = e["n1"] if fwd else e["n0"]
        if len(courses) > MAX_COURSES:
            return [_open(start_id, courses, "loop-guard")]
        hits = [aid for aid in node_anchors.get(n, []) if aid != start_id]
        if hits:
            return [_finish_at_anchor(start_id, anchors_by_id[hits[0]], pos, courses)]
        cands = [j for j in adj.get(n, []) if j not in used]
    if not cands:
        return [_open(start_id, courses, "ran out of record courses")]
    if depth_left <= 0 or budget[0] <= 0:
        return [_open(start_id, courses, f"branch (unresolved: depth/budget limit, {len(cands)} candidates)")]
    results = []
    for k in cands:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        e = rec_edges[k]
        fwd = e["n0"] == n
        pos2 = apply_record(pos, e, fwd)
        n2 = e["n1"] if fwd else e["n0"]
        results.extend(_dfs(pos2, n2, used | {k}, courses + [_course_of(e)], rec_edges, adj, node_anchors,
                             anchors_by_id, start_id, depth_left - 1, budget))
    return results


def resolve_branch(pos, n, used, courses, cands, rec_edges, adj, node_anchors, anchors_by_id, start_id):
    """leg 2: exactly one candidate's own subtree closing IS the proof (JR's own rule); more than one
    closing is ambiguous (both explanations fit the record equally, so neither is picked); zero closing
    leaves it open, same as before, just with the fuller reason attached."""
    budget = [BRANCH_MAX_PATHS]
    terminals = []
    for k in cands:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        e = rec_edges[k]
        fwd = e["n0"] == n
        pos2 = apply_record(pos, e, fwd)
        n2 = e["n1"] if fwd else e["n0"]
        terminals.extend(_dfs(pos2, n2, used | {k}, courses + [_course_of(e)], rec_edges, adj, node_anchors,
                               anchors_by_id, start_id, BRANCH_MAX_DEPTH - 1, budget))
    closed = [t for t in terminals if t["status"] == "closed"]
    if len(closed) == 1:
        r = dict(closed[0])
        r["branch_resolved"] = True
        return r
    if len(closed) > 1:
        r = _open(start_id, courses, f"branch (ambiguous: {len(closed)} continuations close)")
        r["ambiguous_ends"] = sorted({t["end"] for t in closed})
        return r
    return _open(start_id, courses, f"branch ({len(cands)} candidates, {len(terminals)} paths explored "
                                     f"within depth {BRANCH_MAX_DEPTH}, none closed)")


def walk_one(anchor, k0, rec_edges, adj, node_anchors, anchors_by_id):
    n = anchor["node"]
    pos = anchor["pt"].copy()
    used, courses = set(), []
    k = k0
    while True:
        e = rec_edges[k]
        fwd = e["n0"] == n
        pos = apply_record(pos, e, fwd)
        used.add(k)
        courses.append(_course_of(e))
        n = e["n1"] if fwd else e["n0"]
        if len(courses) > MAX_COURSES:
            return _open(anchor["id"], courses, "loop-guard")
        hits = [aid for aid in node_anchors.get(n, []) if aid != anchor["id"]]
        if hits:
            return _finish_at_anchor(anchor["id"], anchors_by_id[hits[0]], pos, courses)
        cands = [j for j in adj.get(n, []) if j not in used]
        if len(cands) == 0:
            return _open(anchor["id"], courses, "ran out of record courses")
        if len(cands) > 1:
            return resolve_branch(pos, n, used, courses, cands, rec_edges, adj, node_anchors, anchors_by_id, anchor["id"])
        k = cands[0]


def run_walks(anchors, rec_edges, adj, node_pos):
    for a in anchors:
        a["node"], a["node_dist"] = nearest_node(node_pos, a["pt"], ARRIVE_FT)
    node_anchors = {}
    for a in anchors:
        if a["node"] is not None:
            node_anchors.setdefault(a["node"], []).append(a["id"])
    anchors_by_id = {a["id"]: a for a in anchors}

    results = []
    for a in anchors:
        if a["node"] is None:
            continue
        for k0 in adj.get(a["node"], []):
            results.append(walk_one(a, k0, rec_edges, adj, node_anchors, anchors_by_id))

    # de-dupe mirrored walks (A->B and B->A over the same courses are the same physical chain)
    seen, deduped = set(), []
    for r in results:
        sig = frozenset(c["name"] for c in r["courses"])
        key = (r["status"], sig, r["end"] and frozenset({r["start"], r["end"]}))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped, [a for a in anchors if a["node"] is None]


# --- recon_anchored (leg 2) ------------------------------------------------------------------------------

def closed_edge_names(chains):
    """Every course name used by ANY closed chain (post branch resolution) -- recon_anchored's own
    definition: boundary covered by a reconstructed edge that belongs to a closed anchored chain."""
    names = set()
    for c in chains:
        if c["status"] == "closed":
            names.update(co["name"] for co in c["courses"])
    return names


def anchored_coverage(internals, names):
    """(covered_ft, denom_ft, per-segment bool aligned to internals["mid"][remaining]) -- SAME denominator
    as recon_all (recon.py's own post-removal `remaining`). recon.py's own cov_mask_full discards the
    matched-edge index (`covered_mask()`'s own `best`); re-run here so each covered segment can be
    attributed back to its own rec_edges entry via rec_parent (face_pieces()'s own majority-vote trick,
    reused at the whole-boundary level instead of per ring piece)."""
    mid, seg_az, seg_len = internals["mid"], internals["seg_az"], internals["seg_len"]
    remaining = internals["remaining"]
    rec_P, rec_Q, rec_az, rec_parent = internals["rec_P"], internals["rec_Q"], internals["rec_az"], internals["rec_parent"]
    rec_edges, buffer_ft = internals["rec_edges"], internals["buffer_ft"]
    any_match, best = recon.covered_mask(mid, seg_az, rec_P, rec_Q, rec_az, buffer_ft, recon.PARALLEL_TOL_DEG)
    anchored_seg = np.zeros(len(mid), bool)
    if any_match.any() and names:
        parent = rec_parent[best[any_match]]
        seg_names = np.array([rec_edges[k]["name"] for k in parent])
        anchored_seg[any_match] = np.isin(seg_names, list(names))
    covered_ft = float(seg_len[remaining & anchored_seg].sum())
    denom_ft = float(seg_len[remaining].sum())
    return covered_ft, denom_ft, anchored_seg[remaining]


def patch_recon_segments_anchored(anchored_seg_kept):
    """Adds an "anchored" bool column to THIS process's own recon_segments.json (recon.run()'s own file,
    just rewritten by load_anchors()'s recon.run() call) -- same shape/order as its existing P/Q/covered/
    dimensioned arrays, so recon_set.py's existing pool-and-dedupe can carry it across sheets exactly like
    those two, for recon_anchored_set_pct."""
    p = OUT / "recon_segments.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    if len(d["P"]) != len(anchored_seg_kept):
        raise SystemExit(f"anchored segment count mismatch: recon_segments.json has {len(d['P'])}, "
                          f"computed {len(anchored_seg_kept)}")
    d["anchored"] = [bool(x) for x in anchored_seg_kept]
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


# --- solvable by closure, unchecked (leg 2) ---------------------------------------------------------------

def load_half_recorded_rows(trav):
    """Every traverse row missing exactly ONE record element (the OTHER came from the drawing) --
    never both, that is "no record" and outside this leg's scope. These never qualify as a
    reconstructed edge (recon.load_rec_edges() requires flags==[]), so they are invisible to the course
    graph above; leg 2 only reported them (never scored, zero redundancy); leg 3's closure_fills()
    checks them against a second landing before counting one.

    kind=='line': "bearing from drawing"/"distance from drawing" flags (traverse.py) -- half="bearing"
    means record gave distance only (row["ft"]), row["az"] is the DRAWING's; half="distance" means
    record gave bearing only (row["az"]), row["ft"] is the DRAWING's.

    kind=='arc', flag "R/L printed, no record chord direction" (traverse.py): R and L are BOTH record
    (this leg's own traverse.py addition passes them through on the row), so the chord LENGTH is fully
    record-derived (2R sin(L/2R), same formula traverse.py's own full-record arc branch uses) even
    though the row's own "ft" is the DRAWING's chord length (traverse.py never trusted R/L for a
    distance without a record direction too -- see its own comment). Only the chord DIRECTION is
    missing -- same shape as a line's half="bearing" (known distance, missing bearing), so it is folded
    into that same category with the record-derived length substituted for row["ft"]."""
    rows = []
    for chain in trav:
        for row in chain["edges"]:
            if not row.get("pts") or len(row["pts"]) < 2:
                continue
            flags = row["flags"]
            pts = np.array(row["pts"], float)
            # row["az"]/a record az is only the direction of whichever way ITS OWN chain happened to
            # walk it (p0->p1 or p1->p0) -- same ambiguity build_graph() resolves for a clean rec_edges
            # entry (see its own docstring); fixed here the identical way, once, into "the az from
            # pts[0] to pts[-1]" (a line's full chord for a line, a curve's own chord for an arc).
            drawn_az = float(recon.azimuth_arr((pts[-1] - pts[0])[None, :])[0])
            if row["kind"] == "line":
                half = None
                if "bearing from drawing" in flags and "distance from drawing" not in flags:
                    half = "bearing"
                elif "distance from drawing" in flags and "bearing from drawing" not in flags:
                    half = "distance"
                if half is None:
                    continue
                az = (row["az"] + 180) % 360 if abs((row["az"] - drawn_az + 180) % 360 - 180) >= 90 else row["az"]
                rows.append({"name": row["edge"], "kind": "line", "az": az, "ft": row["ft"], "half": half,
                             "p": pts[0], "q": pts[-1]})
            elif row["kind"] == "arc" and "R/L printed, no record chord direction" in flags and "R" in row and "L" in row:
                R, L = row["R"], row["L"]
                if not R or abs(L / R) >= 2 * math.pi:  # a real half-angle is well under this; guards div/domain
                    continue
                chord_ft = 2 * R * math.sin(L / R / 2)
                rows.append({"name": row["edge"], "kind": "arc", "az": drawn_az, "ft": chord_ft, "half": "bearing",
                             "p": pts[0], "q": pts[-1], "drawn_ft": row["ft"]})
    return rows


def chain_end_state(chain, anchors_by_id, rec_edges_by_name):
    """Replay a chain's own course-name list from its start anchor to recover the running (pos, node) at
    its FAR end -- the JSON/dict course list carries name/kind/ft/misfit_ft only, not a position. Same
    replay render_chain_crop() already does for a crop's own ground points, factored out so
    solvable_by_closure() can reuse it without re-walking the graph."""
    start = anchors_by_id[chain["start"]]
    pos, n = start["pt"].copy(), start["node"]
    for co in chain["courses"]:
        e = rec_edges_by_name[co["name"]]
        fwd = e["n0"] == n
        pos = apply_record(pos, e, fwd)
        n = e["n1"] if fwd else e["n0"]
    return pos, n


def _closure_candidates(chains, half_rows, anchors, anchors_by_id, rec_edges, node_tol=NODE_FT):
    """leg 2's own match: an OPEN chain (post branch resolution, "ran out of record courses") whose
    current position sits at one end of a half-recorded row (within node_tol) that, completed from THIS
    position to some OTHER anchor's own printed coordinate, agrees with the row's own KNOWN element
    (BEARING_TOL_DEG for a known bearing, CLOSURE_MAX_FT for a known distance). Every match found, with
    enough state (pos, fwd, the open chain itself, the candidate anchor) for leg 3's own closure_fills()
    to check it against a second landing -- the missing element itself is not checked against anything
    here, there is nothing to check it against yet."""
    rec_edges_by_name = {e["name"]: e for e in rec_edges}
    out = []
    for c in chains:
        if c["status"] != "open" or c.get("reason") != "ran out of record courses" or not c["courses"]:
            continue
        pos, _ = chain_end_state(c, anchors_by_id, rec_edges_by_name)
        for row in half_rows:
            if row["name"] in {co["name"] for co in c["courses"]}:
                continue
            d_p, d_q = float(np.hypot(*(pos - row["p"]))), float(np.hypot(*(pos - row["q"])))
            if min(d_p, d_q) > node_tol:
                continue
            fwd = d_p <= d_q  # this chain arrives at the row's own "p" end -> walks it forward
            for a2 in anchors:
                if a2["id"] == c["start"]:
                    continue
                needed = a2["pt"] - pos
                needed_d = float(np.hypot(*needed))
                needed_az = float(recon.azimuth_arr(needed[None, :])[0])
                if row["half"] == "distance":
                    known_az = row["az"] if fwd else (row["az"] + 180) % 360
                    if abs((needed_az - known_az + 180) % 360 - 180) > BEARING_TOL_DEG:
                        continue
                    # exact solve (the distance IS "however far it takes to reach a2") -- lands at a2 by
                    # construction, zero residual; the third-anchor/agreement check is what actually earns it.
                    fill_az, fill_ft, value, residual_ft = row["az"], needed_d, round(needed_d, 3), 0.0
                    diagnostic = {"drawn_ft": row["ft"], "diff_ft": round(needed_d - row["ft"], 3)}
                else:  # missing bearing/chord direction; known element is the record distance/chord length
                    if abs(needed_d - row["ft"]) > CLOSURE_MAX_FT:
                        continue
                    computed_az = needed_az if fwd else (needed_az + 180) % 360
                    # walking the RECORD length (row["ft"]) in computed_az from pos lands short/long of
                    # a2 by this much -- the real landing residual (already bounded <= CLOSURE_MAX_FT above).
                    fill_az, fill_ft, value, residual_ft = computed_az, row["ft"], round(computed_az, 4), round(abs(needed_d - row["ft"]), 3)
                    diagnostic = {"drawn_az_deg": round(row.get("drawn_az", row["az"]), 4),
                                  "diff_deg": round((computed_az - row.get("drawn_az", row["az"]) + 180) % 360 - 180, 3)}
                out.append({"chain": c, "chain_start": c["start"], "course": row["name"], "kind": row["kind"],
                            "missing": row["half"] if row["kind"] == "line" else "chord direction",
                            "reaches": a2["id"], "a2": a2, "fwd": fwd, "row": row, "residual_ft": residual_ft,
                            "fill_az": fill_az, "fill_ft": fill_ft, "value": value, **diagnostic})
    return out


def closure_fills(chains, half_rows, anchors, anchors_by_id, rec_edges, adj, node_pos, node_tol=NODE_FT):
    """Leg 3: leg 2's own candidate match (_closure_candidates(), zero redundancy, never scored) --
    checked. A fill counts ONLY when redundancy checks it: after filling, the walk continues on record
    courses alone (never through another half-recorded row -- those are never in rec_edges/adj, see
    load_half_recorded_rows()'s own docstring, so a second unknown between the same pair just makes the
    continuation dead-end, refused "unchecked", never a false accept) to a THIRD printed anchor within
    ARRIVE_FT (0.5 ft, JR's own number); or the same fill is implied independently by two different
    (chain_start, reaches) anchor pairs agreeing within AGREE_DEG_TOL/AGREE_FT_TOL. Returns
    (candidates: every attempt, report-ready dicts; stitched: one closed-chain dict per ACCEPTED fill,
    same shape run_walks() produces, for closed_edge_names()/anchored_coverage() to fold in verbatim;
    filled_edges: the accepted fill's own geometry, for recon_closure_ft's coverage measurement)."""
    node_anchors = {}
    for a in anchors:
        if a.get("node") is not None:
            node_anchors.setdefault(a["node"], []).append(a["id"])
    idx_by_name = {e["name"]: i for i, e in enumerate(rec_edges)}
    raw = _closure_candidates(chains, half_rows, anchors, anchors_by_id, rec_edges, node_tol)

    def continuation(cand):
        """_dfs() started past the fill (at a2's own node) instead of at a branch -- same bounded search
        resolve_branch() already uses; a landing back at chain_start or a2 itself is excluded by _dfs()'s
        own start_id filter (start_id=a2['id'] here), so every hit is a genuinely different, THIRD
        anchor."""
        a2 = cand["a2"]
        if a2.get("node") is None:
            return [], []
        used = {idx_by_name[co["name"]] for co in cand["chain"]["courses"] if co["name"] in idx_by_name}
        terminals = _dfs(a2["pt"].copy(), a2["node"], used, [], rec_edges, adj, node_anchors, anchors_by_id,
                          a2["id"], BRANCH_MAX_DEPTH, [BRANCH_MAX_PATHS])
        hits = [t for t in terminals if t["end"] is not None and t["end"] != cand["chain_start"]]
        good = [t for t in hits if t["misclosure_ft"] <= ARRIVE_FT]
        return good, hits

    def fmt(cand):
        if cand["missing"] == "distance":
            return f"{cand['value']} ft", f"{cand['drawn_ft']} ft ({cand['diff_ft']:+.3f} ft)"
        return f"{cand['value']} deg", f"{cand['drawn_az_deg']} deg ({cand['diff_deg']:+.3f} deg)"

    entries, by_course = [], {}
    for cand in raw:
        good, hits = continuation(cand)
        computed, drawing = fmt(cand)
        e = {"chain_start": cand["chain_start"], "reaches": cand["reaches"], "course": cand["course"],
             "kind": cand["kind"], "missing": cand["missing"], "computed": computed, "drawing": drawing}
        if len(good) == 1:
            e.update(status="accepted", reason=f"checked ({cand['chain_start']}->{cand['reaches']}->{good[0]['end']})",
                      check_anchor=good[0]["end"], check_misclosure_ft=good[0]["misclosure_ft"], _third=good[0])
        elif len(good) > 1:
            e.update(status="refused", reason=f"ambiguous continuation ({len(good)} third anchors close)")
        elif hits:
            worst = min(hits, key=lambda t: t["misclosure_ft"])
            e.update(status="refused", reason=f"disagrees (checking landing {worst['misclosure_ft']} ft off at {worst['end']})")
        else:
            e.update(status="refused", reason="unchecked (no third anchor reached)")
        e["_cand"] = cand
        entries.append(e)
        by_course.setdefault(cand["course"], []).append(e)

    # agreement fallback: two DIFFERENT (chain_start, reaches) pairs computing the SAME row's missing
    # value, within AGREE_DEG_TOL (bearing/chord direction) or AGREE_FT_TOL (distance) of each other.
    for course, es in by_course.items():
        if any(e["status"] == "accepted" for e in es):
            continue
        pairs = {(e["chain_start"], e["reaches"]) for e in es}
        if len(pairs) < 2:
            continue
        tol = AGREE_FT_TOL if es[0]["_cand"]["missing"] == "distance" else AGREE_DEG_TOL
        base = es[0]["_cand"]["value"]
        agree_pairs = {(e["chain_start"], e["reaches"]) for e in es if abs(e["_cand"]["value"] - base) <= tol}
        if len(agree_pairs) >= 2:
            for e in es:
                if (e["chain_start"], e["reaches"]) in agree_pairs:
                    e.update(status="accepted", reason=f"agrees across {len(agree_pairs)} anchor pairs (<= {tol})")
        else:
            for e in es:
                if e["status"] != "accepted":
                    e.update(status="refused", reason="ambiguous (independent routes disagree)")

    stitched, filled_edges, candidates = [], [], []
    for e in entries:
        cand = e.pop("_cand")
        added_ft = 0.0
        if e["status"] == "accepted":
            row_course = {"name": cand["course"], "kind": cand["kind"], "ft": cand["fill_ft"], "misfit_ft": 0.0}
            end_id = e.get("check_anchor", cand["reaches"])
            third = e.get("_third")
            tail_courses = third["courses"] if third else []
            tail_len = third["length_ft"] if third else 0.0
            misclosure = e.get("check_misclosure_ft", cand["residual_ft"])
            stitched.append({"start": cand["chain_start"], "end": end_id, "status": "closed",
                              "misclosure_ft": misclosure,
                              "length_ft": round(cand["chain"]["length_ft"] + cand["fill_ft"] + tail_len, 2),
                              "n_courses": cand["chain"]["n_courses"] + 1 + len(tail_courses),
                              "courses": cand["chain"]["courses"] + [row_course] + tail_courses,
                              "resolved": "closure_fill", "closure_course": cand["course"]})
            p, q = cand["row"]["p"], cand["row"]["q"]
            if not cand["fwd"]:
                p, q = q, p
            filled_edges.append({"name": cand["course"], "az": cand["fill_az"], "ft": cand["fill_ft"], "p": p, "q": q})
            added_ft = cand["fill_ft"]
        e.pop("_third", None)
        e["added_ft"] = round(added_ft, 1)
        candidates.append(e)
    return candidates, stitched, filled_edges


def closure_coverage(internals, filled_edges):
    """recon_closure_ft: boundary ft newly matched by an ACCEPTED fill's own geometry (chord only,
    ponytail: an arc fill's own curve bow is not walked here the way rec_segments() does for a clean
    rec_edges entry -- upgrade to the same per-segment polyline if a fill ever lands on a sharp arc and
    the chord-vs-curve gap starts to matter). Same covered_mask() recon.py's own recon_all/anchored_
    coverage already use, restricted to `remaining` (post contamination-removal) so it cannot double-
    count ground recon_all/recon_anchored never counted the drawing for in the first place."""
    mid, seg_az, seg_len, remaining = internals["mid"], internals["seg_az"], internals["seg_len"], internals["remaining"]
    buffer_ft = internals["buffer_ft"]
    if not filled_edges:
        return 0.0, np.zeros(int(remaining.sum()), bool)
    rP = np.array([e["p"] for e in filled_edges])
    rQ = np.array([e["q"] for e in filled_edges])
    rAz = np.array([e["az"] for e in filled_edges])
    any_match, _ = recon.covered_mask(mid, seg_az, rP, rQ, rAz, buffer_ft, recon.PARALLEL_TOL_DEG)
    covered_ft = float(seg_len[remaining & any_match].sum())
    return covered_ft, any_match[remaining]


# --- anchored parcels (leg 2) -----------------------------------------------------------------------------

def run_areas_table():
    """areas_table.py for THIS process's own sheet (SHEET env already set the same way load_anchors()'s
    own recon.run() call relies on) -- same subprocess pattern parcel_score.py already uses."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([str(PY), str(ROOT / "spike" / "areas_table.py")], capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    if r.returncode:
        print(f"areas_table.py failed: {r.stderr[-2000:]}")


def anchored_parcels(internals, closed_names):
    """Named (AREAS-table) faces whose WHOLE ring sits on reconstructed edges that are ALL members of a
    closed anchored chain -- recon.face_pieces() (the same per-piece majority-vote recon.py's own
    per-face closure test uses) run directly here so each piece's own assigned edge can be checked
    against closed_names, not just recon.json's own already-summarised "counts" flag (a different,
    weaker test: >=99% covered and closes <=1ft on ITS OWN ring, not "every edge is in a closed anchored
    chain"). Compared against the record's own AREAS table where a parsed area exists for that parcel id
    -- same id-matching parcel_score.py already uses (a merged face's "parcel" property is "|"-joined)."""
    run_areas_table()
    gj = json.loads((OUT / "parcels.geojson").read_text(encoding="utf-8"))
    faces = recon.load_faces(gj)
    areas_path = OUT / "areas_table.json"
    areas = json.loads(areas_path.read_text(encoding="utf-8")) if areas_path.exists() else []
    area_by_id = {a["parcel"]: a["area_sqft"] for a in areas if a.get("area_sqft") is not None}
    rec_P, rec_Q, rec_az, rec_parent = internals["rec_P"], internals["rec_Q"], internals["rec_az"], internals["rec_parent"]
    rec_edges, buffer_ft = internals["rec_edges"], internals["buffer_ft"]
    out = []
    for f in faces:
        if not f["named"]:
            continue
        pieces, pct, total_len = recon.face_pieces(f["ring"], rec_P, rec_Q, rec_az, rec_parent, buffer_ft,
                                                     recon.PARALLEL_TOL_DEG, recon.DENSIFY_FT)
        # recon.CLOSE_PCT (99%): same "whole ring" bar recon.py's own per-face "counts" test uses -- a
        # None-k piece under the remaining <1% is a zero-length digitizing artifact (a duplicate vertex),
        # not a real uncovered course; only a NAMED edge is checked against closed_names below.
        if total_len == 0 or pct < recon.CLOSE_PCT:
            continue
        ks = {k for k, p, q in pieces if k is not None}
        if not ks or any(rec_edges[k]["name"] not in closed_names for k in ks):
            continue
        ids = f["parcel"].split("|")
        rec_area = sum(area_by_id[i] for i in ids) if all(i in area_by_id for i in ids) else None
        face_area = f["poly"].area
        out.append({"parcel": f["parcel"], "face_area_sqft": round(face_area, 1),
                    "record_area_sqft": round(rec_area, 1) if rec_area is not None else None,
                    "diff_pct": round(100 * (face_area - rec_area) / rec_area, 2) if rec_area else None})
    return out


# --- output (leg 4) -------------------------------------------------------------------------------------

def render_crop(key, g, chain, tag, prefix="l19_1"):
    import pymupdf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    inv_fn = recon.inv_of(g["params"])
    page = pymupdf.open(PDF)[0]
    W, H = page.rect.width, page.rect.height
    px = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(px.samples, dtype=np.uint8).reshape(px.height, px.width)

    ground_pts = [chain["path"][0]] + [c["end"] for c in chain["path_courses"]]
    ground_pts = np.array(ground_pts)
    pg = inv_fn(ground_pts)
    cx, cy = pg.mean(0)
    span = max(float(np.hypot(*(pg.max(0) - pg.min(0)))), 40) * 0.6
    x0, x1 = max(0, cx - span), min(W, cx + span)
    y0, y1 = max(0, cy - span), min(H, cy + span)
    fig, ax = plt.subplots(figsize=(7, 7), dpi=150)
    ax.imshow(img, cmap="gray", extent=(0, W, H, 0))
    color = "#2ca02c" if chain["status"] == "closed" else "#e03030"
    ax.plot(pg[:, 0], pg[:, 1], color=color, lw=1.8, marker="o", ms=4)
    ax.scatter([pg[0, 0]], [pg[0, 1]], color="#1f77b4", s=60, zorder=4, label="start anchor")
    ax.scatter([pg[-1, 0]], [pg[-1, 1]], color="#ff7f0e", s=60, zorder=4, marker="s", label="end anchor")
    ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_aspect("equal")
    ax.set_title(f"{key}: {chain['start']}->{chain['end']} ({chain['status']}, "
                 f"{chain['n_courses']} courses, misclosure {chain['misclosure_ft']}')", fontsize=8)
    ax.legend(loc="lower right", fontsize=7)
    ax.axis("off")
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{chain['start']}_{chain['end']}_{tag}")
    fig.savefig(OUT_RECON / f"{prefix}_{key}_{safe}.png")
    plt.close(fig)


def render_closure_crop(key, g, anchors_by_id, rec_edges, filled_by_name, chain, idx):
    """Leg 3: an accepted fill's own crop -- every printed anchor on the sheet (small blue dots, so the
    gate can see A/B/C among them), the whole stitched chain replayed corner to corner, and the filled
    course itself picked out in red. by_name replay mirrors render_chain_crop(); the ONE course whose
    name is chain["closure_course"] is not in rec_edges (it was never a clean record row) so its own
    az/ft come from filled_by_name (closure_fills()'s own filled_edges, already oriented forward -- see
    its own docstring) instead."""
    import pymupdf
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    inv_fn = recon.inv_of(g["params"])
    page = pymupdf.open(PDF)[0]
    W, H = page.rect.width, page.rect.height
    px = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(px.samples, dtype=np.uint8).reshape(px.height, px.width)

    by_name = {e["name"]: e for e in rec_edges}
    start = anchors_by_id[chain["start"]]
    pos, n = start["pt"].copy(), start["node"]
    ground_pts = [pos.copy()]
    fill_idx = None
    for i, co in enumerate(chain["courses"]):
        if co["name"] == chain["closure_course"]:
            fe = filled_by_name[co["name"]]
            pos = pos + np.array([fe["ft"] * math.sin(math.radians(fe["az"])), fe["ft"] * math.cos(math.radians(fe["az"]))])
            fill_idx = i
        else:
            e = by_name[co["name"]]
            fwd = e["n0"] == n
            pos = apply_record(pos, e, fwd)
            n = e["n1"] if fwd else e["n0"]
        ground_pts.append(pos.copy())
    pg = inv_fn(np.array(ground_pts))

    cx, cy = pg.mean(0)
    span = max(float(np.hypot(*(pg.max(0) - pg.min(0)))), 40) * 0.6
    x0, x1 = max(0, cx - span), min(W, cx + span)
    y0, y1 = max(0, cy - span), min(H, cy + span)
    fig, ax = plt.subplots(figsize=(7, 7), dpi=150)
    ax.imshow(img, cmap="gray", extent=(0, W, H, 0))
    all_pts = inv_fn(np.array([a["pt"] for a in anchors_by_id.values()]))
    ax.scatter(all_pts[:, 0], all_pts[:, 1], color="#1f77b4", s=16, zorder=3, label="printed anchors")
    ax.plot(pg[:, 0], pg[:, 1], color="#2ca02c", lw=1.6, marker="o", ms=3, zorder=4)
    if fill_idx is not None:
        seg = pg[fill_idx:fill_idx + 2]
        ax.plot(seg[:, 0], seg[:, 1], color="#e03030", lw=3.0, zorder=5, label="filled course")
    ax.scatter([pg[0, 0]], [pg[0, 1]], color="#ffdd00", s=70, zorder=6, marker="^", edgecolor="k", label="A (start)")
    ax.scatter([pg[-1, 0]], [pg[-1, 1]], color="#ff7f0e", s=70, zorder=6, marker="s", edgecolor="k", label="C (checked)")
    ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_aspect("equal")
    ax.set_title(f"{key}: closure fill {chain['closure_course']} ({chain['start']}->{chain['end']}, "
                 f"misclosure {chain['misclosure_ft']}')", fontsize=8)
    ax.legend(loc="lower right", fontsize=6)
    ax.axis("off")
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{chain['start']}_{chain['end']}_{idx}")
    fig.savefig(OUT_RECON / f"l19_3_{key}_{safe}.png")
    plt.close(fig)


def main(sheet_name, key):
    anchors, g, internals = load_anchors(sheet_name, key)
    trav = json.loads((OUT / "traverse.json").read_text(encoding="utf-8"))
    rec_edges, n_rows = recon.load_rec_edges(trav)
    adj, node_pos = build_graph(rec_edges)
    chains, unplaced = run_walks(anchors, rec_edges, adj, node_pos)
    anchors_by_id = {a["id"]: a for a in anchors}

    closed = [c for c in chains if c["status"] == "closed"]
    failed = [c for c in chains if c["status"] == "failed"]
    open_ = [c for c in chains if c["status"] == "open"]
    resolved = [c for c in closed if c.get("branch_resolved")]
    ambiguous = [c for c in open_ if "ambiguous" in c.get("reason", "")]

    # leg 3: fills checked by a second landing (closure_fills() itself calls leg 2's own candidate
    # match); accepted ones become their own "closed" chains, folded into recon_anchored below exactly
    # like a branch-resolved one (closed_edge_names() takes status=="closed" from any chain-shaped dict).
    half_rows = load_half_recorded_rows(trav)
    closure_candidates, closure_stitched, filled_edges = closure_fills(chains, half_rows, anchors,
                                                                        anchors_by_id, rec_edges, adj, node_pos)
    closure_accepted = [c for c in closure_candidates if c["status"] == "accepted"]

    # leg 2+3: recon_anchored -- boundary ft covered by a reconstructed edge that belongs to a closed
    # chain (leg 1/2) OR a closure-stitched one (leg 3), PLUS the accepted fill's own new segment
    # (never in rec_edges, so closed_edge_names()/anchored_coverage() alone can never see it).
    names = closed_edge_names(chains) | closed_edge_names(closure_stitched)
    anch_covered_ft, anch_denom_ft, anch_seg_kept = anchored_coverage(internals, names)
    closure_ft, closure_seg_kept = closure_coverage(internals, filled_edges)
    combined_seg_kept = anch_seg_kept | closure_seg_kept
    seg_len_remaining = internals["seg_len"][internals["remaining"]]
    total_covered_ft = float(seg_len_remaining[combined_seg_kept].sum())
    closure_net_ft = float(seg_len_remaining[closure_seg_kept & ~anch_seg_kept].sum())  # net new (no double count)
    patch_recon_segments_anchored(combined_seg_kept)

    parcels = anchored_parcels(internals, names | {c["course"] for c in closure_accepted})

    out = {"sheet": key, "n_anchors": len(anchors), "n_anchors_unplaced": len(unplaced),
           "n_reconstructed_edges": len(rec_edges), "n_nodes": len(node_pos),
           "closed": closed, "failed": failed, "open": open_,
           "branch_resolved": resolved, "branch_ambiguous": ambiguous,
           "recon_anchored": {"covered_ft": round(total_covered_ft, 1), "denom_ft": round(anch_denom_ft, 1),
                               "pct": round(100 * total_covered_ft / anch_denom_ft, 2) if anch_denom_ft else 0},
           "recon_closure": {"added_ft": round(closure_net_ft, 1), "n_accepted": len(closure_accepted),
                              "n_candidates": len(closure_candidates)},
           "closure_candidates": closure_candidates,
           "anchored_parcels": parcels}
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / f"anchored_{key}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    # crops: 3 longest closed chains + every failed one (leg 1) + every branch-resolved closed chain
    # (leg 2) + every accepted closure fill, all anchors shown (leg 3)
    for c in sorted(closed, key=lambda c: -c["length_ft"])[:3]:
        render_chain_crop(key, g, c, anchors_by_id, rec_edges, "closed")
    for c in failed:
        render_chain_crop(key, g, c, anchors_by_id, rec_edges, "failed")
    for i, c in enumerate(resolved):  # index disambiguates two resolved chains sharing the same start/end
        render_chain_crop(key, g, c, anchors_by_id, rec_edges, f"resolved{i}", prefix="l19_2")
    filled_by_name = {e["name"]: e for e in filled_edges}
    for i, c in enumerate(closure_stitched):
        render_closure_crop(key, g, anchors_by_id, rec_edges, filled_by_name, c, i)

    print(f"anchored ({key}): {len(anchors)} anchors ({len(unplaced)} unplaced), "
          f"{len(rec_edges)}/{n_rows} reconstructed edges, {len(node_pos)} nodes -> "
          f"{len(closed)} closed ({len(resolved)} by branch resolution), {len(failed)} failed, "
          f"{len(open_)} open ({len(ambiguous)} ambiguous branches) | "
          f"recon_anchored {total_covered_ft:,.0f}/{anch_denom_ft:,.0f} ft ({out['recon_anchored']['pct']:.1f}%) | "
          f"closure fills {len(closure_accepted)}/{len(closure_candidates)} accepted (+{closure_net_ft:,.1f} ft) | "
          f"anchored parcels {len(parcels)}")
    return out


def render_chain_crop(key, g, chain, anchors_by_id, rec_edges, tag, prefix="l19_1"):
    """Re-walks the chain's own courses (by name -> rec_edges, its n0/n1 fixed once by build_graph())
    to recover corner-by-corner ground positions for the crop -- the JSON course list only carries
    name/kind/ft/misfit_ft. ponytail: assumes reconstructed-edge names are unique per sheet (recon.py's
    own convention); a genuine duplicate name would crop against the wrong twin -- cosmetic only, the
    JSON's own course list is unaffected."""
    by_name = {e["name"]: e for e in rec_edges}
    start = anchors_by_id[chain["start"]]
    pos = start["pt"].copy()
    n = start["node"]
    ground_pts = [pos.copy()]
    for c in chain["courses"]:
        e = by_name[c["name"]]
        fwd = e["n0"] == n
        pos = apply_record(pos, e, fwd)
        n = e["n1"] if fwd else e["n0"]
        ground_pts.append(pos.copy())
    chain2 = dict(chain)
    chain2["path"] = [ground_pts[0]]
    chain2["path_courses"] = [{"end": p} for p in ground_pts[1:]]
    render_crop(key, g, chain2, tag, prefix=prefix)


def run_all():
    for key, pdf in SHEET_PDF.items():
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        if pdf:
            env["SHEET"] = str(pdf)
        else:
            env.pop("SHEET", None)
        r = subprocess.run([str(PY), str(Path(__file__)), key], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=env, cwd=ROOT)
        print(r.stdout.strip())
        if r.returncode:
            print(f"anchored ({key}) FAILED:\n" + "\n".join(r.stderr.splitlines()[-30:]))
    write_report()


def write_report():
    lines = ["# Anchored record walk (loop19 leg 1 + leg 2 + leg 3)\n"]
    for key in SHEET_PDF:
        fp = OUT_RECON / f"anchored_{key}.json"
        if not fp.exists():
            continue
        d = json.loads(fp.read_text(encoding="utf-8"))
        lines.append(f"## {key}\n")
        lines.append(f"anchors {d['n_anchors']} ({d['n_anchors_unplaced']} unplaced) | "
                      f"reconstructed edges {d['n_reconstructed_edges']} | nodes {d['n_nodes']}\n")
        lines.append(f"closed {len(d['closed'])} ({len(d.get('branch_resolved', []))} by branch resolution) | "
                      f"failed {len(d['failed'])} | open {len(d['open'])} "
                      f"({len(d.get('branch_ambiguous', []))} ambiguous branches)\n")
        ra = d.get("recon_anchored")
        if ra:
            lines.append(f"recon_anchored: {ra['covered_ft']:,.0f}/{ra['denom_ft']:,.0f} ft ({ra['pct']:.1f}%)\n")
        if d["closed"]:
            mis = sorted(c["misclosure_ft"] for c in d["closed"])
            lines.append(f"closed misclosure ft: median {mis[len(mis) // 2]:.3f}, max {mis[-1]:.3f}\n")
            lines.append("| start | end | courses | length ft | misclosure ft | resolved |")
            lines.append("|---|---|---|---|---|---|")
            for c in sorted(d["closed"], key=lambda c: -c["length_ft"])[:5]:
                lines.append(f"| {c['start']} | {c['end']} | {c['n_courses']} | {c['length_ft']} | "
                              f"{c['misclosure_ft']} | {'Y' if c.get('branch_resolved') else ''} |")
        if d["failed"]:
            lines.append("\n| start | end | courses | length ft | misclosure ft | worst course |")
            lines.append("|---|---|---|---|---|---|")
            for c in d["failed"]:
                lines.append(f"| {c['start']} | {c['end']} | {c['n_courses']} | {c['length_ft']} | "
                              f"{c['misclosure_ft']} | {c['worst_course']} ({c['worst_misfit_ft']}') |")
        if d.get("branch_ambiguous"):
            lines.append("\nambiguous branches (2+ continuations close, left open):\n")
            lines.append("| start | courses so far | candidate ends |")
            lines.append("|---|---|---|")
            for c in d["branch_ambiguous"]:
                lines.append(f"| {c['start']} | {c['n_courses']} | {', '.join(c.get('ambiguous_ends', []))} |")
        rc = d.get("recon_closure")
        cc = d.get("closure_candidates")
        if rc:
            lines.append(f"recon_closure: {rc['n_accepted']}/{rc['n_candidates']} fills accepted, "
                          f"+{rc['added_ft']:,.1f} ft (net, folded into recon_anchored above)\n")
        if cc:
            lines.append("\nclosure fills -- leg 3, a fill counts only when a second landing checks it:\n")
            lines.append("| A->B | course | missing | computed | vs. drawing | status | reason | ft added |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for s in cc:
                lines.append(f"| {s['chain_start']}->{s['reaches']} | {s['course']} | {s['missing']} | "
                              f"{s['computed']} | {s['drawing']} | {s['status']} | {s['reason']} | {s['added_ft']} |")
        ap = d.get("anchored_parcels")
        if ap:
            lines.append("\nparcels whose whole ring sits in closed anchored chains:\n")
            lines.append("| parcel | face area sqft | record area sqft | diff % |")
            lines.append("|---|---|---|---|")
            for p in ap:
                ra_s = f"{p['record_area_sqft']:,.0f}" if p["record_area_sqft"] is not None else "?"
                diff_s = f"{p['diff_pct']:+.1f}%" if p["diff_pct"] is not None else ""
                lines.append(f"| {p['parcel']} | {p['face_area_sqft']:,.0f} | {ra_s} | {diff_s} |")
        lines.append("")
    total_accepted = total_ft = 0
    for key in SHEET_PDF:
        fp = OUT_RECON / f"anchored_{key}.json"
        if not fp.exists():
            continue
        d = json.loads(fp.read_text(encoding="utf-8"))
        rc = d.get("recon_closure")
        if rc:
            total_accepted += rc["n_accepted"]
            total_ft += rc["added_ft"]
    lines.append(f"## set\n\nrecon_closure_ft (sum over sheets with anchors -- ponytail: not deduped across "
                 f"matchlines the way recon_set.py's own set numbers are, negligible at {total_accepted} "
                 f"accepted fills): {total_accepted} accepted, +{total_ft:,.1f} ft\n")
    (OUT_RECON / "anchored.md").write_text("\n".join(lines), encoding="utf-8")


def _make_chain_edges():
    return [
        {"name": "e0", "kind": "line", "az": 0.0, "ft": 50.0, "misfit_ft": 0.05, "p": np.array([0.0, 0.0]), "q": np.array([0.0, 50.0])},
        {"name": "e1", "kind": "line", "az": 90.0, "ft": 100.0, "misfit_ft": 0.02, "p": np.array([0.0, 50.0]), "q": np.array([100.0, 50.0])},
        {"name": "e2", "kind": "line", "az": 0.0, "ft": 50.0, "misfit_ft": 0.03, "p": np.array([100.0, 50.0]), "q": np.array([100.0, 100.0])},
    ]


def _walk_synthetic(rec_edges):
    """build_graph() tags rec_edges with n0/n1 in place -- walk_one() must be handed that SAME list."""
    adj, node_pos = build_graph(rec_edges)
    a0 = {"id": "A1", "pt": np.array([0.0, 0.0])}
    a1 = {"id": "A2", "pt": np.array([100.0, 100.0])}
    a0["node"], _ = nearest_node(node_pos, a0["pt"], ARRIVE_FT)
    a1["node"], _ = nearest_node(node_pos, a1["pt"], ARRIVE_FT)
    node_anchors = {a0["node"]: ["A1"], a1["node"]: ["A2"]}
    anchors_by_id = {"A1": a0, "A2": a1}
    return walk_one(a0, adj[a0["node"]][0], rec_edges, adj, node_anchors, anchors_by_id)


def _edge(name, p, q, misfit_ft=0.02):
    p, q = np.array(p, float), np.array(q, float)
    az = float(recon.azimuth_arr((q - p)[None, :])[0])
    ft = float(np.hypot(*(q - p)))
    return {"name": name, "kind": "line", "az": az, "ft": ft, "misfit_ft": misfit_ft, "p": p, "q": q}


def _make_branch_edges(both_close=False):
    """e0: A1(0,0) -> branch node (0,50). Two candidates off the branch node: eA reaches A2(100,100)
    directly (closes); eB reaches (50,-50), a dead end near no anchor (stays open) -- the "one closes"
    case. both_close=True swaps eB for eC, which reaches A3(80,-60) directly instead (closes too) -- the
    "both close" (ambiguous) case."""
    edges = [_edge("e0", (0, 0), (0, 50)), _edge("eA", (0, 50), (100, 100))]
    edges.append(_edge("eC", (0, 50), (80, -60)) if both_close else _edge("eB", (0, 50), (50, -50)))
    return edges


def _walk_branch(rec_edges, anchors_pt):
    adj, node_pos = build_graph(rec_edges)
    anchors = [{"id": aid, "pt": np.array(pt, float)} for aid, pt in anchors_pt.items()]
    for a in anchors:
        a["node"], _ = nearest_node(node_pos, a["pt"], ARRIVE_FT)
    node_anchors = {}
    for a in anchors:
        if a["node"] is not None:
            node_anchors.setdefault(a["node"], []).append(a["id"])
    anchors_by_id = {a["id"]: a for a in anchors}
    a0 = anchors_by_id["A1"]
    return walk_one(a0, adj[a0["node"]][0], rec_edges, adj, node_anchors, anchors_by_id)


def _closure_setup(tail=True, tail_ft_error=0.0):
    """A1(0,0) -e0-> (0,50) [clean, open: "ran out of record courses"] -row1(east, distance
    missing)-> A2(100,50) [-e2-> (100,100) = A3, when tail] -- the leg 3 fixture: row1's own known
    bearing (east) points exactly at A2, so the missing distance solves to land there; e2 (when
    present) is the third-anchor continuation. A3 stays snapped to e2's own DRAWN endpoint (so it is a
    real graph target); tail_ft_error perturbs e2's own RECORD length only, same as a real course whose
    record disagrees with the drawing -- the walked position misses A3's printed coordinate by that much
    (_finish_at_anchor's own misclosure), without touching where A3 sits on the graph."""
    edges = [_edge("e0", (0, 0), (0, 50))]
    anchors_pt = {"A1": (0.0, 0.0), "A2": (100.0, 50.0)}
    if tail:
        e2 = _edge("e2", (100, 50), (100, 100))
        e2["ft"] += tail_ft_error
        edges.append(e2)
        anchors_pt["A3"] = (100.0, 100.0)
    half_rows = [{"name": "row1", "kind": "line", "az": 90.0, "ft": 95.0, "half": "distance",
                  "p": np.array([0.0, 50.0]), "q": np.array([100.0, 50.0])}]
    adj, node_pos = build_graph(edges)
    anchors = [{"id": aid, "pt": np.array(pt, float)} for aid, pt in anchors_pt.items()]
    chains, _ = run_walks(anchors, edges, adj, node_pos)
    anchors_by_id = {a["id"]: a for a in anchors}
    return chains, half_rows, anchors, anchors_by_id, edges, adj, node_pos


def _agree_setup():
    """A1(0,0) -e0-> (0,50) -rowB(distance known 100', bearing missing)-> two UNCONNECTED anchors
    A2(0,150), A5(0,150.5) sitting on the exact same ray from (0,50) (dx=0 for both) -- neither offers a
    third-anchor continuation (no edges reach them), but their own independently computed bearings agree
    exactly, so the agreement fallback (not the third-anchor one) must accept both."""
    edges = [_edge("e0", (0, 0), (0, 50))]
    anchors_pt = {"A1": (0.0, 0.0), "A2": (0.0, 150.0), "A5": (0.0, 150.5)}
    half_rows = [{"name": "rowB", "kind": "line", "az": 0.0, "ft": 100.0, "half": "bearing",
                  "p": np.array([0.0, 50.0]), "q": np.array([100.0, 50.0])}]
    adj, node_pos = build_graph(edges)
    anchors = [{"id": aid, "pt": np.array(pt, float)} for aid, pt in anchors_pt.items()]
    chains, _ = run_walks(anchors, edges, adj, node_pos)
    anchors_by_id = {a["id"]: a for a in anchors}
    return chains, half_rows, anchors, anchors_by_id, edges, adj, node_pos


def selftest():
    """Synthetic 3-course chain between two anchors: closes within 0.01 ft on clean record numbers; a
    2 ft distance error on one course fails and names that course. Leg 2: a two-way branch where only
    ONE continuation closes is resolved (status "closed", branch_resolved True); one where BOTH
    continuations close stays open (ambiguous, both ends listed)."""
    r = _walk_synthetic(_make_chain_edges())
    assert r["status"] == "closed" and r["misclosure_ft"] < 0.01, f"a clean 3-course chain must close: {r}"
    assert r["n_courses"] == 3 and abs(r["length_ft"] - 200.0) < 0.01, f"length/course-count sanity: {r}"

    bad = _make_chain_edges()
    bad[1]["ft"] = 102.0  # a 2 ft distance error on e1 -- clear of CLOSURE_MAX_FT's own 1.0 ft edge
    bad[1]["misfit_ft"] = 0.4  # e1's own record-vs-drawing misfit also reads high (the real-world tell)
    r2 = _walk_synthetic(bad)
    assert r2["status"] == "failed" and abs(r2["misclosure_ft"] - 2.0) < 0.01, f"a 2 ft course error must fail: {r2}"
    assert r2["worst_course"] == "e1", f"the erred course must be named: {r2}"

    one = _walk_branch(_make_branch_edges(both_close=False), {"A1": (0, 0), "A2": (100, 100)})
    assert one["status"] == "closed" and one.get("branch_resolved"), f"one-of-two-closes must resolve: {one}"
    assert one["end"] == "A2" and {c["name"] for c in one["courses"]} == {"e0", "eA"}, f"resolved path wrong: {one}"

    both = _walk_branch(_make_branch_edges(both_close=True), {"A1": (0, 0), "A2": (100, 100), "A3": (80, -60)})
    assert both["status"] == "open" and "ambiguous" in both["reason"], f"both-close must stay open: {both}"
    assert sorted(both.get("ambiguous_ends", [])) == ["A2", "A3"], f"both candidate ends must be listed: {both}"

    # leg 3: a fill checked by a third anchor within ARRIVE_FT (0.5 ft) is accepted; the same fill with
    # no third anchor is refused ("unchecked"); a checking landing 2 ft off is refused ("disagrees").
    chains, half_rows, anchors, anchors_by_id, edges, adj, node_pos = _closure_setup(tail=True)
    cands, stitched, filled = closure_fills(chains, half_rows, anchors, anchors_by_id, edges, adj, node_pos)
    assert len(cands) == 1, f"exactly one candidate expected: {cands}"
    assert cands[0]["status"] == "accepted" and "checked" in cands[0]["reason"], f"third anchor within 0.5 ft must accept: {cands[0]}"
    assert stitched and stitched[0]["end"] == "A3" and stitched[0]["misclosure_ft"] < 0.01, f"stitched chain must reach A3: {stitched}"
    assert filled and abs(filled[0]["ft"] - 100.0) < 0.01, f"filled distance must solve to 100.0 ft: {filled}"

    chains_u, half_rows_u, anchors_u, anchors_by_id_u, edges_u, adj_u, node_pos_u = _closure_setup(tail=False)
    cands_u, stitched_u, filled_u = closure_fills(chains_u, half_rows_u, anchors_u, anchors_by_id_u, edges_u, adj_u, node_pos_u)
    assert len(cands_u) == 1 and cands_u[0]["status"] == "refused" and "unchecked" in cands_u[0]["reason"], f"no third anchor must refuse: {cands_u}"
    assert not stitched_u and not filled_u, f"a refused fill must not be stitched or scored: {stitched_u} {filled_u}"

    chains_d, half_rows_d, anchors_d, anchors_by_id_d, edges_d, adj_d, node_pos_d = _closure_setup(tail=True, tail_ft_error=2.0)
    cands_d, stitched_d, filled_d = closure_fills(chains_d, half_rows_d, anchors_d, anchors_by_id_d, edges_d, adj_d, node_pos_d)
    assert len(cands_d) == 1 and cands_d[0]["status"] == "refused" and "disagrees" in cands_d[0]["reason"], f"a 2 ft off landing must refuse: {cands_d}"
    assert not stitched_d and not filled_d, f"a disagreeing fill must not be stitched or scored: {stitched_d} {filled_d}"

    # leg 3: two independent anchor pairs computing the SAME missing bearing, agreeing exactly, accept
    # via the agreement fallback even with no third-anchor continuation at all (neither A2 nor A5 is
    # graph-connected here).
    chains_a, half_rows_a, anchors_a, anchors_by_id_a, edges_a, adj_a, node_pos_a = _agree_setup()
    cands_a, stitched_a, filled_a = closure_fills(chains_a, half_rows_a, anchors_a, anchors_by_id_a, edges_a, adj_a, node_pos_a)
    assert len(cands_a) == 2 and all(c["status"] == "accepted" for c in cands_a), f"agreeing independent pairs must accept: {cands_a}"
    assert all("agrees" in c["reason"] for c in cands_a), f"accepted-by-agreement reason must say so: {cands_a}"
    assert len(stitched_a) == 2 and len(filled_a) == 2, f"both agreeing fills must be stitched and scored: {stitched_a} {filled_a}"

    print("anchored.selftest OK: a clean 3-course chain closes within 0.01 ft; a 2 ft distance error "
          "on one course fails and names that course; a two-way branch resolves when only one "
          "continuation closes, stays open (ambiguous) when both do; leg 3 -- a fill checked by a third "
          "anchor within 0.5 ft accepts, the same fill with no third anchor or a 2 ft off landing "
          "refuses, two independent anchor pairs agreeing accepts without any third anchor at all")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--all" in sys.argv:
        run_all()
    elif len(sys.argv) > 1 and sys.argv[1] in SHEET_PDF:
        key = sys.argv[1]
        sheet_name = "presidio" if key == "presidio" else next(k for k, v in inverse.SHEET_NAMES.items() if v == key)
        main(sheet_name, key)
    else:
        raise SystemExit(__doc__)
