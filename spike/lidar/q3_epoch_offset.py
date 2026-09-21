"""Q3: epoch offset 1991.35 -> NAD83(2011) epoch 2010.0 at ~37.80N, -122.46E.
Queries NGS HTDP v3.6.0 web tool (real API call, not an estimate) and reports the result.
"""
import math
import urllib.request
import urllib.parse
import os

OUT = r"C:\Users\johnr\projects\caltrans\spike\lidar\out"
CACHE = r"C:\Users\johnr\projects\caltrans\spike\lidar\cache"
os.makedirs(OUT, exist_ok=True)

URL = "https://geodesy.noaa.gov/cgi-bin/HTDP/htdp_p1.prl"
fields = {
    "InputFrame": "1",          # NAD_83(2011/CORS96/2007), North America plate fixed
    "date_type": "2",           # decimal year
    "FirstDate": "1991.35",
    "SecondDate": "2010.0",
    "coordinate_type": "1",     # lat/lon/height
    "coordinate1": "37,48,0.0",       # 37.80 N
    "coordinate2": "122,27,36.0",     # 122.46 W (positive-west convention)
    "coordinate3": "0.0",
    "name": "PresidioParkway",
    "velocity_type": "0",       # use HTDP's own predicted velocity
    "velocity1": "", "velocity2": "", "velocity3": "",
    "f1": "1", "f2": "1",
    ".submit": "Submit",
    ".cgifields": "date_type",
}
boundary = "----htdpspike"
body = ""
for k, v in fields.items():
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
body += f"--{boundary}--\r\n"

req = urllib.request.Request(URL, data=body.encode(), method="POST",
                              headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode(errors="replace")
    ok = True
except Exception as e:
    ok = False
    html = ""
    print(f"HTDP request FAILED: {e}")

cache_file = os.path.join(CACHE, "htdp_response.html")
with open(cache_file, "w", encoding="utf-8") as f:
    f.write(html)

if ok:
    print("HTDP request succeeded. Raw <pre> block:")
    pre = html.split("<pre>")[1].split("</pre>")[0] if "<pre>" in html else html
    print(pre)

    # parse the data line (last non-blank line with numbers)
    line = [l for l in pre.splitlines() if l.strip() and l.strip()[0].isalpha() and "NAME" not in l]
    line = line[-1]
    parts = line.split()
    # ... NAME LAT(3) N  LON(3) W  NORTH EAST UP
    north_m = float(parts[-3])
    east_m = float(parts[-2])
    up_m = float(parts[-1])
    mag_m = math.hypot(north_m, east_m)
    mag_ft = mag_m * 3.280839895
    bearing_from_north = math.degrees(math.atan2(east_m, north_m))  # + = east of north
    compass = "N" + f"{abs(bearing_from_north):.1f}" + ("E" if bearing_from_north >= 0 else "W")

    print()
    print("=== MEASURED (NGS HTDP v3.6.0, NAD_83(2011/CORS96/2007), 1991.350 -> 2010.000) ===")
    print(f"North: {north_m:+.3f} m   East: {east_m:+.3f} m   Up: {up_m:+.3f} m")
    print(f"Horizontal magnitude: {mag_m:.3f} m ({mag_ft:.3f} ft)")
    print(f"Direction: {compass} of north ({bearing_from_north:+.1f} deg, +east of north)")
else:
    print("Falling back to published NAD83 plate-motion ESTIMATE (Pacific/NA boundary, SF peninsula).")
    print("ESTIMATE: Pacific plate motion relative to stable North America ~ 45-48 mm/yr,")
    print("SF Bay Area straddles the plate boundary; published NAD83(2011) horizontal velocities")
    print("for SF peninsula CORS stations are typically ~15-25 mm/yr west-northwest")
    print("(source: NGS CORS velocity summaries / UNAVCO GPS velocity field, Pacific-NA relative motion).")
    yrs = 2010.0 - 1991.35
    v_lo, v_hi = 0.015, 0.025  # m/yr, ESTIMATE range
    print(f"Over {yrs:.2f} yr: ESTIMATE range {yrs*v_lo:.2f}-{yrs*v_hi:.2f} m "
          f"({yrs*v_lo*3.28084:.2f}-{yrs*v_hi*3.28084:.2f} ft), direction ESTIMATE ~WNW.")
