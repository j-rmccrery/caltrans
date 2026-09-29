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

def load_half_recorded_lines(trav):
    """Every kind=='line' traverse row missing exactly ONE of bearing/distance from the record (the OTHER
    came from the drawing, per traverse.py's own "bearing from drawing"/"distance from drawing" flags --
    never both, that is "no record" and outside this leg's scope). These never qualify as a
    reconstructed edge (recon.load_rec_edges() requires flags==[]), so they are invisible to the course
    graph above; reported here only, never scored -- a single such course has zero redundancy."""
    rows = []
    for chain in trav:
        for row in chain["edges"]:
            if row["kind"] != "line" or not row.get("pts") or len(row["pts"]) < 2:
                continue
            flags = row["flags"]
            half = None
            if "bearing from drawing" in flags and "distance from drawing" not in flags:
                half = "bearing"   # record gave distance (row["ft"]) only; row["az"] is the DRAWING's
            elif "distance from drawing" in flags and "bearing from drawing" not in flags:
                half = "distance"  # record gave bearing (row["az"]) only; row["ft"] is the DRAWING's
            if half is None:
                continue
            pts = np.array(row["pts"], float)
            # row["az"] is only the direction of whichever way ITS OWN chain happened to walk it (p0->p1
            # or p1->p0) -- same ambiguity build_graph() resolves for a clean rec_edges entry (see its own
            # docstring); fixed here the identical way, once, into "the record az from pts[0] to pts[-1]".
            drawn_az = float(recon.azimuth_arr((pts[-1] - pts[0])[None, :])[0])
            az = (row["az"] + 180) % 360 if abs((row["az"] - drawn_az + 180) % 360 - 180) >= 90 else row["az"]
            rows.append({"name": row["edge"], "az": az, "ft": row["ft"], "half": half,
                         "p": pts[0], "q": pts[-1]})
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


def solvable_by_closure(chains, half_rows, anchors, anchors_by_id, rec_edges, node_tol=NODE_FT):
    """OPEN chains (post branch resolution, still "ran out of record courses") whose current position
    sits at one end of a half-recorded row (within node_tol -- the course graph's own "same drawn vertex"
    tolerance) that, completed from THIS position to some OTHER anchor's own printed coordinate, agrees
    with the row's own KNOWN element (BEARING_TOL_DEG for a known bearing, CLOSURE_MAX_FT for a known
    distance -- the missing element is never checked against anything, there is nothing to check it
    against). Reports every match found; picks none, scores none."""
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
                    out.append({"chain_start": c["start"], "course": row["name"], "missing": "distance",
                               "reaches": a2["id"], "computed_ft": round(needed_d, 3),
                               "drawn_ft": row["ft"], "diff_ft": round(needed_d - row["ft"], 3)})
                else:  # missing bearing; known element is the record distance
                    if abs(needed_d - row["ft"]) > CLOSURE_MAX_FT:
                        continue
                    computed_az = needed_az if fwd else (needed_az + 180) % 360
                    out.append({"chain_start": c["start"], "course": row["name"], "missing": "bearing",
                               "reaches": a2["id"], "computed_az_deg": round(computed_az, 4),
                               "drawn_az_deg": round(row["az"], 4),
                               "diff_deg": round((computed_az - row["az"] + 180) % 360 - 180, 3)})
    return out


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


def main(sheet_name, key):
    anchors, g, internals = load_anchors(sheet_name, key)
    trav = json.loads((OUT / "traverse.json").read_text(encoding="utf-8"))
    rec_edges, n_rows = recon.load_rec_edges(trav)
    adj, node_pos = build_graph(rec_edges)
    chains, unplaced = run_walks(anchors, rec_edges, adj, node_pos)

    closed = [c for c in chains if c["status"] == "closed"]
    failed = [c for c in chains if c["status"] == "failed"]
    open_ = [c for c in chains if c["status"] == "open"]
    resolved = [c for c in closed if c.get("branch_resolved")]
    ambiguous = [c for c in open_ if "ambiguous" in c.get("reason", "")]

    # leg 2: recon_anchored -- boundary ft covered by a reconstructed edge that belongs to a closed chain
    names = closed_edge_names(chains)
    anch_covered_ft, anch_denom_ft, anch_seg_kept = anchored_coverage(internals, names)
    patch_recon_segments_anchored(anch_seg_kept)

    half_rows = load_half_recorded_lines(trav)
    anchors_by_id = {a["id"]: a for a in anchors}
    solvable = solvable_by_closure(chains, half_rows, anchors, anchors_by_id, rec_edges)

    parcels = anchored_parcels(internals, names)

    out = {"sheet": key, "n_anchors": len(anchors), "n_anchors_unplaced": len(unplaced),
           "n_reconstructed_edges": len(rec_edges), "n_nodes": len(node_pos),
           "closed": closed, "failed": failed, "open": open_,
           "branch_resolved": resolved, "branch_ambiguous": ambiguous,
           "recon_anchored": {"covered_ft": round(anch_covered_ft, 1), "denom_ft": round(anch_denom_ft, 1),
                               "pct": round(100 * anch_covered_ft / anch_denom_ft, 2) if anch_denom_ft else 0},
           "solvable_by_closure_unchecked": solvable,
           "anchored_parcels": parcels}
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / f"anchored_{key}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    # crops: 3 longest closed chains + every failed one (leg 1) + every branch-resolved closed chain (leg 2)
    for c in sorted(closed, key=lambda c: -c["length_ft"])[:3]:
        render_chain_crop(key, g, c, anchors_by_id, rec_edges, "closed")
    for c in failed:
        render_chain_crop(key, g, c, anchors_by_id, rec_edges, "failed")
    for i, c in enumerate(resolved):  # index disambiguates two resolved chains sharing the same start/end
        render_chain_crop(key, g, c, anchors_by_id, rec_edges, f"resolved{i}", prefix="l19_2")

    print(f"anchored ({key}): {len(anchors)} anchors ({len(unplaced)} unplaced), "
          f"{len(rec_edges)}/{n_rows} reconstructed edges, {len(node_pos)} nodes -> "
          f"{len(closed)} closed ({len(resolved)} by branch resolution), {len(failed)} failed, "
          f"{len(open_)} open ({len(ambiguous)} ambiguous branches) | "
          f"recon_anchored {anch_covered_ft:,.0f}/{anch_denom_ft:,.0f} ft ({out['recon_anchored']['pct']:.1f}%) | "
          f"solvable-by-closure (unchecked) {len(solvable)} | anchored parcels {len(parcels)}")
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
    lines = ["# Anchored record walk (loop19 leg 1 + leg 2)\n"]
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
        sv = d.get("solvable_by_closure_unchecked")
        if sv:
            lines.append("\nsolvable by closure (unchecked -- zero redundancy, never scored):\n")
            lines.append("| chain start | course | missing | computed | vs. drawing | reaches |")
            lines.append("|---|---|---|---|---|---|")
            for s in sv:
                if s["missing"] == "distance":
                    computed, vs_drawing = f"{s['computed_ft']} ft", f"{s['diff_ft']:+.3f} ft"
                else:
                    computed, vs_drawing = f"{s['computed_az_deg']} deg", f"{s['diff_deg']:+.3f} deg"
                lines.append(f"| {s['chain_start']} | {s['course']} | {s['missing']} | {computed} | {vs_drawing} | {s['reaches']} |")
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

    print("anchored.selftest OK: a clean 3-course chain closes within 0.01 ft; a 2 ft distance error "
          "on one course fails and names that course; a two-way branch resolves when only one "
          "continuation closes, stays open (ambiguous) when both do")


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
