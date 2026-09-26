"""Checks from the line and curve tables through the segment tags on the drawing.

Each tag read by tags.py (L8, C16) names a table row: bearing and distance, or radius, delta and
length. The drawn segment the tag describes is found by geometry alone: the tip of its leader, else
the one chain or arc beside it. Two candidates, none, or a partly read tag go to the queue with a
reason; nothing is guessed. Where a tag is associated, the drawn length, bearing and radius are
compared with the printed row. Table values come from the keyed tables (gt.py); the OCR-vs-key
comparison is ocr.py's own score.

Output: spike/out/tags_checks.csv, spike/out/tags_queue.json
usage: [SHEET=<pdf>] python spike/tables.py
"""
import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent))
from checks import ASSOC, AZ_FILTER, BEAR_TOL, DIST_TOL, az_diff, azimuth, build_pool, fmt_bearing, leaders, lines_on_sheet, linework_segments, parent_window, poly_dist, run_sum, seg_dist, span_for, split_chains, tag_leaders  # noqa: E402
from georef import OUT, PDF, READS, real_text_blocks, segments  # noqa: E402
from gt import TABLES  # noqa: E402

RADIUS_TOL = 0.01  # fraction: a polyline arc's fitted radius vs the printed one
BESIDE = 2.5       # glyph heights: how far from the tag a segment may sit to be "beside" it
CLEAR = 1.5        # the nearest candidate must be this many times closer than the next, else ambiguous
BOUNDARY = 0.8     # pt: R/W lines are 1.98, parcel and easement lines 0.84; hatch and ticks are 0.36-0.42


def table_rows():
    """{tag: {...}} from the tables as read by alphabet.py (tables.json); a row with an unread cell is
    left out, so its tag queues as "no such table row". Falls back to the keyed tables (gt.py)."""
    rows = {}
    if (OUT / "tables.json").exists():
        for tag, r in json.loads((OUT / "tables.json").read_text(encoding="utf-8")).items():
            if tag.startswith("_"):
                continue
            cells = r["cells"]
            try:
                if r["kind"] == "line" and len(cells) >= 2 and "?" not in cells[0] + cells[1]:
                    brg, dist = cells[0], cells[1]
                    rows[tag] = {"kind": "line", "bearing": brg, "az": azimuth(brg.replace("(R)", "").replace("(T)", "")),
                                 "dist": float(re.sub(r"[^\d.]", "", dist)), "total": "(T)" in dist}
                elif r["kind"] == "curve" and len(cells) >= 3 and "?" not in "".join(cells[:3]):
                    rr, d, ln = cells[:3]
                    dd, mm, ss = map(float, re.findall(r"\d+", d.split("(")[0]))
                    rows[tag] = {"kind": "curve", "R": float(re.sub(r"[^\d.]", "", rr)), "delta": dd + mm / 60 + ss / 3600,
                                 "L": float(re.sub(r"[^\d.]", "", ln.split("(")[0])), "total": "(T)" in d + ln}
            except (ValueError, AttributeError, TypeError):
                pass
        return rows
    L = TABLES["line"][1]
    for k in range(0, len(L), 3):
        tag, brg, dist = L[k:k + 3]
        rows[tag.replace("(T)", "")] = {"kind": "line", "bearing": brg, "az": azimuth(brg.replace("(R)", "")),
                                        "dist": float(re.sub(r"[^\d.]", "", dist)), "total": "(T)" in tag + dist}
    for name in ("curve1", "curve2"):
        C = TABLES[name][1]
        for k in range(0, len(C), 4):
            tag, r, d, ln = C[k:k + 4]
            dd, mm, ss = map(float, re.findall(r"\d+", d.split("(")[0]))
            rows[tag.replace("(T)", "")] = {"kind": "curve", "R": float(re.sub(r"[^\d.]", "", r)), "delta": dd + mm / 60 + ss / 3600,
                                            "L": float(re.sub(r"[^\d.]", "", ln.split("(")[0])), "total": "(T)" in tag + d + ln}
    return rows


def fit_radius(P):
    """Least-squares circle through polyline vertices (algebraic fit)."""
    x, y = P[:, 0], P[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones(len(P))])
    (cx, cy, c), *_ = np.linalg.lstsq(A, x ** 2 + y ** 2, rcond=None)
    return float(math.sqrt(max(c + cx ** 2 + cy ** 2, 0)))


def shape(seg):
    """The drawn line or arc a check measured, as points (pt), for the exception page."""
    P = seg["pts"][:: max(1, len(seg["pts"]) // 20)] if "pts" in seg else [seg["p0"], seg["p1"]]
    return [[round(float(x), 1), round(float(y), 1)] for x, y in P]


ROW_RUN_MAX_SKIP = 1  # at most this many differently-tagged rows skipped per direction while
# expanding (Presidio: C17 sits between C16 and C18 by NO. but is a different curve, R=342.74 not
# R=1470 -- skipped over, not a stop, so the run still reaches C18)
ROW_RUN_MAX_ROWS = 6  # a safety cap on how far a run of untagged rows alone can sweep before hitting
# another tagged same-parent row -- ponytail: a flat cap, not a smarter geometric stop, since every
# known case (Presidio's C15/C16/C18) needs only 3


def row_run(tag, seg, rows_, tag_by_num_, arcs_, scale_):
    """Loop9 leg A rule 3: the table's own consecutive NO.-order rows around a still-failing tag, folding
    in any row that's untagged on the drawing or tagged to the SAME parent curve: the drawn span between
    the outermost of those rows' own marks, checked against the sum of ALL their printed lengths (tagged
    and untagged alike) -- a record boundary that isn't drawn at all, and whose row carries no tag
    either, is otherwise unreachable (C15's own piece is C15's share plus C18's, with nothing marking
    where one ends and the other begins). None where the seed carries no "seq" (never itself part of
    a sum-group), the table has no row before/after it to try, or fewer than 2 rows end up in the run.
    Module-level (not nested in main()) so a crop/report tool can call the identical resolution main()
    used, the same reason build_pool is shared (leg6A_crops.py)."""
    m = re.match(r"([LC])(\d+)", tag)
    if not m or "seq" not in seg:
        return None
    letter, seed_n = m[1], int(m[2])
    nums = sorted(int(k[len(letter):]) for k in rows_ if k[:len(letter)] == letter and k[len(letter):].isdigit())
    if seed_n not in nums:
        return None
    idx = nums.index(seed_n)
    parent = seg["parent"]
    seed_R = rows_.get(f"{letter}{seed_n}", {}).get("R")
    included = {seed_n}
    for step in (-1, 1):
        skip, i = 0, idx + step
        while 0 <= i < len(nums) and len(included) < ROW_RUN_MAX_ROWS:
            n = nums[i]
            hit = tag_by_num_.get(n)
            # a row with no tag on the drawing at all has no geometry of its own to check a parent
            # against; its own table R is what says whether it's this same physical curve (C18) or a
            # genuinely different one that just happens to sit between two tagged rows by NO. (C17,
            # R=342.74 -- not R=1470.00) -- table_rows() already reads it whether or not it's drawn
            if hit is not None:
                qualifies = hit[2].get("parent") == parent
            else:
                r = rows_.get(f"{letter}{n}", {}).get("R")
                qualifies = r is not None and seed_R is not None and r == seed_R
            if qualifies:
                included.add(n)
            else:
                skip += 1
                if skip > ROW_RUN_MAX_SKIP:
                    break
            i += step
    if len(included) < 2:
        return None
    tagged_pieces = [tag_by_num_[n][2] for n in included if n in tag_by_num_ and "seq" in tag_by_num_[n][2]]
    if not tagged_pieces:
        return None
    lo, hi = min(x["seq"] for x in tagged_pieces), max(x["seq"] for x in tagged_pieces)
    span_pieces = sorted((x for x in arcs_ if x.get("parent") == parent and "seq" in x and lo <= x["seq"] <= hi), key=lambda x: x["seq"])
    if not span_pieces:
        return None
    keys = [f"{letter}{n}" for n in sorted(included)]
    if any(k not in rows_ for k in keys):
        return None
    Ls = [rows_[k]["L"] for k in keys]
    drawn = sum(x["len_pt"] for x in span_pieces) * scale_
    total, by_sum = run_sum(drawn, Ls)
    untagged = [f"{letter}{n}" for n in sorted(included) if n not in tag_by_num_]
    return keys, untagged, drawn, Ls, total, by_sum, span_pieces


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    tags = json.loads((OUT / "tags.json").read_text(encoding="utf-8"))
    rows = table_rows()
    if not rows or not tags:
        (OUT / "tags_queue.json").write_text("[]", encoding="utf-8")
        with open(OUT / "tags_checks.csv", "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["tag", "check", "printed", "drawn", "difference", "result", "association"])
        print("no table rows or no tags on this sheet: nothing to check"); return

    # leg8A: the identical ARC pool checks.py itself measures labels against (curves split at
    # junctions/circles/ticks, each piece carrying "parent" + "seq" -- build_pool's own doc string),
    # not a second, independently-built split -- so a curve tag's piece knows its parent curve the same
    # way an inline L= label's does (leg6A). Line tags keep tables.py's own chain pool: build_pool's
    # chains are filtered for checks.py's OWN inline-label use (a stub joined to a leader, or touching
    # ANY text label within 150 pt, is dropped -- right for a free-floating bearing/distance annotation,
    # wrong for a table tag, whose short lot-line segment often sits right next to its own tag; sharing
    # it here lost L1/L5/L10/L17/L18 on r10434_1, measured).
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    pool = build_pool(page, blocks)
    arcs, ticks = pool["arcs"], pool["ticks"]
    paths, leader_pids = leaders(page)
    segs = [s for s in linework_segments(page, max_gray=0.2) if s[3] not in leader_pids]
    _, circles = segments(page)
    chains = [c for c in lines_on_sheet(segs, circles) if c["len_pt"] >= 1 and not (c["width"] < BOUNDARY and c["len_pt"] < 9)]  # thin stubs are stationing ticks
    chains = split_chains(chains, circles)  # pieces between breaks; a tag's span is chosen among them by the table's distance

    def along(seg, pt):
        """Unit direction of a chain, or of the arc facet nearest pt."""
        if "dir" in seg:
            return seg["dir"]
        P = seg["pts"]
        k = int(np.hypot(*(P - pt).T).argmin())
        v = P[min(k + 1, len(P) - 1)] - P[max(k - 1, 0)]
        return v / max(np.hypot(*v), 1e-9)

    def candidates(kind, pt, radius, min_width=0.0, arrow=None, exclude_dashdot=False):
        # loop9 leg A attempt 2: a dash-dot train (rule 2) is excluded from the no-leader "beside" curve
        # search -- proximity alone let several unrelated small curves (r10434_3's C6/C32/C9/C33) latch
        # onto the SAME wide alignment-centerline dash-dot train as their nearest candidate, none of them
        # actually its record. A leader landing squarely on the piece is a much stronger signal and still
        # reaches it (Presidio's C20 resolves this way).
        pool = [ln for ln in chains if ln["width"] >= min_width] if kind == "line" else \
            [arc for arc in arcs if arc["width"] >= min_width and not (exclude_dashdot and arc.get("dashdot"))]
        dist = (lambda s: seg_dist(pt, s["p0"], s["p1"])) if kind == "line" else (lambda s: poly_dist(pt, s["pts"]))
        found = sorted(((dist(s), s) for s in pool if dist(s) < radius), key=lambda t: t[0])
        if arrow is not None:  # an arrow points across the line it means, not along it: a stationing tick lies along the arrow
            found = [(d, s) for d, s in found if abs(along(s, pt) @ arrow) < math.cos(math.radians(30))]
        return found

    TICK_HALF = 4.5  # pt: a radial tick/stub is drawn 5-9 pt long (build_pool's own ticks range); half
    # that either side of the stored midpoint, since only midpoint + direction are kept

    def tick_target(tip, reach):
        """A curve tag's leader tip that lands on a radial tick or short straight stub, not the curve
        itself (leg8A): the tick within `reach` of the tip, whose own far end sits within 2 pt of a
        curve piece, names that piece -- not the tick. Nearest such piece wins where more than one
        tick is that close."""
        best = None
        for m, d in ticks:
            if np.hypot(*(m - tip)) >= reach:
                continue
            for end in (m + TICK_HALF * d, m - TICK_HALF * d):
                for arc in arcs:
                    dd = poly_dist(end, arc["pts"])
                    if dd < 2.0 and (best is None or dd < best[0]):
                        best = (dd, arc)
        return best[1] if best else None

    tips = tag_leaders(tags, paths)
    ambig = []  # diagnostic: ambiguous tags, for the table-order adjacency headroom
    tick_fires = 0  # leg8A: tags resolved via a radial tick/stub instead of the curve directly
    window_fires = 0  # leg8A: tags whose own L matched a contiguous window of their parent, alone
    group_fires = 0  # leg8A: tags that only passed as part of a same-parent group run
    out, queue, curve_hits, placed = [], [], [], []  # placed: every tag's table values with the line they sit on, for the traverse
    for ti, t in enumerate(tags):
        region = [round(t["cx"] - 2 * t["gh"]), round(t["cy"] - t["gh"]), round(t["cx"] + 2 * t["gh"]), round(t["cy"] + t["gh"])]
        if "?" in t["tag"]:
            queue.append({"tag": t["tag"], "issue": "tag partly unread", "region": region}); continue
        row = rows.get(t["tag"].replace("(T)", ""))
        if row is None:
            queue.append({"tag": t["tag"], "issue": "no such table row", "region": region}); continue
        kind = row["kind"]
        gh = t["gh"]
        how, cands = "beside", []
        tip = tips.get(ti)
        if tip is not None:
            tip, arrow, hsize = tip
            # a bigger drawn arrowhead can leave a bigger real gap to a curve's tangent (loop2 leg C);
            # a line's tip test stays a fixed 4 pt
            reach = 4.0 if kind == "line" else max(4.0, 0.6 * hsize)
            cands = candidates(kind, tip, reach)  # ponytail: no arrow-direction test; a tag at a line's end gets its arrow along the line
            how = "leader"
            if not cands and kind == "curve":
                # the leader tip may land on a radial tick or short straight stub that meets the curve,
                # not the drawn curve itself (leg8A): resolve to the piece the tick's own far end touches
                arc = tick_target(tip, reach)
                if arc is not None:
                    cands = [(poly_dist(tip, arc["pts"]), arc)]
                    tick_fires += 1
            if not cands:
                queue.append({"tag": t["tag"], "issue": f"leader points at no {kind}", "region": region}); continue
        else:
            cands = candidates(kind, np.array([t["cx"], t["cy"]]), BESIDE * gh, BOUNDARY, exclude_dashdot=True)
        if not cands:
            queue.append({"tag": t["tag"], "issue": f"no leader, no {kind} beside the tag", "region": region}); continue
        if len(cands) > 1 and cands[1][0] < CLEAR * cands[0][0]:
            # the table row's own values pick among the candidates (bearing and length for a line, radius
            # for a curve); one survivor, or a clear nearest among survivors, is the association
            if kind == "line":
                fit = [(d, s) for d, s in cands if az_diff(math.degrees(math.atan2(a * s["dir"][0] + bb * s["dir"][1], bb * s["dir"][0] - a * s["dir"][1])) % 360, row["az"]) < AZ_FILTER]
                if row.get("dist") and not row["total"]:
                    fit2 = [(d, s) for d, s in fit if abs(span_for(s, row["dist"], scale, chains)["len_pt"] * scale - row["dist"]) < 1.0]
                    fit = fit2 or fit
            else:
                fit = [(d, s) for d, s in cands if len(s["pts"]) >= 3 and abs(fit_radius(s["pts"]) * scale - row["R"]) < 0.02 * row["R"]]
                if len(fit) > 1 and row.get("L") and not row["total"]:
                    # a compound bezier curve's whole path and its own split piece(s) (loop2 leg C
                    # attempt 2) sit at the identical distance from the tag and fit the identical circle
                    # (a piece is a subset of the same physical arc) -- radius alone can never tell them
                    # apart. Length does: the printed row length picks the one piece (or the whole, if it
                    # was never actually compound) that is the tag's own arc, the same way a line's own
                    # printed distance already picks among its candidates above
                    # a tie in the length match (the whole path and a piece land on the identical length,
                    # or two pieces do) used to fall to fit's own order -- itself cands' order, itself
                    # arcs' build order (page.get_drawings() then split_at's pieces): an accident of paint
                    # order, not of the geometry. Tie-break on the candidate's own point count (fewer
                    # points: prefer the specific piece over the whole compound path) then its own start
                    # coordinate -- both properties of the candidate itself, not of list position (leg E)
                    fit = [min(fit, key=lambda t: (abs(t[1]["len_pt"] * scale - row["L"]), len(t[1]["pts"]), float(t[1]["pts"][0][0]), float(t[1]["pts"][0][1])))]
                elif not fit:
                    # neither candidate's fitted radius is even close to the row (or one is too short to
                    # fit a radius at all): not a real tie between two good matches -- the wider reach for
                    # a big arrowhead (loop2 leg C) just admitted an extra unrelated piece next to a short
                    # target arc. Nearest wins, the same fallback checks.py's own at_tip already uses when
                    # no candidate's length matches a leader tip's printed value
                    fit = [cands[0]]
            if len(fit) == 1 or (len(fit) > 1 and fit[1][0] >= CLEAR * fit[0][0]):
                cands = fit
        if len(cands) > 1 and cands[1][0] < CLEAR * cands[0][0]:
            ambig.append((t["tag"], kind, cands))
            queue.append({"tag": t["tag"], "issue": f"{len(cands)} {kind}s beside the tag", "region": region}); continue
        seg = cands[0][1]
        if kind == "line" and not row["total"]:
            seg = span_for(seg, row["dist"], scale, chains)
        placed.append({"tag": t["tag"], "kind": kind, **{k: row[k] for k in ("az", "dist", "total", "R", "L", "delta") if k in row}, "line": shape(seg), "how": how})
        if kind == "line":
            drawn = seg["len_pt"] * scale
            dx, dy = seg["dir"][0], -seg["dir"][1]
            gx, gy = a * dx - bb * dy, bb * dx + a * dy
            az = math.degrees(math.atan2(gx, gy)) % 360
            dbrg = min(abs((az - row["az"] + 180) % 360 - 180), abs((az + 180 - row["az"] + 180) % 360 - 180))
            ok_b = dbrg <= max(BEAR_TOL, math.degrees(math.atan2(0.10, row["dist"])))  # a 6 ft line: 0.1 ft sideways is 1 deg
            out.append([t["tag"], "bearing", row["bearing"], fmt_bearing(az if abs((az - row["az"] + 180) % 360 - 180) < 90 else az + 180), f"{dbrg * 60:.1f}'", "pass" if ok_b else "FAIL", how])
            if row["total"]:
                out.append([t["tag"], "distance", f"{row['dist']:.2f}(T)", f"{drawn:.2f}", "", "total over several segments; not checked", how])
            else:
                ok_d = abs(drawn - row["dist"]) <= DIST_TOL + 0.0005 * row["dist"]
                out.append([t["tag"], "distance", f"{row['dist']:.2f}", f"{drawn:.2f}", f"{drawn - row['dist']:+.2f}", "pass" if ok_d else "FAIL", how])
                if not ok_d:
                    queue.append({"tag": t["tag"], "issue": f"drawn {drawn:.2f} ft vs table {row['dist']:.2f} ft", "region": region, "line": shape(seg)})
            if not ok_b:
                queue.append({"tag": t["tag"], "issue": f"drawn bearing off by {dbrg * 60:.1f} arcmin", "region": region, "line": shape(seg)})
        else:
            curve_hits.append((t, row, seg, how, region))

    # loop9 leg A rule 3: NO.-int -> the resolved (t, row, seg, how, region) hit for every curve tag that
    # found ITS OWN geometry (pass or fail; a tag still queued for want of a candidate at all carries no
    # entry) -- row_run's own "is this neighbour on my parent" test.
    tag_by_num = {}
    for hit in curve_hits:
        m = re.match(r"[LC](\d+)", hit[0]["tag"])
        if m:
            tag_by_num[int(m[1])] = hit

    # curves: leg8A -- grouped by PARENT curve (leg6A's parent + seq on every piece), not by the specific
    # piece a leader happened to land on. Each tag first gets its own chance to pass alone: its own
    # resolved piece, or -- leg6A's own search, `parent_window` -- a contiguous window of same-parent
    # pieces around it. Only tags that fail both join their parent's group, checked as a run: the drawn
    # length between the group's own outermost marks (every piece from the first tag's own piece to the
    # last, in seq order -- covering a record boundary between them that isn't itself separately drawn,
    # same as leg6A's standalone L=/(T) window) against the sum of the group's printed lengths.
    def emit_run(sub, drawn, ref_seg):
        nonlocal group_fires, row_run_fires
        if len(sub) < 2:
            for t, row, seg, how, region in sub:
                rr = row_run(t["tag"], seg, rows, tag_by_num, arcs, scale)
                if rr is not None:
                    keys, untagged, rdrawn, Ls, total, by_sum, span_pieces = rr
                    label = f"rows {', '.join(keys)}" + (f"; {', '.join(untagged)} untagged" if untagged else "")
                    sum_str = f"{rdrawn:.2f} = " + " + ".join(f"{v:.2f}" for v in Ls)
                    if by_sum:
                        out.append([t["tag"], "arc length", f"{row['L']:.2f}", sum_str, f"{rdrawn - total:+.2f}",
                                    f"pass as a run of {len(keys)} ({label}): the boundary between these arcs is not drawn", how])
                        row_run_fires += 1
                    else:
                        out.append([t["tag"], "arc length", f"{row['L']:.2f}", sum_str, f"{rdrawn - total:+.2f}", "FAIL", how])
                        queue.append({"tag": t["tag"], "issue": f"drawn run {rdrawn:.2f} ft vs row-run table total {total:.2f} ft ({label})", "region": region, "line": shape(span_pieces[-1])})
                    continue
                d = seg["len_pt"] * scale
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{d:.2f}", f"{d - row['L']:+.2f}", "FAIL", how])
                queue.append({"tag": t["tag"], "issue": f"drawn {d:.2f} ft vs table {row['L']:.2f} ft", "region": region, "line": shape(seg)})
            return
        Ls = [row["L"] for t, row, seg, how, region in sub]
        total, by_sum = run_sum(drawn, Ls)
        for t, row, seg, how, region in sub:
            if by_sum:
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{drawn:.2f} = {' + '.join(f'{x:.2f}' for x in Ls)}", f"{drawn - total:+.2f}",
                            f"pass as a run of {len(Ls)}: the boundary between these arcs is not drawn", how])
                group_fires += 1
            else:
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{drawn:.2f}", f"{drawn - row['L']:+.2f}", "FAIL", how])
                queue.append({"tag": t["tag"], "issue": f"drawn run {drawn:.2f} ft vs table {row['L']:.2f} ft (run holds {len(Ls)} tags summing {total:.2f})", "region": region, "line": shape(ref_seg)})

    row_run_fires = 0  # leg9A: tags that only passed as a run of consecutive table rows (some untagged)
    by_parent = {}
    for hit in curve_hits:
        by_parent.setdefault(hit[2]["parent"], []).append(hit)
    for group_hits in by_parent.values():
        remaining = []
        for t, row, seg, how, region in group_hits:
            drawn = seg["len_pt"] * scale
            sagitta = seg["len_pt"] ** 2 / (8 * row["R"] / scale)  # pt; a 46 ft arc on R=1470 bulges 0.1 pt: no radius in that
            ok_r = True
            if sagitta < 0.5:
                out.append([t["tag"], "radius", f"{row['R']:.2f}", "", "", f"arc too flat to measure a radius (sagitta {sagitta:.2f} pt); not checked", how])
            else:
                R = fit_radius(seg["pts"]) * scale
                ok_r = abs(R - row["R"]) <= RADIUS_TOL * row["R"]
                out.append([t["tag"], "radius", f"{row['R']:.2f}", f"{R:.2f}", f"{(R - row['R']) / row['R'] * 100:+.2f}%", "pass" if ok_r else "FAIL", how])
            if not ok_r:
                queue.append({"tag": t["tag"], "issue": f"fitted radius {R:.1f} ft vs table {row['R']:.2f} ft", "region": region, "line": shape(seg)})
            if row["total"]:  # a (T) total names this whole run itself, not a share of it: never grouped
                ok_t = abs(drawn - row["L"]) <= DIST_TOL + 0.0005 * row["L"]
                out.append([t["tag"], "arc length", f"{row['L']:.2f}(T)", f"{drawn:.2f}", f"{drawn - row['L']:+.2f}", "pass" if ok_t else "FAIL", how])
                if not ok_t:
                    queue.append({"tag": t["tag"], "issue": f"drawn run {drawn:.2f} ft vs table total {row['L']:.2f} ft", "region": region, "line": shape(seg)})
                continue
            ok_l = abs(drawn - row["L"]) <= DIST_TOL + 0.0005 * row["L"]
            if ok_l:
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{drawn:.2f}", f"{drawn - row['L']:+.2f}", "pass", how])
                continue
            window = parent_window(arcs, seg, row["L"], scale)
            if window is not None:
                wdrawn = sum(x["len_pt"] for x in window) * scale
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{wdrawn:.2f} = " + " + ".join(f"{x['len_pt'] * scale:.2f}" for x in window),
                            f"{wdrawn - row['L']:+.2f}", f"pass as a run of {len(window)}: the boundary within its own curve is not drawn", how])
                window_fires += 1
                continue
            remaining.append((t, row, seg, how, region))
        # pieces carrying "seq" (split_at's own cuts) span the outermost marks in seq order; a candidate
        # with no "seq" is the whole, unsplit curve -- never itself compound, so every tag resolving to
        # it already shares the identical object, and its own length already IS the group's span
        seqed = [h for h in remaining if "seq" in h[2]]
        whole = [h for h in remaining if "seq" not in h[2]]
        if whole:
            emit_run(whole, whole[0][2]["len_pt"] * scale, whole[0][2])
        if seqed:
            seqed.sort(key=lambda h: h[2]["seq"])
            lo, hi, parent = seqed[0][2]["seq"], seqed[-1][2]["seq"], seqed[0][2]["parent"]
            span_pieces = sorted((x for x in arcs if x.get("parent") == parent and "seq" in x and lo <= x["seq"] <= hi), key=lambda x: x["seq"])
            drawn = sum(x["len_pt"] for x in span_pieces) * scale
            emit_run(seqed, drawn, max(span_pieces, key=lambda x: x["len_pt"]))

    with open(OUT / "tags_checks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["tag", "check", "printed", "drawn", "difference", "result", "association"]); w.writerows(out)
    if "orderdiag" in ASSOC:  # how many ambiguous tags would table-order adjacency (tag n-1 / n+1 shares an endpoint) settle?
        ends = {}
        for pl in placed:
            P = pl["line"]; ends[pl["tag"].replace("(T)", "")] = (np.array(P[0], float), np.array(P[-1], float))
        for tag, kind, cands in ambig:
            m = re.match(r"([LC])(\d+)", tag)
            if not m:
                continue
            nb = [ends[k] for k in (f"{m[1]}{int(m[2]) - 1}", f"{m[1]}{int(m[2]) + 1}") if k in ends]
            def touch(s):
                P = s["pts"] if "pts" in s else np.array([s["p0"], s["p1"]])
                return any(np.hypot(*(P[i] - e)) < 3.0 for e0, e1 in nb for e in (e0, e1) for i in (0, -1))
            hit = [s for d, s in cands if touch(s)]
            print(f"   order: {tag} {len(cands)} candidates, neighbours placed {len(nb)}, touching a neighbour's end: {len(hit)}")
    (OUT / "tags_queue.json").write_text(json.dumps(queue, indent=1, ensure_ascii=False), encoding="utf-8")
    (OUT / "tag_labels.json").write_text(json.dumps(placed, ensure_ascii=False), encoding="utf-8")

    complete = [t for t in tags if "?" not in t["tag"]]
    assoc = {r[0] for r in out}
    print(f"tags read {len(tags)} ({len(complete)} complete, {len(tags) - len(complete)} partial) of {len(rows)} table rows | "
          f"associated {len(assoc)} ({sum(1 for r in out if r[6] == 'leader') // 2} by leader) | queued {len(queue)}")
    print(f"  leg8A: tick/stub resolution {tick_fires} | own-window pass {window_fires} | group-run pass {group_fires}")
    print(f"  leg9A: consecutive-row-run pass {row_run_fires}")
    for check in ("bearing", "distance", "radius", "arc length"):
        rs = [r for r in out if r[1] == check and (r[5] in ("pass", "FAIL") or r[5].startswith("pass as a run"))]
        print(f"  {check:11} checked {len(rs):3}  pass {sum(r[5].startswith('pass') for r in rs):3}  fail {sum(r[5] == 'FAIL' for r in rs):3}" + (f"  ({sum(r[5].startswith('pass as') for r in rs)} as a run)" if any(r[5].startswith('pass as') for r in rs) else ""))
    for r in out:
        if r[5] == "FAIL":
            print("   ", r)
    for q in queue:
        print("   queue:", q["tag"], "-", q["issue"])
    if len(assoc) < 0.5 * len(complete):
        print(f"WARNING: only {len(assoc)} of {len(complete)} read tags found their segment on this sheet (its leader convention may differ)")


if __name__ == "__main__":
    main()
