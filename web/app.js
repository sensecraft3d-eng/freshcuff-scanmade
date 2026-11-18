// FreshCuff Fit · page controller (ES module; no inline script because of the CSP).
// Flow: 1 Scan → 2 Check (landmarks, fixes) → 3 Fit (7 sizes + custom) → 4 Build (3MF/STL/report/JSON).
import { t, setLang, getLang, onLang, initialLang, fmtNum, applyI18n } from './ui/i18n.js';
import { Viewer } from './ui/viewer.js';
import { readScan, supported, extOf, LIMIT_MB } from './ui/convert.js';
import { buildReport, fitWord } from './ui/report.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const MAKERWORLD = 'https://makerworld.com/en/models/3595433';
const params = new URLSearchParams(location.search);
const MOCK = params.get('mock');

// ---------------------------------------------------------------- state
const S = {
  step: 1, scanName: '', prep: null, prepGlb: null, ana: null, anaGlb: null, build: null, buildGlb: null, files: null,
  fixes: { ch: {}, dz: 0, knuckle_s: null }, overrides: null, snaps: {},
  timings: {}, lastOp: null, toolsReady: false, toolsError: null, urls: [],
};
window.__fc = { S, events: [] };            // read by the e2e test (timings); no user data leaves the page
const mark = (name, extra) => window.__fc.events.push(Object.assign({ name, t: Math.round(performance.now()) }, extra || {}));

// ---------------------------------------------------------------- worker client
const worker = MOCK ? new Worker('/__mock/mock_worker.js?m=' + encodeURIComponent(MOCK)) : new Worker('worker.js');
let seq = 0; const pending = new Map(); let progressSink = null;
worker.onmessage = (ev) => {
  const m = ev.data;
  if (m.type === 'init-progress') return toolsProgress(m.pct);
  if (m.type === 'ready') { S.toolsReady = true; S.timings.tools = m.ms; mark('tools-ready', { ms: m.ms }); return toolsProgress(100); }
  if (m.type === 'progress') { progressSink && progressSink(friendly(m.text), m.key); return; }
  if (m.type === 'result' || m.type === 'error') {
    const p = pending.get(m.id);
    if (m.type === 'error' && (m.op === 'init' || !p)) { S.toolsError = m; toolsFailed(); if (!p) return; }
    if (!p) return; pending.delete(m.id);
    if (m.type === 'result') p.resolve(m); else p.reject(Object.assign(new Error(m.message), { code: m.code, detail: m.detail, op: m.op }));
  }
};
worker.onerror = (e) => { S.toolsError = { message: e.message || 'worker error' }; toolsFailed(); for (const [, p] of pending) p.reject(Object.assign(new Error(e.message || 'worker'), { code: 'worker' })); pending.clear(); };
// Short technical progress notes from Python ("size 3", "W 82.0") become plain words.
function friendly(txt) {
  const s = String(txt || '').trim(); let m;
  if ((m = s.match(/^size\s+(\d+)$/i))) return t('prog_size', { n: m[1] });
  if ((m = s.match(/^W\s*([\d.]+)$/))) return t('prog_width', { w: fmtNum(+m[1], 1) });
  return s;
}
function call(type, data, transfer) {
  const id = ++seq;
  return new Promise((resolve, reject) => { pending.set(id, { resolve, reject }); worker.postMessage(Object.assign({ type, id, lang: getLang() }, data || {}), transfer || []); });
}
worker.postMessage({ type: 'init' });       // start loading Python while the person reads step 1
mark('init-sent');

// ---------------------------------------------------------------- tools status (step 1)
let toolsPct = 0;
function toolsProgress(p) {
  toolsPct = Math.max(toolsPct, p);
  $('#tools-fill').style.width = Math.max(3, toolsPct) + '%';
  if (toolsPct >= 100) { $('#tools').classList.add('ready'); $('#tools-text').textContent = t('tools_ready'); $('#tools-sub').textContent = ''; }
}
function toolsFailed() { $('#tools').classList.add('failed'); $('#tools-text').textContent = t('tools_failed'); $('#tools-sub').textContent = ''; }
onLang(() => { if (S.toolsReady) toolsProgress(100); else if (S.toolsError) toolsFailed(); });

// ---------------------------------------------------------------- viewer
const viewer = new Viewer($('#viewer'), $('#canvas'), $('#labels'));
function labelTexts() { viewer.labelText = { dorsum: t('label_dorsum'), fingers: t('label_fingers'), wrist: t('label_wrist'), knuckles: t('label_knuckles'), band: t('label_band'), cuff: t('label_cuff') }; }
labelTexts(); window.__fc.viewer = viewer;   // test hook (coverage of the 3D view)
onLang(() => { labelTexts(); viewer.refreshLabels(); renderLegend(); });
$$('[data-view]').forEach(b => b.addEventListener('click', () => viewer.frame(b.dataset.view)));
$$('[data-show]').forEach(b => b.addEventListener('click', () => {
  const both = b.dataset.show === 'both'; viewer.setCuffVisible(both);
  $$('[data-show]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
}));
function viewerBusy(text) { const el = $('#v-loading'); if (text) { $('#v-loading-text').textContent = text; el.hidden = false; } else el.hidden = true; }
let legendData = null;
function renderLegend(leg) {
  if (leg !== undefined) legendData = leg;
  const el = $('#legend');
  if (!legendData || !legendData.length) { el.hidden = true; return; }
  const L = [...legendData].sort((a, b) => a.mm - b.mm); const lo = L[0].mm, hi = L[L.length - 1].mm;
  const stops = L.map(s => `rgb(${s.rgb.slice(0, 3).join(',')}) ${((s.mm - lo) / (hi - lo || 1) * 100).toFixed(1)}%`).join(',');
  el.innerHTML = `<h3>${esc(t('legend_title'))}</h3><div class="ramp" style="background:linear-gradient(90deg,${stops})"></div>
    <div class="ticks">${L.map(s => `<span>${s.mm < 0 ? '\u2212' : ''}${fmtNum(Math.abs(s.mm), s.mm % 1 ? 1 : 0)}</span>`).join('')}</div>
    <div class="words"><span>${esc(t('legend_press'))}</span><span>${esc(t('legend_touch'))}</span><span>${esc(t('legend_gap'))} (mm)</span></div>`;
  el.hidden = false;
}

// ---------------------------------------------------------------- navigation
function goStep(n, { focus = true } = {}) {
  S.step = n;
  $('#step-1').hidden = n !== 1; $('#work').hidden = !(n >= 2 && n <= 4); $('#error').hidden = true;
  for (const k of [2, 3, 4]) $('#step-' + k).hidden = k !== n;
  $$('.stepper li').forEach(li => {
    const k = +li.dataset.step; li.classList.toggle('done', k < n);
    if (k === n) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
  });
  $('#legend').hidden = n === 2 || !legendData; $('#v-toggle').hidden = n !== 4 || !S.buildGlb;
  if (n >= 2) viewer.resize();
  if (focus) {
    const h = n === 1 ? $('#s1-title') : $(`#step-${n} h1`);
    if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
    window.scrollTo({ top: 0 });
  }
}
function stepOfLabels() { $$('[data-step-of]').forEach(el => { el.textContent = t('step_of', { n: el.dataset.stepOf }); }); }
onLang(stepOfLabels);

// ---------------------------------------------------------------- errors (never a dead end)
function showError(err, { tips, retry } = {}) {
  mark('error', { code: err.code, message: err.message });
  viewerBusy(null); progressSink = null; stopTimer();
  $('#step-1').hidden = true; $('#work').hidden = true; $('#error').hidden = false;
  const codeMsg = { too_big: t('file_too_big', { mb: fmtNum(err.mb || 0, 0) }), bad_type: t('file_bad_type'), empty: t('file_empty'), usdz: t('file_usdz'),
    integrity: t('err_integrity'), init: t('err_tools'), no_api: t('err_tools'), worker: t('err_tools'), fetch: t('err_tools') };
  $('#err-msg').textContent = codeMsg[err.code] || err.message || String(err);
  const T = tips || (['init', 'no_api', 'worker', 'fetch', 'integrity'].includes(err.code) ? ['err_tip_reload', 'err_tip_browser'] :
    err.code === 'too_big' ? ['err_tip_smaller', 'err_tip_sample'] : err.code === 'usdz' ? ['err_tip_export', 'err_tip_sample'] : ['err_tip_scan', 'err_tip_smaller', 'err_tip_sample']);
  $('#err-tips').innerHTML = T.map(k => `<li>${esc(t(k))}</li>`).join('');
  $('#err-tech').textContent = [err.code && `code: ${err.code}`, err.op && `step: ${err.op}`, err.message, err.detail].filter(Boolean).join('\n');
  S.lastOp = retry || null; $('#err-retry').hidden = !retry;
  $('#err-title').focus(); window.scrollTo({ top: 0 });
}
$('#err-retry').addEventListener('click', () => { const f = S.lastOp; if (f) f(); });
$('#err-file').addEventListener('click', () => { goStep(1); $('#file').click(); });
$('#err-sample').addEventListener('click', () => { goStep(1); loadSample(); });

// ---------------------------------------------------------------- step 1: input
const status1 = (txt, busy) => { const el = $('#start-status'); el.textContent = txt || ''; el.classList.toggle('busy', !!busy); };
function readOpts() {
  const side = ($('input[name=hand]:checked') || {}).value || 'auto';
  const tape = parseFloat(String($('#tape').value).replace(',', '.'));
  const u = $('#units').value;
  return { side, tape_cm: Number.isFinite(tape) && tape > 5 ? tape : null, mm_per_unit: u === 'auto' ? null : parseFloat(u) };
}
async function sha256hex(buf) { return [...new Uint8Array(await crypto.subtle.digest('SHA-256', buf))].map(b => b.toString(16).padStart(2, '0')).join(''); }
let manifestPage = null;
async function loadSample() {
  status1(t('reading'), true); mark('sample-click');
  try {
    const r = await fetch('examples/Artec_Hand.ply'); if (!r.ok) throw Object.assign(new Error('Sample not found (HTTP ' + r.status + ')'), { code: 'fetch' });
    const buf = await r.arrayBuffer();
    try {
      manifestPage = manifestPage || (await (await fetch('manifesto.json', { cache: 'no-cache' })).json()).pagina || {};
      const want = manifestPage['examples/Artec_Hand.ply'];
      if (want && want !== await sha256hex(buf)) throw Object.assign(new Error('sample checksum'), { code: 'integrity' });
    } catch (e) { if (e.code === 'integrity') throw e; }
    await handleScan('Artec_Hand.ply', buf);
  } catch (e) { status1(''); showError(e, { retry: loadSample }); }
}
$('#sample').addEventListener('click', loadSample);
$('#file').addEventListener('change', async (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) await handleFile(f); });
const drop = $('#drop');
['dragenter', 'dragover'].forEach(n => drop.addEventListener(n, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(n => drop.addEventListener(n, e => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', e => { const f = e.dataTransfer?.files?.[0]; if (f) handleFile(f); });
window.addEventListener('dragover', e => e.preventDefault()); window.addEventListener('drop', e => e.preventDefault());

async function handleFile(f) {
  if (!supported(f.name)) return showError(Object.assign(new Error('bad type'), { code: 'bad_type' }), { tips: ['err_tip_scan', 'err_tip_sample'] });
  if (f.size > LIMIT_MB * 1e6) return showError(Object.assign(new Error('too big'), { code: 'too_big', mb: f.size / 1e6 }));
  status1(t('reading'), true);
  try { await handleScan(f.name, await f.arrayBuffer()); } catch (e) { status1(''); showError(e, { retry: () => handleFile(f) }); }
}

async function handleScan(name, buf) {
  S.scanName = name; S.prep = S.ana = S.build = null; S.prepGlb = S.anaGlb = S.buildGlb = null; S.files = null; S.snaps = {};
  S.fixes = { ch: {}, dz: 0, knuckle_s: null }; legendData = null;
  const ext = extOf(name);
  if (!['stl', 'obj', 'ply'].includes(ext)) status1(t('converting', { name }), true);
  const t0 = performance.now();
  const scan = await readScan(name, buf);
  S.timings.read = Math.round(performance.now() - t0); mark('scan-read', { ms: S.timings.read, converted: scan.converted });
  status1('');
  // go to Check immediately: show the raw scan while Python reads it
  $('#s2-wait').hidden = false; $('#s2-body').hidden = true; $('#s2-go').disabled = true;
  $('#s2-wait-t').textContent = t('reading'); $('#s2-wait-sub').textContent = S.toolsReady ? '' : t('tools_loading');
  goStep(2);
  if (scan.preview) { viewer.showRaw(scan.preview); scan.preview.dispose?.(); }
  viewerBusy(t('reading'));
  await runPrepare(scan);
}

async function runPrepare(scan) {
  const t0 = performance.now(); startTimer($('#s2-wait-sub'), 'reading');
  progressSink = (txt) => { $('#s2-wait-t').textContent = txt; $('#v-loading-text').textContent = txt; };
  const bytes = scan.bytes; const keep = bytes.slice(0);   // keep a copy only for "Try again"
  let res;
  try { res = await call('prepare', { scan: bytes, ext: scan.ext, name: S.scanName, opts: Object.assign(readOpts(), { lang: getLang() }) }, [bytes]); }
  catch (e) { stopTimer(); return showError(e, { retry: () => runPrepare({ bytes: keep.slice(0), ext: scan.ext }) }); }
  finally { progressSink = null; }
  stopTimer();
  S.timings.prepare = Math.round(performance.now() - t0); mark('prepared', { ms: S.timings.prepare, status: res.result.status });
  const r = res.result;
  if (r.status === 'refused') {
    viewerBusy(null);
    const msgs = (r.messages || []).filter(m => m.level !== 'info').map(m => m.text).join(' ');
    return showError(Object.assign(new Error(msgs || t('err_tip_scan')), { code: 'refused', op: 'prepare' }), { tips: ['err_tip_scan', 'err_tip_smaller', 'err_tip_sample'] });
  }
  S.prep = r; S.prepGlb = res.glb;
  await showCheck();
}

// ---------------------------------------------------------------- step 2: check
// Choices are ABSOLUTE values for the API (dorsum keep/flip refers to the scan axis frame, fingers high/low, side).
// "Flip", "Swap" and "Left/Right" re-read the cached scan with the new choice (prepare again), so the preview,
// the knuckle line and the band are always the ones Python will use. The knuckle line moves locally (instant) and
// is sent as knuckle_z (view frame of the latest preview).
const conf = c => !Number.isFinite(c) ? '' : c >= 0.85 ? t('sure') : c >= 0.6 ? t('fairly_sure') : t('unsure');
const OPP = { left: 'right', right: 'left', high: 'low', low: 'high', keep: 'flip', flip: 'keep' };
const curDorsum = lm => (lm.dorsum === 'flipped' ? 'flip' : 'keep');
function choiceOpts(extra) {
  const o = readOpts(); const ch = S.fixes.ch;
  const opts = Object.assign({}, o, { lang: getLang(), side: ch.side || o.side || 'auto', dorsum: ch.dorsum || 'auto', fingers: ch.fingers || 'auto' }, extra || {});
  if (S.fixes.dz !== 0) opts.knuckle_z = Math.round(viewer.knuckleZ * 100) / 100;
  else if (S.fixes.knuckle_s != null) opts.knuckle_s = S.fixes.knuckle_s;
  return opts;
}
async function showCheck() {
  const r = S.prep, lm = r.landmarks || {};
  $('#s2-wait').hidden = true; $('#s2-body').hidden = false; $('#s2-go').disabled = false;
  if (S.prepGlb) { viewerBusy(t('view_loading')); try { await viewer.show(S.prepGlb, 'check', lm, r.overlays); } catch (e) { console.warn(e); } }
  viewerBusy(null);
  viewer.setKnuckleShift(S.fixes.dz); viewer.refreshLabels();
  renderCheck();
  viewer.setPicking(true, z => {
    S.fixes.dz = Math.round((z - lm.knuckle_z) * 10) / 10; viewer.setKnuckleShift(S.fixes.dz); fixChanged();
  });
  try { S.snaps.check = viewer.snapshot('reset', 900, 640); } catch (e) { /* optional */ }
}
function renderCheck() {
  const r = S.prep; if (!r) return; const lm = r.landmarks || {}; const q = (r.scan && r.scan.quality) || {}; const ch = S.fixes.ch;
  const sc = Number.isFinite(q.score) ? Math.round(q.score) : null;
  const cls = sc == null ? '' : sc >= 75 ? 'good' : sc >= 50 ? 'ok' : 'poor';
  $('#q-meter').className = 'meter ' + cls; $('#q-fill').style.width = (sc ?? 0) + '%'; $('#q-num').textContent = sc == null ? '–' : sc + '/100';
  $('#q-meter').setAttribute('aria-valuenow', String(sc ?? 0));
  $('#q-word').textContent = cls ? t('quality_' + cls) : '—';
  $('#q-notes').innerHTML = (q.notes || []).map(n => `<li>${esc(n)}</li>`).join('');
  const fact = (k, v, c, changed) => `<dt>${esc(t(k))}</dt><dd>${esc(v)}${changed ? ` <span class="conf">· ${esc(t('changed_by_you'))}</span>` : c ? ` <span class="conf${c === t('unsure') ? ' low' : ''}">· ${esc(c)}</span>` : ''}</dd>`;
  const units = r.scan?.units_guess ? `${r.scan.units_guess}${Number.isFinite(r.scan.mm_per_unit) && r.scan.mm_per_unit !== 1 ? ` (×${fmtNum(r.scan.mm_per_unit, r.scan.mm_per_unit < 10 ? 2 : 0)})` : ''}` : '—';
  const loc = getLang() === 'pt' ? 'pt-BR' : 'en-GB';
  $('#facts').innerHTML = fact('det_side', lm.side === 'left' ? t('side_left') : lm.side === 'right' ? t('side_right') : '—', conf(lm.side_confidence), !!ch.side)
    + fact('det_dorsum', ch.dorsum ? t('turned_over') : t('detected'), conf(lm.dorsum_confidence), !!ch.dorsum)
    + fact('det_fingers', ch.fingers ? t('swapped') : t('detected'), conf(lm.fingers_confidence), !!ch.fingers)
    + (Number.isFinite(lm.knuckle_circumference_cm) ? `<dt>${esc(t('det_circ'))}</dt><dd>${fmtNum(lm.knuckle_circumference_cm, 1)} cm</dd>` : '')
    + fact('det_units', units, '', false)
    + (r.scan?.faces ? `<dt>${esc(t('rep_scan'))}</dt><dd>${esc(t('faces', { n: Number(r.scan.faces).toLocaleString(loc) }))}</dd>` : '');
  const amb = (lm.ambiguities || []);
  const needs = r.status === 'needs_input' || amb.length > 0;
  $('#needs').hidden = !needs;
  const plain = k => (t('amb_' + k) !== 'amb_' + k ? t('amb_' + k) : '');
  $('#needs-list').innerHTML = (amb.length ? amb : [{ kind: 'dorsum' }]).map((a, i) => {
    const c = (a.candidates || []).map((cd, j) => `<button type="button" class="btn btn-secondary btn-sm cand" data-amb="${i}" data-cand="${j}">${esc(cd.label)}</button>`).join('');
    return `<li><span>${esc(a.message || plain(a.kind))}</span>${a.message && plain(a.kind) ? `<span class="help">${esc(plain(a.kind))}</span>` : ''}${c ? `<span class="cands">${c}</span>` : ''}</li>`;
  }).join('');
  $$('#needs-list .cand').forEach(b => b.addEventListener('click', () => {
    const cd = amb[+b.dataset.amb].candidates[+b.dataset.cand]; Object.assign(S.fixes.ch, cd.overrides || {}); reread();
  }));
  $('#fx-flip').setAttribute('aria-pressed', String(!!ch.dorsum));
  $('#fx-fingers').setAttribute('aria-pressed', String(!!ch.fingers));
  $('#fx-side').setAttribute('aria-pressed', String(!!ch.side));
  const any = !!(ch.side || ch.dorsum || ch.fingers) || S.fixes.dz !== 0 || S.fixes.knuckle_s != null;
  $('#fx-reset').hidden = !any;
}
function fixChanged(msg) {
  renderCheck(); viewer.refreshLabels();
  const parts = [];
  if (S.fixes.dz) { const f = S.fixes.dz * viewer.fingersDir; parts.push(t(f > 0 ? 'knuckle_moved_f' : 'knuckle_moved_w', { mm: fmtNum(Math.abs(f), 1) })); }
  const ch = S.fixes.ch; const any = !!(ch.side || ch.dorsum || ch.fingers) || S.fixes.dz !== 0 || S.fixes.knuckle_s != null;
  $('#fix-status').textContent = msg ?? (any ? [...parts, t('fix_changed')].join(' ') : '');
}
// Re-read the cached scan with the current choices (fast: the mesh stays in memory on the Python side).
let rereading = false;
async function reread() {
  if (rereading || !S.prep) return; rereading = true; const back = document.activeElement;
  const btns = $$('#s2-body button, #s2-go'); btns.forEach(b => { b.disabled = true; });
  viewerBusy(t('updating')); $('#fix-status').textContent = t('updating'); $('#fix-status').classList.add('busy');
  const opts = choiceOpts(); const t0 = performance.now(); let res;
  try { res = await call('reprepare', { opts }); }
  catch (e) { rereading = false; btns.forEach(b => { b.disabled = false; }); $('#fix-status').classList.remove('busy'); return showError(e, { retry: () => { goStep(2); showCheck(); } }); }
  rereading = false; btns.forEach(b => { b.disabled = false; }); $('#fix-status').classList.remove('busy');
  mark('reprepared', { ms: Math.round(performance.now() - t0), status: res.result.status, opts });
  const r = res.result;
  if (r.status === 'refused') { viewerBusy(null); $('#fix-status').textContent = (r.messages || []).filter(m => m.level === 'error').map(m => m.text).join(' ') || t('err_tip_scan'); return; }
  if (S.fixes.dz !== 0) { S.fixes.knuckle_s = r.overrides_applied?.knuckle_s ?? null; S.fixes.dz = 0; }
  S.prep = r; S.prepGlb = res.glb;
  await showCheck(); fixChanged();
  if (back && back.isConnected && back !== document.body) back.focus({ preventScroll: true });   // keep keyboard users in place
}
function toggle(key, cur) { const ch = S.fixes.ch; ch[key] = ch[key] ? undefined : OPP[cur]; if (ch[key] === undefined) delete ch[key]; reread(); }
$('#fx-flip').addEventListener('click', () => { const lm = S.prep?.landmarks || {}; const ch = S.fixes.ch;
  if (ch.dorsum) delete ch.dorsum; else ch.dorsum = OPP[curDorsum(lm)]; reread(); });
$('#fx-fingers').addEventListener('click', () => toggle('fingers', (S.prep?.landmarks || {}).fingers_end || 'low'));
$('#fx-side').addEventListener('click', () => toggle('side', (S.prep?.landmarks || {}).side || 'right'));
const nudge = (towardFingers) => { S.fixes.dz = Math.round((S.fixes.dz + (towardFingers ? 1 : -1) * viewer.fingersDir * 1) * 10) / 10; viewer.setKnuckleShift(S.fixes.dz); fixChanged(); };
$('#fx-up').addEventListener('click', () => nudge(true));
$('#fx-down').addEventListener('click', () => nudge(false));
$('#fx-reset').addEventListener('click', () => {
  const had = !!(S.fixes.ch.side || S.fixes.ch.dorsum || S.fixes.ch.fingers) || S.fixes.knuckle_s != null;
  S.fixes = { ch: {}, dz: 0, knuckle_s: null }; viewer.setKnuckleShift(0);
  if (had) reread(); else fixChanged('');
});
$('#s2-back').addEventListener('click', startOver);

function analyzeOverrides() {
  const r = S.prep, lm = r.landmarks || {}; const o = readOpts(); const ch = S.fixes.ch;
  const ov = { lang: getLang(), tape_cm: o.tape_cm };
  // What the person saw and accepted is what we measure: on "needs input", confirm the shown reading explicitly.
  const confirm = r.status === 'needs_input' || (lm.ambiguities || []).length > 0;
  ov.side = ch.side || (confirm && lm.side ? lm.side : (o.side || 'auto'));
  ov.dorsum = ch.dorsum || (confirm && lm.dorsum ? curDorsum(lm) : 'auto');
  ov.fingers = ch.fingers || (confirm && lm.fingers_end ? lm.fingers_end : 'auto');
  if (S.fixes.dz !== 0) ov.knuckle_z = Math.round(viewer.knuckleZ * 100) / 100;
  else if (S.fixes.knuckle_s != null) ov.knuckle_s = S.fixes.knuckle_s;
  return ov;
}

$('#s2-go').addEventListener('click', runAnalyze);
async function runAnalyze() {
  const btn = $('#s2-go'); btn.disabled = true; $('#s2-back').disabled = true;
  S.overrides = analyzeOverrides(); mark('analyze-start', { overrides: S.overrides });
  viewer.setPicking(false);
  viewerBusy(t('analyzing')); $('#fix-status').textContent = t('analyzing'); $('#fix-status').classList.add('busy');
  progressSink = (txt) => { $('#v-loading-text').textContent = txt; $('#fix-status').textContent = txt; };
  const t0 = performance.now(); let res;
  try { res = await call('analyze', { overrides: S.overrides }); }
  catch (e) { btn.disabled = false; $('#fix-status').classList.remove('busy'); return showError(e, { retry: () => { goStep(2); showCheck().then(runAnalyze); } }); }
  finally { progressSink = null; $('#s2-back').disabled = false; }
  $('#fix-status').classList.remove('busy'); $('#fix-status').textContent = ''; btn.disabled = false;
  S.timings.analyze = Math.round(performance.now() - t0); mark('analyzed', { ms: S.timings.analyze, status: res.result.status });
  const r = res.result;
  if (r.status === 'needs_input') {        // still unsure: back to Check with the new reading and its questions
    S.prep = Object.assign({}, S.prep, { status: 'needs_input', landmarks: r.landmarks || S.prep.landmarks });
    if (res.glb) S.prepGlb = res.glb;
    S.fixes.dz = 0; if (r.overrides_applied?.knuckle_s != null) S.fixes.knuckle_s = r.overrides_applied.knuckle_s;
    await showCheck(); fixChanged(t('still_unsure')); $('#needs').scrollIntoView({ block: 'nearest' });
    return;
  }
  S.ana = r; S.anaGlb = res.glb;
  await showFit();
}

// ---------------------------------------------------------------- step 3: fit
async function showFit() {
  goStep(3);
  const r = S.ana;
  renderLegend(r.status === 'refused' || r.status === 'needs_input' ? null : (r.legend || null));
  if (S.anaGlb) { viewerBusy(t('view_loading')); try { await viewer.show(S.anaGlb, 'fit'); viewer.refreshLabels(); } catch (e) { console.warn(e); } }
  viewerBusy(null);
  $('#legend').hidden = !legendData;
  renderFit();
  try { S.snaps.fit = viewer.snapshot('back', 900, 640); } catch (e) { /* optional */ }
}
function signed(v) { if (!Number.isFinite(v)) return '—'; const s = fmtNum(Math.abs(v), 1); return v > 0.049 ? '+' + s : v < -0.049 ? '\u2212' + s : s; }
function renderFit() {
  const r = S.ana; if (!r) return; const rec = $('#rec'); const c = r.custom; const p = (c && c.predicted) || {};
  const n = r.recommended_size;
  if (r.status === 'custom_ready' && c) {
    rec.className = 'card rec';
    rec.innerHTML = `<p class="rec-k">${esc(t('rec_title'))}</p><p class="rec-v">${esc(t('rec_custom'))}</p>
      <p class="rec-sub">${esc(t('rec_custom_sub', { W: fmtNum(c.W, 1) }))}</p>
      <dl>
        ${Number.isFinite(p.closest_section_gap_before) || Number.isFinite(p.after) ? `<dt>${esc(t('custom_pred'))}</dt><dd>${fmtNum(p.closest_section_gap_before, 2)} <span class="arrow">→</span> <span class="better">${fmtNum(p.after, 2)} mm</span></dd>` : ''}
        ${Number.isFinite(p.max_overlap) ? `<dt>${esc(t('custom_overlap'))}</dt><dd>${fmtNum(p.max_overlap, 2)} mm</dd>` : ''}
        ${Number.isFinite(p.share_le_0p5) ? `<dt>${esc(t('custom_share'))}</dt><dd>${fmtNum(p.share_le_0p5 * 100, 0)} %</dd>` : ''}
        ${Number.isFinite(c.dorsal_profile_mm_min) ? `<dt>${esc(t('custom_lowered'))}</dt><dd>${fmtNum(Math.abs(c.dorsal_profile_mm_min), 1)} mm</dd>` : ''}
      </dl>`;
    $('#s3-actions').innerHTML = `<button type="button" class="btn btn-primary btn-lg" id="s3-build"><span>${esc(t('build_btn'))}</span><svg aria-hidden="true" viewBox="0 0 24 24" class="ico"><path d="M5 12h14m0 0-6-6m6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>`;
    $('#s3-build').addEventListener('click', runBuild);
  } else if (r.status === 'standard_only' || (r.status !== 'refused' && n)) {
    rec.className = 'card rec std';
    rec.innerHTML = `<p class="rec-k">${esc(t('rec_title'))}</p><p class="rec-v">${n ? esc(t('rec_standard', { n })) : esc(t('rec_none'))}</p>
      <p class="rec-sub">${esc(t('std_only_lead'))}</p><p class="help">${esc(t('std_only_rings'))}</p>
      <a class="btn btn-primary btn-block" href="${MAKERWORLD}" target="_blank" rel="noopener noreferrer">${esc(n ? t('std_only_btn', { n }) : t('std_only_btn_generic'))}</a>`;
    $('#s3-actions').innerHTML = `<button type="button" class="btn btn-secondary" id="s3-report">${esc(t('download_report'))}</button>`;
    $('#s3-report').addEventListener('click', () => downloadReport());
  } else {
    rec.className = 'card rec bad';
    const errs = (r.messages || []).filter(m => m.level === 'error').map(m => `<li>${esc(m.text)}</li>`).join('');
    rec.innerHTML = `<p class="rec-k">${esc(t('err_what'))}</p><p class="rec-v">${esc(t('refused_title'))}</p>
      ${errs ? `<ul class="notes">${errs}</ul>` : `<p class="rec-sub">${esc(t('rec_none_sub'))}</p>`}
      <button type="button" class="btn btn-primary btn-block" id="s3-fix">${esc(t('refused_fix'))}</button>
      <a class="btn btn-secondary btn-block" href="${MAKERWORLD}" target="_blank" rel="noopener noreferrer">${esc(t('std_only_btn_generic'))}</a>`;
    $('#s3-fix').addEventListener('click', () => $('#s3-back').click());
    $('#s3-actions').innerHTML = '';
  }
  const notes = (r.messages || []).filter(m => m.text);
  $('#fit-notes').hidden = !notes.length;
  $('#fit-notes ul').innerHTML = notes.map(m => `<li class="lv-${esc(m.level)}"><span class="sr-only">${esc(m.level === 'warn' ? t('note_warn') : m.level === 'error' ? t('note_error') : '')}</span>${esc(m.text)}</li>`).join('');
  $('#sizes').closest('.card').hidden = !(r.sizes || []).length;
  const tb = $('#sizes tbody');
  tb.innerHTML = (r.sizes || []).map(s => {
    const w = fitWord(s); const isRec = s.size === n && r.status !== 'refused';
    return `<tr class="${isRec ? 'is-rec' : ''}"><th scope="row" class="sz">${esc(t('size_n', { n: s.size }))}${isRec && r.status !== 'custom_ready' ? `<span class="rtag">${esc(t('recommended'))}</span>` : ''}${isRec && r.status === 'custom_ready' ? `<span class="rtag">${esc(t('tried_custom'))}</span>` : ''}</th>
      <td><span class="pill ${w}" title="${esc(s.note || '')}">${esc(t('fit_' + w))}</span></td>
      <td class="num ${s.rigid_min < -0.049 ? 'neg' : ''}">${signed(s.rigid_min)}</td><td class="num ${s.dorsal_min < -0.049 ? 'neg' : ''}">${signed(s.dorsal_min)}</td><td class="num ${s.lateral_min < -0.049 ? 'neg' : ''}">${signed(s.lateral_min)}</td></tr>`;
  }).join('');
}
$('#s3-back').addEventListener('click', async () => { goStep(2); legendData = null; $('#legend').hidden = true; await showCheck(); });

// ---------------------------------------------------------------- step 4: build
let timer = null;
function fmtElapsed(ms) { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
function startTimer(el, key) {
  stopTimer(); const t0 = performance.now();
  const tick = () => { el.textContent = (key === 'reading' && !S.toolsReady ? t('tools_loading') + ' · ' : '') + t('elapsed', { s: fmtElapsed(performance.now() - t0) }); };
  tick(); timer = setInterval(tick, 1000);
}
function stopTimer() { if (timer) clearInterval(timer); timer = null; }

async function runBuild() {
  goStep(4);
  $('#s4-title').textContent = t('s4_title'); $('#build-progress').hidden = false; $('#build-done').hidden = true;
  $('#v-toggle').hidden = true;
  const list = $('#build-steps'); list.innerHTML = '';
  const addStep = (txt) => {
    const cur = list.querySelector('li.active span:last-child');
    if (cur && cur.textContent.slice(0, 14) === String(txt).slice(0, 14)) { cur.textContent = txt; return; }   // same step, new detail
    const prev = list.querySelector('li.active'); if (prev) { prev.classList.remove('active'); prev.classList.add('done'); }
    const li = document.createElement('li'); li.className = 'active'; li.innerHTML = `<span class="dot" aria-hidden="true"></span><span>${esc(txt)}</span>`; list.appendChild(li);
  };
  progressSink = (txt) => addStep(txt);
  const lock = (on) => { $('#s4-back').disabled = on; $('#s4-over').disabled = on; };
  lock(true);
  startTimer($('#build-elapsed'), 'build');
  const t0 = performance.now(); let res;
  try { res = await call('build', {}); }
  catch (e) { return showError(e, { retry: () => { goStep(3); runBuild(); } }); }
  finally { progressSink = null; lock(false); }
  stopTimer();
  list.querySelectorAll('li.active').forEach(li => { li.classList.remove('active'); li.classList.add('done'); });
  S.timings.build = Math.round(performance.now() - t0); mark('built', { ms: S.timings.build, status: res.result.status });
  S.build = res.result; S.buildGlb = res.glb; S.files = res.files || {};
  await showResult();
}

function blobUrl(bytes, type) { const u = URL.createObjectURL(new Blob([bytes], { type })); S.urls.push(u); return u; }
const sizeTxt = b => b > 1e6 ? `${fmtNum(b / 1e6, 1)} MB` : `${fmtNum(b / 1e3, 0)} kB`;
async function showResult() {
  const r = S.build; const ok = r.status === 'cuff_ready';
  $('#s4-title').textContent = ok ? t('s4_done_title') : t('s4_stopped_title');
  $('#build-progress').hidden = true; $('#build-done').hidden = false;
  if (r.legend) renderLegend(r.legend);
  if (S.buildGlb) { viewerBusy(t('view_loading')); try { const s = await viewer.show(S.buildGlb, 'result'); $('#v-toggle').hidden = !s.hasCuff; viewer.refreshLabels(); } catch (e) { console.warn(e); } }
  viewerBusy(null);
  try { S.snaps.result = viewer.snapshot('reset', 900, 640); S.snaps.resultSide = viewer.snapshot('side', 900, 640); viewer.frame('reset'); } catch (e) { /* optional */ }
  renderResult();
  $('#s4-title').focus();
}
function renderResult() {
  const r = S.build; if (!r) return; const ok = r.status === 'cuff_ready'; const F = S.files || {};
  $('#s4-title').textContent = ok ? t('s4_done_title') : t('s4_stopped_title');
  S.urls.forEach(u => URL.revokeObjectURL(u)); S.urls = [];
  const item = (cls, ext, title, sub, href, name, bytes) => `<a class="dl ${cls}" href="${href}" download="${esc(name)}"><span class="fi">${ext}</span><span><span class="dt">${esc(title)}</span><span class="ds">${esc(sub)}</span></span><span class="dsz">${bytes ? sizeTxt(bytes) : ''}</span></a>`;
  let h = '';
  if (ok && F['3mf']) h += item('primary', '3MF', t('dl_3mf'), t('dl_3mf_sub'), blobUrl(F['3mf'].bytes, 'model/3mf'), F['3mf'].name, F['3mf'].bytes.byteLength);
  // name the STL like the 3MF (FreshCuff_Custom_W82.0_L.stl), whatever the core calls its work file
  const vid = S.ana?.custom?.variant;
  const stlName = F['3mf'] && /_P1S_PETG\.3mf$/i.test(F['3mf'].name) ? F['3mf'].name.replace(/_P1S_PETG\.3mf$/i, '.stl') : vid ? `FreshCuff_Custom_${vid}.stl` : (F.stl && F.stl.name);
  if (ok && F.stl) h += item('', 'STL', t('dl_stl'), t('dl_stl_sub'), blobUrl(F.stl.bytes, 'model/stl'), stlName, F.stl.bytes.byteLength);
  // the core's standalone printable report when present; the page's own report (with 3D snapshots) otherwise
  const rep = F.report_html ? F.report_html.bytes : reportHtml();
  h += item('', 'HTML', t('dl_report'), t('dl_report_sub'), blobUrl(rep, 'text/html'), 'FreshCuff_Fit_report.html', rep.byteLength ?? rep.length);
  const js = dataJson(); h += item('', 'JSON', t('dl_json'), t('dl_json_sub'), blobUrl(js, 'application/json'), 'FreshCuff_Fit_data.json', js.length);
  if (!ok) h += `<a class="btn btn-secondary" href="${MAKERWORLD}" target="_blank" rel="noopener noreferrer">${esc(t('std_only_btn_generic'))}</a>`;
  $('#downloads').innerHTML = h;
  const v = r.verification || {}; const sp = v.same_pose || {}; const locks = r.locks || {}; const fails = locks.failures || [];
  const checks = locks.checks || [];
  const row = (k, val) => Number.isFinite(val) ? `<dt>${esc(t(k))}</dt><dd>${fmtNum(val, 2)} mm</dd>` : '';
  const msgs = (r.messages || []).filter(m => m.level !== 'info').map(m => `<li>${esc(m.text)}</li>`).join('');
  const tick = '<svg aria-hidden="true" viewBox="0 0 24 24" class="ico"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="m7.5 12.5 3 3 6-6.5" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const cross = '<svg aria-hidden="true" viewBox="0 0 24 24" class="ico"><circle cx="12" cy="12" r="10" fill="currentColor"/><path d="m8.5 8.5 7 7m0-7-7 7" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/></svg>';
  const checkList = checks.length ? `<details class="checklist"><summary>${esc(t('checks_show', { n: checks.length }))}</summary><ul>${checks.map(c => `<li class="${c.ok ? 'ok' : 'bad'}">${c.ok ? tick : cross}<span>${esc(c.name)}${Number.isFinite(c.value) ? ` <span class="muted">${fmtNum(c.value, 2)}${c.unit ? ' ' + esc(c.unit) : ''}${c.limit != null ? ` (${esc(String(c.limit))})` : ''}</span>` : ''}</span><span class="sr-only">${esc(c.ok ? t('check_ok') : t('check_failed'))}</span></li>`).join('')}</ul></details>` : '';
  const vOk = !v.verdict || v.verdict === 'approved';
  $('#verif').innerHTML = `<h2>${esc(t('checks_title'))}</h2>
    ${fails.length ? `<p class="badline">${esc(t('checks_fail'))} ${esc(fails.join('; '))}</p>` : `<p class="okline">${tick}${esc(t('checks_pass'))}</p>`}
    ${checkList}
    ${msgs ? `<ul class="notes">${msgs}</ul>` : ''}
    ${r.verification ? `<h2 class="mt">${esc(t('verif_title'))}</h2>
    <p class="${vOk ? 'okline' : 'badline'}">${vOk ? tick : ''}${esc(vOk ? t('verif_ok') : t('verif_bad'))}</p>
    <dl class="kv">${row('verif_gap', sp.closest_section_gap ?? v.closest_section_gap)}${row('verif_overlap', sp.max_overlap ?? v.max_overlap)}${row('verif_palm', S.ana?.custom?.palm_compression_mm ?? v.palm_compression)}</dl>` : ''}`;
}
function reportHtml() {
  const ch = S.fixes.ch, changes = [];
  if (ch.dorsum) changes.push(t('fix_flip')); if (ch.fingers) changes.push(t('fix_fingers')); if (ch.side) changes.push(t('fix_side'));
  if (S.overrides && (S.overrides.knuckle_z != null || S.overrides.knuckle_s != null)) changes.push(t('fix_move'));
  return buildReport({ prep: S.prep, ana: S.ana, build: S.build, overrides: S.overrides, changes, snaps: S.snaps, scanName: S.scanName, files: S.files, timings: S.timings });
}
function dataJson() {
  const strip = r => { if (!r) return r; const o = JSON.parse(JSON.stringify(r)); delete o.overlays; return o; };   // drop display-only rings
  return JSON.stringify({ app: 'FreshCuff Fit (web)', generated: new Date().toISOString(), scan_name: S.scanName, overrides: S.overrides,
    prepare: strip(S.prep), analyze: strip(S.ana), build: strip(S.build), timings_ms: S.timings,
    note: 'Measurements and the five band cross-sections only. The scan mesh itself is not included.' }, null, 1);
}
function downloadReport() {
  const a = document.createElement('a'); a.href = blobUrl(reportHtml(), 'text/html'); a.download = 'FreshCuff_Fit_report.html'; document.body.appendChild(a); a.click(); a.remove();
}
$('#s4-back').addEventListener('click', async () => { if (!S.ana) return; await showFit(); });
$('#s4-over').addEventListener('click', startOver);

async function startOver() {
  S.urls.forEach(u => URL.revokeObjectURL(u)); S.urls = [];
  S.prep = S.ana = S.build = null; S.prepGlb = S.anaGlb = S.buildGlb = null; S.files = null; S.snaps = {}; legendData = null;
  viewer.clear(); viewer.setPicking(false); $('#legend').hidden = true;
  try { await call('reset', {}); } catch (e) { /* nothing to free */ }
  goStep(1);
}

// ---------------------------------------------------------------- language, phone note, boot
$('#lang').addEventListener('click', () => { setLang(getLang() === 'pt' ? 'en' : 'pt'); });
onLang(() => { renderCheck(); renderFit(); if (S.step === 4 && S.build) renderResult(); if (S.step === 4 && !S.build) $('#s4-title').textContent = t('s4_title'); });
setLang(initialLang()); stepOfLabels();
const phone = window.matchMedia('(max-width: 700px)');
let phoneDismissed = false; try { phoneDismissed = sessionStorage.getItem('fc_phone_ok') === '1'; } catch (e) { /* ignore */ }
const phoneNote = () => { $('#phone-note').hidden = !phone.matches || phoneDismissed; };
phone.addEventListener?.('change', phoneNote); phoneNote();
$('#phone-ok').addEventListener('click', () => { phoneDismissed = true; try { sessionStorage.setItem('fc_phone_ok', '1'); } catch (e) { /* ignore */ } phoneNote(); });
goStep(1, { focus: false });
applyI18n();
