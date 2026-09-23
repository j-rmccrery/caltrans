"""Generalisation: run alphabet -> tags -> tables -> checks on every sheet with a credible georeference
and summarise from the files each step writes. Writes spike/out/sheets.csv.
usage: python spike/sheets.py [--run]   (without --run: summarise what is already there)
"""
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).parent / "out"
PY = sys.executable
SMALL = {"distance": 5.0, "arc length": 5.0, "bearing": 60.0}


def sheets():
    """Every vector sheet on disk (--all), else the ones with a credible fit already."""
    import pymupdf
    pdfs = list((ROOT / "Sample Data" / "d4").glob("*.pdf")) + list((ROOT / "Sample Data" / "Right-of-Way Map Record").glob("r_10434_00[13]*.pdf"))
    for pdf in sorted(pdfs):
        if "--all" in sys.argv:
            try:
                page = pymupdf.open(pdf)[0]
            except Exception:
                continue
            if len(page.get_drawings()) < 200 and page.get_images():
                continue  # a scan: not this chain
            yield pdf
            continue
        g = OUT / pdf.stem / "georef.json"
        if g.exists() and json.loads(g.read_text()).get("credible"):
            yield pdf


def run(pdf, step):
    r = subprocess.run([PY, str(Path(__file__).parent / step)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "SHEET": str(pdf), "PYTHONIOENCODING": "utf-8"})
    last = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip()][-1:]
    return r.returncode == 0, (last[0][:100] if last else "")


def summarise(pdf):
    o = OUT / pdf.stem
    row = {"sheet": pdf.stem}
    g = o / "georef.json"
    row["georef"] = ("credible" if json.loads(g.read_text()).get("credible") else "refused") if g.exists() else "-"
    if (o / "alphabet.npz").exists():
        import numpy as np
        z = np.load(o / "alphabet.npz"); row["alphabet"] = len(z["Y"]); row["chars"] = "".join(sorted(set(z["Y"].tolist())))
    if (o / "tables.json").exists():
        t = json.loads((o / "tables.json").read_text(encoding="utf-8"))
        t = {k: v for k, v in t.items() if not k.startswith("_")}
        row["table_rows"] = len(t); row["rows_clean"] = sum(1 for r in t.values() if r["cells"] and not any("?" in c for c in r["cells"][:3]))
    if (o / "tags.json").exists():
        t = json.loads((o / "tags.json").read_text(encoding="utf-8"))
        row["tags"] = sum(1 for x in t if "?" not in x["tag"]); row["tags_partial"] = sum(1 for x in t if "?" in x["tag"])
    if (o / "tags_checks.csv").exists():
        rs = list(csv.DictReader(open(o / "tags_checks.csv", encoding="utf-8")))
        row["tag_assoc"] = len({r["tag"] for r in rs})
        row["tag_pass"] = sum(1 for r in rs if r["result"].startswith("pass")); row["tag_fail"] = sum(1 for r in rs if r["result"] == "FAIL")
    if (o / "checks.csv").exists():
        rs = list(csv.DictReader(open(o / "checks.csv", encoding="utf-8")))
        for k in ("distance", "bearing", "arc length"):
            n = sum(1 for r in rs if r["check"] == k and r["result"] in ("pass", "FAIL")); ok = sum(1 for r in rs if r["check"] == k and r["result"] == "pass")
            row[k.replace(" ", "_")] = f"{ok}/{n}"
    if (o / "exceptions.json").exists():
        e = json.loads((o / "exceptions.json").read_text(encoding="utf-8"))
        row["exceptions"] = len(e)
        row["wrong_line"] = sum(1 for x in e if "issue" not in x and abs(x.get("off_ft", x.get("off_arcmin", 0))) > SMALL.get(x["kind"], 1e9))
    return row


def main():
    rows = []
    for pdf in sheets():
        if "--run" in sys.argv and not ("--missing" in sys.argv and (OUT / pdf.stem / "checks.csv").exists()):
            steps = ("frame.py", "alphabet.py", "read_glyphs.py", "solve.py", "tags.py", "tables.py", "checks.py")
            if "--all" in sys.argv and not (OUT / pdf.stem / "blocks.json").exists():
                steps = ("blocks.py",) + steps
            for step in steps:
                ok, last = run(pdf, step)
                print(f"{pdf.stem[:26]:26} {step:12} {'ok' if ok else 'FAILED'}  {last}")
                if not ok:
                    break
        rows.append(summarise(pdf))
    keys = ["sheet", "georef", "alphabet", "chars", "table_rows", "rows_clean", "tags", "tags_partial", "tag_assoc", "tag_pass", "tag_fail", "distance", "bearing", "arc_length", "exceptions", "wrong_line"]
    with open(OUT / "sheets.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    for r in rows:
        print(" | ".join(f"{k} {r.get(k, '-')}" for k in keys if k != "chars"))


if __name__ == "__main__":
    main()
