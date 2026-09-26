# Ground check: sheet-drawn structures vs LiDAR-derived edges
All six Presidio/Marin sheets (each sheet's own PDF, from Sample Data/d4 or Sample Data/Right-of-Way Map Record). Modelled HTDP epoch shift (already applied to sheet_linework.geojson, as the pipeline does): 2.19 ft, N33W (dE -0.362 m, dN +0.561 m).

Method: each LiDAR building/deck polygon that passes extract.py's own roof-flatness test gets a buffered search (8 m buildings, 15 m deck) over that sheet's own heavy+light linework; a convex hull of what's found nearby, sized within 0.15-6x the LiDAR footprint's area, stands in for "the sheet's drawn version of this feature" -- there is no dedicated building layer to read off directly. Offset = LiDAR centroid - sheet-hull centroid. Every match found was cropped from that sheet's own PDF and looked at before being called credible. Each sheet's text-read cache is also grepped for structure wording (BUILDING/STRUCTURE/WALL/RETAIN/PORTAL/BRIDGE/...).

## R-10434.1
structure-word hits in this sheet's own text: ['STRUCTURE', 'HIGH VIADUCT', '7.21 AC. HIGH VIADUCT ESMT.', 'GOLDEN GATE BRIDGE HIGHWAY', '1)\tPERMIT DATED JULY 27, 1938, GRANTED FROM THE SECRETARY PERMIT DATED JULY 27, 1938, GRANTED FROM THE SECRETARY OF WAR TO THE STATE OF CALIFORNIA TO EXTEND AN APPROACH ROAD (TO BE KNOWN AS THE FUNSTON AVENUE APPROACH) TO CONNECT TO THE GOLDEN GATE BRIDGE, CONSTRUCTED UNDER A PERMIT GRANTED BY THE SECRETARY OF WAR TO THE GOLDEN GATE BRIDGE AND HIGHWAY DISTRICT ON FEBRUARY 13, 1931. 2)\tORIGINAL PERMIT DATED FEBRUARY 13, 1931 ISSUED FROM THE ORIGINAL PERMIT DATED FEBRUARY 13, 1931 ISSUED FROM THE SECRETARY OF WAR TO THE GOLDEN GATE BRIDGE AND HIGHWAY DISTRICT OF CALIFORNIA AND AMENDED BY THE 3RD AMENDMENT DATED JULY 21, 1933.']
buildings: 17 matched of 59 LiDAR candidates in the sheet's plotted area | viaduct deck: 1 matched of 4
  - `R-10434.1_building_2` area 228.0 m2, centroid offset dE -11.03 dN -5.48 m (12.31 m) -- crop `gc_R-10434.1_building_2.png`
  - `R-10434.1_building_4` area 36.0 m2, centroid offset dE +3.67 dN -1.09 m (3.83 m) -- crop `gc_R-10434.1_building_4.png`
  - `R-10434.1_building_5` area 439.0 m2, centroid offset dE -2.58 dN +2.17 m (3.37 m) -- crop `gc_R-10434.1_building_5.png`
  - `R-10434.1_building_7` area 450.0 m2, centroid offset dE -0.06 dN -0.02 m (0.07 m) -- crop `gc_R-10434.1_building_7.png`
  - `R-10434.1_building_8` area 41.0 m2, centroid offset dE -6.04 dN +1.85 m (6.31 m) -- crop `gc_R-10434.1_building_8.png`
  - `R-10434.1_building_14` area 37.0 m2, centroid offset dE +4.64 dN -0.21 m (4.65 m) -- crop `gc_R-10434.1_building_14.png`
  - `R-10434.1_building_15` area 548.0 m2, centroid offset dE +7.90 dN -5.06 m (9.38 m) -- crop `gc_R-10434.1_building_15.png`
  - `R-10434.1_building_18` area 291.0 m2, centroid offset dE +4.07 dN +7.10 m (8.18 m) -- crop `gc_R-10434.1_building_18.png`
  - `R-10434.1_building_20` area 36.0 m2, centroid offset dE +1.57 dN +3.94 m (4.24 m) -- crop `gc_R-10434.1_building_20.png`
  - `R-10434.1_building_21` area 25.0 m2, centroid offset dE -0.62 dN +7.46 m (7.48 m) -- crop `gc_R-10434.1_building_21.png`
  - `R-10434.1_building_25` area 42.0 m2, centroid offset dE -1.48 dN +0.46 m (1.55 m) -- crop `gc_R-10434.1_building_25.png`
  - `R-10434.1_building_26` area 46.0 m2, centroid offset dE -9.48 dN -0.73 m (9.51 m) -- crop `gc_R-10434.1_building_26.png`
  - `R-10434.1_building_31` area 33.0 m2, centroid offset dE +6.61 dN +9.06 m (11.21 m) -- crop `gc_R-10434.1_building_31.png`
  - `R-10434.1_building_33` area 32.0 m2, centroid offset dE +7.54 dN -0.40 m (7.55 m) -- crop `gc_R-10434.1_building_33.png`
  - `R-10434.1_building_34` area 93.0 m2, centroid offset dE -0.65 dN +0.07 m (0.65 m) -- crop `gc_R-10434.1_building_34.png`
  - `R-10434.1_building_43` area 51.0 m2, centroid offset dE +2.25 dN -0.05 m (2.25 m) -- crop `gc_R-10434.1_building_43.png`
  - `R-10434.1_building_57` area 304.0 m2, centroid offset dE +5.56 dN +1.56 m (5.78 m) -- crop `gc_R-10434.1_building_57.png`
  - `R-10434.1_viaduct_deck_3` area 3411.0 m2, centroid offset dE +0.03 dN -1.13 m (1.13 m), perp offset median 10.97 m max 21.20 m -- crop `gc_R-10434.1_viaduct_deck_3.png`

## R-10434.2
structure-word hits in this sheet's own text: ['HIGH VIADUCT', '7.21 AC. HIGH VIADUCT ESMT.', '1)\tNO ACCESS RIGHTS TO ADJOINING HIGHWAY FACILITIES; NO ACCESS RIGHTS TO ADJOINING HIGHWAY FACILITIES; HOWEVER, ACCESS TO SURFACE ABOVE TUNNEL IS NOT RESTRICTED. 2)\tORIGINAL PERMIT DATED FEBRUARY 13, 1931 ISSUED FROM THE ORIGINAL PERMIT DATED FEBRUARY 13, 1931 ISSUED FROM THE SECRETARY OF WAR TO THE GOLDEN GATE BRIDGE AND HIGHWAY DISTRICT OF CALIFORNIA AND AMENDED BY THE 3RD AMENDMENT DATED JULY 21, 1933.', 'GOLDEN GATE BRIDGE HIGHWAY']
buildings: 22 matched of 61 LiDAR candidates in the sheet's plotted area | viaduct deck: 2 matched of 2
  - `R-10434.2_building_1` area 108.0 m2, centroid offset dE +0.76 dN -0.21 m (0.79 m) -- crop `gc_R-10434.2_building_1.png`
  - `R-10434.2_building_3` area 1306.0 m2, centroid offset dE -8.63 dN -5.96 m (10.49 m) -- crop `gc_R-10434.2_building_3.png`
  - `R-10434.2_building_4` area 2242.0 m2, centroid offset dE +10.14 dN -1.43 m (10.24 m) -- crop `gc_R-10434.2_building_4.png`
  - `R-10434.2_building_7` area 46.0 m2, centroid offset dE -1.62 dN +2.40 m (2.90 m) -- crop `gc_R-10434.2_building_7.png`
  - `R-10434.2_building_10` area 58.0 m2, centroid offset dE +3.08 dN +1.21 m (3.31 m) -- crop `gc_R-10434.2_building_10.png`
  - `R-10434.2_building_11` area 116.0 m2, centroid offset dE -11.74 dN +0.76 m (11.76 m) -- crop `gc_R-10434.2_building_11.png`
  - `R-10434.2_building_14` area 174.0 m2, centroid offset dE +3.47 dN -15.34 m (15.73 m) -- crop `gc_R-10434.2_building_14.png`
  - `R-10434.2_building_16` area 53.0 m2, centroid offset dE +1.15 dN +4.00 m (4.17 m) -- crop `gc_R-10434.2_building_16.png`
  - `R-10434.2_building_17` area 147.0 m2, centroid offset dE -3.28 dN +2.47 m (4.10 m) -- crop `gc_R-10434.2_building_17.png`
  - `R-10434.2_building_25` area 481.0 m2, centroid offset dE -2.27 dN +0.09 m (2.28 m) -- crop `gc_R-10434.2_building_25.png`
  - `R-10434.2_building_26` area 108.0 m2, centroid offset dE +3.86 dN -6.51 m (7.57 m) -- crop `gc_R-10434.2_building_26.png`
  - `R-10434.2_building_27` area 53.0 m2, centroid offset dE -4.60 dN -0.89 m (4.69 m) -- crop `gc_R-10434.2_building_27.png`
  - `R-10434.2_building_31` area 343.0 m2, centroid offset dE +4.55 dN -6.35 m (7.81 m) -- crop `gc_R-10434.2_building_31.png`
  - `R-10434.2_building_32` area 105.0 m2, centroid offset dE -1.11 dN -3.10 m (3.29 m) -- crop `gc_R-10434.2_building_32.png`
  - `R-10434.2_building_34` area 148.0 m2, centroid offset dE +2.61 dN +1.33 m (2.93 m) -- crop `gc_R-10434.2_building_34.png`
  - `R-10434.2_building_35` area 218.0 m2, centroid offset dE +3.05 dN -6.01 m (6.74 m) -- crop `gc_R-10434.2_building_35.png`
  - `R-10434.2_building_36` area 147.0 m2, centroid offset dE -5.81 dN -1.60 m (6.03 m) -- crop `gc_R-10434.2_building_36.png`
  - `R-10434.2_building_38` area 63.0 m2, centroid offset dE -4.57 dN -3.66 m (5.86 m) -- crop `gc_R-10434.2_building_38.png`
  - `R-10434.2_building_39` area 33.0 m2, centroid offset dE +3.77 dN -2.62 m (4.59 m) -- crop `gc_R-10434.2_building_39.png`
  - `R-10434.2_building_43` area 40.0 m2, centroid offset dE -5.09 dN +0.25 m (5.09 m) -- crop `gc_R-10434.2_building_43.png`
  - `R-10434.2_building_44` area 210.0 m2, centroid offset dE -0.76 dN -1.41 m (1.60 m) -- crop `gc_R-10434.2_building_44.png`
  - `R-10434.2_building_60` area 196.0 m2, centroid offset dE -1.58 dN -1.91 m (2.47 m) -- crop `gc_R-10434.2_building_60.png`
  - `R-10434.2_viaduct_deck_0` area 8535.0 m2, centroid offset dE -75.46 dN +22.47 m (78.73 m), perp offset median 13.07 m max 24.64 m -- crop `gc_R-10434.2_viaduct_deck_0.png`
  - `R-10434.2_viaduct_deck_1` area 10524.0 m2, centroid offset dE -63.13 dN +13.75 m (64.61 m), perp offset median 14.44 m max 35.62 m -- crop `gc_R-10434.2_viaduct_deck_1.png`

## R-10434.3
structure-word hits in this sheet's own text: ['LOW-VIADUCT', '1)\tNO ACCESS RIGHTS TO ADJOINING HIGHWAY FACILITIES; NO ACCESS RIGHTS TO ADJOINING HIGHWAY FACILITIES; HOWEVER, ACCESS TO SURFACE ABOVE TUNNEL IS NOT RESTRICTED. 2)\tORIGINAL PERMIT DATED FEBRUARY 13, 1931 ISSUED FROM THE ORIGINAL PERMIT DATED FEBRUARY 13, 1931 ISSUED FROM THE SECRETARY OF WAR TO THE GOLDEN GATE BRIDGE AND HIGHWAY DISTRICT OF CALIFORNIA AND AMENDED BY THE 3RD AMENDMENT DATED JULY 21, 1933.', '3.77 AC. HIGHWAY ESMT. AT LOW VIADUCT', 'GOLDEN GATE BRIDGE HIGHWAY']
buildings: 0 matched of 0 LiDAR candidates in the sheet's plotted area | viaduct deck: 2 matched of 4
  - `R-10434.3_viaduct_deck_2` area 575.0 m2, centroid offset dE -2.64 dN +3.46 m (4.36 m), perp offset median 8.61 m max 14.78 m -- crop `gc_R-10434.3_viaduct_deck_2.png`
  - `R-10434.3_viaduct_deck_3` area 9887.0 m2, centroid offset dE -17.51 dN +30.30 m (34.99 m), perp offset median 19.86 m max 76.65 m -- crop `gc_R-10434.3_viaduct_deck_3.png`

## R-10741.1
structure-word hits in this sheet's own text: none
buildings: 0 matched of 0 LiDAR candidates in the sheet's plotted area | viaduct deck: 0 matched of 0
no LiDAR building/deck candidate in this sheet's plotted area matched nearby linework (either none drawn, or none of the required size/shape found).

## R-10741.2
structure-word hits in this sheet's own text: ['GOLDEN GATE BRIDGE, HI', 'GOLDEN GATE BRIDGE, HII']
buildings: 1 matched of 11 LiDAR candidates in the sheet's plotted area | viaduct deck: 0 matched of 0
  - `R-10741.2_building_8` area 64.0 m2, centroid offset dE +2.98 dN +7.16 m (7.75 m) -- crop `gc_R-10741.2_building_8.png`

## R-10741.3
structure-word hits in this sheet's own text: ['BRIDGE', 'BRIDGE,', 'BRIDGE,']
buildings: 3 matched of 22 LiDAR candidates in the sheet's plotted area | viaduct deck: 1 matched of 3
  - `R-10741.3_building_1` area 64.0 m2, centroid offset dE +5.91 dN +5.20 m (7.87 m) -- crop `gc_R-10741.3_building_1.png`
  - `R-10741.3_building_2` area 23.0 m2, centroid offset dE -6.77 dN -6.47 m (9.36 m) -- crop `gc_R-10741.3_building_2.png`
  - `R-10741.3_building_13` area 17.0 m2, centroid offset dE +1.18 dN +0.50 m (1.28 m) -- crop `gc_R-10741.3_building_13.png`
  - `R-10741.3_viaduct_deck_1` area 1.0 m2, centroid offset dE +7.50 dN +3.75 m (8.39 m), perp offset median 8.15 m max 9.06 m -- crop `gc_R-10741.3_viaduct_deck_1.png`

## Credibility verdict (every match above cropped from its own sheet's PDF and reviewed; contact sheets, not sampling)
**Buildings: not credible, 0/6 sheets, 0/43 total matches (the 4 sheets with any).** R-10434.1 (17 crops), R-10434.2 (22), R-10741.2 (1) and R-10741.3 (3) all show the same thing: R/W boundary curves, curve/line data tables, parcel labels (61806/61985 U.S.A. Presidio Trust, TCE/tunnel-easement notes), title-block cells, or on the north sheets a small monument circle ("46825-5", "Right of Way" leader) and route/city title text ("STATE ROUTE…", "COUNTY OF MARIN"). Not one crop shows a drawn building rectangle, on either the 2020 Presidio sheets or the 2017 Marin/toll-plaza-approach sheets. The one sheet-text hit that sounds structural, R-10434.1/.2's "DRAINAGE STRUCTURE" callout, points to a small culvert-inlet symbol (5 leader lines to a cluster of circles), not a building and not resolvable at 15 pts/m2 airborne density anyway. These are right-of-way/easement records; none of the six draws structures. Every reported building vector above is a proximity coincidence (the sheets are dense with R/W and parcel lines everywhere, so the buffered search always finds *something*), not a tie to the same feature -- reported for completeness, not as position checks.

**Viaduct deck: 6/6 matched crops reviewed, credible only as corridor-vs-pavement, never as a same-edge tie.** Every deck crop (R-10434.1/.2/.3, R-10741.3) shows a survey centerline (tick-marked "RAMP LINE…", curve data) plus R/W corridor hatch -- these sheets draw the corridor/parcel line, never the structure's own deck edge (expected for a R/W record; it is not a construction drawing). Perpendicular offset from LiDAR pavement edge to the drawn corridor ranges ~13-14 m on the R-10434.2 ramp and is of the same order on the others -- real corridor width (shoulders/slopes/clearance) by design, not a georeferencing error, consistent with loop 11's prior "purple deck gaps explained" finding. One R-10434.3 deck crop lands next to a parcel labelled "AT GRADE" -- a caveat, not resolved further here: either that LiDAR polygon is a false positive (an at-grade stretch wrongly classified as elevated deck by the height-above-DTM fallback extract.py uses where a tile has no class-17 returns), or the label belongs to an adjacent segment; worth a follow-up leg, not asserted either way.

## Epoch-shift verdict
**Cannot confirm or deny the 0.668 m N33W shift from any of the six sheets' drawn content.** No credible per-feature tie exists small enough to speak to a sub-meter correction: buildings aren't drawn on any sheet (verdict above), and the only linear features found (ramp corridors) are compared against a corridor line that sits meters to tens of meters from the pavement by design, swamping a sub-meter epoch correction by 1-2 orders of magnitude. The only sub-meter check anywhere in this pipeline is record-internal: each sheet's own georef-fit RMS (0.02-0.05 ft across these six sheets), which says nothing about ground truth. The matchline check (spike/matchline.py) is the closer thing to ground truth this snapshot supports, and even that is sheet-vs-sheet (record-vs-record), not record-vs-LiDAR.

## Other features asked for
- edge of pavement: not drawn separately from the R/W line on any of these sheets (extract.py's own pavement-vs-R/W-face distance is the closest existing number, and is a distribution over the whole corridor, not a per-feature tie).
- retaining walls / tunnel portals: no "RETAIN"/"WALL"/"PORTAL" hit on any of the six sheets. "TUNNEL EASEMENT" appears (legal easement over a bored/cut-and-cover tunnel, matches loop 11's "tunnels record-only" finding) but with no portal headwall line to tie to a LiDAR edge; airborne LiDAR at 15 pts/m2 would not resolve a vertical portal face regardless (README's own limit).
