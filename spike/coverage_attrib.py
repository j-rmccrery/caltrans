"""Where every token bench.py's read_cols() counts (bearings_parsed/distances_parsed) actually goes.
Read-only: uses spike/checks.py's own regexes and two pure region-finder helpers, plus each sheet's
already-computed out files (from --snap, a frozen out/ tree -- never spike/out). Writes only under
spike/out_coverage/.

Join rule: bench's denominator is one item per (block, kind) where kind in {bearing, distance} and
BEAR/DIST matches some token inside the block (bench's own read_cols logic, reproduced exactly here so
the totals match bench.csv: 82/307, 47/255, 83/497). checks.py's main() walks the SAME blocks list (its
`READS` file, mirrored by reads_path()) and stamps every value it measures with region(b) = the same
[cx-w/2-4, cy-h/2-4, cx+w/2+4, cy+h/2+4] box, into labels.json (every fully-checked value, pass or fail)
and exceptions.json (every fail plus every unmatched/queued label). So: exact region-box match to
labels.json/exceptions.json tells us what checks.py did with a token, with no need to re-run its
geometry (leader tracing, nearest-line search, arc stitching). A table cell never reaches checks.py's
loop at all (masked by FURNITURE before the loop starts) -- those are matched instead to tags_checks.csv
by kind + value (checks.azimuth()/float, since tables.py re-checks them under a completely different
association: tag leaders on the drawing, not label-to-line).

usage: python spike/coverage_attrib.py --snap <frozen out dir>
  -> spike/out_coverage/attribution.md, spike/out_coverage/crops/*.png
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT / "spike"
sys.path.insert(0, str(SPIKE))
from checks import (  # noqa: E402 -- module import only: no OUT/PDF-dependent function is ever called
    ANG_TOK, AREA_CTX, BEAR, DIST, LEN_TOK, NOTES_CTX, RAD_TOK, STATION, TOKEN,
    alignment_table_regions, azimuth, line_curve_table_regions,
)

OUTDIR = SPIKE / "out_coverage"
CROPS = OUTDIR / "crops"

SHEETS = {
    "presidio": {"pdf": ROOT / "Sample Data" / "Right-of-Way Map Record" / "r_10434_002_2020-09-16.pdf", "sub": ""},
    "r10434_1": {"pdf": ROOT / "Sample Data" / "d4" / "r_10434_001_2020-09-16.pdf", "sub": "r_10434_001_2020-09-16"},
    "r10434_3": {"pdf": ROOT / "Sample Data" / "d4" / "r_10434_003_2020-09-16.pdf", "sub": "r_10434_003_2020-09-16"},
}
BUCKET_NAMES = {
    "a-table": "not a drawing label: table cell (no tag-check found)",
    "a-titleblock": "not a drawing label: title block / notes / legend",
    "a-curvedata": "not a drawing label: curve data R=/Δ/L=, checked via L=R*Δ elsewhere",
    "a-station": "not a drawing label: stationing number",
    "a-area": "not a drawing label: area/acreage figure",
    "a-notes": "not a drawing label: coordinate-basis note (EPOCH/DATUM)",
    "a-runtotal": "not a drawing label (as checked): a bare '(T)' run total, silently skipped by the distance branch's is_total guard",
    "a-radial": "not a drawing label: radial bearing, deliberately not checked",
    "b-duplicate": "counted twice: same value within 8pt of another counted block",
    "c-table-tag": "checked as a table tag instead (tags_checks.csv, L#/C# row)",
    "d-pass": "reached a check and passed (counted in bench's coverage numerator)",
    "d-pass-arc": "reached a check and passed as an arc-length row (bench's coverage numerator skips this check column)",
    "e-fail": "reached a check and failed",
    "f-queued": "queued with a reason (exceptions.json)",
    "g-dropped": "dropped silently: never became a check or exception",
}


def region(b):
    return (round(b["cx"] - b["w"] / 2 - 4), round(b["cy"] - b["h"] / 2 - 4),
            round(b["cx"] + b["w"] / 2 + 4), round(b["cy"] + b["h"] / 2 + 4))


def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def reads_path(o):
    """Mirror bench.py's reads_path()/georef.py's READS choice, read-only, no OUT/env coupling."""
    rs, rg, rr, rt = o / "read_shx.json", o / "read_glyph.json", o / "read_rapid.json", o / "tables.json"

    def has_text(p):
        if not p.exists() or p.stat().st_size < 2:
            return False
        try:
            return any(b.get("text") for b in json.loads(p.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            return False

    def has_rows(p):
        if not p.exists():
            return False
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        return isinstance(t, dict) and any(not k.startswith("_") for k in t)

    validated = has_rows(rt)
    return rs if has_text(rs) else (rg if rg.exists() and rg.stat().st_size > 2 and (validated or not rr.exists()) else rr)


def sheet_decimal_majority(blocks):
    """checks.set_decimals()'s own majority rule, reproduced read-only: which decimal count this sheet's
    real (mutated, per-sheet) DIST/TOKEN narrows to. bench.py's denominator uses the generic {2,3}
    import-time DIST/TOKEN (never narrowed) -- a token with the OFF-majority decimal count is counted by
    bench but is invisible to checks.py's real run: it never becomes a token there at all."""
    two = sum(len(re.findall(r"(?<![\d.,])\d{1,4}\.\d{2}(?!\d)", b["text"])) for b in blocks)
    three = sum(len(re.findall(r"(?<![\d.,])\d{1,4}\.\d{3}(?!\d)", b["text"])) for b in blocks)
    return "3" if three > two else "2"


def dist_value(text):
    return float(text.rstrip("'").replace(",", "").split("(")[0])


def classify(key):
    info = SHEETS[key]
    o = (Path(SNAP) / info["sub"]) if info["sub"] else Path(SNAP)
    blocks = load(reads_path(o), [])
    majority = sheet_decimal_majority(blocks)
    frame_j = load(o / "frame.json", {"furniture": []})
    tables_j = load(o / "tables.json", {})
    course_regs = [tuple(x) for x in tables_j.get("_regions", [])] + [tuple(x) for x in line_curve_table_regions(blocks)]
    align_regs = [tuple(x) for x in alignment_table_regions(blocks)]
    table_regs = course_regs + align_regs
    furn_regs = [tuple(x) for x in frame_j.get("furniture", [])]
    labels_j = load(o / "labels.json", [])
    exc_j = load(o / "exceptions.json", [])
    tags_rows = list(csv.DictReader(open(o / "tags_checks.csv", encoding="utf-8"))) if (o / "tags_checks.csv").exists() else []

    by_reg_lab, by_reg_exc = {}, {}
    for l in labels_j:
        by_reg_lab.setdefault(tuple(l.get("region", [])), []).append(l)
    for e in exc_j:
        by_reg_exc.setdefault(tuple(e.get("region", [])), []).append(e)

    def in_regs(b, regs):
        return any(x0 <= b["cx"] <= x1 and y0 <= b["cy"] <= y1 for x0, y0, x1, y1 in regs)

    items = []
    for b in blocks:
        text = b.get("text", "")
        lines = text.replace(" ", "").split("|")
        parts = [m.group(0) for t in lines for m in TOKEN.finditer(t)] or lines
        bear_hit = any(BEAR.match(p) for p in parts)
        dist_hit = any(DIST.match(p) for p in parts)
        if not bear_hit and not dist_hit:
            continue
        reg = region(b)
        curve_data = any(ANG_TOK.search(t) or RAD_TOK.search(t) or LEN_TOK.search(t) or re.match(r"^[RL][=\-:]", t) for t in lines)
        is_station, is_area, is_notes = bool(STATION.search(text)), bool(AREA_CTX.search(text)), bool(NOTES_CTX.search(text))
        is_align = in_regs(b, align_regs)
        is_table = is_align or in_regs(b, course_regs)
        is_furn = is_table or in_regs(b, furn_regs)

        for kind, hit, matcher in (("bearing", bear_hit, BEAR), ("distance", dist_hit, DIST)):
            if not hit:
                continue
            rep = next(p for p in parts if matcher.match(p))
            item = {"sheet": key, "kind": kind, "text": rep, "block_text": text, "region": list(reg), "cx": b["cx"], "cy": b["cy"], "w": b["w"], "h": b["h"]}
            if is_furn:
                if is_table:
                    # a table's curve row prints R= and L= cells too (checked as "radius"/"arc length" by
                    # tables.py, not "distance") -- both are DIST-shaped tokens on the sheet. Matched by
                    # value, not 1:1 consumed: two curves can legitimately share one design radius/length,
                    # and this join only needs to know whether SOME table-tag check saw this value.
                    check_kinds = {"bearing": ("bearing",), "distance": ("distance", "arc length", "radius")}[kind]
                    match = None
                    for r in tags_rows:
                        if r["check"] not in check_kinds:
                            continue
                        try:
                            ok_match = abs(azimuth(rep) - azimuth(r["printed"])) < 1e-4 if kind == "bearing" else abs(dist_value(rep) - float(r["printed"])) < 0.005
                        except Exception:
                            ok_match = False
                        if ok_match:
                            match = r
                            break
                    if match:
                        item["bucket"], item["reason"] = "c-table-tag", f"table cell for tag {match['tag']} ({match['check']}): {match['result']}"
                    elif kind == "bearing" and BEAR.match(rep) and BEAR.match(rep)[6]:
                        item["bucket"], item["reason"] = "a-table", "radial-bearing column of the curve table; tags_checks.csv has no radial-bearing check"
                    elif is_align:
                        item["bucket"], item["reason"] = "a-table", "STATION/NORTHING/EASTING alignment table cell; checked (if at all) by record_checks.py against the fit, not by tags_checks.csv"
                    else:
                        item["bucket"], item["reason"] = "a-table", "table cell, no matching row in tags_checks.csv (tag's own row never checked)"
                else:
                    item["bucket"], item["reason"] = "a-titleblock", "dense upright text block (title block / notes / legend)"
                items.append(item)
                continue
            lab_kinds = ("bearing", "chord bearing") if kind == "bearing" else ("distance", "chord distance", "arc")
            exc_kinds = ("bearing",) if kind == "bearing" else ("distance", "arc length")
            match_lab = next((l for l in by_reg_lab.get(reg, []) if l.get("kind") in lab_kinds), None)
            if match_lab:
                ck = match_lab.get("kind")
                if match_lab.get("ok"):
                    # bench.py's own coverage formula (run(), "passes = sum(...res[k]... for k in
                    # ('distance','bearing'))") only sums checks.csv rows whose check column is
                    # "distance"/"bearing"/"chord distance"/"chord bearing" -- a distance TOKEN that
                    # passed as an "arc length" row (a standalone L= label, or a bare distance beside a
                    # curve) is a genuine pass bench's own arithmetic never adds in. Split it out so the
                    # table shows this separately from an honest miss.
                    item["bucket"] = "d-pass-arc" if ck == "arc" else "d-pass"
                else:
                    item["bucket"] = "e-fail"
                item["reason"] = f"checked as {ck} ({match_lab.get('how')})"
                items.append(item)
                continue
            match_exc = next((e for e in by_reg_exc.get(reg, []) if e.get("kind") in exc_kinds and "issue" in e), None) \
                or next((e for e in by_reg_exc.get(reg, []) if "issue" in e), None)
            if match_exc:
                item["bucket"], item["reason"] = "f-queued", match_exc.get("issue")
                items.append(item)
                continue
            match_fail = next((e for e in by_reg_exc.get(reg, []) if e.get("kind") in exc_kinds), None)
            if match_fail:
                item["bucket"], item["reason"] = "e-fail", "measured off-tolerance (exceptions.json only, e.g. curve L=R*delta)"
                items.append(item)
                continue
            if kind == "distance" and "(T)" in rep:
                # dist_num()'s is_total flag: checks.py's distance branch is `if is_total or curve_data or
                # ...: continue` -- a BARE "860.77'(T)" (no "L=" prefix) has no run-sum fallback the way a
                # standalone "L=573.93'(T)" block does (that one is caught earlier, as an arc-length
                # label, len(lines)==1 and LEN.match); it is dropped outright, unconditionally.
                item["bucket"], item["reason"] = "a-runtotal", "bare '(T)' run total (no L= prefix): distance branch's is_total guard drops it outright, no run-sum fallback"
            elif kind == "distance" and curve_data:
                item["bucket"], item["reason"] = "a-curvedata", "curve-data block (R=/Δ=/L=): distance branch silently skips curve_data blocks"
            elif kind == "distance" and is_station:
                item["bucket"], item["reason"] = "a-station", "stationing number (STATION context)"
            elif kind == "distance" and is_area:
                item["bucket"], item["reason"] = "a-area", "area/acreage figure (AREA_CTX)"
            elif kind == "distance" and is_notes:
                item["bucket"], item["reason"] = "a-notes", "coordinate-basis note text (EPOCH/DATUM)"
            elif kind == "bearing" and BEAR.match(rep) and BEAR.match(rep)[6]:
                item["bucket"], item["reason"] = "a-radial", "radial bearing (R): checks.py logs it, never checks it"
            elif kind == "distance" and re.search(r"\.(\d+)", rep) and len(re.search(r"\.(\d+)", rep)[1]) != int(majority):
                n_dec = len(re.search(r"\.(\d+)", rep)[1])
                item["bucket"], item["reason"] = "g-dropped", f"decimal-convention mismatch: sheet's real DIST/TOKEN only accept {majority}-decimal distances (set_decimals), this token has {n_dec}"
            else:
                item["bucket"], item["reason"] = "g-dropped", "no check, no exception, no known skip reason"
            items.append(item)

    # (b) counted twice: same kind+value within 8pt of another counted block, different region
    def val_key(it):
        try:
            return round(azimuth(it["text"]), 3) if it["kind"] == "bearing" else round(dist_value(it["text"]), 2)
        except Exception:
            return it["text"]
    n = len(items)
    for i in range(n):
        if items[i]["bucket"] == "b-duplicate":
            continue
        for j in range(i + 1, n):
            if items[j]["bucket"] == "b-duplicate" or items[i]["kind"] != items[j]["kind"] or items[i]["region"] == items[j]["region"]:
                continue
            if abs(items[i]["cx"] - items[j]["cx"]) > 8 or abs(items[i]["cy"] - items[j]["cy"]) > 8:
                continue
            if val_key(items[i]) != val_key(items[j]):
                continue
            items[j]["orig_bucket"], items[j]["bucket"] = items[j]["bucket"], "b-duplicate"
            items[j]["reason"] = f"same {items[j]['kind']} value within 8pt of another counted block (that one: {items[i]['bucket']})"
    return items, {"blocks": len(blocks), "majority_decimals": majority}


def crop(pdf_path, item, out_path, pad=70):
    page = pymupdf.open(pdf_path)[0]
    x0, y0, x1, y1 = item["region"]
    R = pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad) & page.rect
    z = min(300 / 72, 900 / max(R.width, R.height, 1))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), clip=R, alpha=False)
    im = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()
    f = lambda x, y: (int((x - R.x0) * z), int((y - R.y0) * z))
    cv2.rectangle(im, f(x0, y0), f(x1, y1), (0, 0, 220), 2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
    page.parent.close()


def sample(items, n):
    """Evenly spread across sheets, deterministic (index stride, not random)."""
    if len(items) <= n:
        return items
    step = len(items) / n
    return [items[int(i * step)] for i in range(n)]


def build_report(all_items, meta):
    import collections
    lines = ["# Coverage attribution: where every parsed bearing/distance token goes\n",
              "One item per (block, kind) that spike/bench.py's read_cols() counts toward "
              "bearings_parsed/distances_parsed. Denominators below match bench.csv exactly "
              "(82/307, 47/255, 83/497 -- bucket d-pass alone, not d-pass+d-pass-arc).\n"]
    all_flat = []
    for key, items in all_items.items():
        all_flat.extend(items)
        c = collections.Counter(it["bucket"] for it in items)
        lines.append(f"## {key} ({len(items)} tokens, {meta[key]['blocks']} blocks read, "
                     f"majority {meta[key]['majority_decimals']}-decimal distances)\n")
        lines.append("| bucket | n | meaning |")
        lines.append("|---|---|---|")
        for b, n in sorted(c.items(), key=lambda x: -x[1]):
            lines.append(f"| {b} | {n} | {BUCKET_NAMES.get(b, b)} |")
        lines.append(f"| **total** | **{sum(c.values())}** | = bearings_parsed + distances_parsed |\n")

    # crops: bucket g (all sheets; empty once (T) run-totals were root-caused -- shown as a-runtotal
    # instead, viewed here so that root cause is checked, not just asserted) and the single biggest
    # non-check ("a-*"/"c-*") reason
    g_items = [it for it in all_flat if it["bucket"] == "g-dropped"]
    runtotal_items = [it for it in all_flat if it["bucket"] == "a-runtotal"]
    reason_counts = collections.Counter((it["bucket"], it["reason"]) for it in all_flat if it["bucket"].startswith(("a-", "c-")))
    (top_bucket, top_reason), top_n = reason_counts.most_common(1)[0]
    top_items = [it for it in all_flat if it["bucket"] == top_bucket and it["reason"] == top_reason]

    g_title = ("bucket g-dropped is EMPTY (0/0/0): every token resolved to a named reason once the "
               "'(T)' run-total guard (a-runtotal) was added. Shown here instead: every a-runtotal token") \
        if not g_items else "bucket g-dropped: every occurrence, viewed"
    for title, slug, pool in ((g_title, "g", (runtotal_items if not g_items else g_items)),
                              (f"biggest single reason ({top_n} tokens): {top_bucket} / {top_reason}", "top", sample(top_items, 12))):
        lines.append(f"## Crops: {title}\n")
        for i, it in enumerate(pool):
            png = CROPS / f"{slug}_{i:02d}_{it['sheet']}.png"
            crop(SHEETS[it["sheet"]]["pdf"], it, png)
            lines.append(f"- `{png.relative_to(ROOT)}` -- {it['sheet']} {it['kind']} `{it['text']}` "
                         f"(reason: {it['reason']}) -- VERDICT: _pending_")
        lines.append("")
    return "\n".join(lines), g_items, top_bucket, top_reason


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snap", required=True)
    args = ap.parse_args()
    global SNAP
    SNAP = args.snap

    OUTDIR.mkdir(parents=True, exist_ok=True)
    all_items, meta = {}, {}
    for key in SHEETS:
        items, m = classify(key)
        all_items[key] = items
        meta[key] = m
        print(f"{key}: {len(items)} items, majority decimals {m['majority_decimals']}")

    (OUTDIR / "items.json").write_text(json.dumps(all_items, indent=1), encoding="utf-8")
    md, g_items, top_bucket, top_reason = build_report(all_items, meta)
    (OUTDIR / "attribution.md").write_text(md, encoding="utf-8")
    print("wrote", OUTDIR / "items.json", "and", OUTDIR / "attribution.md")
    print(f"g-dropped total: {len(g_items)}; biggest single reason: {top_bucket} / {top_reason}")


if __name__ == "__main__":
    main()
