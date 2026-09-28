"""Matchline check: does each sheet pair put the same record lines in the same ground place.

Standalone measurement script, reading ONLY the frozen snapshot listed in SNAP below (each sheet's
already-computed sheet_linework.geojson, georef.json, and its text-read cache). Does not import
spike/georef.py or spike/overlay.py: those key off spike/out, which another agent is rewriting live.

Method
------
sheet_linework.geojson per sheet is already the sheet's own georef fit + HTDP epoch shift, in
lon/lat (NAD83 2011). Both sheets in a pair get the SAME epoch shift (spike/lidar/htdp.json is one
constant for both tiles), so it cancels in a sheet-vs-sheet comparison; using the already-shifted
ground layer instead of un-shifted CCS83 grid ft changes nothing about the offsets measured here.

1. Two sheets "abut" when their heavy-linework bounding boxes actually overlap in UTM (checked, not
   assumed from sheet numbering -- see ABUTS below).
2. Heavy (R/W + parcel weight) segments per sheet are merged into maximal chains (shared endpoints),
   then clipped to the overlap rectangle.
3. A piece in sheet A is a CANDIDATE match for a piece in sheet B when their directions agree
   (<12 deg) and one's midpoint lies close to the other's infinite line (<8 m) with real projected
   overlap (>5 m). This is not proof of same-line identity by itself: a corner where two different
   courses meet passes it too (same point, different direction beyond it), and so does a genuinely
   different line that happens to share a bearing. A candidate is only PROVEN, and only then counted
   in the offset stats, when bearing agrees to <=1' and the lines coincide (perp <=0.15 m), or the
   pieces' drawn endpoints are essentially touching (<=0.1 m) with perp <=0.15 m. Dropped candidates
   are listed with why.
4. Perpendicular offset: median/max point-to-line distance from A's piece to B's piece over their
   shared projected range, PROVEN pairs only.
5. Corner-tie gap: original (un-clipped) chain endpoints -- real drawn corners/PCs, not clip
   artifacts -- that fall inside the overlap rectangle on both sheets are paired by nearest neighbour
   (<5 m) and their 2D separation reported. This is NOT bearing-verified (no direction check on an
   endpoint), so it is weaker evidence than the proven line pairs or the label-offset measure below;
   kept as a secondary, clearly-labelled heuristic.

Bearing/distance label agreement: each sheet's own text-read cache (SHX/glyph/OCR, whichever the
pipeline already picked -- see READS_FOR) has "N dd^mm'ss\"[EW] [distance']" printed either as one
merged token (SHX, most rapid-OCR reads) or fragmented (glyph, rare here). Regex-pull those tokens,
place them on the ground via each sheet's own georef.json fit, and pair labels across the matchline
whose ground positions land within 6 m of each other. Compare the printed strings.

Outputs: spike/out_ground/matchline.md, spike/out_ground/matchline_<A>_<B>.png per pair.
"""
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Point, box as shpbox
from shapely.ops import linemerge, unary_union

SNAP = Path(__file__).parent / "out"  # live pipeline output (demo step); the loop12 frozen scratchpad
            # snapshot was only needed while another agent was rewriting spike/out concurrently.
OUTDIR = Path(__file__).parent / "out_ground"
OUTDIR.mkdir(exist_ok=True)

M_PER_FT = 0.3048006096012192  # US survey foot
FT_PER_M = 1 / M_PER_FT

SHEETS = {
    "R-10434.1": SNAP / "r_10434_001_2020-09-16",
    "R-10434.2": SNAP,
    "R-10434.3": SNAP / "r_10434_003_2020-09-16",
    "R-10741.1": SNAP / "r_10741_001_2017-02-10",
    "R-10741.2": SNAP / "r_10741_002_2017-02-10",
    "R-10741.3": SNAP / "r_10741_003_2017-02-10",
}
CANDIDATE_PAIRS = [("R-10434.1", "R-10434.2"), ("R-10434.2", "R-10434.3"),
                   ("R-10741.1", "R-10741.2"), ("R-10741.2", "R-10741.3"),
                   ("R-10434.1", "R-10434.3"), ("R-10741.1", "R-10741.3")]  # checked, not assumed

to_utm = Transformer.from_crs("EPSG:6318", "EPSG:6339", always_xy=True)  # sheet_linework.geojson lon/lat -> UTM10N m
ccs83_to_utm = Transformer.from_crs("EPSG:2227", "EPSG:6339", always_xy=True)  # sheet's own CCS83 Z3 ftUS fit -> UTM10N m


def load_lines(d, weight):
    fc = json.loads((d / "sheet_linework.geojson").read_text())
    out = []
    for f in fc["features"]:
        if f["properties"]["weight"] != weight:
            continue
        c = np.array(f["geometry"]["coordinates"])
        x, y = to_utm.transform(c[:, 0], c[:, 1])
        if len(x) >= 2 and np.hypot(x[-1] - x[0], y[-1] - y[0]) > 1e-6:
            out.append(np.c_[x, y])
    return out


def bbox(polys):
    a = np.vstack(polys)
    return a[:, 0].min(), a[:, 0].max(), a[:, 1].min(), a[:, 1].max()


def overlap_rect(bA, bB, pad=2.0):
    xlo = max(bA[0], bB[0]) - pad; xhi = min(bA[1], bB[1]) + pad
    ylo = max(bA[2], bB[2]) - pad; yhi = min(bA[3], bB[3]) + pad
    return xlo, xhi, ylo, yhi


def merged_chains(polys):
    lines = [LineString(p) for p in polys]
    merged = linemerge(unary_union(lines))
    return [merged] if merged.geom_type == "LineString" else list(merged.geoms)


def clip_pieces(chains, rect, min_len=3.0):
    box = shpbox(rect[0], rect[2], rect[1], rect[3])
    pieces = []
    for ln in chains:
        inter = ln.intersection(box)
        geoms = [inter] if inter.geom_type == "LineString" else \
            [g for g in getattr(inter, "geoms", []) if g.geom_type == "LineString"]
        pieces += [g for g in geoms if g.length > min_len]
    return pieces


def true_endpoints(chains, rect, tol=0.02):
    """Chain endpoints that are real drawn ends (not synthetic clip-box crossings), inside rect."""
    xlo, xhi, ylo, yhi = rect
    pts = []
    for ln in chains:
        for p in (ln.coords[0], ln.coords[-1]):
            if xlo < p[0] < xhi and ylo < p[1] < yhi:
                pts.append(np.array(p))
    return pts


def piece_dir(g):
    p0, p1 = np.array(g.coords[0]), np.array(g.coords[-1])
    d = p1 - p0
    n = np.hypot(*d)
    return (d / n) if n > 1e-9 else np.array([1.0, 0.0])


def match_pieces(A, B, angle_tol_deg=12, perp_tol=8.0, min_overlap=5.0):
    matches = []
    for a in A:
        da = piece_dir(a)
        a0, a1 = np.array(a.coords[0]), np.array(a.coords[-1])
        best = None
        for b in B:
            db = piece_dir(b)
            ang = np.degrees(np.arccos(np.clip(abs(np.dot(da, db)), -1, 1)))
            if ang > angle_tol_deg:
                continue
            b0, b1 = np.array(b.coords[0]), np.array(b.coords[-1])
            mid_a = (a0 + a1) / 2
            v = mid_a - b0
            perp = abs(v[0] * db[1] - v[1] * db[0])
            proj = lambda p: float(np.dot(p - b0, db))
            ra = sorted([proj(a0), proj(a1)]); rb = sorted([proj(b0), proj(b1)])
            ov = min(ra[1], rb[1]) - max(ra[0], rb[0])
            if perp < perp_tol and ov > min_overlap and (best is None or perp < best[1]):
                best = (b, perp, ov, db, b0)
        if best:
            matches.append((a, *best))
    return matches


def bearing_deg(d):
    """Undirected line bearing (0-180) from a unit direction vector, so A->B and B->A read the same."""
    ang = np.degrees(np.arctan2(d[0], d[1])) % 360
    return ang % 180


def bearing_diff_min(ba, bb):
    """Smallest angle between two undirected (0-180) bearings, in arc-minutes."""
    d = abs(ba - bb) % 180
    return min(d, 180 - d) * 60


def prove_match(a, b, db, b0, perp_med_m):
    """A geometric candidate (parallel + nearby + projected overlap) is not proof it's the SAME record
    line -- a corner where two DIFFERENT courses meet also passes that test (same point, different
    direction), and two genuinely parallel-but-distinct lines (a property line next to the R/W line)
    can share a bearing by coincidence. Proof requires one of:
      (a) bearing agrees to <=1' AND the lines nearly coincide (perp <= 0.15 m) -- same infinite line.
      (b) the pieces' nearest drawn endpoints are essentially touching (<=0.1 m) AND perp <= 0.15 m --
          literally the same drawn line continuing across, even if the short clipped chord's own
          bearing estimate is noisy.
    Anything else (a shared corner with a different bearing beyond it; a same-bearing line sitting
    metres away with a real end gap) is dropped, not reported as a matchline number."""
    ba, bb = bearing_deg(piece_dir(a)), bearing_deg(db)
    bdiff = bearing_diff_min(ba, bb)
    a0, a1 = np.array(a.coords[0]), np.array(a.coords[-1])
    b0_, b1_ = np.array(b.coords[0]), np.array(b.coords[-1])
    end_gap = min(np.hypot(*(p - q)) for p in (a0, a1) for q in (b0_, b1_))
    ok = (bdiff <= 1.0 and perp_med_m <= 0.15) or (end_gap <= 0.1 and perp_med_m <= 0.15)
    return ok, bdiff, end_gap


def sample_perp_offsets(a, b, db, b0, n=12):
    a0, a1 = np.array(a.coords[0]), np.array(a.coords[-1])
    ts = np.linspace(0, 1, n)
    offs = []
    for t in ts:
        p = a0 + t * (a1 - a0)
        v = p - b0
        offs.append(abs(v[0] * db[1] - v[1] * db[0]))
    return np.array(offs)


# --- labels ---
BEARING_DIST = re.compile(
    r"([NS])\s?(\d{1,3})[^0-9]{1,3}(\d{1,2})[^0-9]{1,3}(\d{1,2})[^0-9A-Z]{0,3}([EW])(?:\s*\|?\s*([\d,]+\.\d{2})')?"
)


def reads_for(d):
    rs, rg, rr, rt = d / "read_shx.json", d / "read_glyph.json", d / "read_rapid.json", d / "tables.json"

    def has_text(p):
        if not p.exists() or p.stat().st_size < 2:
            return False
        try:
            return any(b.get("text") for b in json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            return False

    def has_rows(p):
        if not p.exists():
            return False
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        return isinstance(t, dict) and any(not k.startswith("_") for k in t)

    validated = has_rows(rt)
    if has_text(rs):
        return rs
    if rg.exists() and rg.stat().st_size > 2 and (validated or not rr.exists()):
        return rg
    return rr


def sheet_fit(d):
    g = json.loads((d / "georef.json").read_text())
    a, b, tx, ty = g["params"]
    return a, b, tx, ty


def to_ground_utm(sx, sy, fit):
    a, b, tx, ty = fit
    E = a * sx - b * (-sy) + tx
    N = b * sx + a * (-sy) + ty
    return ccs83_to_utm.transform(E, N)  # epoch shift cancels between sheets, so skipped here


def sheet_labels(d):
    blocks = json.loads(reads_for(d).read_text(encoding="utf-8"))
    fit = sheet_fit(d)
    out = []
    for b in blocks:
        m = BEARING_DIST.search(b.get("text", ""))
        if not m:
            continue
        x, y = to_ground_utm(b["cx"], b["cy"], fit)
        out.append({"printed": b["text"], "x": x, "y": y})
    return out


def pair_labels(La, Lb, tol=6.0):
    pairs = []
    usedB = set()
    for a in La:
        best, bd = None, tol
        for j, b in enumerate(Lb):
            if j in usedB:
                continue
            dd = np.hypot(a["x"] - b["x"], a["y"] - b["y"])
            if dd < bd:
                best, bd = j, dd
        if best is not None:
            usedB.add(best)
            pairs.append((a, Lb[best], bd))
    return pairs


def norm_bd(s):
    m = BEARING_DIST.search(s)
    if not m:
        return None
    ns, d, mm, ss, ew, dist = m.groups()
    return f"{ns}{int(d):02d}-{int(mm):02d}-{int(ss):02d}{ew}", (float(dist.replace(',', '')) if dist else None)


def plot_zoom(name, dA, dB, rect, HA, HB, matches, path):
    fig, ax = plt.subplots(figsize=(9, 8), dpi=150)
    for h in HA:
        ax.plot(h[:, 0], h[:, 1], color="#ff2a2a", lw=0.9, alpha=0.85)
    for h in HB:
        ax.plot(h[:, 0], h[:, 1], color="#00a2ff", lw=0.9, alpha=0.85)
    for a, b, perp, ov, db, b0 in matches:
        xa, ya = a.xy; xb, yb = b.xy
        ax.plot(xa, ya, color="#ff2a2a", lw=2.2)
        ax.plot(xb, yb, color="#00a2ff", lw=2.2)
    pad = 15
    ax.set_xlim(rect[0] - pad, rect[1] + pad); ax.set_ylim(rect[2] - pad, rect[3] + pad)
    ax.set_aspect("equal")
    ax.set_title(f"{name}: red={dA} blue={dB} (matched pieces bold) | UTM10N m")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


def run_pair(nameA, nameB):
    dA, dB = SHEETS[nameA], SHEETS[nameB]
    HA, HB = load_lines(dA, "heavy"), load_lines(dB, "heavy")
    if not HA or not HB:
        return None
    bA, bB = bbox(HA), bbox(HB)
    ox = max(bA[0], bB[0]) < min(bA[1], bB[1])
    oy = max(bA[2], bB[2]) < min(bA[3], bB[3])
    if not (ox and oy):
        return {"abuts": False, "bboxA": bA, "bboxB": bB}
    rect = overlap_rect(bA, bB)
    area = (rect[1] - rect[0]) * (rect[3] - rect[2])
    if area <= 0 or area > 4_000_000:  # sanity: real matchline overlap, not two sheets sharing a huge corridor by chance
        return {"abuts": False, "bboxA": bA, "bboxB": bB, "note": f"overlap area {area:.0f} m2 rejected"}

    chA, chB = merged_chains(HA), merged_chains(HB)
    pA, pB = clip_pieces(chA, rect), clip_pieces(chB, rect)

    # bbox overlap can be spurious (two L-shaped extents overlapping in a corner neither sheet actually
    # draws into): require some clipped pieces from A and B to actually sit near each other before
    # calling this a real, checkable matchline.
    if pA and pB:
        close = min(a.distance(b) for a in pA for b in pB) < 20.0
    else:
        close = False
    if not close:
        return {"abuts": False, "bboxA": bA, "bboxB": bB,
                "note": f"bboxes overlap but drawn linework in the zone does not co-locate "
                        f"(A {len(pA)} pieces, B {len(pB)} pieces, nearest {min((a.distance(b) for a in pA for b in pB), default=float('inf')):.0f} m apart)"}

    candidates = match_pieces(pA, pB)
    proven, dropped = [], []
    for a, b, perp, ov, db, b0 in candidates:
        offs = sample_perp_offsets(a, b, db, b0)
        perp_med_m = float(np.median(offs))
        ok, bdiff, end_gap = prove_match(a, b, db, b0, perp_med_m)
        rec = {"a": a, "b": b, "db": db, "b0": b0, "offs": offs, "perp_med_m": perp_med_m,
               "bdiff_min": bdiff, "end_gap_m": end_gap}
        (proven if ok else dropped).append(rec)
    matches = [(r["a"], r["b"], None, None, r["db"], r["b0"]) for r in proven]  # for plot_zoom
    per_match = [float(r["perp_med_m"] * FT_PER_M) for r in proven]
    perp_all = np.concatenate([r["offs"] for r in proven]) if proven else np.array([])

    eA, eB = true_endpoints(chA, rect), true_endpoints(chB, rect)
    gaps = []
    usedB = set()
    for pa in eA:
        dists = [np.hypot(*(pa - pb)) for pb in eB]
        if dists:
            j = int(np.argmin(dists))
            if dists[j] < 5.0 and j not in usedB:
                usedB.add(j)
                gaps.append(dists[j])

    LA, LB = sheet_labels(dA), sheet_labels(dB)
    # keep labels near the shared corridor only
    LA = [l for l in LA if rect[0] - 60 < l["x"] < rect[1] + 60 and rect[2] - 60 < l["y"] < rect[3] + 60]
    LB = [l for l in LB if rect[0] - 60 < l["x"] < rect[1] + 60 and rect[2] - 60 < l["y"] < rect[3] + 60]
    lpairs = pair_labels(LA, LB)
    lrows = []
    for a, b, dd in lpairs:
        na, ndist_a = norm_bd(a["printed"])
        nb, ndist_b = norm_bd(b["printed"])
        lrows.append({"A": a["printed"], "B": b["printed"], "sep_m": dd,
                      "bearing_agree": na == nb, "dist_agree": (ndist_a == ndist_b) if (ndist_a and ndist_b) else None})

    png = OUTDIR / f"matchline_{nameA}_{nameB}.png"
    plot_zoom(f"{nameA} / {nameB}", nameA, nameB, rect, HA, HB, matches, png)

    return {"abuts": True, "rect": rect, "n_pieces_A": len(pA), "n_pieces_B": len(pB),
            "n_candidates": len(candidates), "n_proven": len(proven), "dropped": dropped,
            "n_matched": len(matches), "perp_offsets_ft": (perp_all * FT_PER_M).tolist(),
            "per_match_ft": per_match,
            "gaps_ft": [g * FT_PER_M for g in gaps], "labels": lrows, "png": png.name}


def fmt_stats(vals):
    if not vals:
        return "n/a (no matches)"
    v = np.array(vals)
    return f"n={len(v)} median {np.median(v):.2f} ft, max {v.max():.2f} ft, p90 {np.percentile(v, 90):.2f} ft"


def main():
    lines = ["# Matchline check\n",
             "Sheet pairs checked for actual bbox overlap first (not assumed from numbering); "
             "candidate line pairs are heavy (R/W + parcel weight) chains agreeing in direction "
             "(<12 deg) with a nearby (<8 m) parallel run and real projected overlap (>5 m) -- but a "
             "geometric candidate is not proof it is the SAME record line (a corner where two "
             "different courses meet passes the same test, and two genuinely distinct parallel lines "
             "can share a bearing by coincidence). A candidate only counts as a matchline measurement "
             "when PROVEN: bearing agrees to <=1' and the lines coincide (perp <=0.15 m), or the pieces' "
             "drawn endpoints are essentially touching (<=0.1 m) and perp <=0.15 m. Unproven candidates "
             "are listed and dropped, not folded into the stats. The cleanest measure of all, where "
             "available, is the ground-position offset between the SAME printed bearing/distance label "
             "appearing on both sheets (labels section) -- that needs no line-identity assumption at "
             "all, just OCR/text-match on the printed string.\n"]
    for nameA, nameB in CANDIDATE_PAIRS:
        r = run_pair(nameA, nameB)
        lines.append(f"\n## {nameA} / {nameB}\n")
        if r is None:
            lines.append("one sheet has no heavy linework in the snapshot -- skipped.\n")
            continue
        if not r["abuts"]:
            lines.append(f"does not abut (bboxes: A {r['bboxA']}, B {r['bboxB']}"
                          f"{', ' + r['note'] if 'note' in r else ''}) -- skipped.\n")
            continue
        lines.append(f"overlap rect (UTM10N m): {tuple(round(v) for v in r['rect'])} "
                      f"| heavy pieces in zone: A {r['n_pieces_A']}, B {r['n_pieces_B']} "
                      f"| geometric candidates {r['n_candidates']}, proven {r['n_proven']}\n")
        if r["dropped"]:
            lines.append("  dropped (geometric candidate, not proven same line):\n")
            for d in r["dropped"]:
                lines.append(f"    - bearing diff {d['bdiff_min']:.1f}', end gap {d['end_gap_m']:.2f} m, "
                             f"perp {d['perp_med_m'] * FT_PER_M:.1f} ft -- "
                             f"{'same bearing but lines do not coincide/connect' if d['bdiff_min'] <= 1 else 'different bearing beyond a shared point' if d['end_gap_m'] <= 0.1 else 'neither bearing nor endpoints line up'}\n")
        if r["n_candidates"] == 0:
            lines.append("  drawn linework from both sheets comes within 20 m in this zone but no piece pair "
                         "agrees in direction/overlap -- see the crop: likely different features, not a shared record line.\n")
        lines.append(f"- perpendicular offset, PROVEN pairs only: {fmt_stats(r['perp_offsets_ft'])}\n")
        if r["per_match_ft"]:
            lines.append("  per proven pair (median ft): " + ", ".join(f"{v:.2f}" for v in sorted(r["per_match_ft"])) + "\n")
        lines.append(f"- corner/end-tie gap (nearest-neighbour endpoints <5 m, NOT bearing-verified -- "
                     f"weaker evidence than the proven line pairs or the label offsets below): {fmt_stats(r['gaps_ft'])}\n")
        if r["labels"]:
            n_ok = sum(1 for l in r["labels"] if l["bearing_agree"])
            seps_ft = [l["sep_m"] * FT_PER_M for l in r["labels"] if l["bearing_agree"]]
            lines.append(f"- **same-label offset (cleanest measure): {len(r['labels'])} bearing/distance "
                         f"labels within 6 m on both sheets, {n_ok} print the identical bearing** "
                         f"{'-- ' + fmt_stats(seps_ft) if seps_ft else ''}\n")
            for l in r["labels"]:
                mark = "OK" if l["bearing_agree"] else "DIFF"
                lines.append(f"  - [{mark}] `{l['A']}` vs `{l['B']}` ({l['sep_m']:.2f} m = {l['sep_m']*FT_PER_M:.2f} ft apart)\n")
        else:
            lines.append("- no printed bearing/distance labels found within 6 m on both sheets near this matchline\n")
        lines.append(f"- zoom (proven pairs only, bold): `{r['png']}`\n")
    (OUTDIR / "matchline.md").write_text("".join(lines), encoding="utf-8")
    print("wrote", OUTDIR / "matchline.md")


if __name__ == "__main__":
    main()
