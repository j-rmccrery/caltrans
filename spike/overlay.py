"""Draw the sheet's vector linework on the LiDAR intensity image, using the fit from georef.py.

sheet pt -> CCS83 Z3 ftUS (EPSG:2227, epoch 1991.35) -> NAD83(2011) UTM 10N m (EPSG:6339)
-> + HTDP epoch displacement 1991.35 -> 2010.0 (measured in spike/lidar/q3).
Writes spike/out/overlay_full.png, overlay_zoom.png, sheet_linework.geojson (lon/lat).
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymupdf
from matplotlib.collections import LineCollection
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).parent))
from gt import TABLES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf"
OUT = Path(__file__).parent / "out"
CACHE = Path(__file__).parent / "lidar" / "cache"
_h = json.loads((Path(__file__).parent / "lidar" / "htdp.json").read_text())  # cached NGS HTDP result (spike/lidar/q3)
HTDP_DN, HTDP_DE = _h["dN_m"], _h["dE_m"]
# the sheet's own frame (frame.py) and its tables (alphabet.py) when they exist; the Presidio constants otherwise
from blocks import OUT as _SHEET_OUT  # noqa: E402  (SHEET-aware, unlike OUT above)
_frame = json.loads((_SHEET_OUT / "frame.json").read_text()) if (_SHEET_OUT / "frame.json").exists() else None
_tables = json.loads((_SHEET_OUT / "tables.json").read_text(encoding="utf-8")).get("_regions", []) if (_SHEET_OUT / "tables.json").exists() else []
MAP_AREA = tuple(_frame["map_area"]) if _frame else (255, 60, 2400, 1285)  # pt; inside the border, above the parcel table and title block
FURNITURE = ([tuple(x) for x in _frame["furniture"]] + [tuple(x) for x in _tables]) if _frame else [t[0] for t in TABLES.values()] + [(255, 60, 620, 125), (2030, 60, 2400, 120)]


def bezier(p0, p1, p2, p3, n=12):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def linework(page):
    """Polylines (pt) split into heavy (R/W and parcel lines) and light, skipping glyphs, hatch and tables."""
    heavy, light = [], []
    x0, y0, x1, y1 = MAP_AREA
    for d in page.get_drawings():
        r, c = d["rect"], d.get("color")
        if c is None or max(c) > 0.2 or max(r.width, r.height) <= 12:
            continue
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if not (x0 < cx < x1 and y0 < cy < y1) or any(a <= cx <= b2 and b <= cy <= d2 for a, b, b2, d2 in FURNITURE):
            continue
        dest = heavy if (d.get("width") or 0) >= 1.0 else light
        for it in d["items"]:
            if it[0] == "l":
                dest.append(np.array([[it[1].x, it[1].y], [it[2].x, it[2].y]]))
            elif it[0] == "c":
                dest.append(bezier(*[np.array([p.x, p.y]) for p in it[1:5]]))
    return heavy, light


def main():
    g = json.loads((OUT / "georef.json").read_text())
    a, b, tx, ty = g["params"]
    to_utm = Transformer.from_crs("EPSG:2227", "EPSG:6339", always_xy=True)
    to_ll = Transformer.from_crs("EPSG:6339", "EPSG:6318", always_xy=True)

    def ground(poly):
        sx, sy = poly[:, 0], -poly[:, 1]
        E, N = a * sx - b * sy + tx, b * sx + a * sy + ty
        x, y = to_utm.transform(E, N)
        return np.c_[np.asarray(x) + HTDP_DE, np.asarray(y) + HTDP_DN]

    heavy, light = linework(pymupdf.open(PDF)[0])
    H, L = [ground(p) for p in heavy], [ground(p) for p in light]

    img = np.load(CACHE / "ortho_intensity_1m.npy")
    xmin, xmax, ymin, ymax = np.load(CACHE / "ortho_bounds.npy")[:4]
    lo, hi = np.percentile(img[img > 0], [2, 98])
    img = np.clip((img - lo) / (hi - lo), 0, 1)

    allpts = np.vstack(H)
    zx = (allpts[:, 0].min() - 20, allpts[:, 0].max() + 20)
    zy = (max(allpts[:, 1].min() - 20, ymin), min(allpts[:, 1].max() + 20, ymax))  # legend samples fall off the tile
    ctrl = np.array([[c["E"], c["N"]] for c in g["control"] if c["used"]])
    cx, cy = to_utm.transform(ctrl[:, 0], ctrl[:, 1])
    for name, xl, yl, size in (("overlay_full", (xmin, xmax), (ymin, ymax), (16, 7.5)), ("overlay_zoom", zx, zy, (18, 8))):
        fig, ax = plt.subplots(figsize=size, dpi=150)
        ax.imshow(img, extent=(xmin, xmax, ymin, ymax), cmap="gray", origin="upper")
        ax.add_collection(LineCollection(L, colors="#00d5ff", linewidths=0.35, alpha=0.8))
        ax.add_collection(LineCollection(H, colors="#ff2a2a", linewidths=1.1))
        ax.plot(np.asarray(cx) + HTDP_DE, np.asarray(cy) + HTDP_DN, "o", ms=5, mfc="yellow", mec="black", label="control read from sheet")
        ax.set_xlim(xl); ax.set_ylim(yl); ax.set_aspect("equal")
        ax.set_title(f"R/W Record Map R-10434.2 linework on LiDAR intensity | fit rms {g['rms_ft']:.2f} ft on {sum(c['used'] for c in g['control'])} control points | NAD83(2011) UTM 10N")
        ax.legend(loc="lower right")
        fig.tight_layout(); fig.savefig(OUT / f"{name}.png"); plt.close(fig)

    feats = []
    for kind, polys in (("heavy", H), ("light", L)):
        for p in polys:
            lon, lat = to_ll.transform(p[:, 0], p[:, 1])
            feats.append({"type": "Feature", "properties": {"weight": kind, "source": "R-10434.2"},
                          "geometry": {"type": "LineString", "coordinates": [[round(x, 8), round(y, 8)] for x, y in zip(lon, lat)]}})
    (OUT / "sheet_linework.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"heavy polylines {len(H)} | light {len(L)} | geojson features {len(feats)}")
    inside = ((allpts[:, 0] > xmin) & (allpts[:, 0] < xmax) & (allpts[:, 1] > ymin) & (allpts[:, 1] < ymax)).mean()
    print(f"heavy linework inside LiDAR extent: {inside:.1%}")
    assert inside > 0.5, "sheet does not land on the LiDAR tile"


if __name__ == "__main__":
    main()
