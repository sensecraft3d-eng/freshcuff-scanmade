// FreshCuff ScanMade · e2e of the Check-step fixes on the real Python core: swap finger end (re-read), undo,
// click on the hand to move the knuckle line, then measure. Screenshots + JSON in tests/e2e/out/fixes/.
//   node tests/e2e/run_fixes.mjs [--port 8783]
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url); const { chromium } = require('playwright');
const HERE = path.dirname(fileURLToPath(import.meta.url)); const REPO = path.resolve(HERE, '../..');
const OUT = path.join(HERE, 'out', 'fixes'); mkdirSync(OUT, { recursive: true });
const i = process.argv.indexOf('--port'); const PORT = i > 0 ? +process.argv[i + 1] : 8783; const MIN = 60_000;
// keep web/manifesto.json in step with web/py, dados, grade (the worker refuses any file that does not match)
if (!process.argv.includes('--no-manifest')) spawnSync('python3', [path.join(REPO, 'tools/build_manifest.py')], { stdio: 'inherit' });
const srv = spawn('python3', [path.join(REPO, 'tools/serve.py'), '--port', String(PORT)], { stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise(r => srv.stdout.once('data', r));
const b = await chromium.launch(); const log = {}; let ok = false;
try {
  const p = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  p.on('pageerror', e => { log.pageerror = (log.pageerror || []).concat(e.message); });
  const idle = () => p.waitForFunction(() => !document.querySelector('#fx-flip').disabled && document.querySelector('#v-loading').hidden, null, { timeout: 5 * MIN });
  await p.goto(`http://127.0.0.1:${PORT}/`); await p.click('#sample');
  await p.waitForSelector('#s2-body:not([hidden]), #error:not([hidden])', { timeout: 10 * MIN });
  if (await p.$('#error:not([hidden])')) throw new Error('prepare error: ' + await p.textContent('#err-tech'));
  await idle();
  const lm0 = await p.evaluate(() => window.__fc.S.prep.landmarks);
  console.log('check ready', Date.now());
  await p.click('#fx-fingers'); await p.waitForTimeout(100); await idle(); await p.waitForTimeout(400);
  await p.screenshot({ path: path.join(OUT, '1_fingers_swapped.png') });
  log.swapped = await p.evaluate(() => ({ status: window.__fc.S.prep.status, fingers_end: window.__fc.S.prep.landmarks.fingers_end, amb: (window.__fc.S.prep.landmarks.ambiguities || []).map(a => a.kind), applied: window.__fc.S.prep.overrides_applied }));
  log.swapped.before = lm0.fingers_end;
  console.log('swapped', JSON.stringify(log.swapped), Date.now());
  await p.click('#fx-reset'); await p.waitForTimeout(100); await idle(); await p.waitForTimeout(300);
  log.undone = await p.evaluate(() => window.__fc.S.prep.landmarks.fingers_end);
  // click on the hand a little toward the wrist from the band centre (canvas centre-ish)
  const box = await p.locator('#canvas').boundingBox();
  await p.mouse.click(box.x + box.width * 0.62, box.y + box.height * 0.52); await p.waitForTimeout(300);
  log.dz = await p.evaluate(() => window.__fc.S.fixes.dz); console.log('clicked, dz =', log.dz, 'undone fingers =', log.undone);
  await p.screenshot({ path: path.join(OUT, '2_knuckle_clicked.png') });
  // undo the click (it was only to prove picking works) and move the line 2 mm toward the wrist with the buttons
  await p.click('#fx-reset'); await p.waitForTimeout(100); await idle();
  await p.click('#fx-down'); await p.click('#fx-down'); log.dz_buttons = await p.evaluate(() => window.__fc.S.fixes.dz);
  await p.click('#s2-go'); console.log('analyze started, dz =', log.dz_buttons);
  await p.waitForFunction(() => !document.querySelector('#step-3').hidden || !document.querySelector('#error').hidden || (window.__fc.events.slice(-1)[0] || {}).name === 'analyzed', null, { timeout: 10 * MIN });
  await p.waitForTimeout(600); await p.screenshot({ path: path.join(OUT, '3_after_click_fit.png') });
  log.analyze = await p.evaluate(() => ({ sent: window.__fc.S.overrides, status: window.__fc.S.ana && window.__fc.S.ana.status, applied: window.__fc.S.ana && window.__fc.S.ana.overrides_applied, rec: window.__fc.S.ana && window.__fc.S.ana.recommended_size }));
  ok = log.swapped.fingers_end !== lm0.fingers_end && log.undone === lm0.fingers_end && log.dz !== 0 && log.analyze.sent.knuckle_z != null && !!log.analyze.status;
} catch (e) { log.error = e.message; }
finally {
  writeFileSync(path.join(OUT, 'fixes.json'), JSON.stringify(log, null, 1)); console.log(JSON.stringify(log, null, 1));
  await b.close(); srv.kill(); console.log(ok ? 'FIXES PASSED' : 'FIXES FAILED'); process.exit(ok ? 0 : 1);
}
