"""Layer name grammar: classify a CAD path by its OCG layer name (`page.get_drawings()[i]["layer"]`).

Civil 3D layer names carry structure (RW-<discipline>-<kind>-...; a few legacy MicroStation-style
names, rw_<kind>_...). classify() reads the name's tokens, case-insensitive, in a fixed order: the
first test a name satisfies wins, mask first, unknown last. Grammar tokens only -- never a sheet's
own layer name, so this generalises past Presidio.

cls in {linework, leader, label, point, table, furniture, mask, unknown}; sub, for linework only,
in {parcel, alignment, other}.

usage: [SHEET=<pdf>] python spike/layers.py   -> self-check + per-class path counts for SHEET
"""
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

_MASK = re.compile(r"wipeout", re.I)
_LEADER_LBL = re.compile(r"lbl", re.I)
_LEADER_TAIL = re.compile(r"-line$|leader", re.I)
_LNWK = re.compile(r"lnwk", re.I)
_LABEL = re.compile(r"lbl|anno|text|txt|att_fields|sheettx", re.I)
_POINT = re.compile(r"pnt|point", re.I)
_TABLE = re.compile(r"tbl", re.I)
_FURNITURE = re.compile(r"sheet_format|border|sheet|record_map|appraisal_map|misc|seal", re.I)
_LINEWORK = re.compile(r"lnwk|parcel|seg|ease|algn|rw_|rw-lnwk", re.I)
_SUB_PARCEL = re.compile(r"parcel|ease|landnet", re.I)
_SUB_ALGN = re.compile(r"algn", re.I)


def _sub(n):
    return "parcel" if (_SUB_PARCEL.search(n) or n.lower().startswith("rw_")) else "alignment" if _SUB_ALGN.search(n) else "other"


def classify(name):
    """(cls, sub) for a CAD OCG layer name, case-insensitive. sub is set only for linework."""
    n = name or ""
    if _MASK.search(n):
        return "mask", None
    if _LEADER_LBL.search(n) and _LEADER_TAIL.search(n):
        return "leader", None
    if _LNWK.search(n):
        # a name with LNWK is drawn linework even where it also carries a label token (Civil 3D's
        # label-associated alignment sub-layer, RW-ALGN-LNWK-LBL-NEW-NCR-AC, still draws real record
        # edges interleaved with RW-ALGN's other linework layers -- measured on Presidio: excluding it
        # broke chain bridging across a genuine boundary run). LNWK beats a co-occurring LBL; the
        # leader test above already took the -Line/LEADER-suffixed variant of this same family.
        return "linework", _sub(n)
    if _LABEL.search(n):
        return "label", None
    if _POINT.search(n):
        return "point", None
    if _TABLE.search(n):
        return "table", None
    if _FURNITURE.search(n):
        return "furniture", None
    if _LINEWORK.search(n) or n.lower().startswith("rw_"):
        return "linework", _sub(n)
    return "unknown", None


def page_classes(page):
    """(cls, sub) per path, aligned with page.get_drawings() index."""
    return [classify(d.get("layer")) for d in page.get_drawings()]


def has_layers(page):
    """True if any path on this page carries a non-empty CAD layer name."""
    return any(d.get("layer") for d in page.get_drawings())


# Presidio (R-10434.2) layer facts from STATE.md's 2026-09-23 CAD-structure note, used as a grammar
# self-check: names not seen there must still classify by the same tokens (r_10434_001/003, etc).
_FACTS = [
    ("RW-PARCEL-SEG-REACQUISITION", "linework", "parcel"),
    ("RW-PARCEL-SEG-Directors_Deeds", "linework", "parcel"),
    ("rw_EASE_EXIST_align", "linework", "parcel"),
    ("RW-ALGN-LNWK-EXIST-XA", "linework", "alignment"),
    ("RW-ALGN-LNWK-EXIST-XRA", "linework", "alignment"),
    ("RW-ALGN-LNWK-EXIST-XCL-Style", "linework", "alignment"),
    ("RW-ALGN-LNWK-LBL-NEW-NCR-AC-Line", "leader", None),
    ("RW-ALGN-LBL-NEW-NRA", "label", None),
    ("RW-ALGN-LBL-NEW-NR", "label", None),
    ("RW-ALGN-LBL-EXIST-XRA", "label", None),
    ("RW-ALGN-LBL", "label", None),
    ("RW-SHEET-PARCEL-ATT_FIELDS", "label", None),
    ("rw_map_anno_Record_Map", "label", None),
    ("rw_map_anno", "label", None),
    ("SHEET-ANNO", "label", None),
    ("SHEET-ANNO-ACTION_FIELDS", "label", None),
    ("SHEETTX", "label", None),
    ("SU-FIG-PNT-MARK", "point", None),
    ("RW-TBL", "table", None),
    ("RW-SHEET-TBL", "table", None),
    ("110_Sheet_Format", "furniture", None),
    ("border", "furniture", None),
    ("RW-SHEET-MISC", "furniture", None),
    ("RW-SHEET-Record_Map", "furniture", None),
    ("RW-SHEET-Appraisal_Map", "furniture", None),
    ("_Wipeout_Areas", "mask", None),
    ("rw_topo_Wipeout_Areas", "mask", None),
    ("", "unknown", None),
]


def main():
    for name, cls, sub in _FACTS:
        got = classify(name)
        assert got == (cls, sub), f"{name!r}: expected {(cls, sub)}, got {got}"
    print(f"self-check: {len(_FACTS)} Presidio layer names classify as stated")

    sys.path.insert(0, str(Path(__file__).parent))
    from georef import PDF  # noqa: E402
    page = pymupdf.open(PDF)[0]
    print(f"SHEET={PDF} | has_layers: {has_layers(page)}")
    counts, subs = Counter(), Counter()
    for cls, sub in page_classes(page):
        counts[cls] += 1
        if sub:
            subs[(cls, sub)] += 1
    for cls, n in counts.most_common():
        print(f"  {cls:10} {n}")
    for (cls, sub), n in subs.most_common():
        print(f"    {cls}/{sub:9} {n}")


if __name__ == "__main__":
    main()
