"""Generalisation check: run the unchanged pipeline on unrelated District 4 record maps.

Picks recent (CAD-era) Record maps from the public D4 index, spread over counties and routes,
downloads them, keeps the vector ones, runs blocks -> ocr -> georef, writes spike/out/batch.csv.
"""
import csv
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
D4 = ROOT / "Sample Data" / "d4"
OUT = Path(__file__).parent / "out"
INDEX = "https://services1.arcgis.com/8CpMUd3fdw6aXef7/arcgis/rest/services/MapIndexMOD/FeatureServer/1/query"
N = 8


def candidates():
    q = urllib.parse.urlencode({
        "where": "maptype='Record' AND mapyear >= '2012' AND sheetlabel NOT LIKE 'R-10434%'",
        "outFields": "name,sheetlabel,county,route,mapyear,image_web_link_public", "returnGeometry": "false",
        "orderByFields": "name", "f": "json"})
    feats = json.load(urllib.request.urlopen(f"{INDEX}?{q}", timeout=60))["features"]
    seen, picks = set(), []
    for f in feats:  # one sheet per county+route so the sample is spread out
        a = f["attributes"]
        key = (a["county"], a["route"])
        m = re.search(r'href="(.*?)"', a["image_web_link_public"] or "")
        if key in seen or not m:
            continue
        seen.add(key)
        picks.append((a["sheetlabel"], a["county"], a["route"], a["mapyear"], m[1]))
    return picks


def scan_row(label, county, route, year, paths, pdf, py, env):
    """A non-vector (scanned) sheet: read text-boxes with the PP-OCRv5-server detector
    (spike/scan_read_v5.py), one process per sheet, falling back to the old RapidOCR-1.4.4
    detector (spike/scan_read.py, slower: tiled OCR + a per-box vision-model second read) if
    v5 fails or writes no boxes. Then spike/scan_consensus.py votes/merges the two reads into
    read_scan.json (or read_scan_rapid.json on the fallback path)."""
    log = ""
    r = subprocess.run([py, str(Path(__file__).parent / "scan_read_v5.py")], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log += r.stdout + r.stderr
    v5_json = OUT / pdf.stem / "read_v5.json"
    v5_ok = r.returncode == 0 and v5_json.exists() and json.loads(v5_json.read_text(encoding="utf-8"))
    if not v5_ok:
        print(f"{label}: scan_read_v5.py failed or found no boxes, falling back to scan_read.py (RapidOCR-1.4.4)")
        r = subprocess.run([py, str(Path(__file__).parent / "scan_read.py")], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log += r.stdout + r.stderr
    r = subprocess.run([py, str(Path(__file__).parent / "scan_consensus.py")], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log += r.stdout + r.stderr
    m = re.search(r"\{'agree': (\d+), 'repaired': (\d+), 'queue': (\d+)\}", log)
    (OUT / pdf.stem).mkdir(parents=True, exist_ok=True)
    (OUT / pdf.stem / "log.txt").write_text(log, encoding="utf-8")
    return {"sheet": label, "county": county, "route": route, "year": year, "vector_paths": paths, "kind": "scan",
            "reader": "v5" if v5_ok else "rapid", "agree": m[1] if m else "", "repaired": m[2] if m else "", "queue": m[3] if m else ""}


def main():
    D4.mkdir(parents=True, exist_ok=True)
    rows, py = [], sys.executable
    for label, county, route, year, url in candidates():
        if len(rows) >= N:
            break
        pdf = D4 / url.rsplit("/", 1)[1]
        if not pdf.exists():
            try:
                pdf.write_bytes(urllib.request.urlopen(url, timeout=180).read())
            except Exception as e:
                print(label, "download failed:", e); continue
        page = pymupdf.open(pdf)[0]
        paths = len(page.get_drawings())
        env = dict(os.environ, SHEET=str(pdf), PYTHONIOENCODING="utf-8")
        if paths < 3000 or page.get_images():
            rows.append(scan_row(label, county, route, year, paths, pdf, py, env))
            print(rows[-1], flush=True)
            continue
        log = ""
        for script, args in (("blocks.py", []), ("ocr.py", ["rapid"]), ("georef.py", [])):
            r = subprocess.run([py, str(Path(__file__).parent / script), *args], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            log += r.stdout + r.stderr
        g = lambda pat: (re.search(pat, log) or [None, ""])[1]
        rows.append({"sheet": label, "county": county, "route": route, "year": year, "vector_paths": paths, "kind": "vector",
                     "blocks": g(r"\| blocks (\d+)"), "callouts": g(r"callouts paired (\d+)"), "traced": g(r"leaders traced (\d+)"),
                     "fit_on": g(r"fit on (\d+/\d+)"), "scale_ft_per_pt": g(r"scale ([\d.]+) ft/pt"), "rotation_deg": g(r"rotation ([-\d.]+) deg"),
                     "rms_ft": g(r"rms ([\d.]+)"), "max_ft": g(r"max ([\d.]+)"), "credible": "no" if "not credible" in log or not g(r"rms ([\d.]+)") else "yes"})
        print(rows[-1], flush=True)
        (OUT / pdf.stem).mkdir(parents=True, exist_ok=True)
        (OUT / pdf.stem / "log.txt").write_text(log, encoding="utf-8")
    if not rows:
        print("done: 0 sheets"); return
    fieldnames = sorted({k for r in rows for k in r})  # vector and scan rows carry different columns
    with open(OUT / "batch.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, restval=""); w.writeheader(); w.writerows(rows)
    print("done:", len(rows), "sheets")


if __name__ == "__main__":
    main()
