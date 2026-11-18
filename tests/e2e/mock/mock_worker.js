// DEV ONLY: same message protocol as web/worker.js, answering from tests/e2e/mock/ fixtures (tools/make_mock_fixtures.py).
// Loaded by the page only with ?mock=1 (and tools/serve.py --dev). ?mock=std / ?mock=needs simulate other outcomes.
const B = new URL('./', self.location.href).href;
const mode = new URL(self.location.href).searchParams.get('m') || '1';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const post = (type, d, tr) => postMessage(Object.assign({ type }, d || {}), tr || []);
const j = async n => (await fetch(B + n)).json();
const bin = async n => new Uint8Array(await (await fetch(B + n)).arrayBuffer());
onmessage = async ev => {
  const m = ev.data;
  if (m.type === 'init') { for (const p of [10, 40, 80, 100]) { post('init-progress', { pct: p }); await sleep(150); } post('ready', { ms: 600 }); return; }
  if (m.type === 'reset') { post('result', { id: m.id, op: 'reset', result: { status: 'ok' } }); return; }
  try {
    if (m.type === 'prepare' || m.type === 'reprepare') {
      post('progress', { id: m.id, text: 'Reading the scan…' }); await sleep(300);
      const r = await j('prepare.json');
      if (mode === 'needs') { r.status = 'needs_input'; r.landmarks.dorsum_confidence = 0.4; r.landmarks.ambiguities = [{ kind: 'dorsum', message: 'Back/palm unclear' }, { kind: 'knuckles', message: 'Knuckles unclear' }]; }
      if (mode === 'error') throw new Error('Mesh has no faces');
      const g = await bin(r.preview_glb); post('result', { id: m.id, op: m.type, result: r, glb: g, ms: 300 }, [g.buffer]);
    } else if (m.type === 'analyze') {
      post('progress', { id: m.id, text: 'Measuring 5 sections over the band…' }); await sleep(400);
      const r = await j('analyze.json');
      if (mode === 'std') { r.status = 'standard_only'; r.custom = null; r.recommended_size = 3; r.sizes[2].fits = true; }
      if (mode === 'nofit') { r.status = 'no_verified_standard_fit'; r.custom = null; r.recommended_size = null; r.size_by_tape = 2; r.sizes.forEach(z => { z.fits = false; }); }
      const tape = (m.overrides || {}).tape_cm; r.knuckle_circumference_cm = { scan: 18.22, tape: tape ?? null };
      if (r.status === 'custom_ready') {          // real core behaviour: the tape confirms the scale
        r.scale_confirmed = tape != null && Math.abs(tape - 18.22) <= 0.6; r.size_by_tape_source = tape != null ? 'tape' : 'scan';
        if (tape == null) { r.status = 'custom_needs_tape'; r.needs = ['tape_cm']; r.messages = [{ level: 'warn', code: 'custom_needs_tape', text: 'A custom cuff is possible: confirm the scale with a tape measurement around the knuckles (18.2 cm on the scan).' }].concat(r.messages || []); }
      }
      if (tape != null && Math.abs(tape - 18.22) > 0.6) { r.status = 'refused'; r.custom = null; r.sizes = []; r.messages = [{ level: 'error', code: 'tape_mismatch', text: `Around the knuckles: 18.2 cm on the scan but ${tape} cm by tape. The scan scale or the measurement is off.` }]; }
      const g = await bin(r.result_glb); post('result', { id: m.id, op: 'analyze', result: r, glb: g, ms: 400 }, [g.buffer]);
    } else if (m.type === 'build') {
      for (const t of ['Applying the personal back profile…', 'Running the safety checks on the part…', 'Packing the 3MF for Bambu Studio…', 'Checking the cuff against the scan…']) { post('progress', { id: m.id, text: t }); await sleep(500); }
      const r = await j('build.json'); r.files = { '3mf': 'cuff.3mf', stl: 'cuff.stl', report_json: 'report.json' };
      if (mode === 'buildneeds') { r.status = 'needs_input'; r.files = {}; r.locks = null; r.verification = null; r.messages = [{ level: 'warn', code: 'tape_required', text: 'A tape measurement around the knuckles is needed before building a custom cuff.' }]; }
      if (mode === 'buildrefused') { r.status = 'refused'; r.files = {}; r.locks = null; r.verification = null; r.messages = [{ level: 'error', code: 'tape_mismatch', text: 'The tape measurement disagrees with the scan by more than 0.6 cm.' }]; } const files = {}; const tr = [];
      for (const [k, n] of Object.entries(r.files)) { const b = await bin(n); files[k] = { name: k === '3mf' ? 'FreshCuff_Custom_L_W82.0_P1S_PETG.3mf' : k === 'stl' ? 'FreshCuff_Custom_L_W82.0.stl' : 'freshcuff_build.json', bytes: b }; tr.push(b.buffer); }
      const g = await bin(r.result_glb); tr.push(g.buffer);
      post('result', { id: m.id, op: 'build', result: r, glb: g, files, ms: 2000 }, tr);
    }
  } catch (e) { post('error', { id: m.id, op: m.type, code: 'python', message: String(e.message || e), detail: String(e.stack || '') }); }
};
