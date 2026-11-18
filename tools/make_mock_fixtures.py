#!/usr/bin/env python3
"""DEV ONLY. Builds approximate mock outputs (JSON + GLB) with the fc_api shape so the UI can be designed without
waiting for Python in the browser. Numbers come from the CPython reference run on the Artec sample; the frame is
approximate. Output: tests/e2e/mock/. Used by the page only with ?mock=1 and tools/serve.py --dev.

  python3 tools/make_mock_fixtures.py <caso_artec_dir>
"""
import json, shutil, sys
from pathlib import Path
import numpy as np, trimesh

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / 'tests' / 'e2e' / 'mock'


def heat(gap):
    """gap (mm) -> rgb 0..1 : overlap red, contact green, gap blue."""
    stops = [(-1.0, (0.80, 0.15, 0.15)), (0.0, (0.95, 0.75, 0.20)), (0.5, (0.25, 0.70, 0.35)), (1.5, (0.20, 0.55, 0.80)), (3.0, (0.30, 0.30, 0.70))]
    g = np.clip(gap, stops[0][0], stops[-1][0])
    out = np.zeros((len(g), 3))
    for (a, ca), (b, cb) in zip(stops[:-1], stops[1:]):
        m = (g >= a) & (g <= b)
        t = ((g[m] - a) / (b - a))[:, None]
        out[m] = np.array(ca) * (1 - t) + np.array(cb) * t
    return out, [{'mm': s, 'rgb': [round(c * 255) for c in col]} for s, col in stops]


def main(caso):
    caso = Path(caso)
    fit = json.loads((caso / 'analise/fit/fit_relatorio.json').read_text(encoding='utf8'))
    al = fit['alinhamento']
    hand = trimesh.load(HERE / 'examples/Artec_Hand.ply', process=False)
    try:
        hand = hand.simplify_quadric_decimation(face_count=150000)
    except Exception as e:
        print('no decimation:', e)
    V = hand.vertices - np.array(al['centro_pca_removido_mm'])
    V = V @ np.array(al['R_pca']).T
    if al['dedos_girados_180_em_y']:
        V[:, 0] *= -1; V[:, 2] *= -1
    if al['dorso_girado_180_em_z']:
        V[:, 0] *= -1; V[:, 1] *= -1
    kz = fit['referencial_marcos']['z_nos_no_referencial_de_marcos']
    V[:, 2] = -(V[:, 2] - (kz - 13.0)); V[:, 0] *= -1
    hand = trimesh.Trimesh(V, hand.faces, process=False)
    grey = np.tile([200, 203, 205, 255], (len(V), 1)).astype(np.uint8)
    hand.visual.vertex_colors = grey

    def ring(z, r=1.0):
        sec = hand.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if sec is None:
            return None
        pts = [trimesh.creation.cylinder(radius=0.6, segment=[a, b], sections=6) for a, b in sec.vertices[sec.vertex_nodes]]
        m = trimesh.util.concatenate(pts)
        return m

    def scene(extra):
        s = trimesh.Scene()
        s.add_geometry(hand, node_name='hand', geom_name='hand')
        for name, g in extra:
            if g is not None:
                s.add_geometry(g, node_name=name, geom_name=name)
        return s

    OUT.mkdir(parents=True, exist_ok=True)
    kl = ring(-13.0); kl.visual.vertex_colors = [30, 34, 38, 255]
    band = trimesh.util.concatenate([r for r in (ring(z) for z in (-12.8, -6.5, 0.0, 6.5, 12.8)) if r is not None])
    band.visual.vertex_colors = [15, 118, 110, 255]
    thumb = trimesh.creation.icosphere(radius=3); thumb.apply_translation([V[:, 0].min() + 5, 0, 25]); thumb.visual.vertex_colors = [180, 90, 40, 255]
    scene([('knuckle_line', kl), ('band', band), ('thumb', thumb)]).export(OUT / 'preview.glb')

    # heat map on the band: fake gap from y (back of the hand larger gap)
    Vb = hand.vertices; inb = (Vb[:, 2] > -13) & (Vb[:, 2] < 13)
    gap = np.where(Vb[:, 1] > 5, 0.7 + 0.05 * (Vb[:, 2] + 13), 0.3 + 0.02 * np.abs(Vb[:, 0]) / 10)
    col, legend = heat(gap)
    c = grey.copy(); c[inb, :3] = (col[inb] * 255).astype(np.uint8)
    hheat = trimesh.Trimesh(Vb, hand.faces, process=False); hheat.visual.vertex_colors = c
    s = trimesh.Scene(); s.add_geometry(hheat, node_name='hand', geom_name='hand'); s.export(OUT / 'analysis.glb')

    cuff = trimesh.load(caso / 'cuff' / 'FreshCuff_Custom_scan_mao.stl')
    C = cuff.vertices.copy(); C[:, 2] = C[:, 2] - 13.0; C[:, 1] += 2.0
    cuff = trimesh.Trimesh(C, cuff.faces, process=False); cuff.visual.vertex_colors = [70, 74, 78, 255]
    s = trimesh.Scene(); s.add_geometry(hheat, node_name='hand', geom_name='hand'); s.add_geometry(cuff, node_name='cuff', geom_name='cuff')
    s.export(OUT / 'result.glb')
    shutil.copy(caso / 'cuff' / 'FreshCuff_Custom_scan_mao_P1S_PETG.3mf', OUT / 'cuff.3mf')
    shutil.copy(caso / 'cuff' / 'FreshCuff_Custom_scan_mao.stl', OUT / 'cuff.stl')
    shutil.copy(caso / 'relatorio_final.json', OUT / 'report.json')

    sizes = []
    for k, v in sorted(fit['encaixe_por_tamanho'].items(), key=lambda kv: int(kv[0])):
        sizes.append({'size': int(k), 'fits': bool(v['viavel']), 'rigid_min': v['rigido_min_mm'], 'dorsal_min': v['dorso_min_mm'],
                      'lateral_min': v['lateral_min_mm'], 'note': ''})
    prepare = {'status': 'ok',
               'scan': {'faces': 800000, 'vertices': 400002, 'extent_mm': [97.1, 41.3, 196.0], 'units_guess': 'mm', 'mm_per_unit': 1.0,
                        'watertight': True, 'open_edges_near_band': 0, 'components': 1,
                        'quality': {'score': 92, 'notes': ['Closed surface around the knuckles.', 'Fingers straight and apart.']}},
               'landmarks': {'side': 'left', 'side_confidence': 0.86, 'fingers_end': 'low', 'dorsum': 'flipped', 'dorsum_confidence': 0.78,
                             'knuckle_z': -13.0, 'thumb_z': 21.5, 'band': {'z0': -13.0, 'z1': 13.0}, 'ambiguities': []},
               'preview_glb': 'preview.glb', 'frame': {}, 'messages': [{'level': 'info', 'text': 'Scan read in millimetres (no scaling needed).'}]}
    analyze = {'status': 'custom_ready', 'sizes': sizes, 'recommended_size': fit['menor_tamanho_compativel_faixa'],
               'custom': {'W': 82.0, 'side': 'left', 'dorsal_profile_mm_min': -2.4,
                          'predicted': {'closest_section_gap_before': 2.52, 'after': 0.72, 'share_le_0p5': 0.41, 'max_overlap': 0.44}},
               'result_glb': 'analysis.glb', 'legend': legend, 'messages': []}
    build = {'status': 'cuff_ready', 'files': {'3mf': 'cuff.3mf', 'stl': 'cuff.stl', 'report_json': 'report.json'},
             'locks': {'failures': []}, 'verification': {'verdict': 'ok', 'closest_section_gap': 0.72, 'max_overlap': 0.44, 'palm_compression': 0.44},
             'result_glb': 'result.glb', 'legend': legend, 'messages': []}
    for n, d in (('prepare', prepare), ('analyze', analyze), ('build', build)):
        (OUT / f'{n}.json').write_text(json.dumps(d, indent=1), encoding='utf8')
    print('mock fixtures in', OUT, [p.name for p in OUT.iterdir()])


if __name__ == '__main__':
    main(sys.argv[1])
