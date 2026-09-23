"""Leg 6b: the four 1969 R-65 hand-lettered scans, georeferenced by Caltrans' own package, on the LiDAR tile.

Each sheet (R-65.1..4) ships a package (Sample Data/d4/pkg/<stem>.tif + .tfw, EPSG:2227, CCS83 Zone 3
US survey ft -- the same CRS tag the vector-sheet fit in georef.py uses, at epoch 1991.35): reproject it
to EPSG:6339, apply the sheets' own cached 1991.35 -> 2010.0 HTDP shift (spike/lidar/htdp.json) so it
lands on the 2025 LiDAR tile the same way sheet_linework.geojson does (overlay.py), clip to the tile
extent, and write spike/out/r65/<stem>_on_tile.tif + a PNG of it over the LiDAR intensity with the 2020
sheet linework on top. Also spike/out/r65/r65_coverage.geojson: each package footprint (lon/lat) + the
tile bbox.

Second half: an independent check of the R-65.2 scan reader (scan_consensus.py's read_scan.json) against
the package. For every "agree" or "repaired" coordinate callout, its point is the nearest Hough circle
to the callout box (scan_georef.circles/REACH -- read_scan.json carries no leader-traced point of its
own, so this is always the fallback, never a special case). That circle is mapped to the package raster
by the same page-width/tif-width scale scan_georef.py already uses for `vs the Caltrans package`, giving
a CCS83 ground coordinate there. R-65.2's callouts are printed in the sheet's own local grid (see
scan_georef.py's docstring), not CCS83, so the CCS83 value is converted back with the same local-grid ->
CCS83 similarity scan_georef.py fits from its own control (there is no other way to compare a
local-grid printed value against a state-plane raster). Reports count, median/90th-pct error, count
within 2 ft.

usage: python spike/scan_on_tile.py
"""
import itertools
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymupdf
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.windows import from_bounds

import sys
sys.path.insert(0, str(Path(__file__).parent))
from georef import apply, number, similarity  # noqa: E402
from scan_georef import DPI, REACH, WINDOW, circles, fit_points, grid_scale, pairs, value_pairs  # noqa: E402

HERE = Path(__file__).parent
ROOT = HERE.parent
D4 = ROOT / "Sample Data" / "d4"
PKG = D4 / "pkg"
OUT = HERE / "out"
R65 = OUT / "r65"
TILE = OUT / "lidar_intensity.tif"
PKG_CRS = "EPSG:2227"   # tag already on all four package tifs; also the sheets' own CRS at epoch 1991.35
UTM = "EPSG:6339"
LL = "EPSG:6318"

STEMS = [("R-65.1", "r_00065_001_1969-09-01_sn-02047"),
         ("R-65.2", "r_00065_002_1969-09-01_sn-02048"),
         ("R-65.3", "r_00065_003_1969-09-01_sn-02049"),
         ("R-65.4", "r_00065_004_1969-09-01_sn-02050")]

_h = json.loads((HERE / "lidar" / "htdp.json").read_text())
HTDP_DN, HTDP_DE = _h["dN_m"], _h["dE_m"]


# ---------------------------------------------------------------- task 2: rasters on the tile ----

def on_tile(label, stem, tile_bounds):
    """Reproject one package to EPSG:6339 + HTDP shift, clip to the tile, write <stem>_on_tile.tif.
    Returns (clip array, clip transform, full-footprint bounds in EPSG:6339 before clipping)."""
    src_path = PKG / f"{stem}.tif"
    with rasterio.open(src_path) as src:
        crs = src.crs if src.crs else PKG_CRS
        note = str(src.crs) if src.crs else f"no CRS tag; assumed {PKG_CRS} (CCS83 Z3 ftUS, like the sheets)"
        dst_transform, w, h = calculate_default_transform(crs, UTM, src.width, src.height, *src.bounds)
        # package is CCS83 Z3 ftUS at the sheets' own epoch (1991.35, same CRS tag the sheet fit uses)
        # -> apply the same HTDP shift the sheets get before landing on the 2025-epoch tile (overlay.py)
        shifted = Affine(dst_transform.a, dst_transform.b, dst_transform.c + HTDP_DE,
                          dst_transform.d, dst_transform.e, dst_transform.f + HTDP_DN)
        data = np.zeros((h, w), dtype=src.dtypes[0])
        reproject(source=rasterio.band(src, 1), destination=data, src_transform=src.transform, src_crs=crs,
                  dst_transform=shifted, dst_crs=UTM, resampling=Resampling.bilinear)
    full_bounds = array_bounds(h, w, shifted)  # (left, bottom, right, top), post-shift, pre-clip

    tl, tb, tr, tt = tile_bounds
    left, bottom, right, top = max(full_bounds[0], tl), max(full_bounds[1], tb), min(full_bounds[2], tr), min(full_bounds[3], tt)
    assert right > left and top > bottom, f"{label}: package footprint does not overlap the LiDAR tile"
    win = from_bounds(left, bottom, right, top, transform=shifted).round_offsets().round_lengths()
    r0, c0 = max(int(win.row_off), 0), max(int(win.col_off), 0)
    r1, c1 = min(r0 + int(win.height), h), min(c0 + int(win.width), w)
    clip = data[r0:r1, c0:c1]
    clip_transform = shifted * Affine.translation(c0, r0)

    prof = dict(driver="GTiff", height=clip.shape[0], width=clip.shape[1], count=1, dtype=clip.dtype,
                crs=UTM, transform=clip_transform, compress="deflate")
    R65.mkdir(parents=True, exist_ok=True)
    with rasterio.open(R65 / f"{stem}_on_tile.tif", "w", **prof) as dst:
        dst.write(clip, 1)
    print(f"{label} ({stem}): package CRS {note} | reprojected {w}x{h} -> clipped {clip.shape[1]}x{clip.shape[0]} "
          f"| epoch: package is CCS83 Z3 ftUS at 1991.35 like the sheets, so the same HTDP shift applies "
          f"(dE {HTDP_DE:.3f} dN {HTDP_DN:.3f} m)")
    return clip, clip_transform, full_bounds


def figure(label, stem, clip, clip_transform, linework_utm, tile_img, tile_transform):
    fig, ax = plt.subplots(figsize=(11, 7), dpi=150)
    tb = array_bounds(tile_img.shape[0], tile_img.shape[1], tile_transform)
    ax.imshow(tile_img, extent=(tb[0], tb[2], tb[1], tb[3]), cmap="gray", origin="upper", vmin=0, vmax=255)
    cb = array_bounds(clip.shape[0], clip.shape[1], clip_transform)
    masked = np.ma.masked_equal(clip, 0)
    ax.imshow(masked, extent=(cb[0], cb[2], cb[1], cb[3]), cmap="gray", origin="upper", alpha=0.85, vmin=0, vmax=255)
    for x, y in linework_utm:
        ax.plot(x, y, color="#ff2a2a", linewidth=0.5)
    ax.set_xlim(cb[0] - 30, cb[2] + 30); ax.set_ylim(cb[1] - 30, cb[3] + 30); ax.set_aspect("equal")
    ax.set_title(f"{label} (1969, Caltrans package) on the LiDAR tile, 2020 sheet linework in red")
    fig.tight_layout(); fig.savefig(R65 / f"{stem}_on_tile.png"); plt.close(fig)


def coverage(footprints):
    to_ll = Transformer.from_crs(UTM, LL, always_xy=True)
    feats = []
    for label, (l, b, r, t) in footprints:
        xs, ys = [l, r, r, l, l], [b, b, t, t, b]
        lon, lat = to_ll.transform(xs, ys)
        feats.append({"type": "Feature", "properties": {"sheet": label, "kind": "package_footprint"},
                      "geometry": {"type": "Polygon", "coordinates": [[[round(x, 8), round(y, 8)] for x, y in zip(lon, lat)]]}})
    with rasterio.open(TILE) as t:
        l, b, r, top = t.bounds
    xs, ys = [l, r, r, l, l], [b, b, top, top, b]
    lon, lat = to_ll.transform(xs, ys)
    feats.append({"type": "Feature", "properties": {"sheet": "tile", "kind": "tile_bbox"},
                  "geometry": {"type": "Polygon", "coordinates": [[[round(x, 8), round(y, 8)] for x, y in zip(lon, lat)]]}})
    (R65 / "r65_coverage.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print(f"r65_coverage.geojson: {len(footprints)} package footprints + tile bbox")


# --------------------------------------------- task 3: R-65.2 callouts vs the package, independently ----

def fit_local_grid(page, img):
    """Reproduce scan_georef.py's own pass1/pass2 fit: pdf pt -> R-65.2's local grid (N, E).
    Same functions and thresholds scan_georef.py uses (circles/pairs/value_pairs/fit_points); its
    build() is a closure inside main() so it is reproduced here rather than imported."""
    pts, _ = circles(img)
    blocks = json.loads((OUT / "r_00065_002_1969-09-01_sn-02048" / "read_rapid.json").read_text(encoding="utf-8"))
    stacked = pairs(blocks)
    gs, n_gs = grid_scale(blocks)

    def build(agreed_only, predict=None):
        points, g = [], 0
        for nb, eb in stacked:
            mid = np.array([(nb["cx"] + eb["cx"]) / 2, -(nb["cy"] + eb["cy"]) / 2])
            near = pts[np.hypot(*(pts - mid).T) < REACH]
            if not len(near):
                continue
            combos = value_pairs(nb, eb, agreed_only)
            if predict is not None:
                pe, pn = predict(mid)
                combos = {(N, E) for N, E in combos if abs(N - pn) < WINDOW and abs(E - pe) < WINDOW}
            for N, E in combos:
                points.append({"N": N, "E": E, "cands": near, "group": g, "label": f"{nb['text']} / {eb['text']}"})
            g += 1
        return points

    p1 = build(agreed_only=False)
    r1 = fit_points(p1, gs)
    assert r1, "R-65.2: pass 1 fit failed (no agreeing groups) -- cannot bridge local grid to the package"
    p, s = r1
    predict = lambda mid: apply(p, mid)[0]
    p2 = build(agreed_only=False, predict=predict)
    r2 = fit_points(p2, gs) if len({q["group"] for q in p2}) >= 2 else None
    if r2:
        p, s = r2
    ok = sum(r < 1.0 for r, _, _ in s.values())
    scale_ok = gs is not None and abs(np.hypot(p[0], p[1]) / gs - 1) < 0.03
    credible = ok >= 4 and scale_ok
    verdict = "credible" if credible else "NOT credible by scan_georef.py's own gate -- downstream ft errors below carry this fit's own uncertainty, not just reader error"
    print(f"R-65.2 local-grid fit (scan_georef pass1/2, reproduced): {ok} agreeing groups of {len(s)}, "
          f"scale {np.hypot(p[0], p[1]):.4f} units/pt, rotation {np.degrees(np.arctan2(p[1], p[0])):.3f} deg | "
          f"grid-label scale {gs if gs else 'unavailable (' + str(n_gs) + ' estimates)'} | {verdict}")
    return p, pts


def local_to_ccs83(page, pdf_stem, p):
    """The local-grid -> CCS83 similarity implied by the package (scan_georef.py's `vs Caltrans package`
    block, kept here instead of only printed so it can be inverted)."""
    tfw = PKG / f"{pdf_stem}.tfw"
    A, D, B, E, C, F = [float(v) for v in tfw.read_text().split()]
    with rasterio.open(tfw.with_suffix(".tif")) as rr:
        k = rr.width / page.rect.width
    W, H = page.rect.width, page.rect.height
    src, dst = [], []
    for px, py in itertools.product(np.linspace(0.1, 0.9, 5) * W, np.linspace(0.1, 0.9, 4) * H):
        src.append(apply(p, [px, -py])[0])
        col, row = px * k - 0.5, py * k - 0.5
        dst.append([A * col + B * row + C, D * col + E * row + F])
    src, dst = np.array(src), np.array(dst)
    q = similarity(src, dst)
    k2 = np.hypot(q[0], q[1])
    print(f"R-65.2 local grid -> CCS83 implied by the package: scale {k2:.4f} (1.00 expected for a local grid "
          f"in feet; {'consistent' if abs(k2 - 1) < 0.02 else 'INCONSISTENT by ' + format(abs(k2 - 1) * 100, '.1f') + '%'}), "
          f"rotation {np.degrees(np.arctan2(q[1], q[0])):.3f} deg")
    return q, k


def check_r65_2():
    stem = "r_00065_002_1969-09-01_sn-02048"
    pdf = D4 / f"{stem}.pdf"
    page = pymupdf.open(pdf)[0]
    z = DPI / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)

    p, pts = fit_local_grid(page, img)
    q, k = local_to_ccs83(page, stem, p)
    qa, qb, qtx, qty = q
    Minv = np.array([[qa, -qb], [qb, qa]])

    A, D, B, E, C, F = [float(v) for v in (PKG / f"{stem}.tfw").read_text().split()]

    reads = json.loads((OUT / stem / "read_scan.json").read_text(encoding="utf-8"))
    accepted = [b for b in reads if b["status"] in ("agree", "repaired")]
    errs, rows, no_letter, far = [], [], 0, 0
    for b in accepted:
        letter, val = number(b["text"]) or (None, None)
        if letter is None or val is None:
            continue
        # read_scan.json has no leader-traced point of its own: nearest Hough circle, per scan_georef's logic
        box_flipped = np.array([b["cx"], -b["cy"]])
        d = np.hypot(*(pts - box_flipped).T)
        j = int(d.argmin())
        if d[j] > REACH:
            far += 1
            continue
        px, py = pts[j][0], -pts[j][1]  # back to native (page-point, y-down) space
        col, row = px * k - 0.5, py * k - 0.5
        ccs83 = np.array([A * col + B * row + C, D * col + E * row + F])
        local_EN = Minv @ (ccs83 - [qtx, qty])  # inverse of q: CCS83 -> local grid
        est = local_EN[1] if letter == "N" else local_EN[0]
        err = abs(est - val)
        errs.append(err)
        rows.append((b["id"], letter, val, est, err, d[j]))
    no_letter = sum(1 for b in accepted if not number(b["text"]))
    print(f"R-65.2 callouts: {len(accepted)} accepted/repaired coordinate boxes | {no_letter} without a parseable N/E value "
          f"(excluded) | {far} with no circle within {REACH} pt (excluded)")
    for id_, letter, val, est, err, dist in sorted(rows, key=lambda r: -r[4]):
        print(f"  id {id_:>4} {letter} read {val:>10,.2f}  package-derived {est:>10,.2f}  error {err:6.2f} ft  circle dist {dist:5.1f} pt")
    if errs:
        e = np.array(errs)
        print(f"compared {len(e)} | median {np.median(e):.2f} ft | 90th pct {np.percentile(e, 90):.2f} ft | within 2 ft: {(e <= 2).sum()}/{len(e)}")
    else:
        print("compared 0 -- no accepted coordinate callout had a nearby circle")
    return errs


def main():
    with rasterio.open(TILE) as t:
        tile_bounds, tile_img, tile_transform = t.bounds, t.read(1), t.transform

    to_utm = Transformer.from_crs(LL, UTM, always_xy=True)
    lw = json.loads((OUT / "sheet_linework.geojson").read_text())
    linework_utm = []
    for feat in lw["features"]:
        xy = np.array(feat["geometry"]["coordinates"])
        x, y = to_utm.transform(xy[:, 0], xy[:, 1])
        linework_utm.append((x, y))

    footprints = []
    for label, stem in STEMS:
        clip, clip_transform, full_bounds = on_tile(label, stem, tile_bounds)
        figure(label, stem, clip, clip_transform, linework_utm, tile_img, tile_transform)
        footprints.append((label, full_bounds))
    coverage(footprints)

    print()
    check_r65_2()


if __name__ == "__main__":
    main()
