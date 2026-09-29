"""Loop17 leg H diagnostic: for each of the 50 "no R" census rows, is a radius printed ANYWHERE on the
sheet for this same physical curve (own drawn circle), and if so why didn't it attach? Classifies:
  A. own block IS "L=..." (entered checks.py's curve_blocks join scan) and a same-circle R=/A= block
     sits within the SAME reach test checks.py already uses -- but the label lost R anyway because the
     standalone-L= path (line ~1536) resolved it FIRST and marked it len_checked, so the later
     curve_blocks pass (line ~1984) skips re-attaching R to the already-placed label. BUG: read, not
     attached (checks.py root cause).
  B. own block is a BARE distance (no "L=" prefix) that only became an "arc" kind label via the
     DIST.match geometric fallback (~1845) -- this code path never even looks at RAD_TOK/curve_blocks,
     so an adjacent R= block, however close, is structurally invisible to it. BUG: not read (wrong code
     path), checks.py root cause.
  C. an R=/A= block sits on the sheet whose OWN fitted circle (from its own paired L, if any, or from
     the nearest curve geometrically) matches this row's circle within share_curve_radius's own
     tolerance, yet share_curve_radius (already run by census) did not borrow it -- means that R never
     became a donor EDGE at all (no label/tag carries it), so build_edges has nothing to share from.
     BUG: parsed but not associated (share_curve_radius has no donor to find).
  D. no R=/A= text found anywhere within a generous search radius of this curve's own drawn pts: R is
     genuinely not printed for this physical curve.
usage: python spike/legH17_noR_diag.py   (reads spike/out/legG17_census.json; needs checks/tables run once
                                            per sheet already -- same precondition as legG17_census.py)
"""
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

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

RAD_TOK = re.compile(r"(?<![A-Za-z0-9)])R=([\d,]{1,7}\.\d{2})'?")
SEARCH_PT = 400.0  # pt: generous search radius for "is R printed anywhere near this curve"


def diag_one(label):
    import pymupdf
    import traverse as tv
    from georef import OUT, PDF, READS, real_text_blocks
    from checks import normalize_quotes, fix_bearing_symbols

    g = json.loads((OUT / "georef.json").read_text())
    scale = g["scale_ft_per_pt"]
    page = pymupdf.open(PDF)[0]
    blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    normalize_quotes(blocks)
    fix_bearing_symbols(blocks)

    edges = tv.build_edges()
    for e in edges:
        e["impossible"] = bool(e["kind"] == "arc" and "L" in e
                                and e["L"] < float(np.hypot(*(e["p1"] - e["p0"]))) * scale * 0.98)
    n_shared = tv.share_curve_radius(edges, scale)

    def poly_dist_pt(pt, P):
        P = np.asarray(P, float)
        d = P - pt
        return float(np.min(np.hypot(d[:, 0], d[:, 1])))

    rows = []
    for e in edges:
        if e["kind"] != "arc" or e.get("impossible") or "R" in e:
            continue
        L = e.get("L")
        if L is None and "delta" in e and "R" in e:
            continue
        chord_ft = L if L is not None else float(np.hypot(*(e["p1"] - e["p0"]))) * scale
        pts = np.asarray(e["pts"], float)
        is_L_prefixed = bool(re.match(r"^L=", e["src"]))

        # nearest R= text block anywhere within SEARCH_PT of this curve's own drawn points
        best = None
        for b in blocks:
            m = RAD_TOK.search(b["text"].replace(" ", ""))
            if not m:
                continue
            bp = np.array([b["cx"], b["cy"]])
            d = poly_dist_pt(bp, pts)
            if d < SEARCH_PT and (best is None or d < best[0]):
                best = (d, float(m[1].replace(",", "")), b["text"], tuple(round(v, 1) for v in bp))

        rows.append({
            "sheet": label, "src": e["src"], "L": L, "chord_ft": round(chord_ft, 1),
            "is_L_prefixed": is_L_prefixed,
            "nearest_R_text": None if best is None else {"dist_pt": round(best[0], 1), "R": best[1], "text": best[2], "at": best[3]},
            "region": e.get("region"),
        })
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
from legH17_noR_diag import diag_one
rows, n_shared = diag_one("{label}")
print(json.dumps({{"rows": rows, "n_shared": n_shared}}))
"""
        r = subprocess.run([str(PY), "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
        if r.returncode:
            print(f"{label}: FAILED\n{r.stderr[-3000:]}")
            continue
        out_lines = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("{")]
        data = json.loads(out_lines[-1])
        print(f"{label}: {len(data['rows'])} no-R rows")
        all_rows.extend(data["rows"])

    (ROOT / "spike" / "out" / "legH17_noR_diag.json").write_text(json.dumps(all_rows, indent=1), encoding="utf-8")

    n_with_nearby_R = sum(1 for r in all_rows if r["nearest_R_text"] and r["nearest_R_text"]["dist_pt"] < 150)
    n_L = sum(1 for r in all_rows if r["is_L_prefixed"])
    print(f"\ntotal {len(all_rows)} rows; {n_L} are L=-prefixed; {n_with_nearby_R} have an R= text block within 150pt")
    for r in all_rows:
        nr = r["nearest_R_text"]
        nr_str = "-" if not nr else f"{nr['R']} @ {nr['dist_pt']:.0f}pt: {nr['text'][:40]!r}"
        print(f"{r['sheet']:10} {r['src']:18} {r['chord_ft']:7.1f} ft  L-pfx={r['is_L_prefixed']!s:5}  nearest R={nr_str}")


if __name__ == "__main__":
    main()
