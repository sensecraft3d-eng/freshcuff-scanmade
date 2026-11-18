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
from OCP.gp import gp_Pnt, gp_Vec, gp_Trsf
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_Sewing,
    BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Transform)
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeBox
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Common
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepLib import BRepLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.StlAPI import StlAPI_Writer
from OCP.gp import gp_Ax2, gp_Dir, gp_Circ
from OCP.Geom import Geom_BSplineCurve
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
from OCP.IFSelect import IFSelect_RetDone

PROJECT = Path(__file__).resolve().parents[3]
BASE = PROJECT / 'trabalho/K1d_CAD/PULSEIRA_R07i/K1c-C-PL-R07i-T4_impressao.stl'
GUIDE = PROJECT / 'entregas/ESTUDO_CONTORNO_ANATOMICO_R01_20261109/perfis_anatomicos_5_planos.csv'
MARK = PROJECT / 'trabalho/K1d_CAD/PULSEIRA_R07f'
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
    slit, aperture, outer = xy_section(trimesh.load(BASE),3.173)
    table = np.loadtxt(GUIDE,delimiter=',',skiprows=1)
    target = Polygon(table[abs(table[:,0]-13)<.01,4:6])
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

def spline_edge(pts,tangent_a,tangent_b):
    chord = pts[-1]-pts[0]
    if np.linalg.norm(chord)>1.e-7:
        d = np.cross(pts-pts[0],chord)/np.linalg.norm(chord)
        if np.max(np.linalg.norm(d,axis=1)) < 1.e-8:
            return BRepBuilderAPI_MakeEdge(gp_Pnt(*pts[0]),gp_Pnt(*pts[-1])).Edge()
    s = make_interp_spline(np.arange(len(pts)),pts,bc_type=([(1,tangent_a)],[(1,tangent_b)]))
    knots,mults = np.unique(s.t,return_counts=True)
    poles = TColgp_Array1OfPnt(1,len(s.c))
    kv = TColStd_Array1OfReal(1,len(knots))
    mv = TColStd_Array1OfInteger(1,len(knots))
    for i,p in enumerate(s.c,1): poles.SetValue(i,gp_Pnt(*p))
    for i,(k,m) in enumerate(zip(knots,mults),1):
        kv.SetValue(i,k)
        mv.SetValue(i,int(m))
    return BRepBuilderAPI_MakeEdge(Geom_BSplineCurve(poles,kv,mv,3,False)).Edge()

def wire(points,z):
    n = len(points)
    a = np.column_stack((points,np.full(n,z)))
    d = (np.roll(a,-1,axis=0)-np.roll(a,1,axis=0))*.5
    w = BRepBuilderAPI_MakeWire()
    for ix in np.array_split(np.arange(n),max(8,n//23)):
        j,k = ix[0],(ix[-1]+1)%n
        w.Add(spline_edge(a[np.r_[ix,k]],d[j],d[k]))
    return w.Wire()

def arc_offset(r,distance):
    return r-np.sqrt(np.maximum(0.,r*r-np.maximum(r-distance,0.)**2))

def section_wires(shapes,z):
    wires = []
    for name,a in shapes.items():
        x,y = a.T
        if name=='outer':
            # The mounting boss has R2 plan corners. A full R2.5 inward
            # offset folds there; ease to R1.6 around boss and thumb tabs.
            radius = 1.6+.9*smooth(y,-5.,1.)
            base = np.where(z<radius*(1.-math.sqrt(.5)),2*radius*(1.-math.sqrt(.5))-z,arc_offset(radius,z))
            off = -np.maximum(arc_offset(radius,26-z),base)
        elif name=='slot':
            # Radius blends at the keyhole neck, where the slit locally opens.
            off = arc_offset(.25+(LEAF_RADIUS-.25)*smooth(y,-7.2,-5.8),26-z)
        else:
            rigid = 1.-smooth(y,-12,-8)
            radius = LEAF_RADIUS+(SKIN_RADIUS-LEAF_RADIUS)*rigid
            off = np.maximum(arc_offset(radius,26-z),np.maximum(0.,.4+.45*rigid-z))
        wires.append(wire(a+np.asarray(off).reshape(-1,1)*normals(a),z))
    return wires

def shell_solid(shapes):
    # Planar ends and ruled strips use the same boundary wires and consistent seams.
    zs = [0.,.4,.85,1.46,2.5,23.5,24.5,25.,25.35,25.6,25.78,25.9,25.97,26.]
    sections = [section_wires(shapes,z) for z in zs]
    sew = BRepBuilderAPI_Sewing(2.e-5)
    for wires in (sections[0],sections[-1]):
        face = BRepBuilderAPI_MakeFace(wires[0],True)
        for hole in wires[1:]: face.Add(TopoDS.Wire_s(hole.Reversed()))
        sew.Add(face.Face())
    for contour in range(3):
        skin = BRepOffsetAPI_ThruSections(False,True,1.e-6)
        skin.CheckCompatibility(False)
        for ws in sections: skin.AddWire(ws[contour])
        skin.Build()
        sew.Add(skin.Shape())
    sew.Perform()
    sh = TopExp_Explorer(sew.SewedShape(),TopAbs_SHELL)
    solid = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(sh.Current())).Solid()
    sh.Next()
    assert not sh.More(), 'separate shell'
    assert BRepLib.OrientClosedSolid_s(solid)
    return solid

def polygon_wire(points):
    w = BRepBuilderAPI_MakePolygon()
    for p in points: w.Add(gp_Pnt(*p))
    w.Close()
    return w.Wire()

def xz_prism(poly,y0,y1):
    def path(ring): return polygon_wire([(x,y0,z) for x,z in ring.coords[:-1]])
    geom = orient(poly)
    face = BRepBuilderAPI_MakeFace(path(geom.exterior),True)
    for hole in geom.interiors: face.Add(path(hole))
    return BRepPrimAPI_MakePrism(face.Face(),gp_Vec(0,y1-y0,0)).Shape()

def boolean(op,body,tool):
    b = op(body,tool)
    if not b.IsDone(): raise RuntimeError(op.__name__)
    return b.Shape()

def fasteners(body):
    # Machine the registration plane before the recesses. This also removes
    # spline overshoot at the short tangencies of the original mounting pad.
    trim = BRepPrimAPI_MakeBox(gp_Pnt(-65,PAD-3,-1),gp_Pnt(65,PAD,27)).Shape()
    body = boolean(BRepAlgoAPI_Cut,body,trim)
    for x in (-12.,12.):
        # Single wire with exact 270-degree arc and two roof slopes.
        from OCP.GC import GC_MakeArcOfCircle
        p = lambda dx,dz: gp_Pnt(x+dx,PAD-.5,13+dz)
        r = 3.3
        q = r/math.sqrt(2)
        left,right,tip = p(-q,q),p(q,q),p(0,2*q)
        w = BRepBuilderAPI_MakeWire()
        w.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(left,p(0,-r),right).Value()).Edge())
        w.Add(BRepBuilderAPI_MakeEdge(right,tip).Edge())
        w.Add(BRepBuilderAPI_MakeEdge(tip,left).Edge())
        port = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(w.Wire()).Face(),gp_Vec(0,9.5,0)).Shape()
        body = boolean(BRepAlgoAPI_Cut,body,port)
        a = 5.2
        pocket = Polygon([(x-a,13-a/math.sqrt(3)),(x,13-2*a/math.sqrt(3)),
                          (x+a,13-a/math.sqrt(3)),(x+a,26.5),(x-a,26.5)])
        body = boolean(BRepAlgoAPI_Cut,body,xz_prism(pocket,-27.05,-21.65))
        # Radius 1 entry, flaring in X and Y toward the top.
        bell = BRepOffsetAPI_ThruSections(True,True,1.e-6)
        bell.CheckCompatibility(False)
        for z in [25.,25.4,25.72,25.9,25.97,26.,26.4]:
            f = arc_offset(1.,max(0.,26-z))
            bell.AddWire(polygon_wire([(x-a-f,-27.05-f,z),(x+a+f,-27.05-f,z),
                                       (x+a+f,-21.65+f,z),(x-a-f,-21.65+f,z)]))
        bell.Build()
        body = boolean(BRepAlgoAPI_Cut,body,bell.Shape())
    return body

def thumbs(body):
    r = (4.**2+1.5**2)/3.
    for sign in (-1,1):
        tool = BRepOffsetAPI_ThruSections(True,True,1.e-6)
        tool.CheckCompatibility(False)
        for z in (3.95,5.5,8.,9.,10.,12.,13.,14.,16.,17.,18.,20.5,22.05):
            depth = min(1.5,z-4.,22.-z) - sum(.5*max(0.,1-abs(z-k)) for k in (9,13,17))
            cx = sign*(55.3-depth+r)
            c = gp_Circ(gp_Ax2(gp_Pnt(cx,-11,z),gp_Dir(0,0,1)),r)
            tool.AddWire(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(c).Edge()).Wire())
        tool.Build()
        body = boolean(BRepAlgoAPI_Cut,body,tool.Shape())
    return body

def logo_polygons():
    dxf = (MARK/'marca/SenseCraft_Icone_S_CAD_H7p00_v1_1.dxf').read_text('latin1').splitlines()
    groups = list(zip(map(str.strip,dxf[::2]),map(str.strip,dxf[1::2])))
    loops = []
    verts = None
    for code,val in groups:
        if code=='0':
            if verts: loops.append(Polygon(verts))
            verts = [] if val=='LWPOLYLINE' else None
        elif verts is not None:
            if code=='10': px = float(val)
            if code=='20': verts.append((-px*12/7,13+float(val)*12/7))
    geo = unary_union(loops)
    return [geo] if geo.geom_type=='Polygon' else list(geo.geoms)

def marks(body):
    from shapely import affinity
    sys.path.insert(0,str(MARK))
    from marca_num import digito
    digit = affinity.translate(digito('4',7),yoff=13)
    body = boolean(BRepAlgoAPI_Cut,body,xz_prism(digit,PAD-.2,PAD+.4))
    transform = gp_Trsf()
    transform.SetTranslation(gp_Vec(0,.4,0))
    envelope = BRepBuilderAPI_Transform(body,transform,False).Shape()
    for poly in logo_polygons():
        piece = boolean(BRepAlgoAPI_Common,envelope,xz_prism(poly,23.,30.))
        body = boolean(BRepAlgoAPI_Fuse,body,piece)
    return body

def write_step(body,path):
    writer = STEPControl_Writer()
    assert writer.Transfer(body,STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(path)) == IFSelect_RetDone

def main(out):
    out.mkdir(parents=True,exist_ok=False)
    shapes = contours()
    print('Perfis reconstruídos',flush=True)
    body = shell_solid(shapes)
    for label,operation in [('corpo',None),('fixadores',fasteners),('abas',thumbs),('marcas',marks)]:
        if operation: body = operation(body)
        assert BRepCheck_Analyzer(body).IsValid(), label
        print(label,'válido',flush=True)
    it = TopExp_Explorer(body,TopAbs_SOLID)
    solid = TopoDS.Solid_s(it.Current())
    it.Next()
    assert not it.More()
    write_step(solid,out/(NAME+'.step'))
    BRepMesh_IncrementalMesh(solid,.024,False,.14,True)
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    assert writer.Write(solid,str(out/(NAME+'.stl')))
    print('STEP e STL exportados',flush=True)

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    main(parser.parse_args().output)

