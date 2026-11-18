"""The fast pose searches must give the same pose and numbers as the validated (slow) ones."""
import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon
import freshcuff_fit as F
import gerador_scan as G
import fc_fastfit as FF


@pytest.fixture(scope='module')
def band(fix, repo):
    d = np.load(fix / 'artec_band_sections.npz')
    n = len(d['z_cuff'])
    est = [dict(poligono=Polygon(d[f'est{i}']), z_cuff=float(d['z_cuff'][i]), dz=float(d['dz'][i]), estado='completo') for i in range(n)]
    _, grade = G.carregar_grade(str(repo / 'web' / 'dados' / 'aberturas_grade_W80_84.json'))
    return est, float(d['angulo']), tuple(d['origem']), grade


def test_signed_distance_is_exact(band):
    _, _, _, grade = band
    rng = np.random.default_rng(3)
    for W in (80.0, 82.0, 84.0):
        for z, P in grade[W]['ab'].items():
            sdf = FF.SignedDistance(np.asarray(P.exterior.coords))
            b = P.bounds
            pts = np.c_[rng.uniform(b[0] - 25, b[2] + 25, 3000), rng.uniform(b[1] - 25, b[3] + 25, 3000)]
            near = np.array([P.exterior.interpolate(u, normalized=True).coords[0] for u in rng.uniform(0, 1, 1500)]) + rng.normal(0, 0.2, (1500, 2))
            pts = np.r_[pts, near, np.asarray(P.exterior.coords)]
            d = shapely.distance(P.exterior, shapely.points(pts))
            ref = np.where(shapely.contains_xy(P, pts[:, 0], pts[:, 1]), d, -d)
            got = sdf.query(pts[:, 0], pts[:, 1])
            assert np.abs(got - ref).max() < 1e-9
            assert np.abs(sdf.brute(pts[:, 0], pts[:, 1]) - ref).max() < 1e-9


KEYS = ('viavel', 'rigido_min_mm', 'dorso_min_mm', 'lateral_min_mm', 'giro_grau', 'dx_mm', 'dy_mm')


@pytest.mark.parametrize('W', [82.0])
def test_fit_band_equals_legacy(band, W):
    est, ang, org, grade = band
    ab = {z: F.Abertura(P, 26) for z, P in grade[W]['ab'].items()}
    a = F.encaixe_faixa(est, ab, ang, org, 0.5, 2.1)
    b = FF.fit_band(est, ab, ang, org, 0.5, 2.1)
    assert [a[k] for k in KEYS + ('margem_mm',)] == [b[k] for k in KEYS + ('margem_mm',)]
    assert a['por_estacao'] == b['por_estacao']
    assert all(np.array_equal(p, q) for p, q in zip(a['_pos'], b['_pos']))


@pytest.mark.parametrize('W', [80.0, 82.0])
def test_fit_lateral_equals_legacy(band, W):
    est, ang, org, grade = band
    ab = {z: F.Abertura(P, 26) for z, P in grade[W]['ab'].items()}
    a = G.encaixe_lateral(est, ab, ang, org, 0.5, 2.1)
    b = FF.fit_lateral(est, ab, ang, org, 0.5, 2.1)
    assert [a.get(k) for k in KEYS] == [b.get(k) for k in KEYS]


@pytest.mark.slow
@pytest.mark.parametrize('W', [80.0, 81.0, 83.0, 84.0])
def test_fit_band_equals_legacy_more_widths(band, W):
    est, ang, org, grade = band
    ab = {z: F.Abertura(P, 26) for z, P in grade[W]['ab'].items()}
    a = F.encaixe_faixa(est, ab, ang, org, 0.5, 2.1)
    b = FF.fit_band(est, ab, ang, org, 0.5, 2.1)
    assert [a[k] for k in KEYS] == [b[k] for k in KEYS]


@pytest.mark.slow
def test_fit_band_equals_legacy_when_nothing_fits(band):
    """Infeasible case (hand scaled up 12 %): the 'least violation' branch must match too."""
    from shapely import affinity
    est, ang, org, grade = band
    big = [dict(e, poligono=affinity.scale(e['poligono'], 1.12, 1.12, origin=org)) for e in est]
    ab = {z: F.Abertura(P, 26) for z, P in grade[80.0]['ab'].items()}
    a = F.encaixe_faixa(big, ab, ang, org, 0.5, 2.1)
    b = FF.fit_band(big, ab, ang, org, 0.5, 2.1)
    assert not a['viavel'] and [a[k] for k in KEYS] == [b[k] for k in KEYS]
