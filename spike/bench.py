"""Association bench: run checks.py on a sheet set, summarise pass / fail / wrong-line per kind.
usage: [ASSOC=bearing,span,layers] python spike/bench.py <label> [presidio r105 r17x r10434_3]
  -> one row per sheet appended to spike/out/bench.csv. wrong_line = fails beyond the exception page's
  SMALL thresholds (the reader measured a different line); no_line = labels with no candidate.
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
    "r10434_3": ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf",
}
SMALL = {"distance": 5.0, "arc length": 5.0, "bearing": 60.0}


def run(key):
    pdf = SHEETS[key]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if pdf:
        env["SHEET"] = str(pdf)
    else:
        env.pop("SHEET", None)
    t = time.time()
    r = subprocess.run([str(PY), str(ROOT / "spike" / "checks.py")], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-3000:])
        raise SystemExit(f"checks.py failed on {key}")
    o = OUT / (pdf.stem if pdf else "")
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
    return res


def main():
    label = sys.argv[1]
    keys = sys.argv[2:] or list(SHEETS)
    out = []
    for k in keys:
        res = run(k)
        res["label"] = label
        out.append(res)
        print(res, flush=True)
    f = OUT / "bench.csv"
    new = not f.exists()
    with open(f, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["label", "sheet", "distance", "bearing", "arc length", "exceptions", "wrong_line", "no_line", "secs"])
        if new:
            w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
