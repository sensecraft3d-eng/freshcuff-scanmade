"""FreshCuff R08A em tamanhos (T1-T7) a partir do gerador R08A T4 (construir_r08a.py, sem alterar o original).
11/11/2026 (Claude). Pedro: 'temos que fazer as pulseiras nos outros tamanhos tb, e os insertos seguindo os tamanhos'.
Deformacao 2D dos tres contornos do T4 (outer/skin/slot) ANTES do solido:
  x: dx = sinal(x) * DW * [fundo: smoothstep(|x|,20,38) | dorso: smoothstep(|x|,10,40)] -> estica onde as paredes sao horizontais (topo e fundo);
     palma central e bloco dos fixadores (|x| < 20) e flancos (|x| > 38) ficam iguais / so transladam.
  y: dy = DH * smoothstep(y, -9, 7)                 -> so a faixa y -9..7 estica (ai as paredes sao verticais: flancos);
     fundo (palma, bloco dos fixadores, abas do polegar) igual; dorso (mola, slot, topo) so translada DH.
Os raios e chanfros de borda (offsets por secao) sao calculados nas coordenadas do T4 (mesma regra do original);
as normais vem do contorno deformado. Fixadores (PAD, porcas x +-12), espessuras e raios: iguais ao T4.
Abas do polegar transladam DW; logo S no dorso translada DH; numero do tamanho gravado na face da placa.
Uso: python construir_r08a_tam.py <saida> --tam N --dw DW --dh DH"""
import argparse, math, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import construir_r08a as c
from construir_r08a import smooth

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

def section_wires_tam(shapes0, shapes, z):
    wires = []
    for name, a0 in shapes0.items():
        a = shapes[name]
        x, y = a0.T            # regras de raio pelas coordenadas do T4
        if name == 'outer':
            radius = 1.6 + .9 * smooth(y, -5., 1.)
            base = np.where(z < radius * (1. - math.sqrt(.5)), 2 * radius * (1. - math.sqrt(.5)) - z, c.arc_offset(radius, z))
            off = -np.maximum(c.arc_offset(radius, 26 - z), base)
        elif name == 'slot':
            off = c.arc_offset(.25 + (c.LEAF_RADIUS - .25) * smooth(y, -7.2, -5.8), 26 - z)
        else:
            rigid = 1. - smooth(y, -12, -8)
            radius = c.LEAF_RADIUS + (c.SKIN_RADIUS - c.LEAF_RADIUS) * rigid
            off = np.maximum(c.arc_offset(radius, 26 - z), np.maximum(0., .4 + .45 * rigid - z))
        wires.append(c.wire(a + np.asarray(off).reshape(-1, 1) * c.normals(a), z))
    return wires

def main(out, tam, DW, DH):
    out.mkdir(parents=True, exist_ok=False)
    shapes0 = c.contours()
    shapes = {k: deformar(v, DW, DH) for k, v in shapes0.items()}
    shapes = restaura_lamina(shapes, shapes0)
    np.savez(out / 'contornos.npz', **{k + '_T4': v for k, v in shapes0.items()}, **shapes)
    c.section_wires = lambda shp, z: section_wires_tam(shapes0, shp, z)
    # abas do polegar: transladam DW (cx = sinal*(55,3-...+r) no original)
    orig_thumbs = c.thumbs
    def thumbs(body):
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Circ, gp_Ax2, gp_Pnt, gp_Dir
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        r = (4.**2 + 1.5**2) / 3.
        for sign in (-1, 1):
            tool = BRepOffsetAPI_ThruSections(True, True, 1.e-6); tool.CheckCompatibility(False)
            for z in (3.95, 5.5, 8., 9., 10., 12., 13., 14., 16., 17., 18., 20.5, 22.05):
                depth = min(1.5, z - 4., 22. - z) - sum(.5 * max(0., 1 - abs(z - k)) for k in (9, 13, 17))
                cx = sign * (55.3 + DW - depth + r)
                cc = gp_Circ(gp_Ax2(gp_Pnt(cx, -11, z), gp_Dir(0, 0, 1)), r)
                tool.AddWire(BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(cc).Edge()).Wire())
            tool.Build()
            body = c.boolean(BRepAlgoAPI_Cut, body, tool.Shape())
        return body
    def marks(body):
        from shapely import affinity
        from OCP.gp import gp_Trsf, gp_Vec
        from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Common
        sys.path.insert(0, str(c.MARK))
        from marca_num import digito
        digit = affinity.translate(digito(str(tam), 7), yoff=13)
        body = c.boolean(BRepAlgoAPI_Cut, body, c.xz_prism(digit, c.PAD - .2, c.PAD + .4))
        tr = gp_Trsf(); tr.SetTranslation(gp_Vec(0, .4, 0))
        envelope = BRepBuilderAPI_Transform(body, tr, False).Shape()
        for poly in c.logo_polygons():
            piece = c.boolean(BRepAlgoAPI_Common, envelope, c.xz_prism(poly, 23. + DH, 30. + DH))
            body = c.boolean(BRepAlgoAPI_Fuse, body, piece)
        return body
    c.NAME = f'FreshCuff_R08A_T{tam}'
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.StlAPI import StlAPI_Writer
    body = c.shell_solid(shapes)
    for label, op in [('corpo', None), ('fixadores', c.fasteners), ('abas', thumbs), ('marcas', marks)]:
        if op: body = op(body)
        assert BRepCheck_Analyzer(body).IsValid(), label
        print(label, 'valido', flush=True)
    it = TopExp_Explorer(body, TopAbs_SOLID); solid = TopoDS.Solid_s(it.Current()); it.Next(); assert not it.More()
    c.write_step(solid, out / (c.NAME + '.step'))
    BRepMesh_IncrementalMesh(solid, .024, False, .14, True)
    w = StlAPI_Writer(); w.ASCIIMode = False; assert w.Write(solid, str(out / (c.NAME + '.stl')))
    print('STEP e STL exportados', out / (c.NAME + '.stl'), flush=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('output', type=Path); p.add_argument('--tam', type=int, required=True)
    p.add_argument('--dw', type=float, required=True); p.add_argument('--dh', type=float, required=True)
    a = p.parse_args(); main(a.output, a.tam, a.dw, a.dh)
