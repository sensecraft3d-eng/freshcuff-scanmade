# -*- coding: utf-8 -*-
"""Núcleo 2D do FreshCuff R08A para o gerador web (gerado por montar_nucleo_web.py; NÃO editar à mão).
Origem: construir_r08a.py sha256 035d95f8ac2f (funções até contours, sem OCP) + deformar/restaura_lamina/contornos_com_dorso
de construir_r08a_scan.py. A seção da base e o alvo do guia vêm de dados/contornos_base.json."""
import json as _json
_BASE = None
def carregar_base(caminho):
    global _BASE
    _BASE = _json.loads(open(caminho, encoding='utf-8').read())
"""FreshCuff R08A T4. Coordenadas e dimensões em mm. Saída nova por execução."""
import argparse
import math
import sys
from pathlib import Path

import numpy as np
import trimesh
from scipy.interpolate import CubicHermiteSpline, make_interp_spline
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union





HEIGHT = 26.
SKIN_RADIUS, LEAF_RADIUS = 1., .415
PAD = -29.75
NAME = 'FreshCuff_R08A_T4'

def smooth(x, lo, hi):
    t = np.clip((x-lo)/(hi-lo), 0., 1.)
    return t*t*(3.-2.*t)

def xy_section(mesh, z):
    return sorted((orient(Polygon(loop[:, :2])) for loop in
                   mesh.section([0,0,1],[0,0,z]).discrete), key=lambda p:p.area)

def vertical(poly, xs):
    cuts = [poly.intersection(LineString([(x,-70),(x,70)])).bounds for x in xs]
    return np.array([[v[1],v[3]] for v in cuts])

def normals(a):
    d = np.roll(a,-1,axis=0) - np.roll(a,1,axis=0)
    return np.column_stack([d[:,1],-d[:,0]]) / np.linalg.norm(d,axis=1)[:,None]

def sample(poly, step):
    ring = poly.exterior
    n = math.ceil(ring.length / step)
    return np.array([ring.interpolate(i/n,normalized=True).coords[0] for i in range(n)])

def contours():
    slit, aperture, outer = [orient(Polygon(_BASE[k])) for k in ('slit','aperture','outer')]
    target = Polygon(_BASE['target'])
    xs = np.arange(-39.,39.001,.1)
    delta = vertical(target,xs) - vertical(aperture,xs)
    def dorsal(x):
        result = np.interp(x,xs,delta[:,1])
        for side in (-1,1):
            a = side*x
            start = np.interp(side*26,xs,delta[:,1])
            slope = (start-np.interp(side*25.5,xs,delta[:,1]))/.5
            blend = CubicHermiteSpline([26,31,36,40.7],[start,start-.45,-1.18,0],
                                       [slope,0.,.14,0.])
            mask = a>26
            result[mask] = blend(np.clip(a[mask],26,40.7))
        return result
    shapes = {}
    for name,poly,step in [('outer',outer,.62),('skin',aperture,.52),('slot',slit,.32)]:
        a = sample(poly,step)
        x,y = a.T.copy()
        if name=='outer':
            a[:,1] += dorsal(x)*smooth(y,2,9)
            out = normals(a)
            extra = (.61+2.42*smooth(abs(x),6.,29.))*smooth(y,-6.,.0)
            a += extra[:,None]*out
            a[(abs(x)<20)&(y<-29.748),1] = PAD
            a[:,1] -= .025*(1.-smooth(y,-29.72,-28.8))
        else:
            # Deform both slit walls together to preserve vertical travel.
            dy = dorsal(x)*smooth(y,2.,9.)
            if name=='skin':
                palm = np.clip(np.interp(x,xs,delta[:,0])/4.8846,0.,1.16)
                palm *= 1.-smooth(abs(x),19.,32.)
                # Soften lower shoulders away from thumb tabs and root.
                shoulder = .88*smooth(abs(x),24,33)*(1.-smooth(abs(x),35,41))
                dy += (palm+shoulder)*(1.-smooth(y,-16.,-10.))
            else:
                # Normal-thickness compensation for the change in dorsal slope.
                e = .15
                base_y = lambda q: np.interp(q,xs,vertical_cache)
                s0 = (base_y(x+e)-base_y(x-e))/(2*e)
                s1 = s0+(dorsal(x+e)-dorsal(x-e))/(2*e)
                correction = .9*(np.hypot(1.,s1)-np.hypot(1.,s0))
                dy += np.clip(correction,-.035,.14)*smooth(y,7,11)*(1.-smooth(abs(x),36,40))
            a[:,1] += dy
        if name=='outer':
            vertical_cache = vertical(aperture,xs)[:,1]
        shapes[name] = a
    return shapes



def deformar(a, DW, DH):
    # v2 (11/11): faixa y -9..7 (a -7,5..5,5 apertava o entalhe do contorno externo em y -5..-2,5 e o chanfro do topo se auto-cruzava no T1);
    # faixa x larga no dorso (10..40, lamina inclinada perde menos espessura: T1 0,865 x T4 0,899 mm a meia altura) e estreita no fundo (20..38,
    # preserva o bloco dos fixadores |x| < 20), com transicao suave entre y -10 e 0 (flancos |x| > 40 transladam DW nos dois casos).
    x, y = a[:, 0], a[:, 1]
    b = a.copy()
    w = smooth(y, -10., 0.)
    g = (1 - w) * smooth(np.abs(x), 24., 38.) + w * smooth(np.abs(x), 10., 40.)  # v4: fundo 24..38 (canto do bloco dos fixadores em |x| 20..24 fica igual)
    b[:, 0] = x + np.sign(x) * DW * g
    b[:, 1] = y + DH * smooth(y, -9., 7.)
    return b


def restaura_lamina(shapes, shapes0):
    # v3 (11/11): a deformacao em x afina a lamina inclinada do dorso (T1: 0,865 x 0,899 mm; no topo os chanfros quase se tocam e o solido do T1
    # sai invalido). Cada ponto do slot a menos de 3 mm da pele e empurrado para fora (direcao pele->slot) ate a espessura normal do T4 no mesmo ponto.
    from shapely.geometry import Point, LinearRing
    sk0 = LinearRing(shapes0['skin']); sk = LinearRing(shapes['skin']); out = shapes['slot'].copy()
    for j, (p0, p) in enumerate(zip(shapes0['slot'], shapes['slot'])):
        d0 = sk0.distance(Point(p0)); P = Point(p); d = sk.distance(P)
        if d0 < 3.0 and d < d0:
            q = sk.interpolate(sk.project(P)); v = np.array([p[0] - q.x, p[1] - q.y]); v /= np.linalg.norm(v)
            out[j] = p + v * (d0 - d)
    shapes = dict(shapes); shapes['slot'] = out
    return shapes

def contornos_com_dorso(raise_json):
    """Mesma funcao contours() do R08A, com um acrescimo dorsal pessoal somado ao delta do guia anatomico
    (delta[:,1] += raise(x)). Como o mesmo dorsal(x) desloca pele, fenda e contorno externo, o curso da mola se preserva."""
    import inspect, json as _j
    d = raise_json if isinstance(raise_json, dict) else _j.loads(Path(raise_json).read_text(encoding='utf-8'))
    xr, rr = np.array(d['x_T4']), np.array(d['raise'])
    s = inspect.getsource(contours)
    old = "    delta = vertical(target,xs) - vertical(aperture,xs)\n"
    assert s.count(old) == 1
    s = s.replace(old, old + "    delta[:,1] += np.interp(xs, _XR, _RR)\n")
    ns = dict(globals()); ns['_XR'] = xr; ns['_RR'] = rr
    exec(s, ns)
    return ns['contours']()

