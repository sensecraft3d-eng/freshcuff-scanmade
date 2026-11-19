"""CAD folder: runs from a clean clone and reproduces the published geometry.

Fast tests need only the standard test dependencies. The build tests need cadquery-ocp
(and manifold3d for the checks); they are marked slow and skip when OCP is missing.
    python -m pytest tests/cad -m slow -ra
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CAD = REPO / 'cad'
SRC = CAD / 'src'
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(CAD))


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_assets_present():
    import paths
    for p in (paths.BASE_STL, paths.GUIDE_CSV, paths.LOGO_DXF, paths.SIZE_TABLE):
        assert p.is_file(), p
    # the same base section and guide that web/dados/contornos_base.json was extracted from
    origin = json.loads((REPO / 'web/dados/contornos_base.json').read_text(encoding='utf-8'))['origem']
    assert sha256(paths.BASE_STL) == origin['base_stl_sha256']
    assert sha256(paths.GUIDE_CSV) == origin['guia_sha256']
    assert sha256(SRC / 'original' / 'construir_r08a.py') == origin['construir_r08a_sha256']


def test_no_machine_specific_paths():
    bad = re.compile(r'[A-Z]:\\\\|[A-Z]:\\[A-Za-z]|/mnt/|/home/|parents\[3\]')
    for f in [*SRC.glob('*.py'), CAD / 'build.py', CAD / 'compare.py']:
        lines = [ln for ln in f.read_text(encoding='utf-8').splitlines() if not ln.lstrip().startswith('#')]
        hits = [ln for ln in lines if bad.search(ln)]
        assert not hits, f'{f.name}: {hits}'


def test_size_table_matches_formula():
    import build
    t = build.size_table()
    assert sorted(t) == list(range(1, 8))
    for n, (W, DW, DH) in t.items():
        assert W == 70 + 4 * (n - 1)
        assert DW == pytest.approx((W - 82) / 2)
        assert DH == pytest.approx(35.5 * (W / 82 - 1), abs=6e-4)


def test_grid_ids_match_web_index():
    import build
    ids = {f'W{W:.1f}_{s}' for W in build.GRID_WIDTHS for s, _ in build.SIDES}
    web = json.loads((REPO / 'web/grade/indice_grade_web.json').read_text(encoding='utf-8'))
    assert ids == {r['id'] for r in web}
    for r in web:
        dw, dh = build.width_params(r['W'])
        assert (dw, dh) == (r['dw'], r['dh'])


def test_custom_params_formats(tmp_path):
    import build
    (tmp_path / 'd.json').write_text(json.dumps({'x_T4': [-39, 39], 'raise': [0, 0]}))
    (tmp_path / 'en.json').write_text(json.dumps({'W': 82.5, 'side': 'left', 'dorsal_profile': 'd.json'}))
    p = build.read_params(tmp_path / 'en.json')
    assert (p['dw'], p['dh'], p['left'], p['label']) == (0.25, 0.2165, True, 'L')
    assert p['profile'] == str((tmp_path / 'd.json').resolve())
    (tmp_path / 'pt.json').write_text(json.dumps({'W': 81, 'dw': -0.5, 'dh': -0.4329, 'esquerda': False, 'rotulo': 'R', 'dorso': 'd.json'}))
    p = build.read_params(tmp_path / 'pt.json')
    assert (p['dw'], p['left'], p['label']) == (-0.5, False, 'R')


def _needs_ocp():
    pytest.importorskip('OCP')


@pytest.mark.slow
def test_web_core_regenerates_identically(tmp_path):
    _needs_ocp()
    subprocess.run([sys.executable, str(SRC / 'montar_nucleo_web.py'), str(tmp_path)], check=True, capture_output=True)
    assert sha256(tmp_path / 'py/nucleo_r08a.py') == sha256(REPO / 'web/py/nucleo_r08a.py')
    assert sha256(tmp_path / 'dados/contornos_base.json') == sha256(REPO / 'web/dados/contornos_base.json')


def _build_size4(tmp_path):
    out = tmp_path / 'size4'
    subprocess.run([sys.executable, str(CAD / 'build.py'), 'size', '4', '--out', str(out)], check=True)
    assert (out / 'FreshCuff_R08A_T4.step').is_file()
    published = json.loads((REPO / 'web/py/cuff_openings_R08A_v2.json').read_text(encoding='utf-8'))['sizes']['4']['sha256']
    return out / 'FreshCuff_R08A_T4.stl', published


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get('FC_REFERENCE_ENV'),
                    reason='byte identity is checked only in the reference environment (set FC_REFERENCE_ENV=1); '
                           'elsewhere OpenCascade may triangulate differently, see the geometric test')
def test_size4_sha256_equals_published_in_reference_env(tmp_path):
    """Strict, reference environment only (Linux x86-64, Python 3.13, cadquery-ocp 7.9.3.1.1, see cad/README.md):
    the rebuilt size 4 must be byte-identical to the published solid. The same OCP wheel on GitHub's runners
    gives a different triangulation of the same shape, so CI relies on the geometric test below."""
    _needs_ocp()
    stl, published = _build_size4(tmp_path)
    assert sha256(stl) == published


@pytest.mark.slow
def test_size4_is_geometrically_equivalent_to_published(tmp_path):
    """Any platform: the rebuilt size 4 has the published geometry (another OCP build may tessellate differently, so
    the hash is not required here): closed single solid, same volume, same bounding box, same band openings."""
    _needs_ocp()
    import numpy as np
    import trimesh
    from shapely.geometry import Polygon, Point
    stl, _ = _build_size4(tmp_path)
    m = trimesh.load(stl)
    assert m.is_watertight and len(m.split()) == 1
    assert abs(m.volume - 52978.6) < 5
    assert abs(m.extents[2] - 26.0) < 0.01
    ref = json.loads((REPO / 'web/py/cuff_openings_R08A_v2.json').read_text(encoding='utf-8'))['sizes']['4']['z']
    for z, c in ref.items():
        sec = m.section(plane_origin=[0, 0, float(z)], plane_normal=[0, 0, 1])
        polys = [Polygon(v[:, :2]) for v in sec.discrete if len(v) > 3]
        opening = min((p for p in polys if p.is_valid and p.contains(Point(0, 0))), key=lambda p: p.area)
        pub = Polygon(c['contour'])
        assert abs(opening.area - pub.area) < 0.5, z
        assert opening.symmetric_difference(pub).area < 1.0, z
        assert np.allclose(opening.bounds, pub.bounds, atol=0.02), z


@pytest.mark.slow
def test_grid_variant_matches_web_grid(tmp_path):
    _needs_ocp()
    pytest.importorskip('manifold3d')
    import compare
    out = tmp_path / 'grid'
    subprocess.run([sys.executable, str(CAD / 'build.py'), 'grid', '--out', str(out), '--only', 'W82.0_R'], check=True)
    rec = json.loads((out / 'indice_grade_rl.json').read_text(encoding='utf-8'))[0]
    assert rec['gerou'] and rec['falhas'] == []
    r = compare.compare(out / 'W82.0_R' / 'cuff_W82.0_R.stl', REPO / 'web/grade/W82.0_R.stl', samples=5000)
    # Reference environment: float-level agreement. Elsewhere (e.g. CI runners) OpenCascade may triangulate the same
    # shape slightly differently, so the bound is geometric: well below print resolution.
    strict = bool(os.environ.get('FC_REFERENCE_ENV'))
    assert abs(r['volume_diff_mm3']) < (0.01 if strict else 0.5)
    assert max(map(abs, r['bbox_min_diff_mm'] + r['bbox_max_diff_mm'])) < (1e-3 if strict else 0.01)
    # deviation_max is a sampled maximum (random surface points), so on other triangulations it lands around 0.01 mm
    assert r['deviation_max_mm'] < (1e-3 if strict else 0.05)
