// FreshCuff ScanMade · Python worker (Pyodide 0.27.7, vendored in pyodide/). Everything runs on this computer:
// the tools come from this site only (no CDN, no PyPI), every file is checked against manifesto.json (sha256)
// before use, and the scan is never sent anywhere. Calls the public core API web/py/fc_api.py:
//   prepare(scan_path, work_dir, opts) -> analyze(work_dir, overrides) -> build(work_dir, grid_dir, data_dir)
// Messages in:  {type:'init'} | {type:'prepare', id, scan:ArrayBuffer, ext, opts} | {type:'reprepare', id, opts}
//               {type:'analyze', id, overrides}
//               {type:'build', id} | {type:'reset'}
// Messages out: {type:'init-progress', pct, key} | {type:'ready', ms} | {type:'progress', id, text}
//               {type:'result', id, op, result, glb, files, ms} | {type:'error', id, op, code, message, detail}
// Integrity chain (does not depend on any HTTP header, so it holds on GitHub Pages too):
//   1. manifesto.json is fetched from this site (same origin as this worker: it is the root of trust).
//   2. pyodide.js and pyodide.asm.js are fetched, their sha256 compared with manifesto.json["pyodide"], and only
//      the verified bytes are executed (importScripts of a blob: URL made from those bytes).
//   3. Every other runtime file Pyodide asks for (pyodide.asm.wasm, python_stdlib.zip, pyodide-lock.json, each
//      wheel/zip) goes through verifiedFetch(): same check before Pyodide sees the bytes; a file under pyodide/
//      that is not listed in the manifest is refused.
//   4. App files (py/, dados/, grade/) are checked against manifesto.json["arquivos"] before being written to the
//      Python file system. A mismatch stops the run with a clear message.
const BASE = new URL('./', self.location.href).href;
const PYO = BASE + 'pyodide/';
const LIMIT_MB = 150;
const WORK = '/work/run';
let py = null, manifest = null, ready = null;
let lastAnalyze = null, lastScan = null;

const post = (type, data, transfer) => postMessage(Object.assign({ type }, data || {}), transfer || []);
const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');

class FcError extends Error { constructor(code, message, detail) { super(message); this.code = code; this.detail = detail; } }

async function fetchChecked(rel, expected) {
  const r = await nativeFetch(BASE + rel, { cache: 'no-cache' });
  if (!r.ok) throw new FcError('fetch', `Could not download ${rel} (HTTP ${r.status}).`);
  const b = new Uint8Array(await r.arrayBuffer());
  const h = hex(await crypto.subtle.digest('SHA-256', b));
  if (h !== expected) throw new FcError('integrity', `${rel} does not match manifesto.json (sha256).`, `expected ${expected}\ngot      ${h}`);
  return b;
}

const GLUE = String.raw`
import json, math, inspect, os, shutil, gc, traceback, sys
_cb = None
_lang = None
def _progress(*a, **k):
    try:
        if _cb is not None: _cb(' '.join(str(x) for x in a))
    except Exception:
        pass
def _clean(o):
    if isinstance(o, float): return o if math.isfinite(o) else None
    if isinstance(o, dict): return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(v) for v in o]
    if hasattr(o, 'tolist'): return _clean(o.tolist())
    if hasattr(o, 'item'):
        try: return _clean(o.item())
        except Exception: pass
    if isinstance(o, (str, int, bool)) or o is None: return o
    if hasattr(o, '__fspath__'): return os.fspath(o)
    return str(o)
def call(name, args_json):
    import fc_api
    if hasattr(fc_api, 'set_progress'):
        try: fc_api.set_progress(_progress)
        except Exception: pass
    f = getattr(fc_api, name)
    args = json.loads(args_json)
    kw = {}
    try:
        params = inspect.signature(f).parameters
        for nm in ('progress', 'progress_cb', 'on_progress'):
            if nm in params: kw[nm] = _progress; break
        if 'lang' in params and _lang: kw['lang'] = _lang
    except (TypeError, ValueError):
        pass
    try:
        r = f(*args, **kw)
    except BaseException as e:
        msg = str(e) if str(e) else e.__class__.__name__
        return json.dumps({'status': 'error', 'error': {'type': e.__class__.__name__, 'message': msg, 'trace': traceback.format_exc()[-4000:]}})
    return json.dumps(_clean(r))
def release():
    try:
        import fc_api
        for nm in ('release', 'liberar', 'cleanup'):
            if hasattr(fc_api, nm): getattr(fc_api, nm)(); break
    except Exception:
        pass
    try:
        import freshcuff_fit as F; F._INTERNO = None
    except Exception:
        pass
    shutil.rmtree('${WORK}', ignore_errors=True)
    for f in os.listdir('/work'):
        p = os.path.join('/work', f)
        if os.path.isfile(p): os.remove(p)
    gc.collect()
`;

const nativeFetch = self.fetch.bind(self);
const MIME = { wasm: 'application/wasm', js: 'text/javascript', json: 'application/json', zip: 'application/zip', whl: 'application/zip' };
function runtimeHash(rel) {
  const h = manifest && manifest.pyodide && manifest.pyodide[rel];
  if (!h) throw new FcError('integrity', `${rel} is not listed in manifesto.json, so it was not used.`);
  return h;
}
// Pyodide's own downloads go through here: verified bytes only.
async function verifiedFetch(input, init) {
  const url = new URL(typeof input === 'string' ? input : input.url, BASE).href;
  if (!url.startsWith(PYO)) return nativeFetch(input, init);
  const rel = 'pyodide/' + decodeURIComponent(url.slice(PYO.length).split(/[?#]/)[0]);
  const bytes = await fetchChecked(rel, runtimeHash(rel));
  const ext = rel.split('.').pop();
  return new Response(bytes, { status: 200, headers: { 'Content-Type': MIME[ext] || 'application/octet-stream' } });
}
// Execute a script only after its bytes match the manifest.
async function importVerified(rel) {
  const bytes = await fetchChecked(rel, runtimeHash(rel));
  const url = URL.createObjectURL(new Blob([bytes], { type: 'text/javascript' }));
  try { importScripts(url); }
  catch (e) { throw new FcError('integrity', `Could not run the verified ${rel} (${e.message}). If this site sends a CSP header, it must allow blob: in script-src.`); }
  finally { URL.revokeObjectURL(url); }
}

async function init() {
  const t0 = performance.now();
  post('init-progress', { pct: 3, key: 'manifest' });
  manifest = await (await nativeFetch(BASE + 'manifesto.json', { cache: 'no-cache' })).json();
  if (!manifest.pyodide) throw new FcError('integrity', 'manifesto.json does not list the Python runtime files.');
  const dep = JSON.parse(new TextDecoder().decode(await fetchChecked('pyodide/manifesto_dependencias.json', runtimeHash('pyodide/manifesto_dependencias.json'))));
  post('init-progress', { pct: 6, key: 'python' });
  await importVerified('pyodide/pyodide.js');
  await importVerified('pyodide/pyodide.asm.js');          // defines _createPyodideModule: Pyodide will not load it again
  self.fetch = verifiedFetch;                               // wasm, stdlib, lock file and wheels: verified before use
  post('init-progress', { pct: 12, key: 'python' });
  py = await loadPyodide({ indexURL: PYO });
  post('init-progress', { pct: 35, key: 'packages' });
  await py.loadPackage(['numpy', 'scipy', 'shapely', 'networkx'], { messageCallback: () => {}, errorCallback: () => {} });
  post('init-progress', { pct: 75, key: 'trimesh' });
  const wheel = await fetchChecked('pyodide/' + dep.trimesh_wheel, runtimeHash('pyodide/' + dep.trimesh_wheel));
  py.unpackArchive(wheel.buffer, 'wheel', { extractDir: '/lib/python3.12/site-packages' });
  for (const d of ['/app/py', '/app/dados', '/app/grade', '/work']) py.FS.mkdirTree(d);
  const files = Object.entries(manifest.arquivos).filter(([rel]) => !(rel.startsWith('grade/') && rel.endsWith('.stl')));  // grid variants: only the chosen one, later
  let i = 0;
  for (const [rel, h] of files) {
    const dir = '/app/' + rel.split('/').slice(0, -1).join('/'); py.FS.mkdirTree(dir);
    py.FS.writeFile('/app/' + rel, await fetchChecked(rel, h));
    if (++i % 4 === 0) post('init-progress', { pct: 78 + Math.round(18 * i / files.length), key: 'files' });
  }
  py.runPython("import sys; sys.path.insert(0, '/app/py')\nimport compat_wasm");
  py.FS.writeFile('/app/fc_glue.py', GLUE);
  py.runPython("import sys; sys.path.insert(0, '/app')\nimport fc_glue");
  const hasApi = py.runPython("import importlib.util; importlib.util.find_spec('fc_api') is not None");
  if (!hasApi) throw new FcError('no_api', 'The analysis module (fc_api) is not available in this build.');
  // warm import (so the first click does not pay for it)
  py.runPython('import fc_api');
  post('init-progress', { pct: 100, key: 'ready' });
  post('ready', { ms: Math.round(performance.now() - t0) });
}

let lang = 'en';
function callApi(name, args, id) {
  const glue = py.pyimport('fc_glue');
  glue._cb = (t) => post('progress', { id, text: String(t) });
  glue._lang = lang;
  try {
    const out = JSON.parse(glue.call(name, JSON.stringify(args)));
    if (out && out.status === 'error' && out.error) throw new FcError('python', out.error.message, out.error.trace);
    return out;
  } finally { glue._cb = null; glue.destroy(); }
}

const abs = (p) => !p ? null : (String(p).startsWith('/') ? String(p) : WORK + '/' + p);
function readFile(p) { try { return py.FS.readFile(abs(p)); } catch (e) { return null; } }

function release() { try { py && py.pyimport('fc_glue').release(); } catch (e) { /* nothing to free */ } lastAnalyze = null; lastScan = null; }

async function prepare(m) {
  if (!m.scan || m.scan.byteLength > LIMIT_MB * 1e6) throw new FcError('too_big', `Scan too large (${(m.scan.byteLength / 1e6).toFixed(0)} MB; limit ${LIMIT_MB} MB).`);
  release();
  const ext = /^(stl|obj|ply)$/.test(m.ext) ? m.ext : 'stl';
  const base = String(m.name || 'scan').replace(/\.[^.]*$/, '').replace(/[^A-Za-z0-9_-]+/g, '_').slice(0, 60) || 'scan';
  const scanPath = `/work/${base}.${ext}`;   // the file name shows in the report
  py.FS.writeFile(scanPath, new Uint8Array(m.scan)); m.scan = null;
  py.FS.mkdirTree(WORK);
  const opts = Object.assign({ mm_per_unit: null, side: 'auto', tape_cm: null }, m.opts || {});
  lastScan = scanPath;
  const r = callApi('prepare', [scanPath, WORK, opts], m.id);
  const glb = readFile(r.preview_glb);
  return { result: r, glb };
}

// Same scan, new choices (back/palm, finger end, side, knuckle line): the API re-reads the cached scan only.
async function reprepare(m) {
  if (!lastScan) throw new FcError('internal', 'No scan loaded.');
  const opts = Object.assign({ mm_per_unit: null, side: 'auto', tape_cm: null }, m.opts || {});
  const r = callApi('prepare', [lastScan, WORK, opts], m.id);
  return { result: r, glb: readFile(r.preview_glb) };
}

async function analyze(m) {
  const r = callApi('analyze', [WORK, m.overrides || {}], m.id);
  lastAnalyze = r;
  return { result: r, glb: readFile(r.result_glb) };
}

function variantId(r) {
  const c = r && r.custom; if (!c) return null;
  if (c.variant || c.grid_variant || c.grid_id) return c.variant || c.grid_variant || c.grid_id;
  if (!Number.isFinite(c.W)) return null;
  return `W${c.W.toFixed(1)}_${String(c.side || '').toLowerCase().startsWith('l') ? 'L' : 'R'}`;
}

async function build(m) {
  const vid = variantId(lastAnalyze);
  if (vid) {
    const idx = JSON.parse(py.FS.readFile('/app/grade/indice_grade_web.json', { encoding: 'utf8' }));
    const v = idx.find(x => x.id === vid);
    if (!v) throw new FcError('variant', `Base part ${vid} is not in the published grid.`);
    const rel = 'grade/' + v.arquivo;
    let have = false; try { py.FS.stat('/app/' + rel); have = true; } catch (e) { /* not yet */ }
    if (!have) {
      post('progress', { id: m.id, text: `Downloading the base part (${(v.bytes / 1e6).toFixed(1)} MB)…`, key: 'download_base' });
      py.FS.writeFile('/app/' + rel, await fetchChecked(rel, manifest.arquivos[rel]));
    }
  }
  const r = callApi('build', [WORK, '/app/grade', '/app/dados'], m.id);
  const files = {}; const transfer = [];
  for (const [k, p] of Object.entries(r.files || {})) {
    const b = readFile(p); if (!b) continue;
    files[k] = { name: String(p).split('/').pop(), bytes: b }; transfer.push(b.buffer);
  }
  return { result: r, glb: readFile(r.result_glb), files, transfer };
}

onmessage = async (ev) => {
  const m = ev.data; const t0 = performance.now();
  if (m.lang) lang = m.lang === 'pt' ? 'pt' : 'en';
  try {
    if (m.type === 'init') { ready = ready || init(); await ready; return; }
    if (m.type === 'reset') { release(); post('result', { id: m.id, op: 'reset', result: { status: 'ok' } }); return; }
    if (!ready) ready = init();
    await ready;
    let out;
    if (m.type === 'prepare') out = await prepare(m);
    else if (m.type === 'reprepare') out = await reprepare(m);
    else if (m.type === 'analyze') out = await analyze(m);
    else if (m.type === 'build') out = await build(m);
    else return;
    const transfer = (out.transfer || []).slice(); if (out.glb) transfer.push(out.glb.buffer);
    post('result', { id: m.id, op: m.type, result: out.result, glb: out.glb, files: out.files || null, ms: Math.round(performance.now() - t0) }, transfer);
  } catch (err) {
    const code = err.code || (m.type === 'init' ? 'init' : 'internal');
    post('error', { id: m.id, op: m.type, code, message: String((err && err.message) || err).slice(-2000), detail: err.detail ? String(err.detail).slice(-4000) : null });
    if (m.type === 'init') ready = null;
  }
};
