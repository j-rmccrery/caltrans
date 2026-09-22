"""The screen for the demo: a QGIS project with every layer the pipeline emits, styled, in order.

Built by QGIS itself (PyQGIS, run under QGIS's Python), so the project is valid by construction.
Writes spike/out/demo.qgz with relative data sources (the whole spike/out folder moves as one) and
spike/out/demo_render.png, the opening view rendered headless as proof. Object records carry a map
tip: hover any object for its sheet, region, printed and measured values, rule and status.

usage: %LOCALAPPDATA%\\Programs\\OSGeo4W\\bin\\python-qgis-ltr.bat spike/qgis_project.py   (demo.py does this)
"""
import sys
from pathlib import Path

import numpy as np
from qgis.core import (QgsApplication, QgsCategorizedSymbolRenderer, QgsContrastEnhancement, QgsCoordinateReferenceSystem,
                       QgsMapRendererSequentialJob, QgsMapSettings, QgsPalLayerSettings, QgsProject, QgsRasterLayer,
                       QgsRendererCategory, QgsSimpleMarkerSymbolLayerBase, QgsSingleBandGrayRenderer, QgsSingleSymbolRenderer, QgsSymbol, QgsTextBufferSettings,
                       QgsTextFormat, QgsUnitTypes, QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsWkbTypes)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QFont

OUT = Path(__file__).resolve().parent / "out"
UTM, LL = "EPSG:6339", "EPSG:6318"
OBJ_FIELDS = ["kind", "status", "check", "printed", "measured", "residual", "units", "rule", "reason", "sheet", "region", "parcel", "adjudicated_by"]
STATUS = {"verified": ("verified: printed matches drawn", "#0a9640"), "queued": ("queued: needs a surveyor", "#e68c00"),
          "refused": ("refused: not checkable", "#c81e1e"), "info": ("record: no check applies", "#787878")}


def col(hex6, alpha=255):
    """Qt reads 8-digit hex as #AARRGGBB; keep colours as #RRGGBB plus an alpha."""
    c = QColor(hex6); c.setAlpha(alpha); return c


def symbol(geom, color, width=None, outline=None, size=None, shape=None, style=None):
    s = QgsSymbol.defaultSymbol(geom)
    s.setColor(color if isinstance(color, QColor) else QColor(color))
    sl = s.symbolLayer(0)
    if width is not None:
        (sl.setWidth if geom == QgsWkbTypes.LineGeometry else sl.setStrokeWidth)(width)
    if outline is not None:
        sl.setStrokeColor(outline if isinstance(outline, QColor) else QColor(outline))
    if size is not None:
        sl.setSize(size)
    if shape is not None:
        sl.setShape(shape)
    if style is not None:
        sl.setPenStyle(style)
    return s


def categorized(attr, cats):
    return QgsCategorizedSymbolRenderer(attr, [QgsRendererCategory(v, s, l) for v, l, s in cats])


def maptip(fields):
    rows = "".join(f'<tr><td style="color:#777;padding-right:8px">{f}</td><td>[% "{f}" %]</td></tr>' for f in fields)
    return f'<table style="font-size:11px">{rows}</table>'


def labels(field, color):
    s = QgsPalLayerSettings()
    s.fieldName = field
    f = QgsTextFormat(); f.setFont(QFont("Arial")); f.setSize(9); f.setColor(QColor(color))
    b = QgsTextBufferSettings(); b.setEnabled(True); b.setSize(0.8); b.setColor(QColor("white")); f.setBuffer(b)
    s.setFormat(f)
    return QgsVectorLayerSimpleLabeling(s)


def vector(name, src, renderer, tip=None, labeling=None):
    l = QgsVectorLayer(str(OUT / src), name, "ogr")
    assert l.isValid() and l.featureCount(), f"{name}: invalid or empty ({src})"
    l.setCrs(QgsCoordinateReferenceSystem(LL))
    l.setRenderer(renderer)
    if tip:
        l.setMapTipTemplate(tip)
    if labeling:
        l.setLabeling(labeling); l.setLabelsEnabled(True)
    return l


def raster(name, src, opacity):
    l = QgsRasterLayer(str(OUT / src), name, "gdal")
    assert l.isValid(), f"{name}: invalid ({src})"
    l.setCrs(QgsCoordinateReferenceSystem(UTM))
    r = QgsSingleBandGrayRenderer(l.dataProvider(), 1)
    ce = QgsContrastEnhancement(l.dataProvider().dataType(1))
    ce.setMinimumValue(0); ce.setMaximumValue(255); ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
    r.setContrastEnhancement(ce)
    l.setRenderer(r); l.setOpacity(opacity)
    return l


def main():
    app = QgsApplication([], False)
    app.initQgis()
    P, L, F, M = QgsWkbTypes.PointGeometry, QgsWkbTypes.LineGeometry, QgsWkbTypes.PolygonGeometry, QgsWkbTypes.PointGeometry
    layers = [  # top of the legend first
        vector("Object record: control points", "objects.geojson|geometrytype=Point",
               categorized("status", [(k, lab, symbol(P, c, size=2.6, outline="white", width=0.4)) for k, (lab, c) in STATUS.items()]), maptip(OBJ_FIELDS)),
        vector("Object record: lines and checks", "objects.geojson|geometrytype=LineString",
               categorized("status", [(k, lab, symbol(L, c, width=0.25 if k == "info" else 0.9)) for k, (lab, c) in STATUS.items()]), maptip(OBJ_FIELDS)),
        vector("Object record: parcels and features", "objects.geojson|geometrytype=Polygon",
               categorized("status", [(k, lab, symbol(F, col("#000000", 0), outline=c, width=0.7)) for k, (lab, c) in STATUS.items()]), maptip(OBJ_FIELDS)),
        vector("Encroachment clusters", "encroachments.geojson",
               categorized("verdict", [("building", "building inside a parcel face", symbol(M, "#dc0000", size=3.2, outline="white", width=0.4, shape=QgsSimpleMarkerSymbolLayerBase.Square)),
                                       ("vegetation/terrain (filtered)", "vegetation / terrain (filtered out)", symbol(M, col("#b4b4b4", 160), size=1.8, outline=col("#787878", 160), width=0.2))]),
               maptip(["parcel", "verdict", "footprint_m2", "height_m", "flat_top", "points"])),
        vector("LiDAR features (pavement, deck, buildings)", "extracted_features.geojson",
               categorized("kind", [("pavement", "pavement", symbol(F, col("#5a5a5a", 120), outline="#3c3c3c", width=0.3)),
                                    ("viaduct deck", "viaduct deck", symbol(F, col("#783cb4", 110), outline="#5a288c", width=0.3)),
                                    ("building", "building footprint", symbol(F, col("#f09628", 90), outline="#c86e00", width=0.35))]),
               maptip(["kind", "verdict", "area_m2", "height_m", "flat_top", "rule"])),
        vector("Parcels from the sheet", "parcels.geojson", QgsSingleSymbolRenderer(symbol(F, col("#1e5ac8", 25), outline="#1e5ac8", width=0.8)),
               maptip(["parcel", "area_sqft", "table_area_sqft", "diff_pct", "labels_inside"]), labels("parcel", "#143ca0")),
        vector("Sheet linework R-10434.2", "sheet_linework.geojson",
               categorized("weight", [("heavy", "heavy (R/W, parcel lines)", symbol(L, "black", width=0.7)), ("light", "light", symbol(L, col("#5a5a5a", 160), width=0.2))])),
        raster("LiDAR intensity", "lidar_intensity.tif", 0.55),
        raster("LiDAR hillshade", "lidar_hillshade.tif", 1.0),
    ]
    p = QgsProject.instance()
    p.clear()
    p.setTitle("SWYFT Record Twin: Presidio sheet R-10434.2 on 2025 LiDAR")
    p.setCrs(QgsCoordinateReferenceSystem(UTM))
    p.setFileName(str(OUT / "demo.qgz"))
    p.writeEntry("Paths", "/Absolute", False)
    p.setDistanceUnits(QgsUnitTypes.DistanceFeet); p.setAreaUnits(QgsUnitTypes.AreaSquareFeet)  # what a surveyor reads
    root = p.layerTreeRoot()
    for l in layers:
        p.addMapLayer(l, False)
        root.addLayer(l)
    extent = layers[-1].extent()
    assert p.write(), "project write failed"

    # proof: re-read and render the opening view
    p.clear()
    assert p.read(str(OUT / "demo.qgz")), "project re-read failed"
    tree = [n.layer() for n in p.layerTreeRoot().findLayers()]
    assert all(l is not None and l.isValid() for l in tree) and len(tree) == len(layers), "a layer did not survive the round trip"
    ms = QgsMapSettings()
    ms.setLayers(tree); ms.setDestinationCrs(p.crs()); ms.setBackgroundColor(QColor("white"))
    ms.setOutputSize(QSize(2000, 900)); ms.setExtent(extent)
    job = QgsMapRendererSequentialJob(ms); job.start(); job.waitForFinished()
    img = job.renderedImage(); img.save(str(OUT / "demo_render.png"))
    ptr = img.constBits(); ptr.setsize(img.sizeInBytes())
    ink = int((np.frombuffer(ptr, np.uint8) < 250).sum())
    print(f"demo.qgz: {len(tree)} layers valid after round trip, CRS {p.crs().authid()}, "
          f"{sum(l.featureCount() for l in tree if isinstance(l, QgsVectorLayer))} features; demo_render.png {img.width()}x{img.height()}, {ink} inked samples")
    assert ink > 100000, "the render is blank"
    app.exitQgis()


if __name__ == "__main__":
    main()
