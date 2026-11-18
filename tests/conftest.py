import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (REPO / 'web' / 'py', REPO / 'tests', REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
FIX = REPO / 'tests' / 'fixtures'
ARTEC = REPO / 'examples' / 'Artec_Hand.ply'


def pytest_configure(config):
    config.addinivalue_line('markers', 'slow: full pipeline runs (tens of seconds each); deselect with -m "not slow"')
    config.addinivalue_line('markers', 'legacy: runs the original R07 code for comparison (about 2 minutes); needs FC_RUN_LEGACY=1')


@pytest.fixture(scope='session')
def repo():
    return REPO


@pytest.fixture(scope='session')
def fix():
    return FIX


@pytest.fixture(scope='session')
def synth():
    """(V, F) of the synthetic right hand (fit frame, mm)."""
    import synth_hand
    return synth_hand.make_hand()


@pytest.fixture(scope='session')
def synth_file(synth, tmp_path_factory):
    import synth_hand
    return synth_hand.write_mesh(tmp_path_factory.mktemp('synth') / 'hand.stl', *synth)


@pytest.fixture(scope='session')
def artec_run(tmp_path_factory):
    """One full run on the Artec sample (prepare, analyze, build), shared by the slow tests."""
    import fc_api as A
    work = tmp_path_factory.mktemp('artec')
    p = A.prepare(ARTEC, work, {'side': 'left', 'tape_cm': 18.2})
    a = A.analyze(work, {})
    b = A.build(work, REPO / 'web' / 'grade', REPO / 'web' / 'dados')
    return work, p, a, b
