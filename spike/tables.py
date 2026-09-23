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
from checks import BEAR_TOL, DIST_TOL, arcs_on_sheet, azimuth, fmt_bearing, leaders, lines_on_sheet, linework_segments, poly_dist, seg_dist, span_for, split_at, split_chains, tag_leaders  # noqa: E402
from georef import OUT, PDF, segments  # noqa: E402
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

    paths, leader_pids = leaders(page)
    # black lines of any weight (the alignment curves C9-C14 are 0.36 pt), minus the leaders, which share
    # the lettering weight; a leader tip may land on any of them, a tag with no leader only on a heavy one
    segs = [s for s in linework_segments(page, max_gray=0.2) if s[3] not in leader_pids]
    _, circles = segments(page)
    chains = [c for c in lines_on_sheet(segs, circles) if c["len_pt"] >= 1 and not (c["width"] < BOUNDARY and c["len_pt"] < 9)]  # thin stubs are stationing ticks
    chains = split_chains(chains, circles)  # pieces between breaks; a tag's span is chosen among them by the table's distance
    junction_lines = [c for c in chains if c["len_pt"] >= 20]  # boundary lines of any weight; ticks are handled apart
    # short thin perpendicular strokes: radial ticks on the thin alignment curves mark where an arc ends
    ticks = np.array([(s0 + s1) / 2 for s0, s1, w, _ in linework_segments(page, max_gray=0.2) if w < BOUNDARY and 5 < np.hypot(*(s1 - s0)) < 9]).reshape(-1, 2)
    arcs = []
    for arc in arcs_on_sheet(page):
        if max(arc.get("color", (0,))) < 0.2 and np.hypot(*(arc["pts"][0] - arc["pts"][-1])) > 2:  # not a point-symbol circle
            arcs.append({"pts": arc["pts"], "len_pt": arc["len_pt"], "width": arc["width"]})
    for c in lines_on_sheet(segs, circles, max_turn_deg=20.0):  # R=60 ft curves turn 7 deg per facet
        if c["n"] >= 3 and c["len_pt"] > 12:
            for P in split_at(c["pts"], circles, junction_lines, ticks=ticks if c["width"] < BOUNDARY else ()):
                arcs.append({"pts": P, "len_pt": float(np.sum(np.hypot(*np.diff(P, axis=0).T))), "width": c["width"]})

    def along(seg, pt):
        """Unit direction of a chain, or of the arc facet nearest pt."""
        if "dir" in seg:
            return seg["dir"]
        P = seg["pts"]
        k = int(np.hypot(*(P - pt).T).argmin())
        v = P[min(k + 1, len(P) - 1)] - P[max(k - 1, 0)]
        return v / max(np.hypot(*v), 1e-9)

    def candidates(kind, pt, radius, min_width=0.0, arrow=None):
        pool = [ln for ln in chains if ln["width"] >= min_width] if kind == "line" else [arc for arc in arcs if arc["width"] >= min_width]
        dist = (lambda s: seg_dist(pt, s["p0"], s["p1"])) if kind == "line" else (lambda s: poly_dist(pt, s["pts"]))
        found = sorted(((dist(s), s) for s in pool if dist(s) < radius), key=lambda t: t[0])
        if arrow is not None:  # an arrow points across the line it means, not along it: a stationing tick lies along the arrow
            found = [(d, s) for d, s in found if abs(along(s, pt) @ arrow) < math.cos(math.radians(30))]
        return found

    tips = tag_leaders(tags, paths)
    out, queue, curve_hits = [], [], []
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
            tip, arrow = tip
            cands = candidates(kind, tip, 4.0)  # ponytail: no arrow-direction test; a tag at a line's end gets its arrow along the line
            how = "leader"
            if not cands:
                queue.append({"tag": t["tag"], "issue": f"leader points at no {kind}", "region": region}); continue
        else:
            cands = candidates(kind, np.array([t["cx"], t["cy"]]), BESIDE * gh, BOUNDARY)
        if not cands:
            queue.append({"tag": t["tag"], "issue": f"no leader, no {kind} beside the tag", "region": region}); continue
        if len(cands) > 1 and cands[1][0] < CLEAR * cands[0][0]:
            queue.append({"tag": t["tag"], "issue": f"{len(cands)} {kind}s beside the tag", "region": region}); continue
        seg = cands[0][1]
        if kind == "line" and not row["total"]:
            seg = span_for(seg, row["dist"], scale, chains)
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

    # curves: a drawn run between junctions may hold several record arcs whose boundary is not drawn;
    # a tag passes on its own length, or all tags on the run pass together when the run equals their sum
    by_run = {}
    for hit in curve_hits:
        by_run.setdefault(id(hit[2]), []).append(hit)
    for hits in by_run.values():
        seg = hits[0][2]
        drawn = seg["len_pt"] * scale
        Ls = [h[1]["L"] for h in hits if not h[1]["total"]]
        total = sum(Ls)
        by_sum = len(Ls) > 1 and abs(drawn - total) <= DIST_TOL + 0.0005 * total
        for t, row, seg, how, region in hits:
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
            if row["total"]:
                ok_t = abs(drawn - row["L"]) <= DIST_TOL + 0.0005 * row["L"]
                out.append([t["tag"], "arc length", f"{row['L']:.2f}(T)", f"{drawn:.2f}", f"{drawn - row['L']:+.2f}", "pass" if ok_t else "FAIL", how])
                if not ok_t:
                    queue.append({"tag": t["tag"], "issue": f"drawn run {drawn:.2f} ft vs table total {row['L']:.2f} ft", "region": region, "line": shape(seg)})
                continue
            ok_l = abs(drawn - row["L"]) <= DIST_TOL + 0.0005 * row["L"]
            if ok_l:
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{drawn:.2f}", f"{drawn - row['L']:+.2f}", "pass", how])
            elif by_sum:
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{drawn:.2f} = {' + '.join(f'{x:.2f}' for x in Ls)}", f"{drawn - total:+.2f}",
                            f"pass as a run of {len(Ls)}: the boundary between these arcs is not drawn", how])
            else:
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{drawn:.2f}", f"{drawn - row['L']:+.2f}", "FAIL", how])
                queue.append({"tag": t["tag"], "issue": f"drawn run {drawn:.2f} ft vs table {row['L']:.2f} ft" + (f" (run holds {len(Ls)} arcs summing {total:.2f})" if len(Ls) > 1 else ""), "region": region, "line": shape(seg)})

    with open(OUT / "tags_checks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["tag", "check", "printed", "drawn", "difference", "result", "association"]); w.writerows(out)
    (OUT / "tags_queue.json").write_text(json.dumps(queue, indent=1, ensure_ascii=False), encoding="utf-8")

    complete = [t for t in tags if "?" not in t["tag"]]
    assoc = {r[0] for r in out}
    print(f"tags read {len(tags)} ({len(complete)} complete, {len(tags) - len(complete)} partial) of {len(rows)} table rows | "
          f"associated {len(assoc)} ({sum(1 for r in out if r[6] == 'leader') // 2} by leader) | queued {len(queue)}")
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
