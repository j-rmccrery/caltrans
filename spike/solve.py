"""One georeferencing solver over every kind of printed control on a sheet.

Observations, all linear in the similarity parameters (a, b, tx, ty) with sy = -pdf_y:
  point   (coordinate callout / monument note, one of several candidate sheet points)
          a*sx - b*sy + tx = E   and   b*sx + a*sy + ty = N
  line    (grid tick label along a grid-line stub; each stub end)
          E-line: a*sx - b*sy + tx = E        N-line: b*sx + a*sy + ty = N
Hypotheses come from pairs of point candidates and from the tick-only fit; the one that explains the
most observations wins, then everything it explains is refit together. A sheet with two callouts and
five grid lines, which neither path alone can verify, has plenty of redundancy here.
Usage: SHEET=<pdf> python spike/solve.py   ->  spike/out/<sheet>/georef.json (same format as georef.py)
"""
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from georef import (DEFAULT, OUT, READS, PDF, apply, callouts, frame, monument_symbols, ngs_points, package_affine,  # noqa: E402
                    package_xy, real_text_blocks, segments, similarity, snap_circle, trace_leader, vs_caltrans_package)
from georef_ticks import fit as tick_fit, stub, tick_labels  # noqa: E402

TOL = 1.0  # sheet ground units (ft or m): an observation the hypothesis explains


def gather(page, blocks):
    segs, circles = segments(page)
    ends = np.array([q for s0, s1, _, _ in segs for q in (s0, s1)])
    idx = [(k, e) for k in range(len(segs)) for e in (0, 1)]
    tree, ctree = cKDTree(ends), cKDTree(circles)
    symbols = np.array(monument_symbols(page)) if len(page.get_drawings()) else np.zeros((0, 2))

    points = []
    from gt import TABLES
    for co in callouts(blocks, [t[0] for t in TABLES.values()] if PDF == DEFAULT else []) + ngs_points(blocks):
        cands = []
        if co.get("note"):
            b = co["nb"]
            for q in symbols:
                if abs(q[0] - b["cx"]) < b["w"] * 0.9 + 15 and abs(q[1] - b["cy"]) < b["h"] * 0.9 + 15:
                    cands.append((q[0], -q[1]))
                    for k in tree.query_ball_point(q, 6):
                        seg = segs[idx[k][0]]
                        far = seg[1] if idx[k][1] == 0 else seg[0]
                        cands.append((far[0], -far[1]))
        for tip in trace_leader(co, segs, tree, idx) or []:
            pt, _ = snap_circle(tip, circles, ctree)
            cands.append((pt[0], -pt[1]))
        if cands:
            points.append({"E": co["E"], "N": co["N"], "cands": np.array(cands, float), "note": bool(co.get("note"))})

    lines = []
    for t in tick_labels(blocks):
        s = stub(t, segs)
        if s is not None:
            lines.append({"value": t["value"], "axis": t["axis"], "angle": t["b"]["angle"],
                          "ends": np.array([[q[0], -q[1]] for q in s], float)})
    return points, lines


def line_res(p, ln, axis):
    a, b, tx, ty = p
    sx, sy = ln["ends"][:, 0], ln["ends"][:, 1]
    v = a * sx - b * sy + tx if axis == "E" else b * sx + a * sy + ty
    return float(np.abs(v - ln["value"]).max())


def score(p, points, lines):
    """Per observation: residual, and which candidate / axis explains it best."""
    pr = [(float(r.min()), int(r.argmin())) for r in (np.hypot(*(apply(p, pt["cands"]) - [pt["E"], pt["N"]]).T) for pt in points)]
    lr = []
    for ln in lines:
        axes = [ln["axis"]] if ln["axis"] else ["E", "N"]
        r = [(line_res(p, ln, ax), ax) for ax in axes]
        lr.append(min(r))
    return pr, lr


def refit(p, points, lines):
    pr, lr = score(p, points, lines)
    rows, rhs = [], []
    used_pts = [i for i, (r, _) in enumerate(pr) if r < TOL]
    used_lns = [i for i, (r, _) in enumerate(lr) if r < TOL]
    for i in used_pts:
        sx, sy = points[i]["cands"][pr[i][1]]
        rows += [[sx, -sy, 1, 0], [sy, sx, 0, 1]]; rhs += [points[i]["E"], points[i]["N"]]
    for i in used_lns:
        for sx, sy in lines[i]["ends"]:
            rows.append([sx, -sy, 1, 0] if lr[i][1] == "E" else [sy, sx, 0, 1]); rhs.append(lines[i]["value"])
    if len(rows) < 4:
        return p, used_pts, used_lns, pr, lr
    q, *_ = np.linalg.lstsq(np.array(rows, float), np.array(rhs, float), rcond=None)
    return q, used_pts, used_lns, pr, lr


def hypotheses(points, lines):
    hs = []
    for i, j in itertools.combinations(range(len(points)), 2):
        for ci, cj in itertools.product(points[i]["cands"], points[j]["cands"]):
            if np.hypot(*(ci - cj)) > 20:
                hs.append(similarity(np.array([ci, cj]), np.array([[points[i]["E"], points[i]["N"]], [points[j]["E"], points[j]["N"]]])))
    if len(lines) >= 3:
        ang = np.array([ln["angle"] % 180 for ln in lines])
        g0 = np.abs(((ang - ang[0]) + 90) % 180 - 90) < 20
        for e_group in (True, False):
            assign = ["E" if g == e_group else "N" for g in g0]
            if any(ln["axis"] and ln["axis"] != a for ln, a in zip(lines, assign)):
                continue
            # tick_fit flips y itself, so hand it pdf-space ends
            r = tick_fit([dict(ln, ends=ln["ends"] * [1, -1]) for ln in lines], assign)
            if r:
                hs.append(r[0])
                # grid lines fix direction and scale; one callout can then fix the offset the lines leave open
                a, b = r[0][:2]
                for pt in points:
                    for sx, sy in pt["cands"]:
                        hs.append(np.array([a, b, pt["E"] - (a * sx - b * sy), pt["N"] - (b * sx + a * sy)]))
    return hs


def mode(vals, tol, period=None):
    """Median of the densest cluster (values within tol of a member), or None with fewer than 3 in it."""
    vals = np.array(vals, float)
    if len(vals) < 3:
        return None, 0
    d = np.abs(vals[:, None] - vals[None, :])
    if period:
        d = np.minimum(d, period - d)
    k = int((d < tol).sum(1).argmax())
    inl = vals[d[k] < tol]
    if len(inl) < 3:
        return None, 0
    if period:
        inl = vals[k] + ((inl - vals[k] + period / 2) % period - period / 2)
    return float(np.median(inl)), len(inl)


def record_frame(page, blocks, points, scale=None):
    """A sheet without a grid (most right-of-way maps): the printed bearings fix the rotation, each
    against the drawn line it labels; the printed distances fix the scale the same way; one coordinate
    callout, if there is one, fixes the offset. A label matched to the wrong line is an outlier to the
    cluster, not a vote. Returns (params, votes) or None."""
    import checks
    from checks import BEAR, azimuth, dist_num, nearest_line, seg_dist, sheet_lines, tag_leaders
    checks.set_decimals(blocks)
    DIST, TOKEN = checks.DIST, checks.TOKEN
    chains, _, paths, _ = sheet_lines(page, blocks)
    tips = tag_leaders(blocks, paths)
    rots, scales = [], []
    for bi, b in enumerate(blocks):
        for part in [m.group(0) for t in b["text"].replace(" ", "").split("|") for m in TOKEN.finditer(t)]:
            ln = None
            if bi in tips:
                near = min(((seg_dist(tips[bi][0], c["p0"], c["p1"]), c) for c in chains), key=lambda t: t[0], default=None)
                ln = near[1] if near and near[0] < 4.0 else None
            ln = ln or nearest_line(b, chains, 5.0 * b["glyph_h"])
            if ln is None:
                continue
            if BEAR.match(part) and not BEAR.match(part)[6]:
                rots.append((math.degrees(math.atan2(ln["dir"][0], -ln["dir"][1])) - azimuth(part)) % 180)
            elif DIST.match(part):
                num_str, is_total = dist_num(DIST.match(part))
                if not is_total and ln["len_pt"] > 5:
                    scales.append(math.log(float(num_str) / ln["len_pt"]))
    rot, n_rot = mode(rots, 0.5, period=180)
    ls, n_sc = mode(scales, 0.005)
    print(f"record frame: rotation from {n_rot}/{len(rots)} bearings, scale from {n_sc}/{len(scales)} distances")
    if rot is None or (ls is None and scale is None):
        return None
    scale = math.exp(ls) if ls is not None else scale  # a caller with a scale of its own only needs the rotation confirmed

    def offsets(rot):  # (tx, ty) each callout implies under this rotation, from its first candidate point
        a, b = scale * math.cos(math.radians(rot)), scale * math.sin(math.radians(rot))
        return a, b, np.array([[pt["E"] - (a * sx - b * sy), pt["N"] - (b * sx + a * sy)] for pt in points for sx, sy in pt["cands"][:1]])

    # a bearing allows two rotations 180 apart; two callouts that agree on the offset settle it, else north up (or nearest)
    rot = (rot + 90) % 180 - 90
    if len(points) >= 2:
        rot = min((rot, rot + 180), key=lambda r: np.ptp(offsets(r)[2], axis=0).sum())
    a, b, off = offsets(rot)
    tx = ty = 0.0
    offset = "none: local frame (no coordinate callout read)"
    if len(off):
        tx, ty = np.median(off, axis=0)
        offset = f"{len(off)} callouts, spread {np.ptp(off, axis=0).round(1).tolist()}" if len(off) > 1 else "one callout, unverified"
    return np.array([a, b, tx, ty]), {"bearings": [n_rot, len(rots)], "distances": [n_sc, len(scales)], "offset": offset}


def main():
    page = pymupdf.open(PDF)[0]
    blocks = json.loads((READS).read_text(encoding="utf-8"))
    real = real_text_blocks(page)
    blocks = [b for b in blocks if not any(abs(b["cx"] - r["cx"]) < 8 and abs(b["cy"] - r["cy"]) < 8 for r in real)] + real
    points, lines = gather(page, blocks)
    print(f"control found: {len(points)} coordinate callouts ({sum(p['note'] for p in points)} in notes), {len(lines)} grid lines")

    hs = hypotheses(points, lines)
    if not hs:
        r = record_frame(page, blocks, points)
        if r is None:
            raise SystemExit("solve: not enough control for even one hypothesis, and too few bearings or distances for a record frame")
        p, votes = r
        a, b = p[:2]
        scale, rot = float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)))
        print(f"record frame: scale {scale:.5f} units/pt | rotation {rot:.4f} deg | offset {votes['offset']}")
        frame_kind, placed_by, pkg_report = "record", None, None
        if votes["offset"].startswith("none"):
            # no callout gave an offset: borrow one from Caltrans' own package at the sheet centre,
            # keeping our sheet-derived scale and rotation. HARN vs NAD83(2011) at this site is well
            # under a foot, so no datum shift is applied here.
            aff = package_affine(page)
            if aff is not None:
                W, H = page.rect.width, page.rect.height
                gx, gy = package_xy(aff, W / 2, H / 2)
                tx = gx - a * (W / 2) - b * (H / 2)
                ty = gy - b * (W / 2) + a * (H / 2)
                p = np.array([a, b, tx, ty])
                A, D, B, E, C, F, k = aff
                a_pkg, b_pkg = (A * k - E * k) / 2, (B * k + D * k) / 2
                pkg_scale, pkg_rot = float(np.hypot(a_pkg, b_pkg)), float(np.degrees(np.arctan2(b_pkg, a_pkg)))
                dscale, drot = 100 * (pkg_scale / scale - 1), ((pkg_rot - rot + 90) % 180 - 90)
                pkg_report = {"scale_ft_per_pt": pkg_scale, "rotation_deg": pkg_rot, "dscale_pct": dscale, "drot_deg": drot}
                frame_kind, placed_by = "record+package", "caltrans package (offset only)"
                print(f"package affine: scale {pkg_scale:.5f} units/pt ({dscale:+.2f} %) | rotation {pkg_rot:.4f} deg ({drot:+.4f} deg vs ours)")
                print(f"offset from package at sheet centre: tx {tx:.1f} ty {ty:.1f}")
        vs_caltrans_package(page, p)
        (OUT / "georef.json").write_text(json.dumps({
            "note": "x=a*sx-b*sy+tx, y=b*sx+a*sy+ty with sy=-pdf_y; RECORD FRAME: rotation and scale from the printed bearings and distances, offset from one callout, the Caltrans package at the sheet centre, or none",
            "params": [float(v) for v in p], "scale_ft_per_pt": scale, "rotation_deg": rot, "rms_ft": None, "credible": False, "weak": True,
            "frame": frame_kind, "placed_by": placed_by, "votes": votes, "package": pkg_report,
            "control": [], "grid_lines": []}, indent=1))
        return
    best = None
    for h in hs:
        pr, lr = score(h, points, lines)
        n = 2 * sum(r < TOL for r, _ in pr) + sum(r < TOL for r, _ in lr)
        key = (n, -sum(min(r, TOL) for r, _ in pr) - sum(min(r, TOL) for r, _ in lr))
        if best is None or key > best[0]:
            best = (key, h)
    p = best[1]
    for _ in range(3):
        p, used_pts, used_lns, pr, lr = refit(p, points, lines)

    a, b, tx, ty = p
    scale, rot = float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)))
    eqs = 2 * len(used_pts) + 2 * len(used_lns)
    feats = len(used_pts) + len(used_lns)
    res = [pr[i][0] for i in used_pts] + [lr[i][0] for i in used_lns]
    rms = float(np.sqrt(np.mean(np.square(res)))) if res else float("nan")
    print(f"fit: {len(used_pts)}/{len(points)} callouts + {len(used_lns)}/{len(lines)} grid lines | scale {scale:.5f} units/pt | rotation {rot:.4f} deg | rms {rms:.2f} max {max(res, default=0):.2f}")
    for i, pt in enumerate(points):
        print(f"  point E {pt['E']:>13,.2f} N {pt['N']:>13,.2f}  residual {pr[i][0]:8.2f}{'' if i in used_pts else '  <- rejected'}")
    for i, ln in enumerate(lines):
        print(f"  line  {lr[i][1]} {ln['value']:>13,.0f}                  residual {lr[i][0]:8.2f}{'' if i in used_lns else '  <- rejected'}")
    on_e = len(used_pts) + sum(lr[i][1] == "E" for i in used_lns)  # features that pin the easting offset
    on_n = len(used_pts) + sum(lr[i][1] == "N" for i in used_lns)
    credible = eqs >= 8 and feats >= 4 and min(on_e, on_n) >= 2
    if credible:
        print("credible")
    elif eqs >= 8 and feats >= 4:
        print(f"WEAK: {'northing' if on_n < 2 else 'easting'} offset rests on a single feature; unverified in that axis")
    else:
        print("NOT credible: too little agreeing control")
    weak = eqs >= 8 and feats >= 4 and not credible
    verified = None
    if not credible and not weak and len(used_pts) >= 2:
        # two callouts fix a frame nothing else on the sheet confirms; the printed bearings can confirm its rotation
        r = record_frame(page, blocks, points, scale)
        if r is not None:
            ra, rb = r[0][:2]
            rrot, rscale = float(np.degrees(np.arctan2(rb, ra))), float(np.hypot(ra, rb))
            drot = abs((rot - rrot + 90) % 180 - 90)
            print(f"record frame says rotation {rrot:.4f} (off {drot:.4f} deg), scale {rscale:.5f} ({100 * (rscale / scale - 1):+.2f} %)")
            if drot < 0.1:
                weak, verified = True, f"rotation confirmed by {r[1]['bearings'][0]} bearings; scale rests on the callout pair" + (f", confirmed by {r[1]['distances'][0]} distances" if r[1]['distances'][0] else "")
                print("WEAK:", verified)
    vs_caltrans_package(page, p)
    (OUT / "georef.json").write_text(json.dumps({
        "note": "x=a*sx-b*sy+tx, y=b*sx+a*sy+ty with sy=-pdf_y; ground units and datum as printed on the sheet",
        "params": [float(v) for v in p], "scale_ft_per_pt": scale, "rotation_deg": rot, "rms_ft": rms, "credible": bool(credible), "weak": bool(weak), "verified": verified,
        "control": [{"E": pt["E"], "N": pt["N"], "sx": float(pt["cands"][pr[i][1]][0]), "sy": float(pt["cands"][pr[i][1]][1]),
                     "residual_ft": pr[i][0], "used": i in used_pts} for i, pt in enumerate(points)],
        "grid_lines": [{"axis": lr[i][1], "value": ln["value"], "residual": lr[i][0], "used": i in used_lns} for i, ln in enumerate(lines)]}, indent=1))
    assert credible or weak, "fit is not credible"


if __name__ == "__main__":
    main()
