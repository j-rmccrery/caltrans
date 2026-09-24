"""Read-only probe: are the radial lines R-5..R-9 the dividers of the 61985 strip? Prints, writes nothing."""
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
from shapely.geometry import LineString

ROOT = Path(r"C:\Users\johnr\projects\caltrans")
sys.path.insert(0, str(ROOT / "spike"))
from dashes import collect_dashes, dash_trains  # noqa: E402
from georef import PDF  # noqa: E402

page = pymupdf.open(PDF)[0]
blocks = json.load(open(ROOT / "spike/out/read_shx.json", encoding="utf-8"))
tags = {b["text"]: (b["cx"], b["cy"]) for b in blocks if b["text"] in [f"R-{i}" for i in range(1, 13)] and 900 < b["cx"] < 1800 and 600 < b["cy"] < 900}
print("radial tags on the drawing:", {k: (round(x), round(y)) for k, (x, y) in tags.items()})
table = {b["text"]: (b["cx"], b["cy"]) for b in blocks if b["text"] in [f"R-{i}" for i in range(1, 13)] and b["cx"] > 1800}
print("radial table rows at:", {k: (round(x), round(y)) for k, (x, y) in table.items()})
# bearings beside the table rows
for k, (x, y) in sorted(table.items(), key=lambda kv: kv[1][1]):
    row = [b["text"] for b in blocks if abs(b["cy"] - y) < 4 and b["cx"] > x and b["cx"] < x + 120]
    print(" ", k, row)

trains = dash_trains(collect_dashes(page))
trains = sorted(trains, key=lambda t: -t["len_pt"])
north = LineString(trains[0]["pts"])
south = [LineString(t["pts"]) for t in trains[1:6]]
print("trains:", [(round(t["len_pt"]), [round(v) for v in t["pts"][0]], [round(v) for v in t["pts"][-1]]) for t in trains])

# thin straight strokes in the strip region that cross the north boundary
cands = []
for d in page.get_drawings():
    c = d.get("color")
    if c is None or max(c) > 0.2:
        continue
    w = round(d.get("width") or 0, 2)
    for it in d["items"]:
        if it[0] != "l":
            continue
        a, b = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
        L = float(np.hypot(*(a - b)))
        if L < 8 or not (950 < a[0] < 1720 and 600 < a[1] < 860):
            continue
        ls = LineString([a, b])
        dn = ls.distance(north)
        ds = min(ls.distance(s) for s in south)
        if dn < 3 and ds < 3:
            cands.append((w, round(L, 1), [round(v) for v in a], [round(v) for v in b], round(dn, 2), round(ds, 2), d.get("layer")))
print(f"strokes within 3 pt of both boundaries: {len(cands)}")
for x in sorted(cands, key=lambda x: x[2][0]):
    print(" ", x)
