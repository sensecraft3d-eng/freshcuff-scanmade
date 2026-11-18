"""End-to-end regression on the Artec sample hand (CC BY 3.0): the new engine must reproduce the validated R07
result (reference numbers in fixtures/legacy_artec_reference.json, produced by the untouched legacy code)."""
import json
import os
import subprocess
import sys
import zipfile
import numpy as np
import pytest
import trimesh
import fc_api as A
import synth_hand as SH
from conftest import ARTEC, REPO, FIX

pytestmark = pytest.mark.slow
TOL = 0.05      # mm


@pytest.fixture(scope='module')
def ref():
    return json.loads((FIX / 'legacy_artec_reference.json').read_text(encoding='utf8'))


def test_statuses_and_speed(artec_run):
    work, p, a, b = artec_run
    assert (p['status'], a['status'], b['status']) == ('ok', 'custom_ready', 'cuff_ready')
    total = p['seconds'] + a['seconds'] + b['seconds']
    print('seconds: prepare %.1f analyze %.1f build %.1f total %.1f' % (p['seconds'], a['seconds'], b['seconds'], total))
    assert total < 60, 'full run should stay well under a minute in CPython (target 30 s on 2 cores)'


def test_same_choice_and_gaps_as_legacy(artec_run, ref):
    _, p, a, b = artec_run
    cu = a['custom']
    assert cu['variant'] == ref['variant'] and cu['W'] == ref['W'] and cu['side'] == 'left'
    assert abs(cu['pose']['dx_mm'] - ref['pose']['dx_mm']) < 1e-9 and abs(cu['pose']['dy_mm'] - ref['pose']['dy_mm']) < 1e-9
    assert abs(cu['lateral_clearance_mm'] - ref['lateral_min_raw']) < TOL
    assert abs(cu['palm_compression_mm'] + ref['rigid_min_raw']) < TOL
    before, after = ref['prediction']['antes'], ref['prediction']['depois_bruto']
    pr = cu['predicted']
    assert abs(pr['closest_section_gap_before'] - before['folga_media_corte_mais_proximo_mm']) < TOL
    assert abs(pr['raw_after']['folga_media_corte_mais_proximo_mm'] - after['folga_media_corte_mais_proximo_mm']) < TOL
    assert abs(pr['raw_after']['maior_sobreposicao_mm'] - after['maior_sobreposicao_mm']) < TOL
    assert abs(pr['raw_after']['folga_media_todos_cortes_mm'] - after['folga_media_todos_cortes_mm']) < TOL
    assert abs(pr['share_le_0p5'] - ref['prediction']['depois']['frac_corte_mais_proximo_ate_0_5mm']) < 0.01
    for g in a['custom_range']:                                   # the whole W 80-84 table
        r = ref['grid']['%.1f' % g['W']]
        assert g['fits'] == r['viavel']
        for k_new, k_old in (('rigid_min', 'rigido_min_mm'), ('dorsal_min', 'dorso_min_mm'), ('lateral_min', 'lateral_min_mm')):
            assert abs(g[k_new] - r[k_old]) < TOL
    assert a['smallest_fitting_size'] == ref['fit']['menor_tamanho_compativel_faixa']
    assert a['size_by_tape'] == ref['fit']['tamanho_pela_fita_scan']
    assert abs(p['landmarks']['knuckle_circumference_cm'] - ref['fit']['nos']['fita_scan_cm']) < 0.005


def test_same_solid_locks_and_verification_as_legacy(artec_run, ref):
    work, _, _, b = artec_run
    assert b['hashes']['stl_sha256'] == ref['stl_sha256'], 'generated STL differs from the validated one'
    assert not b['locks']['failures'] and all(c['ok'] for c in b['locks']['checks'])
    for k, v in ref['locks_raw'].items():
        got = b['locks']['raw'][k]
        assert got == v if isinstance(v, bool) else abs(got - v) < 1e-6, k
    v = b['verification']
    assert v['verdict'] == 'approved' and not v['failures']
    same = ref['verification_same_pose_raw']
    assert abs(v['same_pose']['closest_section_gap'] - same['folga_media_corte_mais_proximo_mm']) < TOL
    assert abs(v['same_pose']['max_overlap'] - same['maior_sobreposicao_mm']) < TOL
    assert abs(v['same_pose']['rigid_min'] - same['rigido_min_mm']) < TOL
    assert abs(v['same_pose']['lateral_min'] - same['lateral_min_mm']) < TOL
    assert abs(v['gap_difference_mm'] - ref['verdict']['dif_folga_bruta_mm']) < 1e-6
    assert v['limits'] == {'gap_difference_mm': 0.15, 'rigid_min_mm': -0.5, 'spring_travel_mm': 2.1, 'lateral_min_mm': 0.4}


def test_outputs_and_provenance(artec_run):
    work, p, a, b = artec_run
    for k in ('stl', '3mf', 'report_json', 'report_html'):
        assert (work / b['files'][k]).exists(), k
    z = zipfile.ZipFile(work / b['files']['3mf'])
    assert '3D/Objects/object_1.model' in z.namelist() and z.testzip() is None
    rep = json.loads((work / b['files']['report_json']).read_text(encoding='utf8'))
    assert rep['scan']['sha256'] == p['scan']['sha256'] and rep['outputs']['stl_sha256'] == b['hashes']['stl_sha256']
    for f in ('fc_api.py', 'fc_core.py', 'fc_fastfit.py', 'freshcuff_fit.py', 'gerador_scan.py', 'gerador_web.py'):
        assert len(rep['programs_sha256'][f]) == 64
    assert rep['variant']['id'] == a['custom']['variant'] and rep['parameters']['faixa_B']['w_min'] == 80.0
    html = (work / b['files']['report_html']).read_text(encoding='utf8')
    assert html.count('<svg') == 6 and 'http' not in html.replace('http-equiv', '')      # standalone: no external assets
    assert 'W82.0_L' in html and 'approved' in html


def test_glbs(artec_run):
    work, p, a, b = artec_run
    sizes = 0
    for name, nodes in (('preview.glb', {'hand', 'knuckle_line', 'band_0', 'thumb'}), ('analysis.glb', {'hand', 'knuckle_line', 'cuff_outline_0', 'cuff_outline_4'}),
                        ('result.glb', {'hand', 'cuff'})):
        sizes += (work / name).stat().st_size
        g = trimesh.load(work / name)
        assert nodes <= set(g.geometry), name
    assert sizes < 8e6
    g = trimesh.load(work / 'result.glb')
    hand, cuff = g.geometry['hand'], g.geometry['cuff']
    assert abs(cuff.bounds[0][2] + 13) < 0.01 and abs(cuff.bounds[1][2] - 13) < 0.01       # band centred on z = 0
    V = np.asarray(hand.vertices)
    band = np.abs(V[:, 2]) < 12
    lo, hi = cuff.bounds
    palm = band & (np.abs(V[:, 0]) < 45)                                                    # (the thumb crosses the band's z range)
    assert palm.sum() > 1000 and np.all(V[palm, 1] > lo[1]) and np.all(V[palm, 1] < hi[1])
    assert np.mean((V[band, 0] > lo[0]) & (V[band, 0] < hi[0])) > 0.8
    col = np.asarray(hand.visual.vertex_colors)[:, :3]
    assert len(np.unique(col[band], axis=0)) > 20 and len(np.unique(col[~band & (np.abs(V[:, 2]) > 14)], axis=0)) == 1
    assert a['legend'][0]['mm'] < 0 < a['legend'][-1]['mm']


def _close(x, y, where, tol=1e-3):
    """Same structure, same strings and booleans; numbers equal within tol."""
    if isinstance(x, dict):
        assert isinstance(y, dict) and set(x) == set(y), where
        for k in x:
            _close(x[k], y[k], f'{where}.{k}', tol)
    elif isinstance(x, list):
        assert isinstance(y, list) and len(x) == len(y), where
        for i, (u, v) in enumerate(zip(x, y)):
            _close(u, v, f'{where}[{i}]', tol)
    elif isinstance(x, bool) or x is None or isinstance(x, str):
        assert x == y, where
    elif isinstance(x, (int, float)):
        assert isinstance(y, (int, float)) and not isinstance(y, bool) and abs(x - y) <= tol, (where, x, y)
    else:
        assert x == y, where


def test_fixture_files_match_current_engine(artec_run):
    """tests/fixtures/artec is what the UI is developed against: it must agree with a fresh run."""
    _, p, a, b = artec_run
    fa = json.loads((FIX / 'artec' / 'analyze.json').read_text())
    fb = json.loads((FIX / 'artec' / 'build.json').read_text())
    assert fa['status'] == a['status'] and fa['custom']['variant'] == a['custom']['variant']
    # numbers: equal to 0.001 (mm, mm2 or score); another numpy/scipy build may change the last digits
    _close(fa['custom']['predicted'], a['custom']['predicted'], 'custom.predicted')
    _close(fa['sizes'], a['sizes'], 'sizes')
    assert fb['hashes']['stl_sha256'] == b['hashes']['stl_sha256'] and set(fb) == set(b)


@pytest.mark.parametrize('case', ['rotated_metres', 'mirrored'])
def test_artec_rotation_scale_mirror(tmp_path, artec_run, case):
    _, p0, a0, _ = artec_run
    m = trimesh.load(ARTEC, process=False)
    V, F = np.asarray(m.vertices, dtype=np.float64), np.asarray(m.faces)
    if case == 'rotated_metres':
        V, side, variant = (V @ SH.rotation(11).T + [10, 200, -40]) * 0.001, 'left', 'W82.0_L'
    else:
        V, F, side, variant = V * [1, -1, 1], F[:, ::-1], 'right', 'W82.0_R'
    f = tmp_path / (case + '.ply')
    trimesh.Trimesh(V, F, process=False).export(f)
    p = A.prepare(f, tmp_path / 'w', {'tape_cm': 18.2})          # side detected; tape confirms the scale
    assert p['status'] == 'ok' and p['landmarks']['side'] == side
    assert p['scan']['units_guess'] == ('m' if case == 'rotated_metres' else 'mm')
    a = A.analyze(tmp_path / 'w', {})
    assert a['status'] == 'custom_ready' and a['custom']['variant'] == variant
    # The validated pose rule works on a 0.25 mm lateral grid with tie-breaks, so a re-sampled copy of the same hand
    # (float32 file, other units) may seat one grid step aside: W must not change, numbers stay within 0.1 mm.
    assert a['custom']['W'] == a0['custom']['W']
    for k in ('closest_section_gap_before', 'after', 'max_overlap'):
        assert abs(a['custom']['predicted'][k] - a0['custom']['predicted'][k]) <= 0.1, k
    assert abs(a['custom']['lateral_clearance_mm'] - a0['custom']['lateral_clearance_mm']) < 0.1
    assert abs(p['landmarks']['knuckle_circumference_cm'] - p0['landmarks']['knuckle_circumference_cm']) < 0.01
    assert [s['fits'] for s in a['sizes']] == [s['fits'] for s in a0['sizes']]
    A.release(tmp_path / 'w')


def test_cli(tmp_path):
    r = subprocess.run([sys.executable, str(REPO / 'fc_cli.py'), str(ARTEC), '--out', str(tmp_path / 'o'), '--side', 'left',
                        '--tape-cm', '18.2', '--build', '--quiet'], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    assert 'BUILD  status: cuff_ready' in r.stdout and 'W 82.0 mm' in r.stdout and 'Recommended standard size: 4' in r.stdout
    r = subprocess.run([sys.executable, str(REPO / 'fc_cli.py'), str(ARTEC), '--out', str(tmp_path / 'o2'), '--tape-cm', '25', '--json'],
                       capture_output=True, text=True)
    assert r.returncode == 3 and json.loads(r.stdout)['analyze']['status'] == 'refused'


@pytest.mark.legacy
@pytest.mark.skipif(not os.environ.get('FC_RUN_LEGACY'), reason='set FC_RUN_LEGACY=1 to run the original code (about 2 min)')
def test_reference_file_matches_legacy_code(tmp_path, ref):
    import gerador_web as GW
    r = GW.analisar(str(ARTEC), 'esquerda', 18.2, str(tmp_path / 'leg'), str(REPO / 'web' / 'dados'), 'mao', [], progresso=lambda s: None)
    assert r['resultado'] == 'ANALISE_PRONTA' and r['variante'] == ref['variant']
    r = GW.montar(str(tmp_path / 'leg'), str(REPO / 'web' / 'grade'), str(REPO / 'web' / 'dados'), progresso=lambda s: None)
    assert r['resultado'] == 'CUFF_PRONTO' and r['stl_sha256'] == ref['stl_sha256']


def test_heatmap_only_on_the_band(artec_run):
    """No coloured vertex may lie farther than 5 mm from the band sections (the thumb tip crosses the band's z range)."""
    import shapely
    from shapely.geometry import Polygon
    work, p, a, b = artec_run
    skin = np.array([224, 190, 168])
    secs = [(s['z_cuff'], Polygon(s['hand']).buffer(0)) for s in a['sections']]
    zs = np.array([z for z, _ in secs])
    for name in ('analysis.glb', 'result.glb'):
        h = trimesh.load(work / name).geometry['hand']
        V = np.asarray(h.vertices)
        col = np.asarray(h.visual.vertex_colors)[:, :3]
        painted = np.any(col != skin, axis=1)
        assert painted.sum() > 1000, name
        P = V[painted]
        assert np.all(np.abs(P[:, 2]) <= 13.0 + 1e-6)
        k = np.abs((P[:, 2] + 13.0)[:, None] - zs[None, :]).argmin(1)
        d = np.zeros(len(P))
        for i, (_, poly) in enumerate(secs):
            m = k == i
            d[m] = shapely.distance(poly, shapely.points(np.c_[-P[m, 0], P[m, 1]]))      # left hand: view x = -CAD x
        assert d.max() <= 5.0, (name, d.max())
        assert not painted[V[:, 0] > 60].any(), name + ': thumb must stay skin-coloured'
