"""Loop4 legD gate evidence: 8 of the 12 L34-45 table distance cells that used to be read as spurious
standalone distance labels (masked out by line_curve_table_regions, checks.py) -- red label box, blue
the WRONG line checks.py used to measure it against before the fix (from exceptions_before.json, a
throwaway snapshot with NO_LC_TABLES=1 set). None of these is the line the label describes: the label
is a table row (an L# course's printed distance), not a callout on the drawing at all.
usage: SHEET="Sample Data/d4/r_10434_003_2020-09-16.pdf" python spike/legD_fixed_crops.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF  # noqa: E402
from legD_crops import caption_tile, grid  # noqa: E402
import pymupdf


def main():
    page = pymupdf.open(PDF)[0]
    before = json.loads((OUT / "exceptions_before.json").read_text(encoding="utf-8"))
    after_keys = {(e["kind"], e["text"], tuple(e["region"])) for e in json.loads((OUT / "exceptions_after.json").read_text(encoding="utf-8"))
                  if "issue" not in e}
    removed = [e for e in before if "issue" not in e and (e["kind"], e["text"], tuple(e["region"])) not in after_keys]
    removed.sort(key=lambda e: abs(e.get("off_ft", e.get("off_arcmin", 0))), reverse=True)
    picks = removed[:8]
    grid(page, picks, "legD_fixed.png")


if __name__ == "__main__":
    main()
