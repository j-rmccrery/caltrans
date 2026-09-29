"""Loop17 leg M: the honest ceiling on recon.py's reconstructability metric.

recon_attrib.py already gives every dimensioned-but-uncovered foot one cause; the biggest one,
no_traverse_edge (unlabelled + labelled + residual_contamination), means "no traverse.json row of
any kind sits near this stretch" -- it does NOT say whether the RECORD ever printed a value for that
stretch at all. This script answers that, for every no_traverse_edge stretch, by grouping the
uncovered elementary segments into contiguous runs and giving each run one of five classes:

  a  dimensioned on THIS sheet but never read/associated -- a printed bearing/distance/curve-length
     token exists on the sheet whose own value fits the run (bearing within BEAR_TOL_DEG deg and/or
     distance within DIST_TOL_PCT of the run's chord, positioned within PLAUSIBLE_FT of the run on
     the ground) -- these are next fixes, an association/read miss, not a missing record.
  b  dimensioned on a matchline neighbour -- the SAME ground line (by position+direction) IS a clean
     reconstructed edge on an abutting sheet's own traverse.json, even though this sheet's traverse
     never reached it. Geometric test, not a text search: traverse.json "pts" are ground coordinates
     shared across sheets (same real-world CRS), so recon.covered_mask() against the NEIGHBOUR's own
     rec_edges is a direct, sheet-independent proof the record reached this exact line somewhere in
     the six-sheet set.
  c  referenced but not dimensioned here -- a note token (SEE R-..., PER DEED, M-####, EXIST R/W SEE
     NOTE) sits near the run, or the only nearby distance match is a "(T)" total (covers several
     courses, not this one alone).
  d  not dimensioned anywhere in the set -- no evidence found for a/b/c. The honest ceiling excludes
     this (plain drawn lines with no record value can never be reconstructed from the record).
  e  contamination -- not really boundary. Reuses recon_attrib's own hand-identified presidio wedge
     list (PRESIDIO_CONTAM_PT); this script does not hunt for new contamination sources.

Runs are chained maximal sequences of consecutive (in recon.py's own elementary-segment order)
uncovered segments with NO nearby traverse row of any kind (any_match False in covered_mask against
ALL traverse rows, same test recon_attrib.py uses for its no_traverse_edge bucket), whose endpoints
touch within CHAIN_TOL_FT.

Read-only: imports recon.py/recon_attrib.py functions, never calls their file-writing entry points
(run_sheet()/report()) -- and monkeypatches recon.make_figure/make_zoom_figure to no-ops so
recon.run()'s own side effects stay to recon.json (sanctioned, identical content) only.

usage: SHEET=<pdf> python spike/recon_ceiling.py          (one sheet; unset SHEET for presidio)
       python spike/recon_ceiling.py --report              (aggregate ceiling_<stem>.json -> md)
"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import PDF, DEFAULT  # noqa: E402
import recon  # noqa: E402
import recon_attrib  # noqa: E402
from checks import BEAR, DIST, TOKEN, LEN_TOK, dist_num, azimuth  # noqa: E402

OUT_RECON = recon.OUT_RECON
CROPS_DIR = OUT_RECON / "ceiling_crops"
CHAIN_TOL_FT = 1.5        # ft: how close two elementary segments' shared endpoint must sit to chain
BEAR_TOL_DEG = 0.5        # deg: task spec
DIST_TOL_PCT = 0.01       # 1%: task spec
DIST_TOL_FLOOR_FT = 1.0   # floor for short runs
PLAUSIBLE_FT = 250.0      # ft: how far a printed token may sit from the run and still "fit" it
BEND_CONTAM_DEG = 150.0   # deg: a chained run whose own direction spread (ptp of member az mod 180)
                           # reaches this near a full reversal is a spike/wedge, not a walkable course
N_SAMPLE_CROPS = 5        # per class per sheet, for the eyeball check
CROP_MARGIN_PT = 45.0

NOTE_RE = re.compile(
    r"SEE\s+R-?\d|PER\s+DEED|PER\s+R-?\d|M-\s?\d{3,4}(\.\d+)?|EXIST(?:ING)?\s+R/?W|SEE\s+NOTE|SEE\s+SHEET",
    re.I)

# short-key <-> pdf-stem, matching bench.SHEETS / recon_attrib.SHEET_NAMES conventions
SHORT2STEM = {
    "presidio": "presidio",
    "r10434_1": "r_10434_001_2020-09-16", "r10434_3": "r_10434_003_2020-09-16",
    "r10741_1": "r_10741_001_2017-02-10", "r10741_2": "r_10741_002_2017-02-10",
    "r10741_3": "r_10741_003_2017-02-10",
}
STEM2SHORT = {v: k for k, v in SHORT2STEM.items()}
NEIGHBORS = {  # abutting pairs only (matchline.md: .1/.3 within a tile do NOT abut)
    "presidio": ["r10434_1", "r10434_3"], "r10434_1": ["presidio"], "r10434_3": ["presidio"],
    "r10741_1": ["r10741_2"], "r10741_2": ["r10741_1", "r10741_3"], "r10741_3": ["r10741_2"],
}
BASE_OUT = recon_attrib.BASE_OUT


def neighbor_out_dir(short_key):
    stem = SHORT2STEM[short_key]
    return BASE_OUT if short_key == "presidio" else BASE_OUT / stem


def load_neighbor_rec(short_key):
    p = neighbor_out_dir(short_key) / "traverse.json"
    if not p.exists():
        return None
    trav = json.loads(p.read_text(encoding="utf-8"))
    rec_edges, _ = recon.load_rec_edges(trav)
    rP, rQ, raz, rparent = recon.rec_segments(rec_edges)
    return rec_edges, rP, rQ, raz, rparent


def token_candidates(blocks, ground):
    """Every bearing/distance/curve-length token on the sheet -> dict with ground xy, parsed value(s)."""
    out = []
    for b in blocks:
        text = b["text"]
        gp = ground(np.array([[b["cx"], b["cy"]]]))[0]
        for tok in TOKEN.findall(text):
            if BEAR.match(tok):
                m = BEAR.match(tok)
                out.append({"kind": "bearing", "az": azimuth(tok), "radial": bool(m[6]),
                            "text": tok, "block": text, "gx": gp[0], "gy": gp[1]})
                continue
            m = DIST.match(tok)
            if m:
                val, total = dist_num(m)
                out.append({"kind": "distance", "ft": float(val), "total": total,
                            "text": tok, "block": text, "gx": gp[0], "gy": gp[1]})
        for tok in LEN_TOK.finditer(text):
            out.append({"kind": "distance", "ft": float(tok[1]), "total": bool(tok[2]),
                        "text": tok[0], "block": text, "gx": gp[0], "gy": gp[1], "curve": True})
    return out


def note_candidates(blocks, ground):
    out = []
    for b in blocks:
        m = NOTE_RE.search(b["text"])
        if m:
            gp = ground(np.array([[b["cx"], b["cy"]]]))[0]
            out.append({"text": b["text"], "gx": gp[0], "gy": gp[1]})
    return out


# title-block/legend/notes boilerplate: sample-checking r_10434_001's biggest class-d run (1261 ft)
# by eye showed its bbox sitting on the GRANTOR NOTES / LEGEND / title block, not a parcel line --
# table gridlines in that corner apparently get picked up as face-boundary linework by recon.py's own
# face loader. Not the presidio-specific wedge contamination (PRESIDIO_CONTAM_PT), a different and
# more general source, checked for on every sheet.
TITLEBLOCK_RE = re.compile(  # anchors unique to the title/notes/legend block ONLY -- generic phrases
                            # that can legitimately also appear as a real note or callout elsewhere on
                            # the sheet (plain "RIGHT OF WAY", "STATE OF CALIFORNIA", legend key terms
                            # like "ACCESS PROHIBITED") are deliberately excluded: one such match far
                            # from the real title block (found: a "...STATE OF CALIFORNIA..." disclaimer
                            # paragraph near the TOP of the presidio sheet) blew this box up to cover
                            # nearly the whole sheet and wrongly swallowed every run into (e).
                            r"GRANTOR NOTES|^LEGEND$|COPYRIGHT 20\d\d CALIFORNIA DEPARTMENT OF TRANSPORTATION|"
                            r"^RECORD MAP$|^SCALE:|^DRAFTED BY|^CHECKED BY|^SHEET NO\.?$|^TOTAL SHEETS$|"
                            r"^PROJECT ID:", re.I)
TITLEBLOCK_PAD_FT = 5.0   # sample-checking found even 40 ft of pad pulled in a real, printed parcel
                           # line ("46825 PARCEL 3", bearings visible right next to it) that just
                           # happened to sit near the box's edge -- kept tight since this only ever
                           # coerces an already-unexplained (d) run (see classify_run's caller), so
                           # under-catching genuine title-block debris an outer corner costs a few
                           # more (d) ft, not a false (a)/(c) match


def titleblock_box(blocks, ground):
    """ground-space bounding box of every title-block/legend/notes text match, padded -- a single
    region test, not per-text-block proximity: LOCAL_SPLIT_DEG (added after this check was first
    written) now cuts the title-block gridlines into several short sub-runs, and a per-run nearest-
    single-label distance test missed sub-runs that drifted more than TITLEBLOCK_TOL_FT from any one
    matched word even while still plainly inside the boilerplate block. None found -> None (no region)."""
    pts = [ground(np.array([[b["cx"], b["cy"]]]))[0] for b in blocks if TITLEBLOCK_RE.search(b["text"])]
    if not pts:
        return None
    pts = np.array(pts)
    lo, hi = pts.min(0) - TITLEBLOCK_PAD_FT, pts.max(0) + TITLEBLOCK_PAD_FT
    return lo, hi


def in_box(pt, box):
    if box is None:
        return False
    lo, hi = box
    return bool((pt >= lo).all() and (pt <= hi).all())


def az_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


LOCAL_SPLIT_DEG = 20.0  # deg: a real curve's per-1ft-elementary-segment turn is tiny (a 375 ft-radius
                         # curve turns ~0.15 deg per ft); any local jump past this is either a genuine
                         # polygon corner (two distinct courses -- split so each gets its own chord/az
                         # for token matching) or a leader-stub kink (sample-checking r_10741_002's
                         # biggest run showed a real curve L=469.16' run swept into (e) only because a
                         # coordinate-label leader stub was chained onto its end) -- split either way.


def build_runs(idx_pool, P_f, Q_f, seg_len_f, seg_az_f):
    """idx_pool: indices (into the *_f arrays) of uncovered, no-traverse-row elementary segments, in
    their original construction order. -> list of runs, each a dict of member idx / ft / chord az+len
    / ground midpoint, chained by endpoint proximity AND split wherever the walk turns more than
    LOCAL_SPLIT_DEG from one elementary segment to the next (see LOCAL_SPLIT_DEG)."""
    runs = []
    cur = []
    for i in idx_pool:
        if cur:
            prev = cur[-1]
            gap = min(np.hypot(*(Q_f[prev] - P_f[i])), np.hypot(*(Q_f[prev] - Q_f[i])),
                      np.hypot(*(P_f[prev] - P_f[i])))
            turn = az_diff(seg_az_f[prev], seg_az_f[i])
            if gap > CHAIN_TOL_FT or turn > LOCAL_SPLIT_DEG:
                runs.append(cur); cur = []
        cur.append(i)
    if cur:
        runs.append(cur)

    out = []
    for members in runs:
        ft = float(seg_len_f[members].sum())
        # chord: start point of the first segment (by whichever end chains) to end point of the last;
        # approximate as the two most-separated endpoints among the run's own P/Q set (robust to a
        # winding direction flip between consecutive segments).
        pts = np.vstack([P_f[members], Q_f[members]])
        d = np.hypot(*(pts[:, None, :] - pts[None, :, :]).transpose(2, 0, 1))
        a, bidx = np.unravel_index(np.argmax(d), d.shape)
        p0, p1 = pts[a], pts[bidx]
        chord_ft = float(np.hypot(*(p1 - p0)))
        chord_az = float(recon.azimuth_arr((p1 - p0)[None, :])[0])
        mid = (p0 + p1) / 2
        if len(members) > 1:
            # circular-safe cumulative direction spread: plain ptp(az % 180) wrongly reports a huge
            # bend for a normal, gently-sweeping curve whose azimuth range happens to straddle a
            # multiple of 180 (found sample-checking r_10741_002's 455 ft run: a real R=375'
            # delta=71.67deg curve, ptp(%180) said 173 deg). Un-wrap relative to the run's own first
            # segment instead -- safe since no real boundary run sweeps a full 360.
            rel = (seg_az_f[members] - seg_az_f[members[0]] + 180) % 360 - 180
            bend = float(np.ptp(rel))
        else:
            bend = 0.0
        out.append({"members": members, "ft": ft, "chord_ft": max(chord_ft, ft * 0.5),
                    "az": chord_az, "mid": mid, "bend_deg": bend, "n_seg": len(members)})
    return out


def classify_run(run, tok_cands, note_cands, neighbor_recs, buffer_ft):
    """(e) contamination is decided by the caller (presidio wedge list, ground-distance test) before
    this is reached; this only ever returns a/b/c/d."""
    mid = run["mid"]
    best_bear, best_dist = None, None
    for c in tok_cands:
        dpos = math.hypot(c["gx"] - mid[0], c["gy"] - mid[1])
        if dpos > PLAUSIBLE_FT:
            continue
        if c["kind"] == "bearing" and not c["radial"]:
            diff = min(az_diff(c["az"], run["az"]), az_diff(c["az"] + 180, run["az"]))
            if diff <= BEAR_TOL_DEG and (best_bear is None or dpos < best_bear[1]):
                best_bear = (c, dpos, diff)
        elif c["kind"] == "distance":
            tol = max(DIST_TOL_FLOOR_FT, DIST_TOL_PCT * run["chord_ft"])
            if abs(c["ft"] - run["chord_ft"]) <= tol and not c["total"]:
                if best_dist is None or dpos < best_dist[1]:
                    best_dist = (c, dpos, abs(c["ft"] - run["chord_ft"]))

    if best_bear or best_dist:
        ev = {}
        if best_bear:
            ev["bearing"] = {"text": best_bear[0]["text"], "block": best_bear[0]["block"],
                              "dist_pt_ground_ft": round(best_bear[1], 1), "diff_deg": round(best_bear[2], 3)}
        if best_dist:
            ev["distance"] = {"text": best_dist[0]["text"], "block": best_dist[0]["block"],
                               "dist_pt_ground_ft": round(best_dist[1], 1), "diff_ft": round(best_dist[2], 2)}
        return "a", ev

    # (b) matchline neighbour: proven on a neighbour's own traverse
    for nkey, rec in neighbor_recs.items():
        if rec is None:
            continue
        rec_edges, rP, rQ, raz, rparent = rec
        if len(rP) == 0:
            continue
        any_match, best = recon.covered_mask(mid[None, :], np.array([run["az"]]), rP, rQ, raz,
                                              buffer_ft, recon.PARALLEL_TOL_DEG)
        if any_match[0]:
            e = rec_edges[rparent[best[0]]]
            return "b", {"neighbor": nkey, "edge": e["name"], "edge_ft": e["ft"], "edge_az": round(e["az"], 2)}

    # (c) referenced but not dimensioned here: a note nearby (SEE R-, PER DEED, ...) -- genuinely not
    # this sheet's own record value, unreachable from these six sheets alone.
    for n in note_cands:
        if math.hypot(n["gx"] - mid[0], n["gy"] - mid[1]) <= PLAUSIBLE_FT:
            return "c", {"note": n["text"]}
    # (c_T) a bare "(T)" total nearby, no per-piece breakdown -- loop18 leg 1 (JR): this IS the sheet's
    # own printed record value for the whole run, just not yet split into its own pieces (loop18 leg 3's
    # own task: "(T) totals as whole courses"). Split out of (c) into its own class: reachable in
    # principle (a total that sums its own run within tolerance is a record value, not a missing one),
    # not lumped in with a genuine cross-reference to another sheet/deed this six-sheet set can never
    # resolve on its own.
    for c in tok_cands:
        if c["kind"] == "distance" and c["total"] and math.hypot(c["gx"] - mid[0], c["gy"] - mid[1]) <= PLAUSIBLE_FT:
            return "c_T", {"note": f"(T) total only: {c['text']} in \"{c['block']}\""}

    return "d", {}


def run_sheet():
    sheet_name = "presidio" if PDF == DEFAULT else PDF.stem
    short_key = STEM2SHORT.get(sheet_name)
    if short_key is None:
        raise SystemExit(f"unrecognised sheet {sheet_name}; add it to SHORT2STEM")

    recon.make_figure = lambda *a, **k: None
    recon.make_zoom_figure = lambda *a, **k: None

    result, internals = recon.run(sheet_name, return_internals=True)
    inv, ground, buffer_ft = internals["inv"], internals["ground"], internals["buffer_ft"]
    remaining = internals["remaining"]
    P_f, Q_f = internals["P"][remaining], internals["Q"][remaining]
    mid_f = internals["mid"][remaining]
    seg_len_f = internals["seg_len"][remaining]
    seg_az_f = internals["seg_az"][remaining]
    cov_f = internals["cov_mask_full"][remaining]
    dim_f = internals["dim_mask_full"][remaining]

    rows = recon_attrib.load_all_rows()
    rP, rQ, raz, ridx = recon_attrib.row_segments(rows)
    uncov_mask = dim_f & ~cov_f
    any_match, _ = recon.covered_mask(mid_f, seg_az_f, rP, rQ, raz, buffer_ft, recon.PARALLEL_TOL_DEG)
    notrav_mask = uncov_mask & ~any_match
    idx_pool = np.nonzero(notrav_mask)[0]

    runs = build_runs(idx_pool, P_f, Q_f, seg_len_f, seg_az_f)
    notrav_ft = float(seg_len_f[notrav_mask].sum())
    runs_ft = sum(r["ft"] for r in runs)
    assert abs(runs_ft - notrav_ft) < 1.0, f"{sheet_name}: run sum {runs_ft:.1f} != notrav {notrav_ft:.1f}"

    blocks = internals["blocks"]
    tok_cands = token_candidates(blocks, ground)
    note_cands = note_candidates(blocks, ground)
    contam_pts_ground = (ground(np.array(recon_attrib.PRESIDIO_CONTAM_PT))
                          if sheet_name == "presidio" else np.zeros((0, 2)))
    contam_tol_ground = recon_attrib.PRESIDIO_CONTAM_TOL_PT * internals["scale"]
    tb_box = titleblock_box(blocks, ground)

    neighbor_recs = {nk: load_neighbor_rec(nk) for nk in NEIGHBORS.get(short_key, [])}

    classified = []
    for r in runs:
        cls, ev = "?", {}
        if r["bend_deg"] >= BEND_CONTAM_DEG:
            # sample-checking (presidio_c_0_247ft.png, r_10434_003's 188/455 ft d-runs) showed every
            # run whose direction nearly reverses on itself (bend_deg close to 180) is a thin spike --
            # a real boundary course only ever walks forward; this is the same leader/wedge shape
            # recon_attrib's hand-picked PRESIDIO_CONTAM_PT list caught on presidio alone, generalised.
            cls, ev = "e", {"note": f"near-reversal run (bend {r['bend_deg']:.0f} deg): spike/wedge/leader shape"}
        elif len(contam_pts_ground) and np.hypot(*(contam_pts_ground - r["mid"]).T).min() <= contam_tol_ground:
            cls, ev = "e", {"note": "presidio wedge list (recon_attrib.PRESIDIO_CONTAM_PT)"}
        else:
            cls, ev = classify_run(r, tok_cands, note_cands, neighbor_recs, buffer_ft)
            if cls == "d" and in_box(r["mid"], tb_box):
                # titleblock_box is a coarse rectangle (real drawn parcel content can sit just inside
                # its padding next to the actual notes/legend/title furniture -- sample-checking found
                # a "46825 PARCEL 3" bubble with a real printed bearing there) -- so it only ever
                # coerces an otherwise-unexplained (d) run, never overrides a genuine a/b/c match.
                cls, ev = "e", {"note": "title block / legend / notes boilerplate region"}
        members = r["members"]
        pg = np.vstack([inv(P_f[members]), inv(Q_f[members])])
        classified.append({"ft": r["ft"], "chord_ft": r["chord_ft"], "az": r["az"], "bend_deg": r["bend_deg"],
                            "n_seg": r["n_seg"], "class": cls, "evidence": ev,
                            "mid_page": inv(r["mid"][None, :])[0].tolist(),
                            "mid_ground": r["mid"].tolist(),
                            "page_bbox": [float(pg[:, 0].min()), float(pg[:, 1].min()),
                                          float(pg[:, 0].max()), float(pg[:, 1].max())]})

    classes_ft = {}
    for c in classified:
        classes_ft[c["class"]] = classes_ft.get(c["class"], 0.0) + c["ft"]
    assert abs(sum(classes_ft.values()) - notrav_ft) < 1.0

    out = {
        "sheet": sheet_name, "short_key": short_key,
        "recon_dim_denom_ft": result["recon_dim_denom_ft"], "recon_dim_covered_ft": result["recon_dim_covered_ft"],
        "notrav_ft": round(notrav_ft, 1), "n_runs": len(classified),
        "classes_ft": {k: round(v, 1) for k, v in classes_ft.items()},
        "runs": sorted(classified, key=lambda c: -c["ft"]),
    }
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / f"ceiling_{sheet_name}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")

    make_crops(sheet_name, internals["page"], classified)

    print(f"{sheet_name}: notrav {notrav_ft:.1f} ft, {len(classified)} runs -> "
          + ", ".join(f"{k} {v:.0f}" for k, v in sorted(classes_ft.items(), key=lambda kv: -kv[1])))


def make_crops(sheet_name, page, classified):
    CROPS_DIR.mkdir(parents=True, exist_ok=True)
    W, H = page.rect.width, page.rect.height
    by_class = {}
    for c in classified:
        by_class.setdefault(c["class"], []).append(c)
    for cls, items in by_class.items():
        items = sorted(items, key=lambda c: -c["ft"])[:N_SAMPLE_CROPS]
        for n, c in enumerate(items):
            x0, y0, x1, y1 = c["page_bbox"]
            clip = pymupdf.Rect(max(0, x0 - CROP_MARGIN_PT), max(0, y0 - CROP_MARGIN_PT),
                                 min(W, x1 + CROP_MARGIN_PT), min(H, y1 + CROP_MARGIN_PT))
            if clip.is_empty or clip.width < 5 or clip.height < 5:
                continue
            # cap rendered pixel size (a long run's own bbox can span most of the sheet) so the crop
            # stays a manageable image instead of a multi-thousand-px render
            scale = min(3.0, 2600.0 / max(clip.width, clip.height, 1.0))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip)
            pix.save(CROPS_DIR / f"{sheet_name}_{cls}_{n}_{c['ft']:.0f}ft.png")


SHEET_ORDER = ["presidio", "r10434_1", "r10434_3", "r10741_1", "r10741_2", "r10741_3"]


UNCLEAN_BUCKETS = ["curve", "distance_from_drawing", "bearing_from_drawing", "misfit"]  # loop18 leg 1
# (JR): recon_attrib.py's own buckets for a segment the record DOES reach (a traverse row sits on it)
# but that row is still flagged/misfit -- reachable in principle (a read/association fix, not a missing
# record), unlike the no_traverse_edge pool recon_ceiling.py's own a/b/c/c_T/d/e split classifies.
# "other_flag"/"no_traverse_edge_*"/"residual_contamination"/"anomaly" are deliberately excluded: JR's
# own ruling names exactly these four.


def load_attrib(short_key, stem):
    p = (BASE_OUT / stem / "attrib.json") if stem else (BASE_OUT / "attrib.json")
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("buckets_ft", {})


def report():
    rows = []
    for short_key in SHEET_ORDER:
        stem = SHORT2STEM[short_key]
        p = OUT_RECON / f"ceiling_{stem}.json"
        if not p.exists():
            print(f"missing {p}, run: SHEET=... python spike/recon_ceiling.py")
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        r["short_key"] = short_key
        r["unclean_ft"] = sum(load_attrib(short_key, stem).get(b, 0.0) for b in UNCLEAN_BUCKETS)
        rows.append(r)

    classes = ["a", "b", "c", "c_T", "d", "e"]
    lines = ["# recon ceiling: no_traverse_edge, classified\n"]
    lines.append("class a = dimensioned here, not read/associated (next fix) | b = dimensioned on a "
                  "matchline neighbour | c = referenced, not dimensioned here (a different sheet/deed) | "
                  "c_T = a bare (T) total nearby, no per-piece breakdown yet (loop18 leg 1: reachable in "
                  "principle, split out of c) | d = not dimensioned anywhere in the set (true ceiling "
                  "loss) | e = contamination (not boundary)\n")
    lines.append("| sheet | notrav_ft | a | b | c | c_T | d | e | recon_dim_denom | recon_dim_covered |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    tot = {k: 0.0 for k in classes}
    tot_notrav = tot_denom = tot_cov = tot_unclean = 0.0
    for r in rows:
        cf = r["classes_ft"]
        lines.append(f"| {r['sheet']} | {r['notrav_ft']:.0f} | " + " | ".join(f"{cf.get(k, 0):.0f}" for k in classes)
                      + f" | {r['recon_dim_denom_ft']:.0f} | {r['recon_dim_covered_ft']:.0f} |")
        for k in classes:
            tot[k] += cf.get(k, 0.0)
        tot_notrav += r["notrav_ft"]; tot_denom += r["recon_dim_denom_ft"]; tot_cov += r["recon_dim_covered_ft"]
        tot_unclean += r["unclean_ft"]
    lines.append(f"| **total** | {tot_notrav:.0f} | " + " | ".join(f"{tot[k]:.0f}" for k in classes)
                  + f" | {tot_denom:.0f} | {tot_cov:.0f} |\n")

    lines.append("## reached but unclean (loop18 leg 1, JR): a traverse row already sits on this "
                  "stretch, but is itself flagged or misfit -- reachable in principle, a read/association "
                  "fix rather than a missing record. recon_attrib.py's own buckets, summed per sheet:\n")
    lines.append("| sheet | curve | distance_from_drawing | bearing_from_drawing | misfit | unclean total |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        stem = SHORT2STEM[r["short_key"]]
        b = load_attrib(r["short_key"], stem)
        lines.append(f"| {r['sheet']} | " + " | ".join(f"{b.get(k, 0):.0f}" for k in UNCLEAN_BUCKETS)
                      + f" | {r['unclean_ft']:.0f} |")
    lines.append(f"| **total** | " + " | ".join("" for _ in UNCLEAN_BUCKETS) + f" | {tot_unclean:.0f} |\n")

    lines.append("## ceiling implied by this split\n")
    lines.append("ceiling_reachable = covered + a + b + c_T + unclean (record dimensions or already "
                  "reaches it, pipeline could in principle complete it); ceiling_honest = "
                  "ceiling_reachable / (denom - c - d - e) (denominator narrowed to boundary THIS record "
                  "actually dimensions, on this or a neighbour sheet -- c_T and unclean stay IN the "
                  "denominator, since both are already-dimensioned boundary a fix can reach, unlike c/d/e).\n")
    lines.append("| sheet | current_pct | ceiling_reachable_pct | ceiling_honest_pct (denom - c,d,e) |")
    lines.append("|---|---|---|---|")
    for r in rows:
        cf = r["classes_ft"]
        denom, cov = r["recon_dim_denom_ft"], r["recon_dim_covered_ft"]
        reach = cov + cf.get("a", 0) + cf.get("b", 0) + cf.get("c_T", 0) + r["unclean_ft"]
        denom_honest = denom - cf.get("c", 0) - cf.get("d", 0) - cf.get("e", 0)
        cur_pct = 100 * cov / denom if denom else 0
        reach_pct = 100 * reach / denom if denom else 0
        honest_pct = 100 * reach / denom_honest if denom_honest else 0
        lines.append(f"| {r['sheet']} | {cur_pct:.1f} | {reach_pct:.1f} | {honest_pct:.1f} |")
    reach_tot = tot_cov + tot["a"] + tot["b"] + tot["c_T"] + tot_unclean
    denom_honest_tot = tot_denom - tot["c"] - tot["d"] - tot["e"]
    lines.append(f"| **total (per-sheet sum, OLD basis)** | {100*tot_cov/tot_denom:.1f} | {100*reach_tot/tot_denom:.1f} | "
                 f"{100*reach_tot/denom_honest_tot:.1f} |\n")

    # loop18 leg 1 (JR): "recompute on the deduped set basis" -- recon_set.py's own six-sheet union
    # (matchline overlap collapsed, ceiling class (e) already removed at recon.py's own source) replaces
    # the per-sheet SUM as the denominator/covered basis; the a/b/c_T/unclean/c/d/e class breakdown
    # above is still the per-sheet (not re-deduped) sum -- an approximation, flagged as such, since
    # re-deriving that split on the pooled/deduped segment set is a separate leg (recon_ceiling.py's own
    # run_sheet() classifies per sheet, one sheet's own traverse/attrib neighbourhood at a time).
    set_p = OUT_RECON / "set_recon.json"
    if set_p.exists():
        s = json.loads(set_p.read_text(encoding="utf-8"))
        new = s["new_set"]
        set_reach = new["dim_covered_ft"] + tot["a"] + tot["b"] + tot["c_T"] + tot_unclean
        lines.append("### same split, denominator/covered from the deduped SET (recon_set.py) instead of the per-sheet sum\n")
        lines.append("current_pct and ceiling_reachable_pct only -- ceiling_honest_pct (denom - c,d,e) is "
                      "NOT restated here: c/b/c_T/unclean/d/e are still the per-sheet SUM (recon_ceiling's "
                      "own run_sheet() classifies one sheet's own no_traverse_edge pool at a time, not the "
                      "pooled/deduped set), so subtracting them from the SET's own deduped, overlap-free "
                      "denominator double-subtracts the shared matchline ground and can push the ratio "
                      "past 100% (measured, dropped rather than published wrong). A deduped class "
                      "breakdown is a separate leg.\n")
        lines.append("| basis | current_pct | ceiling_reachable_pct |")
        lines.append("|---|---|---|")
        lines.append(f"| OLD (per-sheet sum) | {100*tot_cov/tot_denom:.1f} | {100*reach_tot/tot_denom:.1f} |")
        lines.append(f"| NEW (deduped set) | {100*new['dim_covered_ft']/new['dim_denom_ft'] if new['dim_denom_ft'] else 0:.1f} | "
                     f"{100*set_reach/new['dim_denom_ft'] if new['dim_denom_ft'] else 0:.1f} |\n")
    else:
        lines.append(f"(recon_set.py not yet run -- {set_p} missing; per-sheet-sum basis only above)\n")

    lines.append("## top 5 class-a runs (next fixes)\n")
    a_runs = []
    for r in rows:
        for run in r["runs"]:
            if run["class"] == "a":
                a_runs.append((r["sheet"], run))
    a_runs.sort(key=lambda t: -t[1]["ft"])
    for sheet, run in a_runs[:5]:
        ev = run["evidence"]
        bits = []
        if "bearing" in ev:
            bits.append(f"bearing {ev['bearing']['text']} ({ev['bearing']['dist_pt_ground_ft']} ft away, "
                        f"diff {ev['bearing']['diff_deg']} deg) in \"{ev['bearing']['block']}\"")
        if "distance" in ev:
            bits.append(f"distance {ev['distance']['text']} ({ev['distance']['dist_pt_ground_ft']} ft away, "
                        f"diff {ev['distance']['diff_ft']} ft) in \"{ev['distance']['block']}\"")
        lines.append(f"- {sheet} {run['ft']:.1f} ft az {run['az']:.1f}: " + "; ".join(bits))
    lines.append("")

    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / "ceiling_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_RECON / 'ceiling_report.md'}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    else:
        run_sheet()
