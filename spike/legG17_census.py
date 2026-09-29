"""Loop17 leg G census: every arc row still flagged "chord direction from drawing" (or missing R/delta/L
outright) after the current traverse.py machinery (inherit_bearings, share_curve_radius,
complete_curve_chords) runs -- per row, which ingredient is missing and why, weighted by the row's own
record length (or drawn chord where no record length exists) as the ft-at-stake proxy for
recon_attrib.py's "curve" bucket.
usage: python spike/legG17_census.py   (six canonical sheets; needs checks.py/tables.py/tags.py/
                                          traverse.py already run once per sheet -- reads their JSON)
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
sys.path.insert(0, str(ROOT / "spike"))

SHEETS = {
    "presidio": None,
    "r10434_1": ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf",
    "r10434_3": ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf",
    "r10741_1": ROOT / "Sample Data" / "d4" / "r_10741_001_2017-02-10.pdf",
    "r10741_2": ROOT / "Sample Data" / "d4" / "r_10741_002_2017-02-10.pdf",
    "r10741_3": ROOT / "Sample Data" / "d4" / "r_10741_003_2017-02-10.pdf",
}


def census_one(label, pdf):
    """Runs in-process with SHEET already set by the caller (subprocess isolation, one per sheet --
    georef.py/OUT/PDF read the env var once at import time)."""
    import traverse as tv
    from georef import OUT

    g = json.loads((OUT / "georef.json").read_text())
    scale = g["scale_ft_per_pt"]

    def azimuth(p, q):
        d = q - p
        return math.degrees(math.atan2(d[0], -d[1])) % 360

    edges = tv.build_edges()
    for e in edges:
        e["impossible"] = bool(e["kind"] == "arc" and "L" in e
                                and e["L"] < float(np.hypot(*(e["p1"] - e["p0"]))) * scale * 0.98)

    ends = np.array([p for e in edges for p in (e["p0"], e["p1"])])
    possible = np.array([not edges[i // 2]["impossible"] for i in range(len(ends))])
    good_idx = np.nonzero(possible)[0]
    tree = cKDTree(ends[good_idx]) if len(good_idx) else None
    node_of = {}
    for gi, i in enumerate(good_idx):
        i = int(i)
        if i in node_of:
            continue
        for gj in tree.query_ball_point(ends[i], tv.NODE):
            node_of.setdefault(int(good_idx[gj]), i)
    for i in np.nonzero(~possible)[0]:
        node_of[int(i)] = int(i)

    adj = {}
    for k, e in enumerate(edges):
        n0, n1 = node_of[2 * k], node_of[2 * k + 1]
        e["n0"], e["n1"] = n0, n1
        adj.setdefault(n0, []).append(k); adj.setdefault(n1, []).append(k)
    gh = tv.sheet_glyph_h()
    impossible_nodes = {node_of[int(i)] for i in np.nonzero(~possible)[0]}
    loose = [n for n in adj if len(adj[n]) == 1 and n not in impossible_nodes]
    if loose:
        loose_pts = ends[loose]
        ltree = cKDTree(loose_pts)
        paired = set()
        cand = sorted(ltree.query_pairs(gh), key=lambda p: np.hypot(*(loose_pts[p[0]] - loose_pts[p[1]])))
        for i, j in cand:
            ni, nj = loose[i], loose[j]
            if ni in paired or nj in paired or ni == nj:
                continue
            paired.add(ni); paired.add(nj)
            lo, hi = min(ni, nj), max(ni, nj)
            for e in edges:
                if e["n0"] == hi:
                    e["n0"] = lo
                if e["n1"] == hi:
                    e["n1"] = lo
            adj[lo] = adj.pop(lo) + adj.pop(hi)

    tv.inherit_bearings(edges, adj)
    n_shared = tv.share_curve_radius(edges, scale)
    tv.complete_curve_chords(edges, adj, azimuth, tv.load_radials())

    # diagnose every arc row still missing "az" (or impossible)
    radials = tv.load_radials()
    by_node_pair = set()
    for m in edges:
        if m["kind"] == "line" and m.get("chord_label") and "az" in m:
            by_node_pair.add(frozenset((m["n0"], m["n1"])))

    def end_diag(e, end, node):
        arc_tan = tv.arc_end_tangent_az(e, end, azimuth)
        if arc_tan is None:
            return "own drawn pts too short to fit a tangent"
        lines = [m for j in adj.get(node, []) if (m := edges[j])["kind"] == "line" and not m.get("chord_label") and m is not e]
        if not lines:
            near_r = [r for r in radials if np.hypot(*(r["point"] - node)) < tv.NODE]
            if near_r:
                bad = []
                for r in near_r:
                    for cand_az in ((r["az"] + 90) % 360, (r["az"] - 90) % 360):
                        deflect = abs((cand_az - arc_tan + 180) % 360 - 180)
                        if deflect <= tv.TANGENT_TOL_DEG:
                            return None  # would have filled -- shouldn't reach here
                        bad.append(deflect)
                return f"radial at node but not tangent (best {min(bad):.1f} deg off, tol {tv.TANGENT_TOL_DEG})"
            return "no line or radial at this node (not shared)"
        tangent_lines, dirty_tangent, off_tangent = [], [], []
        for m in lines:
            other_end = m["p1"] if m["n0"] == node else m["p0"]
            own_end = m["p0"] if m["n0"] == node else m["p1"]
            line_leave_az = azimuth(own_end, other_end)
            deflect = abs(180 - abs((line_leave_az - arc_tan + 180) % 360 - 180))
            if deflect <= tv.TANGENT_TOL_DEG:
                (tangent_lines if "az" in m else dirty_tangent).append((deflect, m))
            else:
                off_tangent.append((deflect, m))
        if len(tangent_lines) >= 2:
            return f"{len(tangent_lines)} tangent record donors disagree at this node"
        if tangent_lines:
            return None  # this end resolves -- the OTHER end (or cross-end disagreement) is the blocker
        if dirty_tangent:
            d, m = min(dirty_tangent)
            return f"tangent donor '{m['src'][:40]}' geometrically clean ({d:.2f} deg off) but its own bearing is not record"
        d, m = min(off_tangent, key=lambda t: t[0])
        return f"nearest line '{m['src'][:40]}' at node not tangent ({d:.1f} deg off, tol {tv.TANGENT_TOL_DEG})"

    rows = []
    for e in edges:
        if e["kind"] != "arc" or e.get("impossible") or "az" in e:
            continue
        L = e.get("L")
        R = e.get("R")
        chord_ft = None
        if L is not None:
            chord_ft = L
        elif R is not None and "delta" in e:
            chord_ft = 2 * R * math.sin(math.radians(e["delta"]) / 2)
        if chord_ft is None:
            chord_ft = float(np.hypot(*(e["p1"] - e["p0"]))) * scale

        if "R" not in e:
            reason = "no R (radius)"
        elif "delta" not in e and "L" not in e:
            reason = "no delta/L"
        elif "delta" in e and "L" in e and abs(e["delta"] - math.degrees(e["L"] / e["R"])) > tv.DELTA_CONSISTENCY_TOL_DEG:
            reason = f"delta/L self-inconsistent ({e['delta']:.2f} vs {math.degrees(e['L'] / e['R']):.2f} deg implied)"
        elif frozenset((e["n0"], e["n1"])) in by_node_pair:
            reason = "CB present but somehow unfilled (bug)"
        else:
            d0 = end_diag(e, 0, e["n0"])
            d1 = end_diag(e, 1, e["n1"])
            if d0 is None and d1 is None:
                reason = "both ends resolve but disagree beyond 2x tangent tol"
            elif d0 is None:
                reason = f"end1 (n1): {d1}"
            elif d1 is None:
                reason = f"end0 (n0): {d0}"
            elif d0 == d1:
                reason = f"both ends: {d0}"
            else:
                reason = f"end0: {d0} | end1: {d1}"

        rows.append({"sheet": label, "src": e["src"], "R": R, "delta": e.get("delta"), "L": L,
                     "chord_ft": round(chord_ft, 1), "reason": reason})
    return rows, n_shared


def main():
    all_rows = []
    for label, pdf in SHEETS.items():
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        if pdf:
            env["SHEET"] = str(pdf)
        else:
            env.pop("SHEET", None)
        script = f"""
import sys
sys.path.insert(0, r"{ROOT / 'spike'}")
import json
from legG17_census import census_one
rows, n_shared = census_one("{label}", None)
print(json.dumps({{"rows": rows, "n_shared": n_shared}}))
"""
        r = subprocess.run([str(PY), "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
        if r.returncode:
            print(f"{label}: FAILED\n{r.stderr[-3000:]}")
            continue
        out_lines = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("{")]
        data = json.loads(out_lines[-1])
        print(f"{label}: {len(data['rows'])} arc rows still blocked, {data['n_shared']} radius-shared this run")
        all_rows.extend(data["rows"])

    (ROOT / "spike" / "out" / "legG17_census.json").write_text(json.dumps(all_rows, indent=1), encoding="utf-8")

    # tabulate by top-level reason bucket, ft-weighted
    def bucket(reason):
        if reason.startswith("no R"):
            return "no R"
        if reason.startswith("no delta/L"):
            return "no delta/L"
        if "self-inconsistent" in reason:
            return "delta/L self-inconsistent"
        if "not shared" in reason or "no line or radial" in reason:
            return "node not shared (no line/radial at node)"
        if "not tangent" in reason:
            return "line/radial at node but not tangent"
        if "not record" in reason:
            return "tangent donor exists but not clean (drawing bearing)"
        if "disagree" in reason:
            return "donors disagree (ambiguous, refused)"
        if "too short" in reason:
            return "own pts too short for tangent fit"
        return "other: " + reason[:50]

    from collections import defaultdict
    buckets = defaultdict(float)
    counts = defaultdict(int)
    for row in all_rows:
        b = bucket(row["reason"])
        buckets[b] += row["chord_ft"]
        counts[b] += 1
    print("\n=== census: blocker bucket -> ft (row count) ===")
    for b, ft in sorted(buckets.items(), key=lambda kv: -kv[1]):
        print(f"{ft:8.1f} ft  ({counts[b]:3} rows)  {b}")
    print(f"\ntotal blocked: {sum(buckets.values()):.1f} ft across {len(all_rows)} rows")


if __name__ == "__main__":
    main()
