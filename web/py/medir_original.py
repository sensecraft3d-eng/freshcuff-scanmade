# -*- coding: utf-8 -*-
"""Medidas de secao dos casos da varredura (15/11/2026, Claude). Mesmo metodo de TAMANHOS_R01/verificar_tam.py
(lamina normal, vao lateral, aro do ombro, coroa, fenda, abertura em z=13,003), reescrito aqui para nao depender
dos caminhos relativos daquele script. Referencia dos fixadores: o caso W82_ref (DW=DH=0).
Uso: python medir.py saida_dir resultado.json [ref_stl]"""
import sys, json, numpy as np, trimesh, manifold3d as m3
from pathlib import Path
from shapely.geometry import Polygon, Point, LineString
def smooth(x, lo, hi):
    t = np.clip((np.asarray(x, float) - lo) / (hi - lo), 0, 1); return t * t * (3 - 2 * t)
def points(g):
    if g.is_empty: return []
    if g.geom_type == 'Point': return [np.array(g.coords[0])]
    if hasattr(g, 'geoms'): return [a for q in g.geoms for a in points(q)]
    return [np.array(g.coords[0]), np.array(g.coords[-1])]
def yvals(r, x): return sorted(p[1] for p in points(r.boundary.intersection(LineString([(x, -80), (x, 80)]))))
def xvals(r, y): return sorted(p[0] for p in points(r.boundary.intersection(LineString([(-90, y), (90, y)]))))
def ndist(p, d, b):
    hits = points(b.intersection(LineString([p + .00002 * d, p + 18 * d]))); return min(float(np.dot(q - p, d)) for q in hits)
def sections(mesh, z):
    loops = sorted((Polygon(a[:, :2]) for a in mesh.section([0, 0, 1], [0, 0, z]).discrete), key=lambda s: -s.area)
    return loops[0], next(q for q in loops[1:] if q.contains(Point(0, 0))), next(q for q in loops if q.bounds[1] > -12 and q.area > 120)
def mapx(x, DW, y=10.):
    w = smooth(y, -10., 0.); g = (1 - w) * smooth(abs(x), 24., 38.) + w * smooth(abs(x), 10., 40.); return float(x + np.sign(x) * DW * g)
def spans(loops, DW, DH):
    frame, ap, slot = loops; th, lat, st = [], [], []
    X36 = mapx(36., DW); a26, a36 = mapx(26., DW), mapx(36., DW)
    for x in np.arange(-X36, X36 + .01, .25):
        try:
            y = yvals(ap, x)[-1]; s = (yvals(ap, x + .06)[-1] - yvals(ap, x - .06)[-1]) / .12
            d = np.array([-s, 1.]); d /= np.linalg.norm(d); th.append((x, ndist(np.array([x, y]), d, slot.boundary)))
            if a26 <= abs(x) <= a36:
                ys = yvals(slot, x)[-1]; s = (yvals(slot, x + .06)[-1] - yvals(slot, x - .06)[-1]) / .12
                d = np.array([-s, 1.]); d /= np.linalg.norm(d); st.append((x, ndist(np.array([x, ys]), d, frame.boundary)))
        except Exception: pass
    for side in (-1, 1):
        k = 1 if side == -1 else -2
        for y in np.arange(-6., 8. + max(DH, -6) * 0.9, .125):
            try:
                u = xvals(slot, y); x = u[k]; dx = (xvals(slot, y + .03)[k] - xvals(slot, y - .03)[k]) / .06
                d = side * np.array([1., -dx]); d /= np.linalg.norm(d); lat.append((x, y, ndist(np.array([x, y]), d, slot.boundary)))
            except Exception: pass
    return th, lat, st
def mf(t): return m3.Manifold(m3.Mesh(np.asarray(t.vertices, np.float32), np.asarray(t.faces, np.uint32)))
box = lambda x0, x1, y0, y1, z0, z1: m3.Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))
saida = Path(sys.argv[1]); var = json.loads((saida / 'varredura_resultado.json').read_text(encoding='utf-8'))
ref = Path(sys.argv[3]) if len(sys.argv) > 3 else saida / 'W82_ref' / 'cuff_W82_ref.stl'
M4 = mf(trimesh.load(ref)); reg = box(-20, 20, -29.3, -20, -1, 27)
res = []
for c in var:
    r = dict(id=c['id'], grupo=c.get('grupo'), W=c.get('W'), dw=c['dw'], dh=c['dh'], gerou=bool(c.get('exportou')), erro=c.get('erro'))
    f = saida / c['id'] / f"cuff_{c['id']}.stl"
    if f.exists():
        try:
            m = trimesh.load(f); M = mf(m)
            n = sections(m, 13.003); th, lat, st = spans(n, c['dw'], c['dh']); q = sections(m, 3.173)
            fx = float(((M ^ reg) - (M4 ^ reg)).volume() + ((M4 ^ reg) - (M ^ reg)).volume())
            r.update(fechado=bool(m.is_watertight), pecas=len(m.split()), volume_cm3=round(m.volume / 1000, 2), ext_mm=[round(v, 1) for v in m.extents],
                     abertura_L_y0=round(float(np.ptp(xvals(n[1], 0))), 2), abertura_H_x0=round(float(np.ptp(yvals(n[1], 0))), 2),
                     abertura_perimetro=round(n[1].exterior.length, 1),
                     lamina_min=round(min(v for _, v in th), 3) if th else None, vao_lateral_min=round(min(v[-1] for v in lat), 3) if lat else None,
                     aro_ombro_min=round(min(v for _, v in st), 3) if st else None, coroa=round(yvals(q[0], 0)[-1] - yvals(q[2], 0)[-1], 3),
                     fenda_centro=round(float(np.ptp(yvals(n[2], 0))), 3), fixadores_xor_mm3=round(fx, 4))
        except Exception as e:
            r.update(medida_erro=str(e)[:200])
    res.append(r); print(json.dumps(r, ensure_ascii=False), flush=True)
Path(sys.argv[2]).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding='utf-8')
