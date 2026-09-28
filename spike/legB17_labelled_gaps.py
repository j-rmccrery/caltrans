"""Loop17 leg B target 2: the biggest no_traverse_edge_labelled stretches on ONE sheet, with the actual
nearby label text (not recon_attrib's own coarser "<face> vicinity" grouping) and whether that text
shows up in exceptions.json (queued/failed) or nowhere at all (never reached a check -- regex miss,
filtered, or consumed by a different label's match). One process per sheet, like every other spike
script: georef.OUT/PDF are bound to SHEET at import time, so this can't loop sheets in one process
(recon_attrib.py's own --report has the identical constraint, see its BASE_OUT comment).
usage: [SHEET=<pdf>] python spike/legB17_labelled_gaps.py
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import recon  # noqa: E402
from recon import covered_mask, PARALLEL_TOL_DEG  # noqa: E402
from recon_attrib import row_segments, LABEL_DIST_PT  # noqa: E402
from checks import BEAR, DIST  # noqa: E402
from georef import OUT  # noqa: E402

TOPN = 10


def main():
    sheet_name = sys.argv[1] if len(sys.argv) > 1 else (OUT.name if OUT.name != "out" else "presidio")
    result, internals = recon.run(sheet_name, return_internals=True)
    inv, buffer_ft = internals["inv"], internals["buffer_ft"]
    remaining = internals["remaining"]
    mid_f = internals["mid"][remaining]
    seg_len_f = internals["seg_len"][remaining]
    seg_az_f = internals["seg_az"][remaining]
    cov_f = internals["cov_mask_full"][remaining]
    dim_f = internals["dim_mask_full"][remaining]
    blocks = internals["blocks"]

    rows = json.loads((OUT / "traverse.json").read_text(encoding="utf-8"))
    rows = [row for chain in rows for row in chain["edges"] if row.get("pts") and len(row["pts"]) >= 2]
    rP, rQ, raz, ridx = row_segments(rows)
    uncov_mask = dim_f & ~cov_f
    any_match, best = covered_mask(mid_f, seg_az_f, rP, rQ, raz, buffer_ft, PARALLEL_TOL_DEG)

    lab_pts, lab_text = [], []
    for b in blocks:
        t = b["text"].strip()
        m = BEAR.match(t)
        if (m and not m[6]) or DIST.match(t):  # (R) radial bearings excluded, same as recon_attrib.label_positions
            lab_pts.append((b["cx"], b["cy"])); lab_text.append(t)
    lab_pts = np.array(lab_pts) if lab_pts else np.zeros((0, 2))
    mid_pt = inv(mid_f) if len(mid_f) else np.zeros((0, 2))

    exc = json.loads((OUT / "exceptions.json").read_text(encoding="utf-8")) if (OUT / "exceptions.json").exists() else []
    exc_by_text = {}
    for e in exc:
        exc_by_text.setdefault(e.get("text", "").strip(), []).append(e.get("issue", ""))

    found = {}  # label text -> ft
    for i in np.nonzero(uncov_mask)[0]:
        if any_match[i]:
            continue  # covered by SOME row's classify bucket, not no_traverse_edge
        if not len(lab_pts):
            continue
        d = np.hypot(*(lab_pts - mid_pt[i]).T)
        j = int(d.argmin())
        if d[j] <= LABEL_DIST_PT:
            L = float(seg_len_f[i])
            found[lab_text[j]] = found.get(lab_text[j], 0.0) + L

    top = sorted(found.items(), key=lambda kv: -kv[1])[:TOPN]
    print(f"=== {sheet_name}: top {len(top)} no_traverse_edge_labelled stretches ===")
    for txt, ft in top:
        issues = exc_by_text.get(txt, ["(not in exceptions.json at all)"])
        print(f"  {txt!r}: {ft:.1f} ft")
        for iss in issues:
            print(f"      -> {iss}")


if __name__ == "__main__":
    main()
