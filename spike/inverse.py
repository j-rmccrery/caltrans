"""Loop18 leg 2: inverse courses between two printed record coordinates.

JR ruling (2026-09-28): an inverse between two printed coordinates counts as a record course, in its
OWN column so it can be excluded. Gate is record-vs-record, not record-vs-drawing (circularity: some
of these printed coordinates were georef control, so "the inverse matches the drawing" proves nothing
-- see spike/LOOP.md loop18 leg2).

Inventory (per sheet): on-map callouts already traced to a drawn candidate vertex by georef.py's own
main() (georef.json's "control" list -- reused as-is, not re-traced) plus POINT/NORTHING/EASTING and
STATION/NORTHING/EASTING table rows read straight off the sheet the same way recon.point_table_regions/
checks.alignment_table_regions already box them off for removal (gt.py's TABLES is a hand-keyed
Presidio-only fixture georef.py's own independent check uses; a generic reader is needed here to also
cover R-10434.1/.3, which have no such fixture -- table_points()).

Pairing: every pair of inventory points that both land within SNAP_FT of the sheet's own post-removal
drawn boundary (recon.py's recon_segments.json) AND are joined by ONE continuous, mostly-uncovered,
non-deflecting run of that boundary (corridor_test() -- a real bend breaks the single merged t-interval
before it ever reaches the far point, so "no deflection" falls out of interval continuity, no separate
angle-per-segment test needed) is a candidate. A third inventory point sitting strictly between the two
drops the pair (the shorter sub-runs are preferred -- see the has_mid filter in generate_candidates()).

Gate: every printed bearing/distance/arc "(T)" text near the corridor -- both checks.py's own already-
associated labels.json entries (their own drawn "line", precise) and a raw TOKEN/BEAR/DIST scan of every
block (catches a bare "(T)" run total that never got tied to one drawn line, JR's leg 3 scope) -- must
agree with the inverse (bearing <= BEAR_TOL_DEG mod 180, distance <= DIST_TOL_FT); any disagreement
refuses the pair outright (a bend, or the coordinates bound a different span) instead of trusting the
drawing. No disagreement (including none found at all, "inverse only") accepts it.

Accepted pairs become traverse rows via as_traverse_row(), "source": "by inverse <idA>-<idB>", flags==[]
so recon.load_rec_edges() counts them like any other clean edge. Called from traverse.py's own main()
(add_inverse_chains(), only for a sheet_name in SHEET_NAMES) right after the baseline traverse.json is
written -- it re-writes traverse.json with the accepted chains appended. A recon.py bootstrap run inside
add_inverse_chains() (make_figures=False) supplies the contamination-removed boundary the corridor test
needs and its own recon.json/recon_segments.json become the "without inverse" snapshot (copied to
recon_no_inverse.json / recon_segments_no_inverse.json) that bench.py's recon_inverse_ft column and
recon_set.py's "with vs without" headline both read.

usage: python spike/inverse.py <presidio|r10434_1|r10434_3>   (report + crops, does not touch traverse.json)
       python spike/inverse.py --selftest
"""
import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, READS, real_text_blocks, number  # noqa: E402
import checks  # noqa: E402
from checks import BEAR, DIST, TOKEN, dist_num  # noqa: E402
import recon  # noqa: E402
from recon import ground_of, inv_of, point_seg_dist, point_table_regions, OUT_RECON  # noqa: E402

SHEET_NAMES = {"presidio": "presidio", "r_10434_001_2020-09-16": "r10434_1", "r_10434_003_2020-09-16": "r10434_3"}
# recon.py's own sheet_name ("presidio", else PDF.stem) -> short reporting key. traverse.py only calls
# add_inverse_chains() for a sheet_name in this dict -- the reviewer-evidence set (Presidio, R-10434.1,
# R-10434.3); R-10741.1/.2/.3 are untouched, byte-identical to loop18-1.

SNAP_FT = 0.2            # printed coordinate -> drawn boundary (JR's task 2)
PERP_TOL_FT = 2.0        # corridor half-width for "one straight run, no deflection" -- recon.py's own
# BUFFER_PT (1.5 pt) at Presidio's ~1.39 ft/pt scale is ~2.1 ft; same "on the same line" tolerance this
# whole project already uses for record-vs-drawing matching, reused here for corridor continuity.
GAP_TOL_FT = 10.0        # allowed break in corridor coverage before it's not "one run" -- loop17 leg B's
# own precedent (<= 10 ft out-and-back kinks bridged between pieces of one record course).
MID_MARGIN_FT = 5.0      # a third inventory point this far inside (A,B) drops the pair (has_mid)
MIN_RUN_FT = 10.0        # shorter than this is near-duplicate-point noise, not worth an inverse course
BEAR_TOL_DEG = 0.01      # JR's record-vs-record gate (2026-09-28): <= 0.01 deg (<= 0.1 ft lateral / run)
DIST_TOL_FT = 0.1
LABEL_LINE_PERP_TOL_FT = 2.0   # a labels.json-associated line's own midpoint, on the corridor
LABEL_TEXT_PERP_TOL_FT = 6.0   # a raw bearing/distance/"(T)" text block with no line association yet


def load_blocks(page):
    """Same combine-and-dedupe georef.main()/recon.run() use: the sheet's own reads plus selectable
    real PDF text, real text winning where both exist."""
    rs = json.loads(READS.read_text(encoding="utf-8"))
    real = real_text_blocks(page)
    return [b for b in rs if not any(abs(b["cx"] - r["cx"]) < 8 and abs(b["cy"] - r["cy"]) < 8 for r in real)] + real


def bearing_az(m):
    """checks.BEAR match -> compass azimuth deg."""
    quad, dd, mm, ss, ew = m[1], int(m[2]), int(m[3]), int(m[4]), m[5]
    ang = dd + mm / 60 + ss / 3600
    if quad == "N" and ew == "E":
        return ang
    if quad == "S" and ew == "E":
        return 180 - ang
    if quad == "S" and ew == "W":
        return 180 + ang
    return 360 - ang  # N ... W


def fmt_bearing(az):
    az = az % 360
    ns = "N" if az <= 90 or az > 270 else "S"
    ang = az if az <= 90 else (180 - az if az <= 180 else (az - 180 if az <= 270 else 360 - az))
    ew = "E" if az <= 180 else "W"
    d = int(ang); m = int((ang - d) * 60); s = round(((ang - d) * 60 - m) * 60)
    return f"{ns}{d}°{m:02d}'{s:02d}\"{ew}"


def ang_diff_mod180(a, b):
    d = abs(a - b) % 180
    return min(d, 180 - d)


# --- inventory -------------------------------------------------------------------------------------

def callout_points(g, key):
    """georef.json's own "control" list: each on-map coordinate callout already traced to a candidate
    drawn vertex (sx,sy, flipped-page convention) with its own snap residual -- reused verbatim, never
    re-traced here."""
    a, b, tx, ty = g["params"]
    out = []
    for i, c in enumerate(g.get("control", [])):
        ex = a * c["sx"] - b * c["sy"] + tx
        ny = b * c["sx"] + a * c["sy"] + ty
        out.append({"id": f"CO{i + 1}", "N": c["N"], "E": c["E"], "source": "callout", "sheet": key,
                     "control_used": bool(c.get("used")), "snap_ft": round(float(c.get("residual_ft", 0.0)), 3),
                     "snapped_E": ex, "snapped_N": ny})
    return out


NUM_ID_RE = re.compile(r"^[A-Z]{1,2}\d{0,2}$|^\d{1,3}$")


def table_points(blocks, key):
    """POINT/NORTHING/EASTING (recon.point_table_regions) and STATION/NORTHING/EASTING
    (checks.alignment_table_regions) table rows, read generically -- never hand-keyed (gt.py's TABLES
    is a Presidio-only fixture)."""
    out = []
    for region_fn, hdr_id, src in ((point_table_regions, "POINT", "table"), (checks.alignment_table_regions, "STATION", "alignment")):
        for x0, y0, x1, y1 in region_fn(blocks):
            inside = sorted((b for b in blocks if x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1), key=lambda b: b["cy"])
            hdrs = [b for b in inside if b["text"].strip() in ("NORTHING", "EASTING")]
            if not hdrs:
                continue
            cx_N = next((b["cx"] for b in hdrs if b["text"].strip() == "NORTHING"), None)
            cx_E = next((b["cx"] for b in hdrs if b["text"].strip() == "EASTING"), None)
            rows, cur, last_cy = [], [], None
            for b in inside:
                if b["text"].strip() in (hdr_id, "NORTHING", "EASTING"):
                    continue
                if last_cy is not None and b["cy"] - last_cy > 9:
                    rows.append(cur); cur = []
                cur.append(b); last_cy = b["cy"]
            if cur:
                rows.append(cur)
            for row in rows:
                vals = [(b, number(b["text"])) for b in row]
                nums = [(b, v) for b, v in vals if v]
                if len(nums) < 2:
                    continue
                ids = [b for b, v in vals if not v and NUM_ID_RE.match(b["text"].strip())]
                pid = min(ids, key=lambda b: b["cx"])["text"].strip() if ids else f"row{len(out)}"
                station = next((b["text"].strip() for b in row if "+" in b["text"]), None)

                def axis(b, v):
                    letter, val = v
                    if letter:
                        return letter
                    if cx_N is not None and cx_E is not None:
                        return "N" if abs(b["cx"] - cx_N) < abs(b["cx"] - cx_E) else "E"
                    return None
                tagged = [(axis(b, v), v[1]) for b, v in nums]
                Ns = [val for ax, val in tagged if ax == "N"]
                Es = [val for ax, val in tagged if ax == "E"]
                if len(Ns) != 1 or len(Es) != 1:
                    vs = sorted(v[1] for _, v in nums)
                    if len(vs) != 2:
                        continue
                    Ns, Es = [vs[0]], [vs[1]]  # CA zone 3: easting always the larger number
                label = f"{src[0].upper()}-{pid}" + (f" {station}" if station else "")
                out.append({"id": label, "N": Ns[0], "E": Es[0], "source": src, "sheet": key, "control_used": None})
    return out


def snap_all(points, P, Q):
    if not points:
        return
    todo = [p for p in points if "snap_ft" not in p]
    if not todo:
        return
    A = np.array([[p["E"], p["N"]] for p in todo])
    d = point_seg_dist(A, P, Q).min(1) if len(P) else np.full(len(A), np.inf)
    for p, dd in zip(todo, d):
        p["snap_ft"] = round(float(dd), 3)


# --- corridor geometry -------------------------------------------------------------------------------

def corridor_test(A, B, P, Q, seg_len, covered):
    """A, B: ground [E,N]. -> geometry dict, or None if the drawn boundary between them is not ONE
    continuous run (interval-union check: a real bend, or a genuine gap, breaks the single merged
    t-interval before it spans [0, L])."""
    d = B - A
    L = float(np.hypot(*d))
    if L < MIN_RUN_FT or len(P) == 0:
        return None
    u = d / L
    n = np.array([-u[1], u[0]])
    mid = (P + Q) / 2
    t = (mid - A) @ u
    perp = (mid - A) @ n
    sel = (t >= -GAP_TOL_FT) & (t <= L + GAP_TOL_FT) & (np.abs(perp) <= PERP_TOL_FT)
    if not sel.any():
        return None
    tp = (P[sel] - A) @ u
    tq = (Q[sel] - A) @ u
    lo = np.minimum(tp, tq); hi = np.maximum(tp, tq)
    order = np.argsort(lo)
    lo, hi = lo[order], hi[order]
    merged = [[lo[0], hi[0]]]
    for l, h in zip(lo[1:], hi[1:]):
        if l - merged[-1][1] <= GAP_TOL_FT:
            merged[-1][1] = max(merged[-1][1], h)
        else:
            merged.append([l, h])
    if len(merged) != 1:
        return None
    m_lo, m_hi = merged[0]
    if m_lo > GAP_TOL_FT or m_hi < L - GAP_TOL_FT:
        return None
    tot = float(seg_len[sel].sum())
    cov_frac = float(seg_len[sel][covered[sel]].sum() / tot) if tot else 0.0
    return {"L_ft": round(L, 2), "az_deg": round(math.degrees(math.atan2(d[0], d[1])) % 360, 4),
            "covered_frac": round(cov_frac, 3), "n_segments": int(sel.sum()), "boundary_ft": round(tot, 1)}


# --- gate: record vs record --------------------------------------------------------------------------

def label_line_hits(labels, A, B, ground_fn, u, n, L):
    hits = []
    for lb in labels:
        if lb["kind"] not in ("bearing", "distance"):
            continue
        line = lb.get("line")
        if not line or len(line) < 2:
            continue
        gp = ground_fn(np.array([line[0], line[-1]]))
        mid = gp.mean(0)
        t = float((mid - A) @ u); perp = float((mid - A) @ n)
        if -2 <= t <= L + 2 and abs(perp) <= LABEL_LINE_PERP_TOL_FT:
            val = lb.get("az") if lb["kind"] == "bearing" else lb.get("ft")
            hits.append({"text": lb["printed"], "kind": lb["kind"], "value": val,
                         "is_total": "(T)" in lb["printed"], "how": "labels.json:" + lb.get("how", "")})
    return hits


def raw_text_hits(blocks, A, B, ground_fn, u, n, L):
    hits = []
    for b in blocks:
        lines = b["text"].replace(" ", "").split("|")
        parts = [m.group(0) for t in lines for m in TOKEN.finditer(t)] or lines
        pos = ground_fn(np.array([[b["cx"], b["cy"]]]))[0]
        t = float((pos - A) @ u); perp = float((pos - A) @ n)
        if not (-2 <= t <= L + 2 and abs(perp) <= LABEL_TEXT_PERP_TOL_FT):
            continue
        for p in parts:
            mb = BEAR.match(p)
            if mb:
                hits.append({"text": p, "kind": "bearing", "value": bearing_az(mb), "is_total": False, "how": "raw-block"})
                continue
            md = DIST.match(p)
            if md:
                val, is_total = dist_num(md)
                hits.append({"text": p, "kind": "distance", "value": float(val), "is_total": is_total, "how": "raw-block"})
    return hits


def dedupe_hits(hits):
    seen, out = set(), []
    for h in hits:
        key = (h["kind"], h["text"])
        if key in seen:
            continue
        seen.add(key); out.append(h)
    return out


def gate(inv_az, inv_ft, hits):
    for h in hits:
        if h["value"] is None:
            continue
        if h["kind"] == "bearing":
            diff = ang_diff_mod180(h["value"], inv_az)
            if diff > BEAR_TOL_DEG:
                return False, h, round(diff, 4)
        else:
            diff = abs(h["value"] - inv_ft)
            if diff > DIST_TOL_FT:
                return False, h, round(diff, 3)
    return True, None, None


# --- candidate generation ----------------------------------------------------------------------------

def generate_candidates(sheet_name, key):
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text(encoding="utf-8"))
    ground_fn = ground_of(g["params"])
    blocks = load_blocks(page)
    labels = json.loads((OUT / "labels.json").read_text(encoding="utf-8")) if (OUT / "labels.json").exists() else []
    seg = json.loads((OUT / "recon_segments.json").read_text(encoding="utf-8"))
    P = np.array(seg["P"], float) if seg["P"] else np.zeros((0, 2))
    Q = np.array(seg["Q"], float) if seg["Q"] else np.zeros((0, 2))
    seg_len = np.array(seg["seg_len_ft"], float)
    covered = np.array(seg["covered"], bool)

    pts = callout_points(g, key) + table_points(blocks, key)
    snap_all(pts, P, Q)
    boundary_pts = [p for p in pts if p["snap_ft"] <= SNAP_FT]

    results = []
    n = len(boundary_pts)
    for i in range(n):
        for j in range(i + 1, n):
            pa, pb = boundary_pts[i], boundary_pts[j]
            A = np.array([pa["E"], pa["N"]]); B = np.array([pb["E"], pb["N"]])
            geo = corridor_test(A, B, P, Q, seg_len, covered)
            if geo is None:
                continue
            d = B - A; L = geo["L_ft"]; u = d / L; nrm = np.array([-u[1], u[0]])
            has_mid = False
            for k in range(n):
                if k in (i, j):
                    continue
                Ck = np.array([boundary_pts[k]["E"], boundary_pts[k]["N"]])
                t = float((Ck - A) @ u); perp = float((Ck - A) @ nrm)
                if MID_MARGIN_FT < t < L - MID_MARGIN_FT and abs(perp) <= PERP_TOL_FT:
                    has_mid = True; break
            if has_mid:
                continue
            row = {"sheet": key, "A": pa, "B": pb, **geo}
            if geo["covered_frac"] > 0.5:
                row["verdict"] = "skipped (already covered)"
                results.append(row); continue
            hits = dedupe_hits(label_line_hits(labels, A, B, ground_fn, u, nrm, L) + raw_text_hits(blocks, A, B, ground_fn, u, nrm, L))
            ok, bad, diff = gate(geo["az_deg"], geo["L_ft"], hits)
            row.update(hits=hits, verdict="accepted" if ok else "refused", refused_by=bad, refused_diff=diff)
            results.append(row)
    return results


def as_traverse_row(cand):
    a, b = cand["A"], cand["B"]
    misfit = round(max(a["snap_ft"], b["snap_ft"]), 2)
    name = f"inverse {a['id']}-{b['id']}: {fmt_bearing(cand['az_deg'])} {cand['L_ft']:.2f}'"
    row = {"edge": name, "kind": "line", "az": cand["az_deg"], "ft": cand["L_ft"], "misfit_ft": misfit,
           "chain_misfit_ft": misfit, "flags": [], "E": round(b["E"], 2), "N": round(b["N"], 2),
           "pts": [[round(a["E"], 2), round(a["N"], 2)], [round(b["E"], 2), round(b["N"], 2)]],
           "source": f"by inverse {a['id']}-{b['id']}"}
    return {"closed": False, "n_edges": 1, "full_record": 1, "misfit_max_ft": misfit, "misfit_end_ft": misfit, "edges": [row]}


def render_crops(key, g, cands):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    page = pymupdf.open(PDF)[0]
    inv_fn = inv_of(g["params"])
    W, H = page.rect.width, page.rect.height
    px = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(px.samples, dtype=np.uint8).reshape(px.height, px.width)
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    for c in cands:
        if c["verdict"] not in ("accepted", "refused"):
            continue
        a_pt = inv_fn(np.array([[c["A"]["E"], c["A"]["N"]]]))[0]
        b_pt = inv_fn(np.array([[c["B"]["E"], c["B"]["N"]]]))[0]
        cx, cy = (a_pt + b_pt) / 2
        span = max(float(np.hypot(*(b_pt - a_pt))), 40) * 0.7
        x0, x1 = max(0, cx - span), min(W, cx + span)
        y0, y1 = max(0, cy - span), min(H, cy + span)
        fig, ax = plt.subplots(figsize=(6, 6), dpi=150)
        ax.imshow(img, cmap="gray", extent=(0, W, H, 0))
        color = "#2ca02c" if c["verdict"] == "accepted" else "#e03030"
        ax.plot([a_pt[0], b_pt[0]], [a_pt[1], b_pt[1]], color=color, lw=1.6)
        ax.scatter([a_pt[0], b_pt[0]], [a_pt[1], b_pt[1]], color="#1f77b4", s=22, zorder=3)
        ax.set_xlim(x0, x1); ax.set_ylim(y1, y0); ax.set_aspect("equal")
        ax.set_title(f"{key}: {c['A']['id']} - {c['B']['id']} ({c['verdict']}, {c['L_ft']:.1f}')", fontsize=8)
        ax.axis("off")
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{c['A']['id']}-{c['B']['id']}")
        fig.savefig(OUT_RECON / f"l18_2_{key}_{safe}.png")
        plt.close(fig)


def add_inverse_chains(sheet_name):
    """Called from traverse.py's own main(), right after the baseline traverse.json is written.
    Bootstraps recon.py (contamination-removed boundary + baseline coverage -- also becomes the
    "without inverse" snapshot), computes candidates, and returns the accepted ones as new chains for
    traverse.py to append and re-write. [] for any sheet not in SHEET_NAMES."""
    if sheet_name not in SHEET_NAMES:
        return []
    key = SHEET_NAMES[sheet_name]
    recon.run(sheet_name, make_figures=False)
    shutil.copy(OUT / "recon.json", OUT / "recon_no_inverse.json")
    shutil.copy(OUT / "recon_segments.json", OUT / "recon_segments_no_inverse.json")
    g = json.loads((OUT / "georef.json").read_text(encoding="utf-8"))
    cands = generate_candidates(sheet_name, key)
    accepted = [c for c in cands if c["verdict"] == "accepted"]
    OUT_RECON.mkdir(parents=True, exist_ok=True)
    (OUT_RECON / f"l18_2_{key}.json").write_text(json.dumps(cands, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    render_crops(key, g, cands)
    print(f"inverse ({key}): {sum(1 for c in cands if c['verdict'] == 'accepted')} accepted, "
          f"{sum(1 for c in cands if c['verdict'] == 'refused')} refused, "
          f"{sum(1 for c in cands if c['verdict'].startswith('skipped'))} already covered, "
          f"of {len(cands)} corridor candidates")
    return [as_traverse_row(c) for c in accepted]


def report(key):
    sheet_name = next(k for k, v in SHEET_NAMES.items() if v == key)
    import os
    from georef import DEFAULT
    if key != "presidio":
        os.environ["SHEET"] = str(next(p for p in (Path(__file__).parent.parent / "Sample Data" / "d4").glob(f"{sheet_name}.pdf")))
    else:
        os.environ.pop("SHEET", None)
    import importlib
    import georef as _g
    importlib.reload(_g)
    importlib.reload(recon)
    cands = generate_candidates(sheet_name, key)
    for c in cands:
        a, b = c["A"], c["B"]
        print(f"{key}: {a['id']} ({a['E']:,.2f},{a['N']:,.2f} {a['source']}) -- {b['id']} "
              f"({b['E']:,.2f},{b['N']:,.2f} {b['source']}) L={c['L_ft']:.2f}' az={c['az_deg']:.3f} "
              f"cov_frac={c.get('covered_frac')} -> {c['verdict']}"
              + (f" [{c['refused_by']['text']} diff {c['refused_diff']}]" if c.get("refused_by") else ""))
    return cands


def selftest():
    """corridor_test: a straight run with no deflection spans [0,L] (accepted); one with a real bend
    partway through never forms a single merged interval (rejected). gate(): a printed bearing 0.05 deg
    off the inverse (JR's worked example, Presidio's 1086 ft run) refuses; on-tolerance agrees."""
    A = np.array([0.0, 0.0]); B = np.array([0.0, 1000.0])
    seg = [(0, y, 0, y + 1.0) for y in range(0, 1000)]
    P = np.array([[x0, y0] for x0, y0, x1, y1 in seg]); Q = np.array([[x1, y1] for x0, y0, x1, y1 in seg])
    seg_len = np.hypot(*(Q - P).T); covered = np.zeros(len(P), bool)
    geo = corridor_test(A, B, P, Q, seg_len, covered)
    assert geo is not None and abs(geo["L_ft"] - 1000.0) < 0.01, "a clean straight run must be one corridor"

    # a bend at y=500 kicks the line 20 ft sideways (past PERP_TOL_FT): the far half never matches
    P2 = P.copy(); Q2 = Q.copy()
    P2[500:, 0] = 20.0; Q2[500:, 0] = 20.0
    geo2 = corridor_test(A, B, P2, Q2, seg_len, covered)
    assert geo2 is None, "a real bend partway through must break the single merged interval"

    diff = ang_diff_mod180(105.641, 105.689)
    assert diff < BEAR_TOL_DEG * 6, f"az_diff sanity: {diff}"
    ok, bad, d = gate(285.689444, 1330.0, [{"text": "N74d18'38\"W", "kind": "bearing", "value": 285.641, "is_total": False, "how": "t"}])
    assert not ok and abs(d - 0.048) < 0.002, f"a 0.048 deg printed-bearing disagreement must refuse: got ok={ok} diff={d}"
    ok2, _, _ = gate(285.689, 1330.0, [{"text": "x", "kind": "bearing", "value": 285.695, "is_total": False, "how": "t"}])
    assert ok2, "a sub-0.01 deg agreement must accept"

    print("inverse.selftest OK: corridor continuity rejects a real bend; the record-vs-record gate "
          "refuses a 0.05 deg printed-bearing disagreement and accepts a sub-0.01 deg one")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif len(sys.argv) > 1 and sys.argv[1] in SHEET_NAMES.values():
        report(sys.argv[1])
    else:
        raise SystemExit(__doc__)
