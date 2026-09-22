"""Second control path: georeference from grid tick labels.

Many sheets print no N/E callouts; they label grid lines instead ("X 1546500", "6,433,000", "N1,850,500").
The label is written along a stub of the grid line. Every point of that stub satisfies one linear
equation in the similarity parameters:
    easting line :  a*sx - b*sy + tx = E          northing line :  b*sx + a*sy + ty = N
Least squares over all stubs, drop bad ones, report residuals (perpendicular distance, ground units).
Usage: SHEET=<pdf> python spike/georef_ticks.py      (needs read_rapid.json for that sheet)
"""
import itertools
import json
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, frame, segments  # noqa: E402

TICK = re.compile(r"^([NEXY])?[:.]?(\d{0,2}[,.]?\d{3}[,.]?\d00)$")  # 6 digits (CCS27 Y) to 8


def tick_labels(blocks):
    out = []
    for b in blocks:
        m = TICK.match(b["text"].replace(" ", "").upper())
        if m and len(re.sub(r"\D", "", m[2])) >= 6:
            out.append({"b": b, "value": float(re.sub(r"\D", "", m[2])), "axis": {"N": "N", "Y": "N", "E": "E", "X": "E"}.get(m[1])})
    return out


def stub(label, segs):
    """Closest segment running parallel to the label text, right beside it."""
    b = label["b"]
    c, u, n = frame(b)
    best = None
    for a0, a1, w, _ in segs:
        d = (a1 - a0) / np.hypot(*(a1 - a0))
        if abs(d @ n) > 0.05:  # not parallel to the text (3 deg)
            continue
        mid = (a0 + a1) / 2 - c
        perp = abs(mid @ n)
        lo, hi = sorted(((a0 - c) @ u, (a1 - c) @ u))
        if np.hypot(*(a1 - a0)) < 6 or perp < 0.5 * b["h"]:
            continue  # a stroke of one of the label's own digits, not the grid line
        # the stub sits under the text (rank 0), or, for grid crosses, just past the end of it (rank 1)
        under = lo < b["w"] / 2 and hi > -b["w"] / 2
        beside = lo < b["w"] / 2 + 1.2 * b["w"] and hi > -b["w"] / 2 - 1.2 * b["w"]
        if perp < 3.0 * b["glyph_h"] and (under or beside):
            key = (0 if under else 1, perp)
            if best is None or key < best[0]:
                best = (key, a0, a1)
    return None if best is None else best[1:]


def solve(rows):
    A = np.array([r[0] for r in rows]); L = np.array([r[1] for r in rows])
    p, *_ = np.linalg.lstsq(A, L, rcond=None)
    return p, A @ p - L


def fit(labels, assign):
    """assign: per label 'E' or 'N'. Two equations per label (both stub ends). Drops labels worse than 2 units."""
    keep = list(range(len(labels)))
    while True:
        rows, owner = [], []
        for i in keep:
            for q in labels[i]["ends"]:
                sx, sy = q[0], -q[1]
                rows.append(([sx, -sy, 1, 0], labels[i]["value"]) if assign[i] == "E" else ([sy, sx, 0, 1], labels[i]["value"]))
                owner.append(i)
        if len(set(assign[i] for i in keep)) < 2 or len(keep) < 3:
            return None
        p, r = solve(rows)
        worst = {i: max(abs(x) for x, o in zip(r, owner) if o == i) for i in keep}
        bad = max(worst, key=worst.get)
        if worst[bad] < 2.0 or len(keep) <= 3:
            return p, worst, keep
        keep.remove(bad)


COORD = re.compile(r"^[NEXY]?[:.]?(\d{0,2},?\d{3},?\d{3}\.\d{2,3})$")


def check_callouts(blocks, segs, p):
    """Independent check: printed coordinate pairs with leaders were not used in the tick fit."""
    from scipy.spatial import cKDTree
    from georef import trace_leader
    a, b, tx, ty = p
    nums = [(bl, float(m[1].replace(",", ""))) for bl in blocks if (m := COORD.match(bl["text"].replace(" ", "").upper()))]
    ends = np.array([q for s0, s1, _, _ in segs for q in (s0, s1)])
    idx = [(k, e) for k in range(len(segs)) for e in (0, 1)]
    tree = cKDTree(ends)
    res = []
    for nb, nv in nums:
        c, u, n = frame(nb)
        for eb, ev in nums:
            d = np.array([eb["cx"], eb["cy"]]) - c
            if eb is nb or not (abs(d @ u) < 0.5 * nb["w"] and 1.0 * nb["glyph_h"] < d @ n < 3.2 * nb["glyph_h"]):
                continue
            tips = trace_leader({"nb": nb, "eb": eb}, segs, tree, idx)
            if tips is None:
                continue
            g = [np.hypot(a * t[0] + b * t[1] + tx - ev, b * t[0] - a * t[1] + ty - nv) for t in tips]
            res.append(min(g))
    if res:
        r = np.array(res)
        print(f"independent check, {len(r)} printed coordinate callouts (not used in fit): median {np.median(r):.2f}, within 1.0: {(r < 1).sum()}/{len(r)}, all: {np.round(np.sort(r), 2).tolist()[:12]}")
    else:
        print("independent check: no coordinate callouts with leaders found on this sheet")


def main():
    page = pymupdf.open(PDF)[0]
    blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8"))
    segs, _ = segments(page)
    labels = []
    for t in tick_labels(blocks):
        s = stub(t, segs)
        if s is not None:
            t["ends"] = s
            labels.append(t)
    print(f"tick labels read {len(tick_labels(blocks))} | with a grid-line stub {len(labels)}")
    if len(labels) < 3:
        raise SystemExit("not enough grid ticks for a fit")

    # labels along one direction are all eastings or all northings; the prefix says which, else try both
    ang = np.array([l["b"]["angle"] % 180 for l in labels])
    g0 = np.abs(((ang - ang[0]) + 90) % 180 - 90) < 20
    options = []
    for e_group in (True, False):
        assign = ["E" if g == e_group else "N" for g in g0]
        if any(l["axis"] and l["axis"] != a for l, a in zip(labels, assign)):
            continue
        ev = [l["value"] for l, a in zip(labels, assign) if a == "E"]
        nv = [l["value"] for l, a in zip(labels, assign) if a == "N"]
        if ev and nv and np.median(ev) < np.median(nv) and not any(l["axis"] for l in labels):
            continue  # California state plane, 1927 and 1983: eastings are always the larger numbers
        res = fit(labels, assign)
        if res:
            options.append((-len(res[2]), np.sqrt(np.mean(np.square([res[1][i] for i in res[2]]))), assign, res))
    if not options:
        raise SystemExit("no consistent easting/northing assignment")
    _, rms, assign, (p, worst, keep) = min(options, key=lambda o: o[:2])
    a, b, tx, ty = p
    scale, rot = float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)))
    print(f"fit on {len(keep)}/{len(labels)} grid lines | scale {scale:.5f} units/pt | rotation {rot:.4f} deg | rms {rms:.2f} max {max(worst[i] for i in keep):.2f} (ground units)")
    for i, l in enumerate(labels):
        tag = "" if i in keep else "  <- rejected"
        print(f"  {assign[i]} {l['value']:>12,.0f}  text angle {l['b']['angle']:7.2f}  residual {worst.get(i, float('nan')):6.2f}{tag}")
    (OUT / "georef_ticks.json").write_text(json.dumps({
        "note": "x=a*sx-b*sy+tx, y=b*sx+a*sy+ty with sy=-pdf_y; ground units and datum as printed on the sheet",
        "params": [float(v) for v in p], "scale_per_pt": scale, "rotation_deg": rot, "rms": float(rms), "lines_used": len(keep)}, indent=1))

    check_callouts(blocks, segs, p)

    from georef import vs_caltrans_package
    vs_caltrans_package(page, p)


if __name__ == "__main__":
    main()
