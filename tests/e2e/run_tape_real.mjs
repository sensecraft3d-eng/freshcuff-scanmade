// FreshCuff ScanMade · tape gate on the REAL Python core (no mock). The Artec hand is loaded through the file input
// (not the sample button, so no tape is filled in):
//   no tape -> Fit shows custom_needs_tape, Build disabled
//   19.5 cm (disagrees with the 18.2 cm scan by > 0.6) -> refused on the Fit step, nothing built
//   18.2 cm -> custom_ready -> Build -> 3MF downloaded
//   node tests/e2e/run_tape_real.mjs [--port 8784] [--no-manifest]      (out: tests/e2e/out/tape/)
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url); const { chromium } = require('playwright');
const HERE = path.dirname(fileURLToPath(import.meta.url)); const REPO = path.resolve(HERE, '../..');
const OUT = path.join(HERE, 'out', 'tape'); mkdirSync(OUT, { recursive: true });
const i = process.argv.indexOf('--port'); const PORT = i > 0 ? +process.argv[i + 1] : 8784; const MIN = 60_000;
if (!process.argv.includes('--no-manifest')) spawnSync('python3', [path.join(REPO, 'tools/build_manifest.py')], { stdio: 'inherit' });
const srv = spawn('python3', [path.join(REPO, 'tools/serve.py'), '--port', String(PORT)], { stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise(r => srv.stdout.once('data', r));
const b = await chromium.launch(); const log = { steps: [] }; let ok = false; const t0 = Date.now();
const step = (k, v) => { log.steps.push({ k, s: +((Date.now() - t0) / 1000).toFixed(1), v }); console.log(`[${((Date.now() - t0) / 1000).toFixed(1)} s] ${k}`, v ? JSON.stringify(v) : ''); };
const fail = m => { throw new Error(m); };
try {
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, acceptDownloads: true });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  const analyzed = n => p.waitForFunction(n => window.__fc.events.filter(e => e.name === 'analyzed').length >= n, n, { timeout: 10 * MIN });
  await p.goto(`http://127.0.0.1:${PORT}/`);
  await p.setInputFiles('#file', path.join(REPO, 'web/examples/Artec_Hand.ply'));
  await p.waitForSelector('#s2-body:not([hidden]), #error:not([hidden])', { timeout: 10 * MIN });
  if (await p.$('#error:not([hidden])')) fail('prepare error: ' + await p.textContent('#err-tech'));
  step('check ready');
  await p.click('#s2-go'); await analyzed(1); await p.waitForTimeout(500);
  const a1 = await p.evaluate(() => ({ status: window.__fc.S.ana.status, needs: window.__fc.S.ana.needs, build_disabled: document.querySelector('#s3-build')?.disabled, tape_card: !document.querySelector('#tape-card').hidden, tape: document.querySelector('#tape').value }));
  step('no tape', a1); await p.screenshot({ path: path.join(OUT, '1_custom_needs_tape.png'), fullPage: true });
  if (a1.status !== 'custom_needs_tape' || !a1.build_disabled || !a1.tape_card || a1.tape !== '') fail('no-tape state wrong: ' + JSON.stringify(a1));

  await p.fill('#tape', '19.5'); await p.click('#tape-check'); await analyzed(2); await p.waitForTimeout(500);
  const a2 = await p.evaluate(() => ({ status: window.__fc.S.ana.status, err: document.querySelector('#tape-err').textContent, build: !!document.querySelector('#s3-build') && !document.querySelector('#s3-build').disabled, built: window.__fc.events.some(e => e.name === 'built') }));
  step('tape 19.5', a2); await p.screenshot({ path: path.join(OUT, '2_tape_19_5_refused.png'), fullPage: true });
  if (a2.status !== 'refused' || a2.err.length < 10 || a2.build || a2.built) fail('19.5 cm state wrong: ' + JSON.stringify(a2));

  await p.fill('#tape', '18.2'); await p.click('#tape-check'); await analyzed(3); await p.waitForTimeout(500);
  const a3 = await p.evaluate(() => ({ status: window.__fc.S.ana.status, scale_confirmed: window.__fc.S.ana.scale_confirmed, build_enabled: !!document.querySelector('#s3-build') && !document.querySelector('#s3-build').disabled, ok: document.querySelector('#tape-ok').textContent }));
  step('tape 18.2', a3); await p.screenshot({ path: path.join(OUT, '3_tape_18_2_ready.png'), fullPage: true });
  if (a3.status !== 'custom_ready' || !a3.build_enabled) fail('18.2 cm state wrong: ' + JSON.stringify(a3));

  await p.click('#s3-build'); await p.waitForSelector('#build-done:not([hidden]), #error:not([hidden])', { timeout: 10 * MIN });
  const bs = await p.evaluate(() => window.__fc.S.build && window.__fc.S.build.status); step('build', { status: bs });
  if (bs !== 'cuff_ready') fail('build status ' + bs);
  const dlP = p.waitForEvent('download'); await p.click('a.dl.primary'); const d = await dlP;
  const f = path.join(OUT, d.suggestedFilename()); await d.saveAs(f);
  const head = readFileSync(f).subarray(0, 2).toString('latin1'); const sz = statSync(f).size;
  step('3MF', { name: d.suggestedFilename(), bytes: sz });
  if (!f.endsWith('.3mf') || head !== 'PK' || sz < 50_000) fail('bad 3MF');
  await p.screenshot({ path: path.join(OUT, '4_built.png') });
  if (errs.length) fail('page errors: ' + errs.join(' | '));
  ok = true;
} catch (e) { log.error = e.message; console.error('FAILED:', e.message); }
finally { writeFileSync(path.join(OUT, 'tape.json'), JSON.stringify(log, null, 1)); await b.close(); srv.kill(); console.log(ok ? 'TAPE REAL PASSED' : 'TAPE REAL FAILED'); process.exit(ok ? 0 : 1); }
