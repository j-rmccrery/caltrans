"""Georeference a scanned sheet from its own coordinate callouts, with two readers and geometry.

Reads: each numeric box carries an OCR read and an independent vision-model read (scan_read.py).
  pass 1  boxes where the two readers AGREE form N/E pairs; the labelled point is one of the small
          circles near the pair; the consensus solver fits from those.
  pass 2  with a fit in hand, every other box has a predicted value from where it sits on the sheet.
          A disputed or unpaired read is accepted when one reader's parse lands inside the predicted
          window; the fit is redone with the extra control.
Ground units are whatever the sheet prints (R-65.2: a local grid in feet).
Verification: our fit and Caltrans' package must differ by one similarity; the shape residual is reported.
usage: SHEET=<scan.pdf> python spike/scan_georef.py
"""
import itertools
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, apply, frame, number, similarity  # noqa: E402

DPI = 300
REACH = 90    # pt: how far a leader may run from the callout to its point
TOL = 1.0     # ground units: an observation the hypothesis explains
WINDOW = 150  # ground units: a read must land this close to its predicted value to be accepted in pass 2


def parses(text):
    """All plausible (axis, value) readings of one string: as read, and with a decimal point restored."""
    out = set()
    t = text.replace(" ", "").upper()
    for cand in {t, re.sub(r"^([NE])[.:]?(\d{6,8})$", lambda m: f"{m[1]}{m[2][:-2]}.{m[2][-2:]}", t)}:
        v = number(cand)
        if v:
            out.add(v)
    return out


def reads(b):
    return {"rapid": parses(b["text"]), "vlm": parses(b.get("vlm", ""))}


def circles(img):
    z = DPI / 72
    c = cv2.HoughCircles(cv2.medianBlur(img, 3), cv2.HOUGH_GRADIENT, dp=1.2, minDist=10, param1=120, param2=18, minRadius=5, maxRadius=13)
    c = np.zeros((0, 3)) if c is None else c[0]
    return np.c_[c[:, 0] / z, -c[:, 1] / z], c


def pairs(blocks):
    """Stacked boxes (one above the other, same orientation) that both carry coordinate reads."""
    num = [b for b in blocks if reads(b)["rapid"] | reads(b)["vlm"]]
    out = []
    for nb in num:
        c, u, n = frame(nb)
        for eb in num:
            if eb is nb:
                continue
            d = np.array([eb["cx"], eb["cy"]]) - c
            al, pe = abs(d @ u), d @ n
            if al < 0.6 * max(nb["w"], eb["w"]) and 0.8 * nb["h"] < pe < 2.6 * max(nb["h"], eb["h"]):
                out.append((nb, eb))
    return out


def value_pairs(nb, eb, agreed_only):
    """(N, E) value combinations for a stacked pair. Letters decide the axis; else E is the larger number."""
    rn, re_ = reads(nb), reads(eb)
    top = rn["rapid"] & rn["vlm"] if agreed_only else rn["rapid"] | rn["vlm"]
    bot = re_["rapid"] & re_["vlm"] if agreed_only else re_["rapid"] | re_["vlm"]
    out = set()
    for (a1, v1), (a2, v2) in itertools.product(top, bot):
        if a1 == "E" or a2 == "N":
            continue
        if a1 == "N" or a2 == "E" or (a1 is None and a2 is None and v1 < v2):
            out.add((v1, v2))
    return out


def grid_scale(blocks):
    """Ground units per pt from pairs of same-axis grid labels (N.9000 / N.10000 ...), measured across the
    label direction. Independent of the callouts, so it also serves as a check on the fit."""
    g = []
    for b in blocks:
        for t in (b["text"], b.get("vlm", "")):
            m = re.fullmatch(r"([NE])[.:]?(\d{4,5})(?:\.00)?", t.replace(" ", "").upper())
            if m:
                g.append((m[1], float(m[2]), np.array([b["cx"], b["cy"]]), b["angle"]))
                break
    est = []
    for (a1, v1, c1, t1), (a2, v2, c2, t2) in itertools.combinations(g, 2):
        if a1 != a2 or v1 == v2 or abs(((t1 - t2) + 90) % 180 - 90) > 8:
            continue
        t = np.radians((t1 + t2) / 2)
        d = abs((c2 - c1) @ np.array([-np.sin(t), np.cos(t)]))
        if d > 20:
            est.append(abs(v2 - v1) / d)
    # a misread label (E.3000 for E.13000) gives a wild estimate; keep the value most others agree with
    best = None
    for e in est:
        n = sum(abs(o / e - 1) < 0.05 for o in est)
        if best is None or n > best[0]:
            best = (n, e)
    return (best[1], best[0]) if best and best[0] >= 2 else (None, len(est))


def fit_points(points, scale_prior=None):
    """Consensus over point groups (one value combination per group may be used), then joint refit.
    With many circle candidates per callout a wrong 4-point fit can occur by chance; a scale prior from
    the grid labels rules those out."""
    def score(p):
        best = {}
        for pt in points:
            r = np.hypot(*(apply(p, pt["cands"]) - [pt["E"], pt["N"]]).T)
            k = int(r.argmin())
            if pt["group"] not in best or r[k] < best[pt["group"]][0]:
                best[pt["group"]] = (float(r[k]), pt, k)
        return best
    hs = []
    for a, b in itertools.combinations(points, 2):
        if a["group"] == b["group"]:
            continue
        for ca, cb in itertools.product(a["cands"], b["cands"]):
            if np.hypot(*(ca - cb)) > 40:
                hs.append(similarity(np.array([ca, cb]), np.array([[a["E"], a["N"]], [b["E"], b["N"]]])))
    if not hs:
        return None
    win = None
    for h in hs:
        if scale_prior and abs(np.hypot(h[0], h[1]) / scale_prior - 1) > 0.05:
            continue
        s = score(h)
        key = (sum(r < TOL for r, _, _ in s.values()), -sum(min(r, TOL) for r, _, _ in s.values()))
        if win is None or key > win[0]:
            win = (key, h)
    p = win[1]
    for _ in range(3):
        s = score(p)
        src = np.array([pt["cands"][k] for r, pt, k in s.values() if r < TOL])
        dst = np.array([[pt["E"], pt["N"]] for r, pt, k in s.values() if r < TOL])
        if len(src) >= 2:
            p = similarity(src, dst)
    return p, score(p)


def main():
    page = pymupdf.open(PDF)[0]
    z = DPI / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    pts, raw = circles(img)
    blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8"))
    n_two = sum(1 for b in blocks if "vlm" in b)
    n_agree = sum(1 for b in blocks if "vlm" in b and reads(b)["rapid"] & reads(b)["vlm"])
    print(f"circle candidates {len(pts)} | boxes with two reads {n_two} | readers agree on a coordinate {n_agree}")

    stacked = pairs(blocks)
    gs, n_gs = grid_scale(blocks)
    print(f"scale from grid labels: {gs:.4f} units/pt from {n_gs} label pairs" if gs else "no grid-label scale available")

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

    p1 = build(agreed_only=False)  # every reading is a candidate; consensus decides, agreement only helps
    print(f"pass 1: stacked pairs {len(stacked)} | agreed value pairs with candidate points {len(p1)} in {len({q['group'] for q in p1})} groups")
    r1 = fit_points(p1, gs)
    if r1 is None:
        raise SystemExit("pass 1: not enough agreed pairs for a hypothesis")
    p, s = r1
    ok = sum(r < TOL for r, _, _ in s.values())
    print(f"pass 1 fit: {ok} agreeing groups | scale {np.hypot(p[0], p[1]):.4f} | rotation {np.degrees(np.arctan2(p[1], p[0])):.3f} deg")

    predict = lambda mid: apply(p, mid)[0]  # ground value expected at a label's position
    p2 = build(agreed_only=False, predict=predict)
    r2 = fit_points(p2, gs) if len({q['group'] for q in p2}) >= 2 else None
    if r2:
        p, s = r2
    used = [(r, pt, k) for r, pt, k in s.values() if r < TOL]
    res = [r for r, _, _ in used]
    a, b, tx, ty = p
    scale, rot = float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)))
    print(f"pass 2 fit: {len(used)}/{len(s)} pairs | scale {scale:.4f} units/pt (1in=100ft -> 1.3889) | rotation {rot:.3f} deg | rms {np.sqrt(np.mean(np.square(res))):.2f} max {max(res):.2f}")
    for r, pt, k in sorted(s.values(), key=lambda t: t[0]):
        print(f"  N {pt['N']:>10,.2f} E {pt['E']:>10,.2f}  residual {r:8.2f}  [{pt['label']}]{'' if r < TOL else '  <- rejected'}")
    # with dozens of circle candidates per callout, four pairs agreeing to 1 ft happens by chance;
    # a scan fit is only credible when its scale also matches the grid labels, an independent source
    scale_ok = gs is not None and abs(scale / gs - 1) < 0.03
    credible = len(used) >= 4 and scale_ok
    print("credible" if credible else f"NOT credible: {len(used)} agreeing pairs, scale {'matches' if scale_ok else 'does not match'} the grid labels ({gs:.3f})" if gs else f"NOT credible: no independent scale from grid labels to check {len(used)} agreeing pairs")

    tfw = next(iter((PDF.parent / "pkg").glob(PDF.stem + ".tfw")), None)
    if tfw:
        A, D, B, E, C, F = [float(v) for v in tfw.read_text().split()]
        import rasterio
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
        print(f"local grid -> CCS83 implied by Caltrans' package: scale {k2:.4f} (a local grid in feet should give ~1.00; "
              f"{'consistent' if abs(k2 - 1) < 0.02 else 'INCONSISTENT: our sheet scale differs from theirs by ' + format(abs(k2 - 1) * 100, '.1f') + '%'}), "
              f"rotation {np.degrees(np.arctan2(q[1], q[0])):.3f} deg")

    (OUT / "georef.json").write_text(json.dumps({
        "note": "x=a*sx-b*sy+tx, y=b*sx+a*sy+ty with sy=-pdf_y; units as printed on the sheet (local grid)",
        "params": [float(v) for v in p], "scale_ft_per_pt": scale, "rotation_deg": rot, "credible": credible,
        "control": [{"E": pt["E"], "N": pt["N"], "residual_ft": r, "used": r < TOL, "label": pt["label"]} for r, pt, k in s.values()]}, indent=1))
    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for r, pt, k in s.values():
        c = pt["cands"][k]
        cv2.circle(vis, (int(c[0] * z), int(-c[1] * z)), 22, (0, 0, 255) if r < TOL else (255, 0, 0), 4)
    cv2.imwrite(str(OUT / "scan_control.png"), cv2.resize(vis, None, fx=0.3, fy=0.3, interpolation=cv2.INTER_AREA))


if __name__ == "__main__":
    main()
