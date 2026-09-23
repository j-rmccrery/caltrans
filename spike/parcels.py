"""Parcel polygons from the sheet's heavy linework, checked against the parcel table.

Heavy lines (R/W and parcel boundaries) plus the map border are noded and polygonised; every face
is a candidate parcel. A parcel-number label inside a face names it. Each named face's area
(through the georeferencing fit) is compared with the area printed in the parcel table: a second
deterministic check that touches the whole figure, not one line.
Output: parcels.geojson (lon/lat, WGS84-compatible NAD83(2011)) and a printed area table.
usage: [SHEET=<pdf>] python spike/parcels.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping
from shapely.ops import polygonize, unary_union

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, READS, PDF, real_text_blocks  # noqa: E402
from overlay import MAP_AREA, bezier  # noqa: E402

PARCEL = re.compile(r"^(DK-)?(\d{5})(-\d)?$")
SQFT_PER_ACRE = 43560.0
# parcel table on R-10434.2, keyed by hand for the check (areas printed in acres / square feet)
TABLE_AREA = {"61806-2": ("AC", 7.21), "61806-4": ("AC", 3.34), "61806-5": ("AC", 5.27), "61806-9": ("SF", 6970),
              "61985-1": ("SF", 2518), "61985-2": ("SF", 15372), "61985-3": ("SF", 49552), "61985-4": ("SF", 3248), "63269": ("AC", 11.45)}


def heavy_lines(page):
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
        # R/W lines are 1.98; parcel and easement boundaries share the 0.84 weight with leaders and
        # text, so only long 0.84 paths count. Centreline and hatch edges (0.72) are not boundaries.
        total = sum(np.hypot(it[2].x - it[1].x, it[2].y - it[1].y) for it in d["items"] if it[0] == "l") +             sum(np.hypot(it[4].x - it[1].x, it[4].y - it[1].y) for it in d["items"] if it[0] == "c")
        if w == 0 or total < 12 or (w < 0.8 and total < 40) or max(r.width, r.height) <= 12:
            continue  # fills, characters, short thin leaders. ponytail: admitting the dashed easement strips
            # (single short strokes) also admits stationing ticks and hatch edges and shatters the corridor
            # into 70 faces; easement strips want a traverse from the line table instead
        if d["closePath"] and r.width < 90 and r.height < 24:
            continue  # the rounded box drawn around a parcel number is not a boundary
        pts = []
        for it in d["items"]:
            if it[0] == "l":
                seg = [(it[1].x, it[1].y), (it[2].x, it[2].y)]
            elif it[0] == "c":
                seg = [tuple(p) for p in bezier(*[np.array([p.x, p.y]) for p in it[1:5]])]
            else:
                continue
            if pts and np.hypot(pts[-1][0] - seg[0][0], pts[-1][1] - seg[0][1]) > 0.5:
                out.append(LineString(pts)); pts = []
            pts = (pts[:-1] if pts else []) + seg
        if len(pts) > 1:
            out.append(LineString(pts))
    return out


def close_gaps(lines, gap):
    from shapely.ops import nearest_points
    from shapely.strtree import STRtree
    tree = STRtree(lines)
    extra = []
    for i, ln in enumerate(lines):
        for end in (Point(ln.coords[0]), Point(ln.coords[-1])):
            best = None
            for j in tree.query(end.buffer(gap)):
                if j == i:
                    continue
                d = lines[j].distance(end)
                if 0.05 < d < gap and (best is None or d < best[0]):
                    best = (d, lines[j])
            if best:
                extra.append(LineString([end, nearest_points(end, best[1])[1]]))
    return lines + extra


OVALS = [(1366, 881), (1202, 837), (1221, 782), (1035, 762)]  # 61985-1..4 leader ovals (measured, STATE.md 2026-09-23)


def strip_lines(page, radius=260.0):
    """The dashed easement line (dashes.py) near the four tunnel easements, each train clipped to a
    radius around its own oval. dashes.dedupe already drops the near-duplicate parallel chains that
    were carving 61985-2/-3 into slivers 73-85% too small; this clip keeps a train's far end -- past
    61806-4's own easement, further up the same corridor -- out of the polygonisation, so it cannot
    subdivide a neighbour's parcel that this spike does not otherwise touch."""
    from dashes import collect_dashes, dash_trains
    trains = [LineString(t["pts"]) for t in dash_trains(collect_dashes(page))]
    zone = unary_union([Point(o).buffer(radius) for o in OVALS])
    out = []
    for ln in trains:
        clipped = ln.intersection(zone)
        if clipped.is_empty:
            continue
        geoms = clipped.geoms if hasattr(clipped, "geoms") else [clipped]
        out += [g for g in geoms if g.geom_type == "LineString" and g.length > 3]
    return out


def strip_cross_lines(page):
    """Leg B attempt 2, Build step 1: every short stroke (5-60 pt, any width) in the strip region (x
    950-1720, y 600-850) whose two ends are each within 3 pt of the north boundary (dashes.py's longest
    train, coincident with the heavy R/W line) and the south boundary (the next four trains chained end
    to end -- see strip_boundary) -- i.e. a drawn cross-tie between them. Also checks every printed
    distance/arc label whose drawn line falls in the strip region, the candidates the task names (24.23',
    76.46', 22.32', 50.48', 62.27', 73.82', 44.49', and the L= curve labels): each one's *entire* matched
    polyline (not just its endpoints) is tested against both boundaries, since a chord that merely grazes
    one end of a curve would otherwise look like a hit. None of these was found to touch both -- every one
    of them sits on the north boundary throughout (< 1.5 pt at every sampled point); the R-5..R-9 curve-
    data circles near the corridor are also on north, not south. Returns the list of found true cross-ties
    (empty here) and the diagnostic rows for the checked candidates, for the caller to print."""
    from dashes import collect_dashes, dash_trains
    trains = sorted(dash_trains(collect_dashes(page)), key=lambda t: -t["len_pt"])
    if len(trains) < 8:
        return [], []
    north = LineString(trains[0]["pts"])
    south = LineString(list(trains[2]["pts"]) + list(trains[6]["pts"]) + list(trains[1]["pts"]) + list(trains[5]["pts"]))
    x0, y0, x1, y1 = 950, 600, 1720, 850
    SCALE = 1.38885
    strokes = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] != "l":
                continue
            pa, pb = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
            L = float(np.hypot(*(pb - pa)))
            cx, cy = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
            if 5 <= L <= 60 and x0 < cx < x1 and y0 < cy < y1:
                dNa, dSb = north.distance(Point(pa)), south.distance(Point(pb))
                dNb, dSa = north.distance(Point(pb)), south.distance(Point(pa))
                if (dNa < 3 and dSb < 3) or (dNb < 3 and dSa < 3):
                    strokes.append((pa, pb, L * SCALE))
    labels = json.loads((OUT / "labels.json").read_text(encoding="utf-8")) if (OUT / "labels.json").exists() else []
    strip_region = lambda b: b and 950 < (b[0] + b[2]) / 2 < 1720 and 600 < (b[1] + b[3]) / 2 < 950
    diag = []
    for x in labels:
        if x["kind"] not in ("distance", "arc"):
            continue
        pts = [Point(p) for p in x["line"]]
        if not any(950 < p.x < 1720 and 600 < p.y < 900 for p in pts):
            continue
        dn = [north.distance(p) for p in pts]
        ds = [south.distance(p) for p in pts]
        diag.append((x["printed"], x["ok"], max(dn), max(ds), min(dn), min(ds)))
    return strokes, diag


def strip_boundary(page):
    """North (R/W, dashed twin) and south (dashed offset) boundaries of the 61985 tunnel-easement strip,
    from dashes.py's trains (STATE.md leg B attempt 2): the single longest train is north; the south
    boundary is the next four trains by length, chained west to east (verified end to end within a few
    pt -- green train[2] -> pink train[6] -> orange train[1] -> brown train[5]); the two shortest trains
    close the gap between north's west tip and south's west tip (west closure). Returns (north_pts,
    south_pts) west to east in sheet pt, or None if the sheet has no dash trains."""
    from dashes import collect_dashes, dash_trains
    trains = sorted(dash_trains(collect_dashes(page)), key=lambda t: -t["len_pt"])
    if len(trains) < 8:
        return None
    north = list(trains[0]["pts"])[::-1]  # west -> east
    south = list(trains[2]["pts"]) + list(trains[6]["pts"]) + list(trains[1]["pts"]) + list(trains[5]["pts"])
    return north, south


def strip_faces(page):
    """The 61985-1..4 tunnel-easement strip, built by construction (Leg B attempt 2) instead of
    polygonising: north boundary + east closure + south boundary (reversed) + west closure. No drawn
    cross-tie between north and south was found anywhere in the strip (strip_cross_lines, called by the
    caller for the diagnostic printout) -- every nearby R=/Δ=/L= curve-data block and every short
    printed distance in the corridor traces the *north* boundary throughout its matched line, not a tie
    to south, and the R-5..R-9 vertex circles are on north too. The four easements' individual divisions
    are therefore not independently constructible from this drawing's vector geometry -- only the combined
    four-easement envelope closes. Returns one feature covering all four names, "how": "strip"; the east
    and west end closures are straight constructed lines (no drawn stroke found for either), same as the
    task's own fallback for an unfound cross-tie."""
    b = strip_boundary(page)
    if b is None:
        return []
    north, south = b
    poly_pts = north + south[::-1] + [north[0]]
    return [{"pts": poly_pts, "parcel": "61985-1|61985-2|61985-3|61985-4", "how": "strip",
             "note": "combined envelope only -- no drawn cross-tie divides the four easements (strip_cross_lines); "
                     "see spike/out/legB_61985.png"}]


def faces_on_sheet(page, strips=False):
    """Candidate parcels: the heavy linework plus the border, noded and polygonised. strips=True adds
    the dashed easement line's trains (strip_lines) -- off by default: even after dedupe(), the
    surviving trains near the 61985 corridor still cross the heavy R/W line and each other rather than
    running cleanly parallel to it (STATE.md leg B), so polygonising them in gives 61985-2/-3 as
    slivers 90-97% too small instead of leaving them absent -- worse than the honest gap."""
    lines = heavy_lines(page) + (strip_lines(page) if strips else [])
    x0, y0, x1, y1 = MAP_AREA
    border = LineString([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])
    # lines stop short of point-symbol circles and of each other by a few pt: bridge every loose end
    # to the nearest other line within GAP so the figure closes
    lines = close_gaps(lines + [border], gap=9.0)
    noded = unary_union(lines)  # nodes every crossing so faces close
    faces = [f for f in polygonize(noded) if f.area > 400]  # ignore slivers (< ~800 sq ft)
    faces = [f for f in faces if f.bounds[3] - f.bounds[1] > 26 or f.bounds[2] - f.bounds[0] > 130]  # not a parcel-number box (78 x 20 pt)
    print(f"heavy polylines {len(lines)} | faces {len(faces)}")
    return faces


def face_names(page, faces, blocks):
    """{face index: [parcel numbers]}: a label with a leader names the face the leader tip lands in
    (tunnel easements, small strips, labels pulled clear of their own face for readability), else the
    face the label sits in. Leaders: `checks.leaders` (curly stroked paths to a filled arrowhead or a
    point-symbol circle -- the drafter's actual leader convention here) via `checks.tag_leaders` (each
    leader claimed by the nearest label box, same machinery tables.py uses for the line/curve tags);
    `georef.trace_leader` (built for two-row N/E coordinate callouts) is a second pass for whatever a
    parcel-number oval's leader does not read as, in case its plain-box fallback catches a different one."""
    from scipy.spatial import cKDTree
    from georef import segments, trace_leader
    from checks import leaders as checks_leaders, tag_leaders

    labels = [(m.group(0), Point(bl["cx"], bl["cy"])) for bl in blocks for m in [PARCEL.match(bl["text"].replace(" ", ""))] if m and not bl.get("real")]
    label_blocks = [bl for bl in blocks if PARCEL.match(bl["text"].replace(" ", "")) and not bl.get("real")]

    segs, circles = segments(page)
    ends = np.array([q for s0, s1, _, _ in segs for q in (s0, s1)])
    idx = [(k, e) for k in range(len(segs)) for e in (0, 1)]
    tree = cKDTree(ends)
    paths, _ = checks_leaders(page, circles)
    tips = tag_leaders(blocks, paths)  # {index into blocks: (arrowhead/circle tip, direction)}

    def name_by_tip(bl, tip):
        pt = Point(tip)
        hit = [i for i, f in enumerate(faces) if f.buffer(3).contains(pt) and not f.contains(Point(bl["cx"], bl["cy"]))]
        return min(hit, key=lambda i: faces[i].area) if hit else None

    by_leader, resolved = {}, set()  # resolved: label instances (by id) already placed, one shot each
    for bl in label_blocks:
        name = PARCEL.match(bl["text"].replace(" ", "")).group(0)
        bi = blocks.index(bl)
        fi = name_by_tip(bl, tips[bi][0]) if bi in tips else None
        if fi is None:  # this drafter's arrowhead/circle leader wasn't there: try the callout tracer
            for tip in (trace_leader({"nb": bl, "eb": bl}, segs, tree, idx) or [])[::-1]:  # farthest first
                fi = name_by_tip(bl, tip)
                if fi is not None:
                    break
        if fi is not None:
            by_leader.setdefault(fi, []).append(name)
            resolved.add(id(bl))
    print(f"labels naming a face through a leader: {sum(len(v) for v in by_leader.values())}; labels placed {len(labels)}")

    # neither leader found: many parcel-number ovals are just nudged clear of their own face for
    # readability, no leader drawn at all (checked: touching or a few pt off, next-nearest face
    # 90-150 pt away -- not ambiguous). Each drawn occurrence of a number gets its own shot -- the same
    # number can label two different, non-contiguous slivers of one parcel.
    NEAR = 15.0  # pt
    for bl in label_blocks:
        if id(bl) in resolved:
            continue
        name = PARCEL.match(bl["text"].replace(" ", "")).group(0)
        p = Point(bl["cx"], bl["cy"])
        if any(f.contains(p) for f in faces):
            continue  # the plain-containment fallback below already gets this one
        d = sorted((f.distance(p), i) for i, f in enumerate(faces))
        if d and d[0][0] < NEAR:
            by_leader.setdefault(d[0][1], []).append(name)
            resolved.add(id(bl))

    # a label whose nearest touch is the sheet's one or two huge background faces (the whole corridor,
    # never subdivided without the dashed easement lines) can still sit right beside a small, genuinely
    # distinct sliver a bit further off: name that one too, evidence added not swapped, small faces only
    # so this never reaches for the background face itself
    NEAR2, SMALL_FACE = 70.0, 50_000.0  # pt, sq pt (~1.1 ac at this scale -- well under the corridor faces)
    for bl in label_blocks:
        name = PARCEL.match(bl["text"].replace(" ", "")).group(0)
        p = Point(bl["cx"], bl["cy"])
        for dist, fi in sorted((f.distance(p), i) for i, f in enumerate(faces)):
            if dist >= NEAR2:
                break
            if faces[fi].area < SMALL_FACE and name not in by_leader.get(fi, []):
                by_leader.setdefault(fi, []).append(name)
                resolved.add(id(bl))
    print(f"labels naming a face total (leader + proximity, within {NEAR:.0f}/{NEAR2:.0f} pt): {len(resolved)}")
    # union, not "leader result or plain containment": a face a leader names for one label can still be
    # the face a different label's own position simply sits inside (both are real evidence)
    return {fi: sorted(set(by_leader.get(fi, []) + [n for n, p in labels if f.contains(p)])) for fi, f in enumerate(faces)}


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, b, tx, ty = g["params"]
    faces = faces_on_sheet(page)
    blocks = json.loads((READS).read_text(encoding="utf-8")) + real_text_blocks(page)
    names_of = face_names(page, faces, blocks)
    to_ll = Transformer.from_crs("EPSG:2227", "EPSG:6318", always_xy=True)

    def ground(xy):
        sx, sy = np.asarray(xy)[:, 0], -np.asarray(xy)[:, 1]
        E, N = a * sx - b * sy + tx, b * sx + a * sy + ty
        return E, N

    feats, rows = [], []
    for fi, f in enumerate(faces):
        names = names_of[fi]
        E, N = ground(np.array(f.exterior.coords))
        area_sf = 0.5 * abs(np.dot(E[:-1], N[1:]) - np.dot(N[:-1], E[1:]))
        lon, lat = to_ll.transform(E, N)
        name = names[0] if len(names) == 1 else ("|".join(names) if names else "")
        props = {"parcel": name, "area_sqft": round(area_sf, 1), "area_acres": round(area_sf / SQFT_PER_ACRE, 3), "labels_inside": len(names)}
        if name in TABLE_AREA:
            unit, want = TABLE_AREA[name]
            want_sf = want if unit == "SF" else want * SQFT_PER_ACRE
            props.update(table_area_sqft=want_sf, diff_pct=round((area_sf - want_sf) / want_sf * 100, 2))
            rows.append((name, area_sf, want_sf))
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Polygon", "coordinates": [[[round(x, 8), round(y, 8)] for x, y in zip(lon, lat)]]}})

    # leg B attempt 2: the 61985 tunnel-easement strip, by construction (strip_faces), a separate pass
    # after the polygonised faces above. strip_cross_lines is the Build-step-1 search for a drawn
    # cross-tie between the strip's north and south boundaries -- print what it found (none) so the
    # search is visible every run, not just in STATE.md.
    strokes, diag = strip_cross_lines(page)
    print(f"strip cross-tie strokes found (touch both north and south within 3 pt): {len(strokes)}")
    print(f"{'label':10} {'ok':5} {'minDn':>7} {'maxDn':>7} {'minDs':>7} {'maxDs':>7}  (pt, over the whole matched line)")
    for printed, ok, maxdn, maxds, mindn, minds in diag:
        print(f"{printed:10} {str(ok):5} {mindn:7.1f} {maxdn:7.1f} {minds:7.1f} {maxds:7.1f}")
    for sf in strip_faces(page):
        E, N = ground(np.array(sf["pts"]))
        area_sf = 0.5 * abs(np.dot(E[:-1], N[1:]) - np.dot(N[:-1], E[1:]) + E[-1] * N[0] - N[-1] * E[0])
        lon, lat = to_ll.transform(E, N)
        table_sf = sum(v if u == "SF" else v * SQFT_PER_ACRE for u, v in
                        (TABLE_AREA[n] for n in ("61985-1", "61985-2", "61985-3", "61985-4")))
        props = {"parcel": sf["parcel"], "how": sf["how"], "note": sf["note"],
                  "area_sqft": round(area_sf, 1), "area_acres": round(area_sf / SQFT_PER_ACRE, 3),
                  "table_area_sqft": table_sf, "diff_pct": round((area_sf - table_sf) / table_sf * 100, 2)}
        print(f"strip combined envelope: {area_sf:,.0f} sq ft vs table sum {table_sf:,.0f} sq ft ({props['diff_pct']:+.1f}%)")
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Polygon", "coordinates": [[[round(x, 8), round(y, 8)] for x, y in zip(lon, lat)]]}})

    (OUT / "parcels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    named = [f for f in feats if f["properties"]["parcel"]]
    print(f"named faces {len(named)} of {len(feats)}")
    print(f"{'parcel':10} {'drawn sq ft':>12} {'table sq ft':>12} {'diff':>8}")
    for name, got, want in sorted(rows):
        print(f"{name:10} {got:12,.0f} {want:12,.0f} {(got - want) / want * 100:+7.2f}%")
    unnamed_big = sorted((f["properties"]["area_acres"] for f in feats if not f["properties"]["parcel"]), reverse=True)[:5]
    print("largest unnamed faces (acres):", unnamed_big)


if __name__ == "__main__":
    main()
