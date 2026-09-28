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
A curve edge (R and delta/L from its tag_labels table row) gets its own chord DIRECTION from the
record the same way (loop16 leg E), never from the drawing: a printed chord bearing beside it (CB),
or a record line meeting it tangentially at a shared node (chord az = tangent az +/- delta/2, sign
from the drawing). See complete_curve_chords(). A curve still missing R or delta/L, or whose only
candidate record tangents disagree, keeps its "chord direction from drawing" flag.
Output: traverse.json (chains, edges, misfits, flags) and a printed summary.
usage: [SHEET=<pdf>] python spike/traverse.py   (after checks.py, tables.py)
       python spike/traverse.py --selftest        (inherit_bearings, complete_curve_chords; no sheet needed)
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
DELTA_CONSISTENCY_TOL_DEG = 0.1  # deg: how far a curve row's own printed delta may disagree with its
# own L/R-implied angle (L = R*theta is exact for one real curve piece) before the row is refused --
# see complete_curve_chords()'s own comment. Loop16 leg E set this at 2.0 deg off one known-bad case
# (r10434_3's merged "L=34.05' + C19", 52 deg off); leg F's radial source exposed a SECOND, subtler
# instance of the identical build_edges pass-2 endpoint-merge bug that 2.0 deg let straight through
# (r10434_3's "L=39.86'(T) + C11": its own table row is R=500, L=31.84, delta=3.65 deg -- consistent
# with ITSELF, degrees(31.84/500)=3.65 -- but got merged onto a drawn piece a DIFFERENT, also-genuine
# "L=39.86'(T)" run-total label already confirmed exactly against the drawn length; delta vs THAT L's
# own implied angle is 0.92 deg off, under the old 2.0 deg tolerance, so the row passed through and
# leg F's radial gave it a chord az that put its own misfit at 4.22 ft, which walk() then carried into
# every downstream edge of its (open, unclosed) chain -- recon_all on r10434_3 measured -281 ft before
# this was caught and fixed. Every genuine single-piece curve measured across all 6 gate sheets sits
# under 0.007 deg (36 rows, loop16 leg F); every known-contaminated merge sits at 0.92 deg or worse
# (three rows: 0.92, 52, 425). 0.1 clears the real distribution by 15x with room to spare and refuses
# both contaminated merges with an 9x margin below the smallest one measured.
TANGENT_TOL_DEG = 1.0  # deg: how far a curve's own circle-fit tangent at a shared node may sit from a
# true 180 deg reversal of the adjoining record line's own drawn departure direction (see
# arc_end_tangent_az/complete_curve_chords) and still count as tangent. Measured (loop16 leg E) over
# every curve-with-record-R candidate node on the 6 gate sheets: the one genuine tangent join found
# (r10434_3's C19, meeting "S31 deg 58'57"W + 108.30'") measures 0.19 deg off true tangency; the
# next-nearest candidate (not actually tangent) measures 6.89 deg -- a 35x gap. 1.0 sits with headroom
# above the real join and well clear of the nearest false one.


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


def fit_circle_lsq(P):
    """Least-squares circle (algebraic fit) through every point of a polyline -- same fit as
    tables.fit_radius, plus the centre (needed for a tangent direction, which the radius alone can't
    give). Reused rather than re-derived; tables.py doesn't expose its own version as a shared import
    (module-private helper there)."""
    x, y = P[:, 0], P[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones(len(P))])
    (cx, cy, c), *_ = np.linalg.lstsq(A, x ** 2 + y ** 2, rcond=None)
    return np.array([cx, cy]), math.sqrt(max(c + cx ** 2 + cy ** 2, 0))


def arc_end_tangent_az(e, end, azimuth):
    """Drawn compass azimuth of a curve edge's own tangent direction, leaving node `end` (0 = p0/n0,
    1 = p1/n1) into the curve -- from a least-squares circle fit through the edge's own drawn "pts"
    (every point, not a raw 2-point secant off the end: loop16 leg E measured a bare secant on the
    curve's own ~20-point downsampled "pts" several degrees off the true tangent on some curves, since
    a downsampled arc's first segment can itself span a real fraction of the curve). The fit gives two
    perpendicular candidate directions at the node (a tangent has no separate "which way" of its own);
    picked by whichever agrees with a short secant off the node (direction only, never magnitude -- the
    secant is exactly the noisy estimate this function exists to correct, so it is never used for more
    than a 180 deg tie-break). None where "pts" is too short (<3 points) or degenerate."""
    pts = e["pts"]
    if len(pts) < 3:
        return None
    if end == 0:
        node_pt, near_pt = pts[0], pts[min(1, len(pts) - 1)]
    else:
        node_pt, near_pt = pts[-1], pts[max(len(pts) - 2, 0)]
    if np.hypot(*(near_pt - node_pt)) < 1e-6:
        return None
    secant_az = azimuth(node_pt, near_pt)
    center, r_fit = fit_circle_lsq(pts)
    radial = node_pt - center
    if np.hypot(*radial) < 1e-6:
        return None
    perp = np.array([-radial[1], radial[0]])
    az1 = azimuth(node_pt, node_pt + perp)
    az2 = azimuth(node_pt, node_pt - perp)
    d1 = abs((az1 - secant_az + 180) % 360 - 180)
    d2 = abs((az2 - secant_az + 180) % 360 - 180)
    return az1 if d1 <= d2 else az2


def _pick_by_drawn_chord(cands, drawn_chord_az):
    """Of two record-consistent chord az candidates (delta deg apart), the one nearer the curve's own
    drawn chord (mod 180 -- an undirected line comparison, same reasoning as drawn_bearing180): the
    drawing decides WHICH one applies, never supplies the value itself (leg D's own rule, reused)."""
    def circ180(a, b):
        d = abs(a - b) % 180
        return min(d, 180 - d)
    return min(cands, key=lambda c: circ180(c, drawn_chord_az))


def complete_curve_chords(edges, adj, azimuth, radials=()):
    """Loop16 leg E (extended leg F): give a curve edge its record chord DIRECTION from the record
    where the record determines it -- never from the drawing (traverse.py used to always take a
    curve's chord az from the drawing; see module docstring). Three record sources, tried per curve
    in this priority order (a curve still lacking R or delta/L is skipped outright -- no source can
    complete a row with no record geometry to place a direction on):
      1. CB - a printed chord bearing (checks.py's "chord bearing" kind, loop6 leg C rule 2: a label
         beside a curve that cites the chord, not the arc) whose own matched piece shares BOTH this
         arc edge's own nodes (built_edges' "chord_label" tag; matched by node PAIR, never merely by
         proximity, so an unrelated nearby chord label can never attach to the wrong curve): the
         record value itself, ambiguous by 180 deg exactly like any other bearing -- resolved by
         drawn chord, same rule as every other source below.
      2. tangent - a record line edge (its own printed bearing, or a loop16-D inherited one) meeting
         the curve tangentially at a shared node: arc_end_tangent_az() there, compared against the
         line's own resolved record direction continuing THROUGH the node into the curve, within
         TANGENT_TOL_DEG of true tangency. Two or more candidate donors at one end that disagree once
         resolved are left alone (ambiguous -- the "(T)" trap STATE.md flagged: an alignment tangent
         and the R/W line running collinear with it are different record courses that happen to share
         a drawn point, and averaging them would be a guess, not a record value), same pattern
         inherit_bearings() already uses for a disagreeing straight-line neighbour. Tried at both ends
         independently; if both ends yield a candidate and they disagree beyond TANGENT_TOL_DEG (past
         where sampling noise alone would explain it), the curve is left alone too -- two ends of one
         physical curve must describe the same chord, so disagreement means at least one donor is the
         wrong course, not a tie to break by fiat. Chord az = tangent (that end's resolved record
         direction into the curve) +/- delta/2; sign picked against the curve's OWN drawn chord
         (_pick_by_drawn_chord) -- the drawing decides only WHICH of the two record-consistent values
         applies, same rule leg D's own docstring states for straight-line inheritance.
      3. radial - loop16 leg F. Tried at an end only once the tangent-LINE search above found no
         record line meeting it (an empty `seen`, never an ambiguous one -- an end where two record
         lines already disagree stays refused, radial or not; the line evidence takes priority when
         it exists at all). `radials` is checks.py's radials.json (a printed "(R)" bearing -- real
         record data with no drawn line of its own to check, see checks.py's "bearing (R)" branch),
         pre-filtered to this end's own node point within NODE pt (a radial and the curve it names
         share a drawn point, same coincidence test build_edges' own node-clustering already uses).
         A radial bearing gives the RADIAL line's own direction, ambiguous by 180 deg like any
         bearing -- rotate it +/-90 deg for the two candidate TANGENT directions at that point, and
         keep only the one within TANGENT_TOL_DEG of the curve's own drawn tangent there
         (arc_end_tangent_az) -- same tangency discipline as the line-donor source, never a guess:
         a radial that doesn't actually sit near true-tangent-perpendicular at this end is not this
         end's radial, whatever label happened to be nearest. Two or more radials at one end that
         each pass but disagree are left alone (ambiguous), same as the line-donor source. Chord az
         from there is the same tangent +/- delta/2, drawn-chord-picked, as source 2.
    Sets "az", "chord_source" (cites the source: "CB", "tangent to <donor edge's own src>", or
    "radial <printed text>") and "chord_source_edge" (a reference to the donor -- the donor edge
    object for CB/tangent, or a synthetic {p0, p1, region, src} dict for radial, shaped the same way
    a crop script (legE_crops.py) already reads a donor) on a completed row; mutates edges in place.
    Returns the count completed."""
    filled = 0
    # CB: index chord-label line edges by their own node pair, once (not a per-curve adjacency scan --
    # a chord label shares BOTH the arc's nodes, not just one, so it is never found via adj[] alone).
    by_node_pair = {}
    for m in edges:
        if m["kind"] == "line" and m.get("chord_label") and "az" in m:
            by_node_pair.setdefault(frozenset((m["n0"], m["n1"])), []).append(m)

    for e in edges:
        if e["kind"] != "arc" or "az" in e or e.get("impossible") or "R" not in e:
            continue
        if "delta" in e:
            delta = e["delta"]
            # L = R*theta is a geometric identity for one real curve piece: a printed delta that
            # disagrees with this SAME edge's own L/R-implied angle means build_edges' pass-2
            # endpoint-proximity merge (a pre-existing, unrelated-to-this-leg step: two arc edges
            # merge whenever their drawn endpoints sit within SAME pt, whatever their R/L/delta say)
            # combined a table curve row with a DIFFERENT, merely nearby-ending arc record -- measured
            # on r10434_3's "L=34.05' + C19": C19's own table row is R=65, L=93.18, delta=82.14 deg
            # (its OWN L/R angle, 82.14 deg, agrees with its own delta, as it must); the edge this
            # leg would place a chord on instead carries the SHORTER "L=34.05'" label's own drawn
            # geometry with C19's R and delta grafted on by the merge -- L/R-implied 30.02 deg, 52 deg
            # off the printed 82.14 deg. Neither L nor delta can be trusted alone once they disagree
            # this much: refused, not guessed.
            if "L" in e and abs(delta - math.degrees(e["L"] / e["R"])) > DELTA_CONSISTENCY_TOL_DEG:
                continue
        elif "L" in e:
            delta = math.degrees(e["L"] / e["R"])
        else:
            continue  # no delta/L: nothing to place a direction on (still flagged, unchanged)
        drawn_chord_az = azimuth(e["p0"], e["p1"])

        cb = by_node_pair.get(frozenset((e["n0"], e["n1"])))
        if cb:
            # stored raw (unresolved), exactly like any other record bearing -- walk() already resolves
            # the +/-180 ambiguity per traversal direction; ..._pick_by_drawn_chord would be a no-op
            # here anyway (the two candidates are exactly 180 apart, indistinguishable mod 180)
            e["az"] = cb[0]["az"]
            e["chord_source"] = "CB"
            e["chord_source_edge"] = cb[0]  # direct reference, for a crop script (loop16-D's own pattern)
            filled += 1
            continue

        end_candidates = {}  # end (0/1) -> resolved chord az, or None if no/ambiguous donor
        end_donor = {}   # end -> donor object (a line edge, or a synthetic radial donor dict)
        end_source = {}  # end -> the exact chord_source string to store
        for end, node in ((0, e["n0"]), (1, e["n1"])):
            arc_tangent_az = arc_end_tangent_az(e, end, azimuth)
            if arc_tangent_az is None:
                continue
            seen = {}  # resolved record-tangent az (rounded) -> donor edge, collapses agreeing donors
            for j in adj.get(node, []):
                m = edges[j]
                if m["kind"] != "line" or "az" not in m or m.get("impossible") or m.get("chord_label"):
                    continue
                other_end = m["p1"] if m["n0"] == node else m["p0"]
                own_end = m["p0"] if m["n0"] == node else m["p1"]
                line_leave_az = azimuth(own_end, other_end)  # departing the node, away from the curve
                diff = abs((m["az"] - line_leave_az + 180) % 360 - 180)
                # the record direction continuing THROUGH the node, into the curve -- opposite the
                # line's own departure direction just resolved above
                record_tangent_az = (((m["az"] if diff < 90 else (m["az"] + 180) % 360)) + 180) % 360
                deflect = abs(180 - abs((line_leave_az - arc_tangent_az + 180) % 360 - 180))
                if deflect <= TANGENT_TOL_DEG:
                    seen.setdefault(round(record_tangent_az, 4), m)
            if len(seen) == 1:
                ((tangent_az, m),) = seen.items()
                end_candidates[end] = _pick_by_drawn_chord([(tangent_az + delta / 2) % 360, (tangent_az - delta / 2) % 360], drawn_chord_az)
                end_donor[end] = m
                end_source[end] = f"tangent to {m['src']}"
            elif not seen and radials:
                # loop16 leg F: no record LINE meets this end tangentially -- try a printed radial
                # bearing at this end instead. A radial line's own direction is ambiguous by 180 deg
                # (like any bearing), so it gives two candidate TANGENT directions here (+/- 90 deg);
                # only one sitting within TANGENT_TOL_DEG of the curve's own drawn tangent counts as
                # "this radial, resolved" -- never both, and never a radial whose node point doesn't
                # actually sit at this end.
                node_pt = e["p0"] if end == 0 else e["p1"]
                rseen = {}
                for r in radials:
                    if np.hypot(*(r["point"] - node_pt)) >= NODE:
                        continue
                    for cand_az in ((r["az"] + 90) % 360, (r["az"] - 90) % 360):
                        # direct undirected difference -- unlike the line donor above, a rotated
                        # radial candidate already names the "into the curve" tangent direction
                        # itself (no separate "departing the node" direction to flip past), so it
                        # should agree with arc_tangent_az near-exactly, not near a 180 deg reversal
                        deflect = abs((cand_az - arc_tangent_az + 180) % 360 - 180)
                        if deflect <= TANGENT_TOL_DEG:
                            rseen.setdefault(round(cand_az, 4), r)
                if len(rseen) == 1:
                    ((tangent_az, r),) = rseen.items()
                    end_candidates[end] = _pick_by_drawn_chord([(tangent_az + delta / 2) % 360, (tangent_az - delta / 2) % 360], drawn_chord_az)
                    stub = node_pt + 30.0 * np.array([math.sin(math.radians(r["az"])), math.cos(math.radians(r["az"]))])
                    end_donor[end] = {"p0": node_pt, "p1": stub, "region": r.get("region"), "src": r["printed"]}
                    end_source[end] = f"radial {r['printed']}"

        if not end_candidates:
            continue
        if len(end_candidates) == 2:
            a0, a1 = end_candidates[0], end_candidates[1]
            if abs((a0 - a1 + 180) % 360 - 180) > TANGENT_TOL_DEG * 2:
                continue  # both ends found a donor but they disagree: ambiguous, refuse (not guessed)
        end, az = next(iter(end_candidates.items()))
        e["az"] = az
        e["chord_source"] = end_source[end]
        e["chord_source_edge"] = end_donor[end]  # direct reference, for a crop script (loop16-D's own pattern)
        filled += 1
    return filled


COCURVE_CENTER_TOL_FT = 5.0  # ft: how far apart two arc edges' own least-squares-fit centres may sit
# and still count as the same physical drawn circle.
COCURVE_RADIUS_TOL_FT = 2.0  # ft: same, for the fitted radii. Both must hold (a concentric-but-
# different-radius pair -- two parallel R/W lines offset a fixed distance apart share a centre but are
# NOT the same course) -- radius is the one that actually separates them. Measured (loop17 leg D):
# R-10741.1's genuine compound-curve pair ("L=660.20'" the whole curve, "R=1169.90' L=319.73'" its own
# printed sub-total, same drawn stroke) fits at 0.17 ft centre / 0.22 ft radius apart; Presidio's
# "L=269.94'"/"C4" (already the same curve under two record names) at 0.05/0.03 ft. The nearest
# different-curve pairs found scanning every arc on the 6 gate sheets: r10434_1 "L=132.85'"/"L=170.24'"
# at 1.17/4.91 ft (radius already clears this cutoff 2.4x), r10434_3 "L=344.50'"/"L=415.25'" at a
# deceptively close 0.20 ft centre (two DIFFERENT curves that happen to be concentric) but 9.85 ft
# radius apart (4.9x clear). Radius tolerance carries the real margin; centre tolerance is generous
# because no false pair measured needed it tighter.


def share_curve_radius(edges, scale):
    """Loop17 leg D: a compound curve is sometimes printed as more than one R/delta/L block along the
    SAME drawn stroke -- the whole curve's own total (R, its full delta, its full L) and, beside it, a
    sub-total for part of that same curve (delta and L only, no R printed a second time -- R-10741.1's
    "R=1169.90' delta=32d20'00" L=660.20'" for the whole curve, "delta=15d39'31" L=319.73'" for its own
    printed sub-total). complete_curve_chords() (and the L=R*theta identity generally) needs R on every
    row; a row with delta or L but no R currently stays flagged "chord direction from drawing" forever,
    however good its own delta/L record is, because nothing ever gave it a radius to pair them with.
    checks.py/build_edges never join these two blocks (different printed blocks, not one annotation --
    normalize_quotes/own_block_has_bearing's whole-block-region test does not apply to curve data), so
    the only evidence that they are the same curve is geometric: their own drawn "pts" fit the same
    circle (COCURVE_CENTER_TOL_FT/COCURVE_RADIUS_TOL_FT -- see those constants' own measured margins).
    Never borrows across an ambiguous pair: if more than one candidate donor passes and their own R
    values disagree by more than COCURVE_RADIUS_TOL_FT, the row is left alone (refused, not guessed) --
    same discipline inherit_bearings/complete_curve_chords already use for a disagreeing neighbour.
    Sets "R" and "R_source" (the donor's own src, for a crop script) on a completed row; mutates edges
    in place. Returns the count filled. Must run before complete_curve_chords (which requires "R")."""
    def fit(e):
        pts = np.array(e["pts"], float)
        if len(pts) < 3:
            return None
        try:
            return fit_circle_lsq(pts)
        except Exception:
            return None

    donors = []
    for e in edges:
        if e["kind"] == "arc" and "R" in e and not e.get("impossible"):
            fitted = fit(e)
            if fitted is not None:
                donors.append((e, *fitted))

    filled = 0
    for e in edges:
        if e["kind"] != "arc" or "R" in e or e.get("impossible") or ("delta" not in e and "L" not in e):
            continue
        fitted = fit(e)
        if fitted is None:
            continue
        c, r = fitted
        matches = []
        for de, dc, dr in donors:
            if de is e:
                continue
            cd = float(np.hypot(*(c - dc))) * scale
            rd = abs(r - dr) * scale
            if cd <= COCURVE_CENTER_TOL_FT and rd <= COCURVE_RADIUS_TOL_FT:
                matches.append((cd, de))
        if not matches:
            continue
        r_values = {round(de["R"], 2) for _, de in matches}
        if len(r_values) > 1:
            continue  # disagreeing donors: ambiguous, refused
        _, donor = min(matches, key=lambda m: m[0])
        e["R"] = donor["R"]
        e["R_source"] = f"shared from co-curved {donor['src']}"
        e["R_source_edge"] = donor
        filled += 1
    return filled


def record_vector_misfit(p, q, az, d):
    """Loop17 leg A: one edge's own record vector (compass az, distance d) walked from ITS OWN drawn
    start p, checked against its own drawn end q -- never a chain's carried position. walk() used to
    accumulate a single running position across a whole chain and compare THAT to each node in turn,
    so one bad upstream edge (a misread digit, a wrong association, a merged pair of pieces) put every
    clean downstream edge's misfit at the same inflated number, even though each of those edges' own
    record vector matches its own drawn piece exactly -- measured on R-10741.1: "165.86'" (no record
    bearing, own error ~5.9 ft) sat upstream of two edges whose own bearing+distance match their own
    drawn piece within 0.07/0.09 ft, yet the old cumulative misfit read 6.96/8.36 ft for them, landing
    2,021 ft of otherwise-clean boundary in recon_attrib's "misfit" bucket as guilt by association.
    Returns (end, misfit_ft) so a caller can still accumulate its own running position for a
    whole-chain closure diagnostic (misfit_end_ft/misfit_max_ft) alongside this per-edge measure."""
    end = p + d * np.array([math.sin(math.radians(az)), math.cos(math.radians(az))])
    return end, float(np.hypot(*(end - q)))


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

    # complete_curve_chords (loop16 leg E): a synthetic PC/PT case -- a record line heading due north
    # (az 0) meets, tangentially, a 90 deg-delta R=100 curve turning right (clockwise) into a curve
    # heading due east by its far end. A quarter circle centred (100,0): p0 (0,0) is 180 deg off centre,
    # p1 (100,100) is 90 deg off -- so its own drawn tangent at p0 is due north (matches the line
    # exactly) and at p1 is due east, and its own drawn chord (0,0)->(100,100) is az 45 -- the textbook
    # tangent +/- delta/2 = 0 + 45 = 45 (picked over 0 - 45 = -45/315 by the drawn chord).
    def az_id(p, q):
        d = q - p
        return math.degrees(math.atan2(d[0], d[1])) % 360

    t = np.linspace(0.0, 1.0, 21)
    angle = np.radians(180.0 - 90.0 * t)
    center = np.array([100.0, 0.0])
    quarter = center + 100.0 * np.c_[np.cos(angle), np.sin(angle)]
    assert np.hypot(*(quarter[0] - [0.0, 0.0])) < 1e-6 and np.hypot(*(quarter[-1] - [100.0, 100.0])) < 1e-6

    def curve_edges(extra=()):
        e_line = {"kind": "line", "p0": np.array([0.0, -100.0]), "p1": np.array([0.0, 0.0]), "az": 0.0, "ft": 100.0,
                  "flags": [], "impossible": False, "n0": 10, "n1": 11, "src": "record L north", "chord_label": False}
        e_arc = {"kind": "arc", "p0": quarter[0].copy(), "p1": quarter[-1].copy(), "pts": quarter.copy(), "R": 100.0,
                 "delta": 90.0, "flags": [], "impossible": False, "n0": 11, "n1": 12, "src": "C1", "chord_label": False}
        edges = [e_line, e_arc, *extra]
        adj = {}
        for k, e in enumerate(edges):
            adj.setdefault(e["n0"], []).append(k)
            adj.setdefault(e["n1"], []).append(k)
        return edges, adj

    edges_t, adj_t = curve_edges()
    n_t = complete_curve_chords(edges_t, adj_t, az_id)
    assert n_t == 1
    assert abs(edges_t[1]["az"] - 45.0) < 0.5, f"tangent-curve chord az should be ~45 (tangent 0 + delta/2 45), got {edges_t[1]['az']}"
    assert edges_t[1]["chord_source"].startswith("tangent to"), edges_t[1].get("chord_source")

    # CB beats tangent: a chord-label straight edge sharing BOTH the arc's own nodes (11, 12) -- as
    # checks.py's chord_bearing() places one, endpoints on the curve's own matched piece -- wins over
    # the (still-valid) tangent donor above.
    cb_edge = {"kind": "line", "p0": quarter[0].copy(), "p1": quarter[-1].copy(), "az": 46.0, "ft": 141.4,
               "flags": [], "impossible": False, "n0": 11, "n1": 12, "src": "N46E chord label", "chord_label": True}
    edges_cb, adj_cb = curve_edges(extra=[cb_edge])
    n_cb = complete_curve_chords(edges_cb, adj_cb, az_id)
    assert n_cb == 1
    assert abs(edges_cb[1]["az"] - 46.0) < 1e-6, "a printed chord bearing must win over a tangent-derived one"
    assert edges_cb[1]["chord_source"] == "CB"

    # two disagreeing tangent donors at the SAME end: ambiguous, refused (not guessed) -- same rule
    # inherit_bearings() already applies to a disagreeing collinear straight-line neighbour.
    donor2 = {"kind": "line", "p0": np.array([0.0, -100.0]), "p1": np.array([0.0, 0.0]), "az": 30.0, "ft": 100.0,
              "flags": [], "impossible": False, "n0": 13, "n1": 11, "src": "record L2 disagreeing", "chord_label": False}
    edges_amb, adj_amb = curve_edges(extra=[donor2])
    n_amb = complete_curve_chords(edges_amb, adj_amb, az_id)
    assert n_amb == 0 and "az" not in edges_amb[1], "two disagreeing tangent donors at one node must refuse, not guess"

    # loop16 leg F: radial source, no adjoining record LINE at all -- just the arc and a printed
    # radial at node 11 (0,0). The radial line points from the PC to the curve's own centre (100,0),
    # i.e. due east (az 90); rotating +/-90 gives 180 or 0 -- only 0 matches the curve's own drawn
    # tangent there (established above), so chord az = 0 +/- 45, drawn-chord-picked to 45, exactly
    # the tangent-line result, with no line donor present to produce it.
    e_arc_only = {"kind": "arc", "p0": quarter[0].copy(), "p1": quarter[-1].copy(), "pts": quarter.copy(), "R": 100.0,
                  "delta": 90.0, "flags": [], "impossible": False, "n0": 11, "n1": 12, "src": "C1", "chord_label": False}
    adj_only = {11: [0], 12: [0]}
    radial = {"point": np.array([0.0, 0.0]), "az": 90.0, "printed": 'N90d00m00sE(R)', "region": [0, 0, 1, 1]}
    n_rad = complete_curve_chords([e_arc_only], adj_only, az_id, [radial])
    assert n_rad == 1 and abs(e_arc_only["az"] - 45.0) < 0.5, f"radial-sourced chord az should be ~45, got {e_arc_only.get('az')}"
    assert e_arc_only["chord_source"] == "radial N90d00m00sE(R)"
    # a radial too far from this end's own drawn tangent (neither +90 nor -90 candidate within
    # TANGENT_TOL_DEG) must refuse, not attach to the wrong end/curve
    e_arc_far = {"kind": "arc", "p0": quarter[0].copy(), "p1": quarter[-1].copy(), "pts": quarter.copy(), "R": 100.0,
                 "delta": 90.0, "flags": [], "impossible": False, "n0": 11, "n1": 12, "src": "C1", "chord_label": False}
    far_radial = {"point": np.array([0.0, 0.0]), "az": 45.0, "printed": "far off", "region": [0, 0, 1, 1]}
    n_far = complete_curve_chords([e_arc_far], adj_only, az_id, [far_radial])
    assert n_far == 0 and "az" not in e_arc_far, "a radial whose +/-90 candidates both miss the drawn tangent must refuse"
    print("traverse.selftest: complete_curve_chords OK (tangent chord az = tangent +/- delta/2 on a synthetic 90 deg curve; "
          "CB wins over tangent; disagreeing tangent donors refuse rather than guess; a radial fills the same way "
          "when no record line donates, and refuses when it doesn't match the drawn tangent)")

    # loop17 leg D: share_curve_radius -- a sub-piece of the SAME drawn circle (quarter's own first
    # half, t 0..0.5: still centred (100,0), R=100) printed with its own delta/L but no R must take R
    # from the full-curve donor above; a sub-piece of a DIFFERENT circle must not, and two disagreeing
    # donors must refuse rather than guess (same discipline as inherit_bearings/complete_curve_chords).
    half = center + 100.0 * np.c_[np.cos(angle[:11]), np.sin(angle[:11])]  # t 0..0.5 of the same quarter
    e_full = {"kind": "arc", "p0": quarter[0].copy(), "p1": quarter[-1].copy(), "pts": quarter.copy(), "R": 100.0,
              "delta": 90.0, "flags": [], "impossible": False, "n0": 11, "n1": 12, "src": "whole curve"}
    e_sub = {"kind": "arc", "p0": half[0].copy(), "p1": half[-1].copy(), "pts": half.copy(),
             "delta": 45.0, "flags": [], "impossible": False, "n0": 11, "n1": 20, "src": "sub-total"}
    n_shared = share_curve_radius([e_full, e_sub], scale=1.0)
    assert n_shared == 1 and e_sub.get("R") == 100.0, f"sub-piece of the same circle must take R from the donor: {e_sub.get('R')}"
    assert e_sub["R_source"] == "shared from co-curved whole curve"

    # a differently-centred circle's own delta/L-only piece must not borrow a nearby-but-different R
    other_center = np.array([100.0, 500.0])  # far enough that neither centre nor radius tolerance can reach
    other = other_center + 40.0 * np.c_[np.cos(angle[:11]), np.sin(angle[:11])]
    e_other = {"kind": "arc", "p0": other[0].copy(), "p1": other[-1].copy(), "pts": other.copy(),
               "delta": 45.0, "flags": [], "impossible": False, "n0": 30, "n1": 31, "src": "unrelated"}
    n_none = share_curve_radius([e_full, e_other], scale=1.0)
    assert n_none == 0 and "R" not in e_other, "an unrelated circle's own piece must never borrow R by proximity alone"

    # two donors that disagree on R: refused, not guessed
    e_full2 = {**e_full, "R": 250.0, "src": "disagreeing whole curve"}
    e_sub2 = {"kind": "arc", "p0": half[0].copy(), "p1": half[-1].copy(), "pts": half.copy(),
              "delta": 45.0, "flags": [], "impossible": False, "n0": 11, "n1": 20, "src": "sub-total 2"}
    n_amb2 = share_curve_radius([e_full, e_full2, e_sub2], scale=1.0)
    assert n_amb2 == 0 and "R" not in e_sub2, "disagreeing co-curved donors must refuse, not average or guess"
    print("traverse.selftest: share_curve_radius OK (a same-circle sub-piece takes R from its whole-curve "
          "donor; an unrelated circle never borrows one; disagreeing donors refuse)")

    # loop17 leg A: record_vector_misfit re-anchors each edge's own misfit at its own drawn start, so
    # a bad upstream edge cannot poison a clean downstream one. Synthetic chain along the record
    # north: edge0 (0,0)->(0,100), record az=0 ft=100, exact match. edge1 (0,100)->(0,250), record
    # az=0 but ft=140 -- 10 ft short of its own drawn piece (a misread/wrong-association/merge, the
    # cause doesn't matter here, only that it is wrong). edge2 (0,250)->(0,400), record az=0 ft=150,
    # exact match to ITS OWN drawn piece. Walking a single carried position (the old bug) would read
    # edge2's misfit as ~10 ft, the same as edge1's own error; re-anchored, edge2 must read ~0.
    p0, p1, p2, p3 = (np.array([0.0, 0.0]), np.array([0.0, 100.0]), np.array([0.0, 250.0]), np.array([0.0, 400.0]))
    pos = p0.copy()
    own = []
    for p, q, az, d in [(p0, p1, 0.0, 100.0), (p1, p2, 0.0, 140.0), (p2, p3, 0.0, 150.0)]:
        end, mis = record_vector_misfit(p, q, az, d)
        own.append(mis)
        pos = pos + (end - p)
    assert own[0] < 0.01, own
    assert abs(own[1] - 10.0) < 0.01, f"edge1 is the true introducer, expected ~10 ft, got {own}"
    assert own[2] < 0.01, f"edge2 must be judged on its own drawn piece, not the chain's carried position: {own}"
    chain_end_mis = float(np.hypot(*(pos - p3)))
    assert abs(chain_end_mis - 10.0) < 0.01, "chain-level cumulative diagnostic (misfit_end_ft) must still show the carried error"
    print("traverse.selftest: record_vector_misfit OK (edge2 unpoisoned by edge1's own 10 ft error; "
          "chain-level closure diagnostic still shows it)")


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
             "region": tuple(x["region"]) if x.get("region") else None,
             # loop16 leg E: a printed chord bearing/distance's OWN "line" is the curve's own matched
             # piece's endpoints (checks.chord_bearing/chord_span), so it lands on the SAME node pair
             # as its arc edge once node-clustered -- complete_curve_chords() finds it by that pairing,
             # never by treating it as an ordinary adjoining record course.
             "chord_label": x["kind"] in ("chord bearing", "chord distance")}
        if x["kind"] in ("bearing", "chord bearing"):  # a chord is the straight edge between an arc's ends (loop 6 leg C)
            e["az"] = x["az"]
        elif x["kind"] in ("distance", "chord distance"):
            e["ft"] = x["ft"]
            e["own_bearing_nearby"] = own_block_has_bearing(e["region"], bearing_regions)
        else:
            e["L"] = x["ft"]
            # loop16 leg F: an inline (non-table) curve label's own R and delta, when checks.py's joined
            # R=/A=/L= block match found and checked them (labels.json's "R"/"delta" on an "arc" kind
            # entry) -- same fields a tag_labels.json table curve row already carries below, so
            # complete_curve_chords() (which only ever looks for "R"/"delta"/"L") treats either source
            # identically, never needing to know which one it came from.
            if "R" in x:
                e["R"] = x["R"]
            if "delta" in x:
                e["delta"] = x["delta"]
        edges.append(e)
    for x in json.loads((OUT / "tag_labels.json").read_text(encoding="utf-8")) if (OUT / "tag_labels.json").exists() else []:
        P = np.array(x["line"], float)
        e = {"src": x["tag"], "kind": "arc" if x["kind"] == "curve" else "line", "p0": P[0], "p1": P[-1], "pts": P, "flags": [],
             "region": None, "chord_label": False}
        if x["kind"] == "line":
            e["az"] = x["az"]
            if not x["total"]:
                e["ft"] = x["dist"]
        else:
            e["R"], e["L"] = x["R"], x["L"]
            if "delta" in x:  # loop16 leg E: printed delta (degrees) straight off the curve table row,
                e["delta"] = x["delta"]  # preferred over L/R (deriving it back from L would just
                # reintroduce L's own rounding); still falls back to L/R when a row has no delta cell
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
                m["chord_label"] = m.get("chord_label", False) or e.get("chord_label", False)
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
                for k in ("az", "ft", "R", "L", "delta"):
                    if k in e and k not in m:
                        m[k] = e[k]
                m["own_bearing_nearby"] = m.get("own_bearing_nearby", False) or e.get("own_bearing_nearby", False)
                m["chord_label"] = m.get("chord_label", False) or e.get("chord_label", False)
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


def load_radials():
    """Loop16 leg F: checks.py's radials.json (printed "(R)" bearings, each paired with the curve end
    it sits beside) as complete_curve_chords()'s third source -- "point" converted to np.array once
    here so every caller (main() and legE_crops.py's own build_graph()) gets the same shape without
    re-parsing. Sheet pt, same frame as every edge's own p0/p1 (see build_edges)."""
    p = OUT / "radials.json"
    if not p.exists():
        return []
    return [{**r, "point": np.array(r["point"], float)} for r in json.loads(p.read_text(encoding="utf-8"))]


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

    n_radius_shared = share_curve_radius(edges, scale)
    if n_radius_shared:
        print(f"loop17-D radius sharing: {n_radius_shared} curve edge(s) took their radius from a co-curved donor's own R")

    n_curve_chords = complete_curve_chords(edges, adj, azimuth, load_radials())
    if n_curve_chords:
        print(f"loop16-E/F curve chord completion: {n_curve_chords} curve edge(s) took their chord direction from the record (CB, a tangent record line, or a radial bearing)")

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
        """Positions by the record from the first drawn vertex, for the chain-level closure diagnostic
        (misfit_end_ft/misfit_max_ft: how far the whole record walk drifts from the drawing by the far
        end). Each row's own misfit_ft (loop17 leg A, record_vector_misfit()) is judged separately,
        re-anchored at THAT edge's own drawn start -- never the chain's carried position -- so one bad
        upstream edge cannot poison every clean downstream edge's misfit (see record_vector_misfit)."""
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
                if "az" in e:  # loop16-E: chord direction from the record (CB, a tangent record line, or leg F's radial)
                    az = e["az"] if abs((e["az"] - drawn_az + 180) % 360 - 180) < 90 else (e["az"] + 180) % 360
                else:
                    az = drawn_az; flags.append("chord direction from drawing")
                if "R" in e and "L" in e and "az" in e:
                    # loop16 leg F: the record chord LENGTH (2R sin(delta/2)) is only a distance IN
                    # the record chord's own direction -- pairing it with a drawing-sourced direction
                    # (the "else" just above, no record az) walks the wrong distance the wrong way and
                    # can badly misplace every downstream edge of the chain. Measured: r10434_3's
                    # "R=611.95' L=537.96'" (ok=False on its own arc-length check -- its printed
                    # R/delta/L are self-consistent with EACH OTHER, per DELTA_CONSISTENCY_TOL_DEG, but
                    # not with the drawn piece they are attached to) misplaced a 9-edge open chain by
                    # 18.41 ft here, costing recon_all 281 ft on that sheet before this guard. R/L is
                    # only ever trusted for a distance once the record ALSO gave this row a direction.
                    d = 2 * e["R"] * math.sin(e["L"] / e["R"] / 2)
                elif "R" in e and "L" in e:
                    d = float(np.hypot(*(ground(q) - ground(p)))); flags.append("R/L printed, no record chord direction")
                elif "L" in e:
                    d = float(np.hypot(*(ground(q) - ground(p)))); flags.append("chord from drawing (no radius)")
                else:
                    d = float(np.hypot(*(ground(q) - ground(p)))); flags.append("no record")
            own_end, own_mis = record_vector_misfit(ground(p), ground(q), az, d)
            pos = pos + (own_end - ground(p))  # same displacement, chain's carried start (unchanged)
            chain_mis = float(np.hypot(*(pos - ground(q))))
            misfits.append(chain_mis)
            row = {"edge": e["src"], "kind": e["kind"], "az": round(az, 4), "ft": round(d, 2), "misfit_ft": round(own_mis, 2),
                   "chain_misfit_ft": round(chain_mis, 2), "flags": flags,
                   "E": round(float(pos[0]), 2), "N": round(float(pos[1]), 2),
                   "pts": [[round(float(gp[0]), 2), round(float(gp[1]), 2)] for gp in (ground(pt) for pt in e["pts"])]}
            if "bearing_source" in e:  # loop16-D: this edge's az came from a collinear record neighbour, not the drawing
                row["bearing_source"] = e["bearing_source"]
            if "chord_source" in e:  # loop16-E: this curve's chord az came from the record, not the drawing
                row["chord_source"] = e["chord_source"]
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
