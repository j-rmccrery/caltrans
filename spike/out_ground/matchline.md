# Matchline check
Sheet pairs checked for actual bbox overlap first (not assumed from numbering); candidate line pairs are heavy (R/W + parcel weight) chains agreeing in direction (<12 deg) with a nearby (<8 m) parallel run and real projected overlap (>5 m) -- but a geometric candidate is not proof it is the SAME record line (a corner where two different courses meet passes the same test, and two genuinely distinct parallel lines can share a bearing by coincidence). A candidate only counts as a matchline measurement when PROVEN: bearing agrees to <=1' and the lines coincide (perp <=0.15 m), or the pieces' drawn endpoints are essentially touching (<=0.1 m) and perp <=0.15 m. Unproven candidates are listed and dropped, not folded into the stats. The cleanest measure of all, where available, is the ground-position offset between the SAME printed bearing/distance label appearing on both sheets (labels section) -- that needs no line-identity assumption at all, just OCR/text-match on the printed string.

## R-10434.1 / R-10434.2
overlap rect (UTM10N m): (546760, 546868, 4183776, 4184144) | heavy pieces in zone: A 17, B 21 | geometric candidates 3, proven 2
  dropped (geometric candidate, not proven same line):
    - bearing diff 100.3', end gap 5.94 m, perp 2.5 ft -- neither bearing nor endpoints line up
- perpendicular offset, PROVEN pairs only: n=24 median 0.02 ft, max 0.04 ft, p90 0.03 ft
  per proven pair (median ft): 0.02, 0.03
- corner/end-tie gap (nearest-neighbour endpoints <5 m, NOT bearing-verified -- weaker evidence than the proven line pairs or the label offsets below): n=5 median 6.54 ft, max 11.17 ft, p90 10.73 ft
- no printed bearing/distance labels found within 6 m on both sheets near this matchline
- zoom (proven pairs only, bold): `matchline_R-10434.1_R-10434.2.png`

## R-10434.2 / R-10434.3
overlap rect (UTM10N m): (547659, 547727, 4183795, 4184144) | heavy pieces in zone: A 15, B 15 | geometric candidates 7, proven 5
  dropped (geometric candidate, not proven same line):
    - bearing diff 433.7', end gap 2.14 m, perp 15.5 ft -- neither bearing nor endpoints line up
    - bearing diff 1.9', end gap 0.29 m, perp 0.1 ft -- neither bearing nor endpoints line up
- perpendicular offset, PROVEN pairs only: n=60 median 0.11 ft, max 0.17 ft, p90 0.16 ft
  per proven pair (median ft): 0.03, 0.10, 0.11, 0.15, 0.16
- corner/end-tie gap (nearest-neighbour endpoints <5 m, NOT bearing-verified -- weaker evidence than the proven line pairs or the label offsets below): n=9 median 0.97 ft, max 12.83 ft, p90 3.34 ft
- no printed bearing/distance labels found within 6 m on both sheets near this matchline
- zoom (proven pairs only, bold): `matchline_R-10434.2_R-10434.3.png`

## R-10741.1 / R-10741.2
overlap rect (UTM10N m): (544913, 545403, 4187913, 4188214) | heavy pieces in zone: A 12, B 2 | geometric candidates 0, proven 0
  drawn linework from both sheets comes within 20 m in this zone but no piece pair agrees in direction/overlap -- see the crop: likely different features, not a shared record line.
- perpendicular offset, PROVEN pairs only: n/a (no matches)
- corner/end-tie gap (nearest-neighbour endpoints <5 m, NOT bearing-verified -- weaker evidence than the proven line pairs or the label offsets below): n/a (no matches)
- no printed bearing/distance labels found within 6 m on both sheets near this matchline
- zoom (proven pairs only, bold): `matchline_R-10741.1_R-10741.2.png`

## R-10741.2 / R-10741.3
overlap rect (UTM10N m): (545136, 545716, 4187203, 4187853) | heavy pieces in zone: A 85, B 56 | geometric candidates 3, proven 1
  dropped (geometric candidate, not proven same line):
    - bearing diff 137.4', end gap 0.03 m, perp 15.4 ft -- different bearing beyond a shared point
    - bearing diff 0.1', end gap 23.61 m, perp 13.3 ft -- same bearing but lines do not coincide/connect
- perpendicular offset, PROVEN pairs only: n=12 median 0.03 ft, max 0.03 ft, p90 0.03 ft
  per proven pair (median ft): 0.03
- corner/end-tie gap (nearest-neighbour endpoints <5 m, NOT bearing-verified -- weaker evidence than the proven line pairs or the label offsets below): n=5 median 0.09 ft, max 11.00 ft, p90 6.67 ft
- **same-label offset (cleanest measure): 12 bearing/distance labels within 6 m on both sheets, 12 print the identical bearing** -- n=12 median 0.19 ft, max 0.36 ft, p90 0.30 ft
  - [OK] `S58°55'30"E 399.46'` vs `S58°55'30"E 399.46'` (0.05 m = 0.17 ft apart)
  - [OK] `S11°11'33"W` vs `S11°11'33"W` (0.06 m = 0.21 ft apart)
  - [OK] `N09°38'23"E 255.00'` vs `N09°38'23"E 255.00'` (0.01 m = 0.02 ft apart)
  - [OK] `S09°09'47"E` vs `S09°09'47"E` (0.02 m = 0.07 ft apart)
  - [OK] `S41°08'37"E 508.21'` vs `S41°08'37"E 508.21'` (0.11 m = 0.36 ft apart)
  - [OK] `S41°08'37"E 371.79'` vs `S41°08'37"E 371.79'` (0.09 m = 0.30 ft apart)
  - [OK] `S57°23'37"E 297.64'` vs `S57°23'37"E 297.64'` (0.09 m = 0.29 ft apart)
  - [OK] `N16°11'57"E(R)` vs `N16°11'57"E(R)` (0.02 m = 0.07 ft apart)
  - [OK] `S54°40'22"W(R)` vs `S54°40'22"W(R)` (0.04 m = 0.13 ft apart)
  - [OK] `S73°48'03"E(R)` vs `S73°48'03"E(R)` (0.06 m = 0.20 ft apart)
  - [OK] `N35°19'38"W 411.67'` vs `N35*19'38"W 411.67'` (0.06 m = 0.20 ft apart)
  - [OK] `S55'29'00"E 598.06'` vs `S55*29'00"E 598.06'` (0.06 m = 0.19 ft apart)
- zoom (proven pairs only, bold): `matchline_R-10741.2_R-10741.3.png`

## R-10434.1 / R-10434.3
does not abut (bboxes: A (np.float64(546369.0747023192), np.float64(546866.2604031295), np.float64(4183631.589894004), np.float64(4184600.756839641)), B (np.float64(547660.8960386559), np.float64(548612.4806432673), np.float64(4183797.3847036073), np.float64(4184299.8491342296))) -- skipped.

## R-10741.1 / R-10741.3
does not abut (bboxes: A (np.float64(544796.4845074469), np.float64(545401.0350854791), np.float64(4187914.813077296), np.float64(4188902.824769034)), B (np.float64(545138.1494020944), np.float64(545831.8254592406), np.float64(4187030.624717864), np.float64(4187850.9326791987))) -- skipped.
