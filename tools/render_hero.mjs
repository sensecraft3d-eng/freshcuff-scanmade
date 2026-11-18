// DEV: node tools/render_hero.mjs  -> web/ui/img/cuff_hero.png (product picture on the start page)
import { createRequire } from 'node:module'; import { spawn } from 'node:child_process'; import path from 'node:path'; import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url); const { chromium } = require('playwright');
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const srv = spawn('python3', [path.join(REPO, 'tools/serve.py'), '--port', '8795', '--root', path.join(REPO, 'web')], { stdio: ['ignore', 'pipe', 'inherit'] });
await new Promise(r => srv.stdout.once('data', r));
// the render page lives in tools/render; expose it through a temporary copy under web is not wanted, so serve it with a route
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1200, height: 760 }, deviceScaleFactor: 1 });
const fs = await import('node:fs');
await p.route('**/__render/**', route => { const f = route.request().url().split('/__render/')[1].split('?')[0]; route.fulfill({ body: fs.readFileSync(path.join(REPO, 'tools/render', f)), contentType: f.endsWith('.js') ? 'text/javascript' : 'text/html' }); });
const qs = process.argv[2] || '';
await p.goto('http://127.0.0.1:8795/__render/hero.html' + qs); await p.waitForFunction(() => window.__done, null, { timeout: 60000 });
await p.locator('#c').screenshot({ path: path.join(REPO, 'web/ui/img/cuff_hero.png'), omitBackground: true });
await b.close(); srv.kill(); console.log('wrote web/ui/img/cuff_hero.png');
