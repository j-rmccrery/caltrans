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
loop19 leg 2 will score anchored chains as their own column.

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


# --- anchors (leg 1) -----------------------------------------------------------------------------------

def load_anchors(sheet_name, key):
    import pymupdf
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text(encoding="utf-8"))
    blocks = inverse.load_blocks(page)
    _, full = recon.run(sheet_name, return_internals=True, make_figures=False)
    P, Q = full["P"], full["Q"]
    pts = inverse.callout_points(g, key) + inverse.table_points(blocks, key)
    inverse.snap_all(pts, P, Q)
    anchors = []
    for p in pts:
        if p["snap_ft"] > inverse.SNAP_FT:
            continue
        anchors.append({"id": p["id"], "E": p["E"], "N": p["N"], "pt": np.array([p["E"], p["N"]], float),
                         "source": p["source"], "snap_ft": p["snap_ft"]})
    return anchors, g


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
        courses.append({"name": e["name"], "kind": e["kind"], "ft": e["ft"], "misfit_ft": e["misfit_ft"]})
        n = e["n1"] if fwd else e["n0"]
        if len(courses) > MAX_COURSES:
            return {"start": anchor["id"], "end": None, "status": "open", "reason": "loop-guard",
                    "misclosure_ft": None, "length_ft": round(sum(c["ft"] for c in courses), 2),
                    "n_courses": len(courses), "courses": courses}
        hits = [aid for aid in node_anchors.get(n, []) if aid != anchor["id"]]
        if hits:
            other = anchors_by_id[hits[0]]
            misclosure = float(np.hypot(*(pos - other["pt"])))
            status = "closed" if misclosure <= CLOSURE_MAX_FT else "failed"
            worst = max(courses, key=lambda c: c["misfit_ft"])
            return {"start": anchor["id"], "end": other["id"], "status": status,
                    "misclosure_ft": round(misclosure, 3), "length_ft": round(sum(c["ft"] for c in courses), 2),
                    "n_courses": len(courses), "courses": courses,
                    "worst_course": worst["name"], "worst_misfit_ft": worst["misfit_ft"]}
        cands = [j for j in adj.get(n, []) if j not in used]
        if len(cands) != 1:
            return {"start": anchor["id"], "end": None, "status": "open",
                    "reason": "branch" if len(cands) > 1 else "ran out of record courses",
                    "misclosure_ft": None, "length_ft": round(sum(c["ft"] for c in courses), 2),
                    "n_courses": len(courses), "courses": courses}
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


# --- output (leg 4) -------------------------------------------------------------------------------------

def render_crop(key, g, chain, tag):
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
    fig.savefig(OUT_RECON / f"l19_1_{key}_{safe}.png")
    plt.close(fig)


def main(sheet_name, key):
    anchors, g = load_anchors(sheet_name, key)
    trav = json.loads((OUT / "traverse.json").read_text(encoding="utf-8"))
    rec_edges, n_rows = recon.load_rec_edges(trav)
    adj, node_pos = build_graph(rec_edges)
    chains, unplaced = run_walks(anchors, rec_edges, adj, node_pos)

    closed = [c for c in chains if c["status"] == "closed"]
    failed = [c for c in chains if c["status"] == "failed"]
    open_ = [c for c in chains if c["status"] == "open"]

    out = {"sheet": key, "n_anchors": len(anchors), "n_anchors_unplaced": len(unplaced),
           "n_reconstructed_edges": len(rec_edges), "n_nodes": len(node_pos),
           "closed": closed, "failed": failed, "open": open_}
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / f"anchored_{key}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    # crops: 3 longest closed chains + every failed one
    anchors_by_id = {a["id"]: a for a in anchors}
    for c in sorted(closed, key=lambda c: -c["length_ft"])[:3]:
        render_chain_crop(key, g, c, anchors_by_id, rec_edges, "closed")
    for c in failed:
        render_chain_crop(key, g, c, anchors_by_id, rec_edges, "failed")

    print(f"anchored ({key}): {len(anchors)} anchors ({len(unplaced)} unplaced), "
          f"{len(rec_edges)}/{n_rows} reconstructed edges, {len(node_pos)} nodes -> "
          f"{len(closed)} closed, {len(failed)} failed, {len(open_)} open")
    return out


def render_chain_crop(key, g, chain, anchors_by_id, rec_edges, tag):
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
    render_crop(key, g, chain2, tag)


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
    lines = ["# Anchored record walk (loop19 leg 1)\n"]
    for key in SHEET_PDF:
        fp = OUT_RECON / f"anchored_{key}.json"
        if not fp.exists():
            continue
        d = json.loads(fp.read_text(encoding="utf-8"))
        lines.append(f"## {key}\n")
        lines.append(f"anchors {d['n_anchors']} ({d['n_anchors_unplaced']} unplaced) | "
                      f"reconstructed edges {d['n_reconstructed_edges']} | nodes {d['n_nodes']}\n")
        lines.append(f"closed {len(d['closed'])} | failed {len(d['failed'])} | open {len(d['open'])}\n")
        if d["closed"]:
            mis = sorted(c["misclosure_ft"] for c in d["closed"])
            lines.append(f"closed misclosure ft: median {mis[len(mis) // 2]:.3f}, max {mis[-1]:.3f}\n")
            lines.append("| start | end | courses | length ft | misclosure ft |")
            lines.append("|---|---|---|---|---|")
            for c in sorted(d["closed"], key=lambda c: -c["length_ft"])[:5]:
                lines.append(f"| {c['start']} | {c['end']} | {c['n_courses']} | {c['length_ft']} | {c['misclosure_ft']} |")
        if d["failed"]:
            lines.append("\n| start | end | courses | length ft | misclosure ft | worst course |")
            lines.append("|---|---|---|---|---|---|")
            for c in d["failed"]:
                lines.append(f"| {c['start']} | {c['end']} | {c['n_courses']} | {c['length_ft']} | "
                              f"{c['misclosure_ft']} | {c['worst_course']} ({c['worst_misfit_ft']}') |")
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


def selftest():
    """Synthetic 3-course chain between two anchors: closes within 0.01 ft on clean record numbers; a
    2 ft distance error on one course fails and names that course."""
    r = _walk_synthetic(_make_chain_edges())
    assert r["status"] == "closed" and r["misclosure_ft"] < 0.01, f"a clean 3-course chain must close: {r}"
    assert r["n_courses"] == 3 and abs(r["length_ft"] - 200.0) < 0.01, f"length/course-count sanity: {r}"

    bad = _make_chain_edges()
    bad[1]["ft"] = 102.0  # a 2 ft distance error on e1 -- clear of CLOSURE_MAX_FT's own 1.0 ft edge
    bad[1]["misfit_ft"] = 0.4  # e1's own record-vs-drawing misfit also reads high (the real-world tell)
    r2 = _walk_synthetic(bad)
    assert r2["status"] == "failed" and abs(r2["misclosure_ft"] - 2.0) < 0.01, f"a 2 ft course error must fail: {r2}"
    assert r2["worst_course"] == "e1", f"the erred course must be named: {r2}"

    print("anchored.selftest OK: a clean 3-course chain closes within 0.01 ft; a 2 ft distance error "
          "on one course fails and names that course")


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
