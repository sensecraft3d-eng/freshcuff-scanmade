// FreshCuff ScanMade · UI states that the sample run does not reach, against the mock worker (fast, no Python):
//  M5  keyboard: Tab to "Choose a file" (visible focus ring), Enter opens the file chooser
//  B2  tape required before Build (user file: blocked with a message; sample: 18.2 cm entered and stated;
//      tape disagreeing with the scan: refused on the Fit step; build() needs_input/refused: way back to the tape)
//  B1  'no_verified_standard_fit': no recommended number anywhere, only a labelled estimate
//  M6  report without pictures has no images; m2 glTF: self-contained accepted, external refused with a message
//   node tests/e2e/run_states.mjs [--port 8785]       (screenshots in tests/e2e/out/states/)
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url); const { chromium } = require('playwright');
const HERE = path.dirname(fileURLToPath(import.meta.url)); const REPO = path.resolve(HERE, '../..');
const OUT = path.join(HERE, 'out', 'states'); mkdirSync(OUT, { recursive: true });
const i = process.argv.indexOf('--port'); const PORT = i > 0 ? +process.argv[i + 1] : 8785;
const srv = spawn('python3', [path.join(REPO, 'tools/serve.py'), '--port', String(PORT), '--dev'], { stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise(r => srv.stdout.once('data', r));
const browser = await chromium.launch(); const results = []; let failed = 0;
const SAMPLE = path.join(REPO, 'web/examples/Artec_Hand.ply');
async function scenario(name, mode, fn) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, acceptDownloads: true });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  try {
    await p.goto(`http://127.0.0.1:${PORT}/?mock=${mode}`); await p.waitForFunction(() => window.__fc && window.__fc.S.toolsReady);
    await fn(p); if (errs.length) throw new Error('page errors: ' + errs.join(' | '));
    results.push(`PASS ${name}`);
  } catch (e) { failed++; results.push(`FAIL ${name}: ${e.message.split('\n')[0]}`); await p.screenshot({ path: path.join(OUT, `fail_${name}.png`) }).catch(() => {}); }
  await ctx.close();
}
const ok = (c, m) => { if (!c) throw new Error(m); };
const toFit = async (p, how) => {
  if (how === 'sample') await p.click('#sample'); else await p.setInputFiles('#file', SAMPLE);
  await p.waitForSelector('#s2-body:not([hidden])'); await p.click('#s2-go'); await p.waitForSelector('#step-3:not([hidden])'); await p.waitForTimeout(300);
};

await scenario('M5 keyboard file chooser', '1', async p => {
  let n = 0; while (n++ < 20) { await p.keyboard.press('Tab'); if (await p.evaluate(() => document.activeElement?.id === 'choose')) break; }
  ok(await p.evaluate(() => document.activeElement?.id === 'choose'), 'could not Tab to Choose a file');
  const ring = await p.evaluate(() => getComputedStyle(document.activeElement).boxShadow);
  ok(ring && ring !== 'none', 'no visible focus ring on Choose a file');
  await p.screenshot({ path: path.join(OUT, 'm5_focus_choose.png'), clip: { x: 80, y: 420, width: 760, height: 320 } });
  const fcP = p.waitForEvent('filechooser', { timeout: 8000 }); await p.waitForTimeout(300);   // let Playwright arm the chooser interception first
  await p.keyboard.press('Enter'); const fc = await fcP;
  ok(fc, 'Enter did not open the file chooser');
});
await scenario('B2 user file: tape required before Build', '1', async p => {
  await toFit(p, 'file');
  ok((await p.evaluate(() => window.__fc.S.ana.status)) === 'custom_needs_tape', 'expected custom_needs_tape');
  ok(await p.isVisible('#tape-card'), 'tape card not shown'); ok(await p.isHidden('#tape-sample'), 'sample note shown for a user file');
  ok((await p.inputValue('#tape')) === '', 'tape not empty for a user file');
  ok(await p.isDisabled('#s3-build'), 'Build enabled before the tape is confirmed');
  await p.click('#tape-check'); await p.waitForTimeout(300);
  ok((await p.textContent('#tape-err')).length > 10, 'no tape message'); ok(await p.evaluate(() => document.activeElement?.id === 'tape'), 'focus not on the tape field');
  await p.screenshot({ path: path.join(OUT, 'b2_tape_required.png'), fullPage: true });
  await p.fill('#tape', '18.3'); await p.press('#tape', 'Enter');
  await p.waitForFunction(() => window.__fc.S.ana.status === 'custom_ready'); await p.waitForTimeout(200);
  ok(!(await p.isDisabled('#s3-build')), 'Build still disabled after the tape was confirmed');
  await p.click('#s3-build'); await p.waitForSelector('#build-done:not([hidden])');
  ok((await p.evaluate(() => window.__fc.S.overrides.tape_cm)) === 18.3, 'tape not sent to the analysis');
});
await scenario('B2 sample: 18.2 cm entered and stated', '1', async p => {
  await toFit(p, 'sample');
  ok((await p.inputValue('#tape')) === '18.2', 'sample tape not 18.2'); ok(await p.isVisible('#tape-sample'), 'sample tape note hidden');
  await p.screenshot({ path: path.join(OUT, 'b2_sample_tape.png'), fullPage: true });
});
await scenario('B2 tape disagrees with scan: refused on Fit', '1', async p => {
  await toFit(p, 'file'); await p.fill('#tape', '25'); await p.click('#tape-check');
  await p.waitForFunction(() => window.__fc.S.ana && window.__fc.S.ana.status === 'refused');
  await p.waitForTimeout(300);
  ok(await p.isVisible('#step-3'), 'not on Fit'); ok((await p.textContent('#rec')).includes('25'), 'mismatch message not shown');
  ok(await p.isVisible('#tape-card'), 'tape card hidden after a mismatch'); ok(await p.isDisabled('#s3-build').catch(() => true), 'Build available after a mismatch');
  ok(!(await p.evaluate(() => window.__fc.events.some(e => e.name === 'built'))), 'built despite tape mismatch');
  await p.screenshot({ path: path.join(OUT, 'b2_tape_refused.png'), fullPage: true });
});
for (const mode of ['buildneeds', 'buildrefused']) await scenario(`B2 build() ${mode}`, mode, async p => {
  await toFit(p, 'sample'); await p.click('#s3-build'); await p.waitForSelector('#build-done:not([hidden])');
  ok((await p.textContent('#s4-title')).includes('not'), 'title should say not built');
  ok(!(await p.$('a.dl.primary')), '3MF offered although not built');
  const verif = await p.textContent('#verif');
  ok(!verif.includes('All checks passed'), 'says checks passed although none ran (M-R03-01)');
  ok(verif.includes('Checks not run'), 'missing "checks not run" line');
  const rep = await p.evaluate(() => window.__fc && typeof window.__fc.reportHtml === 'function' ? window.__fc.reportHtml(false) : null);
  ok(rep != null, 'report function not exposed'); ok(!rep.includes('All checks passed') && rep.includes('Checks not run'), 'report says checks passed although none ran');
  await p.screenshot({ path: path.join(OUT, `b2_${mode}.png`), fullPage: true });
  await p.click('#s4-tape'); await p.waitForSelector('#step-3:not([hidden])'); await p.waitForTimeout(200);
  ok(await p.evaluate(() => document.activeElement?.id === 'tape'), 'back to tape did not focus the field');
});
await scenario('m-R04-01 cuff_ready without check results is not shown as passed', 'readyempty', async p => {
  await toFit(p, 'sample'); await p.click('#s3-build'); await p.waitForSelector('#build-done:not([hidden])');
  const verif = await p.textContent('#verif');
  ok(!verif.includes('All checks passed'), 'empty checks shown as passed'); ok(!verif.includes('matches the prediction'), 'missing verdict shown as approved');
  const rep = await p.evaluate(() => window.__fc.reportHtml(false));
  ok(!rep.includes('All checks passed'), 'report shows empty checks as passed');
  ok(!(await p.$('a.dl.primary')), '3MF offered for an inconsistent cuff_ready (M-R05-01)');
  ok(!(await p.$('a[download$=".stl"]')), 'STL offered for an inconsistent cuff_ready (M-R05-01)');
  ok((await p.textContent('#s4-title')).includes('not'), 'title should say not built');
  ok((await p.textContent('#downloads')).includes('inconsistent'), 'inconsistency message missing');
  ok(!rep.includes('<ol>') && rep.includes('No cuff was released for printing'), 'print steps in report for an inconsistent result');
});
for (const mode of ['buildneeds', 'buildrefused']) await scenario(`m-R04-02 report has no print steps when ${mode}`, mode, async p => {
  await toFit(p, 'sample'); await p.click('#s3-build'); await p.waitForSelector('#build-done:not([hidden])');
  const rep = await p.evaluate(() => window.__fc.reportHtml(false));
  ok(rep.includes('No cuff was released for printing'), 'missing not-released line'); ok(!rep.includes('<ol>'), 'print steps present in a refused report');
});
await scenario('m-R05-01 report states a rejected re-check and its reason', 'verifrejected', async p => {
  await toFit(p, 'sample'); await p.click('#s3-build'); await p.waitForSelector('#build-done:not([hidden])');
  ok(!(await p.$('a.dl.primary')), '3MF offered although the re-check was rejected');
  const rep = await p.evaluate(() => window.__fc.reportHtml(false));
  ok(rep.includes('gap differs from the prediction'), 'rejection reason missing from the report');
  ok(rep.includes('No cuff was released for printing'), 'not-released line missing');
});
await scenario('B1 no verified standard fit', 'nofit', async p => {
  await toFit(p, 'file');
  const rec = await p.textContent('#rec');
  ok(rec.includes('None of the standard sizes passed'), 'no-fit title missing'); ok(/Estimate/.test(rec), 'estimate not labelled');
  ok(!/Size \d/.test(rec.replace(/size \d/i, '')), 'a size number shown as a suggestion');
  ok((await p.$$('#sizes .rtag')).length === 0, 'a size is tagged as suggested'); ok(await p.isHidden('#tape-card'), 'tape card shown without custom cuff');
  await p.screenshot({ path: path.join(OUT, 'b1_nofit.png'), fullPage: true });
  const [d] = await Promise.all([p.waitForEvent('download'), p.click('#s3-report')]); const f = path.join(OUT, d.suggestedFilename()); await d.saveAs(f);
  const html = readFileSync(f, 'utf8'); ok(!/<img/.test(html), 'shareable report has pictures'); ok(!/Suggested|Our suggestion: Size/.test(html), 'report suggests a size');
});
await scenario('M6 shareable report without pictures', '1', async p => {
  await toFit(p, 'sample'); await p.click('#s3-build'); await p.waitForSelector('#build-done:not([hidden])');
  const [d] = await Promise.all([p.waitForEvent('download'), p.click('a.dl[download$="_shareable.html"]')]); const f = path.join(OUT, d.suggestedFilename()); await d.saveAs(f);
  ok(!/<img/.test(readFileSync(f, 'utf8')), 'shareable report contains images');
  ok((await p.textContent('.feedback')).includes('without pictures'), 'feedback text does not point to the shareable report');
});
await scenario('m2 glTF self-contained accepted', '1', async p => {
  await p.setInputFiles('#file', path.join(HERE, 'assets/tetra_embedded.gltf')); await p.waitForTimeout(800);
  ok(await p.evaluate(() => window.__fc.events.some(e => e.name === 'scan-read' && e.converted)), 'embedded glTF not converted');
});
await scenario('m2 glTF with external buffers refused clearly', '1', async p => {
  await p.setInputFiles('#file', path.join(HERE, 'assets/tetra_external.gltf')); await p.waitForSelector('#error:not([hidden])');
  ok((await p.textContent('#err-msg')).includes('GLB'), 'message does not suggest GLB');
  await p.screenshot({ path: path.join(OUT, 'm2_gltf_external.png') });
});
await browser.close(); srv.kill();
console.log(results.join('\n')); console.log(failed ? `STATES FAILED (${failed})` : 'STATES PASSED'); process.exit(failed ? 1 : 0);
