"""How much of the survey is reconstructable: the record's own reach over the drawn boundary,
measured geometrically (not by summing record feet -- a record sum double counts shared lines and
can sit off the boundary it is supposed to describe).

Definitions (loop16 leg A, retry):
- drawn boundary: unary_union of (every face's exterior in parcels.geojson) UNION (the sheet's own
  R/W-weight linework, ground ft -- measured on R-10741.1: its 9 clean record edges sit exactly on
  the 1.68 pt R/W linework, but that linework is not part of any face parcels.py polygonised on this
  sheet, so the union must add it back in directly, not just read it off the faces), MINUS five
  contamination classes (removed_ft in the output, each also asserted not to delete a clean record
  edge's own covered stretch):
    frame       - the map-area border rectangle (overlay.MAP_AREA, FRAME_TOL_PT) and the sheet's own
                  title-block/general-notes furniture boxes (frame.json "furniture").
    tables      - annotation-table bounding boxes: tables.json "_regions" (the L#/C# curve/line
                  tables read_shx.py --tables builds) plus checks.alignment_table_regions,
                  checks.line_curve_table_regions, point_table_regions (a POINT/NORTHING/EASTING
                  coordinates table -- alignment_table_regions only anchors on STATION, so Presidio's
                  and R-10434.3's COORDINATES TABLE got no region at all) and radial_table_regions (a
                  RADIAL LINE TABLE's own R-# NO. column -- checks.line_curve_table_regions's NO_TAG_RE
                  only matches an L or C prefix), every box grown by TABLE_REGION_GROW_PT (loop16 leg A3:
                  a table's own region sits snug around its data rows, short of its title bar/frame
                  stroke by 10-25 pt, measured on Presidio), PLUS unnamed faces isolated
                  (TABLE_ISOLATION_FT) from both the R/W linework and every named face's own boundary --
                  R-10741.1's AREAS/GRANTOR table has no NO.-column tags at all (tables.json._regions is
                  empty there) but still noded into ~700-1100 ft-from-R/W grid-cell faces (measured);
                  this heuristic catches those a region-box detector never sees. A table region also
                  excludes any R/W-weight stroke it contains from the R/W class itself (weighted, before
                  rw_P/rw_Q) -- defensive; no sheet measured actually put a table frame on the R/W
                  weight class. ponytail: isolation, not a real table parser -- upgrade if a real small
                  corridor sliver ever needs to sit that far from both.
    matchline   - checks.py's own "line runs to the sheet edge" heuristic (pt x < 262 or > W-50),
                  reused verbatim rather than re-derived.
    leader_wedge- checks.leaders()'s curly stroked paths to an arrowhead/circle (start-tip line,
                  buffered LEADER_TOL_PT): a leader at the parcel/easement 0.84 pt weight noded into a
                  face becomes a spurious wedge sticking out toward its number box. PLUS (loop16 leg A3)
                  a long straight/wedge leader off a parcel/deed label (PARCEL_DEED_RE, e.g.
                  "063269-X1-X1") that checks.leaders() misses on both its tests -- no arrowhead/circle
                  within 7 pt of its tip, and/or over its 120 pt length cap: a weighted() stroke at this
                  drafter's 1.02 pt leader/lettering weight, anchored (LABEL_ANCHOR_TOL_PT) to a
                  parcel/deed label's own box and reaching well beyond it (LEADER_REACH_MIN_PT, to tell
                  a real wedge apart from the label's own drawn box outline or glyph strokes), and not
                  collinear with the R/W class over a majority of its own densified length (protects a
                  real long R/W edge that happens to end near a label, e.g. R-10434.3's R/W corner at
                  PARCEL 1 46825).
    edge_column - ponytail heuristic: near-vertical segments within EDGE_COL_TOL_PT of MAP_AREA's own
                  left/right edge -- a parallel column line just inside the true border that
                  FRAME_TOL_PT's tight (~1 pt) tolerance does not reach. Upgrade to a real per-sheet
                  detector if this proves too broad or too narrow on a sheet.
    titleblock  - loop18 leg 1: recon_ceiling.py's own ceiling class (e), at the source -- a title-
                  block/legend/notes boilerplate region (TITLEBLOCK_RE) whose own table-grid linework
                  got noded into a face the same way TABLE_ISOLATION_FT's debris faces do, but sits
                  close enough to real R/W or named-face boundary that the isolation distance test
                  above never caught it (measured: R-10434.1, 1,493 ft).
    wedge_residual - loop18 leg 1: recon_ceiling's own ceiling class (e), the rest of it -- (a) a
                  chained run of elementary segments whose own direction nearly reverses
                  (wedge_spike_mask(), BEND_CONTAM_DEG: a real boundary course never walks backward on
                  itself) and (b) PRESIDIO_CONTAM_PT, a hand-measured point list of leader wedges that
                  converge on a label rather than running parallel to the corridor (recon_attrib.py's
                  own crop evidence) that recon.py's own leader_wedge class above still misses.
  Removal order is frame -> tables -> titleblock -> matchline -> leader_wedge -> wedge_residual ->
  edge_column (a segment already claimed by an earlier class is not reconsidered, so overlapping
  regions attribute to the first class that touches them, not double-counted).
- reconstructed edge: a traverse.json row with kind in ("line", "arc"), flags == [] and misfit_ft <=
  0.5. misfit_ft (loop17 leg A, traverse.record_vector_misfit()) is this edge's OWN record vector
  (bearing/chord az + distance) walked from ITS OWN drawn start and checked against its own drawn
  end -- never a chain-cumulative position. traverse.py's walk() used to carry one running position
  across a whole chain and compare that to each node, so a single bad upstream edge (misread digit,
  wrong association, a merged pair of pieces) inflated every clean downstream edge's misfit too,
  disqualifying otherwise-reconstructable boundary as guilt by association (2,021 ft of it, measured
  on the six gate sheets before this leg). traverse.json also carries a chain-level chain_misfit_ft
  per row and misfit_end_ft/misfit_max_ft per chain -- the old cumulative measure, kept only as a
  whole-record closure diagnostic (how far the chain's own walk drifts from the drawing by its far
  end); recon.py never reads either, by design: a parcel's own closure is measured independently by
  face_closure() below, per named face, not by traverse.py's open-ended chain walk.
  A curve used to always carry the flag "chord direction from drawing" (traverse.py used to
  always derive a curve's chord direction from the drawing, never the record), so flags == [] never
  held for one; loop16 leg E gives a curve its chord direction from the record where the record
  determines it (a printed chord bearing, or a record line meeting it tangentially at a shared node --
  see traverse.complete_curve_chords()), so a curve with a record radius/delta and a record-sourced
  chord direction can be a reconstructed edge too, exactly like a line. A curve still missing R/delta,
  or one whose only candidate record tangents disagree, keeps its flag and does not qualify.
- covered boundary: drawn-boundary length that lies within BUFFER_FT of a reconstructed edge's own
  drawn geometry (traverse.py's additive "pts" field) AND whose local direction is within
  PARALLEL_TOL_DEG of that edge's azimuth, mod 180 (so a crossing line, or a second line drawn
  parallel a few feet off, does not count). For a line the "geometry" and its one azimuth are the
  whole edge (chord IS the edge); for an arc (loop16 leg E) coverage follows the CURVE, not the chord:
  rec_segments() breaks the row's own drawn "pts" into consecutive small pieces, each compared by its
  own LOCAL direction (mod 180) -- a single overall chord azimuth would only agree with the drawing
  near an arc's own midpoint and miss the rest of a real curve. Each boundary foot is counted once
  even when two edges' buffers overlap it (segments are classified "covered" or not, not summed per
  edge).
- dimensioned boundary: the boundary the record actually describes -- (i) the sheet's heaviest
  *substantial* weight-class linework (R/W lines: on Presidio that is the 1.98 pt class; heavy_lines()
  already folds R/W and the 0.84 pt parcel/easement class together, so recon.py re-derives the
  per-line weight to split them). Refined from "heaviest class" alone after checking R-10741.1: its
  numerically heaviest class was 1 stray stroke, 118 ft (a titleblock/border artifact), while the real
  R/W class -- 1.68 pt, 8 lines, 12,253 ft, the same weight its sibling sheets R-10741.2/.3 use -- sat
  one step down. A class must clear RW_MIN_COUNT lines and RW_MIN_FT total length to be considered R/W.
  Within RW_TOL_FT of a drawn-boundary point, OR (ii) any point that is part of a named face's
  (properties.parcel non-empty) own boundary, within NAMED_TOL_FT (near-zero: the same coordinates,
  not independently drawn linework). Denominator for recon_dim is drawn-boundary length inside that
  set.
- parcels reconstructed: a face counts when >= 99% of its own boundary length is covered (a face
  touching the frame is excluded outright -- its boundary is partly the border, not a record edge)
  AND the record walk around it, built only from reconstructed edges (bearing flipped 180 deg where
  it opposes the ring's own walk direction, exactly as traverse.py's own per-figure walk does; the
  <1% uncovered remainder falls back to the drawn vector, same fallback traverse.py uses for a piece
  with no record), closes within 1 ft. Faces the table/furniture isolation heuristic drops never enter
  this count either (they are not parcel candidates).

usage: [SHEET=<pdf>] python spike/recon.py   (after parcels.py and traverse.py)
       python spike/recon.py --no-inverse    (loop18 leg 2: recon_no_inverse.json/recon_segments_no_
                                               inverse.json, excluding any "by inverse ..." traverse row)
       python spike/recon.py --selftest
Env override (read once at import; unset = today's default 0.5 ft): CT_MISFIT_FT replaces load_rec_edges()'s
clean-edge misfit bar. CLOSURE_MAX_FT (face closure, already 1.0 ft) is not overridable -- JR's 2026-09-29
"increase to a full foot" what-if left it alone (loop19-tol1 bench: CT_MISFIT_FT=1.0).
"""
import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
import shapely

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, DEFAULT, READS, real_text_blocks, segments as georef_segments  # noqa: E402
from overlay import MAP_AREA, bezier  # noqa: E402
from checks import leaders as checks_leaders, alignment_table_regions, line_curve_table_regions, label_box  # noqa: E402

BUFFER_PT = 1.5          # pt-equivalent: main coverage buffer around a reconstructed edge
PARALLEL_TOL_DEG = 20.0  # mod 180: how far a boundary segment's direction may stray from the edge's own
RW_TOL_PT = 3.0          # pt-equivalent: how close a boundary point must sit to the heaviest weight class
RW_MIN_COUNT = 2         # a weight class needs at least this many strokes to be R/W, not a stray artifact
RW_MIN_FT = 1000.0       # and at least this much total length (R-10741.1's 2.28 pt "class" is 1 line, 118 ft;
                         # loop16 leg A retry: raised from 500 -- the real R/W classes measured (1.68/1.98 pt)
                         # all clear 12,000+ ft, so 1000 still passes them with headroom while rejecting more
                         # marginal stray-stroke "classes" than 500 did)
NAMED_TOL_FT = 1.0       # ft: a boundary point counts as "on a named face" only if it is (near) that face's own vertices
FRAME_TOL_PT = 1.0       # pt-equivalent: how close to the map-area frame counts as "on the frame"
TABLE_ISOLATION_FT = 150.0  # ft: an unnamed face this far from BOTH the R/W linework and every named face's
                             # own boundary is table/furniture debris, not a parcel candidate (measured: R-10741.1's
                             # AREAS-table grid faces sit 692-1135 ft from R/W; its real small faces sit <= 114 ft)
MATCHLINE_X0_PT = 262.0     # pt: checks.py's own "line runs to the sheet edge (matchline)" cutoffs, reused verbatim
MATCHLINE_MARGIN_PT = 50.0
LEADER_TOL_PT = 4.0         # pt-equivalent: buffer around a leader's start-tip line for the leader_wedge class
EDGE_COL_TOL_PT = 10.0      # pt: how close to MAP_AREA's own left/right edge counts as the edge_column class
EDGE_COL_ANGLE_DEG = 10.0   # deg off vertical (mod 180) still counted as a "column" line
TABLE_REGION_GROW_PT = 30.0  # pt: every table region box (tables.json._regions / alignment_table_regions /
                              # line_curve_table_regions / point_table_regions) sits snug around the table's own
                              # data rows and undershoots its title bar and outer frame stroke -- measured on
                              # Presidio's CURVE DATA TABLE(1): its title text top sits at y=979, its
                              # tables.json region top at y=1004, a 25 pt gap the frame stroke sits inside of.
                              # Grown on all four sides so the frame itself always falls inside the region.
PARCEL_DEED_RE = re.compile(r"^(DK-)?\d{5,6}(-X\d){1,2}$")  # a parcel/deed label like "063269-X1-X1" or
                                                              # "DK-046825-X1-X1" -- the labels loop16 leg A2's
                                                              # long straight/wedge leaders originate from
LEADER_W_LO, LEADER_W_HI = 0.95, 1.05  # pt: this drafter's leader/lettering stroke weight (checks.leaders()'s
                                        # own docstring: "the same 1.02 weight as the lettering") -- distinct
                                        # from the 0.84 pt parcel/easement boundary weight, so a real long
                                        # boundary edge that happens to end near a label (measured: R-10434.3's
                                        # R/W corner at PARCEL 1 46825, 1.98/0.84 pt) is never caught by this class
LABEL_ANCHOR_TOL_PT = 30.0   # pt: how close a candidate leader stroke's own endpoint must sit to a parcel/deed
                              # label's box (checks.label_box) to count as anchored to it
LEADER_REACH_MIN_PT = 100.0  # pt: how far beyond the label's own centre the stroke's farthest vertex must still
                              # reach -- separates a real long leader/wedge from the label's own drawn box
                              # outline or character strokes (measured: Presidio's genuine wedges reach 160-300 pt
                              # from the label centre; its box-outline sides and glyph strokes never exceed ~80 pt)
DUP_TOL_PT = 1.0         # pt-equivalent: how close two elementary segments' own midpoints (point-to-
                          # segment) may sit and still count as the SAME physically-drawn line (loop16
                          # leg C: an R/W stroke and a face edge, or two faces' own edges, drawn a hair
                          # apart but not bit-identical, both survive unary_union and were each counted as
                          # separate boundary feet -- see module docstring defect note). Measured directly:
                          # for every elementary segment on all six sheets, the offset (point-to-segment,
                          # pt-equivalent) to its nearest same-direction (PARALLEL_TOL_DEG) neighbour,
                          # 190,883 matched segments total -- 99.96% (190,808) sit under 1.0 pt, median
                          # 0.36 pt, essentially none between 0.5 and 1.0 pt (7 segments, 5 ft total across
                          # all six sheets). 1.0 pt sits comfortably above the real duplicate cluster with
                          # margin, short of where a genuinely separate parallel line (a second R/W edge a
                          # few ft off) would start.
DENSIFY_FT = 1.0         # ft: elementary-segment length for the covered/dimensioned classification
CLOSE_PCT = 0.99
CLOSURE_MAX_FT = 1.0
CT_MISFIT_FT = os.environ.get("CT_MISFIT_FT")  # 2026-09-29 what-if (loop19-tol1): env override, read
CT_MISFIT_FT = float(CT_MISFIT_FT) if CT_MISFIT_FT else None  # once at import. Unset -> load_rec_edges()'s
# own "misfit_ft <= 0.5" clean-edge bar, unchanged (default). Set (e.g. CT_MISFIT_FT=1.0) -> a record
# edge whose OWN drawn-vs-record misfit is that many ft or less also counts as clean (reconstructable).
# CLOSURE_MAX_FT (face/anchored closure, already 1.0 ft) is untouched -- JR's ask left it alone.
KINK_BRIDGE_FT = 10.0    # ft: a run of consecutive uncovered ring pieces this short or shorter, with
                          # the SAME reconstructed edge on both sides of it, is a stray digitizing kink
                          # in that one edge's own drawn piece, not a separate record course (loop17 leg
                          # B, face_closure()'s own docstring on loop17 leg A's split-course sharing:
                          # measured on Presidio 61806-9, a 2-vertex out-and-back spike -- 3.99 + 4.00 ft,
                          # returning within 0.2 ft of where it left -- sandwiched between the same
                          # N67d07'01"W course's two pieces on both sides). Comfortably above the one
                          # measured kink; the real guard is requiring the SAME edge on both sides, not
                          # this length alone -- a genuine separate course between two DIFFERENT edges
                          # is never bridged, whatever its length
ZOOM_PT = 600.0           # pt: page-space window size (both axes) for the zoomed record-edge crop
ZOOM_SCALE = 3.0          # raster scale for the zoom crop (>= 3x page pt so lines/text stay legible)
COVERED_INVARIANCE_TOL_FT = 0.5  # a removal must not change covered ft by more than this (discretization slack)
OUT_RECON = Path(__file__).parent / "out_recon"

# loop18 leg 1: ceiling class (e) contamination (recon_ceiling.py), moved to the source -- recon_ceiling
# found 2,267 ft across the six gate sheets that is drawn-boundary linework recon.py's own five removal
# classes above never caught, but is not real boundary either (a title-block/legend/notes table region,
# or a leader/wedge shape recon.py's own leader_wedge class missed). JR (2026-09-28): remove it from the
# denominators here, not by subtracting the ceiling's hand total after the fact.
TITLEBLOCK_RE = re.compile(  # identical to recon_ceiling.TITLEBLOCK_RE (loop17 leg M): anchors unique to
                            # the title/notes/legend block ONLY -- a generic phrase that can legitimately
                            # appear as a real note or callout elsewhere on the sheet is deliberately
                            # excluded (recon_ceiling's own docstring: a "...STATE OF CALIFORNIA..."
                            # disclaimer paragraph near the sheet's TOP once blew this box up to swallow
                            # nearly the whole sheet). Measured: R-10434.1's own GRANTOR NOTES/LEGEND/
                            # title-block region, 1,493 ft of its own table-grid linework counted as
                            # drawn boundary with no region ever removing it.
                            r"GRANTOR NOTES|^LEGEND$|COPYRIGHT 20\d\d CALIFORNIA DEPARTMENT OF TRANSPORTATION|"
                            r"^RECORD MAP$|^SCALE:|^DRAFTED BY|^CHECKED BY|^SHEET NO\.?$|^TOTAL SHEETS$|"
                            r"^PROJECT ID:", re.I)
TITLEBLOCK_PAD_FT = 5.0   # ft: kept tight (recon_ceiling's own measured choice) -- under-catching genuine
                           # title-block debris at an outer corner costs a few more "d" (true ceiling
                           # loss) ft, not a false removal of real boundary
TITLEBLOCK_CLUSTER_FT = 400.0  # ft: single-linkage clustering radius over TITLEBLOCK_RE's own matched
                           # text positions, largest cluster only -- recon_ceiling.titleblock_box() took
                           # one bbox over EVERY match, safe there (it only ever coerced an already-
                           # unexplained "d" run, per its own docstring); a hard removal class needs
                           # more care. Measured on R-10434.1: the real title-block corner's 9 matches
                           # (GRANTOR NOTES, LEGEND, COPYRIGHT, SCALE:, RECORD MAP, DRAFTED/CHECKED BY,
                           # SHEET NO./TOTAL SHEETS/PROJECT ID:) sit within 56-310 ft of their own
                           # nearest neighbour; a SEPARATE "SCALE: 1"=100'" note near the drawing itself
                           # (the ^SCALE: pattern matches both) sits 1,172 ft from the nearest real
                           # title-block match -- one bbox over both blew the box up to swallow ~1,300
                           # ft of real boundary between them (measured: 4,689 ft removed vs the true
                           # ~1,493). 400 ft sits comfortably between the two.
BEND_CONTAM_DEG = 150.0   # deg: a chained run of elementary segments whose own direction very nearly
                           # reverses (a spike/wedge/leader shape a real boundary course never walks)
                           # is contamination, not boundary -- see recon_ceiling.BEND_CONTAM_DEG, same
                           # value, same measured cases (a real gently-sweeping curve's own unwrapped
                           # bend never approaches this; a wedge/spike's does)
CHAIN_TOL_FT_SET = 1.5    # ft: how close two elementary segments' shared endpoint must sit to chain into
                           # one run for the bend test -- see recon_ceiling.CHAIN_TOL_FT, same value
LOCAL_SPLIT_DEG_SET = 20.0  # deg: a run also breaks wherever ONE step turns more than this (recon_ceiling
                           # .LOCAL_SPLIT_DEG) -- essential here: applied to the WHOLE boundary (not
                           # recon_ceiling's own already-sparse uncovered-only pool), a run chained by
                           # gap alone walks every ordinary polygon corner in sequence and its cumulative
                           # unwrapped bend crosses BEND_CONTAM_DEG well before completing one rectangular
                           # parcel (measured: without this split, Presidio's wedge_residual class wrongly
                           # took 3,798 ft instead of ~87). Splitting on each sharp per-step turn keeps a
                           # run to the gently-curving-or-straight pieces a real spike/wedge shape is.
PRESIDIO_CONTAM_PT = [    # page-pt (cx, cy), read directly off read_shx.json -- three leader wedges that
                          # converge on a label rather than running parallel to the corridor for their
                          # whole length (recon_attrib.py's own docstring measured this by crop:
                          # out_recon/_crop_dk046825_063269.png). Presidio-specific by construction (no
                          # equivalent hand list exists, or was measured needed, on any other sheet).
    (789.5, 281.5),   # "DK-046825-X1-X1"
    (1230.0, 388.0),  # "063269-X1-X1"
    (964.5, 396.0),   # "63269" bubble
]
PRESIDIO_CONTAM_TOL_PT = 160.0


def ground_of(params):
    a, b, tx, ty = params

    def ground(pts):
        pts = np.atleast_2d(np.asarray(pts, float))
        sx, sy = pts[:, 0], -pts[:, 1]
        return np.c_[a * sx - b * sy + tx, b * sx + a * sy + ty]
    return ground


def inv_of(params):
    a, b, tx, ty = params
    M = np.array([[a, -b], [b, a]])

    def inv(EN):
        EN = np.atleast_2d(np.asarray(EN, float))
        sxsy = np.linalg.solve(M, (EN - [tx, ty]).T).T
        return np.c_[sxsy[:, 0], -sxsy[:, 1]]
    return inv


def azimuth_arr(d):
    """d: (...,2) ground [dE, dN] -> compass azimuth deg, 0 = north."""
    return np.degrees(np.arctan2(d[..., 0], d[..., 1])) % 360


def point_seg_dist(P, A, B):
    """P: (M,2) points; A,B: (N,2) segment endpoints -> (M,N) point-to-segment distances."""
    if len(A) == 0:
        return np.full((len(P), 0), np.inf)
    AB = B - A
    ab2 = np.maximum((AB ** 2).sum(1), 1e-9)
    AP = P[:, None, :] - A[None, :, :]
    t = np.clip((AP * AB[None, :, :]).sum(2) / ab2[None, :], 0, 1)
    proj = A[None, :, :] + t[:, :, None] * AB[None, :, :]
    diff = P[:, None, :] - proj
    return np.hypot(diff[..., 0], diff[..., 1])


def elementary_segments(geom, densify_ft):
    """(P, Q, mid, seg_len, seg_az) for every consecutive coordinate pair of every LineString
    component of geom, after densifying to densify_ft."""
    if geom is None or geom.is_empty:
        z = np.zeros((0, 2))
        return z, z, z, np.zeros(0), np.zeros(0)
    dense = shapely.segmentize(geom, densify_ft)
    geoms = dense.geoms if hasattr(dense, "geoms") else [dense]
    P, Q = [], []
    for g in geoms:
        if g.is_empty or g.geom_type != "LineString":
            continue
        c = np.array(g.coords)
        if len(c) < 2:
            continue
        P.append(c[:-1]); Q.append(c[1:])
    if not P:
        z = np.zeros((0, 2))
        return z, z, z, np.zeros(0), np.zeros(0)
    P, Q = np.vstack(P), np.vstack(Q)
    mid = (P + Q) / 2
    seg_len = np.hypot(*(Q - P).T)
    seg_az = azimuth_arr(Q - P)
    return P, Q, mid, seg_len, seg_az


def covered_mask(mid, seg_az, rec_P, rec_Q, rec_az, buffer_ft, tol_deg):
    """(covered bool per segment, nearest-matching-edge index per segment (-1 if none))."""
    if len(rec_P) == 0 or len(mid) == 0:
        return np.zeros(len(mid), bool), np.full(len(mid), -1)
    d = point_seg_dist(mid, rec_P, rec_Q)
    adiff = np.abs((seg_az[:, None] - rec_az[None, :] + 90) % 180 - 90)
    match = (d <= buffer_ft) & (adiff <= tol_deg)
    any_match = match.any(1)
    dm = np.where(match, d, np.inf)
    best = np.where(any_match, dm.argmin(1), -1)
    return any_match, best


def dedupe_segments(P, Q, mid, seg_len, seg_az, dup_tol_ft, angle_tol_deg, extra_masks):
    """Collapse near-coincident, near-parallel elementary segments -- the loop16 leg C fix: an R/W stroke
    drawn a hair over a face edge, or two faces' own edges sharing a line, are not bit-identical geometry
    so unary_union keeps both, and both got counted as separate boundary feet (defect: up to 3x on the
    six sheets measured -- see module docstring). Fixed processing order (lexsort on midpoint x, then y,
    then azimuth -- independent of shapely's own union/segmentize ordering, so the result does not depend
    on run-to-run/version geometry ordering): each segment is visited once and either becomes a keeper (no
    not-yet-decided segment near it yet) or is absorbed into the nearest not-yet-decided keeper within
    dup_tol_ft PERPENDICULAR offset and angle_tol_deg of it (mod 180) -- a segment already claimed is
    never reconsidered, same "claimed by the first thing that touches it" rule the contamination-removal
    classes already use. One cKDTree query per keeper (not O(n^2)): 30k+ segments in well under a second.

    Perpendicular offset, not point-to-segment distance: two consecutive elementary pieces of the SAME
    drawn line are exactly collinear (perpendicular offset 0), so a plain point-to-segment distance calls
    them "duplicates" too and collapses a whole straight line down to one point (caught by selftest #7
    while writing this -- a 100 ft line came back 50 ft). The fix also requires the candidate's own
    projected position (t, unclamped, ft along its own direction from its start) to fall within its own
    span (+/- a small margin for the two lines' densify grids not landing on the same phase) -- true
    duplicates sit at the SAME position along the corridor, only offset sideways; a same-line neighbour
    one DENSIFY_FT further down the line does not.

    Which copy survives is otherwise arbitrary (the two copies sit within dup_tol_ft of each other, so it
    does not matter which one's exact coordinates are kept for length/figure purposes) -- what must not be
    arbitrary is classification: extra_masks (cov_mask_full, dim_mask_full) are OR'd into the keeper from
    every duplicate collapsed into it, computed on every copy before collapsing (by the caller, before this
    call), so a keeper never loses a covered/dimensioned flag a collapsed copy alone carried.

    Returns (P, Q, mid, seg_len, seg_az, [mask0, mask1, ...]) sliced to kept segments only."""
    n = len(mid)
    if n == 0:
        return P, Q, mid, seg_len, seg_az, [m.copy() for m in extra_masks]
    order = np.lexsort((seg_az, mid[:, 1], mid[:, 0]))
    tree = cKDTree(mid)
    cap_ft = dup_tol_ft * 1.5 + DENSIFY_FT  # loose ball-query radius; the perp/span test below is the exact one
    span_margin_ft = 0.3 * DENSIFY_FT  # generous vs a duplicate's own densify-grid phase mismatch, tight
                                        # vs an adjacent same-line neighbour a full DENSIFY_FT further along
    processed = np.zeros(n, bool)
    keep = np.ones(n, bool)
    masks = [m.copy() for m in extra_masks]
    for idx in order:
        if processed[idx]:
            continue
        processed[idx] = True
        cand = np.asarray(tree.query_ball_point(mid[idx], r=cap_ft), dtype=int)
        cand = cand[~processed[cand]]
        if len(cand) == 0:
            continue
        adiff = np.abs((seg_az[idx] - seg_az[cand] + 90) % 180 - 90)
        cand = cand[adiff <= angle_tol_deg]
        if len(cand) == 0:
            continue
        AB = Q[cand] - P[cand]
        L = np.maximum(np.hypot(AB[:, 0], AB[:, 1]), 1e-9)
        u = AB / L[:, None]
        AP = mid[idx] - P[cand]
        t = AP[:, 0] * u[:, 0] + AP[:, 1] * u[:, 1]              # ft along candidate's own direction, unclamped
        perp = np.abs(AP[:, 0] * u[:, 1] - AP[:, 1] * u[:, 0])    # perpendicular ft offset
        dup = cand[(t >= -span_margin_ft) & (t <= L + span_margin_ft) & (perp <= dup_tol_ft)]
        if len(dup) == 0:
            continue
        processed[dup] = True
        keep[dup] = False
        for m in masks:
            if m[dup].any():
                m[idx] = True
    return P[keep], Q[keep], mid[keep], seg_len[keep], seg_az[keep], [m[keep] for m in masks]


def heavy_lines_weighted(page):
    """Same filter as parcels.heavy_lines(), but keeps each polyline's own stroke weight so R/W
    linework (the heaviest class) can be told apart from the 0.84 pt parcel/easement class."""
    x0, y0, x1, y1 = MAP_AREA
    out = []
    for d in page.get_drawings():
        r, c = d["rect"], d.get("color")
        w = round(d.get("width") or 0, 2)
        if c is None or max(c) > 0.2:
            continue
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if not (x0 < cx < x1 and y0 < cy < y1):
            continue
        total = (sum(np.hypot(it[2].x - it[1].x, it[2].y - it[1].y) for it in d["items"] if it[0] == "l")
                 + sum(np.hypot(it[4].x - it[1].x, it[4].y - it[1].y) for it in d["items"] if it[0] == "c"))
        if w == 0 or total < 12 or (w < 0.8 and total < 40) or max(r.width, r.height) <= 12:
            continue
        if d["closePath"] and r.width < 90 and r.height < 24:
            continue
        pts = []
        for it in d["items"]:
            if it[0] == "l":
                seg = [(it[1].x, it[1].y), (it[2].x, it[2].y)]
            elif it[0] == "c":
                seg = [tuple(p) for p in bezier(*[np.array([p.x, p.y]) for p in it[1:5]])]
            else:
                continue
            if pts and np.hypot(pts[-1][0] - seg[0][0], pts[-1][1] - seg[0][1]) > 0.5:
                out.append((LineString(pts), w)); pts = []
            pts = (pts[:-1] if pts else []) + seg
        if len(pts) > 1:
            out.append((LineString(pts), w))
    return out


def pick_rw_class(weights):
    """weights: {stroke width: [count, length_ft]} -> the heaviest class clearing RW_MIN_COUNT lines
    and RW_MIN_FT total length, or None. A numerically heavier class that is really a stray
    titleblock/border stroke (measured: R-10741.1's 2.28 pt, 1 line, 118 ft) is rejected by the count
    and length floors, not by picking a lower class by fiat."""
    candidates = {w: v for w, v in weights.items() if v[0] >= RW_MIN_COUNT and v[1] >= RW_MIN_FT}
    return max(candidates) if candidates else None


def boxes_to_ground_union(boxes, ground):
    """[x0,y0,x1,y1] page-pt boxes -> unary_union of ground-ft rectangles, or None if boxes is empty."""
    polys = []
    for x0, y0, x1, y1 in boxes:
        if x1 <= x0 or y1 <= y0:
            continue
        polys.append(Polygon(ground([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])))
    return unary_union(polys) if polys else None


def grow_box(b, pad):
    x0, y0, x1, y1 = b
    return [x0 - pad, y0 - pad, x1 + pad, y1 + pad]


def in_any_box(pt, boxes):
    x, y = pt
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in boxes)


def point_table_regions(blocks, gap=30):
    """Bounding box of a 'POINT / NORTHING / EASTING' coordinates table. checks.alignment_table_regions()
    only anchors on a 'STATION' header, so a table shaped like Presidio's and R-10434.3's COORDINATES
    TABLE (POINT column instead of STATION) gets no region there at all and its frame stays whole in the
    drawn boundary (measured: Presidio's COORDINATES TABLE, top right, header 'POINT | NORTHING |
    EASTING' at cy 227 -- no STATION block anywhere near it). Same shape as alignment_table_regions,
    anchored on POINT instead."""
    headers = [b for b in blocks if b["text"].strip() in ("POINT", "NORTHING", "EASTING")]
    regions = []
    for pt in (h for h in headers if h["text"].strip() == "POINT"):
        row = [pt] + [h for h in headers if h is not pt and abs(h["cy"] - pt["cy"]) < 15 and h["cx"] > pt["cx"]]
        x0 = min(h["cx"] - h.get("w", 40) / 2 for h in row) - 60
        x1 = max(h["cx"] + h.get("w", 60) / 2 for h in row) + 20
        col = sorted((b for b in blocks if x0 <= b["cx"] <= x1 and b["cy"] > pt["cy"]), key=lambda b: b["cy"])
        y1 = pt["cy"] + 15
        for b in col:
            if b["cy"] - y1 > gap:
                break
            y1 = max(y1, b["cy"] + 15)
        regions.append((round(x0), round(pt["cy"] - 25), round(x1), round(y1)))
    return regions


RADIAL_TAG_RE = re.compile(r"^R-(\d+)$")


def radial_table_regions(blocks, reach=250):
    """Bounding box of each RADIAL LINE TABLE (its own NO. column reads 'R-1', 'R-2', ...), re-derived the
    same way checks.line_curve_table_regions() chains L#/C# tags -- but that function's own NO_TAG_RE only
    matches an L or C prefix, so an 'R-' tag never matches it and a radial table never gets a region from
    it at all. Measured on R-10434.3: its RADIAL LINE TABLE (1) left column chains R-1..R-13 at x 331-335,
    cy 1125-1255; with no region source of its own, only the tail tables.json happened to cover stayed
    grey, and R-1..R-10's own column-divider stroke (part of a named face's ring, same as any other table
    grid line) stayed in the drawn boundary."""
    tagged = [(b, int(m[1])) for b in blocks for m in [RADIAL_TAG_RE.match(b["text"].strip())] if m]
    used, regions = set(), []
    for i, (b0, num0) in enumerate(tagged):
        if i in used:
            continue
        col = [(i, b0, num0)]
        pitch = None
        while True:
            by = col[-1][1]["cy"]
            nxt = [(j, bj, nj) for j, (bj, nj) in enumerate(tagged)
                   if j not in used and j not in {c[0] for c in col} and nj == num0 + len(col)
                   and abs(bj["cx"] - b0["cx"]) < 8 and 6 < bj["cy"] - by < 30 and (pitch is None or abs(bj["cy"] - by - pitch) < 4)]
            if not nxt:
                break
            j, bj, nj = nxt[0]
            pitch = pitch or (bj["cy"] - by)
            col.append((j, bj, nj))
        if len(col) < 4:
            continue
        used.update(c[0] for c in col)
        band = max(6.0, 0.6 * (pitch or 14))
        xs = [c[1]["cx"] for c in col]
        ys = [c[1]["cy"] for c in col]
        x1 = max(xs)
        for _, brow, _ in col:
            row = [ob for ob in blocks if ob is not brow and not RADIAL_TAG_RE.match(ob["text"].strip())
                   and 0 < ob["cx"] - brow["cx"] < reach and abs(ob["cy"] - brow["cy"]) < band]
            if row:
                x1 = max(x1, max(ob["cx"] + ob.get("w", 40) / 2 for ob in row))
        regions.append([round(min(xs) - 20), round(min(ys) - 16), round(x1 + 20), round(max(ys) + 16)])
    return regions


def largest_cluster(pts, radius_ft):
    """pts (N,2) -> the points of the largest single-linkage cluster (edges within radius_ft), by
    count -- a plain union-find, cheap at the handful of matches this is ever run on. See
    TITLEBLOCK_CLUSTER_FT's own comment for why this exists."""
    n = len(pts)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i

    d = np.hypot(*(pts[:, None, :] - pts[None, :, :]).transpose(2, 0, 1))
    for i in range(n):
        for j in range(i + 1, n):
            if d[i, j] <= radius_ft:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    roots = [find(i) for i in range(n)]
    biggest = max(set(roots), key=roots.count)
    return pts[[i for i in range(n) if roots[i] == biggest]]


def titleblock_region(blocks, ground):
    """ground-space box (a shapely Polygon) around the LARGEST single-linkage cluster (largest_cluster(),
    TITLEBLOCK_CLUSTER_FT) of title-block/legend/notes text matches (TITLEBLOCK_RE), padded by
    TITLEBLOCK_PAD_FT -- ported from recon_ceiling.titleblock_box() (loop17 leg M), which only ever fed
    the ceiling report; this is the same rule applied at the source so it actually removes the ft from
    recon.py's own denominators, with the clustering step added since a hard removal here (unlike
    recon_ceiling's own "d"-run-only gate) needs to reject an unrelated same-text-pattern match
    elsewhere on the sheet, not merge it in. None where no such text exists on the sheet (most of the
    six gate sheets carry none)."""
    pts = [ground(np.array([[b["cx"], b["cy"]]]))[0] for b in blocks if TITLEBLOCK_RE.search(b["text"])]
    if not pts:
        return None
    pts = largest_cluster(np.array(pts), TITLEBLOCK_CLUSTER_FT)
    lo, hi = pts.min(0) - TITLEBLOCK_PAD_FT, pts.max(0) + TITLEBLOCK_PAD_FT
    return Polygon([(lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1])])


def wedge_spike_mask(P, Q, mid, seg_len, seg_az, chain_tol_ft, bend_deg, local_split_deg):
    """bool per elementary segment: part of a chained run (endpoint proximity AND no single sharp
    per-step turn -- same two-part chaining recon_ceiling.build_runs() uses, LOCAL_SPLIT_DEG included:
    see LOCAL_SPLIT_DEG_SET's own comment for why the turn split matters here) whose own direction very
    nearly reverses end to end (ptp of the run's own per-segment azimuth, unwrapped relative to its
    first member so a run whose azimuth range straddles a multiple of 180 does not read as a false
    reversal -- see recon_ceiling.build_runs()'s own comment). A real boundary course only ever walks
    forward; a spike/wedge/leader shape does not. Ported from recon_ceiling's own per-run bend
    classification (loop17 leg M, class (e) "near-reversal run"), applied here to every elementary
    segment of the boundary (not just an already-uncovered no-traverse-edge pool), so a wedge shape
    anywhere is removed at the source, not only inside the ceiling report."""
    n = len(mid)
    if n == 0:
        return np.zeros(0, bool)

    def az_diff360(a, b):
        d = abs(a - b) % 360
        return min(d, 360 - d)

    runs = []
    cur = []
    for i in range(n):
        if cur:
            prev = cur[-1]
            gap = min(np.hypot(*(Q[prev] - P[i])), np.hypot(*(Q[prev] - Q[i])), np.hypot(*(P[prev] - P[i])))
            turn = az_diff360(seg_az[prev], seg_az[i])
            if gap > chain_tol_ft or turn > local_split_deg:
                runs.append(cur); cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    hit = np.zeros(n, bool)
    for members in runs:
        if len(members) < 2:
            continue
        az0 = seg_az[members[0]]
        rel = (seg_az[members] - az0 + 180) % 360 - 180
        if float(np.ptp(rel)) >= bend_deg:
            hit[members] = True
    return hit


def region_hit(region, mid):
    """bool per row of mid (ground ft Nx2): inside region (a shapely geometry or None)."""
    if region is None or region.is_empty or len(mid) == 0:
        return np.zeros(len(mid), bool)
    return shapely.contains_xy(region, mid[:, 0], mid[:, 1])


def face_pieces(ring, rec_P, rec_Q, rec_az, rec_parent, buffer_ft, tol_deg, densify_ft):
    """Per-original-vertex ring segment: (rec_edges index or None, p, q), plus the fraction of the
    ring's own length that some reconstructed edge covers. An edge is assigned to a ring segment only
    when it accounts for >= half that segment's own (densified) covered length -- a majority vote, so
    one stray sub-point near a different edge cannot hijack a whole drawn piece.
    rec_P/rec_Q/rec_az (loop16 leg E: rec_segments()) may carry several small sub-segments per curve
    (the arc's own local direction, piece by piece, not one long chord); rec_parent maps each one back
    to its single parent rec_edges entry (a line's own single segment maps to itself, rec_parent[i]==i)
    so the majority vote -- and face_closure()'s own record walk after it -- always resolves to ONE
    edge per ring piece, its record chord vector, never a stray local sub-segment's own az/whole-length
    mismatched against each other."""
    pieces, covered_len, total_len = [], 0.0, 0.0
    for i in range(len(ring) - 1):
        p, q = ring[i], ring[i + 1]
        L = float(np.hypot(*(q - p)))
        total_len += L
        if L < 1e-6:
            pieces.append((None, p, q)); continue
        n = max(1, int(L / densify_ft))
        ts = (np.arange(n) + 0.5) / n
        sub_mid = p + ts[:, None] * (q - p)
        seg_az = azimuth_arr(q - p) * np.ones(n)
        any_match, best = covered_mask(sub_mid, seg_az, rec_P, rec_Q, rec_az, buffer_ft, tol_deg)
        covered_len += any_match.mean() * L
        if any_match.mean() >= 0.5:
            parent_best = rec_parent[best[any_match]]
            vals, counts = np.unique(parent_best, return_counts=True)
            k = int(vals[np.argmax(counts)])
        else:
            k = None
        pieces.append((k, p, q))
    # loop17 leg B: bridge a short run of uncovered pieces flanked by the SAME reconstructed edge on
    # both sides -- see KINK_BRIDGE_FT. Length-gated and only ever assigns an edge that already covers
    # both neighbours, so it can only turn a stray kink into "covered by the edge already either side
    # of it", never invent a new edge or extend one past a genuinely different or missing course.
    i = 0
    while i < len(pieces):
        if pieces[i][0] is not None:
            i += 1; continue
        j = i
        while j < len(pieces) and pieces[j][0] is None:
            j += 1
        if 0 < i and j < len(pieces) and pieces[i - 1][0] == pieces[j][0]:
            run_len = sum(float(np.hypot(*(np.array(q) - np.array(p)))) for _, p, q in pieces[i:j])
            if run_len <= KINK_BRIDGE_FT:
                k = pieces[i - 1][0]
                covered_len += run_len
                for m in range(i, j):
                    pieces[m] = (k, pieces[m][1], pieces[m][2])
        i = j
    pct = covered_len / total_len if total_len else 0.0
    return pieces, pct, total_len


def face_closure(pieces, rec_edges):
    """Walk the ring by record where a piece has a reconstructed edge (bearing flipped 180 deg when
    it opposes the ring's own walk direction, as traverse.py's own per-figure walk does), by the
    drawn vector otherwise. closure = |sum of vectors| back to the start.
    An arc piece (loop16 leg E) walks the same way, by its own record CHORD vector, not the drawing:
    rec_edges' own "ft"/"az" for an arc entry are already the row's CHORD length/direction (traverse.py's
    own walk() -- 2*R*sin(delta/2) at the record chord az, never a local sub-segment's), so no
    kind-specific branch is needed here; face_pieces()'s own rec_parent already resolved k to that one
    parent entry, whichever local sub-segment matched.
    Loop17 leg A: a single drawn record course can span more than one ORIGINAL ring vertex (a stray
    digitizing kink -- a vertex pair a few pt apart -- splits face_pieces()'s per-vertex walk into
    two-or-more pieces that all majority-vote to the SAME rec_edges entry k, possibly with a genuine
    small no-record jog piece between them). Applying that edge's FULL record vector to every one of
    those pieces overcounts it -- measured on Presidio's 61806-9 (98.1% covered, unflagged, unmisfit):
    its own "N67 deg 07'01"W + 138.21'" record course sits on 2 ring pieces (24.70 + 113.34 = 138.04 ft
    drawn, matching the record length), so the old code added a 138.21 ft vector TWICE and reported a
    162 ft closure miss on a parcel that is, in fact, fully walked by record. Each piece sharing a k now
    takes a fair SHARE of that edge's record length, by its own drawn-length fraction of every piece
    sharing that k in this ring -- collinear fragments sum back to exactly one course's own vector,
    applied once in total, not once per fragment."""
    k_drawn_len = {}
    for k, p, q in pieces:
        if k is not None:
            k_drawn_len[k] = k_drawn_len.get(k, 0.0) + float(np.hypot(*(np.array(q, float) - np.array(p, float))))
    pos = np.array(pieces[0][1], float)
    total = np.zeros(2)
    for k, p, q in pieces:
        p, q = np.array(p, float), np.array(q, float)
        if k is None:
            v = q - p
        else:
            e = rec_edges[k]
            drawn_az = azimuth_arr(q - p)
            az = e["az"] if abs((e["az"] - drawn_az + 180) % 360 - 180) < 90 else (e["az"] + 180) % 360
            piece_len = float(np.hypot(*(q - p)))
            share = e["ft"] * (piece_len / k_drawn_len[k]) if k_drawn_len[k] > 0 else 0.0
            v = share * np.array([math.sin(math.radians(az)), math.cos(math.radians(az))])
        total += v
    return float(np.hypot(*total))


def buffer_sensitivity(mid, seg_az, seg_len, rec_P, rec_Q, rec_az, pts_list):
    out = {}
    for bp in pts_list:
        any_match, _ = covered_mask(mid, seg_az, rec_P, rec_Q, rec_az, bp["ft"], PARALLEL_TOL_DEG)
        out[bp["pt"]] = float(seg_len[any_match].sum())
    return out


def load_faces(gj):
    to_ground = Transformer.from_crs("EPSG:6318", "EPSG:2227", always_xy=True)
    faces = []
    for feat in gj["features"]:
        coords = feat["geometry"]["coordinates"][0]
        lon, lat = zip(*coords)
        E, N = to_ground.transform(lon, lat)
        ring = np.c_[E, N]
        name = feat["properties"].get("parcel", "")
        faces.append({"poly": Polygon(ring), "ring": ring, "named": bool(name), "parcel": name})
    return faces


def load_rec_edges(trav, exclude_inverse=False):
    """A clean traverse.json row (flags==[], misfit<=0.5) as a reconstructed edge. kind=="line" as
    before; kind=="arc" now qualifies too (loop16 leg E: once traverse.py's own chord-direction
    completion clears "chord direction from drawing", an arc row can be flag-free the same as a
    line). An arc entry additionally carries its own full drawn "pts" polyline (ground ft, the curve
    itself) -- see rec_segments(), which is what actually follows it for coverage; "p"/"q"/"az"/"ft"
    here stay the row's own CHORD endpoints/direction/length, used by face_closure()'s record walk.
    exclude_inverse=True (loop18 leg 2) drops a row inverse.py added ("source": "by inverse ...") --
    the "without inverse" comparison recon_set.py and bench's recon_inverse_ft column both want.
    CT_MISFIT_FT env override (read once at import, defined above CLOSURE_MAX_FT) replaces the 0.5 ft
    clean bar."""
    rec = []
    n_rows = 0
    for chain in trav:
        for row in chain["edges"]:
            n_rows += 1
            if row["kind"] not in ("line", "arc") or row["flags"] or row["misfit_ft"] > (CT_MISFIT_FT if CT_MISFIT_FT is not None else 0.5):
                continue
            if exclude_inverse and str(row.get("source", "")).startswith("by inverse"):
                continue
            pts = row.get("pts")
            if not pts or len(pts) < 2:
                continue
            pts = np.array(pts, float)
            e = {"name": row["edge"], "az": row["az"], "ft": row["ft"], "misfit_ft": row["misfit_ft"],
                 "p": pts[0], "q": pts[-1], "kind": row["kind"]}
            if row["kind"] == "arc":
                e["pts"] = pts
            rec.append(e)
    return rec, n_rows


def rec_segments(rec_edges):
    """Flat (P, Q, az, parent_idx) arrays for covered_mask()/face_pieces(): a line contributes its own
    single p/q/az (unchanged); an arc contributes every consecutive pair of its OWN drawn "pts" (loop16
    leg E: coverage follows the curve's own local direction, piece by piece, not one long chord az that
    only agrees with the drawing at the arc's midpoint), each tagged with the SAME parent index so a
    match on any one sub-segment still resolves back to one rec_edges entry."""
    P, Q, az, parent = [], [], [], []
    for i, e in enumerate(rec_edges):
        if e["kind"] == "arc":
            pts = e["pts"]
            for j in range(len(pts) - 1):
                p, q = pts[j], pts[j + 1]
                if np.hypot(*(q - p)) < 1e-9:
                    continue
                P.append(p); Q.append(q); az.append(float(azimuth_arr((q - p)[None, :])[0])); parent.append(i)
        else:
            P.append(e["p"]); Q.append(e["q"]); az.append(e["az"]); parent.append(i)
    if not P:
        z = np.zeros((0, 2))
        return z, z, np.zeros(0), np.zeros(0, int)
    return np.array(P), np.array(Q), np.array(az), np.array(parent, int)


def densest_cluster_center(rec_edges):
    """ft-length-weighted centroid of reconstructed edges' own midpoints: a simple, single-cluster proxy
    for "where the record edges are thickest on the ground", not a real density clustering. ponytail:
    upgrade to a real clustering (e.g. DBSCAN on edge midpoints) if a sheet's record edges ever split
    into two well-separated groups that this centroid would land between rather than on either one."""
    if not rec_edges:
        return None
    pts = np.array([(e["p"] + e["q"]) / 2 for e in rec_edges])
    w = np.array([max(e["ft"], 1.0) for e in rec_edges])
    return (pts * w[:, None]).sum(0) / w.sum()


def run(sheet_name, return_internals=False, exclude_inverse=False, make_figures=True, suffix=""):
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    ground = ground_of(g["params"])
    inv = inv_of(g["params"])
    scale = g["scale_ft_per_pt"]
    buffer_ft, rw_tol_ft, frame_tol_ft = BUFFER_PT * scale, RW_TOL_PT * scale, FRAME_TOL_PT * scale
    leader_tol_ft = LEADER_TOL_PT * scale
    dup_tol_ft = DUP_TOL_PT * scale

    gj = json.loads((OUT / "parcels.geojson").read_text())
    faces = load_faces(gj)

    # --- table/frame regions (defect 2, "tables" class), computed early so the R/W weight-class pick and
    # the dimensioned-test rw_P/rw_Q below can also drop a table's own frame/header strokes -- loop16 leg
    # A3: confirmed these are NOT R/W-weight (Presidio's table grid/frame strokes measured at 0.72 pt,
    # R-10434.3's at 0.72/1.44/1.02 pt; rw_w picked 1.98/1.98 pt on the two sheets, no overlap), so the
    # defect was never "shared R/W weight" -- it was (a) Presidio's/R-10434.3's COORDINATES TABLE using a
    # POINT header instead of STATION, which alignment_table_regions() never matches at all (no region),
    # and (b) tables.json._regions sitting snug around the data rows, short of the title bar/outer frame
    # stroke by 10-25 pt (measured on Presidio's three bottom-right tables). See TABLE_REGION_GROW_PT and
    # point_table_regions(). The R/W-in-table filter below is kept anyway per the fix brief, as a
    # defensive belt-and-suspenders for a sheet where a table frame does land on the R/W weight class.
    frame_json = json.loads((OUT / "frame.json").read_text(encoding="utf-8")) if (OUT / "frame.json").exists() else {}
    tables_json = json.loads((OUT / "tables.json").read_text(encoding="utf-8")) if (OUT / "tables.json").exists() else {}
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    table_boxes_pt = [grow_box(b, TABLE_REGION_GROW_PT) for b in
                      list(tables_json.get("_regions", [])) + alignment_table_regions(blocks)
                      + line_curve_table_regions(blocks) + point_table_regions(blocks) + radial_table_regions(blocks)]
    table_union = boxes_to_ground_union(table_boxes_pt, ground)

    # --- R/W weight class (defect 3): heaviest class clearing RW_MIN_COUNT/RW_MIN_FT, excluding any
    # stroke that lands inside a (grown) table region -- a table's own heavy frame/header strokes must
    # never count toward, or be measured against, the R/W class (defect 1 fix, retry).
    weighted_raw = heavy_lines_weighted(page)
    weighted = [(ln, w) for ln, w in weighted_raw if not in_any_box(ln.centroid.coords[0], table_boxes_pt)]
    weights = {}
    for ln, w in weighted:
        weights.setdefault(w, [0, 0.0])
        weights[w][0] += 1; weights[w][1] += ln.length * scale
    rw_w = pick_rw_class(weights)
    rw_lines_ground = [LineString(ground(np.array(ln.coords))) for ln, w in weighted if w == rw_w] if rw_w is not None else []
    rw_union_ground = unary_union(rw_lines_ground) if rw_lines_ground else None
    rw_P = np.vstack([np.array(l.coords)[:-1] for l in rw_lines_ground]) if rw_lines_ground else np.zeros((0, 2))
    rw_Q = np.vstack([np.array(l.coords)[1:] for l in rw_lines_ground]) if rw_lines_ground else np.zeros((0, 2))

    named_rings = [f["ring"] for f in faces if f["named"]]
    named_union = unary_union([LineString(r) for r in named_rings]) if named_rings else None
    named_P = np.vstack([r[:-1] for r in named_rings]) if named_rings else np.zeros((0, 2))
    named_Q = np.vstack([r[1:] for r in named_rings]) if named_rings else np.zeros((0, 2))

    trav = json.loads((OUT / "traverse.json").read_text())
    rec_edges, n_rows = load_rec_edges(trav, exclude_inverse=exclude_inverse)
    rec_P, rec_Q, rec_az, rec_parent = rec_segments(rec_edges)
    rec_lines_union = unary_union([LineString([p, q]) for p, q in zip(rec_P, rec_Q)]) if len(rec_P) else None

    # --- table/furniture debris faces (defect 2, "tables" class): unnamed faces isolated from both the
    # R/W linework and every named face's own boundary -- see module docstring / TABLE_ISOLATION_FT. A
    # face within buffer_ft of a clean record edge is never dropped this way, whatever its isolation --
    # same never-delete-a-covered-stretch rule the segment-level removal below enforces.
    dropped_faces = []
    kept_faces = []
    for f in faces:
        near_record = rec_lines_union is not None and f["poly"].exterior.distance(rec_lines_union) <= buffer_ft
        if not f["named"] and not near_record and rw_union_ground is not None:
            iso = f["poly"].distance(rw_union_ground)
            if named_union is not None:
                iso = min(iso, f["poly"].distance(named_union))
            if iso > TABLE_ISOLATION_FT:
                dropped_faces.append(f); continue
        kept_faces.append(f)

    boundary_lines_all = [f["poly"].exterior for f in faces if not f["poly"].exterior.is_empty]
    boundary_lines_kept = [f["poly"].exterior for f in kept_faces if not f["poly"].exterior.is_empty]
    union_all_faces = unary_union(boundary_lines_all)
    union_kept_faces = unary_union(boundary_lines_kept)
    dropped_face_ft = max(0.0, union_all_faces.length - union_kept_faces.length)

    # defect 1 fix: the drawn boundary is faces UNION the R/W linework, not faces alone -- R-10741.1's
    # record edges sit on R/W linework that no face on this sheet actually carries.
    rw_add_parts = [union_kept_faces] + ([rw_union_ground] if rw_union_ground is not None else [])
    drawn_pre = unary_union(rw_add_parts)
    rw_added_ft = drawn_pre.length - union_kept_faces.length

    # invariant baseline: covered ft measured on the fully raw boundary (no face-drop, no region removal,
    # WITH the defect-1 R/W fix) -- compared against the final, cleaned boundary below.
    drawn_baseline = unary_union([union_all_faces] + ([rw_union_ground] if rw_union_ground is not None else []))

    Pb, Qb, midb, seg_lenb, seg_azb = elementary_segments(drawn_baseline, DENSIFY_FT)
    cov_maskb, _ = covered_mask(midb, seg_azb, rec_P, rec_Q, rec_az, buffer_ft, PARALLEL_TOL_DEG)
    # defect 6 fix (double/triple-counted boundary): dedupe the baseline too, the same way as the main
    # boundary below -- see dedupe_segments(). Otherwise this invariance check compares a deduped final
    # boundary against a still-inflated raw one and gets blown up by the very over-counting the fix
    # removes, not by anything the face-drop/removal steps actually did.
    Pb, Qb, midb, seg_lenb, seg_azb, (cov_maskb,) = dedupe_segments(
        Pb, Qb, midb, seg_lenb, seg_azb, dup_tol_ft, PARALLEL_TOL_DEG, [cov_maskb])
    covered_ft_baseline = float(seg_lenb[cov_maskb].sum())

    P, Q, mid, seg_len, seg_az = elementary_segments(drawn_pre, DENSIFY_FT)
    cov_mask_full, _ = covered_mask(mid, seg_az, rec_P, rec_Q, rec_az, buffer_ft, PARALLEL_TOL_DEG)
    # dimensioned classification (heaviest R/W weight class within rw_tol_ft, OR a named face's own
    # boundary within NAMED_TOL_FT -- same formula as before, just moved up from its old spot near the end
    # of run()) computed here, on the raw pre-dedup segment set, so a duplicate copy's own dim match is
    # available to OR into its keeper next.
    rw_dist = point_seg_dist(mid, rw_P, rw_Q).min(1) if len(mid) and len(rw_P) else np.full(len(mid), np.inf)
    named_dist = point_seg_dist(mid, named_P, named_Q).min(1) if len(mid) and len(named_P) else np.full(len(mid), np.inf)
    dim_mask_full = (rw_dist <= rw_tol_ft) | (named_dist <= NAMED_TOL_FT)
    # defect 6 fix: collapse near-coincident parallel copies into one before any covered/dim/removal
    # classification -- each keeper inherits cov_mask_full/dim_mask_full True if ANY collapsed copy had it
    # (see dedupe_segments()).
    P, Q, mid, seg_len, seg_az, (cov_mask_full, dim_mask_full) = dedupe_segments(
        P, Q, mid, seg_len, seg_az, dup_tol_ft, PARALLEL_TOL_DEG, [cov_mask_full, dim_mask_full])
    covered_ft_pre_removal = float(seg_len[cov_mask_full].sum())

    x0, y0, x1, y1 = MAP_AREA
    mid_pt = inv(mid) if len(mid) else np.zeros((0, 2))
    W = page.rect.width

    frame_line = LineString(ground([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]))
    frame_buf = frame_line.buffer(frame_tol_ft)
    furniture_union = boxes_to_ground_union(frame_json.get("furniture", []), ground)

    _, circles = georef_segments(page)
    leader_paths, _ = checks_leaders(page, circles)
    leader_lines_ground = [LineString(ground(np.array([p0, p1]))) for p0, p1, _, _ in leader_paths]

    # defect 4 fix (leaders, retry): checks.leaders() requires an arrowhead/circle within 7 pt of the
    # path's own tip AND caps total stroked length at 120 pt -- a long straight/wedge leader off a
    # parcel/deed label (measured: Presidio's DK-046825-X1-X1/063269-X1-X1 wedges, 255-478 pt, drawn at
    # this drafter's 1.02 pt leader/lettering weight per checks.leaders()'s own docstring) clears neither
    # test and never enters leader_paths. Grounded instead in the drawing itself: a weighted() stroke at
    # the leader/lettering weight, with one end anchored at/inside a parcel/deed label's own box
    # (checks.label_box) and reaching well beyond that box (LEADER_REACH_MIN_PT -- separates a real wedge
    # from the label's own drawn box outline, also 0.84-0.99 pt and up to ~150 pt long, and from its
    # glyph strokes), and NOT collinear with the R/W class at that point -- confirmed by hand on both
    # sheets: a long diagonal near-vertical 0.84/1.98 pt line running to the label "46825 PARCEL 1" on
    # R-10434.3 (bearing S55'49"27"E printed beside it, an R/W corner) is real dimensioned boundary, not a
    # leader, and is correctly left alone by the weight + collinearity tests below.
    deed_labels = [b for b in blocks if PARCEL_DEED_RE.match(b["text"].strip())]
    label_leader_lines = []
    if deed_labels:
        rw_az = azimuth_arr(rw_Q - rw_P) if len(rw_P) else np.zeros(0)
        for ln, w in weighted:
            if not (LEADER_W_LO <= w <= LEADER_W_HI):
                continue
            coords = np.array(ln.coords)
            if len(coords) < 2:
                continue
            p0, p1 = coords[0], coords[-1]
            for b in deed_labels:
                c, u, n, hw, hh, gh = label_box(b)
                outs = [float(np.hypot(max(abs((pt - c) @ u) - hw, 0), max(abs((pt - c) @ n) - hh, 0))) for pt in (p0, p1)]
                if min(outs) > LABEL_ANCHOR_TOL_PT:
                    continue
                reach = max(float(np.hypot(*(pt - c))) for pt in coords)
                if reach < LEADER_REACH_MIN_PT:
                    continue
                # collinearity is judged over the WHOLE path's own densified length, not its start-end
                # chord -- a round-trip wedge (label -> far tip -> back near the label) has a near-zero
                # chord sitting right next to the corridor it points at, which a naive endpoint test reads
                # as "on R/W" every time (measured: Presidio's 2nd 063269-X1-X1 wedge, p0/p1 10.6 pt apart,
                # both a few ft off the highway R/W). A real R/W stroke instead sits on R/W for (near) its
                # whole own length.
                gline = LineString(ground(coords))
                gp, gq, gmid, glen, gaz = elementary_segments(gline, DENSIFY_FT)
                collinear_mask, _ = covered_mask(gmid, gaz, rw_P, rw_Q, rw_az, buffer_ft, PARALLEL_TOL_DEG)
                collinear_frac = float(glen[collinear_mask].sum() / glen.sum()) if glen.sum() > 0 else 0.0
                if collinear_frac < 0.5:
                    label_leader_lines.append(gline)
                break  # this stroke is claimed (or rejected as real R/W) by its nearest anchoring label

    label_leader_union = unary_union([ln.buffer(leader_tol_ft) for ln in label_leader_lines]) if label_leader_lines else None
    leader_union = unary_union([ln.buffer(leader_tol_ft) for ln in leader_lines_ground]) if leader_lines_ground else None
    leader_union = unary_union([u for u in (leader_union, label_leader_union) if u is not None]) \
        if (leader_union is not None or label_leader_union is not None) else None

    az_mod = seg_az % 180
    vertical = (az_mod < EDGE_COL_ANGLE_DEG) | (az_mod > 180 - EDGE_COL_ANGLE_DEG)
    near_edge = (np.abs(mid_pt[:, 0] - x0) < EDGE_COL_TOL_PT) | (np.abs(mid_pt[:, 0] - x1) < EDGE_COL_TOL_PT) if len(mid_pt) else np.zeros(len(mid), bool)

    # loop18 leg 1: ceiling class (e), at the source -- see TITLEBLOCK_RE/PRESIDIO_CONTAM_PT/
    # wedge_spike_mask() above. The point-radius test is restricted to LEADER_W_LO/HI stroke weight,
    # same as label_leader_lines above -- a flat point-radius over EVERY stroke measured 0.84 pt real
    # parcel/easement boundary and 0.72 pt table gridlines within reach of these 3 points (neither a
    # leader wedge); weight is what actually tells a wedge apart from real boundary here, not distance.
    titleblock_union = titleblock_region(blocks, ground)
    contam_pts_ground = ground(np.array(PRESIDIO_CONTAM_PT)) if sheet_name == "presidio" else np.zeros((0, 2))
    contam_tol_ground = PRESIDIO_CONTAM_TOL_PT * scale
    presidio_wedge_hit = np.zeros(len(mid), bool)
    if len(contam_pts_ground):
        wedge_lines = []
        for ln, w in weighted:
            if not (LEADER_W_LO <= w <= LEADER_W_HI):
                continue
            gc = ground(np.array(ln.coords))
            if np.hypot(*(gc[:, None, :] - contam_pts_ground[None, :, :]).transpose(2, 0, 1)).min() <= contam_tol_ground:
                wedge_lines.append(LineString(gc))
        if wedge_lines:
            presidio_wedge_union = unary_union([ln.buffer(leader_tol_ft) for ln in wedge_lines])
            presidio_wedge_hit = region_hit(presidio_wedge_union, mid)
    wedge_bend_hit = wedge_spike_mask(P, Q, mid, seg_len, seg_az, CHAIN_TOL_FT_SET, BEND_CONTAM_DEG, LOCAL_SPLIT_DEG_SET)

    removed_ft = {}
    protected_ft = {}
    remaining = np.ones(len(mid), bool)

    def apply(name, hit):
        # a segment cov_mask_full already marks "covered by a clean record edge" can never be removed as
        # contamination -- protects the invariant by construction instead of only detecting a violation
        # after the fact (measured need: R-10741.1's coordinate-callout leaders touch R/W vertices).
        protect = hit & remaining & cov_mask_full
        if protect.any():
            protected_ft[name] = round(float(seg_len[protect].sum()), 1)
        hit = hit & remaining & ~cov_mask_full
        removed_ft[name] = round(float(seg_len[hit].sum()), 1)
        remaining[hit] = False

    apply("frame", region_hit(frame_buf, mid) | region_hit(furniture_union, mid))
    apply("tables", region_hit(table_union, mid))
    removed_ft["tables"] = round(removed_ft["tables"] + dropped_face_ft, 1)  # + the isolated-face debris above
    apply("titleblock", region_hit(titleblock_union, mid))
    apply("matchline", (mid_pt[:, 0] < MATCHLINE_X0_PT) | (mid_pt[:, 0] > W - MATCHLINE_MARGIN_PT) if len(mid_pt) else np.zeros(len(mid), bool))
    apply("leader_wedge", region_hit(leader_union, mid))
    apply("wedge_residual", presidio_wedge_hit | wedge_bend_hit)
    apply("edge_column", vertical & near_edge)

    covered_ft = float(seg_len[remaining & cov_mask_full].sum())
    covered_invariance_diff = round(abs(covered_ft - covered_ft_pre_removal), 2)
    covered_invariance_diff_vs_raw = round(abs(covered_ft - covered_ft_baseline), 2)
    if covered_invariance_diff > 1e-6:
        print(f"WARNING: contamination removal changed covered ft by {covered_invariance_diff:.2f} "
              f"({covered_ft_pre_removal:.1f} -> {covered_ft:.1f}) -- a removal class deleted part of a "
              f"clean record edge's own covered stretch")
    if covered_invariance_diff_vs_raw > COVERED_INVARIANCE_TOL_FT:
        print(f"WARNING: covered ft vs the fully raw (no face-drop) boundary differs by "
              f"{covered_invariance_diff_vs_raw:.2f} ft ({covered_ft_baseline:.1f} -> {covered_ft:.1f})")

    drawn_ft = float(seg_len[remaining].sum())

    # dimensioned boundary: dim_mask_full was computed earlier (before dedup, then OR'd through it -- see
    # above module docstring section and the dedupe_segments() call). AND with remaining (post
    # contamination-removal), same as before.
    dim_mask = dim_mask_full & remaining
    dim_ft = float(seg_len[dim_mask].sum())
    dim_covered_ft = float(seg_len[dim_mask & cov_mask_full].sum())

    sens = buffer_sensitivity(mid[remaining], seg_az[remaining], seg_len[remaining], rec_P, rec_Q, rec_az,
                               [{"pt": p, "ft": p * scale} for p in (1.0, 1.5, 2.5)])

    # parcels reconstructed: per KEPT face (table/furniture debris faces are not parcel candidates),
    # >=99% covered (frame-touching faces excluded), closes <= 1 ft
    per_face = []
    for f in kept_faces:
        touches_frame = f["poly"].exterior.intersects(frame_buf)
        if touches_frame:
            per_face.append({"parcel": f["parcel"], "named": f["named"], "touches_frame": True,
                              "pct_covered": None, "closure_ft": None, "counts": False})
            continue
        pieces, pct, total_len = face_pieces(f["ring"], rec_P, rec_Q, rec_az, rec_parent, buffer_ft, PARALLEL_TOL_DEG, DENSIFY_FT)
        counts = False
        closure = None
        if pct >= CLOSE_PCT and total_len > 0:
            closure = face_closure(pieces, rec_edges)
            counts = closure <= CLOSURE_MAX_FT
        per_face.append({"parcel": f["parcel"], "named": f["named"], "touches_frame": False,
                          "pct_covered": round(pct * 100, 2), "closure_ft": round(closure, 2) if closure is not None else None,
                          "counts": counts})

    n_all, faces_all = sum(f["counts"] for f in per_face), len(per_face)
    dim_faces_list = [f for f in per_face if f["named"]]
    n_dim, faces_dim = sum(f["counts"] for f in dim_faces_list), len(dim_faces_list)

    result = {
        "sheet": sheet_name, "scale_ft_per_pt": scale,
        "buffer_pt": BUFFER_PT, "buffer_ft": buffer_ft, "parallel_tol_deg": PARALLEL_TOL_DEG,
        "rw_tol_ft": rw_tol_ft, "named_tol_ft": NAMED_TOL_FT, "frame_tol_ft": frame_tol_ft,
        "rw_added_ft": round(rw_added_ft, 1),
        "dropped_faces": {"n": len(dropped_faces), "ft": round(dropped_face_ft, 1)},
        "removed_ft": removed_ft,
        "protected_from_removal_ft": protected_ft,
        "covered_invariance": {"baseline_raw_ft": round(covered_ft_baseline, 1), "pre_removal_ft": round(covered_ft_pre_removal, 1),
                                "final_ft": round(covered_ft, 1), "diff_vs_pre_removal_ft": covered_invariance_diff,
                                "diff_vs_raw_ft": covered_invariance_diff_vs_raw},
        "drawn_boundary_ft": round(drawn_ft, 1),
        "reconstructed_edges": len(rec_edges), "traverse_rows": n_rows,
        "recon_all_covered_ft": round(covered_ft, 1), "recon_all_denom_ft": round(drawn_ft, 1),
        "recon_dim_covered_ft": round(dim_covered_ft, 1), "recon_dim_denom_ft": round(dim_ft, 1),
        "weight_classes": {str(w): {"count": c, "length_ft": round(l, 1)} for w, (c, l) in sorted(weights.items(), reverse=True)},
        "rw_weight": rw_w,
        "buffer_sensitivity_ft": {f"{p}pt": round(v, 1) for p, v in sens.items()},
        "parcels_all": {"n": n_all, "of": faces_all}, "parcels_dim": {"n": n_dim, "of": faces_dim},
        "faces": per_face,
        "edges": [{"name": e["name"], "az": round(e["az"], 4), "ft": e["ft"], "misfit_ft": e["misfit_ft"]} for e in rec_edges],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"recon{suffix}.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    Pf, Qf = P[remaining], Q[remaining]
    cov_final = cov_mask_full[remaining]
    dim_final = dim_mask_full[remaining]

    # loop18 leg 1: this sheet's own final elementary segments (ground ft, EPSG:2227 -- the same real-
    # world CRS every sheet's own `ground()` affine and load_faces()'s lon/lat->2227 transform both land
    # in, same as matchline.py/recon_ceiling.py's own cross-sheet neighbour tests already rely on), with
    # their covered/dimensioned flags -- consumed by recon_set.py to dedupe the SIX sheets' own drawn
    # boundary into one ground union without re-deriving each sheet's own removal/dedup pipeline.
    seg_out = {
        "sheet": sheet_name, "P": Pf.round(2).tolist(), "Q": Qf.round(2).tolist(),
        "seg_len_ft": seg_len[remaining].round(2).tolist(),
        "covered": cov_final.tolist(), "dimensioned": dim_final.tolist(),
    }
    (OUT / f"recon_segments{suffix}.json").write_text(json.dumps(seg_out, ensure_ascii=False), encoding="utf-8")

    if make_figures:
        make_figure(sheet_name, page, inv, Pf, Qf, cov_final, dim_final, buffer_ft)
        center = densest_cluster_center(rec_edges)
        if center is not None:
            center_pt = inv(center)[0]
            make_zoom_figure(sheet_name, page, inv, Pf, Qf, cov_final, dim_final, center_pt)

    pct_all = 100 * covered_ft / drawn_ft if drawn_ft else 0
    pct_dim = 100 * dim_covered_ft / dim_ft if dim_ft else 0
    print(f"recon_all {covered_ft:,.0f}/{drawn_ft:,.0f} ft ({pct_all:.1f}%) | "
          f"recon_dim {dim_covered_ft:,.0f}/{dim_ft:,.0f} ft ({pct_dim:.1f}%) | "
          f"parcels {n_all}/{faces_all} n_dim {n_dim}/{faces_dim} | rw_weight {rw_w} | "
          f"removed_ft {removed_ft} | dropped_faces {len(dropped_faces)} ({dropped_face_ft:.0f} ft)")
    if return_internals:
        # loop16 leg B (recon_attrib.py): the same arrays run() already computed, handed back instead of
        # recomputed -- no copy-paste of this function's own logic. Never touched by the normal call path
        # (return_internals defaults False, main() below never passes it), so recon.json / the two figures
        # this function writes are byte-identical to before this parameter existed.
        internals = {
            "page": page, "inv": inv, "ground": ground, "scale": scale, "buffer_ft": buffer_ft,
            "P": P, "Q": Q, "mid": mid, "seg_len": seg_len, "seg_az": seg_az, "remaining": remaining,
            "cov_mask_full": cov_mask_full, "dim_mask_full": dim_mask_full,
            "rec_edges": rec_edges, "rec_P": rec_P, "rec_Q": rec_Q, "rec_az": rec_az, "rec_parent": rec_parent,
            "kept_faces": kept_faces, "blocks": blocks,
        }
        return result, internals
    return result


def make_figure(sheet_name, page, inv, P, Q, cov_mask, dim_mask, buffer_ft):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    def to_pt_segs(A, B):
        if len(A) == 0:
            return []
        a, b = inv(A), inv(B)
        return list(zip(a.tolist(), b.tolist()))

    grey = to_pt_segs(P, Q)
    green = to_pt_segs(P[cov_mask], Q[cov_mask])
    red_mask = dim_mask & ~cov_mask
    red = to_pt_segs(P[red_mask], Q[red_mask])

    W, H = page.rect.width, page.rect.height
    px = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(px.samples, dtype=np.uint8).reshape(px.height, px.width)

    dpi = 150
    fig, ax = plt.subplots(figsize=(2000 / dpi, 2000 / dpi * H / W), dpi=dpi)
    ax.imshow(img, cmap="gray", extent=(0, W, H, 0), alpha=0.35)
    ax.add_collection(LineCollection(grey, colors="#555555", linewidths=0.9, alpha=1.0, label="drawn boundary"))
    ax.add_collection(LineCollection(red, colors="#e03030", linewidths=1.3, label="dimensioned, not reconstructed"))
    ax.add_collection(LineCollection(green, colors="#2ca02c", linewidths=1.3, label="reconstructed (covered)"))
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.set_aspect("equal")
    ax.set_title(f"{sheet_name}: reconstructable boundary (buffer {buffer_ft:.2f} ft)")
    ax.legend(loc="lower right", fontsize=7)
    ax.axis("off")
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT_RECON / f"{sheet_name}_recon.png")
    plt.close(fig)


def make_zoom_figure(sheet_name, page, inv, P, Q, cov_mask, dim_mask, center_pt):
    """~ZOOM_PT x ZOOM_PT pt window centred on the record edges' own densest cluster, rendered at
    ZOOM_SCALE so a human can check whether green sits directly on the drawn line."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    W, H = page.rect.width, page.rect.height
    half = ZOOM_PT / 2
    cx, cy = float(center_pt[0]), float(center_pt[1])
    bx0, bx1 = max(cx - half, 0), min(cx + half, W)
    by0, by1 = max(cy - half, 0), min(cy + half, H)
    if bx1 <= bx0 or by1 <= by0:
        return
    px = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM_SCALE, ZOOM_SCALE), clip=pymupdf.Rect(bx0, by0, bx1, by1), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(px.samples, dtype=np.uint8).reshape(px.height, px.width)

    def to_pt_segs(A, B):
        if len(A) == 0:
            return []
        a, b = inv(A), inv(B)
        return list(zip(a.tolist(), b.tolist()))

    grey = to_pt_segs(P, Q)
    green = to_pt_segs(P[cov_mask], Q[cov_mask])
    red_mask = dim_mask & ~cov_mask
    red = to_pt_segs(P[red_mask], Q[red_mask])

    fig, ax = plt.subplots(figsize=(9, 9), dpi=150)
    ax.imshow(img, cmap="gray", extent=(bx0, bx1, by1, by0))
    ax.add_collection(LineCollection(grey, colors="#555555", linewidths=1.4, alpha=1.0, label="drawn boundary"))
    ax.add_collection(LineCollection(red, colors="#e03030", linewidths=2.2, label="dimensioned, not reconstructed"))
    ax.add_collection(LineCollection(green, colors="#2ca02c", linewidths=2.2, label="reconstructed (covered)"))
    ax.set_xlim(bx0, bx1); ax.set_ylim(by1, by0); ax.set_aspect("equal")
    ax.set_title(f"{sheet_name}: zoom on densest record-edge cluster")
    ax.legend(loc="lower right", fontsize=7)
    ax.axis("off")
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT_RECON / f"{sheet_name}_recon_zoom.png")
    plt.close(fig)


def selftest():
    """Synthetic 100x100 ft square: a full, unflagged 4-edge record closes and counts; a parallel
    line 3 pt (~4.17 ft on a 1.389 ft/pt sheet) away from a reconstructed edge is not covered."""
    scale = 1.38885
    buffer_ft = BUFFER_PT * scale  # ~2.08 ft
    sq = np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]])
    rec_edges = []
    for i in range(4):
        p, q = sq[i], sq[i + 1]
        az = azimuth_arr(q - p)
        rec_edges.append({"name": f"e{i}", "az": float(az), "ft": float(np.hypot(*(q - p))), "misfit_ft": 0.1, "p": p, "q": q, "kind": "line"})
    rec_P, rec_Q, rec_az, rec_parent = rec_segments(rec_edges)

    # 1. the square itself: fully covered, closes at 0
    ring = sq
    pieces, pct, total_len = face_pieces(ring, rec_P, rec_Q, rec_az, rec_parent, buffer_ft, PARALLEL_TOL_DEG, DENSIFY_FT)
    assert pct >= 0.999, f"square should be ~100% covered, got {pct:.3f}"
    closure = face_closure(pieces, rec_edges)
    assert closure < 0.01, f"square record walk should close at 0, got {closure}"

    # 1b. loop17 leg A: a stray digitizing vertex splits ONE record edge's own covered stretch into
    # two ring pieces (both majority-voting to the same rec_edges index) -- face_closure must not add
    # that edge's full record vector twice (Presidio 61806-9: a real 138 ft course split this way read
    # closure as 162 ft off a fully-record-walked parcel; the fix walks a repeat occurrence by its own
    # drawn vector, not the record edge's length again).
    kink_pieces = [(0, sq[0], sq[1]), (1, sq[1], sq[2]),
                   (2, sq[2], np.array([50.0, 100.0])), (2, np.array([50.0, 100.0]), sq[3]),
                   (3, sq[3], sq[4])]
    kink_closure = face_closure(kink_pieces, rec_edges)
    assert kink_closure < 0.01, f"a record edge split into two ring pieces by a stray vertex must not be double-counted, got {kink_closure}"

    # 1c. loop17 leg B: a short out-and-back spike (2 pieces, uncovered on their own -- not parallel to
    # any record edge) sandwiched between two pieces of the SAME record edge is bridged to that edge
    # (Presidio 61806-9: an 8 ft spike in the middle of a 138 ft record course read the parcel 98.06%
    # covered, one edge under CLOSE_PCT; fixed to 100%, closes). A ring with a real vertex there (edge 0
    # subdivided) plus a tiny 2 ft spike poking off it, both sides voting edge 0.
    kink_ring = np.array([[0.0, 0.0], [40.0, 0.0], [40.0, -2.0], [42.0, -2.0], [42.0, 0.0], [100.0, 0.0],
                           [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]])
    kpieces, kpct, _ = face_pieces(kink_ring, rec_P, rec_Q, rec_az, rec_parent, buffer_ft, PARALLEL_TOL_DEG, DENSIFY_FT)
    assert kpct >= 0.999, f"a short spike flanked by the same edge on both sides must be bridged, got pct {kpct:.3f}"
    assert all(k == 0 for k, p, q in kpieces[1:5]), f"the bridged spike pieces must carry the flanking edge's own index, got {[k for k, p, q in kpieces[1:5]]}"
    # a spike between two DIFFERENT edges (edge 0 and edge 1) must never be bridged
    diff_ring = np.array([[0.0, 0.0], [98.0, 0.0], [98.0, -2.0], [100.0, -2.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]])
    dpieces, dpct, _ = face_pieces(diff_ring, rec_P, rec_Q, rec_az, rec_parent, buffer_ft, PARALLEL_TOL_DEG, DENSIFY_FT)
    assert dpct < 0.999, "a spike between two different edges must not be bridged"

    # 2. a line offset 3 pt (~4.17 ft) parallel to the south edge: outside the buffer, not covered
    off = 3.0 * scale
    p, q = np.array([0.0, -off]), np.array([100.0, -off])
    mid = np.array([(p + q) / 2])
    seg_az = azimuth_arr(q - p) * np.ones(1)
    any_match, _ = covered_mask(mid, seg_az, rec_P, rec_Q, rec_az, buffer_ft, PARALLEL_TOL_DEG)
    assert not any_match[0], "a line 3 pt off a reconstructed edge must not be covered"

    # 3. sanity: the same offset line at 1.0 pt IS within buffer (buffer itself works)
    off2 = 1.0 * scale
    p2, q2 = np.array([0.0, -off2]), np.array([100.0, -off2])
    mid2 = np.array([(p2 + q2) / 2])
    any_match2, _ = covered_mask(mid2, seg_az, rec_P, rec_Q, rec_az, buffer_ft, PARALLEL_TOL_DEG)
    assert any_match2[0], "a line 1 pt off a reconstructed edge should be covered at the 1.5 pt buffer"

    # 4. loop16 leg A retry: R/W linework that is NOT part of any face's own boundary must still enter
    # the drawn-boundary denominator once unioned in (defect 1, R-10741.1) -- a disjoint face ring and a
    # disjoint R/W line, unioned, keep both lengths (no clipping/absorption just from being unioned).
    face_ring = LineString(sq)
    rw_line = LineString([[500.0, 0.0], [600.0, 0.0]])  # far away, touches nothing
    merged = unary_union([face_ring, rw_line])
    assert abs(merged.length - (face_ring.length + rw_line.length)) < 1e-6, \
        "R/W linework absent from every face must still enter the denominator once unioned into the drawn boundary"

    # 5. the R/W weight-class rule rejects a numerically heavier 1-line/118 ft "class" in favour of a
    # lighter class that actually clears RW_MIN_COUNT/RW_MIN_FT (R-10741.1, measured)
    weights_stray = {2.28: [1, 118.0], 1.68: [8, 12253.0]}
    assert pick_rw_class(weights_stray) == 1.68, "a 1-line 118 ft class must not outrank a real R/W class"
    weights_short = {2.0: [3, 800.0], 1.5: [10, 5000.0]}  # 3 lines but under RW_MIN_FT=1000
    assert pick_rw_class(weights_short) == 1.5, "a class under RW_MIN_FT must be rejected even with enough lines"

    # 6. loop16 leg A3: an R/W-weight rectangle (a table's own frame stroke) sitting just outside a table's
    # un-grown region, but inside it once grown by TABLE_REGION_GROW_PT, must never enter the drawn-boundary
    # denominator -- Presidio's CURVE DATA TABLE(1) frame sits 10-25 pt above its own tables.json region.
    tbl_region = [100.0, 100.0, 140.0, 140.0]  # snug region, page pt: [x0, y0, x1, y1]
    frame_rect = LineString([(100.0, 85.0), (140.0, 85.0)])  # the table's title-bar top stroke, 15 pt above
    grown = [grow_box(tbl_region, TABLE_REGION_GROW_PT)]
    assert not in_any_box(frame_rect.centroid.coords[0], [tbl_region]), "sanity: the un-grown region must miss the frame stroke"
    assert in_any_box(frame_rect.centroid.coords[0], grown), "a table frame stroke 15 pt outside its own region must fall inside once grown"

    # 7. loop16 leg C: dedupe_segments() collapses two near-coincident parallel strokes into one count
    # (0.5 pt apart, well under DUP_TOL_PT), but leaves two strokes 10 pt apart as two (well over it).
    dup_tol_ft = DUP_TOL_PT * scale
    line_a = LineString([[0.0, 0.0], [100.0, 0.0]])

    off_close = 0.5 * scale
    merged_close = unary_union([line_a, LineString([[0.0, off_close], [100.0, off_close]])])
    Pc, Qc, midc, seg_lenc, seg_azc = elementary_segments(merged_close, DENSIFY_FT)
    _, _, _, seg_lenk, _, _ = dedupe_segments(Pc, Qc, midc, seg_lenc, seg_azc, dup_tol_ft, PARALLEL_TOL_DEG, [])
    assert abs(seg_lenk.sum() - 100.0) < 1.0, \
        f"two strokes 0.5 pt apart should collapse to one ~100 ft line, got {seg_lenk.sum():.1f} ft"

    off_far = 10.0 * scale
    merged_far = unary_union([line_a, LineString([[0.0, off_far], [100.0, off_far]])])
    Pf2, Qf2, midf2, seg_lenf2, seg_azf2 = elementary_segments(merged_far, DENSIFY_FT)
    _, _, _, seg_lenk2, _, _ = dedupe_segments(Pf2, Qf2, midf2, seg_lenf2, seg_azf2, dup_tol_ft, PARALLEL_TOL_DEG, [])
    assert abs(seg_lenk2.sum() - 200.0) < 1.0, \
        f"two strokes 10 pt apart should stay two ~200 ft total, got {seg_lenk2.sum():.1f} ft"

    # 7b. a collapsed duplicate's own mask flag must survive, OR'd into the keeper -- not silently dropped.
    mask_b_only = midc[:, 1] > 0.01  # true only for the offset (line_b) copy's own segments
    _, _, _, _, _, (mask_k,) = dedupe_segments(Pc, Qc, midc, seg_lenc, seg_azc, dup_tol_ft, PARALLEL_TOL_DEG, [mask_b_only])
    assert mask_k.all(), "a duplicate segment's own mask flag must be OR'd into the surviving keeper"

    # 8. loop16 leg E: an arc's own coverage buffer follows its drawn CURVE, not its chord --
    # rec_segments() emits one small sub-segment per pair of the row's own drawn "pts", each with its
    # own local direction, so a point ON the curve is covered but the straight chord between its ends
    # (which bows well away from a real arc) is not.
    R_arc, delta_arc = 100.0, 90.0
    tt = np.linspace(0.0, 1.0, 21)
    ang = np.radians(180.0 - delta_arc * tt)
    ctr = np.array([R_arc, 0.0])
    arc_pts = ctr + R_arc * np.c_[np.cos(ang), np.sin(ang)]
    chord_ft = 2 * R_arc * math.sin(math.radians(delta_arc) / 2)
    chord_az = float(azimuth_arr(arc_pts[-1] - arc_pts[0]))
    arc_rec_edges = [{"name": "C-test", "az": chord_az, "ft": chord_ft, "misfit_ft": 0.1,
                       "p": arc_pts[0], "q": arc_pts[-1], "kind": "arc", "pts": arc_pts}]
    arc_rec_P, arc_rec_Q, arc_rec_az, _ = rec_segments(arc_rec_edges)

    on_curve_mid = np.array([(arc_pts[10] + arc_pts[11]) / 2])
    on_curve_az = azimuth_arr(np.array([arc_pts[11] - arc_pts[10]]))
    on_curve_match, _ = covered_mask(on_curve_mid, on_curve_az, arc_rec_P, arc_rec_Q, arc_rec_az, buffer_ft, PARALLEL_TOL_DEG)
    assert on_curve_match[0], "a point on the arc's own drawn curve must be covered"

    chord_mid = np.array([(arc_pts[0] + arc_pts[-1]) / 2])
    chord_seg_az = azimuth_arr(np.array([arc_pts[-1] - arc_pts[0]]))
    chord_match, _ = covered_mask(chord_mid, chord_seg_az, arc_rec_P, arc_rec_Q, arc_rec_az, buffer_ft, PARALLEL_TOL_DEG)
    assert not chord_match[0], "the straight chord between the arc's own ends must NOT be covered by its curve-following buffer"

    print("selftest OK: full square closes and counts; a record edge split by a stray vertex into two "
          "ring pieces is not double-counted; a short spike flanked by the same edge on both sides is "
          "bridged to it, a spike between two different edges is not; "
          "3 pt offset line not covered; 1 pt offset covered; "
          "an arc's own curve is covered but its chord is not; "
          "un-faced R/W linework still enters the denominator; RW class rule rejects a stray heavier class; "
          "a grown table region catches its own frame stroke; dedupe collapses 0.5 pt duplicates but keeps "
          "10 pt-apart strokes separate, and OR's a collapsed copy's mask flag into its keeper")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    sheet_name = "presidio" if PDF == DEFAULT else PDF.stem
    if "--no-inverse" in sys.argv:
        # loop18 leg 2: the "without inverse" comparison, to a separate file pair -- never touches the
        # normal recon.json/recon_segments.json/figures a plain run writes.
        run(sheet_name, exclude_inverse=True, make_figures=False, suffix="_no_inverse")
    else:
        run(sheet_name)


if __name__ == "__main__":
    main()
