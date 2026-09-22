"""Georeference a scanned sheet from its own coordinate callouts.

Same idea as the vector path, on pixels: coordinate pairs come from scan_read.py; the labelled point
is one of the small circles (line vertices) near the callout; the consensus solver picks which.
Ground units are whatever the sheet prints (R-65.2: a local grid in feet).
Verification: the shape of our fit against Caltrans' georeferenced package (a similarity must relate
the two, since the local grid and CCS83 differ by one), reported as residuals.
usage: SHEET=<scan.pdf> python spike/scan_georef.py
"""
import itertools
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, apply, callouts, similarity  # noqa: E402
from solve import TOL, refit, score  # noqa: E402

DPI = 300
REACH = 90  # pt: how far a leader may run from the callout to its point


def circles(img):
    """Small circles (line vertices, monument symbols) as sheet points (pt, y up)."""
    z = DPI / 72
    blur = cv2.medianBlur(img, 3)
    c = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=10, param1=120, param2=18, minRadius=5, maxRadius=13)
    c = np.zeros((0, 3)) if c is None else c[0]
    return np.c_[c[:, 0] / z, -c[:, 1] / z], c


def main():
    page = pymupdf.open(PDF)[0]
    z = DPI / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    pts, raw = circles(img)
    print(f"circle candidates on the sheet: {len(pts)}")

    blocks = json.loads((OUT / "read_rapid.json").read_text(encoding="utf-8"))
    cos = callouts(blocks, [])
    points = []
    for co in cos:
        mid = np.array([(co["nb"]["cx"] + co["eb"]["cx"]) / 2, -(co["nb"]["cy"] + co["eb"]["cy"]) / 2])
        near = pts[np.hypot(*(pts - mid).T) < REACH]
        if len(near):
            points.append({"E": co["E"], "N": co["N"], "cands": near, "note": False})
    print(f"callout pairs {len(cos)} | with circle candidates {len(points)} | candidates per pair {[len(p['cands']) for p in points]}")
    if len(points) < 3:
        raise SystemExit("too few callouts with candidate points")

    hs = []
    for i, j in itertools.combinations(range(len(points)), 2):
        for ci, cj in itertools.product(points[i]["cands"], points[j]["cands"]):
            if np.hypot(*(ci - cj)) > 40:
                hs.append(similarity(np.array([ci, cj]), np.array([[points[i]["E"], points[i]["N"]], [points[j]["E"], points[j]["N"]]])))
    best = None
    for h in hs:
        pr, _ = score(h, points, [])
        key = (sum(r < TOL for r, _ in pr), -sum(min(r, TOL) for r, _ in pr))
        if best is None or key > best[0]:
            best = (key, h)
    p = best[1]
    for _ in range(3):
        p, used, _, pr, _ = refit(p, points, [])
    a, b, tx, ty = p
    scale, rot = float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)))
    res = [pr[i][0] for i in used]
    print(f"fit on {len(used)}/{len(points)} callouts | scale {scale:.4f} units/pt (1in=100ft -> 1.3889) | rotation {rot:.3f} deg | rms {np.sqrt(np.mean(np.square(res))):.2f} max {max(res):.2f}")
    for i, pt in enumerate(points):
        print(f"  N {pt['N']:>10,.2f} E {pt['E']:>10,.2f}  residual {pr[i][0]:8.2f}{'' if i in used else '  <- rejected'}")
    credible = len(used) >= 4
    print("credible" if credible else "NOT credible: fewer than 4 agreeing callouts")

    tfw = next(iter((PDF.parent / "pkg").glob(PDF.stem + ".tfw")), None)
    if tfw:
        A, D, B, E, C, F = [float(v) for v in tfw.read_text().split()]
        import rasterio
        with rasterio.open(tfw.with_suffix(".tif")) as r:
            k = r.width / page.rect.width
        W, H = page.rect.width, page.rect.height
        src, dst = [], []
        for px, py in itertools.product(np.linspace(0.1, 0.9, 5) * W, np.linspace(0.1, 0.9, 4) * H):
            src.append(apply(p, [px, -py])[0])
            col, row = px * k - 0.5, py * k - 0.5
            dst.append([A * col + B * row + C, D * col + E * row + F])
        src, dst = np.array(src), np.array(dst)
        q = similarity(src, dst)
        d = np.hypot(*(apply(q, src) - dst).T)
        print(f"local grid -> CCS83 (from Caltrans package): scale {np.hypot(q[0], q[1]):.5f}, rotation {np.degrees(np.arctan2(q[1], q[0])):.3f} deg; "
              f"shape residual rms {np.sqrt(np.mean(d ** 2)):.2f} ft over 20 sheet points (0 = our fit and theirs agree up to one similarity)")

    (OUT / "georef.json").write_text(json.dumps({
        "note": "x=a*sx-b*sy+tx, y=b*sx+a*sy+ty with sy=-pdf_y; units as printed on the sheet (local grid)",
        "params": [float(v) for v in p], "scale_ft_per_pt": scale, "rotation_deg": rot, "credible": credible,
        "control": [{"E": pt["E"], "N": pt["N"], "residual_ft": pr[i][0], "used": i in used} for i, pt in enumerate(points)]}, indent=1))

    vis = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for x, y, r in raw:
        cv2.circle(vis, (int(x), int(y)), int(r), (0, 200, 0), 2)
    for i, pt in enumerate(points):
        c = pt["cands"][pr[i][1]]
        cv2.circle(vis, (int(c[0] * z), int(-c[1] * z)), 22, (0, 0, 255) if i in used else (255, 0, 0), 4)
    cv2.imwrite(str(OUT / "scan_control.png"), cv2.resize(vis, None, fx=0.3, fy=0.3, interpolation=cv2.INTER_AREA))


if __name__ == "__main__":
    main()
