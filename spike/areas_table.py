"""Loop18 leg 1: read the "AREAS (square feet or as noted)" table printed on each sheet -- PARCEL#,
TITLE CODE, GRANTOR, TOTAL/EXCESS/REMAINDER acreage, TYPE, DOC.#, DATE, REMARKS -- so parcels can be
scored against the record's own official area, not just recon.py's geometric closure test. JR
(2026-09-28): "Parcels are scored against the official AREAS tables printed on the sheets."

Method: chain every text block shaped like a parcel id (PARCEL_ID_RE) sitting in the PARCEL# header's
own column (same column-chaining discipline recon.radial_table_regions() already uses for an R-# table),
then for each row take the REMARKS column's own text at (about) the same row height -- this drafter
prints each row's own record area as the REMARKS cell's own leading number+unit ("6,970 S.F. HIGHWAY
ESMT. AT GRADE", "10.46 AC. HIGHWAY ESMT. AT GRADE"), separate from the TOTAL column (the *parent*
parcel's own acreage, repeated identically down the whole table -- never this row's own area; skipped by
requiring the REMARKS column's own x band, well right of TOTAL's). Works on both a SHX-readable sheet
(Presidio, R-10434.1/.3: real_text_blocks()/read_shx.json) and an OCR-only sheet (R-10741.1/.2/.3:
read_rapid.json) -- both share the same {cx, cy, text} block shape; OCR noise (missing commas/periods,
fused tokens) shows up as a parcel row this reader cannot place, not a crash.

usage: SHEET=<pdf> python spike/areas_table.py     (prints this sheet's own AREAS rows; unset SHEET for presidio)
       python spike/areas_table.py --selftest
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT, PDF, DEFAULT, READS, real_text_blocks  # noqa: E402

PARCEL_ID_RE = re.compile(r"^\d{4,6}(-\d{1,3})?$")     # "61806-9", "9178-16", "63269"
COL_X_TOL_PT = 45.0     # pt: how far a candidate parcel-id block's own cx may sit from the PARCEL#
                         # header's own cx and still count as that column (measured: Presidio's own
                         # column sits within a few pt of its header at every row)
ROW_REACH_PT = 10.0     # pt: how far below the header row a table may start (measured: Presidio/R-10434.1
                         # both put their first data row 23 pt below the PARCEL# header; 10 pt keeps out
                         # only the header row's own other cells, never a real first data row)
MAX_TABLE_PT = 700.0    # pt: generous cap on how far below the header the PARCEL# column may run
REMARKS_X_LO_PT = -150.0  # pt: REMARKS column search band, relative to the REMARKS header's own cx --
                          # a data cell's own text starts well left of the (shorter, roughly centred)
                          # "REMARKS" header label itself (measured: Presidio/R-10434.1 both start their
                          # own REMARKS text 70-90 pt left of the header's own cx)
REMARKS_X_HI_PT = 250.0
ROW_Y_TOL_PT = 7.0      # pt: how far off the parcel-id row's own cy a REMARKS block may sit and still
                         # be THIS row's own remarks -- must stay under half the table's own row pitch
                         # (measured 13-15 pt on Presidio/R-10434.1) or a neighbouring row's own REMARKS
                         # cell qualifies as a candidate too; same-row jitter between two cells of one
                         # printed row measured well under 1 pt, so 7 pt keeps full margin on "same row"
                         # while excluding the next row up or down

AREA_RE = re.compile(
    r"^\*?\s*([\d,]+\.?\d{0,3})\s*(AC\.?RES?|AC\.?|S\.?\s*F\.?|SQ\.?\s*F(?:EE)?T?\.?)\b", re.I)


def area_sqft(text):
    """Leading '<number> <unit>' at the start of a REMARKS cell -> sqft, or None. AC(RES) converts by
    43,560; S.F./SQ FT is already sqft. A leading '*' (the TOTAL column's own convention for "see
    footnote") is stripped, never treated as a multiplier."""
    m = AREA_RE.match(text.strip())
    if not m:
        return None
    val = float(m[1].replace(",", ""))
    unit = m[2].upper().replace(" ", "").replace(".", "")
    if unit.startswith("AC"):
        return val * 43560.0
    return val


def header_blocks(blocks, pattern):
    return [b for b in blocks if re.match(pattern, b["text"].strip(), re.I)]


def areas_rows(sheet_name=None, blocks=None):
    """-> list of {parcel: str, area_sqft: float|None, remarks: str, cy: float} for every PARCEL#-column
    row found on this sheet (SHEET env already selects the sheet via georef.PDF/OUT; sheet_name is for
    the caller's own bookkeeping only). area_sqft is None where the REMARKS cell's own text does not
    parse (OCR noise, or a row whose own area sits in a differently-shaped cell) -- the row is still
    returned (a parcel a reader could not price is still a parcel in the table, JR's own headline
    denominator)."""
    if blocks is None:
        page = __import__("pymupdf").open(PDF)[0]
        blocks = json.loads(READS.read_text(encoding="utf-8")) + real_text_blocks(page)
    parcel_hdrs = header_blocks(blocks, r"PARCEL\s*#?$")
    remarks_hdrs = header_blocks(blocks, r"REMARKS$")
    if not parcel_hdrs:
        return []
    out = []
    for phdr in parcel_hdrs:
        rhdr = min(remarks_hdrs, key=lambda b: abs(b["cy"] - phdr["cy"])) if remarks_hdrs else None
        col = [b for b in blocks if b is not phdr and PARCEL_ID_RE.match(b["text"].strip())
               and abs(b["cx"] - phdr["cx"]) <= COL_X_TOL_PT
               and ROW_REACH_PT <= b["cy"] - phdr["cy"] <= MAX_TABLE_PT]
        col.sort(key=lambda b: b["cy"])
        for b in col:
            remarks_text, remarks_area = "", None
            if rhdr is not None:
                cands = [ob for ob in blocks if ob is not b
                         and REMARKS_X_LO_PT <= ob["cx"] - rhdr["cx"] <= REMARKS_X_HI_PT
                         and abs(ob["cy"] - b["cy"]) <= ROW_Y_TOL_PT]
                if cands:
                    # ROW_Y_TOL_PT above already GATES "same row" (glyph-baseline jitter between two
                    # cells of one printed row is itself a few tenths of a pt -- not a usable ranking
                    # signal: measured, a same-row TYPE cell's own cy can sit CLOSER to the parcel-id
                    # row's own cy than the true REMARKS cell does). Rank by X-proximity to the REMARKS
                    # header's own column instead -- that is what actually separates the real REMARKS
                    # text (starts nearest the header) from a same-row TYPE/DOC# cell further right.
                    rb = min(cands, key=lambda ob: abs(ob["cx"] - rhdr["cx"]))
                    remarks_text = rb["text"]
                    remarks_area = area_sqft(remarks_text)
            out.append({"parcel": b["text"].strip(), "area_sqft": remarks_area,
                        "remarks": remarks_text, "cx": b["cx"], "cy": b["cy"]})
    return out


def selftest():
    assert abs(area_sqft("6,970 S.F. HIGHWAY ESMT. AT GRADE") - 6970.0) < 1e-6
    assert abs(area_sqft("10.46 AC. HIGHWAY ESMT. AT GRADE") - 10.46 * 43560.0) < 1e-6
    assert abs(area_sqft("13355 SF SLOPE EASEMENT") - 13355.0) < 1e-6, "OCR text with no comma/period must still parse"
    assert abs(area_sqft("*1,505.853 AC.") - 1505.853 * 43560.0) < 1e-6, "a leading '*' must be stripped, not block the parse"
    assert area_sqft("2,518 S.F. PERPETUAL TUNNEL EASEMENT") == 2518.0
    assert area_sqft("SEE NOTE 2") is None, "text with no leading number+unit must not parse"

    blocks = [
        {"text": "PARCEL#", "cx": 300.0, "cy": 1377.0},
        {"text": "REMARKS", "cx": 1168.0, "cy": 1374.0},
        {"text": "61806-1", "cx": 300.0, "cy": 1400.0},
        {"text": "10.46 AC. HIGHWAY ESMT. AT GRADE", "cx": 1098.0, "cy": 1400.0},
        {"text": "61806-2", "cx": 302.0, "cy": 1414.0},
        {"text": "7.21 AC. HIGH VIADUCT ESMT.", "cx": 1080.0, "cy": 1414.0},
        {"text": "*1,505.853 AC.", "cx": 636.0, "cy": 1402.0},   # TOTAL column: must never be picked as REMARKS
        {"text": "SEE NOTE 2", "cx": 1140.0, "cy": 1442.0},       # a row with no clean area (unparsed, still listed)
        {"text": "63269", "cx": 294.0, "cy": 1442.0},
    ]
    rows = areas_rows(blocks=blocks)
    by_id = {r["parcel"]: r for r in rows}
    assert set(by_id) == {"61806-1", "61806-2", "63269"}, by_id
    assert abs(by_id["61806-1"]["area_sqft"] - 10.46 * 43560.0) < 1.0
    assert abs(by_id["61806-2"]["area_sqft"] - 7.21 * 43560.0) < 1.0
    assert by_id["63269"]["area_sqft"] is None and by_id["63269"]["remarks"] == "SEE NOTE 2", \
        "an unparseable REMARKS cell must still return the row, area_sqft None"
    print("areas_table.selftest OK: area_sqft parses AC/S.F./OCR-noise text, skips the TOTAL column's "
          "own '*' acreage; areas_rows chains the PARCEL# column and pairs each row with its own "
          "REMARKS cell by row height, including a row whose own area does not parse")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sheet_name = PDF.stem if PDF != DEFAULT else "presidio"
        rows = areas_rows(sheet_name)
        for r in rows:
            print(r["parcel"], r["area_sqft"], "|", r["remarks"][:70])
        print(f"{len(rows)} AREAS rows, {sum(1 for r in rows if r['area_sqft'] is not None)} with a parsed area")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "areas_table.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
