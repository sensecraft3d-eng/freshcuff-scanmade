"""API behaviour on the synthetic hand: orientation in any pose, units, mirror, open meshes, loose pieces,
no dead ends (needs_input + overrides), tape handling, messages in plain English."""
import json
import re
import numpy as np
import pytest
import trimesh
import fc_api as A
import synth_hand as SH
from fc_strings import STRINGS

INTERNAL_CODES = re.compile(r'\b(G0?\d{1,2}|R0[0-9][A-Z]?|R08A|T[1-7]|faixa B|B0[1-5]|N0[0-9])\b')


def prep(tmp_path, V, F, name='h.stl', **opts):
    f = SH.write_mesh(tmp_path / name, V, F)
    return A.prepare(f, tmp_path / ('w_' + name.split('.')[0]), opts)


def test_prepare_reference(tmp_path, synth):
    p = prep(tmp_path, *synth)
    assert p['status'] == 'ok', p['messages']
    lm = p['landmarks']
    assert lm['side'] == 'right' and lm['found_automatically'] and not lm['ambiguities']
    assert 15.5 < lm['knuckle_circumference_cm'] < 18.5
    assert p['scan']['units_guess'] == 'mm' and p['scan']['open_edges'] == 0 and p['scan']['components'] == 1
    assert p['scan']['quality']['score'] >= 85
    assert (tmp_path / 'w_h' / 'preview.glb').exists()
    json.dumps(p)                                              # JSON-serialisable as returned
    # view frame: band centred, +z toward the wrist, back of hand up
    g = trimesh.load(tmp_path / 'w_h' / 'preview.glb')
    assert {'hand', 'knuckle_line', 'band_0', 'band_4', 'thumb'} <= set(g.geometry)
    Vh = np.asarray(g.geometry['hand'].vertices)
    assert Vh[:, 2].min() < -60 and Vh[:, 2].max() > 60        # fingers at -z, wrist at +z
    k = np.asarray(g.geometry['knuckle_line'].vertices)
    assert np.allclose(k[:, 2], -12.8, atol=1e-6)
    thumb = np.asarray(g.geometry['thumb'].vertices)
    assert thumb[:, 0].mean() < -30                            # right hand: thumb at -x
    assert len(g.geometry['hand'].faces) <= 80000


@pytest.mark.parametrize('seed,scale,units', [(1, 1.0, 'mm'), (2, 0.001, 'm'), (3, 0.1, 'cm'), (4, 1 / 25.4, 'inch')])
def test_rotation_and_units_invariance(tmp_path, synth, seed, scale, units):
    V, F = synth
    ref = prep(tmp_path, V, F, 'ref.stl')['landmarks']
    R = SH.rotation(seed)
    p = prep(tmp_path, (V @ R.T + [50, -20, 300]) * scale, F, 'rot.stl')
    assert p['status'] == 'ok', p['messages']
    assert p['scan']['units_guess'] == units
    lm = p['landmarks']
    assert lm['side'] == 'right'
    assert abs(lm['knuckle_circumference_cm'] - ref['knuckle_circumference_cm']) < 0.03
    assert abs(lm['knuckle_width_mm'] - ref['knuckle_width_mm']) < 0.2
    assert abs(lm['thumb_z'] - ref['thumb_z']) < 0.5


def test_mirror_gives_left_hand(tmp_path, synth):
    V, F = synth
    p = prep(tmp_path, V * [-1, 1, 1], F[:, ::-1], 'left.stl')
    assert p['status'] == 'ok' and p['landmarks']['side'] == 'left'
    g = trimesh.load(tmp_path / 'w_left' / 'preview.glb')
    assert np.asarray(g.geometry['thumb'].vertices)[:, 0].mean() > 30     # left hand shown with the thumb at +x


def test_loose_piece_is_dropped(tmp_path, synth):
    V, F = synth
    cube = trimesh.creation.box(extents=(30, 30, 30))
    cube.apply_translation((260, 40, 0))
    p = prep(tmp_path, np.vstack([V, cube.vertices]), np.vstack([F, cube.faces + len(V)]), 'debris.stl')
    assert p['status'] == 'ok' and p['scan']['components'] == 2
    assert any(m['code'] == 'dropped_parts' for m in p['messages'])
    assert p['landmarks']['side'] == 'right'


def test_open_at_wrist_is_accepted_open_at_band_is_refused(tmp_path, synth):
    V, F = synth
    zc = V[F].mean(1)[:, 2]
    wrist_open = F[zc > V[:, 2].min() + 4]                    # cut the wrist cap off
    p = prep(tmp_path, V, wrist_open, 'wrist.stl')
    assert p['status'] == 'ok' and p['scan']['open_edges'] > 0 and p['scan']['open_edges_near_band'] == 0
    assert any(m['code'] == 'open_far' for m in p['messages'])
    a = A.analyze(tmp_path / 'w_wrist', {'tape_cm': None})
    assert a['status'] in ('custom_ready', 'standard_only'), a['messages']
    # a hole on the back of the hand inside the band
    c = V[F].mean(1)
    hole = (np.abs(c[:, 0]) < 6) & (c[:, 1] > 0) & (np.abs(c[:, 2] - 25) < 4)
    p = prep(tmp_path, V, F[~hole], 'hole.stl')
    assert p['scan']['open_edges_near_band'] > 0
    a = A.analyze(tmp_path / 'w_hole', {})
    assert a['status'] == 'refused'
    assert any(m['code'] in ('open_near_band', 'band_gap') for m in a['messages'])


def test_one_sided_surface_is_refused_with_reason(tmp_path, synth):
    V, F = synth
    top = F[V[F].mean(1)[:, 1] > 0]                            # only the back of the hand
    p = prep(tmp_path, V, top, 'half.stl')
    assert p['status'] == 'refused'
    assert any(m['code'] == 'open_surface' for m in p['messages'])
    assert p['preview_glb'] == 'preview.glb'


def test_unreadable_file(tmp_path):
    f = tmp_path / 'bad.stl'
    f.write_bytes(b'not a mesh at all')
    p = A.prepare(f, tmp_path / 'w', {})
    assert p['status'] == 'refused' and p['messages'][0]['level'] == 'error'


def test_wrong_declared_side_asks_instead_of_refusing(tmp_path, synth):
    p = prep(tmp_path, *synth, name='side.stl', side='left')    # it is a right hand
    assert p['status'] == 'needs_input'
    amb = p['landmarks']['ambiguities'][0]
    assert amb['kind'] == 'side' and len(amb['candidates']) == 2
    right = next(c for c in amb['candidates'] if c['overrides']['side'] == 'right')
    p2 = A.prepare(tmp_path / 'side.stl', tmp_path / 'w_side', dict(right['overrides']))
    assert p2['status'] == 'ok' and p2['landmarks']['side'] == 'right'


def test_dorsum_flip_override_and_click(tmp_path, synth):
    p = prep(tmp_path, *synth, name='ov.stl')
    lm = p['landmarks']
    other = 'flip' if lm['dorsum'] == 'kept' else 'keep'
    p2 = A.prepare(tmp_path / 'ov.stl', tmp_path / 'w_ov', {'dorsum': other})
    assert p2['landmarks']['dorsum'] != lm['dorsum'] and p2['landmarks']['side'] == 'left'    # flipped reading = other hand
    # knuckle click 5 mm toward the wrist, given in view coordinates of the latest preview; idempotent
    p3 = A.prepare(tmp_path / 'ov.stl', tmp_path / 'w_ov', {'knuckle_z': -12.8 + 5.0})
    p4 = A.prepare(tmp_path / 'ov.stl', tmp_path / 'w_ov', {'knuckle_z': -12.8 + 5.0})
    assert abs(abs(p3['landmarks']['knuckle_s'] - lm['knuckle_s']) - 5.0) < 1e-6
    assert p4['landmarks']['knuckle_s'] == p3['landmarks']['knuckle_s']
    assert not p3['landmarks']['found_automatically']
    # the same through the stable coordinate and the band shift
    p5 = A.prepare(tmp_path / 'ov.stl', tmp_path / 'w_ov', {'band_shift_mm': 5.0})
    assert abs(p5['landmarks']['knuckle_s'] - p3['landmarks']['knuckle_s']) < 1e-6
    bad = A.prepare(tmp_path / 'ov.stl', tmp_path / 'w_ov', {'knuckle_s': 9999.0})
    assert bad['status'] == 'needs_input' and bad['landmarks']['ambiguities'][0]['kind'] == 'knuckles'


@pytest.mark.slow
def test_fused_fingers_asks_for_the_knuckle_line(tmp_path):
    """A mitten-like hand (no finger separation) cannot be read automatically: ask, do not refuse."""
    h = 1.5
    lo = np.array([-50.0, -24.0, -84.0]); n = np.array([110, 32, 150])
    g = [lo[a] + (np.arange(n[a]) + 0.5) * h for a in range(3)]
    X, Y, Z = np.meshgrid(*g, indexing='ij')
    P = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    f = np.minimum(SH.implicit(P), SH._capsule(P, (-28, 2, 40), (28, 2, 40), 9.0))
    f = np.minimum(f, np.maximum(np.abs(P[:, 0]) - 38, np.maximum(np.abs(P[:, 1] - 2) - 9.5, np.abs(P[:, 2] - 85) - 50)))
    V, F = SH.voxel_surface((f < 0).reshape(n), lo, h)
    V = SH.smooth(V, F)
    p = prep(tmp_path, V, F, 'mitten.stl')
    assert p['status'] == 'needs_input'
    kinds = {a['kind'] for a in p['landmarks']['ambiguities']}
    assert kinds & {'knuckles', 'fingers'}
    assert (tmp_path / 'w_mitten' / 'preview.glb').exists()
    a = A.analyze(tmp_path / 'w_mitten', {'fingers': p['landmarks']['fingers_end'], 'knuckle_s': p['landmarks']['knuckle_s'],
                                          'thumb_s': p['landmarks']['thumb_s'], 'side': 'right'})
    assert a['status'] != 'needs_input' or all(x['kind'] not in ('knuckles', 'fingers') for x in a['landmarks']['ambiguities'])


def test_tape_optional_and_mismatch(tmp_path, synth):
    p = prep(tmp_path, *synth, name='tape.stl')
    scan_cm = p['landmarks']['knuckle_circumference_cm']
    a = A.analyze(tmp_path / 'w_tape', {'tape_cm': scan_cm + 3.0})
    assert a['status'] == 'refused' and any(m['code'] == 'tape_mismatch' for m in a['messages'])
    a = A.analyze(tmp_path / 'w_tape', {'tape_cm': 99})
    assert a['status'] == 'refused' and any(m['code'] == 'tape_range' for m in a['messages'])


@pytest.mark.slow
def test_analyze_synthetic_and_invariance(tmp_path, synth):
    V, F = synth
    res = []
    for name, VV, FF_ in (('a.stl', V, F), ('b.stl', (V @ SH.rotation(7).T) * 0.001, F), ('c.stl', V * [-1, 1, 1], F[:, ::-1])):
        prep(tmp_path, VV, FF_, name)
        a = A.analyze(tmp_path / ('w_' + name[0]), {})
        assert a['status'] in ('custom_ready', 'standard_only'), a['messages']
        assert any(m['code'] == 'no_tape' and m['level'] == 'warn' for m in a['messages'])
        assert len(a['sizes']) == 7 and a['recommended_size'] in range(1, 8)
        json.dumps(a)
        res.append(a)
    assert res[0]['landmarks']['side'] == res[1]['landmarks']['side'] == 'right' and res[2]['landmarks']['side'] == 'left'
    for r in res[1:]:
        assert r['recommended_size'] == res[0]['recommended_size']
        for s0, s1 in zip(res[0]['sizes'], r['sizes']):
            assert s0['fits'] == s1['fits'] and abs(s0['rigid_min'] - s1['rigid_min']) < 0.05
        if res[0]['custom']:
            assert r['custom'] and abs(r['custom']['W'] - res[0]['custom']['W']) <= 0.5
            assert abs(r['custom']['predicted']['after'] - res[0]['custom']['predicted']['after']) < 0.1


def test_no_internal_codes_in_user_text():
    for key, e in STRINGS.items():
        for lang, text in e.items():
            assert not INTERNAL_CODES.search(text), (key, lang, text)
        assert 'en' in e


def test_build_without_analysis_is_a_clean_stop(tmp_path, synth, repo):
    prep(tmp_path, *synth, name='nb.stl')
    b = A.build(tmp_path / 'w_nb', repo / 'web' / 'grade', repo / 'web' / 'dados')
    assert b['status'] == 'stopped' and b['messages'][0]['code'] == 'build_no_analysis'


def test_progress_is_translated_and_per_size(tmp_path, synth):
    f = SH.write_mesh(tmp_path / 'pg.stl', *synth)
    seen = []
    A.prepare(f, tmp_path / 'w', {'lang': 'pt'}, progress=seen.append)
    assert seen == ['Lendo o scan...', 'Procurando a linha dos nós...']
    seen.clear()
    A.prepare(f, tmp_path / 'w2', {'lang': 'en'}, progress=seen.append)
    assert seen[0] == 'Reading the scan...'


@pytest.mark.slow
def test_progress_per_size_and_width(tmp_path, synth):
    f = SH.write_mesh(tmp_path / 'pg.stl', *synth)
    A.prepare(f, tmp_path / 'w', {})
    seen = []
    A.analyze(tmp_path / 'w', {}, progress=seen.append)
    assert ['size %d' % t for t in range(1, 8)] == [s for s in seen if s.startswith('size ')]
    assert [s for s in seen if s.startswith('W ')] == ['W %.1f' % (80 + 0.5 * i) for i in range(9)]
