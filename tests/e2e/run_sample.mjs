// FreshCuff ScanMade · end-to-end test in Chromium (Playwright).
// Serves web/ with tools/serve.py (same CSP as production), drives the whole flow with the KEYBOARD ONLY
// (Tab/Enter) using "Try with a sample hand", asserts a 3MF download, records timings and screenshots,
// asserts that no request leaves 127.0.0.1, then takes a phone-viewport screenshot.
//
//   node tests/e2e/run_sample.mjs [--port 8780] [--mock] [--lang pt] [--no-manifest]
//   FRESHCUFF_URL=http://127.0.0.1:8765/ node tests/e2e/run_sample.mjs   (use an already running server, e.g. in CI)
// Output: tests/e2e/out/ (screenshots, timings.json, the downloaded files)
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');   // pre-installed globally (NODE_PATH)

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '../..');
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const PORT = +arg('--port', 8780); const MOCK = process.argv.includes('--mock'); const LANG = arg('--lang', null);
const OUT = path.join(HERE, 'out', MOCK ? 'mock_run' : ''); mkdirSync(OUT, { recursive: true });
const MIN = 60_000;
const T = {}; const t0 = Date.now(); const lap = (k) => { T[k] = Date.now() - t0; console.log(`[${(T[k] / 1000).toFixed(1)} s] ${k}`); };
const fail = (m) => { throw new Error(m); };

// keep web/manifesto.json in step with web/py, dados, grade (the worker refuses any file that does not match)
const EXT_URL = !MOCK && process.env.FRESHCUFF_URL ? process.env.FRESHCUFF_URL.replace(/\/?$/, '/') : null;   // CI serves web/ itself
if (!EXT_URL && !process.argv.includes('--no-manifest')) spawnSync('python3', [path.join(REPO, 'tools/build_manifest.py')], { stdio: 'inherit' });
const srv = EXT_URL ? null : spawn('python3', [path.join(REPO, 'tools/serve.py'), '--port', String(PORT), ...(MOCK ? ['--dev'] : [])], { stdio: ['ignore', 'pipe', 'inherit'] });
if (srv) await new Promise((r, j) => { srv.stdout.once('data', r); srv.once('exit', c => j(new Error('server exited ' + c))); });
const BASE = EXT_URL || `http://127.0.0.1:${PORT}/`;
const LOCAL_HOSTS = ['127.0.0.1', 'localhost', new URL(BASE).hostname];
const browser = await chromium.launch();
const problems = []; const external = []; const tabLog = []; let hiddenCheck = null;
let ok = false;
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, acceptDownloads: true });
  const page = await ctx.newPage();
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') problems.push('console: ' + m.text()); });
  page.on('request', r => { const u = new URL(r.url()); if (!LOCAL_HOSTS.includes(u.hostname) && !['blob:', 'data:'].includes(u.protocol)) external.push(r.url()); });

  // Press Tab until the focused element matches `sel` (proves it is keyboard reachable). Returns the number of presses.
  async function tabTo(sel, max = 80) {
    for (let i = 1; i <= max; i++) {
      await page.keyboard.press('Tab');
      if (await page.evaluate(s => !!document.activeElement && document.activeElement.matches(s), sel)) { tabLog.push({ sel, presses: i }); return i; }
    }
    fail(`keyboard: could not reach ${sel} with Tab`);
  }
  async function shot(name, full = false) { await page.screenshot({ path: path.join(OUT, name + '.png'), fullPage: full }); }

  await page.goto(BASE + (MOCK ? '?mock=1' : '') + (LANG ? (MOCK ? '&' : '?') + 'lang=' + LANG : ''));
  lap('page loaded');
  await page.waitForSelector('#sample'); await page.waitForTimeout(500);
  await shot('01_start', true);
  // tools load in the background while the person reads; wait for them (time it)
  await page.waitForFunction(() => window.__fc && (window.__fc.S.toolsReady || window.__fc.S.toolsError), null, { timeout: 8 * MIN });
  if (await page.evaluate(() => !!window.__fc.S.toolsError)) fail('tools failed: ' + JSON.stringify(await page.evaluate(() => window.__fc.S.toolsError)));
  lap('tools ready');

  // ---- Step 1 → keyboard only
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await tabTo('#sample');
  await page.keyboard.press('Enter');
  lap('sample chosen');
  await page.waitForSelector('#step-2:not([hidden])', { timeout: MIN });
  await page.waitForTimeout(400); await shot('02a_reading');
  await page.waitForSelector('#s2-body:not([hidden]), #error:not([hidden])', { timeout: 15 * MIN });
  if (await page.$('#error:not([hidden])')) { await shot('error_prepare', true); fail('prepare error: ' + await page.textContent('#err-tech')); }
  lap('check ready (prepare done)');
  await page.waitForTimeout(800); await shot('02_check');
  // a fix control is reachable and reversible by keyboard (then undone, so the run stays on the detected values)
  const idle = () => page.waitForFunction(() => !document.querySelector('#fx-flip').disabled && document.querySelector('#v-loading').hidden, null, { timeout: 5 * MIN });
  await tabTo('#fx-flip'); let tf = Date.now(); await page.keyboard.press('Enter'); await page.waitForTimeout(100); await idle();
  T['flip re-read (duration)'] = Date.now() - tf; await page.waitForTimeout(500); await shot('02b_check_flipped');
  if (!(await page.evaluate(() => document.activeElement && document.activeElement.id === 'fx-flip'))) problems.push('focus not restored after flip');
  tf = Date.now(); await page.keyboard.press('Enter'); await page.waitForTimeout(100); await idle();   // flip back
  T['flip back re-read (duration)'] = Date.now() - tf;
  await tabTo('#s2-go'); await page.keyboard.press('Enter');
  lap('analyze started');
  await page.waitForSelector('#step-3:not([hidden]) #sizes tbody tr, #error:not([hidden])', { timeout: 15 * MIN });
  if (await page.$('#error:not([hidden])')) { await shot('error_analyze', true); fail('analyze error: ' + await page.textContent('#err-tech')); }
  lap('fit ready (analyze done)');
  await page.waitForTimeout(800); await shot('03_fit'); await shot('03_fit_full', true);
  const fit = await page.evaluate(() => { const a = window.__fc.S.ana, c = a.custom || {}; return { status: a.status, rec: a.recommended_size, variant: c.variant, W: c.W, gap_before: c.predicted?.closest_section_gap_before, gap_after: c.predicted?.after, max_overlap: c.predicted?.max_overlap, sizes: (a.sizes || []).length }; });
  console.log('fit:', JSON.stringify(fit));
  if (fit.sizes !== 7) problems.push(`expected 7 sizes, got ${fit.sizes}`);
  if (fit.status !== 'custom_ready') fail('sample hand should be custom_ready, got ' + fit.status);

  await tabTo('#s3-build');
  // Emulate the person switching tabs during the build: page hidden AND the viewer at zero size while the
  // result arrives (this used to leave a blank view with labels stuck in the corner).
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    document.querySelector('#viewer').style.display = 'none';
  });
  await page.keyboard.press('Enter');
  lap('build started (page hidden)');
  await page.waitForTimeout(1500); await shot('04a_building');
  await page.waitForSelector('#build-done:not([hidden]), #error:not([hidden])', { timeout: 15 * MIN });
  if (await page.$('#error:not([hidden])')) { await shot('error_build', true); fail('build error: ' + await page.textContent('#err-tech')); }
  lap('cuff ready (build done)');
  await page.waitForTimeout(500);
  await page.evaluate(() => {   // come back to the tab
    delete document.hidden; delete document.visibilityState;
    document.querySelector('#viewer').style.display = '';
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.waitForTimeout(800);
  const vis = await page.evaluate(() => {
    const v = document.querySelector('#viewer').getBoundingClientRect();
    const ls = [...document.querySelectorAll('#labels .lbl:not(.hidden)')].map(e => e.getBoundingClientRect());
    const inside = ls.filter(r => r.left >= v.left - 1 && r.right <= v.right + 1 && r.top >= v.top - 1 && r.bottom <= v.bottom + 1);
    const distinct = new Set(ls.map(r => Math.round(r.left / 20) + ':' + Math.round(r.top / 20))).size;
    return { coverage: window.__fc.viewer.coverage(), labels: ls.length, inside: inside.length, distinct };
  });
  // the GPU may also drop the WebGL context of a background tab: lose it, give it back, the view must come back
  await page.evaluate(() => { const gl = window.__fc.viewer.renderer.getContext(); window.__lc = gl.getExtension('WEBGL_lose_context'); window.__lc && window.__lc.loseContext(); });
  await page.waitForTimeout(400);
  await page.evaluate(() => window.__lc && window.__lc.restoreContext());
  await page.waitForTimeout(1200);
  vis.coverage_after_context_restore = await page.evaluate(() => window.__fc.viewer.coverage());
  hiddenCheck = vis; console.log('view after hidden build:', JSON.stringify(vis));
  if (!(vis.coverage_after_context_restore > 0.02)) fail('3D view blank after a WebGL context loss: ' + JSON.stringify(vis));
  if (!(vis.coverage > 0.02)) fail('3D view blank after the page was hidden during the build: ' + JSON.stringify(vis));
  if (!(vis.labels >= 2 && vis.inside === vis.labels && vis.distinct >= 2)) fail('labels misplaced after hidden build: ' + JSON.stringify(vis));
  await page.waitForTimeout(800); await shot('04_result'); await shot('04_result_full', true);
  const bstatus = await page.evaluate(() => window.__fc.S.build.status);
  if (bstatus !== 'cuff_ready') fail('build status ' + bstatus);

  // ---- downloads (3MF by keyboard: Tab to the link, Enter)
  const dlPromise = page.waitForEvent('download', { timeout: MIN });
  await tabTo('a.dl.primary'); await page.keyboard.press('Enter');
  const dl = await dlPromise; const name3 = dl.suggestedFilename(); const p3 = path.join(OUT, name3); await dl.saveAs(p3);
  const head = readFileSync(p3).subarray(0, 2).toString('latin1'); const sz = statSync(p3).size;
  if (!name3.endsWith('.3mf') || head !== 'PK' || sz < 50_000) fail(`3MF download invalid: ${name3} ${sz} B head=${head}`);
  console.log(`3MF ok: ${name3} (${(sz / 1e6).toFixed(2)} MB)`);
  const stlName = await page.getAttribute('a.dl[download$=".stl"]', 'download');
  if (stlName !== name3.replace(/_P1S_PETG\.3mf$/, '.stl')) fail(`STL name ${stlName} does not match the 3MF ${name3}`);
  for (const [sel, ext] of [['a.dl[download$=".stl"]', '.stl'], ['a.dl[download$=".html"]', '.html'], ['a.dl[download$=".json"]', '.json']]) {
    const el = await page.$(sel); if (!el) { problems.push('missing download ' + ext); continue; }
    const [d] = await Promise.all([page.waitForEvent('download'), el.click()]);
    await d.saveAs(path.join(OUT, d.suggestedFilename()));
  }
  lap('downloads saved');

  // report page renders (open the downloaded HTML file)
  const rp = await ctx.newPage(); await rp.goto('file://' + path.join(OUT, 'FreshCuff_ScanMade_report.html')); await rp.waitForTimeout(300);
  await rp.screenshot({ path: path.join(OUT, '05_report.png'), fullPage: true }); await rp.close();

  const appT = await page.evaluate(() => window.__fc.S.timings);
  writeFileSync(path.join(OUT, 'timings.json'), JSON.stringify({ wall_ms: T, app_ms: appT, fit, hidden_tab_check: hiddenCheck, tab_stops: tabLog, external_requests: external, problems, when: new Date().toISOString(), mock: MOCK }, null, 1));

  // ---- Portuguese toggle (keyboard) on the result page
  await page.keyboard.press('Shift+Tab'); await page.focus('#lang'); await page.keyboard.press('Enter'); await page.waitForTimeout(300);
  await shot('04_result_pt');
  if ((await page.textContent('#s4-title')).trim() !== 'Seu cuff está pronto') problems.push('PT toggle did not translate the result title');

  // ---- phone viewport
  const ph = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const pp = await ph.newPage(); await pp.goto(BASE + (MOCK ? '?mock=1' : '')); await pp.waitForTimeout(800);
  await pp.screenshot({ path: path.join(OUT, '06_phone_start.png'), fullPage: true });
  const overflow = await pp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (overflow) problems.push('phone: horizontal overflow');
  if (await pp.$('#phone-note[hidden]')) problems.push('phone: best-on-computer note not shown');
  await ph.close();

  if (external.length) fail('requests left the computer: ' + external.join(', '));
  ok = true;
} catch (e) {
  console.error('E2E FAILED:', e.message);
  writeFileSync(path.join(OUT, 'timings.json'), JSON.stringify({ wall_ms: T, failed: e.message, tab_stops: tabLog, external_requests: external, problems }, null, 1));
} finally {
  await browser.close(); if (srv) srv.kill();
  console.log('timings (s):', Object.fromEntries(Object.entries(T).map(([k, v]) => [k, +(v / 1000).toFixed(1)])));
  if (problems.length) console.log('problems:', problems);
  console.log(ok ? 'E2E PASSED' : 'E2E FAILED');
  process.exit(ok ? 0 : 1);
}
