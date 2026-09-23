"""Association bench: run checks.py on a sheet set, summarise pass / fail / wrong-line per kind.
usage: [ASSOC=bearing,span,layers] python spike/bench.py <label> [--tags] [--parcels] [--traverse] [presidio r105 r17x r10434_1 r10434_3]
  -> one row per sheet appended to spike/out/bench.csv. wrong_line = fails beyond the exception page's
  SMALL thresholds (the reader measured a different line); no_line = labels with no candidate.
  --tags/--parcels/--traverse run tables.py/parcels.py/traverse.py per sheet and add their columns;
  a step that errors fills its columns with "err" and prints the last 20 lines of stderr, without
  killing the bench.
"""
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
OUT = ROOT / "spike" / "out"
SHEETS = {
    "presidio": None,
    "r105": ROOT / "Sample Data" / "d4" / "r_00105_014_2021-05-21.pdf",
    "r17x": ROOT / "Sample Data" / "d4" / "r_00017x_001_2021-10-19.pdf",
    "r10434_1": ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf",
    "r10434_3": ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf",
}
SMALL = {"distance": 5.0, "arc length": 5.0, "bearing": 60.0}
TAGS_COLS = ["tags_assoc", "tags_pass", "tags_fail", "tags_queued"]
PARCELS_COLS = ["faces", "faces_named"]
TRAVERSE_COLS = ["chains", "closed"]
FIELDS = ["label", "sheet", "distance", "bearing", "arc length", "exceptions", "wrong_line", "no_line", "secs"] + TAGS_COLS + PARCELS_COLS + TRAVERSE_COLS


def env_for(pdf):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if pdf:
        env["SHEET"] = str(pdf)
    else:
        env.pop("SHEET", None)
    return env


def out_dir(pdf):
    return OUT / (pdf.stem if pdf else "")


def run_step(script, pdf):
    """Run a spike/<script>.py for this sheet; return (ok, stderr_tail)."""
    env = env_for(pdf)
    r = subprocess.run([str(PY), str(ROOT / "spike" / script)], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    if r.returncode:
        return False, "\n".join(r.stderr.splitlines()[-20:])
    return True, ""


def tags_cols(pdf):
    ok, err = run_step("tables.py", pdf)
    if not ok:
        print(f"tables.py failed: {err}")
        return {k: "err" for k in TAGS_COLS}
    o = out_dir(pdf)
    try:
        rows = list(csv.DictReader(open(o / "tags_checks.csv", encoding="utf-8")))
        queue = json.loads((o / "tags_queue.json").read_text(encoding="utf-8"))
        return {
            "tags_assoc": len({r["tag"] for r in rows}),
            "tags_pass": sum(1 for r in rows if r["result"] == "pass"),
            "tags_fail": sum(1 for r in rows if r["result"] == "FAIL"),
            "tags_queued": len(queue),
        }
    except Exception as e:
        print(f"tags read failed: {type(e).__name__} {e}")
        return {k: "err" for k in TAGS_COLS}


def parcels_cols(pdf):
    ok, err = run_step("parcels.py", pdf)
    if not ok:
        print(f"parcels.py failed: {err}")
        return {k: "err" for k in PARCELS_COLS}
    o = out_dir(pdf)
    try:
        g = json.loads((o / "parcels.geojson").read_text(encoding="utf-8"))
        feats = g["features"]
        return {"faces": len(feats), "faces_named": sum(1 for f in feats if f["properties"].get("parcel"))}
    except Exception as e:
        print(f"parcels read failed: {type(e).__name__} {e}")
        return {k: "err" for k in PARCELS_COLS}


def traverse_cols(pdf):
    ok, err = run_step("traverse.py", pdf)
    if not ok:
        print(f"traverse.py failed: {err}")
        return {k: "err" for k in TRAVERSE_COLS}
    o = out_dir(pdf)
    try:
        chains = json.loads((o / "traverse.json").read_text(encoding="utf-8"))
        return {"chains": len(chains), "closed": sum(1 for c in chains if c.get("closed"))}
    except Exception as e:
        print(f"traverse read failed: {type(e).__name__} {e}")
        return {k: "err" for k in TRAVERSE_COLS}


def run(key, steps):
    pdf = SHEETS[key]
    env = env_for(pdf)
    t = time.time()
    r = subprocess.run([str(PY), str(ROOT / "spike" / "checks.py")], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-3000:])
        raise SystemExit(f"checks.py failed on {key}")
    o = out_dir(pdf)
    rows = list(csv.DictReader(open(o / "checks.csv", encoding="utf-8")))
    exc = json.loads((o / "exceptions.json").read_text(encoding="utf-8"))
    res = {"sheet": key, "secs": round(time.time() - t)}
    for kind in ("distance", "bearing", "arc length"):
        ks = [x for x in rows if x["check"] == kind]
        res[kind] = f"{sum(1 for x in ks if x['result'] == 'pass')}/{len(ks)}"
    wrong = 0
    for e in exc:
        v = e.get("off_ft", e.get("off_arcmin"))
        k = e.get("kind")
        if v is not None and k in SMALL and abs(v) > SMALL[k]:
            wrong += 1
    res["exceptions"] = len(exc)
    res["wrong_line"] = wrong
    res["no_line"] = sum(1 for e in exc if "no line" in e.get("issue", ""))
    if "tags" in steps:
        res.update(tags_cols(pdf))
    if "parcels" in steps:
        res.update(parcels_cols(pdf))
    if "traverse" in steps:
        res.update(traverse_cols(pdf))
    res["secs"] = round(time.time() - t)  # includes any optional steps
    return res


def main():
    label = sys.argv[1]
    rest = sys.argv[2:]
    steps = {a[2:] for a in rest if a.startswith("--")}
    keys = [a for a in rest if not a.startswith("--")] or list(SHEETS)
    out = []
    for k in keys:
        res = run(k, steps)
        res["label"] = label
        out.append(res)
        print(res, flush=True)
    f = OUT / "bench.csv"
    if f.exists():
        existing_header = next(csv.reader(open(f, encoding="utf-8")), [])
        if existing_header != FIELDS:
            f.rename(OUT / "bench_old.csv")
    new = not f.exists()
    with open(f, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
