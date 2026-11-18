"""Fast checks on the committed fixtures: API contract keys and the standalone HTML report."""
import json
import re
import xml.dom.minidom as minidom
import report_html

SPEC_PREPARE = {'status', 'scan', 'landmarks', 'preview_glb', 'frame', 'messages'}
SPEC_ANALYZE = {'status', 'sizes', 'recommended_size', 'custom', 'result_glb', 'messages', 'legend'}
SPEC_BUILD = {'status', 'files', 'locks', 'verification', 'result_glb', 'messages'}


def load(fix, name):
    return json.loads((fix / 'artec' / name).read_text(encoding='utf8'))


def test_contract_keys(fix):
    p, a, b = load(fix, 'prepare.json'), load(fix, 'analyze.json'), load(fix, 'build.json')
    assert SPEC_PREPARE <= set(p) and SPEC_ANALYZE <= set(a) and SPEC_BUILD <= set(b)
    assert {'faces', 'vertices', 'extent_mm', 'units_guess', 'mm_per_unit', 'watertight', 'open_edges_near_band', 'components', 'quality'} <= set(p['scan'])
    assert 0 <= p['scan']['quality']['score'] <= 100 and p['scan']['quality']['notes']
    assert {'side', 'side_confidence', 'fingers_end', 'dorsum', 'dorsum_confidence', 'knuckle_z', 'thumb_z', 'band', 'ambiguities'} <= set(p['landmarks'])
    assert len(a['sizes']) == 7 and {'size', 'fits', 'rigid_min', 'dorsal_min', 'lateral_min', 'note'} <= set(a['sizes'][0])
    assert {'W', 'side', 'dorsal_profile_mm_min', 'predicted'} <= set(a['custom'])
    assert {'closest_section_gap_before', 'after', 'share_le_0p5', 'max_overlap'} <= set(a['custom']['predicted'])
    assert -3.0 <= a['custom']['dorsal_profile_mm_min'] <= 0 and 80 <= a['custom']['W'] <= 84
    assert {'3mf', 'stl', 'report_json', 'report_html'} <= set(b['files'])
    assert b['locks']['failures'] == [] and b['verification']['verdict'] == 'approved'
    for d in (p, a, b):
        for m in d['messages']:
            assert m['level'] in ('info', 'warn', 'error') and m['text']
            assert not re.search(r'\b(G0?\d{1,2}|R08A|T[1-7]|faixa)\b', m['text'])
    assert len(p['frame']['scan_to_view']) == 4 and len(a['sections']) == 5


def test_report_html_is_standalone_and_well_formed(fix):
    rep = load(fix, 'report.json')
    for lang in ('en', 'pt'):
        h = report_html.render(rep, lang)
        assert h.startswith('<!doctype html>') and '</html>' in h
        assert not re.search(r'(src|href)\s*=', h) and 'url(' not in h          # no external assets at all
        svgs = re.findall(r'<svg.*?</svg>', h, flags=re.S)
        assert len(svgs) == 6
        for s in svgs:
            minidom.parseString(s)
        assert h.count('<tr') >= 7 + 9 + 9
    assert 'Cuff ready' in report_html.render(rep, 'en')
    stopped = dict(rep, status='stopped', verification=None)
    assert 'Stopped' in report_html.render(stopped, 'en')
