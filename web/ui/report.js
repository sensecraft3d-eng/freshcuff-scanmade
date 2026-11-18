// FreshCuff ScanMade · printable fit report (a standalone HTML file, no scripts, images inlined as data: URLs).
import { t, fmtNum, getLang } from './i18n.js';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const mm = v => Number.isFinite(v) ? `${v < -0.004 ? '\u2212' : ''}${fmtNum(Math.abs(v), 2)} mm` : '—';

export function fitWord(s) { return s.fits ? 'fits' : (Number.isFinite(s.rigid_min) && s.rigid_min < 0 ? 'tight' : 'loose'); }

export function buildReport({ prep, ana, build, overrides, changes, snaps, scanName, files, timings }) {
  const lang = getLang(); const date = new Date().toLocaleString(lang === 'pt' ? 'pt-BR' : 'en-GB');
  const lm = prep?.landmarks || {}; const q = prep?.scan?.quality || {};
  const sideTxt = lm.side === 'left' ? t('side_left') : lm.side === 'right' ? t('side_right') : '—';
  const ovr = changes || [];
  const rows = (ana?.sizes || []).map(s => {
    const w = fitWord(s); const rec = s.size === ana.recommended_size;
    return `<tr${rec ? ' class="rec"' : ''}><td><b>${esc(t('size_n', { n: s.size }))}</b>${rec ? ` <span class="tag">${esc(t('recommended'))}</span>` : ''}</td><td class="${w}">${esc(t('fit_' + w))}</td><td class="n">${mm(s.rigid_min)}</td><td class="n">${mm(s.dorsal_min)}</td><td class="n">${mm(s.lateral_min)}</td></tr>`;
  }).join('');
  const c = ana?.custom; const p = c?.predicted || {};
  let recHtml = '';
  if (ana?.status === 'custom_ready' && c) {
    recHtml = `<h2>${esc(t('rec_title'))}: ${esc(t('rec_custom'))}</h2><p>${esc(t('rec_custom_sub', { W: fmtNum(c.W, 1) }))}</p>
      <table class="kv"><tr><td>${esc(t('custom_pred'))}</td><td class="n">${mm(p.closest_section_gap_before)} → ${mm(p.after)}</td></tr>
      <tr><td>${esc(t('custom_overlap'))}</td><td class="n">${mm(p.max_overlap)}</td></tr>
      ${Number.isFinite(p.share_le_0p5) ? `<tr><td>${esc(t('custom_share'))}</td><td class="n">${fmtNum(p.share_le_0p5 * 100, 0)} %</td></tr>` : ''}
      ${Number.isFinite(c.dorsal_profile_mm_min) ? `<tr><td>${esc(t('custom_lowered'))}</td><td class="n">${mm(Math.abs(c.dorsal_profile_mm_min))}</td></tr>` : ''}</table>`;
  } else if (ana?.recommended_size) {
    recHtml = `<h2>${esc(t('rec_title'))}: ${esc(t('rec_standard', { n: ana.recommended_size }))}</h2><p>${esc(t('std_only_lead'))}</p><p>https://makerworld.com/en/models/3595433</p>`;
  }
  let buildHtml = '';
  if (build) {
    const v0 = build.verification || {}; const v = Object.assign({}, v0, v0.same_pose || {}, { palm_compression: ana?.custom?.palm_compression_mm }); const fails = build.locks?.failures || [];
    buildHtml = `<h2>${esc(t('verif_title'))}</h2><table class="kv">
      ${Number.isFinite(v.closest_section_gap) ? `<tr><td>${esc(t('verif_gap'))}</td><td class="n">${mm(v.closest_section_gap)}</td></tr>` : ''}
      ${Number.isFinite(v.max_overlap) ? `<tr><td>${esc(t('verif_overlap'))}</td><td class="n">${mm(v.max_overlap)}</td></tr>` : ''}
      ${Number.isFinite(v.palm_compression) ? `<tr><td>${esc(t('verif_palm'))}</td><td class="n">${mm(v.palm_compression)}</td></tr>` : ''}
      <tr><td>${esc(t('checks_title'))}</td><td class="n">${fails.length ? esc(t('checks_fail')) + ' ' + fails.length : esc(t('checks_pass'))}</td></tr></table>`;
  }
  const img = (u, cap) => u ? `<figure><img src="${u}" alt="${esc(cap)}"><figcaption>${esc(cap)}</figcaption></figure>` : '';
  const fileList = Object.values(files || {}).map(f => `<li>${esc(f.name)}${f.sha256 ? ` <code>sha256 ${esc(f.sha256.slice(0, 16))}…</code>` : ''}</li>`).join('');
  return `<!DOCTYPE html><html lang="${lang === 'pt' ? 'pt-BR' : 'en'}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(t('rep_title'))}</title><style>
body{font:15px/1.5 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:#191c1e;max-width:860px;margin:0 auto;padding:32px 24px;background:#fff}
header{display:flex;justify-content:space-between;align-items:baseline;border-bottom:3px solid #2a2e31;padding-bottom:10px;margin-bottom:18px}
header b{font-size:1.05rem}h1{font-size:1.7rem;margin:.2rem 0 .3rem;letter-spacing:-.02em}h2{font-size:1.1rem;margin:1.6rem 0 .5rem}
.muted{color:#5b6266}.warn{background:#fff5e0;border:1px solid #f0cf8a;color:#4a3a1a;padding:10px 14px;border-radius:10px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:6px 8px;border-bottom:1px solid #e3e6e7;text-align:left}th{font-size:.82rem;color:#5b6266}
.n{text-align:right}tr.rec td{background:#e3f1ef}.tag{font-size:.7rem;font-weight:700;color:#0b6e69;text-transform:uppercase}
.fits{color:#1f6b3a;font-weight:600}.tight{color:#a3221a;font-weight:600}.loose{color:#2b5c88;font-weight:600}
.kv td:first-child{color:#4b5357}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:0}img{width:100%;border:1px solid #d6dbdd;border-radius:10px}
figcaption{font-size:.8rem;color:#5b6266}dl{display:grid;grid-template-columns:auto 1fr;gap:4px 16px}dt{color:#5b6266}dd{margin:0;font-weight:600}
footer{margin-top:28px;border-top:1px solid #d6dbdd;padding-top:10px;font-size:.8rem;color:#5b6266}
@media print{body{padding:0}.noprint{display:none}h2{break-after:avoid}figure,table{break-inside:avoid}}
</style></head><body>
<header><b>SenseCraft · FreshCuff ScanMade</b><span class="muted">${esc(date)}</span></header>
<h1>${esc(t('rep_title'))}</h1>
<p class="muted">${esc(t('rep_generated', { d: date }))} <span class="noprint">· ${esc(t('rep_print'))}: Ctrl/⌘ + P</span></p>
<p class="warn">${esc(t('rep_disclaimer'))}</p>
<h2>${esc(t('rep_scan'))}</h2>
<dl><dt>${esc(t('rep_scan'))}</dt><dd>${esc(scanName || '')}${prep?.scan?.faces ? ' · ' + esc(t('faces', { n: Number(prep.scan.faces).toLocaleString() })) : ''}</dd>
<dt>${esc(t('rep_hand'))}</dt><dd>${esc(sideTxt)}</dd>
<dt>${esc(t('rep_quality'))}</dt><dd>${Number.isFinite(q.score) ? Math.round(q.score) + ' / 100' : '—'}</dd>
<dt>${esc(t('rep_overrides'))}</dt><dd>${ovr.length ? esc(ovr.join(' · ')) : esc(t('rep_none'))}</dd></dl>
<div class="grid">${img(snaps?.check, t('step_check'))}${img(snaps?.fit, t('legend_title'))}</div>
${recHtml}
<h2>${esc(t('sizes_title'))}</h2>
<table><thead><tr><th>${esc(t('th_size'))}</th><th>${esc(t('th_fit'))}</th><th class="n">${esc(t('th_min'))}</th><th class="n">${esc(t('th_back'))}</th><th class="n">${esc(t('th_sides'))}</th></tr></thead><tbody>${rows}</tbody></table>
<p class="muted">${esc(t('sizes_caption'))}</p>
${buildHtml}
${snaps?.result ? `<div class="grid">${img(snaps.result, t('label_cuff'))}${img(snaps.resultSide, t('view_side'))}</div>` : ''}
${fileList ? `<h2>${esc(t('rep_files'))}</h2><ul>${fileList}</ul>` : ''}
${build ? `<h2>${esc(t('print_title'))}</h2><ol>${['print_1', 'print_2', 'print_3', 'print_4', 'print_5'].map(k => `<li>${esc(t(k))}</li>`).join('')}</ol>` : ''}
<footer>SenseCraft · FreshCuff ScanMade · ${esc(t('footer_license'))} · ${esc(t('footer_sample'))}${timings ? ' · ' + esc(Object.entries(timings).filter(([, v]) => Number.isFinite(v)).map(([k, v]) => `${k} ${(v / 1000).toFixed(1)} s`).join(', ')) : ''}</footer>
</body></html>`;
}
