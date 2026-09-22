"""One command, offline: the whole Presidio pipeline, timed per step.

    python spike/demo.py            # everything
    python spike/demo.py --fast     # skip the OCR pass (reuses spike/out/read_rapid.json)

Order matters: blocks -> ocr -> solve -> overlay -> parcels -> checks -> tags -> tables -> extract -> encroach -> rasters -> objects.
The LiDAR intensity cache (spike/lidar/cache) comes from spike/lidar/q2_terrain_check.py once.
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PY = sys.executable
STEPS = [
    ("text blocks", ["blocks.py"]),
    ("read text", ["ocr.py", "rapid"]),
    ("georeference", ["solve.py"]),
    ("linework on LiDAR", ["overlay.py"]),
    ("parcels", ["parcels.py"]),
    ("checks + exception queue", ["checks.py"]),
    ("segment tags", ["tags.py"]),
    ("table checks via tags", ["tables.py"]),
    ("LiDAR features", ["lidar/extract.py"]),
    ("encroachment", ["encroach.py"]),
    ("rasters for QGIS", ["export_rasters.py"]),
    ("object record", ["objects.py"]),
]


def main():
    fast = "--fast" in sys.argv
    if not (HERE / "lidar" / "cache" / "ortho_intensity_1m.npy").exists():
        STEPS.insert(6, ("LiDAR intensity cache", ["lidar/q2_terrain_check.py"]))
    t_all = time.time()
    for name, args in STEPS:
        if fast and args[0] == "ocr.py" and (HERE / "out" / "read_rapid.json").exists():
            print(f"{name:26} skipped (--fast)"); continue
        t = time.time()
        r = subprocess.run([PY, str(HERE / args[0]), *args[1:]], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        last = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.strip() and "Warning" not in ln][-1:]
        print(f"{name:26} {time.time() - t:6.1f}s  {'ok' if r.returncode == 0 else 'FAILED'}  {last[0][:90] if last else ''}")
        if r.returncode != 0:
            print(r.stdout[-1500:], r.stderr[-1500:])
            sys.exit(1)
    print(f"total {time.time() - t_all:.0f}s")


if __name__ == "__main__":
    main()
