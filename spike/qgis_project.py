"""The screen for the demo: a QGIS project with every layer the pipeline emits, styled, in order.

Writes spike/out/demo.qgz (a zip holding demo.qgs). No QGIS needed to build it: the project is
XML with relative data sources, so the whole spike/out folder moves as one. Object records carry
a map tip: hover any object for its sheet, region, printed and measured values, rule and status.

usage: python spike/qgis_project.py   (after demo.py; opens with QGIS 3.28+)
"""
import json
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import rasterio

sys.path.insert(0, str(Path(__file__).parent))
from georef import OUT  # noqa: E402

CRS = {
    "EPSG:6339": ("NAD83(2011) / UTM zone 10N", "+proj=utm +zone=10 +ellps=GRS80 +units=m +no_defs"),
    "EPSG:6318": ("NAD83(2011)", "+proj=longlat +ellps=GRS80 +no_defs"),
}


def srs(authid):
    name, proj4 = CRS[authid]
    return f"<spatialrefsys><proj4>{proj4}</proj4><authid>{authid}</authid><description>{name}</description><geographicflag>{'true' if 'longlat' in proj4 else 'false'}</geographicflag></spatialrefsys>"


def sym(kind, sname, **props):
    """A one-layer symbol: kind is marker / line / fill."""
    cls = {"marker": "SimpleMarker", "line": "SimpleLine", "fill": "SimpleFill"}[kind]
    return (f'<symbol type="{kind}" name="{sname}" alpha="1" clip_to_extent="1" force_rhr="0"><layer class="{cls}" enabled="1" locked="0" pass="0">'
            + "".join(f'<prop k="{k}" v="{escape(str(v))}"/>' for k, v in props.items()) + "</layer></symbol>")


def single(kind, **props):
    return f'<renderer-v2 type="singleSymbol" forceraster="0" enableorderby="0"><symbols>{sym(kind, "0", **props)}</symbols></renderer-v2>'


def categorized(attr, kind, cats):
    """cats: [(value, label, props)]; the last entry with value '' is the fallback."""
    c = "".join(f'<category value="{escape(str(v))}" symbol="{i}" label="{escape(l)}" render="true" type="string"/>' for i, (v, l, _) in enumerate(cats))
    s = "".join(sym(kind, str(i), **p) for i, (_, _, p) in enumerate(cats))
    return f'<renderer-v2 type="categorizedSymbol" attr="{attr}" forceraster="0" enableorderby="0"><categories>{c}</categories><symbols>{s}</symbols></renderer-v2>'


def label(field, size=9, color="30,30,30,255", buffer=True):
    return (f'<labeling type="simple"><settings calling="Layer"><text-style fieldName="{field}" fontSize="{size}" fontFamily="Arial" textColor="{color}" '
            f'isExpression="0" namedStyle="Regular" fontWeight="50" textOpacity="1">'
            + (f'<text-buffer bufferDraw="1" bufferSize="0.8" bufferColor="255,255,255,255" bufferOpacity="1"/>' if buffer else "")
            + '</text-style><placement placement="0" centroidInside="1"/><rendering scaleVisibility="0" drawLabels="1"/></settings></labeling>')


def vector(lid, name, src, geometry, authid, renderer, extra=""):
    return (f'<maplayer type="vector" geometry="{geometry}" autoRefreshEnabled="0" refreshOnNotifyEnabled="0" hasScaleBasedVisibilityFlag="0" readOnly="0" simplifyDrawingHints="1" styleCategories="AllStyleCategories">'
            f"<id>{lid}</id><datasource>{escape(src)}</datasource><layername>{escape(name)}</layername><srs>{srs(authid)}</srs>"
            f'<provider encoding="UTF-8">ogr</provider>{renderer}{extra}<blendMode>0</blendMode><featureBlendMode>0</featureBlendMode><layerOpacity>1</layerOpacity></maplayer>')


def raster(lid, name, src, authid, opacity=1.0):
    return (f'<maplayer type="raster" autoRefreshEnabled="0" hasScaleBasedVisibilityFlag="0" styleCategories="AllStyleCategories">'
            f"<id>{lid}</id><datasource>{escape(src)}</datasource><layername>{escape(name)}</layername><srs>{srs(authid)}</srs><provider>gdal</provider>"
            f'<pipe><provider><resampling enabled="false"/></provider>'
            f'<rasterrenderer type="singlebandgray" band="1" gradient="BlackToWhite" opacity="{opacity}" alphaBand="-1" nodataColor="">'
            f'<rasterTransparency/><minMaxOrigin><limits>None</limits><extent>WholeRaster</extent><statAccuracy>Estimated</statAccuracy></minMaxOrigin>'
            f"<contrastEnhancement><minValue>0</minValue><maxValue>255</maxValue><algorithm>StretchToMinimumMaximum</algorithm></contrastEnhancement>"
            f'</rasterrenderer><brightnesscontrast brightness="0" contrast="0" gamma="1"/><huesaturation saturation="0" grayscaleMode="0"/>'
            f'<rasterresampler maxOversampling="2"/></pipe><blendMode>0</blendMode></maplayer>')


def maptip(fields):
    rows = "".join(f'<tr><td style="color:#777;padding-right:8px">{f}</td><td>[% "{f}" %]</td></tr>' for f in fields)
    return f'<mapTip enabled="1">&lt;table style="font-size:11px"&gt;{escape(rows)}&lt;/table&gt;</mapTip>'


OBJ_FIELDS = ["kind", "status", "check", "printed", "measured", "residual", "units", "rule", "reason", "sheet", "region", "parcel", "adjudicated_by"]
STATUS = [("verified", "verified: printed matches drawn", {}), ("queued", "queued: needs a surveyor", {}), ("refused", "refused: not checkable", {}), ("info", "record: no check applies", {})]
STATUS_COLOR = {"verified": "0,150,60,255", "queued": "230,140,0,255", "refused": "200,30,30,255", "info": "120,120,120,110"}


def main():
    with rasterio.open(OUT / "lidar_hillshade.tif") as d:
        b = d.bounds
    obj = OUT / "objects.geojson"
    layers = [  # top of the legend first
        ("obj_pts", "Object record: control points", vector("obj_pts", "Object record: control points", "./objects.geojson|geometrytype=Point", "Point", "EPSG:6318",
                                                            categorized("status", "marker", [(v, l, {"color": STATUS_COLOR[v], "size": "2.6", "name": "circle", "outline_color": "255,255,255,255", "outline_width": "0.4"}) for v, l, _ in STATUS]), maptip(OBJ_FIELDS))),
        ("obj_lines", "Object record: lines and checks", vector("obj_lines", "Object record: lines and checks", "./objects.geojson|geometrytype=LineString", "Line", "EPSG:6318",
                                                                categorized("status", "line", [(v, l, {"line_color": STATUS_COLOR[v], "line_width": "0.9" if v != "info" else "0.25"}) for v, l, _ in STATUS]), maptip(OBJ_FIELDS))),
        ("obj_polys", "Object record: parcels and features", vector("obj_polys", "Object record: parcels and features", "./objects.geojson|geometrytype=Polygon", "Polygon", "EPSG:6318",
                                                                    categorized("status", "fill", [(v, l, {"color": "0,0,0,0", "outline_color": STATUS_COLOR[v], "outline_width": "0.7", "outline_style": "dash" if v == "queued" else "solid"}) for v, l, _ in STATUS]), maptip(OBJ_FIELDS))),
        ("encroach", "Encroachment clusters", vector("encroach", "Encroachment clusters", "./encroachments.geojson", "Point", "EPSG:6318",
                                                     categorized("verdict", "marker", [("building", "building inside a parcel face", {"color": "220,0,0,255", "size": "3.2", "name": "square", "outline_color": "255,255,255,255", "outline_width": "0.4"}),
                                                                                       ("vegetation/terrain (filtered)", "vegetation / terrain (filtered out)", {"color": "180,180,180,160", "size": "1.8", "name": "circle", "outline_color": "120,120,120,160", "outline_width": "0.2"})]),
                                                     maptip(["parcel", "verdict", "footprint_m2", "height_m", "flat_top", "points"]))),
        ("features", "LiDAR features (pavement, deck, buildings)", vector("features", "LiDAR features (pavement, deck, buildings)", "./extracted_features.geojson", "Polygon", "EPSG:6318",
                                                                           categorized("kind", "fill", [("pavement", "pavement", {"color": "90,90,90,120", "outline_color": "60,60,60,255", "outline_width": "0.3"}),
                                                                                                        ("viaduct deck", "viaduct deck", {"color": "120,60,180,110", "outline_color": "90,40,140,255", "outline_width": "0.3"}),
                                                                                                        ("building", "building footprint", {"color": "240,150,40,90", "outline_color": "200,110,0,255", "outline_width": "0.35"})]),
                                                                           maptip(["kind", "verdict", "area_m2", "height_m", "flat_top", "rule"]))),
        ("parcels", "Parcels from the sheet", vector("parcels", "Parcels from the sheet", "./parcels.geojson", "Polygon", "EPSG:6318",
                                                     single("fill", color="30,90,200,25", outline_color="30,90,200,255", outline_width="0.8"),
                                                     label("parcel", 9, "20,60,160,255") + maptip(["parcel", "area_sqft", "table_area_sqft", "diff_pct", "labels_inside"]))),
        ("linework", "Sheet linework R-10434.2", vector("linework", "Sheet linework R-10434.2", "./sheet_linework.geojson", "Line", "EPSG:6318",
                                                        categorized("weight", "line", [("heavy", "heavy (R/W, parcel lines)", {"line_color": "0,0,0,255", "line_width": "0.7"}),
                                                                                       ("light", "light", {"line_color": "90,90,90,160", "line_width": "0.2"})]))),
        ("intensity", "LiDAR intensity", raster("intensity", "LiDAR intensity", "./lidar_intensity.tif", "EPSG:6339", 0.55)),
        ("hillshade", "LiDAR hillshade", raster("hillshade", "LiDAR hillshade", "./lidar_hillshade.tif", "EPSG:6339", 1.0)),
    ]
    tree = "".join(f'<layer-tree-layer id="{lid}" name="{escape(name)}" checked="Qt::Checked" expanded="1" providerKey="{"gdal" if lid in ("intensity", "hillshade") else "ogr"}" source="{escape(xml.split("<datasource>")[1].split("</datasource>")[0])}"/>'
                   for lid, name, xml in layers)
    qgs = f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis projectname="SWYFT Record Twin" version="3.34.0" saveUser="swyft">
  <homePath path=""/>
  <title>SWYFT Record Twin: Presidio sheet R-10434.2 on 2025 LiDAR</title>
  <projectCrs>{srs("EPSG:6339")}</projectCrs>
  <layer-tree-group><customproperties/>{tree}<custom-order enabled="0"/></layer-tree-group>
  <mapcanvas name="theMapCanvas" annotationsVisible="1">
    <units>meters</units>
    <extent><xmin>{b.left}</xmin><ymin>{b.bottom}</ymin><xmax>{b.right}</xmax><ymax>{b.top}</ymax></extent>
    <rotation>0</rotation>
    <destinationsrs>{srs("EPSG:6339")}</destinationsrs>
    <rendermaptile>0</rendermaptile>
  </mapcanvas>
  <projectlayers>{"".join(xml for _, _, xml in layers)}</projectlayers>
  <properties>
    <Paths><Absolute type="bool">false</Absolute></Paths>
    <Gui><CanvasColorBluePart type="int">255</CanvasColorBluePart><CanvasColorGreenPart type="int">255</CanvasColorGreenPart><CanvasColorRedPart type="int">255</CanvasColorRedPart></Gui>
    <Measurement><DistanceUnits type="QString">feet</DistanceUnits><AreaUnits type="QString">ft2</AreaUnits></Measurement>
    <PositionPrecision><Automatic type="bool">true</Automatic></PositionPrecision>
  </properties>
</qgis>
"""
    import xml.dom.minidom
    xml.dom.minidom.parseString(qgs)  # well-formed or die
    (OUT / "demo.qgs").write_text(qgs, encoding="utf-8")
    with zipfile.ZipFile(OUT / "demo.qgz", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(OUT / "demo.qgs", "demo.qgs")
    (OUT / "demo.qgs").unlink()
    n = sum(1 for f in json.loads(obj.read_text(encoding="utf-8"))["features"])
    print(f"demo.qgz: {len(layers)} layers, {n} object records with map tips; project CRS EPSG:6339, extent {b.left:.0f}-{b.right:.0f} E, {b.bottom:.0f}-{b.top:.0f} N")


if __name__ == "__main__":
    main()
