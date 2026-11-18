# Digito em poligono (fonte DejaVu Sans Bold), altura h, centrado em (0,0)
from matplotlib.textpath import TextPath
from matplotlib.font_manager import FontProperties
import shapely.geometry as sg
from shapely import affinity
def digito(txt, h):
    tp = TextPath((0, 0), txt, size=10, prop=FontProperties(family='DejaVu Sans', weight='bold'))
    ps = [sg.Polygon(p) for p in tp.to_polygons() if len(p) > 2]
    g = ps[0]
    for p in ps[1:]: g = g.symmetric_difference(p)
    b = g.bounds; k = h/(b[3] - b[1])
    g = affinity.scale(g, k, k, origin=(0, 0)); b = g.bounds
    return affinity.translate(g, -(b[0] + b[2])/2, -(b[1] + b[3])/2).buffer(0)
