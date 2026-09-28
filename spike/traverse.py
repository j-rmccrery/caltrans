"""The record twin: the sheet's printed record walked as a traverse, checked against the drawing.

Every value the checks placed on the drawing (labels.json: inline bearings and distances, arc lengths;
tag_labels.json: line and curve table rows through their tags) is an edge with the sheet line it sits
on. Edges that meet end to end form chains; a chain that returns to its start is a closed figure.
Each chain is walked from its first drawn vertex by the record alone — bearing and distance per line,
chord from R and L per curve — and the walked position is compared with the drawn one at every node:
that misfit is what the drawing and the record disagree by, in feet, per edge, with no reader in
between. A closed figure also gets its record area against the parcel table. An edge with no record,
or a curve whose chord direction had to come from the drawing, is flagged, not guessed.
A distance-only line edge that meets a collinear record-bearing neighbour end to end, with no
deflection, inherits that neighbour's own printed bearing (loop16 leg D, candidate 1 -- survey
convention prints a course's bearing once and breaks it into several distance-only pieces; the
drawing decides only WHICH neighbour's value applies, never supplies the value itself). Such a row
loses its "bearing from drawing" flag and carries "bearing_source" instead. See inherit_bearings().
Output: traverse.json (chains, edges, misfits, flags) and a printed summary.
usage: [SHEET=<pdf>] python spike/traverse.py   (after checks.py, tables.py)
       python spike/traverse.py --selftest        (inherit_bearings, no sheet needed)
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, READS, real_text_blocks  # noqa: E402

NODE = 3.0  # pt: two edge ends this close meet
SAME = 1.5  # pt: a bearing's line and a distance's line this close are one line
COLLINEAR_TOL_DEG = 0.05  # deg: drawn-bearing agreement (mod 180) at a shared vertex counted as "no deflection"


def drawn_bearing180(e):
    """Undirected drawn bearing (0-180 deg) of an edge's own drawn geometry: a line's compass course
    does not care which end is called p0, so comparing mod 180 is the right collinearity test."""
    d = e["p1"] - e["p0"]
    return math.degrees(math.atan2(d[0], d[1])) % 180


def own_block_has_bearing(region, bearing_regions):
    """Loop16 leg D2, rule 1 (gate finding, r10434_1's "10.36'"): True when a bearing token was
    printed in THIS distance's own annotation block -- checks.py's region(b) is computed per block
    (a whole multi-line annotation, e.g. "S87 deg 54'05"E|10.36'" is ONE block), so an EXACT region
    match means the same block, never merely a nearby one. Whether or not checks.py's own line
    search for that bearing succeeded: a block's bearing token either (a) lands in labels.json as a
    "bearing"/"chord bearing" row -- pass 1 above already merges that into one full edge by shared
    region, so it never reaches inherit_bearings missing az -- or (b) when its own line search
    failed (r10434_1's case: the candidate line was only 7.2 pt, "piece too short to carry a
    bearing"), an exceptions.json "bearing" row with the SAME region. Either way the record printed
    a bearing with this distance; a different, merely-collinear neighbour's bearing overriding it
    would be wrong by definition, whatever checks.py's own (possibly mis-associated) drawn line for
    the distance shows. `bearing_regions` is every such region (from both labels.json and
    exceptions.json), gathered once per sheet by build_edges()."""
    return region is not None and region in bearing_regions


def inherit_bearings(edges, adj):
    """Loop16 leg D, candidate 1 (collinear inheritance): a distance-only line edge (record ft, no
    record az -- traverse's own 'bearing from drawing' flag) that meets, end to end with no
    deflection, a neighbour line edge carrying a RECORD bearing inherits that neighbour's own
    printed az -- never a bearing measured off the drawing. Survey convention: a course is often
    printed once and then broken into several distance-only pieces (a stationed run, a piece cut at
    a crossing or a table split) -- this recovers that printed bearing for every piece on the same
    straight run. Iterated to a fixed point so a run of N such pieces under one printed bearing all
    inherit it, hop by hop; each inherited edge can then itself seed its next-door neighbour (e.g.
    R-10741's "S10 deg 26'37"E + 889.92'" printed once, the drawn run continuing past it in pieces
    of distance alone). Ambiguous nodes -- two collinear neighbours disagreeing on their own record
    az -- are left alone: flagged, not guessed. An edge flagged "own_bearing_nearby" (build_edges,
    see own_block_has_bearing(): its own printed annotation block already carries a bearing token,
    whether or not checks.py managed to associate it with a drawn line) never inherits either,
    whatever the drawing says -- its own record already claims a bearing, so a collinear-but-
    different neighbour's value would silently overrule the record instead of supplying it (loop16
    leg D2, r10434_1's "10.36'" gate finding: its own block prints "S87 deg 54'05"E|10.36'", not the
    "S2 deg 05'55"W" its mis-associated drawn line happened to touch). The drawing decides only
    WHICH neighbour's value applies (collinearity); the value
    itself always comes from that neighbour's own record, and never overrides a row's own.
    Mutates edges in place (sets "az", "bearing_source", and "bearing_source_edge" -- a direct
    reference to the donor edge object, for a consumer like a crop script that needs the exact
    edge identity rather than a re-lookup by its possibly-ambiguous printed name); returns the
    count filled."""
    filled = 0
    changed = True
    while changed:
        changed = False
        for k, e in enumerate(edges):
            if (e["kind"] != "line" or "az" in e or "ft" not in e or e.get("impossible")
                    or e.get("own_bearing_nearby")):
                continue
            be = drawn_bearing180(e)
            seen = {}  # record az (rounded) -> (diff, neighbour edge) -- collapses agreeing neighbours
            for n in (e["n0"], e["n1"]):
                for j in adj.get(n, []):
                    if j == k:
                        continue
                    m = edges[j]
                    if m["kind"] != "line" or "az" not in m or m.get("impossible"):
                        continue
                    diff = abs(be - drawn_bearing180(m)) % 180
                    diff = min(diff, 180 - diff)
                    if diff <= COLLINEAR_TOL_DEG:
                        seen.setdefault(round(m["az"], 4), (diff, m))
            if len(seen) == 1:
                ((diff, m),) = seen.values()
                e["az"] = m["az"]
                e["bearing_source"] = f"inherited from {m['src']}"
                e["bearing_source_edge"] = m
                filled += 1
                changed = True
    return filled


def selftest():
    """One runnable check for inherit_bearings: three collinear edges sharing nodes 0-1-2-3 along a
    line; edge0 carries the record bearing, edges 1 and 2 are distance-only and must inherit it
    hop by hop. A fourth, non-collinear distance-only edge off node 3 must NOT inherit (no collinear
    record neighbour). A fifth case: two collinear record neighbours that disagree must stay unfilled
    (ambiguous, left flagged rather than guessed). A sixth case (loop16 leg D2, rule 1): a distance
    edge flagged own_bearing_nearby (its own printed course already names a bearing, stacked beside
    it per checks.paired_bearing) must NOT inherit even though it is geometrically collinear with,
    and shares a node with, an unrelated record-bearing neighbour -- the r10434_1 "10.36'" gate
    finding: a merely-collinear neighbour ("S2 deg 05'55"W", the R/W line it was mis-associated to)
    must never override a course whose own record already prints a different bearing ("S87 deg
    54'05"E"), even when the wrong-line association makes the two look adjacent. Also checks
    stacked_bearing_nearby() directly against that real gate case's own label regions."""
    def line(n0, n1, p0, p1, az=None, ft=None, src="e", own_bearing_nearby=False):
        e = {"kind": "line", "p0": np.array(p0, float), "p1": np.array(p1, float), "flags": [],
             "impossible": False, "n0": n0, "n1": n1, "src": src, "own_bearing_nearby": own_bearing_nearby}
        if az is not None:
            e["az"] = az
        if ft is not None:
            e["ft"] = ft
        return e

    edges = [
        line(0, 1, (0, 0), (0, 100), az=0.0, ft=100.0, src="record 100.00'"),      # full record
        line(1, 2, (0, 100), (0, 250), ft=150.0, src="piece B 150.00'"),           # distance-only, collinear
        line(2, 3, (0, 250), (0, 400), ft=150.0, src="piece C 150.00'"),           # distance-only, collinear, 2 hops
        line(3, 4, (0, 400), (100, 400), ft=50.0, src="piece D 50.00'"),           # distance-only, NOT collinear
        line(5, 6, (500, 0), (500, 100), az=10.0, ft=100.0, src="record L"),       # ambiguous pair below
        line(6, 7, (500, 100), (500, 200), az=20.0, ft=100.0, src="record R"),
        line(6, 8, (500, 100), (500, 300), ft=200.0, src="piece amb"),             # collinear with BOTH 10 and 20
        line(9, 10, (0, 1000), (0, 1100), az=45.0, ft=100.0, src="record M"),      # rule-1 case below
        line(10, 11, (0, 1100), (0, 1250), ft=150.0, src="piece own-bearing", own_bearing_nearby=True),
    ]
    adj = {}
    for k, e in enumerate(edges):
        adj.setdefault(e["n0"], []).append(k)
        adj.setdefault(e["n1"], []).append(k)
    n = inherit_bearings(edges, adj)
    assert edges[1]["az"] == 0.0 and edges[1]["bearing_source"] == "inherited from record 100.00'"
    assert edges[1]["bearing_source_edge"] is edges[0], "bearing_source_edge must be the exact donor object, not a name re-lookup"
    assert edges[2]["az"] == 0.0 and "inherited from" in edges[2]["bearing_source"]
    assert "az" not in edges[3], "non-collinear neighbour must not donate a bearing"
    assert "az" not in edges[6], "ambiguous (disagreeing) collinear neighbours must not donate a bearing"
    assert "az" not in edges[8], "own_bearing_nearby must refuse inheritance even from a collinear, node-sharing neighbour"
    assert n == 2, f"expected exactly 2 fills, got {n}"
    print("traverse.selftest: inherit_bearings OK (2 filled; non-collinear, ambiguous, and own-bearing-nearby cases correctly refused)")

    # own_block_has_bearing() against the real gate case (r10434_1, sheet pt): the "10.36'" block is
    # "S87 deg 54'05"E|10.36'" -- ONE block, region (360,1018,417,1044) for both its distance (in
    # labels.json, ok=False) and its bearing (in exceptions.json only: its own line search rejected
    # the candidate as "piece too short to carry a bearing (7.2 pt)", so it never reached labels.json
    # at all -- own_block_has_bearing must still catch it via exceptions.json's bearing regions). A
    # same-printed-text bearing from a DIFFERENT block nearby ("S87 deg 54'05"E" paired with a
    # different distance, "79.99'", region (344,1056,411,1089)) must NOT count -- different block,
    # same text is not the same record.
    dist_region = (360, 1018, 417, 1044)
    own_bearing_region = (360, 1018, 417, 1044)       # same block: the bearing exception's own region
    other_block_region = (344, 1056, 411, 1089)       # a different block, same printed bearing text
    assert own_block_has_bearing(dist_region, {own_bearing_region}) is True
    assert own_block_has_bearing(dist_region, {other_block_region}) is False
    assert own_block_has_bearing(None, {own_bearing_region}) is False
    print("traverse.selftest: own_block_has_bearing OK (r10434_1 10.36' block correctly separated from its neighbour's same-text block)")


def sheet_glyph_h():
    """Median glyph height on this sheet, in sheet pt: the natural unit for a snap tolerance that
    scales with this sheet's own drawing instead of a constant in ft that would be wrong on a
    differently-scaled sheet."""
    p = OUT / "blocks.json"
    if not p.exists():
        return 6.0
    blocks = json.loads(p.read_text(encoding="utf-8"))
    return float(np.median([b["glyph_h"] for b in blocks])) if blocks else 6.0


def build_edges():
    """Every placed record value (labels.json, tag_labels.json) as an edge, merged where a bearing and
    a distance describe the same line. Shared by traverse.py's own walk and other consumers (e.g. the
    tunnel-easement chains in leg5_61985.py) that need the same edge set without a full re-run."""
    # edges: one per placed record, merged where a bearing and a distance sit on the same line
    labels = json.loads((OUT / "labels.json").read_text(encoding="utf-8")) if (OUT / "labels.json").exists() else []
    exceptions = json.loads((OUT / "exceptions.json").read_text(encoding="utf-8")) if (OUT / "exceptions.json").exists() else []
    # loop16 leg D2 rule 1: every block region that printed a bearing token, whether or not checks.py
    # could associate it with a drawn line -- see own_block_has_bearing()
    bearing_regions = {tuple(x["region"]) for x in labels if x["kind"] in ("bearing", "chord bearing") and x.get("region")}
    bearing_regions |= {tuple(x["region"]) for x in exceptions if x.get("kind") == "bearing" and x.get("region")}
    edges = []
    for x in labels:
        P = np.array(x["line"], float)
        e = {"src": x["printed"], "kind": "arc" if x["kind"] == "arc" else "line", "p0": P[0], "p1": P[-1], "pts": P, "flags": [],
             "region": tuple(x["region"]) if x.get("region") else None}
        if x["kind"] in ("bearing", "chord bearing"):  # a chord is the straight edge between an arc's ends (loop 6 leg C)
            e["az"] = x["az"]
        elif x["kind"] in ("distance", "chord distance"):
            e["ft"] = x["ft"]
            e["own_bearing_nearby"] = own_block_has_bearing(e["region"], bearing_regions)
        else:
            e["L"] = x["ft"]
        edges.append(e)
    for x in json.loads((OUT / "tag_labels.json").read_text(encoding="utf-8")) if (OUT / "tag_labels.json").exists() else []:
        P = np.array(x["line"], float)
        e = {"src": x["tag"], "kind": "arc" if x["kind"] == "curve" else "line", "p0": P[0], "p1": P[-1], "pts": P, "flags": [], "region": None}
        if x["kind"] == "line":
            e["az"] = x["az"]
            if not x["total"]:
                e["ft"] = x["dist"]
        else:
            e["R"], e["L"] = x["R"], x["L"]
        edges.append(e)

    # pass 1: a bearing and a distance printed in the same annotation block (same region) are one edge
    # with both values -- the block is the ground truth for "these describe the same line", not whether
    # the two checks happened to land on geometrically identical spans (span_for can trim them a token
    # or two apart even when they are the same printed call).
    by_region = {}
    merged = []
    for e in edges:
        if e["region"] is not None and e["kind"] == "line":
            m = by_region.get(e["region"])
            if m is None:
                by_region[e["region"]] = e
                merged.append(e)
            else:
                for k in ("az", "ft"):
                    if k in e and k not in m:
                        m[k] = e[k]
                m["own_bearing_nearby"] = m.get("own_bearing_nearby", False) or e.get("own_bearing_nearby", False)
                if e["src"] not in m["src"]:
                    m["src"] += " + " + e["src"]
        else:
            merged.append(e)
    edges = merged

    # pass 2: the same line under two separate blocks (bearing beside, distance by leader elsewhere on
    # the same run): one edge, matched by endpoint proximity
    merged = []
    for e in edges:
        for m in merged:
            if m["kind"] == e["kind"] and (np.hypot(*(m["p0"] - e["p0"])) < SAME and np.hypot(*(m["p1"] - e["p1"])) < SAME
                                           or np.hypot(*(m["p0"] - e["p1"])) < SAME and np.hypot(*(m["p1"] - e["p0"])) < SAME):
                for k in ("az", "ft", "R", "L"):
                    if k in e and k not in m:
                        m[k] = e[k]
                m["own_bearing_nearby"] = m.get("own_bearing_nearby", False) or e.get("own_bearing_nearby", False)
                m["src"] += " + " + e["src"]
                break
        else:
            merged.append(e)
    edges = merged
    # A third pass tried pairing a leftover bearing-only edge with a leftover distance-only edge by
    # collinearity + span overlap alone (no shared block, no shared endpoint): on this sheet the one
    # geometrically plausible match it found (N77 deg 39'22"E paired with the drawn line under "391.93'")
    # was wrong -- it broke a 5-edge chain that closed to 0.05 ft (391.93' walked from the drawing) into
    # a 4-edge chain that misses by 173 ft (391.93' walked on the printed bearing instead). Two labels
    # sitting near the same infinite line is not enough evidence that they are the same record edge;
    # dropped rather than guess. A bearing-only or distance-only edge is left flagged.

    return edges


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, b, tx, ty = g["params"]

    def ground(p):
        sx, sy = p[0], -p[1]
        return np.array([a * sx - b * sy + tx, b * sx + a * sy + ty])

    def azimuth(p, q):
        d = ground(q) - ground(p)
        return math.degrees(math.atan2(d[0], d[1])) % 360

    edges = build_edges()
    print(f"record edges placed on the drawing: {len(edges)} ({sum(1 for e in edges if e['kind'] == 'line' and 'az' in e and 'ft' in e)} lines with bearing and distance, "
          f"{sum(1 for e in edges if e['kind'] == 'arc' and 'R' in e)} curves with R and L)")

    # an arc's own record length can never be shorter than the straight chord between its matched
    # ends (L = R*theta, chord = 2R*sin(theta/2), and L >= chord for every theta >= 0): a piece whose
    # printed length is shorter than its drawn chord was not matched to the curve it describes (e.g.
    # loop2 leg C's wider bezier candidate pool: R-10434.1's '31.80'' measures a 308 ft run instead of
    # its own 31.80 ft piece). Such an edge is dropped from the node graph -- it still gets its own
    # one-edge entry below, flagged, but it can no longer sit at a shared vertex and turn a real
    # pass-through into a branch that stops the chain walk.
    scale = g["scale_ft_per_pt"]
    for e in edges:
        e["impossible"] = bool(e["kind"] == "arc" and "L" in e
                                and e["L"] < float(np.hypot(*(e["p1"] - e["p0"]))) * scale * 0.98)
        if e["impossible"]:
            e["flags"].append(f"L {e['L']:.2f} ft shorter than the drawn chord: impossible match, dropped from the graph")

    # nodes: edge ends clustered. An 'impossible' edge's ends are excluded from the shared tree, each
    # kept as its own private node, so a wrong candidate match can never bridge two real chains or
    # fracture one apart.
    ends = np.array([p for e in edges for p in (e["p0"], e["p1"])])
    possible = np.array([not edges[i // 2]["impossible"] for i in range(len(ends))])
    good_idx = np.nonzero(possible)[0]
    tree = cKDTree(ends[good_idx]) if len(good_idx) else None
    node_of = {}
    for gi, i in enumerate(good_idx):
        i = int(i)
        if i in node_of:
            continue
        for gj in tree.query_ball_point(ends[i], NODE):
            node_of.setdefault(int(good_idx[gj]), i)
    for i in np.nonzero(~possible)[0]:
        node_of[int(i)] = int(i)

    # a compound curve's cut point can land a few pt from where the next record edge starts (the same
    # split_at regrouping as above): snap loose ends (degree 1, otherwise unconnected) within one
    # glyph height of another loose end, so a small cut-point drift does not read as a chain break.
    # Pairs only, never a radius merge over the whole point set -- that snowballs transitively into a
    # spray of accidental branch points elsewhere on the sheet (tried, made Presidio and R-10434.1
    # both worse: more, smaller chains, no new closures).
    adj = {}
    for k, e in enumerate(edges):
        n0, n1 = node_of[2 * k], node_of[2 * k + 1]
        e["n0"], e["n1"] = n0, n1
        adj.setdefault(n0, []).append(k); adj.setdefault(n1, []).append(k)
    gh = sheet_glyph_h()
    impossible_nodes = {node_of[int(i)] for i in np.nonzero(~possible)[0]}
    loose = [n for n in adj if len(adj[n]) == 1 and n not in impossible_nodes]
    if loose:
        loose_pts = ends[loose]
        ltree = cKDTree(loose_pts)
        paired = set()
        cand = sorted(ltree.query_pairs(gh), key=lambda p: np.hypot(*(loose_pts[p[0]] - loose_pts[p[1]])))
        for i, j in cand:
            ni, nj = loose[i], loose[j]
            if ni in paired or nj in paired or ni == nj:
                continue
            paired.add(ni); paired.add(nj)
            lo, hi = min(ni, nj), max(ni, nj)
            for e in edges:
                if e["n0"] == hi:
                    e["n0"] = lo
                if e["n1"] == hi:
                    e["n1"] = lo
            adj[lo] = adj.pop(lo) + adj.pop(hi)

    n_inherited = inherit_bearings(edges, adj)
    if n_inherited:
        print(f"loop16-D collinear inheritance: {n_inherited} distance-only edge(s) took a record bearing from a collinear neighbour")

    # chains: follow edges end to end while the way on is single
    used, chains = set(), []
    for start in sorted(adj, key=lambda n: len(adj[n])):  # loose ends first, so open chains start at their end
        for k0 in adj[start]:
            if k0 in used:
                continue
            chain, n, k = [], start, k0
            while k is not None and k not in used:
                used.add(k)
                e = edges[k]
                fwd = e["n0"] == n
                chain.append((k, fwd))
                n = e["n1"] if fwd else e["n0"]
                nxt = [j for j in adj[n] if j not in used]
                k = nxt[0] if len(nxt) == 1 else None
            chains.append({"edges": chain, "closed": n == start and len(chain) > 2, "end": n})

    def walk(chain):
        """Positions by the record from the first drawn vertex; misfit vs the drawn vertex at each node."""
        k0, f0 = chain["edges"][0]
        e0 = edges[k0]
        pos = ground(e0["p0"] if f0 else e0["p1"])
        rows, misfits = [], []
        for k, fwd in chain["edges"]:
            e = edges[k]
            p, q = (e["p0"], e["p1"]) if fwd else (e["p1"], e["p0"])
            drawn_az = azimuth(p, q)
            flags = list(e["flags"])
            if e["kind"] == "line":
                if "az" in e:
                    az = e["az"] if abs((e["az"] - drawn_az + 180) % 360 - 180) < 90 else (e["az"] + 180) % 360
                else:
                    az = drawn_az; flags.append("bearing from drawing")
                if "ft" in e:
                    d = e["ft"]
                else:
                    d = float(np.hypot(*(ground(q) - ground(p)))); flags.append("distance from drawing")
            else:
                az = drawn_az; flags.append("chord direction from drawing")
                if "R" in e and "L" in e:
                    d = 2 * e["R"] * math.sin(e["L"] / e["R"] / 2)
                elif "L" in e:
                    d = float(np.hypot(*(ground(q) - ground(p)))); flags.append("chord from drawing (no radius)")
                else:
                    d = float(np.hypot(*(ground(q) - ground(p)))); flags.append("no record")
            pos = pos + d * np.array([math.sin(math.radians(az)), math.cos(math.radians(az))])
            mis = float(np.hypot(*(pos - ground(q))))
            misfits.append(mis)
            row = {"edge": e["src"], "kind": e["kind"], "az": round(az, 4), "ft": round(d, 2), "misfit_ft": round(mis, 2), "flags": flags,
                   "E": round(float(pos[0]), 2), "N": round(float(pos[1]), 2),
                   "pts": [[round(float(gp[0]), 2), round(float(gp[1]), 2)] for gp in (ground(pt) for pt in e["pts"])]}
            if "bearing_source" in e:  # loop16-D: this edge's az came from a collinear record neighbour, not the drawing
                row["bearing_source"] = e["bearing_source"]
            rows.append(row)
        return rows, misfits

    out = []
    for c in chains:
        rows, mis = walk(c)
        rec = {"closed": c["closed"], "n_edges": len(rows), "full_record": sum(1 for r in rows if not r["flags"]),
               "misfit_max_ft": round(max(mis), 2), "misfit_end_ft": round(mis[-1], 2), "edges": rows}
        if c["closed"]:
            P = np.array([[r["E"], r["N"]] for r in rows])
            rec["record_area_sqft"] = round(0.5 * abs(np.dot(P[:, 0], np.roll(P[:, 1], -1)) - np.dot(P[:, 1], np.roll(P[:, 0], -1))), 1)
        out.append(rec)
    out.sort(key=lambda r: (-r["closed"], -r["n_edges"]))
    (OUT / "traverse.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    closed = [r for r in out if r["closed"]]
    long_ = [r for r in out if r["n_edges"] >= 2]
    print(f"chains: {len(out)} ({len(closed)} closed, {len(long_)} of 2+ edges); edges with a full record {sum(r['full_record'] for r in out)} of {sum(r['n_edges'] for r in out)}")
    print(f"{'chain':6} {'edges':>5} {'full':>4} {'closed':>6} {'end misfit':>10} {'max misfit':>10}  edges")
    for i, r in enumerate([r for r in out if r["n_edges"] >= 2][:20]):
        print(f"{i:6} {r['n_edges']:5} {r['full_record']:4} {str(r['closed']):>6} {r['misfit_end_ft']:10.2f} {r['misfit_max_ft']:10.2f}  {' > '.join(e['edge'][:14] for e in r['edges'])[:90]}")
    # where the drawing and the record disagree, per edge, over the whole sheet
    full = [e for r in out for e in r["edges"] if not e["flags"]]
    if full:
        m = np.array([e["misfit_ft"] for e in full])
        print(f"edges with full record: {len(full)}; per-edge misfit vs drawing median {np.median(m):.2f} ft, 90% {np.percentile(m, 90):.2f} ft, max {m.max():.2f} ft")

    # parcel faces: how much of each named face's boundary the record covers
    try:
        from parcels import faces_on_sheet, face_names, TABLE_AREA
        from shapely.geometry import LineString
        blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
        faces = faces_on_sheet(page)
        names = face_names(page, faces, blocks)
        lines = [LineString(e["pts"]) for e in edges]
        figures = []
        for fi, f in enumerate(faces):
            if not names[fi]:
                continue
            # the face's boundary walked: each drawn piece under a record edge takes the record's value, the rest the drawing's
            C = list(f.exterior.coords)
            pieces = []  # (record edge index or None, first point, last point)
            for i in range(len(C) - 1):
                seg = LineString(C[i:i + 2])
                hit = [k for k, ln in enumerate(lines) if seg.distance(ln) < 2.0 and (edges[k]["kind"] == "arc" or ln.length > 0.5 * seg.length)]
                k = min(hit, key=lambda k: seg.distance(lines[k])) if hit else None
                if pieces and pieces[-1][0] == k and (k is not None or abs((azimuth(C[i], C[i + 1]) - azimuth(*pieces[-1][1:3]) + 180) % 360 - 180) < 2.0):
                    pieces[-1] = (k, pieces[-1][1], C[i + 1])
                else:
                    pieces.append((k, C[i], C[i + 1]))
            pos = ground(C[0]); P = [pos]; by_record = 0; flags = []
            for k, p, q in pieces:
                drawn = ground(q) - ground(p)
                if k is None:
                    v = drawn; flags.append("drawn")
                else:
                    e = edges[k]; drawn_az = azimuth(p, q)
                    if e["kind"] == "line" and "az" in e and "ft" in e:
                        az = e["az"] if abs((e["az"] - drawn_az + 180) % 360 - 180) < 90 else (e["az"] + 180) % 360
                        v = e["ft"] * np.array([math.sin(math.radians(az)), math.cos(math.radians(az))]); by_record += 1
                    elif e["kind"] == "arc" and "R" in e and "L" in e:
                        d = 2 * e["R"] * math.sin(e["L"] / e["R"] / 2)
                        v = d * drawn / max(np.hypot(*drawn), 1e-9); by_record += 1; flags.append("chord direction drawn")
                    else:
                        v = drawn; flags.append("partial record")
                pos = pos + v; P.append(pos)
            P = np.array(P)
            area = 0.5 * abs(np.dot(P[:-1, 0], P[1:, 1]) - np.dot(P[:-1, 1], P[1:, 0]))
            name = names[fi][0] if len(names[fi]) == 1 else "|".join(names[fi])
            fig = {"parcel": name, "edges": len(pieces), "by_record": by_record, "closure_ft": round(float(np.hypot(*(P[-1] - P[0]))), 2), "record_area_sqft": round(float(area), 1), "flags": flags}
            if name in TABLE_AREA:
                unit, want = TABLE_AREA[name]
                want = want if unit == "SF" else want * 43560.0
                fig["table_area_sqft"] = want; fig["diff_pct"] = round(100 * (area - want) / want, 2)
            figures.append(fig)
            print(f"figure {name:12} edges {len(pieces):3} by record {by_record:3} closure {fig['closure_ft']:8.2f} ft  area {area:12,.0f} sq ft" + (f"  table {fig['table_area_sqft']:12,.0f}  {fig['diff_pct']:+8.2f} %" if "table_area_sqft" in fig else ""))
        (OUT / "traverse_figures.json").write_text(json.dumps(figures, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("faces skipped:", type(e).__name__, str(e)[:80])


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
