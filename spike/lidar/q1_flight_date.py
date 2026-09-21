"""Q1: when was it flown? Decode gps_time per flightline (point_source_id)."""
import laspy
import numpy as np
from datetime import datetime, timedelta, timezone

LAZ = r"C:\Users\johnr\projects\caltrans\Sample Data\LiDAR-Point-cloud\points.laz"
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=timezone.utc)

f = laspy.open(LAZ)
h = f.header
bit0 = h.global_encoding.gps_time_type  # 0 = GPS week time, 1 = adjusted standard GPS time
print(f"global_encoding.gps_time_type bit = {bit0} ({'adjusted standard GPS time' if bit0 else 'GPS week time (per header)'})")

minmax = {}  # psid -> [min, max]
n = 0
for pts in f.chunk_iterator(2_000_000):
    gt = pts.gps_time
    psid = pts.point_source_id
    for pid in np.unique(psid):
        m = psid == pid
        lo, hi = gt[m].min(), gt[m].max()
        if pid not in minmax:
            minmax[pid] = [lo, hi]
        else:
            minmax[pid][0] = min(minmax[pid][0], lo)
            minmax[pid][1] = max(minmax[pid][1], hi)
    n += len(pts)
f.close()
print(f"points scanned: {n}")

raw_min = min(v[0] for v in minmax.values())
raw_max = max(v[1] for v in minmax.values())
print(f"raw gps_time range across file: {raw_min:.3f} .. {raw_max:.3f}")
# Header bit claims GPS week time (max 604800s), but observed values are ~4.4e8 -- only
# consistent with Adjusted Standard GPS Time (value + 1e9 = seconds since GPS epoch).
# Header bit is WRONG/mislabeled; decoding using the adjusted-standard formula since it's
# the only interpretation the magnitude supports.
print("NOTE: header bit says GPS week time, but raw values (~4.4e8) exceed one GPS week")
print("(604800s) by ~730x -- values are actually Adjusted Standard GPS Time (mislabeled header).")
print("Decoding with: date = GPS_EPOCH + (value + 1e9) seconds. Leap seconds (~18s) ignored (date-level only).")

print()
print(f"{'flightline':>10} {'first_date_utc':>20} {'last_date_utc':>20} {'span_sec':>10}")
for pid in sorted(minmax):
    lo, hi = minmax[pid]
    d_lo = GPS_EPOCH + timedelta(seconds=lo + 1e9)
    d_hi = GPS_EPOCH + timedelta(seconds=hi + 1e9)
    print(f"{pid:>10} {d_lo.isoformat():>20} {d_hi.isoformat():>20} {hi-lo:>10.1f}")

overall_lo = GPS_EPOCH + timedelta(seconds=raw_min + 1e9)
overall_hi = GPS_EPOCH + timedelta(seconds=raw_max + 1e9)
print()
print(f"overall date range: {overall_lo.isoformat()} .. {overall_hi.isoformat()}")
cutoff = datetime(2015, 12, 31, tzinfo=timezone.utc)
print(f"after ~2015 Presidio Parkway completion? {'YES' if overall_lo > cutoff else 'NO'}")
