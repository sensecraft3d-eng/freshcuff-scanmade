#!/usr/bin/env python3
"""FreshCuff · gerador por scan R01 · conferência do STL gerado contra o scan (16/11/2026, Claude). v2c: veredito automático e hashes. v2f: veredito com valores brutos (R04-01). v2g: NaN/inf reprova (R05-01). v2h: a recusa por NaN/inf também grava conferencia_stl.json (R06-01); JSON sem NaN.
Lê <caso>/mao_faixa_cad.npz (cortes da mão no quadro CAD de mão direita, gravados pelo gerador_scan.py) e o STL do CAD.
Mão esquerda: o STL sai espelhado (--esquerda); aqui ele volta ao quadro de mão direita (x → −x) para a comparação.
 (a) mesma pose da previsão: folga dorsal por corte, invasão rígida e folga lateral, com as aberturas DO STL;
 (b) busca de pose nova com as aberturas do STL (a mão ainda assenta?).
Uso: python conferir_cuff_gerado.py <pasta_do_caso> <cuff.stl>"""
import sys, json, math
from pathlib import Path
import numpy as np, trimesh
from shapely.geometry import Polygon, Point
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freshcuff_fit as F
import gerador_scan as G

TOL = {'dif_folga_corte_proximo_mm': 0.15, 'rigido_min_mm': -0.5, 'lateral_tolerancia_mm': 0.1}


def json_seguro(x):
    """R06-01: valores não finitos viram texto ('NaN', 'inf', '-inf'), para o JSON ser válido e o REPROVADO ficar registrado."""
    if isinstance(x, dict): return {k: json_seguro(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [json_seguro(v) for v in x]
    if isinstance(x, float) and not math.isfinite(x): return 'NaN' if x != x else ('inf' if x > 0 else '-inf')
    return x


def veredito(a_bruto, viavel_pose_nova, prev_bruto, par):
    """R04-01 (rodada 4): todos os limites comparam valores BRUTOS (sem arredondar); arredondar só para mostrar."""
    curso = float(par.get('curso_mm', 2.1)); lat_alvo = float(par.get('folga_lateral_mm', 0.5))
    chaves = ('folga_media_corte_mais_proximo_mm', 'maior_sobreposicao_mm', 'rigido_min_mm', 'lateral_min_mm')
    valores = [a_bruto.get(k) for k in chaves] + [prev_bruto.get('folga_media_corte_mais_proximo_mm'), curso, lat_alvo]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in valores):   # R05-01: NaN/inf nunca aprova
        return {'resultado': 'REPROVADO', 'falhas': ['métrica ausente ou não finita (NaN/inf) na conferência'], 'dif_folga_bruta_mm': None,
                'limites': dict(TOL, curso_mm=curso, folga_lateral_alvo_mm=lat_alvo), 'comparacao': 'valores brutos'}
    dif = float(a_bruto['folga_media_corte_mais_proximo_mm']) - float(prev_bruto['folga_media_corte_mais_proximo_mm'])
    falhas = []
    if abs(dif) > TOL['dif_folga_corte_proximo_mm']: falhas.append('previsão de folga dorsal não confirmada no STL')
    if a_bruto['maior_sobreposicao_mm'] > curso: falhas.append('sobreposição dorsal acima do curso da mola')
    if a_bruto['rigido_min_mm'] < TOL['rigido_min_mm']: falhas.append('parte rígida invade além da hipótese de pele')
    if a_bruto['lateral_min_mm'] < lat_alvo - TOL['lateral_tolerancia_mm']: falhas.append('folga lateral abaixo do mínimo')
    if not viavel_pose_nova: falhas.append('a mão não assenta com as aberturas do STL (pose nova)')
    return {'resultado': 'APROVADO' if not falhas else 'REPROVADO', 'falhas': falhas, 'dif_folga_bruta_mm': dif,
            'limites': dict(TOL, curso_mm=curso, folga_lateral_alvo_mm=lat_alvo), 'comparacao': 'valores brutos'}


def main():
    caso, stl = Path(sys.argv[1]), Path(sys.argv[2])
    d = np.load(caso / 'mao_faixa_cad.npz')
    n = len(d['z_cuff']); zc = [float(z) for z in d['z_cuff']]
    est = [dict(poligono=Polygon(d[f'est{i}']), z_cuff=zc[i], dz=float(d['dz'][i]), estado='completo') for i in range(n)]
    pos = [d[f'pos{i}'] for i in range(n)]
    m = trimesh.load(stl)
    if bool(d['esquerda']):
        m.vertices[:, 0] *= -1; m.invert()
    ab = {}
    for z in sorted(set(zc)):
        s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        g = min([Polygon(v[:, :2]) for v in s.discrete if len(v) > 3 and Polygon(v[:, :2]).is_valid and Polygon(v[:, :2]).contains(Point(0, 0))],
                key=lambda g: g.area).simplify(0.02)
        ab[z] = F.Abertura(g, 26)
    X = d['X']
    Ga = G.matriz_folga_dorsal(pos, est, ab, X)
    rig = [ab[e['z_cuff']].medir(P) for P, e in zip(pos, est)]
    a_bruto = G.resumo_folga(Ga, bruto=True)
    a_bruto.update({'rigido_min_mm': float(min(r[0] for r in rig)), 'lateral_min_mm': float(min(r[2] for r in rig))})
    b = F.encaixe_faixa(est, ab, float(d['angulo']), tuple(d['origem']), 0.5, 2.1)
    Gb = G.matriz_folga_dorsal(b['_pos'], est, ab, X)
    rel_g = json.loads((caso / 'gerador_relatorio.json').read_text(encoding='utf8'))
    prev = rel_g['previsao_dorso']
    prev_bruto = prev.get('depois_bruto') or prev['depois']
    import hashlib
    par = json.loads((caso / 'parametros.json').read_text(encoding='utf8'))
    mostra = lambda dct, n=3: {k: (round(v, n) if isinstance(v, float) and math.isfinite(v) else v) for k, v in dct.items()}
    v = veredito(a_bruto, bool(b['viavel']), prev_bruto, par)
    out = {'stl': str(stl), 'stl_sha256': hashlib.sha256(stl.read_bytes()).hexdigest(),
           'parametros_sha256': hashlib.sha256((caso / 'parametros.json').read_bytes()).hexdigest(),
           'a_mesma_pose': mostra(a_bruto, 2), 'a_mesma_pose_bruto': a_bruto,
           'b_pose_nova': dict(mostra({k: b[k] for k in ('viavel', 'rigido_min_mm', 'dorso_min_mm', 'lateral_min_mm', 'giro_grau', 'dx_mm', 'dy_mm')}),
                               **G.resumo_folga(Gb)),
           'previsto_depois': prev['depois'], 'dif_folga_media_corte_proximo_mm': None if v['dif_folga_bruta_mm'] is None else round(v['dif_folga_bruta_mm'], 3),
       'veredito': v}
    out = json_seguro(out)
    with open(caso / 'conferencia_stl.json', 'x', encoding='utf8') as _f:   # nunca regrava (B02)
        _f.write(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
