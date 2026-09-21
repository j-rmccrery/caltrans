"""Header probe for the sample LiDAR: CRS, extent, density, classes, sensor hints."""
from pathlib import Path

import laspy
import numpy as np
import rasterio

D = Path(__file__).parent / "Sample Data" / "LiDAR-Point-cloud"

with laspy.open(D / "points.laz") as f:
    h = f.header
    print("version", h.version, "| point format", h.point_format.id, "| points", f"{h.point_count:,}")
    print("mins", h.mins, "\nmaxs", h.maxs)
    print("system id:", repr(h.system_identifier), "| software:", repr(h.generating_software), "| date:", h.creation_date)
    try:
        crs = h.parse_crs()
        print("crs:", crs.name if crs else None, "| units:", [a.unit_name for a in crs.axis_info] if crs else None)
    except Exception as e:
        print("crs parse failed:", e)
    dx, dy = (h.maxs - h.mins)[:2]
    print(f"extent {dx:.1f} x {dy:.1f} (crs units) | density {h.point_count / (dx * dy):.2f} pts per sq unit")
    print("dims:", list(h.point_format.dimension_names))

    ch = next(f.chunk_iterator(5_000_000))
    cls, n = np.unique(np.asarray(ch.classification), return_counts=True)
    print("classes (first 5M pts):", dict(zip(cls.tolist(), n.tolist())))
    print("max number_of_returns:", int(np.asarray(ch.number_of_returns).max()))
    ang = np.asarray(ch.scan_angle_rank if "scan_angle_rank" in ch.point_format.dimension_names else ch.scan_angle)
    print("scan angle min/max:", ang.min(), ang.max())
    src = np.unique(np.asarray(ch.point_source_id))
    print("point_source_ids (flightlines/passes):", len(src), src[:10].tolist())

with rasterio.open(D / "output.tin.tif") as r:
    print("\ntif crs:", r.crs, "| res", r.res, "| size", r.width, "x", r.height, "| bounds", r.bounds)
    a = r.read(1, masked=True)
    print("elev min/max:", float(a.min()), float(a.max()), "| nodata", r.nodata)
