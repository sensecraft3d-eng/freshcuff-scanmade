import numpy as np
import pytest
import trimesh
import fc_mesh as M
import freshcuff_fit as F


@pytest.mark.parametrize('ext,units,k', [(0.19, 'm', 1000.0), (19.0, 'cm', 10.0), (190.0, 'mm', 1.0), (7.5, 'inch', 25.4),
                                         (450.0, 'mm', 1.0), (45.0, 'cm', 10.0)])
def test_units_guess(ext, units, k):
    kk, name, conf, _ = M.guess_units(ext)
    assert (name, kk) == (units, k)
    assert 0 < conf <= 1


def test_units_manual_and_ambiguous():
    assert M.guess_units(3.0, 25.4)[:2] == (25.4, 'inch')
    assert M.guess_units(18.0)[2] < 0.9          # 18 could be cm or inches: lower confidence, cm assumed
    assert M.guess_units(18.0)[1] == 'cm'
    with pytest.raises(ValueError):
        M.guess_units(100.0, -1)


def test_slicer_matches_legacy_section(synth):
    V, Fc = synth
    m = trimesh.Trimesh(V.copy(), Fc, process=False)
    S = M.Slicer(V.copy(), Fc)
    for z in np.linspace(S.zmin + 4, S.zmax - 4, 23):
        a, b = S.section(z), F.corte(m, z)
        assert len(a[0]) == len(b[0]) and a[1] == b[1]
        for p, q in zip(a[0], b[0]):
            assert np.array_equal(np.asarray(p.exterior.coords), np.asarray(q.exterior.coords))


def test_slicer_flip_is_exact(synth):
    V, Fc = synth
    S = M.Slicer(V.copy(), Fc)
    a = S.section(10.0)[0][0]
    S.flip(-1, 1, -1)
    b = S.section(-10.0)[0][0]
    assert abs(a.area - b.area) < 1e-6 and abs(a.length - b.length) < 1e-6


def test_components_and_edges(synth):
    V, Fc = synth
    cube = trimesh.creation.box(extents=(12, 12, 12))
    cube.apply_translation((300, 0, 0))                       # debris far from the hand
    V2 = np.vstack([V, cube.vertices])
    F2 = np.vstack([Fc, cube.faces + len(V)])
    Vk, Fk, info = M.keep_hand_component(V2, F2.astype(np.int32))
    assert info['components'] == 2 and info['kept'] == 1 and len(Fk) == len(Fc)
    b, nonman = M.edge_stats(Fk, len(Vk))
    assert len(b) == 0
    b, _ = M.edge_stats(Fk[:-50], len(Vk))                    # remove triangles -> open edges appear
    assert len(b) > 0


def test_cluster_decimate(synth):
    V, Fc = synth
    V2, F2, inv = M.cluster_decimate(V, Fc, 20000)
    assert len(F2) <= 20000 and len(F2) > 4000
    assert F2.max() < len(V2) and len(inv) == len(V)
    assert np.all(np.abs(V2.max(0) - V.max(0)) < 4) and np.all(np.abs(V2.min(0) - V.min(0)) < 4)
    area = lambda v, f: trimesh.Trimesh(v, f, process=False).area
    assert abs(area(V2, F2) / area(V, Fc) - 1) < 0.1


def test_glb_roundtrip(synth, tmp_path):
    V, Fc = synth
    V2, F2, _ = M.cluster_decimate(V, Fc, 8000)
    col = np.zeros((len(V2), 3), dtype=np.uint8)
    col[:, 0] = 200
    ring = np.c_[np.cos(np.linspace(0, 6.28, 40)) * 30, np.sin(np.linspace(0, 6.28, 40)) * 12, np.zeros(40)]
    n = M.export_glb(tmp_path / 't.glb', [dict(name='hand', kind='mesh', V=V2, F=F2, colors=col),
                                           dict(name='band', kind='lines', rings=[ring, ring + [0, 0, 5]], rgb=(255, 150, 0))])
    assert n == (tmp_path / 't.glb').stat().st_size
    s = trimesh.load(tmp_path / 't.glb')
    assert set(s.geometry) == {'hand', 'band_0', 'band_1'}
    assert np.asarray(s.geometry['hand'].visual.vertex_colors)[0, 0] == 200
