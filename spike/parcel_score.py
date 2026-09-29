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

usage: python spike/parcel_score.py     (after the six-sheet bench; runs areas_table.py per sheet itself)
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
sys.path.insert(0, str(Path(__file__).parent))
import recon  # noqa: E402
from recon import OUT_RECON  # noqa: E402

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
    # which recon.py's own per_face list already carries and is unique per sheet by construction).
    by_name = {f["parcel"]: f for f in faces if f["named"]}
    face_rows = []
    for pf in recon_json.get("faces", []):
        if not pf["named"] or pf["parcel"] not in by_name:
            continue
        poly = by_name[pf["parcel"]]["poly"]
        face_rows.append({"sheet": short_key, "parcel": pf["parcel"], "ids": pf["parcel"].split("|"),
                          "counts": pf["counts"], "touches_frame": pf["touches_frame"],
                          "pct_covered": pf["pct_covered"], "closure_ft": pf["closure_ft"],
                          "area_sqft": poly.area})
    return areas, face_rows


def run():
    all_areas, all_faces = [], []
    for short_key, (pdf, stem) in SHEETS.items():
        areas, face_rows = load_sheet(short_key, pdf, stem)
        for a in areas:
            all_areas.append({**a, "sheet": short_key})
        all_faces.extend(face_rows)

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
    n_recon = sum(1 for p in parcels if p["reconstructed"])
    n_face = sum(1 for p in parcels if p["has_face"])
    result = {"headline": f"{n_recon}/{n_total}", "parcels_reconstructed": n_recon,
              "parcels_in_areas_tables": n_total, "parcels_with_a_face": n_face, "parcels": parcels}
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / "parcel_areas.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    lines = [f"# parcel score vs AREAS tables (loop18 leg 1)\n",
             f"headline: **{n_recon} / {n_total}** parcels reconstructed (of {n_total} listed across the six "
             f"AREAS tables, deduped by id); {n_face} have a matching face on some sheet.\n",
             "| parcel | listed on | has face | reconstructed | record area (sqft) | face area (sqft) | diff % |",
             "|---|---|---|---|---|---|---|"]
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

    print(f"parcels reconstructed / in AREAS tables: {n_recon}/{n_total} ({n_face} have a matching face)")
    for p in parcels:
        print(f"  {p['parcel']:12s} listed_on={','.join(p['listed_on']):20s} face={'Y' if p['has_face'] else 'n'} "
              f"recon={'Y' if p['reconstructed'] else 'n'} record_sqft={p['record_area_sqft']}")
    return result


if __name__ == "__main__":
    run()
