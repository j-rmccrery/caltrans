"""Loop16 leg B: give every foot of dimensioned-but-not-covered boundary (recon.py's
recon_dim_denom_ft - recon_dim_covered_ft) exactly one cause, so the causes rank legs C/D.

Method: recon.py already classifies every drawn-boundary segment covered/dimensioned; this script
adds one more classification on top, for the dimensioned-but-not-covered segments only -- which
traverse.json row (of ANY kind/flags, not just recon.py's clean-line rec_edges) sits nearest within
recon.py's own buffer_ft/PARALLEL_TOL_DEG. That row's kind/flags pick the bucket, in priority order:
  1. curve               - nearest row kind == "arc" that is STILL flagged (loop16 leg E: a curve
                           whose record gives a chord direction -- CB or a tangent record line -- and
                           R/delta can be a clean rec_edge like a line now; such a curve's own covered
                           stretch is never "uncovered" to begin with, so classify_row's arc branch is
                           only ever reached here for a curve still missing that -- no record radius/
                           delta, or no record chord direction found).
  2. bearing_from_drawing- nearest row flagged "bearing from drawing" (record gave distance only).
  3. distance_from_drawing-nearest row flagged "distance from drawing" (record gave bearing only).
  4. other_flag          - nearest row carries some other flag (dropped-impossible-curve, no record,
                           chord-from-drawing-no-radius, ...).
  5. misfit              - nearest row unflagged but misfit_ft > 0.5 (record and drawing disagree
                           past recon.py's own reconstructed-edge cutoff).
  6. no_traverse_edge    - no traverse row of any kind sits within buffer+direction tolerance: the
                           record never reached this stretch at all. Split unlabelled vs "labelled but
                           not walked" (a bearing/distance-shaped text block sits within LABEL_DIST_PT
                           of the segment on the sheet, but never became a traverse edge).
  7. residual_contamination - reclassified OUT of no_traverse_edge by hand, with a crop as evidence,
                           for segments recon.py's own leader/wedge removal did not catch (see
                           PRESIDIO_CONTAM_PT below).
A segment can only be dimensioned-but-uncovered because SOME clean row (line or, since loop16 leg E,
arc) failed to match it within buffer+tolerance -- so if the nearest ANY-kind row found here were
itself a clean (flags==[], misfit<=0.5) row within that same buffer+tolerance, recon.py's own
cov_mask_full would already have marked the segment covered (same covered_mask() call, same
buffer/tol/per-segment decomposition -- row_segments() below splits an arc row into its own local
sub-segments exactly as recon.rec_segments() does -- and rec_edges is a strict subset of the all-rows
set searched here). That contradiction is asserted (bucket "anomaly": expected empty) rather than
assumed.

usage: [SHEET=<pdf>] python spike/recon_attrib.py      (per sheet, after recon.py's own prerequisites
                                                          -- parcels.py, traverse.py)
       python spike/recon_attrib.py --report             (aggregate every out/<sheet>/attrib.json
                                                          already on disk into out_recon/attribution.md)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, DEFAULT  # noqa: E402
import recon  # noqa: E402
from recon import azimuth_arr, covered_mask, face_pieces, PARALLEL_TOL_DEG, DENSIFY_FT, OUT_RECON  # noqa: E402
from checks import BEAR, DIST  # noqa: E402

LABEL_DIST_PT = 40.0   # pt: how close a bearing/distance-shaped text block must sit to an uncovered
                        # segment to call it "labelled but not walked" rather than "unlabelled"
FACE_ONE_SHORT_PCT = 90.0  # a named face >= this %% covered, with exactly one uncovered ring piece,
                            # counts as "one edge short" in the parcel-blocker table

# loop16 leg B: crop evidence (out_recon/_crop_dk046825_063269.png, cropped from this script's own
# attrib_presidio.png) shows two V-shaped fans of grey (no_traverse_edge) strokes converging on the
# DK-046825-X1-X1 and 063269-X1-X1 callout boxes near the CRISSY FIELD AVE corridor -- the same wedge
# leaders recon.py's own leader_wedge removal targets (module docstring, PARCEL_DEED_RE), but which
# survive here: real leaders radiate FROM a label toward the drawing, a real R/W edge runs parallel to
# the corridor for its whole length (every other grey/red stroke in the crop does) -- these three do
# neither, they converge to a point at the label. Page-pt (cx, cy) read directly off read_shx.json
# (georef.READS for Presidio): "DK-046825-X1-X1" id251, "063269-X1-X1" id247, "63269" bubble id245 --
# the third cluster the task brief names. A generous point-radius (not a line search) undercounts the
# far end of each wedge leg (measured: only 106-263 ft nets within 120-160 pt of the label itself,
# against 354-664 ft of leg recon.py's own docstring measures end to end) -- fine for ranking (this
# bucket is a few hundred ft either way, nowhere near top 3), not exact.
# loop18 leg 1: moved to recon.py (its own "wedge_residual" removal class, at the source) -- kept as
# aliases here so this module's own residual_contamination bucket (below) and recon_ceiling.py's
# import of these two names both keep working unchanged.
PRESIDIO_CONTAM_PT = recon.PRESIDIO_CONTAM_PT
PRESIDIO_CONTAM_TOL_PT = recon.PRESIDIO_CONTAM_TOL_PT

SHEET_NAMES = ["presidio", "r10434_1", "r10434_3", "r10741_1", "r10741_2", "r10741_3"]
BASE_OUT = Path(__file__).parent / "out"  # spike/out/ -- OUT itself is fixed to THIS process's own SHEET
                                            # env at import time, so --report (every sheet) must not use it


def classify_row(row):
    """Priority-ordered bucket for the nearest traverse row matched to an uncovered segment."""
    if row["kind"] == "arc":
        return "curve"
    flags = row["flags"]
    if "bearing from drawing" in flags:
        return "bearing_from_drawing"
    if "distance from drawing" in flags:
        return "distance_from_drawing"
    if flags:
        return "other_flag"
    if row["misfit_ft"] > 0.5:
        return "misfit"
    return "anomaly"  # see module docstring: expected to never fire


def load_all_rows():
    trav = json.loads((OUT / "traverse.json").read_text(encoding="utf-8"))
    return [row for chain in trav for row in chain["edges"] if row.get("pts") and len(row["pts"]) >= 2]


def row_segments(rows):
    """rows -> elementary (P, Q, az, row_idx) across every row's own consecutive pts pairs, any
    kind/flags -- the same shape recon.covered_mask() expects, built from ALL traverse rows rather
    than just its own clean-line rec_edges subset."""
    P, Q, ridx = [], [], []
    for i, row in enumerate(rows):
        pts = np.array(row["pts"], float)
        if len(pts) < 2:
            continue
        P.append(pts[:-1]); Q.append(pts[1:]); ridx += [i] * (len(pts) - 1)
    if not P:
        z = np.zeros((0, 2))
        return z, z, np.zeros(0), np.zeros(0, int)
    P, Q = np.vstack(P), np.vstack(Q)
    return P, Q, azimuth_arr(Q - P), np.array(ridx, int)


def label_positions(blocks):
    """Every bearing/distance-shaped text block, for the "does an uncovered segment sit near a printed
    record value" test -- EXCEPT a radial "(R)" bearing (loop17 leg B): checks.py's own summary already
    calls these out as "not checked against a line" (they name a curve's radius direction to its centre,
    not a boundary course), so a boundary segment sitting near one has no record edge to have missed --
    counting it as "labelled" blamed an association miss that was never possible on some of the biggest
    no_traverse_edge_labelled stretches (R-10434.3: 6 of its top 10, 796 of 1,605 ft, all radial
    bearings; the segment is genuinely unlabelled, reclassified to no_traverse_edge_unlabelled)."""
    pts = [(b["cx"], b["cy"]) for b in blocks
           if (m := BEAR.match(b["text"].strip())) and not m[6] or DIST.match(b["text"].strip())]
    return np.array(pts) if pts else np.zeros((0, 2))


def run_sheet(sheet_name):
    result, internals = recon.run(sheet_name, return_internals=True)
    inv, buffer_ft = internals["inv"], internals["buffer_ft"]
    remaining = internals["remaining"]
    mid_f = internals["mid"][remaining]
    seg_len_f = internals["seg_len"][remaining]
    seg_az_f = internals["seg_az"][remaining]
    cov_f = internals["cov_mask_full"][remaining]
    dim_f = internals["dim_mask_full"][remaining]
    rec_edges, rec_P, rec_Q, rec_az, rec_parent = (internals["rec_edges"], internals["rec_P"], internals["rec_Q"],
                                                    internals["rec_az"], internals["rec_parent"])
    kept_faces, blocks = internals["kept_faces"], internals["blocks"]

    denom_ft = float(seg_len_f[dim_f].sum())
    covered_dim_ft = float(seg_len_f[dim_f & cov_f].sum())
    assert abs(denom_ft - result["recon_dim_denom_ft"]) < 1.0, f"{sheet_name}: dim denom drifted from recon.json"
    assert abs(covered_dim_ft - result["recon_dim_covered_ft"]) < 1.0, f"{sheet_name}: dim covered drifted from recon.json"

    rows = load_all_rows()
    rP, rQ, raz, ridx = row_segments(rows)
    uncov_mask = dim_f & ~cov_f
    any_match, best = covered_mask(mid_f, seg_az_f, rP, rQ, raz, buffer_ft, PARALLEL_TOL_DEG)
    label_xy = label_positions(blocks)
    mid_pt = inv(mid_f) if len(mid_f) else np.zeros((0, 2))

    contam_pts = np.array(PRESIDIO_CONTAM_PT) if sheet_name == "presidio" else np.zeros((0, 2))
    named_faces = [(f["parcel"], f["poly"].exterior) for f in kept_faces if f["named"]]

    def nearest_face(pt):
        if not named_faces:
            return "?"
        p = Point(pt)
        return min(named_faces, key=lambda nf: nf[1].distance(p))[0]

    buckets, flags_seen, misfits = {}, set(), []
    examples = {}  # bucket -> {edge/face label: ft}
    idx_bucket = np.full(len(mid_f), "", dtype=object)

    for i in np.nonzero(uncov_mask)[0]:
        L = float(seg_len_f[i])
        if any_match[i]:
            row = rows[ridx[best[i]]]
            b = classify_row(row)
            if b == "other_flag":
                flags_seen.update(row["flags"])
            if b == "misfit":
                misfits.append(row["misfit_ft"])
            row_name = row["edge"]
        else:
            if len(contam_pts) and np.hypot(*(contam_pts - mid_pt[i]).T).min() <= PRESIDIO_CONTAM_TOL_PT:
                b = "residual_contamination"
            elif len(label_xy) and np.hypot(*(label_xy - mid_pt[i]).T).min() <= LABEL_DIST_PT:
                b = "no_traverse_edge_labelled"
            else:
                b = "no_traverse_edge_unlabelled"
            row_name = f"{nearest_face(mid_f[i])} vicinity"
        idx_bucket[i] = b
        buckets[b] = buckets.get(b, 0.0) + L
        examples.setdefault(b, {})
        examples[b][row_name] = examples[b].get(row_name, 0.0) + L

    lost_ft = denom_ft - covered_dim_ft
    total_bucketed = sum(buckets.values())
    assert abs(total_bucketed - lost_ft) < 1.0, (
        f"{sheet_name}: bucket sum {total_bucketed:.1f} ft != recon_dim_denom - recon_dim_covered {lost_ft:.1f} ft")
    if buckets.get("anomaly"):
        print(f"WARNING {sheet_name}: {buckets['anomaly']:.1f} ft landed in 'anomaly' -- a clean-line "
              f"nearest row matched an uncovered segment; should never happen, see module docstring")

    # --- per-face blocker table (qualitative; not summed into the ft total above -- recon.py's own
    # per-face walk, reused via face_pieces(), does not apply the frame/tables/matchline/leader_wedge/
    # edge_column contamination removal the segment-level total above does; see attribution.md notes).
    face_blockers = []
    for f, rf in zip(kept_faces, result["faces"]):
        if not f["named"] or rf["touches_frame"]:
            continue
        pieces, pct, total_len = face_pieces(f["ring"], rec_P, rec_Q, rec_az, rec_parent, buffer_ft, PARALLEL_TOL_DEG, DENSIFY_FT)
        uncovered_pieces = [(p, q) for k, p, q in pieces if k is None]
        piece_buckets = {}
        for p, q in uncovered_pieces:
            L = float(np.hypot(*(np.array(q) - np.array(p))))
            pmid = np.array([(np.array(p) + np.array(q)) / 2])
            paz = azimuth_arr(np.array(q) - np.array(p)) * np.ones(1)
            am, bst = covered_mask(pmid, paz, rP, rQ, raz, buffer_ft, PARALLEL_TOL_DEG)
            b = classify_row(rows[ridx[bst[0]]]) if am[0] else "no_traverse_edge"
            piece_buckets[b] = piece_buckets.get(b, 0.0) + L
        face_blockers.append({
            "parcel": rf["parcel"], "pct_covered": rf["pct_covered"], "counts": rf["counts"],
            "n_uncovered_pieces": len(uncovered_pieces), "blockers_ft": {k: round(v, 1) for k, v in piece_buckets.items()},
            "one_edge_short": bool((not rf["counts"]) and rf["pct_covered"] is not None
                                    and rf["pct_covered"] >= FACE_ONE_SHORT_PCT and len(uncovered_pieces) == 1),
        })

    out = {
        "sheet": sheet_name, "recon_dim_denom_ft": round(denom_ft, 1), "recon_dim_covered_ft": round(covered_dim_ft, 1),
        "lost_ft": round(lost_ft, 1), "buckets_ft": {k: round(v, 1) for k, v in buckets.items()},
        "flags_seen_other_flag": sorted(flags_seen), "misfit_ft_values": sorted(round(m, 2) for m in misfits),
        "examples": {k: sorted(v.items(), key=lambda kv: -kv[1])[:4] for k, v in examples.items()},
        "face_blockers": face_blockers,
    }
    (OUT / "attrib.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    make_attrib_figure(sheet_name, internals, uncov_mask, idx_bucket)
    print(f"{sheet_name}: lost {lost_ft:.1f} ft -> " + ", ".join(f"{k} {v:.0f}" for k, v in sorted(buckets.items(), key=lambda kv: -kv[1])))
    return out


BUCKET_COLORS = {
    "curve": "#1f77b4", "bearing_from_drawing": "#ff7f0e", "distance_from_drawing": "#e377c2",
    "other_flag": "#9467bd", "misfit": "#8c564b", "no_traverse_edge_labelled": "#d62728",
    "no_traverse_edge_unlabelled": "#7f7f7f", "residual_contamination": "#17becf", "anomaly": "#000000",
}


def make_attrib_figure(sheet_name, internals, uncov_mask, idx_bucket):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D

    page, inv, remaining = internals["page"], internals["inv"], internals["remaining"]
    Pf, Qf = internals["P"][remaining], internals["Q"][remaining]  # same "remaining" set recon.py's own figures use

    W, H = page.rect.width, page.rect.height
    px = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(px.samples, dtype=np.uint8).reshape(px.height, px.width)

    dpi = 150
    fig, ax = plt.subplots(figsize=(2000 / dpi, 2000 / dpi * H / W), dpi=dpi)
    ax.imshow(img, cmap="gray", extent=(0, W, H, 0), alpha=0.35)

    for b, color in BUCKET_COLORS.items():
        sel = uncov_mask & (idx_bucket == b)
        if not sel.any():
            continue
        a, q = inv(Pf[sel]), inv(Qf[sel])
        segs = list(zip(a.tolist(), q.tolist()))
        ax.add_collection(LineCollection(segs, colors=color, linewidths=1.6, label=b))
    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.set_aspect("equal")
    ax.set_title(f"{sheet_name}: dimensioned-but-uncovered boundary, by cause")
    handles = [Line2D([0], [0], color=c, lw=2, label=b) for b, c in BUCKET_COLORS.items()]
    ax.legend(handles=handles, loc="lower right", fontsize=6)
    ax.axis("off")
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT_RECON / f"attrib_{sheet_name}.png")
    plt.close(fig)


def report():
    rows = []
    for name in SHEET_NAMES:
        d = BASE_OUT / recon_out_dirname(name)
        p = d / "attrib.json"
        if not p.exists():
            print(f"missing {p}, run: SHEET=... python spike/recon_attrib.py for {name}")
            continue
        rows.append(json.loads(p.read_text(encoding="utf-8")))

    all_buckets = {}
    for r in rows:
        for k, v in r["buckets_ft"].items():
            all_buckets[k] = all_buckets.get(k, 0.0) + v
    total = sum(all_buckets.values())
    ranked = sorted(all_buckets.items(), key=lambda kv: -kv[1])

    lines = ["# recon attribution: every dimensioned-uncovered foot, one cause\n"]
    lines.append(f"total lost across 6 sheets: {total:,.1f} ft\n")
    lines.append("## per-sheet bucket table (ft)\n")
    cols = [k for k, _ in ranked]
    lines.append("| sheet | lost_ft | " + " | ".join(cols) + " |")
    lines.append("|---|---|" + "---|" * len(cols))
    for r in rows:
        cells = [f"{r['buckets_ft'].get(c, 0.0):.0f}" for c in cols]
        lines.append(f"| {r['sheet']} | {r['lost_ft']:.0f} | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## all-sheets ranking\n")
    lines.append("| bucket | ft | % of total lost |")
    lines.append("|---|---|---|")
    for k, v in ranked:
        lines.append(f"| {k} | {v:,.1f} | {100 * v / total:.1f}% |")
    for k in ("other_flag", "anomaly"):
        if k not in all_buckets:
            lines.append(f"| {k} | 0.0 | 0.0% (never the nearest row) |")
    lines.append("")
    lines.append("no_traverse_edge splits unlabelled/labelled and residual_contamination (7) is carved "
                  "out of it by hand -- together they are one cause (\"the record never reached this "
                  f"line\"): {100 * (all_buckets.get('no_traverse_edge_unlabelled', 0) + all_buckets.get('no_traverse_edge_labelled', 0) + all_buckets.get('residual_contamination', 0)) / total:.1f}% "
                  "combined, the largest single cause by a wide margin over any one flag/misfit/curve bucket.\n")

    lines.append("## top 3 buckets: notes and examples\n")
    for k, v in ranked[:3]:
        lines.append(f"### {k} ({v:,.0f} ft, {100 * v / total:.1f}%)")
        exs = []
        for r in rows:
            for name, ft in r["examples"].get(k, []):
                exs.append((r["sheet"], name, ft))
        exs.sort(key=lambda t: -t[2])
        for sheet, name, ft in exs[:2]:
            lines.append(f"- {name} ({sheet}): {ft:.1f} ft")
        if k == "other_flag":
            flags = sorted({f for r in rows for f in r["flags_seen_other_flag"]})
            lines.append(f"- flags seen: {flags}")
        if k == "misfit":
            m = sorted(mm for r in rows for mm in r["misfit_ft_values"])
            if m:
                lines.append(f"- misfit_ft distribution: n={len(m)} min={m[0]:.2f} median={m[len(m)//2]:.2f} max={m[-1]:.2f}")
        if k == "curve":
            lines.append("- loop16 leg E: a curve can be a clean rec_edge now (CB, or a tangent record "
                          "line, gives its chord direction; see traverse.py's complete_curve_chords). "
                          "What remains here is a curve still missing a record radius/delta, or one "
                          "whose only candidate record tangents disagree (refused, not guessed).")
        if k.startswith("no_traverse_edge"):
            lines.append("- the record simply never reached this stretch -- no traverse.json row of any "
                          "kind (line, curve, flagged or not) sits within recon.py's own buffer+direction "
                          "tolerance. \"labelled\" means a bearing/distance-shaped text block sits within "
                          f"{LABEL_DIST_PT:.0f} pt on the sheet but never became an edge (an association miss, "
                          "not a missing record); \"unlabelled\" means no such text sits nearby either.")
        lines.append("")

    blocked = [(r["sheet"], f) for r in rows for f in r["face_blockers"] if not f["counts"]]
    n_one_short = sum(1 for _, f in blocked if f["one_edge_short"])
    best_sheet, best = max(blocked, key=lambda sf: sf[1]["pct_covered"] or -1, default=(None, None))
    lines.append(f"## parcel blockers ({len(blocked)} named faces short of closing; not summed into the ft total above)\n")
    lines.append(f"{n_one_short} faces are \"one edge short\" (>= {FACE_ONE_SHORT_PCT:.0f}% covered, exactly "
                  "one uncovered ring piece). Closest to closing: "
                  + (f"{best['parcel']} ({best_sheet}) at {best['pct_covered']:.1f}% covered, "
                     f"{best['n_uncovered_pieces']} uncovered piece(s)" if best else "none") + ".\n")
    lines.append("| sheet | parcel | pct_covered | counts | n_uncovered_pieces | one_edge_short | blockers_ft |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in rows:
        for f in r["face_blockers"]:
            if f["counts"]:
                continue
            lines.append(f"| {r['sheet']} | {f['parcel']} | {f['pct_covered']} | {f['counts']} | "
                          f"{f['n_uncovered_pieces']} | {f['one_edge_short']} | {f['blockers_ft']} |")
    lines.append("")

    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / "attribution.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_RECON / 'attribution.md'}")


def recon_out_dirname(sheet_name):
    from bench import SHEETS
    pdf = SHEETS[sheet_name]
    return pdf.stem if pdf is not None else ""


def main():
    if "--report" in sys.argv:
        report()
        return
    sheet_name = "presidio" if PDF == DEFAULT else PDF.stem
    run_sheet(sheet_name)


if __name__ == "__main__":
    main()
