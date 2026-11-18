// DEV: quick UI screenshots against the mock worker (?mock=1). node tests/e2e/shots_mock.mjs [port]
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');   // global install (NODE_PATH)
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const HERE = path.dirname(fileURLToPath(import.meta.url)); const REPO = path.resolve(HERE, '../..');
const OUT = path.join(HERE, 'out', 'mock'); mkdirSync(OUT, { recursive: true });
const port = +(process.argv[2] || 8771); const mode = process.argv[3] || '1';
const srv = spawn('python3', [path.join(REPO, 'tools/serve.py'), '--port', String(port), '--dev'], { stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise(r => srv.stdout.once('data', r));
const browser = await chromium.launch();
const errors = [];
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, acceptDownloads: true });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  await page.goto(`http://127.0.0.1:${port}/?mock=${mode}`);
  await page.waitForFunction(() => window.__fc && window.__fc.S.toolsReady);
  await page.screenshot({ path: path.join(OUT, `1_start_${mode}.png`), fullPage: true });
  await page.click('#sample');
  await page.waitForSelector('#s2-body:not([hidden])', { timeout: 60000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, `2_check_${mode}.png`) });
  await page.click('#fx-flip'); await page.click('#fx-up'); await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT, `2b_check_fixed_${mode}.png`) });
  await page.click('#fx-reset');
  await page.click('#s2-go');
  await page.waitForSelector('#step-3:not([hidden]) #sizes tbody tr', { timeout: 60000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, `3_fit_${mode}.png`) });
  if (await page.$('#s3-build')) {
    await page.click('#s3-build');
    await page.waitForTimeout(900);
    await page.screenshot({ path: path.join(OUT, `4a_building_${mode}.png`) });
    await page.waitForSelector('#build-done:not([hidden])', { timeout: 60000 });
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(OUT, `4_result_${mode}.png`) });
    await page.screenshot({ path: path.join(OUT, `4_result_full_${mode}.png`), fullPage: true });
  }
} finally { await browser.close(); srv.kill(); console.log('errors:', JSON.stringify(errors, null, 1)); }
