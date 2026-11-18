// Runs the FreshCuff Fit core inside the vendored Pyodide (the browser target) under Node.js.
//   node tests/run_pyodide_node.mjs [scan] [side] [tape_cm]
// Defaults: examples/Artec_Hand.ply left 18.2.  Prints timings and the key results as JSON on the last line.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PYO = resolve(REPO, 'web/pyodide') + '/';
const scan = resolve(process.argv[2] || resolve(REPO, 'examples/Artec_Hand.ply'));
const side = process.argv[3] || 'left';
const tape = process.argv[4] === 'none' ? null : Number(process.argv[4] || 18.2);

const { loadPyodide } = await import(pathToFileURL(PYO + 'pyodide.mjs').href);
let t = Date.now();
const py = await loadPyodide({ indexURL: PYO });
await py.loadPackage(['numpy', 'scipy', 'shapely', 'networkx'], { messageCallback: () => {} });
const dep = JSON.parse(readFileSync(PYO + 'manifesto_dependencias.json', 'utf8'));
py.unpackArchive(new Uint8Array(readFileSync(PYO + dep.trimesh_wheel)), 'wheel', { extractDir: '/lib/python3.12/site-packages' });
for (const d of ['/app', '/scan', '/work']) py.FS.mkdirTree(d);
py.FS.mount(py.FS.filesystems.NODEFS, { root: resolve(REPO, 'web') }, '/app');
py.FS.mount(py.FS.filesystems.NODEFS, { root: dirname(scan) }, '/scan');
const boot = (Date.now() - t) / 1000;
py.globals.set('_scan', '/scan/' + scan.split('/').pop());
py.globals.set('_side', side);
py.globals.set('_tape', tape);
let out;
try {
  out = py.runPython(`
import sys, json, time
sys.path.insert(0, '/app/py')
import compat_wasm
import numpy as np
import fc_api as A
T = {}
t = time.time(); p = A.prepare(_scan, '/work/job', {'side': _side, 'tape_cm': _tape}); T['prepare'] = round(time.time() - t, 1)
t = time.time(); a = A.analyze('/work/job', {}); T['analyze'] = round(time.time() - t, 1)
b = None
if a['status'] == 'custom_ready':
    t = time.time(); b = A.build('/work/job', '/app/grade', '/app/dados'); T['build'] = round(time.time() - t, 1)
import os
res = {'intp_bits': np.dtype(np.intp).itemsize * 8, 'numpy': np.__version__, 'seconds': T,
       'prepare': p['status'], 'side': (p.get('landmarks') or {}).get('side'), 'quality': (p.get('scan') or {}).get('quality', {}).get('score'),
       'analyze': a['status'], 'recommended_size': a['recommended_size'],
       'custom': a['custom'] and {'variant': a['custom']['variant'], 'predicted': {k: v for k, v in a['custom']['predicted'].items() if k != 'raw_after'},
                                  'lateral': a['custom']['lateral_clearance_mm']},
       'build': b and b['status'], 'stl_sha256': b and b['hashes'].get('stl_sha256'), 'locks_failed': b and b['locks']['failures'],
       'verification': b and b['verification'] and b['verification']['verdict'], 'files': b and b['files'],
       'glb_bytes': {g: os.path.getsize('/work/job/' + g) for g in ('preview.glb', 'analysis.glb', 'result.glb') if os.path.exists('/work/job/' + g)},
       'errors': [m['text'] for d in (p, a, b or {}) for m in d.get('messages', []) if m['level'] == 'error']}
json.dumps(res)
`);
} catch (e) {
  console.error(String(e && e.message || e).slice(-3000));
  process.exit(1);
}
const res = JSON.parse(out);
res.seconds.boot = boot;
console.log(JSON.stringify(res, null, 1));
