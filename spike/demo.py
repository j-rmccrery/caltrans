"""One command, offline: the whole Presidio pipeline, timed per step.

    python spike/demo.py            # everything
    python spike/demo.py --fast     # skip the OCR pass (reuses spike/out/read_rapid.json)
    python spike/demo.py --six      # also run the other five sheets' tails + the six-sheet QGIS project
    python spike/demo.py --fast --six

Order matters: blocks -> ocr -> solve -> overlay -> parcels -> checks -> tags -> tables -> traverse -> extract -> encroach -> rasters -> objects.
The LiDAR intensity cache (spike/lidar/cache) comes from spike/lidar/q2_terrain_check.py once.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PY = sys.executable
STEPS = [
    ("text blocks", ["blocks.py"]),
    ("read text (SHX annotations)", ["read_shx.py"]),
    ("sheet frame", ["frame.py"]),
    ("sheet alphabet + tables", ["alphabet.py"]),
    ("tables from annotations", ["read_shx.py", "--tables"]),  # last writer of tables.json where the sheet has SHX text; the bench does the same
    ("read text by glyph", ["read_glyphs.py"]),
    ("read text (OCR)", ["ocr.py", "rapid"]),
    ("georeference", ["solve.py"]),
    ("linework on LiDAR", ["overlay.py"]),
    ("parcels", ["parcels.py"]),
    ("checks + exception queue", ["checks.py"]),
    ("segment tags", ["tags.py"]),
    ("table checks via tags", ["tables.py"]),
    ("record twin (traverse)", ["traverse.py"]),
    ("record self-checks", ["record_checks.py"]),  # alignment tables vs fit, table L=R*Delta, cell counts (all six sheets)
    ("matchline check", ["matchline.py"]),          # same-line agreement across adjacent sheets (all six, loop 12)
    ("LiDAR features", ["lidar/extract.py"]),
    ("highway surface", ["lidar/surface.py"]),      # per-tile pavement+deck dissolve inside R/W (south/north/gap, loop 11)
    ("encroachment", ["encroach.py"]),
    ("rasters for QGIS", ["export_rasters.py"]),
    ("object record", ["objects.py"]),
    ("exception page", ["exceptions_page.py"]),
    ("QGIS project", ["qgis_project.py"]),  # runs under QGIS's own Python, see QGIS_PY
    ("figures", ["figures.py"]),            # same
    ("numbers for the slides", ["slide_numbers.py"]),
]
QGIS_PY = Path(__import__("os").environ.get("LOCALAPPDATA", "")) / "Programs" / "OSGeo4W" / "bin" / "python-qgis-ltr.bat"


def _has_shx_text(out_dir=None):
    rs = (out_dir or HERE / "out") / "read_shx.json"
    if not (rs.exists() and rs.stat().st_size > 2):
        return False
    try:
        return any(b.get("text") for b in json.loads(rs.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return False


def main():
    fast = "--fast" in sys.argv
    if not (HERE / "lidar" / "cache" / "ortho_intensity_1m.npy").exists():
        STEPS.insert(7, ("LiDAR intensity cache", ["lidar/q2_terrain_check.py"]))  # after georeference, before overlay
    t_all = time.time()
    for name, args in STEPS:
        if args[0] in ("read_glyphs.py", "ocr.py") and _has_shx_text():
            print(f"{name:26} skipped (SHX annotation text covers this sheet)"); continue
        if "--tables" in args and not _has_shx_text():
            print(f"{name:26} skipped (no SHX annotations: tables from the glyph alphabet)"); continue
        if args[0] == "ocr.py":
            rg = HERE / "out" / "read_glyph.json"
            if rg.exists() and rg.stat().st_size > 2:
                print(f"{name:26} skipped (stroked sheet: read by glyph)"); continue
            if fast and (HERE / "out" / "read_rapid.json").exists():
                print(f"{name:26} skipped (--fast)"); continue
        t = time.time()
        if args[0] in ("qgis_project.py", "figures.py") and not QGIS_PY.exists():
            print(f"{name:26} skipped (QGIS not installed)"); continue
        run_args = args + ["--fast"] if (fast and args[0] == "lidar/surface.py") else args
        r = subprocess.run([str(QGIS_PY) if args[0] in ("qgis_project.py", "figures.py") else PY, str(HERE / run_args[0]), *run_args[1:]], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        last = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip() and "Warning" not in ln][-1:]
        print(f"{name:26} {time.time() - t:6.1f}s  {'ok' if r.returncode == 0 else 'FAILED'}  {last[0][:90] if last else ''}")
        if r.returncode != 0:
            print(r.stdout[-1500:], r.stderr[-1500:])
            sys.exit(1)
    print(f"total {time.time() - t_all:.0f}s")


# --six: the other five sheets' tails, then rasters per tile, then the six-sheet QGIS project.
SIX_SHEETS = [
    ("R-10434.1", "r_10434_001_2020-09-16", "south"),
    ("R-10434.3", "r_10434_003_2020-09-16", "south"),
    ("R-10741.1", "r_10741_001_2017-02-10", "north"),
    ("R-10741.2", "r_10741_002_2017-02-10", "north"),
    ("R-10741.3", "r_10741_003_2017-02-10", "north"),
]
SIX_STEPS = [
    ("text blocks", ["blocks.py"]),
    ("read text (SHX annotations)", ["read_shx.py"]),
    ("sheet frame", ["frame.py"]),
    ("sheet alphabet + tables", ["alphabet.py"]),
    ("tables from annotations", ["read_shx.py", "--tables"]),  # last writer of tables.json where the sheet has SHX text; the bench does the same
    ("read text by glyph", ["read_glyphs.py"]),
    ("read text (OCR)", ["ocr.py", "rapid"]),
    ("georeference", ["solve.py"]),
    ("linework on LiDAR", ["overlay.py"]),
    ("parcels", ["parcels.py"]),
    ("checks + exception queue", ["checks.py"]),
    ("segment tags", ["tags.py"]),
    ("table checks via tags", ["tables.py"]),
    ("record twin (traverse)", ["traverse.py"]),
    ("LiDAR features", ["lidar/extract.py"]),
    ("encroachment", ["encroach.py"]),
    ("object record", ["objects.py"]),
]
PDF_DIR = HERE.parent / "Sample Data" / "d4"


def run_six(fast):
    failures = []
    t_six = time.time()
    for label, stem, tile in SIX_SHEETS:
        out_dir = HERE / "out" / stem
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SHEET": str(PDF_DIR / f"{stem}.pdf")}
        print(f"-- {label} ({stem}, {tile} tile) --")
        t_sheet = time.time()
        for name, args in SIX_STEPS:
            if args[0] in ("read_glyphs.py", "ocr.py") and _has_shx_text(out_dir):
                print(f"  {name:26} skipped (SHX annotation text covers this sheet)"); continue
            if "--tables" in args and not _has_shx_text(out_dir):
                print(f"  {name:26} skipped (no SHX annotations: tables from the glyph alphabet)"); continue
            if args[0] == "ocr.py":
                rg = out_dir / "read_glyph.json"
                if rg.exists() and rg.stat().st_size > 2:
                    print(f"  {name:26} skipped (stroked sheet: read by glyph)"); continue
                if fast and (out_dir / "read_rapid.json").exists():
                    print(f"  {name:26} skipped (--fast)"); continue
            t = time.time()
            r = subprocess.run([PY, str(HERE / args[0]), *args[1:]], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=env)
            last = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip() and "Warning" not in ln][-1:]
            ok = r.returncode == 0
            print(f"  {name:26} {time.time() - t:6.1f}s  {'ok' if ok else 'FAILED'}  {last[0][:90] if last else ''}")
            if not ok:
                print(r.stdout[-1500:], r.stderr[-1500:])
                failures.append(f"{label}: {name} failed")
                break  # this sheet's later steps depend on this one; move to the next sheet
        print(f"  {label} total {time.time() - t_sheet:.0f}s")

    for label, stem, tile in [("R-10434.1", "r_10434_001_2020-09-16", "south"), ("R-10741.1", "r_10741_001_2017-02-10", "north")]:
        t = time.time()
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "SHEET": str(PDF_DIR / f"{stem}.pdf")}
        r = subprocess.run([PY, str(HERE / "export_rasters.py")], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        ok = r.returncode == 0
        print(f"rasters ({tile} tile)          {time.time() - t:6.1f}s  {'ok' if ok else 'FAILED'}")
        if not ok:
            print(r.stdout[-1500:], r.stderr[-1500:])
            failures.append(f"rasters ({tile}) failed")

    if QGIS_PY.exists():
        t = time.time()
        r = subprocess.run([str(QGIS_PY), str(HERE / "qgis_project.py"), "--six"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        ok = r.returncode == 0
        print(f"QGIS six-sheet project      {time.time() - t:6.1f}s  {'ok' if ok else 'FAILED'}")
        print(r.stdout[-2000:], r.stderr[-1500:] if not ok else "")
        if not ok:
            failures.append("qgis_project.py --six failed")
    else:
        print("QGIS six-sheet project      skipped (QGIS not installed)")

    print(f"--six total {time.time() - t_six:.0f}s, {len(failures)} failure(s)")
    if failures:
        print("failures:", "; ".join(failures))
    return failures


if __name__ == "__main__":
    main()
    if "--six" in sys.argv:
        if run_six("--fast" in sys.argv):
            sys.exit(1)
