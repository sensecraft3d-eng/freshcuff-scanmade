import fc_api as A
import synth_hand as SH


def test_overrides_persist_between_calls(tmp_path, synth):
    """An override accepted once (e.g. the user picked 'right hand') stays in force for later calls of the session."""
    f = SH.write_mesh(tmp_path / 'h.stl', *synth)
    p = A.prepare(f, tmp_path / 'w', {'side': 'left'})                 # wrong side declared
    assert p['status'] == 'needs_input'
    pick = next(c for c in p['landmarks']['ambiguities'][0]['candidates'] if c['is_guess'])
    a = A.analyze(tmp_path / 'w', dict(pick['overrides'], tape_cm=50))  # (bad tape: stops early, cheap)
    assert a['overrides_applied']['side'] == 'right' and a['status'] == 'refused'
    a2 = A.analyze(tmp_path / 'w', {'tape_cm': 51})
    assert a2['overrides_applied']['side'] == 'right' and a2['overrides_applied']['dorsum'] == pick['overrides']['dorsum']
    A.release(tmp_path / 'w')
