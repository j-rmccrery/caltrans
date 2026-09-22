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
from checks import BEAR_TOL, DIST_TOL, arcs_on_sheet, azimuth, fmt_bearing, lines_on_sheet, linework_segments  # noqa: E402
from georef import OUT, PDF, segments  # noqa: E402
from gt import TABLES  # noqa: E402

RADIUS_TOL = 0.01  # fraction: a polyline arc's fitted radius vs the printed one
BESIDE = 2.5       # glyph heights: how far from the tag a segment may sit to be "beside" it
CLEAR = 1.5        # the nearest candidate must be this many times closer than the next, else ambiguous
BOUNDARY = 0.8     # pt: R/W lines are 1.98, parcel and easement lines 0.84; hatch and ticks are 0.36-0.42


def leaders(page):
    """Leaders: thin stroked paths (this drafter's are curly, 15-30 pt, the same 1.02 weight as the
    lettering) that end at a filled arrowhead triangle. (start, arrowhead) pairs."""
    heads, paths = [], []
    for pid, d in enumerate(page.get_drawings()):
        c, w = d.get("color"), round(d.get("width") or 0, 2)
        if c is None or max(c) > 0.6:
            continue
        r = d["rect"]
        if d["type"] in ("f", "fs") and len(d["items"]) == 3 and max(r.width, r.height) < 12:
            heads.append(np.array([[it[1].x, it[1].y] for it in d["items"]]))  # the triangle's corners
        elif d["type"] == "s" and 0 < w < 1.1:
            items = [it for it in d["items"] if it[0] in ("l", "c")]
            if items:
                pts = [np.array([it[1].x, it[1].y]) for it in items] + [np.array([items[-1][-1].x, items[-1][-1].y])]
                paths.append((pts[0], pts[-1], sum(np.hypot(*(q - p)) for p, q in zip(pts, pts[1:])), pid))
    if not heads:
        return [], set()
    tree = cKDTree(np.array([h.mean(0) for h in heads]))
    out, pids = [], set()
    for p0, p1, total, pid in paths:
        if not 8 < total < 120:
            continue
        for start, end in ((p0, p1), (p1, p0)):
            dist, j = tree.query(end)
            if dist < 7:  # the leader stops at the triangle's base; the tip is the corner farthest from it
                tip = heads[j][int(np.hypot(*(heads[j] - end).T).argmax())]
                v = tip - heads[j].mean(0)
                out.append((start, tip, v / max(np.hypot(*v), 1e-9))); pids.add(pid)
    return out, pids


def tag_leaders(tags, paths):
    """Each leader to the one tag whose box its start is nearest (stacked tags L4/L5/L7 share a
    neighbourhood; a leader is claimed once). {tag index: arrowhead tip}."""
    pairs = []
    for k, t in enumerate(tags):
        gh = t["gh"]
        c = np.array([t["cx"], t["cy"]])
        th = np.radians(t["angle"])
        u, n = np.array([np.cos(th), np.sin(th)]), np.array([-np.sin(th), np.cos(th)])
        hw, hh = 0.45 * gh * len(t["tag"]) + 0.3 * gh, 0.7 * gh

        def outside(p):  # distance from the tag's box, 0 inside
            d = p - c
            return float(np.hypot(max(abs(d @ u) - hw, 0), max(abs(d @ n) - hh, 0)))
        for j, (start, head, _) in enumerate(paths):
            dn = outside(start)
            if dn < 1.5 * gh and outside(head) > dn:
                pairs.append((dn, k, j))
    out, taken = {}, set()
    for dn, k, j in sorted(pairs):
        if k not in out and j not in taken:
            out[k] = paths[j][1:]; taken.add(j)
    return out


def table_rows():
    """{tag: {...}} from the keyed tables; (T) marks a total over several segments."""
    rows = {}
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


def split_at(P, circles, chains, tol=2.0):
    """A curved chain runs on through its tangent points; a vertex circle, or a line meeting the curve at
    an angle (ending on it or crossing it), marks where one table arc ends (C15, C16 and C18 share one
    drawn curve of R=1470). The cut is the exact meeting point, not the nearest facet vertex. A line
    that continues the curve's own direction is one of its pieces."""
    A = np.array([c["p0"] for c in chains]); B = np.array([c["p1"] for c in chains])
    D = np.array([c["dir"] for c in chains]); LN = np.hypot(*(B - A).T)
    ctree = cKDTree(circles) if len(circles) else None
    sin10 = math.sin(math.radians(10))
    pts, cut = [P[0]], [True]
    for i in range(len(P) - 1):
        p, q = P[i], P[i + 1]
        t = q - p
        L = max(np.hypot(*t), 1e-9); t = t / L
        # lines meeting this facet (extended by tol so a line ending on the curve counts): p + s t = a + r d
        den = t[0] * D[:, 1] - t[1] * D[:, 0]
        ok = np.abs(den) > sin10
        ap = A - p
        s = np.where(ok, (ap[:, 0] * D[:, 1] - ap[:, 1] * D[:, 0]) / np.where(ok, den, 1), -1)
        r = np.where(ok, (ap[:, 0] * t[1] - ap[:, 1] * t[0]) / np.where(ok, den, 1), -1)
        for sk in sorted(s[ok & (s > 0.3) & (s < L - 0.3) & (r > -tol) & (r < LN + tol)]):
            pts.append(p + sk * t); cut.append(True)
        pts.append(q)
        cut.append(bool(ctree is not None and ctree.query(q)[0] < 2 * tol))
    cut[-1] = True
    pieces, start = [], 0
    for i in range(1, len(pts)):
        if cut[i]:
            pieces.append(np.array(pts[start:i + 1]))  # one facet is still an arc: C18 is 6 ft on R=1470
            start = i
    return pieces


def shape(seg):
    """The drawn line or arc a check measured, as points (pt), for the exception page."""
    P = seg["pts"][:: max(1, len(seg["pts"]) // 20)] if "pts" in seg else [seg["p0"], seg["p1"]]
    return [[round(float(x), 1), round(float(y), 1)] for x, y in P]


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(ab @ ab, 1e-9), 0, 1)
    return float(np.hypot(*(p - (a + t * ab))))


def poly_dist(p, P):
    """Distance from p to a polyline (its segments, not just its vertices: R/W curves are 15-40 pt facets)."""
    A, B = P[:-1], P[1:]
    AB = B - A
    t = np.clip(((p - A) * AB).sum(1) / np.maximum((AB * AB).sum(1), 1e-9), 0, 1)
    return float(np.hypot(*(p - (A + t[:, None] * AB)).T).min())


def main():
    page = pymupdf.open(PDF)[0]
    g = json.loads((OUT / "georef.json").read_text())
    a, bb = g["params"][:2]
    scale = float(np.hypot(a, bb))
    tags = json.loads((OUT / "tags.json").read_text(encoding="utf-8"))
    rows = table_rows()

    paths, leader_pids = leaders(page)
    # black lines of any weight (the alignment curves C9-C14 are 0.36 pt), minus the leaders, which share
    # the lettering weight; a leader tip may land on any of them, a tag with no leader only on a heavy one
    segs = [s for s in linework_segments(page, max_gray=0.2) if s[3] not in leader_pids]
    _, circles = segments(page)
    chains = [c for c in lines_on_sheet(segs, circles) if c["len_pt"] >= 1 and not (c["width"] < BOUNDARY and c["len_pt"] < 9)]  # thin stubs are stationing ticks
    junction_lines = [c for c in chains if c["len_pt"] >= 9]  # any weight: the thin radials end the alignment arcs
    arcs = []
    for arc in arcs_on_sheet(page):
        if max(arc.get("color", (0,))) < 0.2 and np.hypot(*(arc["pts"][0] - arc["pts"][-1])) > 2:  # not a point-symbol circle
            arcs.append({"pts": arc["pts"], "len_pt": arc["len_pt"], "width": arc["width"]})
    for c in lines_on_sheet(segs, circles, max_turn_deg=20.0):  # R=60 ft curves turn 7 deg per facet
        if c["n"] >= 3 and c["len_pt"] > 12:
            for P in split_at(c["pts"], circles, junction_lines):
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
    out, queue = [], []
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
            drawn = seg["len_pt"] * scale
            sagitta = seg["len_pt"] ** 2 / (8 * row["R"] / scale)  # pt; a 46 ft arc on R=1470 bulges 0.1 pt: no radius in that
            ok_r = True
            if sagitta < 0.5:
                out.append([t["tag"], "radius", f"{row['R']:.2f}", "", "", f"arc too flat to measure a radius (sagitta {sagitta:.2f} pt); not checked", how])
            else:
                R = fit_radius(seg["pts"]) * scale
                ok_r = abs(R - row["R"]) <= RADIUS_TOL * row["R"]
                out.append([t["tag"], "radius", f"{row['R']:.2f}", f"{R:.2f}", f"{(R - row['R']) / row['R'] * 100:+.2f}%", "pass" if ok_r else "FAIL", how])
            if row["total"]:
                out.append([t["tag"], "arc length", f"{row['L']:.2f}(T)", f"{drawn:.2f}", "", "total over several segments; not checked", how])
            else:
                ok_l = abs(drawn - row["L"]) <= DIST_TOL + 0.0005 * row["L"]
                out.append([t["tag"], "arc length", f"{row['L']:.2f}", f"{drawn:.2f}", f"{drawn - row['L']:+.2f}", "pass" if ok_l else "FAIL", how])
                if not ok_l:
                    queue.append({"tag": t["tag"], "issue": f"drawn arc {drawn:.2f} ft vs table {row['L']:.2f} ft", "region": region, "line": shape(seg)})
            if not ok_r:
                queue.append({"tag": t["tag"], "issue": f"fitted radius {R:.1f} ft vs table {row['R']:.2f} ft", "region": region, "line": shape(seg)})

    with open(OUT / "tags_checks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["tag", "check", "printed", "drawn", "difference", "result", "association"]); w.writerows(out)
    (OUT / "tags_queue.json").write_text(json.dumps(queue, indent=1, ensure_ascii=False), encoding="utf-8")

    complete = [t for t in tags if "?" not in t["tag"]]
    assoc = {r[0] for r in out}
    print(f"tags read {len(tags)} ({len(complete)} complete, {len(tags) - len(complete)} partial) of {len(rows)} table rows | "
          f"associated {len(assoc)} ({sum(1 for r in out if r[6] == 'leader') // 2} by leader) | queued {len(queue)}")
    for check in ("bearing", "distance", "radius", "arc length"):
        rs = [r for r in out if r[1] == check and r[5] in ("pass", "FAIL")]
        print(f"  {check:11} checked {len(rs):3}  pass {sum(r[5] == 'pass' for r in rs):3}  fail {sum(r[5] == 'FAIL' for r in rs):3}")
    for r in out:
        if r[5] == "FAIL":
            print("   ", r)
    for q in queue:
        print("   queue:", q["tag"], "-", q["issue"])
    assert len(assoc) >= 0.5 * len(complete), "association is broken: under half the read tags found their segment"


if __name__ == "__main__":
    main()
