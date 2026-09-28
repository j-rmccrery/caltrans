"""Truth for 34 text boxes on the 1969 scan R-65.2, keyed by eye from 4x crops (spike/out/scan_boxes_*.png).

Key = box id in spike/out/r_00065_002_1969-09-01_sn-02048/read_rapid.json; value = the one line that
box covers, as printed. Scoring compares the digit string (letters, dots and symbols are structure
the parser can repair; the digits are the record).
"""
TRUTH = {
    186: "N9996.26", 41: "E13540.21", 253: "E12692.22", 133: "N.10162.42", 82: "E.12640.84",
    165: "N.10010.89", 184: "E.13440.89", 234: "N.10018.76", 14: "E.12943.43", 261: "N.10001.91",
    249: "E.14000", 97: "E.12000",
    209: "0°40'21\"", 228: "21°00'11\"", 229: "21°00'11\"", 196: "21°00'11\"",
    1: "17859",
    136: "1311.66'", 47: "R=1472'", 206: "1122.09'", 239: "51.37'", 42: "539.59'", 15: "1015.13'",
    189: "515.40'", 161: "R=3500'", 121: "602.23'", 107: "R=3425'", 110: "R=3434'", 119: "762.88'",
    111: "100.12'", 211: "98.33'", 164: "S.79°12'59\"E.632.31'",
}


def digits(s):
    return "".join(ch for ch in s if ch.isdigit())


if __name__ == "__main__":
    import json, sys
    from pathlib import Path
    reads = {b["id"]: b for b in json.load(open(Path(__file__).parent / "out" / "r_00065_002_1969-09-01_sn-02048" / "read_rapid.json", encoding="utf-8"))}
    ok = 0
    for k, v in TRUTH.items():
        got = reads[k]["text"]
        hit = digits(got) == digits(v)
        ok += hit
        print(f"  {k:4} {'ok ' if hit else 'BAD'} truth {v!r:26} ocr {got!r}")
    print(f"RapidOCR digits exact: {ok}/{len(TRUTH)}")
