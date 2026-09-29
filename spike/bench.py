"""Association bench: run checks.py on a sheet set, summarise pass / fail / wrong-line per kind.
usage: [ASSOC=layers] python spike/bench.py <label> [--tags] [--parcels] [--traverse] [--tables] [presidio r105 r17x r10434_1 r10434_3]
  -> one row per sheet appended to spike/out/bench.csv. wrong_line = fails beyond the exception page's
  SMALL thresholds (the reader measured a different line); no_line = labels with no candidate.
  --tags/--parcels/--traverse run tables.py/parcels.py/traverse.py per sheet and add their columns;
  --tables runs read_shx.py then read_shx.py --tables (the annotation table rebuild) and adds
  table_rows/rows_clean (sheets.py's clean definition: cells non-empty, no "?" in the first 3);
  a step that errors fills its columns with "err" and prints the last 20 lines of stderr, without
  killing the bench. Adding a column changes the CSV header, which rotates the old file to
  bench_old.csv -- expected the first time --tables is used.
  Always-on columns (every row, no flag): frame = "callouts"/"grid"/"record"/"record+package" (georef.json's
  credible/frame) plus " rms <ft>" when rms_ft is set; blocks_read = glyphs with no "?" over total
  blocks in the sheet's read file (georef's READS choice, mirrored here); bearings_parsed/
  distances_parsed = blocks whose text matches checks.BEAR/checks.DIST after the same line-split +
  TOKEN extraction checks.py runs on a label.
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
sys.path.insert(0, str(ROOT / "spike"))
from checks import BEAR, DIST, TOKEN  # noqa: E402 -- same regexes/token split checks.py runs its labels through
SHEETS = {
    "presidio": None,
    "r105": ROOT / "Sample Data" / "d4" / "r_00105_014_2021-05-21.pdf",
    "r17x": ROOT / "Sample Data" / "d4" / "r_00017x_001_2021-10-19.pdf",
    "r10434_1": ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf",
    "r10434_3": ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf",
    "r10741_1": ROOT / "Sample Data" / "d4" / "r_10741_001_2017-02-10.pdf",
    "r10741_2": ROOT / "Sample Data" / "d4" / "r_10741_002_2017-02-10.pdf",
    "r10741_3": ROOT / "Sample Data" / "d4" / "r_10741_003_2017-02-10.pdf",
    "r71_70": ROOT / "Sample Data" / "d4" / "r_00071_070_2019-10-15.pdf",
    "r71_71": ROOT / "Sample Data" / "d4" / "r_00071_071_2024-07-16.pdf",
    "r10258": ROOT / "Sample Data" / "d4" / "r_10258_001_2020-04-17.pdf",
}
SMALL = {"distance": 5.0, "arc length": 5.0, "bearing": 60.0, "chord distance": 5.0, "chord bearing": 60.0}
# chord bearing/distance (loop6 leg C rule 2: a label beside a curve cites the chord, not the arc) count
# toward the same distance/bearing columns as their straight-line namesakes -- CHORD_KIND maps the extra
# row kind onto the FIELDS column it belongs under
TAGS_COLS = ["tags_assoc", "tags_pass", "tags_fail", "tags_queued"]
PARCELS_COLS = ["faces", "faces_named"]
TRAVERSE_COLS = ["chains", "closed"]
RECON_COLS = ["recon_all", "recon_dim", "recon_parcels", "recon_inverse_ft", "recon_anchored", "recon_closure_ft"]
OUT_RECON = ROOT / "spike" / "out_recon"
ANCHORED_KEYS = {"presidio", "r10434_1", "r10434_3"}  # loop19 leg 1's own anchored.SHEET_PDF scope --
                                                       # anchored.py has no anchors built for the other
                                                       # sheets yet, so their own recon_anchored reads
                                                       # 0/<recon_all_denom_ft>, not "err"
TABLES_COLS = ["table_rows", "rows_clean"]
READ_COLS = ["frame", "blocks_read", "bearings_parsed", "distances_parsed"]
# coverage: distance+bearing passes over every parsed distance/bearing token (a rate over checked values alone
# rises when labels are queued); gold: passes/fails scored against spike/gold, right/wrong/unkeyed for
# passes then fail_real/fail_wrong/fail_unkeyed for FAILs (loop 14)
QUALITY_COLS = ["coverage", "gold"]
FIELDS = ["label", "sheet", "distance", "bearing", "arc length", "exceptions", "wrong_line", "no_line", "secs"] + TAGS_COLS + PARCELS_COLS + TRAVERSE_COLS + TABLES_COLS + READ_COLS + QUALITY_COLS + RECON_COLS


def env_for(pdf):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if pdf:
        env["SHEET"] = str(pdf)
    else:
        env.pop("SHEET", None)
    return env


def out_dir(pdf):
    return OUT / (pdf.stem if pdf else "")


def run_step(script, pdf, args=()):
    """Run a spike/<script>.py for this sheet; return (ok, stderr_tail)."""
    env = env_for(pdf)
    r = subprocess.run([str(PY), str(ROOT / "spike" / script), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    if r.returncode:
        return False, "\n".join(r.stderr.splitlines()[-20:])
    return True, ""


def tags_cols(pdf):
    ok, err = run_step("tags.py", pdf)  # tables.py reads tags.json; sheets never run through the full
    if not ok:                          # pipeline (the north set) don't have one yet
        print(f"tags.py failed: {err}")
        return {k: "err" for k in TAGS_COLS}
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
            "tags_pass": sum(1 for r in rows if r["result"].startswith("pass")),  # tables.py's own run-sum
            # rows ("pass as a run of N: ...", its `_regions`/curve-table grouping) are a pass, exact
            # equality here missed them silently since loop2 legC introduced that message (measured:
            # presidio already carries 2 on disk) -- same convention tables.py's own printed summary uses
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


def tables_cols(pdf):
    ok, err = run_step("read_shx.py", pdf)
    if ok:
        ok, err = run_step("read_shx.py", pdf, args=["--tables"])
    if not ok:
        print(f"read_shx.py failed: {err}")
        return {k: "err" for k in TABLES_COLS}
    o = out_dir(pdf)
    try:
        raw = json.loads((o / "tables.json").read_text(encoding="utf-8"))
        t = {k: v for k, v in raw.items() if not k.startswith("_")} if isinstance(raw, dict) else {}  # a
        # sheet with no NO. column (no L#/C# table) writes [] -- 0 rows, not an error
        return {"table_rows": len(t), "rows_clean": sum(1 for r in t.values() if r["cells"] and not any("?" in c for c in r["cells"][:3]))}
    except Exception as e:
        print(f"tables read failed: {type(e).__name__} {e}")
        return {k: "err" for k in TABLES_COLS}


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


def recon_cols(pdf, key):
    """recon.py: run only after --parcels and --traverse have both written their outputs (loop16 leg A).
    Also runs recon.py --no-inverse (loop18 leg 2): recon_inverse_ft is the ft recon_all_covered_ft
    gains from "by inverse ..." traverse rows alone (0 on a sheet inverse.py never touched). loop19 leg
    2: on a sheet anchored.py has anchors for (ANCHORED_KEYS), also runs anchored.py <key> -- it re-runs
    recon.py internally (deterministic, same numbers) and patches recon_segments.json with the "anchored"
    column recon_set.py's own set-level recon_anchored_set_pct needs. loop19 leg 3: recon_closure_ft is
    that same anchored.py run's own "recon_closure"."added_ft" -- net NEW boundary ft a checked closure
    fill's own segment adds (already folded into recon_anchored above; this column is the breakout)."""
    ok, err = run_step("recon.py", pdf)
    if not ok:
        print(f"recon.py failed: {err}")
        return {k: "err" for k in RECON_COLS}
    ok2, err2 = run_step("recon.py", pdf, args=["--no-inverse"])
    if not ok2:
        print(f"recon.py --no-inverse failed: {err2}")
    anchored_str, closure_ft = "", ""
    if key in ANCHORED_KEYS:
        ok3, err3 = run_step("anchored.py", pdf, args=[key])
        if not ok3:
            print(f"anchored.py failed: {err3}")
            anchored_str, closure_ft = "err", "err"
        else:
            try:
                a = json.loads((OUT_RECON / f"anchored_{key}.json").read_text(encoding="utf-8"))
                ra = a["recon_anchored"]
                anchored_str = f"{int(ra['covered_ft'])}/{int(ra['denom_ft'])}"
                closure_ft = a["recon_closure"]["added_ft"]
            except Exception as e:
                print(f"anchored read failed: {type(e).__name__} {e}")
                anchored_str, closure_ft = "err", "err"
    o = out_dir(pdf)
    try:
        r = json.loads((o / "recon.json").read_text(encoding="utf-8"))
        inverse_ft = ""
        if ok2 and (o / "recon_no_inverse.json").exists():
            r0 = json.loads((o / "recon_no_inverse.json").read_text(encoding="utf-8"))
            inverse_ft = round(r["recon_all_covered_ft"] - r0["recon_all_covered_ft"], 1)
        return {
            "recon_all": f"{int(r['recon_all_covered_ft'])}/{int(r['recon_all_denom_ft'])}",
            "recon_dim": f"{int(r['recon_dim_covered_ft'])}/{int(r['recon_dim_denom_ft'])}",
            "recon_parcels": f"{r['parcels_all']['n']}/{r['parcels_all']['of']}|{r['parcels_dim']['n']}/{r['parcels_dim']['of']}",
            "recon_inverse_ft": inverse_ft,
            "recon_anchored": anchored_str or f"0/{int(r['recon_all_denom_ft'])}",
            "recon_closure_ft": closure_ft,
        }
    except Exception as e:
        print(f"recon read failed: {type(e).__name__} {e}")
        return {k: "err" for k in RECON_COLS}


def reads_path(o):
    """Mirror georef.py's READS choice for out dir o: read_shx.json when it carries text, else
    read_glyph.json, else read_rapid.json."""
    rs, rg, rr, rt = o / "read_shx.json", o / "read_glyph.json", o / "read_rapid.json", o / "tables.json"

    def has_text(p):
        if not p.exists() or p.stat().st_size < 2:
            return False
        try:
            return any(b.get("text") for b in json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            return False
    from georef import _has_rows
    validated = _has_rows(rt)
    return rs if has_text(rs) else (rg if rg.exists() and rg.stat().st_size > 2 and (validated or not rr.exists()) else rr)


def read_cols(pdf):
    o = out_dir(pdf)
    try:
        g = json.loads((o / "georef.json").read_text(encoding="utf-8"))
        if g.get("credible") or g.get("weak"):
            # the point-fit path (georef.json has "control"/"grid_lines", no "frame" key of its own) is
            # "record" when >= 2 traced callouts carried the fit, "grid" when it rested on tick lines instead
            used_pts = sum(1 for c in g.get("control", []) if c.get("used"))
            base = "callouts" if used_pts >= 2 else "grid"
        else:
            base = g.get("frame") or "?"
        rms = g.get("rms_ft")
        frame = f"{base} rms {rms:.2f}" if rms is not None else base
        rp = reads_path(o)
        blocks = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else []
        full = sum(1 for b in blocks if "?" not in b.get("text", ""))
        bear = dist = 0
        for b in blocks:
            lines = b.get("text", "").replace(" ", "").split("|")
            parts = [m.group(0) for t in lines for m in TOKEN.finditer(t)] or lines
            bear += any(BEAR.match(p) for p in parts)
            dist += any(DIST.match(p) for p in parts)
        return {"frame": frame, "blocks_read": f"{full}/{len(blocks)}", "bearings_parsed": bear, "distances_parsed": dist}
    except Exception as e:
        print(f"read cols failed: {type(e).__name__} {e}")
        return {k: "err" for k in READ_COLS}


def run(key, steps):
    pdf = SHEETS[key]
    env = env_for(pdf)
    t = time.time()
    tables = tables_cols(pdf) if "tables" in steps else {}  # before checks: tables.json masks table cells, so the annotation rebuild must be the last writer
    r = subprocess.run([str(PY), str(ROOT / "spike" / "checks.py")], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=ROOT)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-3000:])
        raise SystemExit(f"checks.py failed on {key}")
    o = out_dir(pdf)
    rows = list(csv.DictReader(open(o / "checks.csv", encoding="utf-8")))
    exc = json.loads((o / "exceptions.json").read_text(encoding="utf-8"))
    res = {"sheet": key, "secs": round(time.time() - t)}
    for kind in ("distance", "bearing", "arc length"):
        ks = [x for x in rows if x["check"] in (kind, "chord " + kind)]
        res[kind] = f"{sum(1 for x in ks if x['result'].startswith('pass'))}/{len(ks)}"  # a checks.py
        # run-sum row ("pass as a run of N: ...", leg5/leg6A's grouping) is a pass; same fix as tags_pass above
    wrong = 0
    for e in exc:
        v = e.get("off_ft", e.get("off_arcmin"))
        k = e.get("kind")
        # a bearing/chord-bearing exception carries its own scaled tolerance (checks.bearing_tol_deg,
        # loop6 leg C rule 1): wrong-line uses that instead of the flat SMALL cutoff where it's wider,
        # so a short piece's few-arcmin measurement slop doesn't get flagged "wrong line" either
        cutoff = max(SMALL.get(k, 0), e["tol_arcmin"]) if "tol_arcmin" in e else SMALL.get(k)
        if v is not None and cutoff is not None and abs(v) > cutoff:
            wrong += 1
    res["exceptions"] = len(exc)
    res["wrong_line"] = wrong
    res["no_line"] = sum(1 for e in exc if "no line" in e.get("issue", ""))
    res.update(read_cols(pdf))
    if "tags" in steps:
        res.update(tags_cols(pdf))
    if "parcels" in steps:
        res.update(parcels_cols(pdf))
    if "traverse" in steps:
        res.update(traverse_cols(pdf))
    if "parcels" in steps and "traverse" in steps:
        res.update(recon_cols(pdf, key))
    res.update(tables)
    try:
        passes = sum(int(str(res[k]).split("/")[0]) for k in ("distance", "bearing"))
        parsed = int(res.get("distances_parsed") or 0) + int(res.get("bearings_parsed") or 0)
        res["coverage"] = f"{passes}/{parsed}" if parsed else ""
    except (ValueError, KeyError):
        res["coverage"] = ""
    import coverage_attrib  # honest coverage where the attribution knows the sheet: drawing-label passes (arcs
    if key in coverage_attrib.SHEETS:  # included) over labels a check could address (no table cells, notes,
        coverage_attrib.SNAP = str(OUT)  # areas, radials, duplicates)
        items, _ = coverage_attrib.classify(key)
        EXCLUDE = {"a-table", "c-table-tag", "a-titleblock", "a-notes", "a-area", "a-radial", "a-station", "b-duplicate"}
        addressable = [i for i in items if i["bucket"] not in EXCLUDE]
        res["coverage"] = f"{sum(1 for i in addressable if i['bucket'].startswith('d-pass'))}/{len(addressable)}"
    if "tags" in steps and (ROOT / "spike" / "gold" / f"{key}_assoc.json").exists():
        import gold_assoc
        g = gold_assoc.current(o, key)
        res["gold"] = f"{g['right']}/{g['wrong']}/{g['unkeyed']}|{g['fail_real']}/{g['fail_wrong']}/{g['fail_unkeyed']}"
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
        if existing_header != FIELDS:  # migrate in place: old rows keep their values, new columns blank
            old = list(csv.DictReader(open(f, encoding="utf-8")))
            with open(f, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
                w.writeheader()
                w.writerows(old)
    new = not f.exists()
    with open(f, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
