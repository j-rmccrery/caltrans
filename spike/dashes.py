"""Dash trains: the dashed easement line (layer rw_EASE_EXIST_align on Presidio, ~350 short strokes,
no dash pattern -- every dash is its own path) chained into polylines checks.py and parcels.py can use
as arcs/lines, the same way the solid R/W curves already are. See STATE.md 2026-09-23, spike/LOOP.md
loop 2 leg B.
usage: [SHEET=<pdf>] python spike/dashes.py  -> prints train count/lengths, writes
  spike/out[/<sheet>]/dash_trains.png (diagnostic crop over the strip region)
"""
import math
import sys
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402

REACH = 20.0     # pt: next dash must begin within ~1.5 dash lengths (dashes run <=6 pt) + 10 pt gap
SIDE_TOL = 1.0   # pt: sideways offset off the current heading
TURN_DEG = 12.0  # deg: max heading change dash to dash (the strip curves turn well under 2 deg per dash)


def _strokes(d):
    for it in d["items"]:
        if it[0] == "l":
            a, b = np.array([it[1].x, it[1].y]), np.array([it[2].x, it[2].y])
            L = float(np.hypot(*(b - a)))
            if 0 < L < 8:
                yield a, b


def collect_dashes(page):
    """Short strokes that make up the dashed easement line: strokes on a CAD layer named rw_EASE*.
    Tried a layer-free fallback (black 0.84-pt strokes under 8 pt inside the map area) for sheets with
    no such layer: on r10434_1/.3 it pulls in thousands of ordinary 0.84-pt parcel-line and tick
    segments (2,800+ strokes, 250+ bogus "trains") since nothing there marks them as dashes without
    the layer name. Restricted to the layer, per STATE.md's rule for this kind of false candidate;
    sheets without an easement layer simply get no dash trains."""
    return [(a, b) for d in page.get_drawings() if "rw_EASE" in (d.get("layer") or "") for a, b in _strokes(d)]


def circle_fit(P):
    """Algebraic (Kasa) circle fit through the train's points; NaN if too few points or the fit is
    poor (a near-straight run, or noise)."""
    if len(P) < 4:
        return float("nan")
    x, y = P[:, 0], P[:, 1]
    sol, *_ = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x ** 2 + y ** 2, rcond=None)
    cx, cy, c = sol
    r = math.sqrt(max(c + cx ** 2 + cy ** 2, 0))
    resid = float(np.sqrt(np.mean((np.hypot(x - cx, y - cy) - r) ** 2)))
    return r if 0 < r < 1e5 and resid < 0.02 * r + 0.3 else float("nan")


def dash_trains(dashes):
    """Chain dashes end to end into polylines: from each dash's free end, the next dash's near end
    must lie within REACH straight ahead (sideways offset < SIDE_TOL, never behind), and its own
    heading must turn less than TURN_DEG from the current one. Returns
    [{"pts": Nx2 array, "len_pt": float, "radius_pt": float}], lone unmatched dashes dropped."""
    if not dashes:  # sheets with no rw_EASE layer (r10434_1/.3): no trains, not an error
        return []
    ends = np.array([q for a, b in dashes for q in (a, b)])
    tree = cKDTree(ends)
    idx = [(k, e) for k in range(len(dashes)) for e in (0, 1)]
    used, trains = set(), []
    for k0 in range(len(dashes)):
        if k0 in used:
            continue
        a0, b0 = dashes[k0]
        d0 = (b0 - a0) / max(np.hypot(*(b0 - a0)), 1e-9)
        used.add(k0)
        sides = {}
        for start, direction in ((a0, -1), (b0, 1)):
            cur, cur_dir, pts = start, d0 * direction, []
            while True:
                cands = []
                for j in tree.query_ball_point(cur, REACH):
                    k, e = idx[j]
                    if k in used:
                        continue
                    a, b = dashes[k]
                    near, far = (a, b) if e == 0 else (b, a)
                    v = near - cur
                    along, side = v @ cur_dir, abs(v @ np.array([-cur_dir[1], cur_dir[0]]))
                    if along < -0.5 or side > SIDE_TOL:
                        continue
                    dl = (far - near) / max(np.hypot(*(far - near)), 1e-9)
                    turn = dl @ cur_dir
                    if turn < math.cos(math.radians(TURN_DEG)):
                        continue
                    cands.append((turn, k, far, dl))  # most collinear continuation wins, not merely nearest --
                # two nearly-parallel dashed curves pass within REACH of each other near the record's
                # vertex circles; picking the straightest continuation (not the closest dash) keeps the
                # chain on its own curve instead of hopping to the neighbour
                if not cands:
                    break
                _, k, far, dl = max(cands, key=lambda t: t[0])
                used.add(k); pts.append(far); cur, cur_dir = far, dl
            sides[direction] = pts
        pts = list(reversed(sides[-1])) + [a0, b0] + sides[1]
        P = np.array(pts)
        L = float(np.sum(np.hypot(*np.diff(P, axis=0).T)))
        trains.append({"pts": P, "len_pt": L, "radius_pt": circle_fit(P)})
    trains = [t for t in trains if len(t["pts"]) >= 3]
    return dedupe(trains)


def dedupe(trains, tol=15.0, cover_frac=0.8):
    """A chain most of whose points (>= cover_frac) fall within tol pt of an already-kept, longer chain
    is the same physical dashed run walked again from a different starting dash (the algorithm above
    ends up on slightly different dashes near a vertex circle where two curves nearly touch) -- not a
    separate line, even though the shorter one may run past the longer one's end at either tip. Keep
    the longer one only: feeding both into parcels.py's polygonisation braided the boundary between
    them, carving 61985-2/-3 into slivers 73-85% too small (STATE.md 2026-09-23). Asymmetric on
    purpose -- checked against the *kept* chain's points, not the other way, so a short chain fully
    inside a long one is dropped even though the long one clearly is not inside the short one."""
    trains = sorted(trains, key=lambda t: -t["len_pt"])
    kept = []
    for t in trains:
        dup = False
        for k in kept:
            tree = cKDTree(k["pts"])
            d, _ = tree.query(t["pts"])
            if (d < tol).mean() >= cover_frac:
                dup = True
                break
        if not dup:
            kept.append(t)
    return kept


def render(page, trains, path):
    """Diagnostic crop: each train in its own colour over the strip region (sheet pt 700-1800 x, 550-1000 y), 3x."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x0, y0, x1, y1 = 700, 550, 1800, 1000
    pix = page.get_pixmap(clip=pymupdf.Rect(x0, y0, x1, y1), matrix=pymupdf.Matrix(3, 3))
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    fig, ax = plt.subplots(figsize=(pix.width / 150, pix.height / 150), dpi=150)
    ax.imshow(img, extent=(x0, x1, y1, y0))
    cmap = plt.get_cmap("tab20")
    for i, t in enumerate(trains):
        P = t["pts"]
        ax.plot(P[:, 0], P[:, 1], "-", color=cmap(i % 20), linewidth=1.8)
    ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.axis("off")
    fig.tight_layout(pad=0); fig.savefig(path, dpi=150); plt.close(fig)


def main():
    page = pymupdf.open(PDF)[0]
    dashes = collect_dashes(page)
    trains = dash_trains(dashes)
    trains.sort(key=lambda t: -t["len_pt"])
    print(f"dashes {len(dashes)} -> trains {len(trains)}")
    for t in trains[:12]:
        r = f"{t['radius_pt']:.1f}" if t["radius_pt"] == t["radius_pt"] else "nan"
        print(f"  len {t['len_pt']:7.1f} pt  n {len(t['pts']):3}  radius {r} pt")
    render(page, trains, OUT / "dash_trains.png")
    return trains


if __name__ == "__main__":
    main()
