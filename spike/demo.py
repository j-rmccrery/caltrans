"""One command, offline: the whole Presidio pipeline, timed per step.

    python spike/demo.py            # everything
    python spike/demo.py --fast     # skip the OCR pass (reuses spike/out/read_rapid.json)

Order matters: blocks -> ocr -> solve -> overlay -> parcels -> checks -> tags -> tables -> traverse -> extract -> encroach -> rasters -> objects.
The LiDAR intensity cache (spike/lidar/cache) comes from spike/lidar/q2_terrain_check.py once.
"""
import json
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
    ("rasters for QGIS", ["export_rasters.py"]),
    ("object record", ["objects.py"]),
    ("exception page", ["exceptions_page.py"]),
    ("QGIS project", ["qgis_project.py"]),  # runs under QGIS's own Python, see QGIS_PY
    ("figures", ["figures.py"]),            # same
    ("numbers for the slides", ["slide_numbers.py"]),
]
QGIS_PY = Path(__import__("os").environ.get("LOCALAPPDATA", "")) / "Programs" / "OSGeo4W" / "bin" / "python-qgis-ltr.bat"


def _has_shx_text():
    rs = HERE / "out" / "read_shx.json"
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
        if args[0] == "ocr.py":
            rg = HERE / "out" / "read_glyph.json"
            if rg.exists() and rg.stat().st_size > 2:
                print(f"{name:26} skipped (stroked sheet: read by glyph)"); continue
            if fast and (HERE / "out" / "read_rapid.json").exists():
                print(f"{name:26} skipped (--fast)"); continue
        t = time.time()
        if args[0] in ("qgis_project.py", "figures.py") and not QGIS_PY.exists():
            print(f"{name:26} skipped (QGIS not installed)"); continue
        r = subprocess.run([str(QGIS_PY) if args[0] in ("qgis_project.py", "figures.py") else PY, str(HERE / args[0]), *args[1:]], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        last = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip() and "Warning" not in ln][-1:]
        print(f"{name:26} {time.time() - t:6.1f}s  {'ok' if r.returncode == 0 else 'FAILED'}  {last[0][:90] if last else ''}")
        if r.returncode != 0:
            print(r.stdout[-1500:], r.stderr[-1500:])
            sys.exit(1)
    print(f"total {time.time() - t_all:.0f}s")


if __name__ == "__main__":
    main()
