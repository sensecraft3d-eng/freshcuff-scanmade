"""Release gates: what must be true before a size is recommended or a manufacturing file is handed out.

B1  no standard size passes the geometric check -> recommended_size is None (never the tape estimate)
B2  no custom STL/3MF without an independent scale check (tape given and within 0.6 cm of the scan)
M1  a stopped build returns no manufacturing file
m1  non-manifold edges at the band refuse the scan
M4  non-finite numbers anywhere in the chain end in a recorded refusal and zero manufacturing files
"""
import json
import math
import subprocess
import sys
import numpy as np
import pytest
import fc_api as A
import fc_core as C
import fc_fastfit as FF
import report_html
import synth_hand as SH
from conftest import ARTEC, REPO

GRID, DATA = REPO / 'web' / 'grade', REPO / 'web' / 'dados'
MANUFACTURING = ('stl', '3mf')


def no_manufacturing_files(b, work):
    assert not any(k in b['files'] for k in MANUFACTURING), b['files']
    assert not b.get('hashes'), b.get('hashes')
    for sub in work.glob('build_*'):
        for f in sub.iterdir():
            if f.suffix in ('.stl', '.3mf'):
                st = json.loads((work / 'fc_state.json').read_text())
                assert st.get('build', {}).get('status') == 'cuff_ready' and sub.name == st['build']['dir'] or \
                    _released_earlier(work, sub), 'manufacturing file left in ' + str(f)
    return True


def _released_earlier(work, sub):
    rep = sub / 'report.json'
    return rep.exists() and json.loads(rep.read_text())['status'] == 'cuff_ready'


# ------------------------------------------------------------------------------------------------ B1
def test_b1_no_size_recommended_when_nothing_passes(tmp_path, synth, monkeypatch):
    f = SH.write_mesh(tmp_path / 'h.stl', *synth)
    p = A.prepare(f, tmp_path / 'w', {})
    real_sizes = C.fit_sizes

    def none_fit(rd, lang='en', progress=None):                    # geometry says: every size is too small
        est, nos, ang, org = C.cad_sections(rd)
        sizes = [{'size': t, 'fits': False, 'rigid_min': -3.0 - t, 'dorsal_min': -2.5, 'lateral_min': -3.0, 'rotation_deg': 0.0,
                  'at_search_limit': [], 'note': 'does not fit'} for t in range(1, 8)]
        return sizes, {}, (ang, org), est

    def no_custom(*a, **k):
        raise C.CustomStop('standard_only', 'custom_none', grid=[])
    monkeypatch.setattr(C, 'fit_sizes', none_fit)
    monkeypatch.setattr(C, 'custom_cuff', no_custom)
    tape = p['landmarks']['knuckle_circumference_cm']
    for ov in ({}, {'tape_cm': tape}):
        A.release(tmp_path / 'w')
        a = A.analyze(tmp_path / 'w', ov)
        assert a['status'] == 'no_verified_standard_fit', a['status']
        assert a['recommended_size'] is None and a['smallest_fitting_size'] is None and a['custom'] is None
        assert a['size_by_tape'] in range(1, 8)                    # kept, as a separate estimate
        assert a['size_by_tape_source'] == ('tape' if ov else 'scan')
        assert any(m['code'] == 'no_verified_fit' for m in a['messages'])
        assert not any(m['code'] == 'use_standard' for m in a['messages'])
        assert 'heatmap_for' not in a
    b = A.build(tmp_path / 'w', GRID, DATA)
    assert b['status'] == 'stopped' and b['files'] == {}
    # the report shows no recommended number
    rep = {'status': 'stopped', 'analysis': {'sizes': a['sizes'], 'recommended_size': a['recommended_size'], 'size_by_tape': a['size_by_tape']},
           'scan': {}, 'landmarks': {}, 'messages': a['messages']}
    html = report_html.render(rep, 'en')
    assert '(recommended' not in html and 'class="rec"' not in html and 'circumference estimate' in html


def test_b1_standard_only_recommends_only_a_size_that_passed(tmp_path, synth, monkeypatch):
    f = SH.write_mesh(tmp_path / 'h.stl', *synth)
    A.prepare(f, tmp_path / 'w', {})

    def size5(rd, lang='en', progress=None):
        est, nos, ang, org = C.cad_sections(rd)
        return ([{'size': t, 'fits': t >= 5, 'rigid_min': 0.1, 'dorsal_min': 1.0, 'lateral_min': 0.5, 'rotation_deg': 0.0,
                  'at_search_limit': [], 'note': ''} for t in range(1, 8)], {}, (ang, org), est)

    def no_custom(*a, **k):
        raise C.CustomStop('standard_only', 'custom_narrow', lat=7.0, W=80.0, mx=6.0, grid=[])
    monkeypatch.setattr(C, 'fit_sizes', size5)
    monkeypatch.setattr(C, 'custom_cuff', no_custom)
    a = A.analyze(tmp_path / 'w', {})
    assert a['status'] == 'standard_only' and a['recommended_size'] == 5
    assert any(m['code'] == 'use_standard' and 'size 5' in m['text'] for m in a['messages'])


@pytest.mark.slow
def test_b1_real_oversized_hand(tmp_path):
    """A hand 40 % larger than the synthetic one is beyond size 7 and beyond the custom range (real searches)."""
    V, F = SH.make_hand()
    f = SH.write_mesh(tmp_path / 'big.stl', V * 1.4, F)
    p = A.prepare(f, tmp_path / 'w', {})
    a = A.analyze(tmp_path / 'w', {'tape_cm': p['landmarks']['knuckle_circumference_cm']})
    assert a['status'] == 'no_verified_standard_fit', (a['status'], a['messages'])
    assert a['recommended_size'] is None and not any(s['fits'] for s in a['sizes']) and a['size_by_tape'] in range(1, 8)


# ------------------------------------------------------------------------------------------------ B2 (fast part)
def test_b2_build_refuses_without_a_confirmed_scale(tmp_path, synth):
    f = SH.write_mesh(tmp_path / 'h.stl', *synth)
    A.prepare(f, tmp_path / 'w', {})
    st_file = tmp_path / 'w' / 'fc_state.json'
    st = json.loads(st_file.read_text())
    base = {'dir': 'analysis_01', 'variant': 'W82.0_R', 'pose': [0, [0, 0], [0, 0]], 'W': 82.0, 'lang': 'en'}
    for extra in ({'tape_cm': None, 'tape_scan_cm': 17.0, 'scale_confirmed': False},        # no tape
                  {'tape_cm': 17.1, 'tape_scan_cm': 17.0, 'scale_confirmed': False},        # never confirmed
                  {'tape_cm': 19.0, 'tape_scan_cm': 17.0, 'scale_confirmed': True},         # tampered: flag says yes, numbers say no
                  {'tape_cm': float('nan'), 'tape_scan_cm': 17.0, 'scale_confirmed': True}):
        st['analysis'] = dict(base, **extra)
        st_file.write_text(json.dumps(st).replace('NaN', 'NaN'))
        b = A.build(tmp_path / 'w', GRID, DATA)
        assert b['status'] == 'needs_input' and b['needs'] == ['tape_cm'] and b['files'] == {}
        assert b['messages'][0]['code'] == 'build_needs_tape'
        assert not list((tmp_path / 'w').glob('build_*'))


def test_b2_cli_build_requires_tape(tmp_path):
    r = subprocess.run([sys.executable, str(REPO / 'fc_cli.py'), str(ARTEC), '--out', str(tmp_path / 'o'), '--build'], capture_output=True, text=True)
    assert r.returncode == 2 and '--build requires --tape-cm' in r.stderr and not (tmp_path / 'o').exists()


# ------------------------------------------------------------------------------------------------ m1
def _tetra_on_edge(V, F, where):
    """Glue a small closed tetrahedron on one mesh edge near ``where``: that edge is then shared by 4 faces
    (non-manifold) while no open edge is created."""
    c = V[F].mean(1)
    k = int(np.argmin(np.linalg.norm(c - where, axis=1)))
    v0, v1, v2 = F[k]
    n = np.cross(V[v1] - V[v0], V[v2] - V[v0]); n /= np.linalg.norm(n)
    mid = 0.5 * (V[v0] + V[v1])
    side = np.cross(V[v1] - V[v0], n); side /= np.linalg.norm(side)
    a, b = mid + 1.5 * n + 0.8 * side, mid + 1.5 * n - 0.8 * side
    ia, ib = len(V), len(V) + 1
    V2 = np.vstack([V, a, b])
    F2 = np.vstack([F, [[v0, v1, ia], [v1, v0, ib], [v0, ia, ib], [v1, ib, ia]]])
    return V2, F2.astype(np.int32)


def test_m1_nonmanifold_edge_at_the_band_is_refused(tmp_path, synth):
    V, F = synth
    ref = A.prepare(SH.write_mesh(tmp_path / 'ok.stl', V, F), tmp_path / 'w0', {})
    assert ref['scan']['nonmanifold_near_band'] == 0
    V2, F2 = _tetra_on_edge(V, F, np.array([0.0, 14.0, SH.KNUCKLE_Z - 18.0]))       # back of the hand, inside the band
    p = A.prepare(SH.write_mesh(tmp_path / 'nm.stl', V2, F2), tmp_path / 'w1', {})
    assert p['scan']['open_edges_near_band'] == 0 and p['scan']['nonmanifold_near_band'] > 0
    assert any(m['code'] == 'nonmanifold_near_band' and m['level'] == 'error' for m in p['messages'])
    a = A.analyze(tmp_path / 'w1', {'tape_cm': ref['landmarks']['knuckle_circumference_cm']})
    assert a['status'] == 'refused' and a['recommended_size'] is None and a['sizes'] == []
    assert any(m['code'] == 'nonmanifold_near_band' for m in a['messages'])
    # the same defect far from the band (fingertip) does not refuse
    V3, F3 = _tetra_on_edge(V, F, np.array([9.5, 10.0, SH.KNUCKLE_Z + 70.0]))
    p = A.prepare(SH.write_mesh(tmp_path / 'far.stl', V3, F3), tmp_path / 'w2', {})
    assert p['scan']['nonmanifold_near_band'] == 0 and p['status'] == 'ok'


# ------------------------------------------------------------------------------------------------ slow: Artec
@pytest.fixture(scope='module')
def artec_work(tmp_path_factory):
    work = tmp_path_factory.mktemp('gates')
    p = A.prepare(ARTEC, work, {'side': 'left'})
    return work, p


@pytest.mark.slow
def test_b2_tape_missing_divergent_confirmed(artec_work):
    work, p = artec_work
    a = A.analyze(work, {})                                          # tape missing
    assert a['status'] == 'custom_needs_tape' and a['needs'] == ['tape_cm'] and not a['scale_confirmed']
    assert a['custom']['W'] == 82.0 and len(a['sizes']) == 7 and a['recommended_size'] == 4
    assert any(m['code'] == 'custom_needs_tape' for m in a['messages'])
    b = A.build(work, GRID, DATA)
    assert b['status'] == 'needs_input' and b['needs'] == ['tape_cm'] and b['files'] == {}
    assert not list(work.glob('build_*'))
    a = A.analyze(work, {'tape_cm': 18.2 + 0.7})                     # divergent (> 0.6 cm)
    assert a['status'] == 'refused' and any(m['code'] == 'tape_mismatch' for m in a['messages'])
    b = A.build(work, GRID, DATA)
    assert b['status'] == 'stopped' and b['files'] == {} and not list(work.glob('build_*'))
    a = A.analyze(work, {'tape_cm': 18.2})                           # confirmed (geometry re-used, not recomputed)
    assert a['status'] == 'custom_ready' and a['scale_confirmed'] and a['seconds'] < 5
    b = A.build(work, GRID, DATA)
    assert b['status'] == 'cuff_ready' and {'stl', '3mf', 'report_json', 'report_html'} <= set(b['files'])
    assert b['hashes']['stl_sha256'] == json.loads((REPO / 'tests/fixtures/legacy_artec_reference.json').read_text())['stl_sha256']


@pytest.mark.slow
def test_b2_ambiguous_units_block_until_tape(tmp_path):
    """The Artec hand saved in centimetres (18.3 units long) could also be inches: no release without the tape."""
    import trimesh
    m = trimesh.load(ARTEC, process=False)
    f = tmp_path / 'cm.ply'
    trimesh.Trimesh(np.asarray(m.vertices) * 0.1, m.faces, process=False).export(f)
    p = A.prepare(f, tmp_path / 'w', {'side': 'left'})
    assert p['scan']['units_guess'] == 'cm' and p['scan']['units_confidence'] < 0.9
    a = A.analyze(tmp_path / 'w', {})
    assert a['status'] == 'custom_needs_tape' and any(m['code'] == 'units_confirm' for m in a['messages'])
    assert A.build(tmp_path / 'w', GRID, DATA)['status'] == 'needs_input'
    a = A.analyze(tmp_path / 'w', {'tape_cm': 18.2})
    assert a['status'] == 'custom_ready'
    # wrong units forced by hand (inches): the tape catches it
    p = A.prepare(f, tmp_path / 'w_in', {'side': 'left', 'mm_per_unit': 25.4})
    a = A.analyze(tmp_path / 'w_in', {'tape_cm': 18.2})
    assert a['status'] in ('refused', 'needs_input') and a['custom'] is None
    A.release()


@pytest.fixture()
def ready(artec_work):
    work, _ = artec_work
    a = A.analyze(work, {'tape_cm': 18.2})
    assert a['status'] == 'custom_ready'
    return work


@pytest.mark.slow
def test_m1_lock_failure_returns_no_manufacturing_file(ready, monkeypatch):
    import gerador_web as GW
    real = GW.trava
    monkeypatch.setattr(GW, 'trava', lambda r: real(r) + ['G04'])
    b = A.build(ready, GRID, DATA)
    assert b['status'] == 'stopped' and b['locks']['failures'] and b['verification'] is None
    assert set(b['files']) <= {'report_json', 'report_html'} and not b['hashes']
    d = ready / json.loads((ready / 'fc_state.json').read_text())['build']['dir']
    assert not list(d.glob('*.stl')) and not list(d.glob('*.3mf'))
    rep = json.loads((ready / b['files']['report_json']).read_text())
    assert rep['status'] == 'stopped' and rep['outputs']['released'] is False
    assert any(m['code'] == 'build_locks_failed' for m in b['messages'])


@pytest.mark.slow
def test_m1_verification_failure_returns_no_manufacturing_file(ready, monkeypatch):
    import conferir_cuff_gerado as CC
    real = CC.veredito

    def reject(a, viavel, prev, par):
        return real(dict(a, lateral_min_mm=0.0), viavel, prev, par)          # side clearance below the minimum
    monkeypatch.setattr(CC, 'veredito', reject)
    b = A.build(ready, GRID, DATA)
    assert b['status'] == 'stopped' and b['verification']['verdict'] == 'rejected' and b['verification']['failures']
    assert set(b['files']) <= {'report_json', 'report_html'} and not b['hashes']
    d = ready / json.loads((ready / 'fc_state.json').read_text())['build']['dir']
    assert not list(d.glob('*.stl')) and not list(d.glob('*.3mf'))


# ------------------------------------------------------------------------------------------------ M4 non-finite
@pytest.mark.slow
@pytest.mark.parametrize('bad', [float('nan'), float('inf'), float('-inf')])
def test_m4_nonfinite_lock_measurement(ready, monkeypatch, bad):
    import gerador_web as GW
    real = GW.medir
    monkeypatch.setattr(GW, 'medir', lambda m, dw, dh: dict(real(m, dw, dh), lamina_min=bad))
    b = A.build(ready, GRID, DATA)
    assert b['status'] == 'stopped' and not any(k in b['files'] for k in MANUFACTURING) and not b['hashes']
    assert b['locks']['failures'], 'the non-finite measurement must be recorded as a failed check'
    assert b['locks']['checks'][0]['ok'] is False or bad == float('-inf')          # "all measurements are finite"
    json.dumps(b)
    rep = json.loads((ready / b['files']['report_json']).read_text())
    assert rep['status'] == 'stopped' and rep['locks']['failures']


@pytest.mark.slow
@pytest.mark.parametrize('key', ['folga_media_corte_mais_proximo_mm', 'maior_sobreposicao_mm'])
@pytest.mark.parametrize('bad', [float('nan'), float('inf')])
def test_m4_nonfinite_verification_metric(ready, monkeypatch, key, bad):
    import gerador_scan as G
    real = G.resumo_folga

    def poisoned(Gm, bruto=False):
        r = real(Gm, bruto)
        return dict(r, **{key: bad}) if bruto else r
    monkeypatch.setattr(G, 'resumo_folga', poisoned)
    b = A.build(ready, GRID, DATA)
    assert b['status'] == 'stopped' and b['verification']['verdict'] == 'rejected'
    assert not any(k in b['files'] for k in MANUFACTURING) and not b['hashes']
    assert any(m['code'] == 'build_verify_failed' for m in b['messages'])
    json.dumps(b)


@pytest.mark.slow
@pytest.mark.parametrize('field,bad', [('rigido_min_mm', float('nan')), ('lateral_min_mm', float('nan')), ('dorso_min_mm', float('inf')),
                                       ('lateral_min_mm', float('-inf'))])
def test_m4_nonfinite_pose_search_result(artec_work, monkeypatch, field, bad):
    work, _ = artec_work
    real = FF.fit_lateral

    def poisoned(*a, **k):
        r = real(*a, **k)
        return dict(r, **{field: bad}) if r.get('viavel') else r
    monkeypatch.setattr(FF, 'fit_lateral', poisoned)
    A.release(work)                                                  # drop the cached geometry of this session
    a = A.analyze(work, {'tape_cm': 18.2})
    assert a['status'] not in ('custom_ready', 'custom_needs_tape') and a['custom'] is None, a['status']
    assert any(m['level'] in ('warn', 'error') and m['code'].startswith('custom_') for m in a['messages'])
    json.dumps(a)
    b = A.build(work, GRID, DATA)
    assert b['status'] == 'stopped' and b['files'] == {}
    monkeypatch.undo()
    A.release(work)
