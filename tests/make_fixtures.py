#!/usr/bin/env python3
"""Regenerate tests/fixtures/artec (JSON returned by prepare/analyze/build + the three GLBs + report) from
examples/Artec_Hand.ply.  Usage: python tests/make_fixtures.py"""
import json, shutil, sys, tempfile, time
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'web' / 'py'))
import fc_api as A

def main():
    out = REPO / 'tests' / 'fixtures' / 'artec'
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='fc_fix_'))
    t = time.time()
    p = A.prepare(REPO / 'examples' / 'Artec_Hand.ply', work, {'side': 'left', 'tape_cm': 18.2})
    a = A.analyze(work, {})
    b = A.build(work, REPO / 'web' / 'grade', REPO / 'web' / 'dados')
    print('status', p['status'], a['status'], b['status'], 'seconds', round(time.time() - t, 1))
    for name, d in (('prepare', p), ('analyze', a), ('build', b)):
        (out / (name + '.json')).write_text(json.dumps(d, indent=1), encoding='utf8')
    for g in ('preview.glb', 'analysis.glb', 'result.glb'):
        shutil.copyfile(work / g, out / g)
    for k in ('report_json', 'report_html'):
        if b['files'].get(k):
            shutil.copyfile(work / b['files'][k], out / Path(b['files'][k]).name)
    A.release()
    shutil.rmtree(work, ignore_errors=True)

if __name__ == '__main__':
    main()
