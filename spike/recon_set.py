"""Loop18 leg 1: the six-sheet SET measure -- recon.py's own headline is per sheet, and R-10741.2/.3,
R-10741.1/.2 and the Presidio tile (R-10434.1/.2/.3) draw overlapping ground: two adjoining sheets each
carry their own copy of the shared corridor near a matchline, drawn (and, where the record reaches it,
covered) independently on each sheet's own PDF. Summing every sheet's own recon_all_denom_ft/covered_ft
(the "OLD" headline, = loop17-final's own reported total) counts that shared ground TWICE. JR (2026-09-28):
"the headline counts each foot of GROUND once."

Method: recon.py's own run() now writes each sheet's own final elementary segments (ground ft, EPSG:2227
-- the same real-world CRS every sheet's own georef fit and parcels.geojson's lon/lat transform land in,
same fact matchline.py/recon_ceiling.py's own cross-sheet neighbour tests already rely on) to
<outdir>/recon_segments.json, each with its own covered/dimensioned flags. This script pools all six,
then collapses near-coincident, near-parallel copies across sheets with the SAME dedupe_segments()
recon.py uses within one sheet -- a shared matchline course, drawn on both abutting sheets, sits within a
few tenths of a ft of its own copy (loop12: proven same-line pairs agree <= 0.17 ft, median 0.19 ft);
DUP_TOL_FT_SET (1.0 ft) sits comfortably above that margin, same as recon.py's own within-sheet DUP_TOL_PT
converts to (~1.1-1.4 ft on these sheets' scales) -- and well short of a genuinely separate parallel
course a few ft off. A collapsed pair's covered/dimensioned flags are OR'd into the keeper (same
dedupe_segments() rule), so the SET's own covered/dimensioned ft can only rise, never silently drop, when
either sheet's own copy was covered/dimensioned.

Prerequisite: recon.py has already run for all six sheets (recon_segments.json exists in each own out
dir) -- the canonical bench with --parcels --traverse does this.

usage: python spike/recon_set.py                (after the six-sheet bench)
       python spike/recon_set.py --selftest
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from recon import dedupe_segments, azimuth_arr, PARALLEL_TOL_DEG, OUT_RECON  # noqa: E402

DUP_TOL_FT_SET = 1.0  # ft: see module docstring -- comfortably above the loop12 matchline-pair margin
                       # (<= 0.17 ft, median 0.19 ft), short of a genuinely separate parallel course.

SHEETS = {  # short key -> out dir stem (mirrors bench.SHEETS / recon_ceiling.SHORT2STEM)
    "presidio": "", "r10434_1": "r_10434_001_2020-09-16", "r10434_3": "r_10434_003_2020-09-16",
    "r10741_1": "r_10741_001_2017-02-10", "r10741_2": "r_10741_002_2017-02-10", "r10741_3": "r_10741_003_2017-02-10",
}
BASE_OUT = Path(__file__).parent / "out"


def load_sheet_segments(short_key, stem, no_inverse=False):
    """no_inverse=True (loop18 leg 2): recon_segments_no_inverse.json when bench.py's recon.py
    --no-inverse step wrote one for this sheet, else the plain file (a sheet inverse.py never touched
    has no by-inverse rows to exclude in the first place -- same numbers either way)."""
    base = BASE_OUT / stem if stem else BASE_OUT
    p = base / "recon_segments_no_inverse.json" if no_inverse and (base / "recon_segments_no_inverse.json").exists() else base / "recon_segments.json"
    if not p.exists():
        raise SystemExit(f"missing {p} -- run the bench (--parcels --traverse, which runs recon.py) for {short_key} first")
    d = json.loads(p.read_text(encoding="utf-8"))
    P = np.array(d["P"], float) if d["P"] else np.zeros((0, 2))
    Q = np.array(d["Q"], float) if d["Q"] else np.zeros((0, 2))
    seg_len = np.array(d["seg_len_ft"], float)
    cov = np.array(d["covered"], bool)
    dim = np.array(d["dimensioned"], bool)
    return P, Q, seg_len, cov, dim


def old_headline():
    """Sum of every sheet's own recon.json (the per-sheet numbers unchanged by this script) -- the OLD,
    double-counting-on-overlap headline (== loop17-final's own six-sheet total, modulo loop18 leg 1's
    own per-sheet fixes)."""
    drawn = dim_denom = covered = dim_covered = 0.0
    per_sheet = {}
    for short_key, stem in SHEETS.items():
        p = BASE_OUT / stem / "recon.json" if stem else BASE_OUT / "recon.json"
        r = json.loads(p.read_text(encoding="utf-8"))
        drawn += r["recon_all_denom_ft"]; covered += r["recon_all_covered_ft"]
        dim_denom += r["recon_dim_denom_ft"]; dim_covered += r["recon_dim_covered_ft"]
        per_sheet[short_key] = r
    return {"drawn_ft": round(drawn, 1), "covered_ft": round(covered, 1),
            "dim_denom_ft": round(dim_denom, 1), "dim_covered_ft": round(dim_covered, 1)}, per_sheet


def pool_all_sheets(no_inverse=False):
    P_all, Q_all, len_all, cov_all, dim_all, sheet_all = [], [], [], [], [], []
    for short_key, stem in SHEETS.items():
        P, Q, seg_len, cov, dim = load_sheet_segments(short_key, stem, no_inverse=no_inverse)
        if len(P) == 0:
            continue
        P_all.append(P); Q_all.append(Q); len_all.append(seg_len); cov_all.append(cov); dim_all.append(dim)
        sheet_all.append(np.full(len(P), short_key, dtype=object))
    P = np.vstack(P_all); Q = np.vstack(Q_all)
    seg_len = np.concatenate(len_all); cov = np.concatenate(cov_all); dim = np.concatenate(dim_all)
    sheet = np.concatenate(sheet_all)
    mid = (P + Q) / 2
    seg_az = azimuth_arr(Q - P)
    return P, Q, mid, seg_len, seg_az, cov, dim, sheet


def run():
    P, Q, mid, seg_len, seg_az, cov, dim, sheet = pool_all_sheets()
    old, per_sheet = old_headline()

    P2, Q2, mid2, seg_len2, seg_az2, (cov2, dim2) = dedupe_segments(
        P, Q, mid, seg_len, seg_az, DUP_TOL_FT_SET, PARALLEL_TOL_DEG, [cov, dim])
    # loop18 leg 1: overlap ft removed -- old per-sheet SUM minus the deduped set total, split by class
    # (drawn/dim/covered), so the gate can compare this script's own measured overlap against JR's two
    # independently-measured numbers (traverse-row overlap .2/.3 3,874 ft, .1/.2 1,645 ft; the DENOMINATOR
    # (face boundary) overlap this script actually measures is a different, larger quantity -- the whole
    # drawn/dimensioned boundary near a shared matchline, not just clean traverse rows -- so these are
    # cross-checks, not required to match exactly).
    new_drawn = float(seg_len2.sum())
    new_covered = float(seg_len2[cov2].sum())
    new_dim_denom = float(seg_len2[dim2].sum())
    new_dim_covered = float(seg_len2[cov2 & dim2].sum())

    # loop18 leg 2: the same set pooling, over recon_segments_no_inverse.json -- the headline with every
    # "by inverse ..." traverse row excluded (identical to new_set on a run where none was ever accepted).
    P0, Q0, mid0, seg_len0, seg_az0, cov0, dim0, sheet0 = pool_all_sheets(no_inverse=True)
    P02, Q02, mid02, seg_len02, seg_az02, (cov02, dim02) = dedupe_segments(
        P0, Q0, mid0, seg_len0, seg_az0, DUP_TOL_FT_SET, PARALLEL_TOL_DEG, [cov0, dim0])
    no_inv_drawn = float(seg_len02.sum())
    no_inv_covered = float(seg_len02[cov02].sum())
    no_inv_dim_denom = float(seg_len02[dim02].sum())
    no_inv_dim_covered = float(seg_len02[cov02 & dim02].sum())

    result = {
        "dup_tol_ft": DUP_TOL_FT_SET,
        "old_sum_of_per_sheet": old,
        "new_set": {
            "drawn_ft": round(new_drawn, 1), "covered_ft": round(new_covered, 1),
            "dim_denom_ft": round(new_dim_denom, 1), "dim_covered_ft": round(new_dim_covered, 1),
        },
        "new_set_no_inverse": {
            "drawn_ft": round(no_inv_drawn, 1), "covered_ft": round(no_inv_covered, 1),
            "dim_denom_ft": round(no_inv_dim_denom, 1), "dim_covered_ft": round(no_inv_dim_covered, 1),
            "recon_all_pct": round(100 * no_inv_covered / no_inv_drawn, 2) if no_inv_drawn else 0,
            "recon_dim_pct": round(100 * no_inv_dim_covered / no_inv_dim_denom, 2) if no_inv_dim_denom else 0,
        },
        "inverse_gain_ft": round(new_covered - no_inv_covered, 1),
        "overlap_ft_removed": {
            "drawn_ft": round(old["drawn_ft"] - new_drawn, 1),
            "covered_ft": round(old["covered_ft"] - new_covered, 1),
            "dim_denom_ft": round(old["dim_denom_ft"] - new_dim_denom, 1),
            "dim_covered_ft": round(old["dim_covered_ft"] - new_dim_covered, 1),
        },
        "recon_all_set_pct": round(100 * new_covered / new_drawn, 2) if new_drawn else 0,
        "recon_dim_set_pct": round(100 * new_dim_covered / new_dim_denom, 2) if new_dim_denom else 0,
        "recon_all_old_pct": round(100 * old["covered_ft"] / old["drawn_ft"], 2) if old["drawn_ft"] else 0,
        "recon_dim_old_pct": round(100 * old["dim_covered_ft"] / old["dim_denom_ft"], 2) if old["dim_denom_ft"] else 0,
        "per_sheet_recon_json": {k: {"recon_all_denom_ft": r["recon_all_denom_ft"], "recon_all_covered_ft": r["recon_all_covered_ft"],
                                      "removed_ft": r["removed_ft"]} for k, r in per_sheet.items()},
    }
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / "set_recon.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"OLD (sum of per-sheet): recon_all {old['covered_ft']:,.0f}/{old['drawn_ft']:,.0f} ft "
          f"({result['recon_all_old_pct']:.1f}%) | recon_dim {old['dim_covered_ft']:,.0f}/{old['dim_denom_ft']:,.0f} ft "
          f"({result['recon_dim_old_pct']:.1f}%)")
    print(f"NEW (set, deduped):     recon_all {new_covered:,.0f}/{new_drawn:,.0f} ft "
          f"({result['recon_all_set_pct']:.1f}%) | recon_dim {new_dim_covered:,.0f}/{new_dim_denom:,.0f} ft "
          f"({result['recon_dim_set_pct']:.1f}%)")
    print(f"NEW without inverse:    recon_all {no_inv_covered:,.0f}/{no_inv_drawn:,.0f} ft "
          f"({result['new_set_no_inverse']['recon_all_pct']:.1f}%) | recon_dim {no_inv_dim_covered:,.0f}/{no_inv_dim_denom:,.0f} ft "
          f"({result['new_set_no_inverse']['recon_dim_pct']:.1f}%) | inverse gain {result['inverse_gain_ft']:,.1f} ft")
    print(f"overlap removed: drawn {result['overlap_ft_removed']['drawn_ft']:,.0f} ft | "
          f"covered {result['overlap_ft_removed']['covered_ft']:,.0f} ft | "
          f"dim_denom {result['overlap_ft_removed']['dim_denom_ft']:,.0f} ft | "
          f"dim_covered {result['overlap_ft_removed']['dim_covered_ft']:,.0f} ft")
    return result


def selftest():
    """Two sheets whose own recon_segments.json draw the SAME 100 ft ground line (0.15 ft apart --
    under DUP_TOL_FT_SET), one of them covered: the pooled/deduped set must count it once, drawn AND
    covered (the covered flag survives the collapse, same dedupe_segments() rule recon.py's own
    within-sheet dedup relies on). A second, genuinely separate 100 ft line 5 ft off must stay two."""
    P = np.array([[0.0, 0.0], [0.0, 0.15], [500.0, 0.0]])
    Q = np.array([[100.0, 0.0], [100.0, 0.15], [600.0, 0.0]])
    mid = (P + Q) / 2
    seg_az = azimuth_arr(Q - P)
    seg_len = np.hypot(*(Q - P).T)
    cov = np.array([True, False, False])   # sheet A's own copy is covered, sheet B's copy of the SAME line is not
    dim = np.array([True, True, False])

    P2, Q2, mid2, seg_len2, seg_az2, (cov2, dim2) = dedupe_segments(P, Q, mid, seg_len, seg_az, DUP_TOL_FT_SET, PARALLEL_TOL_DEG, [cov, dim])
    assert len(seg_len2) == 2, f"the two near-coincident matchline copies must collapse to one, the separate line stays: got {len(seg_len2)}"
    total = float(seg_len2.sum())
    assert abs(total - 200.0) < 1.0, f"one shared 100 ft line + one separate 100 ft line = 200 ft total, got {total:.1f}"
    shared_idx = int(np.argmin(mid2[:, 0]))  # the collapsed shared-line keeper sits near x~50
    assert bool(cov2[shared_idx]), "the shared line's covered flag (True on sheet A's own copy) must survive the collapse"
    assert bool(dim2[shared_idx]), "the shared line's dimensioned flag must survive the collapse"

    # a genuinely separate line 5 ft off a shared one must never collapse into it
    P3 = np.array([[0.0, 0.0], [0.0, 5.0]])
    Q3 = np.array([[100.0, 0.0], [100.0, 5.0]])
    mid3 = (P3 + Q3) / 2
    seg_az3 = azimuth_arr(Q3 - P3)
    seg_len3 = np.hypot(*(Q3 - P3).T)
    _, _, _, seg_len3k, _, _ = dedupe_segments(P3, Q3, mid3, seg_len3, seg_az3, DUP_TOL_FT_SET, PARALLEL_TOL_DEG, [])
    assert abs(float(seg_len3k.sum()) - 200.0) < 1.0, "two lines 5 ft apart (past DUP_TOL_FT_SET) must stay separate, ~200 ft total"

    print("recon_set.selftest OK: two sheets' own near-coincident copies of a shared matchline course "
          "collapse to one, ft counted once, covered/dimensioned flags OR'd through; a genuinely "
          "separate line 5 ft off is never absorbed")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        run()
