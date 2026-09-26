"""Every number the slides quote, taken from the run's outputs, never from memory.

Writes spike/out/numbers.md (to paste) and numbers.json (to cite), plus tunnel_profile.png
(ground elevation along each tunnel easement from tunnel_profile.csv).
usage: python spike/slide_numbers.py   (after demo.py)
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

BENCH_SHEETS = {"presidio": "R-10434.2 Presidio", "r10434_1": "R-10434.1", "r10434_3": "R-10434.3", "r10741_1": "R-10741.1", "r10741_2": "R-10741.2", "r10741_3": "R-10741.3"}


def record_twin_block():
    """The latest loop's closing snapshot: the last `loop3-final` bench row per baseline sheet, this
    sheet's own closed traverse chain, and the 61985 blocker, all read from files."""
    bench = list(csv.DictReader(open(OUT / "bench.csv", encoding="utf-8")))
    verify = {r["sheet"]: r for r in bench if r["label"] == BENCH_LABEL}  # last row per sheet wins
    lines = ["## Record twin, 2026-09-23 loop 2", "",
             f"Pass counts from `spike/out/bench.csv` (rows labelled `{BENCH_LABEL}`):", "",
             "| sheet | distance | bearing | arc length | tags associated | faces named |", "|---|---|---|---|---|---|"]
    for key, label in BENCH_SHEETS.items():
        r = verify.get(key)
        if r:
            lines.append(f"| {label} | {r['distance']} | {r['bearing']} | {r['arc length']} | {r['tags_assoc']} | {r['faces_named']} |")
    trav = json.loads((OUT / "traverse.json").read_text(encoding="utf-8"))
    closed = [c for c in trav if c["closed"]]
    if closed:
        c = closed[0]
        lines += ["", f"Closed chain on {PDF.stem}: {c['n_edges']} edges ({c['full_record']} with a full record), "
                       f"end misfit {c['misfit_end_ft']} ft, record area {c['record_area_sqft']:,.1f} sq ft."]
    loop_md = (Path(__file__).parent / "LOOP.md").read_text(encoding="utf-8")
    strip = json.loads((OUT / "leg5_61985.json").read_text(encoding="utf-8")) if (OUT / "leg5_61985.json").exists() else []
    env = next((r.get("strip_combined") for r in strip if r.get("strip_combined")), None)
    if env:
        lines += ["", f"Blocker: 61985-1..4 do not close as separate figures. The drawing carries them as one strip "
                      f"(dashed easement layer under the R/W line and parallel to it), {env['area_sqft']:,.0f} sq ft against "
                      f"a table sum of {env['table_area_sqft']:,.0f} ({env['diff_pct']:+.1f} %); no drawn stroke divides the four, "
                      "and their printed curve data sits on the R/W line. The four stay queued; the envelope is what is measured."]
    return "\n".join(lines) + "\n"

SQFT_PER_ACRE = 43560.0
BENCH_LABEL = "loop9-final"


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main():
    N = {}
    g = load("georef.json")
    N["georef"] = {"sheet": PDF.stem, "credible": g["credible"], "control_points": len([c for c in g.get("pairs", [])]) or None,
                   "rms_ft": round(g["rms_ft"], 3), "scale_ft_per_pt": round(g["scale_ft_per_pt"], 5), "rotation_deg": round(g["rotation_deg"], 3)}
    rows = list(csv.DictReader(open(OUT / "checks.csv", encoding="utf-8")))
    N["checks"] = {k: {"checked": sum(1 for r in rows if r["check"] == k and r["result"] in ("pass", "FAIL")), "pass": sum(1 for r in rows if r["check"] == k and r["result"] == "pass")}
                   for k in ("distance", "bearing", "arc length", "curve L=R*delta")}
    passes = [r for r in rows if r["result"] == "pass" and r["check"] in ("distance", "arc length")]
    if passes:
        d = np.abs([float(r["difference"]) for r in passes])
        N["checks"]["pass_residual_ft"] = {"median": round(float(np.median(d)), 3), "max": round(float(d.max()), 3)}
    bp = [r for r in rows if r["result"] == "pass" and r["check"] == "bearing"]
    if bp:
        d = np.abs([float(r["difference"].rstrip("'")) for r in bp])
        N["checks"]["pass_residual_arcmin"] = {"median": round(float(np.median(d)), 2), "max": round(float(d.max()), 2)}
    exc = load("exceptions.json")
    small = {"distance": 5.0, "arc length": 5.0, "bearing": 60.0}
    N["exceptions"] = {"total": len(exc),
                       "unmatched": sum(1 for e in exc if "issue" in e and "sheet edge" not in e["issue"]),
                       "matchline": sum(1 for e in exc if "sheet edge" in e.get("issue", "")),
                       "disagree_small": sum(1 for e in exc if "issue" not in e and abs(e.get("off_ft", e.get("off_arcmin", 0))) <= small.get(e["kind"], 1e9)),
                       "wrong_line": sum(1 for e in exc if "issue" not in e and abs(e.get("off_ft", e.get("off_arcmin", 0))) > small.get(e["kind"], 1e9))}
    tags = load("tags.json")
    trows = list(csv.DictReader(open(OUT / "tags_checks.csv", encoding="utf-8")))
    tq = load("tags_queue.json")
    N["tags"] = {"table_rows": 44, "read": sum(1 for t in tags if "?" not in t["tag"]), "distinct": len({t["tag"] for t in tags if "?" not in t["tag"]}),
                 "partial_queued": sum(1 for t in tags if "?" in t["tag"]), "associated": len({r["tag"] for r in trows}),
                 "by_leader": len({r["tag"] for r in trows if r["association"] == "leader"}), "queued": len(tq),
                 **{k: {"checked": sum(1 for r in trows if r["check"] == k and r["result"] in ("pass", "FAIL")), "pass": sum(1 for r in trows if r["check"] == k and r["result"] == "pass")}
                    for k in ("distance", "bearing", "radius", "arc length")}}
    parc = load("parcels.geojson")["features"]
    N["parcels"] = {"faces": len(parc), "named": sum(1 for f in parc if f["properties"]["parcel"]),
                    "with_table_area": sum(1 for f in parc if "table_area_sqft" in f["properties"]),
                    "within_1pct": sum(1 for f in parc if abs(f["properties"].get("diff_pct", 999)) <= 1.0)}
    feats = load("extracted_features.geojson")["features"]
    byk = {}
    for f in feats:
        k = f["properties"]["kind"]; byk.setdefault(k, []).append(f["properties"]["area_m2"])
    N["lidar_features"] = {k: {"polygons": len(v), "area_m2": round(sum(v))} for k, v in byk.items()}
    N["lidar_features"]["buildings_roof_test"] = sum(1 for f in feats if f["properties"].get("verdict") == "building")
    enc = load("encroachments.geojson")["features"]
    N["encroachment"] = {"clusters": len(enc), "building_verdict": sum(1 for f in enc if f["properties"]["verdict"] == "building"),
                         "in_named_parcels": sum(1 for f in enc if f["properties"]["verdict"] == "building" and not str(f["properties"]["parcel"]).startswith("face-")),
                         "parcels": sorted({f["properties"]["parcel"] for f in enc if f["properties"]["verdict"] == "building" and not str(f["properties"]["parcel"]).startswith("face-")})}
    prof = list(csv.DictReader(open(OUT / "tunnel_profile.csv", encoding="utf-8")))
    tun = {}
    for r in prof:
        tun.setdefault(r["parcel"], []).append((float(r["station_m"]), float(r["ground_m"]) if r["ground_m"] not in ("", "nan") else np.nan))
    N["tunnel"] = {k: {"length_m": round(max(s for s, _ in v)), "ground_min_m": round(float(np.nanmin([z for _, z in v])), 1), "ground_max_m": round(float(np.nanmax([z for _, z in v])), 1)} for k, v in tun.items()}
    h = json.loads((Path(__file__).parent / "lidar" / "htdp.json").read_text())
    N["htdp"] = {"from_epoch": h["from_epoch"], "to_epoch": h["to_epoch"], "dN_m": h["dN_m"], "dE_m": h["dE_m"], "shift_m": round(float(np.hypot(h["dN_m"], h["dE_m"])), 3),
                 "bearing_deg": round(float(np.degrees(np.arctan2(h["dE_m"], h["dN_m"])) % 360), 1)}
    (OUT / "numbers.json").write_text(json.dumps(N, indent=1), encoding="utf-8")

    # tunnel profile figure
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 3.2), dpi=150)
    for k, v in sorted(tun.items()):
        s, z = zip(*v)
        ax.plot(s, z, lw=1.6, label=f"{k}  ({N['tunnel'][k]['length_m']} m)")
    ax.set_xlabel("station along easement (m)"); ax.set_ylabel("LiDAR ground (m, NAVD88)"); ax.grid(alpha=0.3)
    ax.legend(fontsize=8, title="tunnel easement"); ax.set_title("Ground over the tunnel easements, from the 2025 LiDAR ground class", fontsize=10)
    fig.tight_layout(); fig.savefig(OUT / "tunnel_profile.png"); plt.close(fig)

    c, t, x, p, lf, e, ht = N["checks"], N["tags"], N["exceptions"], N["parcels"], N["lidar_features"], N["encroachment"], N["htdp"]
    md = f"""# Numbers from the run — {PDF.stem}

All from `spike/out/` after `python spike/demo.py`. Re-run before quoting.

## Georeferencing
- Fit credible: {N['georef']['credible']}; RMS {N['georef']['rms_ft']} ft; scale {N['georef']['scale_ft_per_pt']} ft/pt; grid north {N['georef']['rotation_deg']:+.3f}° from sheet up.

## Printed vs drawn (labels on the drawing)
| check | checked | pass |
|---|---|---|
""" + "".join(f"| {k} | {v['checked']} | {v['pass']} |\n" for k, v in c.items() if isinstance(v, dict) and v.get("checked")) + f"""
- Where a label passes, printed vs drawn agrees to {c.get('pass_residual_ft', {}).get('median', '-')} ft median (max {c.get('pass_residual_ft', {}).get('max', '-')}) and {c.get('pass_residual_arcmin', {}).get('median', '-')}′ median bearing.
- Exception queue: {x['total']} items = {x['disagree_small']} genuine disagreements, {x['wrong_line']} where the reader measured a different line, {x['unmatched']} labels with no line found, {x['matchline']} lines leaving the sheet.

## Table tags (L#, C#) read from the glyph paths, no OCR
- {t['read']} of {t['table_rows']} table rows found on the drawing ({t['distinct']} distinct), {t['partial_queued']} partial reads queued, {t['associated']} associated ({t['by_leader']} by leader arrowhead), {t['queued']} queue items.
| check | checked | pass |
|---|---|---|
""" + "".join(f"| {k} | {t[k]['checked']} | {t[k]['pass']} |\n" for k in ("bearing", "distance", "radius", "arc length")) + f"""
## Parcels
- {p['faces']} faces from the heavy linework, {p['named']} named by a label or leader, {p['with_table_area']} with a parcel-table area, {p['within_1pct']} within 1 % of it (figures leave the sheet at matchlines; easement strips do not close).

## LiDAR (2025 flight)
- Epoch: sheet 1991.35 → LiDAR 2010.0 frame, HTDP shift {ht['shift_m']} m toward {ht['bearing_deg']:.0f}° (dN {ht['dN_m']} m, dE {ht['dE_m']} m), applied to the sheet before overlay.
- Features: """ + ", ".join(f"{v['polygons']} {k} ({v['area_m2']:,} m²)" for k, v in lf.items() if isinstance(v, dict)) + f"""; {lf['buildings_roof_test']} buildings pass the roof-flatness test.
- Encroachment screen: {e['clusters']} building-class clusters inside parcel faces, {e['building_verdict']} with a building verdict, {e['in_named_parcels']} in named parcels ({', '.join(e['parcels'])}).
- Tunnel easements, ground over them: """ + "; ".join(f"{k} {v['length_m']} m, {v['ground_min_m']}–{v['ground_max_m']} m" for k, v in sorted(N['tunnel'].items())) + """ (`tunnel_profile.png`).
- Caveat: the easement faces come from the polygonised linework, not a closed traverse; where a face's area is far from the parcel table (""" + ", ".join(f"{f['properties']['parcel']} {f['properties']['diff_pct']:+.0f} %" for f in parc if "diff_pct" in f["properties"] and abs(f["properties"]["diff_pct"]) > 5) + """) the profile runs along the wrong figure. Say so on the slide.
"""
    md += "\n" + record_twin_block()
    (OUT / "numbers.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
