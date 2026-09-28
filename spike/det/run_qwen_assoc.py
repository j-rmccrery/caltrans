"""Trial B: qwen2.5vl:7b label-to-line ASSOCIATION as a second opinion.

For every keyed label in spike/gold/presidio_assoc.json with correct_line true/false, sends the
crop (spike/out_gold/presidio/<file>: printed value boxed red, candidate line boxed blue) and asks
a yes/no question, no verdict leak. Scores against correct_line. Runs two prompt variants.

usage: python spike/det/run_qwen_assoc.py [--limit N]
"""
import base64
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLD_DIR = HERE.parent / "gold"
CROP_DIR = HERE.parent / "out_gold" / "presidio"

PROMPT_A = ('In this survey drawing crop, the red box marks a printed measurement label. '
            'The blue highlighted line is a candidate for the line that label describes. '
            'Does the label belong to the blue line? Answer yes or no, then one short reason.')

PROMPT_B = ('You are checking a candidate line-label pairing on a survey drawing crop. '
            'A printed measurement is boxed in red. One drawn line is highlighted in blue as a '
            'CANDIDATE match -- it may be wrong. Look only at whether the red label sits along, '
            'at the end of, or clearly annotates the blue line specifically, not any other line '
            'in the crop. If you are not confident the label describes the blue line, answer no. '
            'Answer with exactly one word, yes or no, on the first line, then one short reason on '
            'the second line.')


def ask(png_bytes, prompt):
    req = {"model": "qwen2.5vl:7b", "stream": False, "options": {"temperature": 0},
           "prompt": prompt, "images": [base64.b64encode(png_bytes).decode()]}
    r = urllib.request.urlopen(urllib.request.Request(
        "http://localhost:11434/api/generate", json.dumps(req).encode(), {"Content-Type": "application/json"}),
        timeout=120)
    return json.load(r)["response"].strip()


def parse_yn(resp):
    m = re.search(r"\b(yes|no)\b", resp, re.I)
    return m.group(1).lower() if m else "?"


def run_variant(name, prompt, items, files):
    print(f"\n=== variant {name} ===")
    conf = {("true", "yes"): 0, ("true", "no"): 0, ("false", "yes"): 0, ("false", "no"): 0}
    unparsed = 0
    errors = []
    t_start = time.time()
    for it in items:
        f = CROP_DIR / files[it["id"]]
        png = f.read_bytes()
        t0 = time.time()
        try:
            resp = ask(png, prompt)
        except Exception as e:
            print(f"  {it['id']} FAILED {type(e).__name__}: {e}")
            continue
        dt = time.time() - t0
        yn = parse_yn(resp)
        gt = it["correct_line"]
        if yn == "?":
            unparsed += 1
        else:
            conf[(gt, yn)] += 1
        wrong = (yn != "?" and ((gt == "true" and yn == "no") or (gt == "false" and yn == "yes")))
        if wrong:
            errors.append((it["id"], it["kind"], it["printed"], gt, yn, resp.replace("\n", " | ")[:160]))
        print(f"  {it['id']:10} gt={gt:5} -> {yn:3} ({dt:.1f}s){'  *** ERROR' if wrong else ''}")
    total_dt = time.time() - t_start
    n = len(items)
    acc = (conf[("true", "yes")] + conf[("false", "no")]) / max(n - unparsed, 1)
    print(f"\nvariant {name}: {n} items, {total_dt:.1f}s total, {total_dt / n:.1f}s/call")
    print(f"  confusion: true->yes {conf[('true','yes')]}  true->no {conf[('true','no')]}  "
          f"false->yes {conf[('false','yes')]}  false->no {conf[('false','no')]}  unparsed {unparsed}")
    print(f"  accuracy {acc:.3f}  (chance if always 'yes': {sum(1 for it in items if it['correct_line']=='true')/n:.3f})")
    print(f"  errors ({len(errors)}):")
    for e in errors:
        print(f"    {e[0]} kind={e[1]} printed={e[2]!r} gt={e[3]} got={e[4]} reason={e[5]!r}")
    return conf, unparsed, errors


def main():
    gold = json.load(open(GOLD_DIR / "presidio_assoc.json", encoding="utf-8"))
    manifest = json.load(open(CROP_DIR / "_manifest.json", encoding="utf-8"))
    files = {m["id"]: m["file"] for m in manifest}
    items = [g for g in gold if g["correct_line"] in ("true", "false") and g["id"] in files]
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
        items = items[:limit]
    if "--sample-true" in sys.argv:
        # time-box cut: keep every false (rare, high-signal) + an evenly spaced sample of true
        n_true_target = int(sys.argv[sys.argv.index("--sample-true") + 1])
        false_items = [it for it in items if it["correct_line"] == "false"]
        true_items = [it for it in items if it["correct_line"] == "true"]
        step = max(len(true_items) // n_true_target, 1)
        true_sample = true_items[::step][:n_true_target]
        items = false_items + true_sample
        items.sort(key=lambda it: it["id"])
    print(f"{len(items)} keyed labels (true/false only) of {len(gold)} total in gold set")
    n_true = sum(1 for it in items if it["correct_line"] == "true")
    print(f"true={n_true} false={len(items) - n_true}")

    run_variant("A_asis", PROMPT_A, items, files)
    run_variant("B_strict", PROMPT_B, items, files)


if __name__ == "__main__":
    main()
