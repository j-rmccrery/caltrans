"""Gold set for label-to-drawn-line association (spike/checks.py, spike/tables.py).

checks.py / tables.py report pass when a printed value agrees with whatever line
nearest_line() / candidates() picked for it -- nobody has verified the picked line
is the RIGHT line (luck passes have been found by eye more than once). This script
renders one crop per checked label (printed-value box in red, the line the code
measured in blue -- reusing exceptions_page.crop(), same rendering the exception
queue uses), a human keys each crop true/false/unsure, and a scorer turns the keyed
file into precision numbers.

Usage:
  python spike/gold_assoc.py render --snap <dir> [--sheet <key>]   crops -> spike/out_gold/<key>/
  python spike/gold_assoc.py score  --snap <dir> [--sheet <key>]   precision/fail-breakdown from spike/gold/<key>_assoc.json

--sheet defaults to "presidio", whose output names are unchanged (spike/gold/presidio_assoc.json,
spike/out_gold/presidio/) so existing files and bench.py's presidio gold column keep working. Any
other --sheet must be a key in bench.SHEETS (reused here for the sheet -> PDF path table).

Inputs, all read from --snap <dir> (a frozen copy of spike/out -- never spike/out
itself, which another agent is rewriting):
  labels.json          checks.py: one entry per checked bearing/distance/arc label
                        (already carries "region" and "line" in pt -- exactly what
                        exceptions_page.crop() wants)
  tag_labels.json       tables.py: one entry per successfully-placed table tag
                        (line, but no region -- tag_labels.json doesn't keep the
                        tag's own text position)
  tags.json             tables.py/tags.py: every detected tag's text box (cx, cy,
                        gh) incl. unresolved ones ("?..."); joined back to
                        tag_labels.json by tag name (unique among resolved tags) to
                        rebuild the same region tables.py itself computes
  tags_checks.csv       tables.py: one row per tag check (bearing/distance/radius/
                        arc length) with its pass/FAIL/"not checked" result

id scheme, stable across re-runs of the same --snap dir, documented so the scorer
(or bench.py later) can rejoin the keyed gold file back to labels.json / tags_checks.csv:
  "label:<i>"          i = index into labels.json
  "tag:<tag>:<check>"  tag name + the "check" column of tags_checks.csv,
                       e.g. "tag:C4:arc length"

Gold key format (spike/gold/presidio_assoc.json), a JSON list of:
  {id, kind, printed, verdict_by_code, correct_line, note}
  correct_line: "true" | "false" | "unsure" (a string, not a bool: "unsure" is a
  third state, not a missing key)
"""
import argparse
import base64
import csv
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from exceptions_page import crop  # noqa: E402 -- reuse the exact red-box/blue-line rendering
import bench  # noqa: E402 -- reuse SHEETS (sheet key -> pdf path), don't duplicate it here

GOLD_DIR = HERE / "gold"


def sheet_pdf(sheet):
    """bench.SHEETS[sheet], or georef's DEFAULT (the presidio sheet) for the presidio key.
    georef.PDF reads the SHEET env at import time -- opening the PDF explicitly here instead
    of importing georef.PDF avoids that import-order trap for a non-default sheet."""
    pdf = bench.SHEETS[sheet]
    if pdf is None:
        from georef import DEFAULT
        return DEFAULT
    return pdf


def gold_file(sheet):
    return GOLD_DIR / f"{sheet}_assoc.json"


def crop_dir(sheet):
    return HERE / "out_gold" / sheet


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.+-]+", "_", str(s))[:80]


def load_items(snap):
    """Every checked label (pass or FAIL -- never "not checked"/no-line exceptions,
    those never made it into labels.json / never got a pass-or-FAIL row)."""
    snap = Path(snap)
    labels = json.loads((snap / "labels.json").read_text(encoding="utf-8"))
    items = [{
        "id": f"label:{i}",
        "kind": lb["kind"],
        "printed": lb["printed"],
        "verdict_by_code": "pass" if lb["ok"] else "FAIL",
        "region": lb["region"],
        "line": lb["line"],
    } for i, lb in enumerate(labels)]

    tag_labels = {tl["tag"]: tl for tl in json.loads((snap / "tag_labels.json").read_text(encoding="utf-8"))}
    tag_pos = {t["tag"]: t for t in json.loads((snap / "tags.json").read_text(encoding="utf-8")) if "?" not in t["tag"]}
    with open(snap / "tags_checks.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        result = r["result"]
        if result == "pass" or result.startswith("pass as a run"):
            verdict = "pass"
        elif result == "FAIL":
            verdict = "FAIL"
        else:
            continue  # "not checked" (flat arc, total-over-several-segments): no association attempted
        tl, pos = tag_labels.get(r["tag"]), tag_pos.get(r["tag"])
        if tl is None or pos is None:
            continue  # shouldn't happen: every checked row has a placed tag with a known text position
        region = [round(pos["cx"] - 2 * pos["gh"]), round(pos["cy"] - pos["gh"]),
                  round(pos["cx"] + 2 * pos["gh"]), round(pos["cy"] + pos["gh"])]  # same formula tables.py uses
        items.append({
            "id": f"tag:{r['tag']}:{r['check']}",
            "kind": "tag " + r["check"],
            "printed": r["printed"],
            "verdict_by_code": verdict,
            "region": region,
            "line": tl["line"],
        })
    return items


def render(snap, sheet="presidio"):
    items = load_items(snap)
    cdir = crop_dir(sheet)
    cdir.mkdir(parents=True, exist_ok=True)
    page = pymupdf.open(sheet_pdf(sheet))[0]
    for it in items:
        im = cv2.imdecode(np.frombuffer(base64.b64decode(crop(page, it["region"], it["line"])), np.uint8), cv2.IMREAD_COLOR)
        it["file"] = f"{safe(it['id'])}__{it['verdict_by_code']}__{safe(it['printed'])}.png"
        cv2.imwrite(str(cdir / it["file"]), im)
    (cdir / "_manifest.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} crops -> {cdir}  ({sum(1 for i in items if i['verdict_by_code'] == 'pass')} pass, "
          f"{sum(1 for i in items if i['verdict_by_code'] == 'FAIL')} FAIL)")
    return items


def score(out_dir, sheet="presidio"):
    """out_dir: the directory holding <sheet>_assoc.json (e.g. spike/gold). Returns
    {"per_kind": {kind: {pass_checked, pass_correct, pass_precision, fail_checked,
    fail_wrong_line, fail_real}}, "fail_breakdown": {wrong_line, real_disagreement},
    "unsure": n}. A function, not a script action, so bench.py can call it directly."""
    keyed = json.loads((Path(out_dir) / f"{sheet}_assoc.json").read_text(encoding="utf-8"))
    by_kind, fails, unsure = {}, {"wrong_line": 0, "real_disagreement": 0}, 0
    for k in keyed:
        if k["correct_line"] == "unsure":
            unsure += 1
            continue
        correct = k["correct_line"] is True or k["correct_line"] == "true"
        d = by_kind.setdefault(k["kind"], {"pass_checked": 0, "pass_correct": 0, "fail_checked": 0, "fail_wrong_line": 0, "fail_real": 0})
        if k["verdict_by_code"] == "pass":
            d["pass_checked"] += 1
            d["pass_correct"] += correct
        else:
            d["fail_checked"] += 1
            if correct:
                d["fail_real"] += 1
                fails["real_disagreement"] += 1
            else:
                d["fail_wrong_line"] += 1
                fails["wrong_line"] += 1
    for d in by_kind.values():
        d["pass_precision"] = d["pass_correct"] / d["pass_checked"] if d["pass_checked"] else None
    return {"per_kind": by_kind, "fail_breakdown": fails, "unsure": unsure}


def _same_line(a, b, tol=3.0):
    """Two measured lines (two endpoints each, PDF pt) are the same when both ends agree within tol, either order."""
    import math
    d = lambda p, q: math.hypot(p[0] - q[0], p[1] - q[1])
    return (d(a[0], b[0]) <= tol and d(a[-1], b[-1]) <= tol) or (d(a[0], b[-1]) <= tol and d(a[-1], b[0]) <= tol)


def current(run_out, key="presidio"):
    """Score a CURRENT run (run_out = the dir holding labels.json / tags_checks.csv) against the gold set, so the
    bench tracks precision as code changes. Labels rejoin by (kind, region); tags by (tag, check).
    right  = passes now on the line the gold set says is correct
    wrong  = passes now on a line the gold set says is wrong, or on a different line than the keyed correct one
    unkeyed = passes now with no gold entry, or keyed unsure: look at these before trusting a gain.
    fail_real/fail_wrong/fail_unkeyed = the same rejoin for CURRENT FAILs (loop 14): a fail keyed
    correct_line true is a real disagreement, false is the checker measuring the wrong line, missing/
    unsure is fail_unkeyed."""
    import csv
    gold = {g["id"]: g for g in json.loads(gold_file(key).read_text(encoding="utf-8"))}
    man = {(m["kind"], tuple(m["region"])): m for m in json.loads((crop_dir(key) / "_manifest.json").read_text(encoding="utf-8")) if m.get("region") and m["id"].startswith("label:")}
    right = wrong = unkeyed = 0
    fail_real = fail_wrong = fail_unkeyed = 0
    for lab in json.loads((Path(run_out) / "labels.json").read_text(encoding="utf-8")):
        m = man.get((lab["kind"], tuple(lab["region"])))
        g = gold.get(m["id"]) if m else None
        if lab.get("ok") is False:
            if g is None or str(g["correct_line"]) == "unsure":
                fail_unkeyed += 1
            elif str(g["correct_line"]).lower() == "true":
                fail_real += 1
            else:
                fail_wrong += 1
            continue
        if not lab.get("ok"):
            continue
        if g is None or str(g["correct_line"]) == "unsure":
            unkeyed += 1
        elif str(g["correct_line"]).lower() == "true" and m.get("line") and _same_line(lab["line"], m["line"]):
            right += 1
        elif str(g["correct_line"]).lower() == "false" and m.get("line") and not _same_line(lab["line"], m["line"]):
            unkeyed += 1  # moved off the keyed wrong line: new line not keyed yet
        else:
            wrong += 1
    for r in csv.DictReader(open(Path(run_out) / "tags_checks.csv", encoding="utf-8")):
        g = gold.get(f"tag:{r['tag']}:{r['check']}")
        if r["result"] == "FAIL":
            if g is None or str(g["correct_line"]) == "unsure":
                fail_unkeyed += 1
            elif str(g["correct_line"]).lower() == "true":
                fail_real += 1
            else:
                fail_wrong += 1
            continue
        if not r["result"].startswith("pass"):
            continue
        if g is None or str(g["correct_line"]) == "unsure":
            unkeyed += 1
        elif str(g["correct_line"]).lower() == "true":
            right += 1
        else:
            wrong += 1
    return {"right": right, "wrong": wrong, "unkeyed": unkeyed,
            "fail_real": fail_real, "fail_wrong": fail_wrong, "fail_unkeyed": fail_unkeyed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="render", choices=["render", "score"])
    ap.add_argument("--snap", required=True)
    ap.add_argument("--sheet", default="presidio")
    args = ap.parse_args()
    if args.cmd == "score":
        r = score(GOLD_DIR, args.sheet)
        for kind, d in sorted(r["per_kind"].items()):
            p = d["pass_precision"]
            print(f"{kind:14} pass precision {p:.3f} ({d['pass_correct']}/{d['pass_checked']})" if p is not None else f"{kind:14} no keyed passes",
                  f" | FAIL keyed {d['fail_checked']} (wrong line {d['fail_wrong_line']}, real disagreement {d['fail_real']})" if d["fail_checked"] else "")
        print(f"fail breakdown overall: wrong line {r['fail_breakdown']['wrong_line']}, real disagreement {r['fail_breakdown']['real_disagreement']}")
        print(f"unsure: {r['unsure']}")
    else:
        render(args.snap, args.sheet)


if __name__ == "__main__":
    main()
