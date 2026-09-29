"""Loop17 leg G gate evidence: crops backing the census's negative findings (no candidate lever
actually completes a curve on the six gate sheets) -- one crop per example cited in the leg's report.
usage: python spike/legG17_crops.py   (presidio; writes spike/out_recon/l17G_*.png)
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
from leg4_crops import tile  # noqa: E402
import traverse as tv  # noqa: E402
from recon import OUT_RECON  # noqa: E402


def region_of(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def caption_tile(page, region, line, label, color=(220, 0, 0)):
    im = tile(page, region, line)
    im = cv2.copyMakeBorder(im, 26, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.putText(im, label[:80], (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    return im


def main():
    page = pymupdf.open(PDF)[0]
    edges = __import__("legE_crops").build_graph()
    by_src = {e["src"]: e for e in edges if e["kind"] == "arc"}

    # 1. C4: nearest lines (L7, L4, L6) sit 10.5-13.7 pt from its own ends but measure 13.9-179 deg off
    # true tangency (tol 1.0 deg) -- a genuinely isolated curve, not a snap-tolerance miss.
    c4 = by_src.get("C4")
    if c4 is not None:
        r = region_of(c4["pts"])
        im1 = caption_tile(page, r, c4["pts"].tolist(), "C4: nearest donor (L7, 10.5pt) measures 179deg off tangent -- not a real donor", color=(0, 90, 220))
        cv2.imwrite(str(OUT_RECON / "l17G_C4_isolated.png"), im1)
        print("wrote", OUT_RECON / "l17G_C4_isolated.png")

    # 2. The C13/C14/C19 cluster: three curves meeting at one drawn point (a real compound-curve PC/PT
    # node), each still unresolved -- loop17-G's new curve-to-curve chaining CAN cross this node (see
    # traverse.selftest), but finds no external record anchor anywhere in the connected cluster (no
    # line, CB, or radial with a resolved/derivable record direction reaches it from outside).
    cluster_pts = []
    for tag in ("C13", "C14", "C19"):
        e = by_src.get(tag)
        if e is not None:
            cluster_pts.extend(e["pts"].tolist())
    if cluster_pts:
        r = region_of(cluster_pts)
        im2 = tile(page, r, None)
        im2 = cv2.copyMakeBorder(im2, 26, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(im2, "C13/C14/C19: share one node, no external record anchor in the cluster", (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.imwrite(str(OUT_RECON / "l17G_C13_C14_C19_cluster.png"), im2)
        print("wrote", OUT_RECON / "l17G_C13_C14_C19_cluster.png")

    # 3. A standalone "no R" example (L=150.85'): a bare arc length with no radius anywhere nearby --
    # a reading/association gap (leg C/B territory), not a traverse.py logic blocker.
    l15085 = by_src.get("L=150.85'")
    if l15085 is not None:
        r = region_of(l15085["pts"])
        im3 = caption_tile(page, r, l15085["pts"].tolist(), "L=150.85': no R printed/associated anywhere nearby -- a reading gap, not a logic blocker")
        cv2.imwrite(str(OUT_RECON / "l17G_L150_85_noR.png"), im3)
        print("wrote", OUT_RECON / "l17G_L150_85_noR.png")


if __name__ == "__main__":
    main()
