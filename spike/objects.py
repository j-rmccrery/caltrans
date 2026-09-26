"""The object record: every published thing, with where it came from and how it was checked.

One GeoJSON (lon/lat, NAD83(2011)) whose features share a provenance schema:
  kind        control point | check | parcel | linework | lidar feature | encroachment
  sheet       source sheet id
  region      [x0, y0, x1, y1] on the sheet in PDF points, where the reader saw it (when it came from text)
  printed     the value(s) as printed on the sheet
  measured    what geometry or LiDAR gave
  residual    difference, in the object's units
  status      verified | queued | refused | info      (nothing is 'verified' by a model)
  rule        the deterministic rule or fit that produced it
  adjudicated_by, adjudicated_on   empty until a surveyor works the queue
usage: [SHEET=<pdf>] python spike/objects.py  ->  spike/out[/<sheet>]/objects.geojson
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

SHEET = PDF.stem
to_ll = Transformer.from_crs("EPSG:2227", "EPSG:6318", always_xy=True)
BASE = {"sheet": SHEET, "adjudicated_by": "", "adjudicated_on": ""}


def feat(geom, **props):
    return {"type": "Feature", "properties": {**BASE, **props}, "geometry": geom}


def main():
    g = json.loads((OUT / "georef.json").read_text())
    a, b, tx, ty = g["params"]
    feats = []

    # control points: printed coordinates, the sheet point the leader reached, the fit residual
    for c in g["control"]:
        E, N = c["E"], c["N"]
        lon, lat = to_ll.transform(E, N)
        feats.append(feat({"type": "Point", "coordinates": [round(lon, 8), round(lat, 8)]},
                          kind="control point", printed={"E": E, "N": N}, measured={"sheet_pt": [round(c["sx"], 2), round(-c["sy"], 2)]},
                          residual=round(c["residual_ft"], 3), units="ft",
                          status="verified" if c["used"] else "refused",
                          rule="printed N/E callout, leader traced to point, similarity fit by consensus; residual vs fit"))
    for ln in g.get("grid_lines", []):
        feats.append(feat(None, kind="control line", printed={ln["axis"]: ln["value"]}, residual=round(ln["residual"], 3), units="ft",
                          status="verified" if ln["used"] else "refused", rule="grid tick label along a grid-line stub; one equation per stub end"))
    fit_rule = "4-parameter similarity, sheet to CCS83 Zone 3 US survey ft (EPSG:2227), epoch 1991.35 as printed"
    if g.get("placed_by"):
        fit_rule += f"; rotation and scale from printed bearings/distances, offset from {g['placed_by']}"
    feats.append(feat(None, kind="georeferencing fit", measured={"scale_ft_per_pt": g["scale_ft_per_pt"], "rotation_deg": g["rotation_deg"], "rms_ft": g["rms_ft"]},
                      status="verified" if g.get("credible", True) else ("queued" if g.get("weak") else "refused"),
                      rule=fit_rule))

    # checks: printed value vs drawn geometry
    if (OUT / "checks.csv").exists():
        for r in csv.DictReader(open(OUT / "checks.csv", encoding="utf-8")):
            st = {"pass": "verified", "FAIL": "queued"}.get(r["result"], "info")
            feats.append(feat(None, kind="check", check=r["check"], printed=r["printed"], measured=r["drawn"], residual=r["difference"],
                              status=st, rule="label matched to the parallel adjacent line; length x scale and azimuth from the fit; curves L=R*delta"))
    if (OUT / "exceptions.json").exists():
        for e in json.loads((OUT / "exceptions.json").read_text(encoding="utf-8")):
            feats.append(feat(None, kind="check", check=e["kind"], printed=e.get("text", e.get("printed", "")), measured=e.get("drawn") or e.get("drawn_ft") or e.get("calc_L"),
                              residual=e.get("off_ft") or e.get("off_arcmin"), region=e["region"], status="queued", reason=e.get("issue", "value mismatch"),
                              rule="same as checks; unmatched or failed"))

    # parcels, linework, lidar features, encroachments: carry their own properties through
    for name, kind, status_of in (
        ("parcels.geojson", "parcel", lambda p: "info" if not p.get("parcel") else ("queued" if p.get("diff_pct") is not None and abs(p["diff_pct"]) > 1 else "verified" if p.get("diff_pct") is not None else "info")),
        ("sheet_linework.geojson", "linework", lambda p: "info"),
        ("extracted_features.geojson", "lidar feature", lambda p: "queued" if p.get("verdict", "").startswith("vegetation") else "info"),
        ("encroachments.geojson", "encroachment", lambda p: "queued" if p.get("verdict") == "building" else "refused"),
    ):
        path = OUT / name
        if not path.exists():
            continue
        for f in json.loads(path.read_text())["features"]:
            p = dict(f["properties"])
            if "kind" in p:
                p["feature"] = p.pop("kind")  # lidar features name their class 'kind'; ours means object type
            rule = p.pop("rule", None) or {"parcel": "faces of the sheet's boundary linework, named by a label inside or by its leader; area through the fit vs the parcel table",
                                            "linework": "sheet vector paths through the fit and the HTDP epoch shift",
                                            "encroachment": "building-class returns inside a parcel face, clustered, roof-flatness verdict"}.get(kind, "")
            feats.append(feat(f["geometry"], kind=kind, status=status_of(p), rule=rule, **p))

    (OUT / "objects.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    by = {}
    for f in feats:
        k = (f["properties"]["kind"], f["properties"]["status"]); by[k] = by.get(k, 0) + 1
    print(f"objects.geojson: {len(feats)} objects")
    for (k, s), n in sorted(by.items()):
        print(f"  {k:18} {s:9} {n:5}")


if __name__ == "__main__":
    main()
