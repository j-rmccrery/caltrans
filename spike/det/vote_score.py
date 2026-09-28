"""Vote between the old scan detector (RapidOCR-1.4.4, read_rapid.json) and the new one
(PP-OCRv5-server, read_v5.json, spike/scan_read_v5.py) on the 32 keyed truth boxes
(spike/gt_scan.py), per loop16's send-back item 4: scan_consensus.pick_reader per keyed
location, structural-validity-then-confidence, no truth in the vote itself -- truth is used only
afterwards, to grade old / new / voted. Isolated in spike/det/, writes nothing outside it.

usage: SHEET=<scan.pdf> python spike/det/vote_score.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
sys.path.insert(0, str(SPIKE))
from gt_scan import TRUTH, digits  # noqa: E402
from det_score import match_truth, RAPID  # noqa: E402
from scan_consensus import pick_reader  # noqa: E402

STEM = "r_00065_002_1969-09-01_sn-02048"
V5 = SPIKE / "out" / STEM / "read_v5.json"


def main():
    rapid = {b["id"]: b for b in json.load(open(RAPID, encoding="utf-8"))}
    v5 = json.load(open(V5, encoding="utf-8"))
    matches = match_truth(v5)
    hits = {"old": 0, "new": 0, "vote": 0}
    for k, want in sorted(TRUTH.items()):
        old = rapid[k]
        idx, cov = matches[k]
        new = v5[idx] if idx is not None else {"text": "", "conf": 0.0}
        voted, src = pick_reader(old["text"], old["conf"], new["text"], new["conf"])
        ho = digits(old["text"]) == digits(want)
        hn = digits(new["text"]) == digits(want)
        hv = digits(voted) == digits(want)
        hits["old"] += ho; hits["new"] += hn; hits["vote"] += hv
        print(f"  {k:4} truth {want!r:24} old {old['text']!r:22}{'OK' if ho else '--'}  "
              f"new {new['text']!r:22}{'OK' if hn else '--'}  vote[{src}] {voted!r:22}{'OK' if hv else '--'}")
    print(f"old {hits['old']}/{len(TRUTH)}  new {hits['new']}/{len(TRUTH)}  voted {hits['vote']}/{len(TRUTH)}")


if __name__ == "__main__":
    main()
