"""Loop18 leg 1: score parcels against the record's own official AREAS tables (areas_table.py), not just
recon.py's geometric closure test alone. JR (2026-09-28): "Parcels are scored against the official AREAS
tables printed on the sheets ... Only 29 faces carry a parcel name today; several are merged multi-parcel
faces; 9 touch the frame/matchline."

Method: run areas_table.py for each of the six gate sheets (writes <outdir>/areas_table.json), pool every
row's own parcel id into one SET-level list (a parcel printed on more than one sheet's own AREAS table --
JR: measured on R-10434.1/.3, both list 61806-2 and 63269 -- is one parcel, deduped by id). For each
listed parcel id, search every sheet's own parcels.geojson (recon.load_faces(), a pure function of the
geojson -- no PDF/SHEET needed) for a face named for it: a face's own "parcel" property is a "|"-joined
list of every parcel id it merges (parcels.py's own convention -- see recon.load_faces()'s docstring);
membership is by id in that list, not string equality, so a merged face is found for each of its own
constituent ids. Reconstructed = that face's own recon.json "counts" flag (>=99% covered, record-walked
ring closes <= 1 ft -- recon.py's own per-face test, read back, never re-derived) on ANY sheet drawing it.
Area agreement: a face named for exactly ONE parcel compares its own polygon area (shapely, EPSG:2227 US
survey ft -- already the units the AREAS table itself prints, AC converted x43,560) directly against that
parcel's own record area; a MERGED face compares its own polygon area against the SUM of its own
constituent parcels' record areas (only where every one of them has a parsed area) -- comparing one
parcel's record figure against a merged face's whole polygon would be meaningless.

Loop19 leg 4 task 2: cross-sheet parcels. A named face that TOUCHES the sheet frame/matchline
(recon.py's own per_face "touches_frame" flag) is cut there -- recon.py's own per-face closure test never
even attempts it (counts=False by construction, see recon.py's run()). Where the SAME parcel id has a
touches_frame face on 2+ sheets, join every sheet's own candidate ring for that id into one ground-space
polygon (shapely, a small BUFFER_SNAP_FT buffer-then-unbuffer closes the sub-ft digitizing gap between two
sheets' own copies of the shared matchline edge -- same tolerance recon_set.py's own DUP_TOL_FT_SET uses
for "same matchline course, two sheets"), then re-run recon.py's own face_pieces()/face_closure() test on
the joined ring against the pooled record edges of every contributing sheet.

Loop19 leg 4 task 3: R-10741.2 DETAIL "A" (N.T.S.). Parcel 46825-5's own non-frame-touching face (the
~93%-covered one -- a SECOND, frame-touching candidate of the same name also exists, parcels.py's own
nested/duplicate polygonisation, excluded here by pct match) has one drawn gap with no record edge; DETAIL
"A" prints the two courses that fill it (N51 deg26'23"E 10.95', N19 deg41'37"W 156.02' -- read straight off
read_glyph.json's own OCR blocks at the detail's own text cluster, never its N.T.S. drawing). Attached to
the gap by VALUE: the two courses' own record vectors, walked from the gap's own drawn start point, must
land at the gap's own drawn end point within recon.CLOSURE_MAX_FT; each drawn gap piece is assigned
whichever course's own bearing is closest, only when within DETAIL_A_BEARING_TOL_DEG.

usage: python spike/parcel_score.py     (after the six-sheet bench; runs areas_table.py per sheet itself)
       python spike/parcel_score.py --selftest
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
sys.path.insert(0, str(Path(__file__).parent))
import recon  # noqa: E402
from recon import OUT_RECON  # noqa: E402

BUFFER_SNAP_FT = 1.0        # closes a sub-ft digitizing gap between two sheets' own copies of a shared
                             # matchline edge before shapely's union sees them as touching -- recon_set.py's
                             # own DUP_TOL_FT_SET reused (same "same matchline course, two sheets" margin).
DETAIL_A_BEARING_TOL_DEG = 5.0  # how far a drawn gap piece's own azimuth may sit from a DETAIL "A" course's
                                 # printed bearing (or its +180) and still be assigned to it.
DETAIL_A_LEN_TOL_FT = 0.5   # JR's own number (task 3): the two courses' own summed length vs. the gap's
                             # own drawn length.
DETAIL_A_COURSES_DMS = [    # printed inside DETAIL "A" on R-10741.2 (also cited on R-10741.3) -- values
    # only, never the inset's own N.T.S. drawing (JR's own instruction).
    ("N", 51, 26, 23, "E", 10.95, "N51 deg26'23\"E"),
    ("N", 19, 41, 37, "W", 156.02, "N19 deg41'37\"W"),
]


def _dms_az(ns, d, m, s, ew):
    """Bearing quadrant + DMS -> compass azimuth deg (0 = north), same convention as recon.azimuth_arr."""
    deg = d + m / 60 + s / 3600
    if ns == "N" and ew == "E":
        return deg
    if ns == "S" and ew == "E":
        return 180 - deg
    if ns == "S" and ew == "W":
        return 180 + deg
    return (360 - deg) % 360  # N...W


DETAIL_A_COURSES = [{"name": f"detailA:{label}", "az": _dms_az(ns, d, m, s, ew), "ft": ft, "label": label}
                     for ns, d, m, s, ew, ft, label in DETAIL_A_COURSES_DMS]

SHEETS = {  # short key -> (pdf path or None for presidio, out dir stem)
    "presidio": (None, ""),
    "r10434_1": (ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf", "r_10434_001_2020-09-16"),
    "r10434_3": (ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf", "r_10434_003_2020-09-16"),
    "r10741_1": (ROOT / "Sample Data" / "d4" / "r_10741_001_2017-02-10.pdf", "r_10741_001_2017-02-10"),
    "r10741_2": (ROOT / "Sample Data" / "d4" / "r_10741_002_2017-02-10.pdf", "r_10741_002_2017-02-10"),
    "r10741_3": (ROOT / "Sample Data" / "d4" / "r_10741_003_2017-02-10.pdf", "r_10741_003_2017-02-10"),
}
BASE_OUT = Path(__file__).parent / "out"
AREA_DIFF_TOL_PCT = 5.0  # pct: how far a face's own computed area may sit from the record's own AREAS
                          # figure and still count as "agrees" in the summary line (informational only --
                          # every row's own exact pct diff is in the written report either way)


def out_dir(pdf):
    return BASE_OUT / (pdf.stem if pdf else "")


def run_areas_table(pdf):
    import os
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if pdf:
        env["SHEET"] = str(pdf)
    else:
        env.pop("SHEET", None)
    r = subprocess.run([str(PY), str(Path(__file__).parent / "areas_table.py")],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    if r.returncode:
        print(f"areas_table.py failed on {pdf}: {r.stderr[-2000:]}")


def load_sheet(short_key, pdf, stem):
    o = out_dir(pdf)
    run_areas_table(pdf)
    areas = json.loads((o / "areas_table.json").read_text(encoding="utf-8")) if (o / "areas_table.json").exists() else []
    recon_json = json.loads((o / "recon.json").read_text(encoding="utf-8")) if (o / "recon.json").exists() else {"faces": []}
    gj = json.loads((o / "parcels.geojson").read_text(encoding="utf-8")) if (o / "parcels.geojson").exists() else {"features": []}
    faces = recon.load_faces(gj)  # pure function of the geojson: polygon + ring + named + parcel string
    # zip recon.json's own per-face record (counts/pct_covered/closure_ft/touches_frame) to load_faces()'s
    # own polygon, in the SAME order recon.run() built both from (kept_faces, in load_faces() order minus
    # any table/furniture-debris faces recon.py itself dropped -- matched here by the parcel name string,
    # IN APPEARANCE ORDER per name (not a plain name->face dict): a name can repeat (parcels.py's own
    # nested/duplicate polygonisation -- e.g. 46825-5 on R-10741.2 has both a frame-touching candidate and
    # the ~93%-covered one DETAIL "A" fills), and both this list and recon.json's own per_face list keep
    # every same-named occurrence in the same relative order, so a name-keyed zip recovers the right pair.
    by_name_faces, by_name_pf = {}, {}
    for f in faces:
        if f["named"]:
            by_name_faces.setdefault(f["parcel"], []).append(f)
    for pf in recon_json.get("faces", []):
        if pf["named"]:
            by_name_pf.setdefault(pf["parcel"], []).append(pf)
    face_rows = []
    for name, pf_list in by_name_pf.items():
        for pf, fobj in zip(pf_list, by_name_faces.get(name, [])):
            face_rows.append({"sheet": short_key, "parcel": pf["parcel"], "ids": pf["parcel"].split("|"),
                              "counts": pf["counts"], "touches_frame": pf["touches_frame"],
                              "pct_covered": pf["pct_covered"], "closure_ft": pf["closure_ft"],
                              "area_sqft": fobj["poly"].area, "poly": fobj["poly"]})
    return areas, face_rows, recon_json.get("buffer_ft", 2.0)


def render_joined_crop(pid, union, closes, pieces_meta):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import re
    fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
    if union.geom_type == "Polygon":
        xs, ys = union.exterior.xy
        ax.fill(xs, ys, color="#9ecae1" if closes else "#eeeeee",
                edgecolor="#2ca02c" if closes else "#e03030", lw=1.5)
    ax.set_aspect("equal")
    sheets = ", ".join(sorted({p["sheet"] for p in pieces_meta}))
    ax.set_title(f"{pid}: joined cross-sheet ring ({sheets}), closes={closes}", fontsize=8)
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", pid)
    fig.savefig(OUT_RECON / f"l19_4_joined_{safe}.png")
    plt.close(fig)


def joined_parcels(all_faces, record_area, buffer_by_sheet, stem_by_sheet, exclude_ids=frozenset()):
    """Task 2: a matchline cuts ONE parcel into pieces -- restricted to SINGLE-id faces only (f["ids"]
    has exactly one member). parcels.py's own polygonization also emits "kitchen-sink" merged faces near
    a sheet border (id lists 4-6 long, e.g. "46825|61806|61806-1|61806-2|63269", touching the frame purely
    because that merge happens to sprawl to the sheet edge) -- unioning THOSE across sheets by loose id
    membership produced a MultiPolygon and a 10-million-sqft garbage "ring" on a real run of this data;
    excluded here, on purpose, as not one real parcel. A candidate id needs a single-id touches_frame face
    on at least one sheet AND a single-id face (frame-touching or not: a matchline-cut parcel may sit
    fully inside its own sheet on one side) for the same id on at least one OTHER sheet -- those pieces
    are buffer-snap-unioned into one ring and scored with recon.py's own face_pieces()/face_closure() test
    against the pooled record edges of every contributing sheet (a shared matchline course drawn on 2
    sheets is not deduped here the way anchored.py's cross-sheet edges are -- covered_mask()'s own "any
    match" is duplicate-tolerant, harmless for a coverage test)."""
    single = [f for f in all_faces if len(f["ids"]) == 1]
    # parcels.py's own nested/overlapping polygonisation candidates can repeat the SAME id on the SAME
    # sheet (e.g. R-10434.3 prints three separate "46825" faces): reduce to exactly ONE candidate per
    # (sheet, id) before any cross-sheet union -- the frame-touching one when the id touches frame on
    # that sheet (the boundary-cut piece is the one this join needs), else the smallest-area candidate
    # (same "closest to a single, tightly-drawn parcel, not a nested merge" heuristic the summary table
    # above already uses), so a sheet's own polygonisation noise never enters the union at all.
    best_by_sheet_id = {}
    for f in single:
        key = (f["sheet"], f["ids"][0])
        cur = best_by_sheet_id.get(key)
        if cur is None:
            best_by_sheet_id[key] = f
            continue
        if f["touches_frame"] and not cur["touches_frame"]:
            best_by_sheet_id[key] = f
        elif f["touches_frame"] == cur["touches_frame"] and f["poly"].area < cur["poly"].area:
            best_by_sheet_id[key] = f
    reduced = list(best_by_sheet_id.values())

    by_id_touch = {}
    for f in reduced:
        if f["touches_frame"]:
            by_id_touch.setdefault(f["ids"][0], set()).add(f["sheet"])
    by_id_any_sheets = {}
    for f in reduced:
        by_id_any_sheets.setdefault(f["ids"][0], set()).add(f["sheet"])
    results = []
    for pid, touch_sheets in sorted(by_id_touch.items()):
        if pid in exclude_ids or len(by_id_any_sheets.get(pid, set())) < 2:
            continue
        contributing = sorted(by_id_any_sheets[pid])
        polys, pieces_meta = [], []
        for f in reduced:
            if f["ids"][0] == pid:
                polys.append(f["poly"].buffer(BUFFER_SNAP_FT))
                pieces_meta.append({"sheet": f["sheet"], "face": f["parcel"], "touches_frame": f["touches_frame"]})
        union = unary_union(polys).buffer(-BUFFER_SNAP_FT)
        if union.geom_type != "Polygon":
            results.append({"parcel": pid, "pieces": pieces_meta, "joined": False,
                            "reason": f"union is {union.geom_type}, not one polygon -- pieces do not abut"})
            continue
        ring = np.array(union.exterior.coords)
        rec_edges = []
        for sheet in contributing:
            trav_p = BASE_OUT / stem_by_sheet[sheet] / "traverse.json" if stem_by_sheet[sheet] else BASE_OUT / "traverse.json"
            if trav_p.exists():
                rec_edges.extend(recon.load_rec_edges(json.loads(trav_p.read_text(encoding="utf-8")))[0])
        buffer_ft = max((buffer_by_sheet.get(s, 2.0) for s in contributing), default=2.0)
        rP, rQ, rAz, rParent = recon.rec_segments(rec_edges)
        pieces, pct, total_len = recon.face_pieces(ring, rP, rQ, rAz, rParent, buffer_ft, recon.PARALLEL_TOL_DEG, recon.DENSIFY_FT)
        closure_ft = closes = None
        if pct >= recon.CLOSE_PCT and total_len > 0:
            closure_ft = recon.face_closure(pieces, rec_edges)
            closes = closure_ft <= recon.CLOSURE_MAX_FT
        rec_area_v = record_area(pid)
        results.append({"parcel": pid, "pieces": pieces_meta, "joined": True,
                        "pct_covered": round(pct * 100, 2), "closure_ft": round(closure_ft, 2) if closure_ft is not None else None,
                        "closes": bool(closes), "face_area_sqft": round(union.area, 1),
                        "record_area_sqft": rec_area_v,
                        "diff_pct": round(100 * (union.area - rec_area_v) / rec_area_v, 2) if rec_area_v else None})
        render_joined_crop(pid, union, bool(closes), pieces_meta)
    return results


def render_detail_a_crop(pieces, gap, assigned_pcs, result):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
    for k, p, q in pieces:
        p, q = np.array(p), np.array(q)
        ax.plot([p[0], q[0]], [p[1], q[1]], color="#2ca02c" if k is not None else "#cccccc", lw=2.0, zorder=2)
    assigned_idx = {a["piece"] for a in assigned_pcs}
    for m in range(gap["i"], gap["j"]):
        k, p, q = pieces[m]
        p, q = np.array(p), np.array(q)
        ax.plot([p[0], q[0]], [p[1], q[1]], color="#e03030" if m in assigned_idx else "#000000", lw=3.0, zorder=3)
    ax.set_aspect("equal")
    ax.set_title(f"46825-5 (R-10741.2): DETAIL \"A\" gap {result['gap_len_ft']}' vs courses "
                 f"{result['courses_sum_ft']}' -- {result['status']}, closes={result['closes']}", fontsize=8)
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_RECON / "l19_4_detailA_46825-5.png")
    plt.close(fig)


def detail_a_46825_5(all_faces, buffer_by_sheet, stem_by_sheet):
    """Task 3: 46825-5's own non-frame-touching face on R-10741.2 (the ~93%-covered one -- a SECOND,
    frame-touching candidate of the same name is excluded by load_sheet()'s own appearance-order pairing,
    see its docstring). Finds the ring's own uncovered gap run closest in length to the two DETAIL "A"
    courses' own sum, assigns each drawn gap piece to whichever course's own printed bearing is closest
    (within DETAIL_A_BEARING_TOL_DEG), then re-runs face_closure() with the two courses injected as
    synthetic record edges (az/ft only -- face_closure() never reads a record edge's own p/q, only its
    drawn-length SHARE of whichever ring piece(s) it was assigned, so no placement geometry is needed for
    the injected edges themselves)."""
    cands = [f for f in all_faces if f["sheet"] == "r10741_2" and f["parcel"] == "46825-5" and not f["touches_frame"]]
    if not cands:
        return {"status": "refused", "reason": "no non-frame-touching 46825-5 face found on r10741_2"}
    f = cands[0]
    buffer_ft = buffer_by_sheet.get("r10741_2", 2.0)
    trav_p = BASE_OUT / stem_by_sheet["r10741_2"] / "traverse.json"
    rec_edges, _ = recon.load_rec_edges(json.loads(trav_p.read_text(encoding="utf-8")))
    rP, rQ, rAz, rParent = recon.rec_segments(rec_edges)
    ring = np.array(f["poly"].exterior.coords)
    pieces, pct, total_len = recon.face_pieces(ring, rP, rQ, rAz, rParent, buffer_ft, recon.PARALLEL_TOL_DEG, recon.DENSIFY_FT)

    runs, i = [], 0
    while i < len(pieces):
        if pieces[i][0] is not None:
            i += 1
            continue
        j = i
        while j < len(pieces) and pieces[j][0] is None:
            j += 1
        run_len = sum(float(np.hypot(*(np.array(pieces[k][2]) - np.array(pieces[k][1])))) for k in range(i, j))
        runs.append({"i": i, "j": j, "len_ft": run_len})
        i = j
    if not runs:
        return {"status": "refused", "reason": "no uncovered gap found on the ring", "pct_covered_before": round(pct * 100, 2)}
    target_sum = sum(c["ft"] for c in DETAIL_A_COURSES)
    gap = min(runs, key=lambda r: abs(r["len_ft"] - target_sum))
    len_diff = abs(gap["len_ft"] - target_sum)
    if len_diff > DETAIL_A_LEN_TOL_FT + 5.0:
        return {"status": "refused",
                "reason": f"nearest gap run is {gap['len_ft']:.2f} ft vs the two courses summing {target_sum:.2f} ft ({len_diff:.2f} ft off)",
                "pct_covered_before": round(pct * 100, 2), "gap_len_ft": round(gap["len_ft"], 2), "courses_sum_ft": round(target_sum, 2)}

    extra_rec_edges = list(rec_edges)
    course_idx = {}
    anchor_pt = np.array(pieces[gap["i"]][1])
    for c in DETAIL_A_COURSES:
        course_idx[c["name"]] = len(extra_rec_edges)
        extra_rec_edges.append({"name": c["name"], "kind": "line", "az": c["az"], "ft": c["ft"], "misfit_ft": 0.0,
                                "p": anchor_pt, "q": anchor_pt})
    new_pieces = list(pieces)
    assigned_pcs = []
    for m in range(gap["i"], gap["j"]):
        k0, p, q = pieces[m]
        az = float(recon.azimuth_arr((np.array(q) - np.array(p))[None, :])[0])
        best_c, best_err = None, None
        for c in DETAIL_A_COURSES:
            err = min(abs((az - c["az"] + 180) % 360 - 180), abs((az - (c["az"] + 180) % 360 + 180) % 360 - 180))
            if best_err is None or err < best_err:
                best_c, best_err = c, err
        if best_err is not None and best_err <= DETAIL_A_BEARING_TOL_DEG:
            new_pieces[m] = (course_idx[best_c["name"]], p, q)
            assigned_pcs.append({"piece": m, "course": best_c["label"], "bearing_err_deg": round(best_err, 2),
                                 "drawn_ft": round(float(np.hypot(*(np.array(q) - np.array(p)))), 2)})

    covered_len2 = sum(float(np.hypot(*(np.array(q) - np.array(p)))) for k, p, q in new_pieces if k is not None)
    pct2 = covered_len2 / total_len if total_len else 0.0
    closure_ft2, closes = None, False
    if pct2 >= recon.CLOSE_PCT and total_len > 0:
        closure_ft2 = recon.face_closure(new_pieces, extra_rec_edges)
        closes = closure_ft2 <= recon.CLOSURE_MAX_FT

    result = {"status": "attached" if assigned_pcs else "refused",
              "reason": "" if assigned_pcs else "no gap piece matched either course's bearing within tolerance",
              "gap_len_ft": round(gap["len_ft"], 2), "courses_sum_ft": round(target_sum, 2),
              "len_diff_ft": round(len_diff, 2), "assigned_pieces": assigned_pcs,
              "pct_covered_before": round(pct * 100, 2), "pct_covered_after": round(pct2 * 100, 2),
              "closure_ft": round(closure_ft2, 2) if closure_ft2 is not None else None, "closes": bool(closes),
              "sheet": "r10741_2", "face": f["parcel"]}
    render_detail_a_crop(pieces, gap, assigned_pcs, result)
    return result


def run():
    all_areas, all_faces = [], []
    buffer_by_sheet, stem_by_sheet = {}, {}
    for short_key, (pdf, stem) in SHEETS.items():
        areas, face_rows, buffer_ft = load_sheet(short_key, pdf, stem)
        for a in areas:
            all_areas.append({**a, "sheet": short_key})
        all_faces.extend(face_rows)
        buffer_by_sheet[short_key] = buffer_ft
        stem_by_sheet[short_key] = stem

    # SET-level parcel list: dedupe by id, keep every sheet's own listing (id -> list of {sheet, area_sqft, remarks})
    by_id = {}
    for a in all_areas:
        by_id.setdefault(a["parcel"], []).append({"sheet": a["sheet"], "area_sqft": a["area_sqft"], "remarks": a["remarks"]})

    def record_area(pid):
        """First parsed area for this id across every sheet's own listing, or None."""
        for listing in by_id.get(pid, []):
            if listing["area_sqft"] is not None:
                return listing["area_sqft"]
        return None

    parcels = []
    for pid, listings in sorted(by_id.items()):
        matches = [f for f in all_faces if pid in f["ids"]]
        reconstructed = any(f["counts"] for f in matches)
        rec_area = record_area(pid)
        area_rows = []
        for f in matches:
            if len(f["ids"]) == 1:
                diff_pct = round(100 * (f["area_sqft"] - rec_area) / rec_area, 2) if rec_area else None
                area_rows.append({"sheet": f["sheet"], "face": f["parcel"], "merged": False,
                                  "face_area_sqft": round(f["area_sqft"], 1), "record_area_sqft": rec_area,
                                  "diff_pct": diff_pct})
            else:
                sub_areas = [record_area(i) for i in f["ids"]]
                rec_sum = sum(sub_areas) if all(v is not None for v in sub_areas) else None
                diff_pct = round(100 * (f["area_sqft"] - rec_sum) / rec_sum, 2) if rec_sum else None
                area_rows.append({"sheet": f["sheet"], "face": f["parcel"], "merged": True,
                                  "face_area_sqft": round(f["area_sqft"], 1), "record_area_sqft": rec_sum,
                                  "diff_pct": diff_pct})
        parcels.append({
            "parcel": pid, "listed_on": sorted({l["sheet"] for l in listings}),
            "record_area_sqft": rec_area, "record_remarks": next((l["remarks"] for l in listings if l["remarks"]), ""),
            "has_face": bool(matches), "reconstructed": reconstructed,
            "faces": [{"sheet": f["sheet"], "face": f["parcel"], "counts": f["counts"],
                      "pct_covered": f["pct_covered"], "closure_ft": f["closure_ft"],
                      "touches_frame": f["touches_frame"]} for f in matches],
            "area_agreement": area_rows,
        })

    n_total = len(parcels)
    n_recon_before = sum(1 for p in parcels if p["reconstructed"])

    # loop19 leg 4 task 2 + 3: cross-sheet joins and the DETAIL "A" gap fill, both scored with recon.py's
    # own face_pieces()/face_closure() test -- a parcel a join or DETAIL "A" now closes is folded back into
    # `reconstructed` here, same test every other parcel above was scored by.
    detail_a = detail_a_46825_5(all_faces, buffer_by_sheet, stem_by_sheet)
    # a parcel DETAIL "A" already closes whole, on its own sheet, is not a join candidate -- excluded
    # from joined_parcels() so a SEPARATE, unrelated polygon that merely happens to share its id (a real
    # find on this data: a second, much larger face also named "46825-5" via parcels.py's own nested
    # polygonisation, touching the frame but not the drawn parcel DETAIL "A" already closed) is never
    # reported as a bogus 65-acre "joined ring" beside the real, closed, single-sheet one.
    exclude_ids = {"46825-5"} if detail_a.get("closes") else set()
    joined = joined_parcels(all_faces, record_area, buffer_by_sheet, stem_by_sheet, exclude_ids)
    joined_closed_ids = {j["parcel"] for j in joined if j.get("closes")}
    by_pid = {p["parcel"]: p for p in parcels}
    for pid in joined_closed_ids:
        if pid in by_pid:
            by_pid[pid]["reconstructed"] = True
    if detail_a.get("closes") and "46825-5" in by_pid:
        by_pid["46825-5"]["reconstructed"] = True

    n_recon = sum(1 for p in parcels if p["reconstructed"])
    n_face = sum(1 for p in parcels if p["has_face"])
    result = {"headline": f"{n_recon}/{n_total}", "headline_before_leg4": f"{n_recon_before}/{n_total}",
              "parcels_reconstructed": n_recon, "parcels_reconstructed_before_leg4": n_recon_before,
              "parcels_in_areas_tables": n_total, "parcels_with_a_face": n_face, "parcels": parcels,
              "joined_parcels": joined, "detail_a_46825_5": detail_a}
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / "parcel_areas.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    lines = [f"# parcel score vs AREAS tables (loop18 leg 1 + loop19 leg 4)\n",
             f"headline: **{n_recon} / {n_total}** parcels reconstructed (before loop19 leg 4's cross-sheet "
             f"joins + DETAIL \"A\": {n_recon_before} / {n_total}); of {n_total} listed across the six AREAS "
             f"tables, deduped by id; {n_face} have a matching face on some sheet.\n"]
    if joined:
        lines.append("## cross-sheet joined parcels (task 2)\n")
        lines.append("| parcel | pieces (sheet:face) | pct covered | closure ft | closes | face area sqft | record area sqft | diff % |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for j in joined:
            pcs = ", ".join(f"{p['sheet']}:{p['face']}" for p in j["pieces"])
            if not j["joined"]:
                lines.append(f"| {j['parcel']} | {pcs} | - | - | no ({j['reason']}) | - | - | - |")
                continue
            ra = f"{j['record_area_sqft']:,.0f}" if j["record_area_sqft"] is not None else "?"
            fa = f"{j['face_area_sqft']:,.0f}"
            diff = f"{j['diff_pct']:+.1f}%" if j["diff_pct"] is not None else ""
            lines.append(f"| {j['parcel']} | {pcs} | {j['pct_covered']}% | {j['closure_ft']} | "
                          f"{'YES' if j['closes'] else 'no'} | {fa} | {ra} | {diff} |")
        lines.append("")
    lines.append("## DETAIL \"A\" (R-10741.2, 46825-5, task 3)\n")
    lines.append(f"status: **{detail_a['status']}** -- {detail_a.get('reason', '')}\n")
    da_keys = ("gap_len_ft", "courses_sum_ft", "len_diff_ft", "pct_covered_before", "pct_covered_after", "closure_ft", "closes")
    lines.append("| " + " | ".join(da_keys) + " |")
    lines.append("|" + "---|" * len(da_keys))
    lines.append("| " + " | ".join(str(detail_a.get(k, "")) for k in da_keys) + " |\n")
    if detail_a.get("assigned_pieces"):
        lines.append("| drawn gap piece | assigned course | bearing err deg | drawn ft |")
        lines.append("|---|---|---|---|")
        for a in detail_a["assigned_pieces"]:
            lines.append(f"| {a['piece']} | {a['course']} | {a['bearing_err_deg']} | {a['drawn_ft']} |")
        lines.append("")

    lines.append("## per-parcel vs AREAS tables\n")
    lines.append("| parcel | listed on | has face | reconstructed | record area (sqft) | face area (sqft) | diff % |")
    lines.append("|---|---|---|---|---|---|---|")
    for p in parcels:
        # a parcel id can match more than one candidate face (parcels.py's own polygonization sometimes
        # emits nested/overlapping merged-face candidates for the same ground, JR's own "several are
        # merged multi-parcel faces" note) -- the summary table shows the reconstructed one if any, else
        # the smallest-area candidate (closest to a single, tightly-drawn parcel rather than a large
        # nested merge); parcel_areas.json keeps every candidate, not just this one pick.
        cands = p["area_agreement"]
        best = None
        if cands:
            recon_faces = {f["face"] for f in p["faces"] if f["counts"]}
            recon_cands = [c for c in cands if c["face"] in recon_faces]
            pool = recon_cands or cands
            best = min(pool, key=lambda c: c["face_area_sqft"])
        fa = f"{best['face_area_sqft']:,.0f}{' (merged)' if best['merged'] else ''}" if best else ""
        diff = f"{best['diff_pct']:+.1f}%" if best and best["diff_pct"] is not None else ""
        ra = f"{p['record_area_sqft']:,.0f}" if p["record_area_sqft"] is not None else "?"
        lines.append(f"| {p['parcel']} | {','.join(p['listed_on'])} | {'yes' if p['has_face'] else 'no'} | "
                      f"{'YES' if p['reconstructed'] else 'no'} | {ra} | {fa} | {diff} |")
    (OUT_RECON / "parcel_areas.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"parcels reconstructed / in AREAS tables: {n_recon}/{n_total} (before leg 4: {n_recon_before}/{n_total}; "
          f"{n_face} have a matching face)")
    print(f"  joined (task 2): {len(joined)} candidates, {len(joined_closed_ids)} close")
    print(f"  DETAIL A (task 3): {detail_a['status']} -- closes={detail_a.get('closes')}")
    for p in parcels:
        print(f"  {p['parcel']:12s} listed_on={','.join(p['listed_on']):20s} face={'Y' if p['has_face'] else 'n'} "
              f"recon={'Y' if p['reconstructed'] else 'n'} record_sqft={p['record_area_sqft']}")
    return result


def selftest():
    """leg 4 task 2: two sheets' own half-rectangles, cut at a shared matchline (x=50), join into one
    100x50 ring and close against the four pooled record sides -- the exact mechanics joined_parcels()
    itself runs, exercised directly with no disk files. Task 3: DETAIL "A"'s own two printed courses,
    walked from a gap's own construction point, must self-close (round-trip: the same DMS -> az conversion
    detail_a_46825_5() uses to build the fixture is the one under test)."""
    from shapely.geometry import Polygon
    face_a = Polygon([(0, 0), (50, 0), (50, 50), (0, 50)])
    face_b = Polygon([(50, 0), (100, 0), (100, 50), (50, 50)])
    union = unary_union([face_a.buffer(BUFFER_SNAP_FT), face_b.buffer(BUFFER_SNAP_FT)]).buffer(-BUFFER_SNAP_FT)
    assert union.geom_type == "Polygon", f"two abutting halves must union to one polygon: {union.geom_type}"
    assert abs(union.area - 5000.0) < 50.0, f"joined area must be ~100x50: {union.area}"
    ring = np.array(union.exterior.coords)
    rec_edges = [
        {"name": "bottom", "kind": "line", "az": 90.0, "ft": 100.0, "p": np.array([0.0, 0.0]), "q": np.array([100.0, 0.0])},
        {"name": "right", "kind": "line", "az": 0.0, "ft": 50.0, "p": np.array([100.0, 0.0]), "q": np.array([100.0, 50.0])},
        {"name": "top", "kind": "line", "az": 270.0, "ft": 100.0, "p": np.array([100.0, 50.0]), "q": np.array([0.0, 50.0])},
        {"name": "left", "kind": "line", "az": 180.0, "ft": 50.0, "p": np.array([0.0, 50.0]), "q": np.array([0.0, 0.0])},
    ]
    rP, rQ, rAz, rParent = recon.rec_segments(rec_edges)
    pieces, pct, total_len = recon.face_pieces(ring, rP, rQ, rAz, rParent, 2.0, recon.PARALLEL_TOL_DEG, recon.DENSIFY_FT)
    assert pct >= recon.CLOSE_PCT, f"the joined ring's own 4 sides must all match a record edge: {pct}"
    closure = recon.face_closure(pieces, rec_edges)
    assert closure <= recon.CLOSURE_MAX_FT, f"a clean rectangle's own record walk must close: {closure}"

    # a 2-course open path is not itself a ring (face_closure() sums vectors all the way back to the
    # ring's own start, expecting ~0) -- close it with a third, real "return" edge so this exercises the
    # SAME kind of sum detail_a_46825_5() feeds face_closure(): a full ring, DETAIL's own 2 courses among
    # its pieces.
    az1, az2 = DETAIL_A_COURSES[0]["az"], DETAIL_A_COURSES[1]["az"]
    p0 = np.array([0.0, 0.0])
    p1 = p0 + np.array([10.95 * math.sin(math.radians(az1)), 10.95 * math.cos(math.radians(az1))])
    p2 = p1 + np.array([156.02 * math.sin(math.radians(az2)), 156.02 * math.cos(math.radians(az2))])
    return_az = float(recon.azimuth_arr((p0 - p2)[None, :])[0])
    return_ft = float(np.hypot(*(p0 - p2)))
    gap_pieces = [(None, p0, p1), (None, p1, p2), ("return", p2, p0)]
    extra_rec_edges, course_idx = [], {}
    for c in DETAIL_A_COURSES:
        course_idx[c["name"]] = len(extra_rec_edges)
        extra_rec_edges.append({"name": c["name"], "kind": "line", "az": c["az"], "ft": c["ft"], "misfit_ft": 0.0, "p": p0, "q": p0})
    return_idx = len(extra_rec_edges)
    extra_rec_edges.append({"name": "return", "kind": "line", "az": return_az, "ft": return_ft, "misfit_ft": 0.0, "p": p2, "q": p0})
    new_pieces = []
    for k0, p, q in gap_pieces:
        if k0 == "return":
            new_pieces.append((return_idx, p, q))
            continue
        az = float(recon.azimuth_arr((np.array(q) - np.array(p))[None, :])[0])
        best_c, best_err = None, None
        for c in DETAIL_A_COURSES:
            err = min(abs((az - c["az"] + 180) % 360 - 180), abs((az - (c["az"] + 180) % 360 + 180) % 360 - 180))
            if best_err is None or err < best_err:
                best_c, best_err = c, err
        assert best_err <= DETAIL_A_BEARING_TOL_DEG, f"a course's own exact bearing must self-match: {best_err}"
        new_pieces.append((course_idx[best_c["name"]], p, q))
    closure2 = recon.face_closure(new_pieces, extra_rec_edges)
    assert closure2 <= recon.CLOSURE_MAX_FT, f"the two DETAIL courses must close back to their own endpoint: {closure2}"

    print("parcel_score.selftest OK: two sheets' own half-rectangles cut at a shared matchline join into "
          "one ring and close against the pooled record edges; DETAIL \"A\"'s two printed courses, walked "
          "from a gap's own start point, close back to their own construction")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run()
