"""One figure per demo segment, rendered from the QGIS project so the slides show the same screen.

  fig_record.png   the sheet on the LiDAR with every check coloured by status (segment 1: the record)
  fig_parcels.png  parcels, LiDAR features and the encroachment screen (segment 2)
  fig_tunnel.png   the tunnel easements with the buildings over them (segment 3)
  fig_htdp.png     the 1991 -> 2010 epoch shift: sheet linework before (red) and after (black) on the intensity image

usage: %LOCALAPPDATA%\\Programs\\OSGeo4W\\bin\\python-qgis-ltr.bat spike/figures.py   (demo.py does this)
"""
import json
from pathlib import Path

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsGeometry, QgsMapRendererSequentialJob,
                       QgsMapSettings, QgsProject, QgsRectangle, QgsSingleSymbolRenderer, QgsSymbol, QgsVectorLayer, QgsWkbTypes)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

OUT = Path(__file__).resolve().parent / "out"


def render(layers, rect, name, size=(2400, 1200), crs=None):
    ms = QgsMapSettings()
    ms.setLayers(layers)  # top of the stack first, as in the legend
    ms.setDestinationCrs(crs); ms.setBackgroundColor(QColor("white"))
    ms.setOutputSize(QSize(*size)); ms.setExtent(rect)
    job = QgsMapRendererSequentialJob(ms); job.start(); job.waitForFinished()
    job.renderedImage().save(str(OUT / name))
    print(f"{name}: {rect.toString(0)}")


def pad(xmin, ymin, xmax, ymax, f=0.06):
    dx, dy = (xmax - xmin) * f, (ymax - ymin) * f
    return QgsRectangle(xmin - dx, ymin - dy, xmax + dx, ymax + dy)


def main():
    app = QgsApplication([], False)
    app.initQgis()
    p = QgsProject.instance()
    assert p.read(str(OUT / "demo.qgz"))
    L = {n.layer().name(): n.layer() for n in p.layerTreeRoot().findLayers()}
    by = lambda *names: [L[n] for n in names]
    utm = p.crs()
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:6318"), utm, p)
    ext = lambda lyr: tr.transformBoundingBox(lyr.extent())
    linework, parcels = L["Sheet linework R-10434.2"], L["Parcels from the sheet"]

    e = ext(linework)
    render(by("Object record: control points", "Object record: lines and checks", "Sheet linework R-10434.2", "LiDAR hillshade"), pad(e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()), "fig_record.png", crs=utm)
    e = ext(parcels)
    render(by("Encroachment clusters", "LiDAR features (pavement, deck, buildings)", "Parcels from the sheet", "Sheet linework R-10434.2", "LiDAR intensity", "LiDAR hillshade"),
           pad(e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum()), "fig_parcels.png", crs=utm)
    tun = QgsRectangle()
    for f in parcels.getFeatures():
        if str(f["parcel"]).startswith("61985"):
            tun.combineExtentWith(tr.transformBoundingBox(f.geometry().boundingBox()))
    render(by("Encroachment clusters", "LiDAR features (pavement, deck, buildings)", "Parcels from the sheet", "Sheet linework R-10434.2", "LiDAR hillshade"),
           pad(tun.xMinimum(), tun.yMinimum(), tun.xMaximum(), tun.yMaximum(), 0.1), "fig_tunnel.png", crs=utm)

    # HTDP before/after: undo the shift on a copy of the linework (memory layer in UTM), draw it red under the shifted black
    h = json.loads((Path(__file__).parent / "lidar" / "htdp.json").read_text())
    before = QgsVectorLayer("LineString?crs=EPSG:6339", "sheet linework at epoch 1991.35 (before HTDP)", "memory")
    prov = before.dataProvider()
    feats = []
    for f in linework.getFeatures():
        g = QgsGeometry(f.geometry()); g.transform(tr); g.translate(-h["dE_m"], -h["dN_m"])
        nf = QgsFeature(); nf.setGeometry(g); feats.append(nf)
    prov.addFeatures(feats); before.updateExtents()
    s = QgsSymbol.defaultSymbol(QgsWkbTypes.LineGeometry); s.setColor(QColor("#d01818")); s.symbolLayer(0).setWidth(0.5)
    before.setRenderer(QgsSingleSymbolRenderer(s))
    p.addMapLayer(before, False)
    # a 90 m window where a heavy sheet line runs along the LiDAR pavement edge: the shift is visible there
    feat_layer = L["LiDAR features (pavement, deck, buildings)"]
    pave = [QgsGeometry(f.geometry()) for f in feat_layer.getFeatures() if f["kind"] == "pavement"]
    for g in pave:
        g.transform(tr)
    edge = QgsGeometry.unaryUnion(pave).convertToType(QgsWkbTypes.LineGeometry) if pave else None
    best = None
    for f in linework.getFeatures():
        if f["weight"] != "heavy":
            continue
        g = QgsGeometry(f.geometry()); g.transform(tr)
        if g.length() < 40 or edge is None:
            continue
        d = g.distance(edge)
        if best is None or d < best[0]:
            best = (d, g)
    c = best[1].interpolate(best[1].length() / 2).asPoint() if best else ext(linework).center()
    render([linework, before, L["LiDAR intensity"]], QgsRectangle(c.x() - 45, c.y() - 22, c.x() + 45, c.y() + 22), "fig_htdp.png", size=(2400, 1174), crs=utm)
    app.exitQgis()


if __name__ == "__main__":
    main()
