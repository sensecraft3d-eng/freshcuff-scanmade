# -*- coding: utf-8 -*-
"""FreshCuff Fit - standalone printable report (one HTML file, inline CSS + inline SVG, no external assets).

    render(report_dict, lang='en') -> str        report_dict = the content of build_NN/report.json
    python report_html.py report.json out.html
"""
import html
import json
import sys

_T = {
    'en': dict(title='FreshCuff Fit report', ready='Cuff ready', stopped='Stopped - no cuff released',
               scan='Scan', hand='Hand', sizes='Standard sizes (rigid geometric fit of the 26 mm band)',
               size='Size', fits='Fits', yes='yes', no='no', rigid='Rigid min (mm)', dorsal='Under spring min (mm)',
               lateral='Side min (mm)', note='Note', custom='Custom cuff', range='Custom range W 80-84 mm',
               sections='The 5 sections of the band in the seated position',
               sec_cap='Grey dashed: standard opening. Teal: your opening (spring face lowered). Brown: your hand. '
                       'Back of the hand up; thumb side left.',
               profile='Personal profile of the spring face', prof_cap='Blue: gap under the standard spring face (closest section). '
                       'Teal: how much the face is lowered (up to 3 mm).',
               locks='Manufacturing checks on the generated solid', check='Check', value='Value', limit='Limit', ok='OK', fail='FAIL',
               verify='Generated cuff re-checked against the scan', prov='Provenance', files='Files', msgs='Messages',
               knuckles='from knuckle line', recommended='recommended', by_tape='by tape',
               legend_neg='negative = presses into the hand', print='Print / save as PDF'),
    'pt': dict(title='Relatório FreshCuff Fit', ready='Cuff pronto', stopped='Barrado - nenhum cuff liberado',
               scan='Scan', hand='Mão', sizes='Tamanhos padrão (encaixe geométrico rígido da faixa de 26 mm)',
               size='Tamanho', fits='Serve', yes='sim', no='não', rigid='Rígido mín (mm)', dorsal='Sob a mola mín (mm)',
               lateral='Lateral mín (mm)', note='Nota', custom='Cuff sob medida', range='Faixa sob medida W 80-84 mm',
               sections='Os 5 cortes da faixa na posição assentada',
               sec_cap='Cinza tracejado: abertura padrão. Verde-azulado: a sua abertura (face da mola abaixada). Marrom: a sua mão. '
                       'Dorso para cima; polegar à esquerda.',
               profile='Perfil pessoal da face da mola', prof_cap='Azul: folga sob a face padrão (corte mais próximo). '
                       'Verde-azulado: quanto a face é abaixada (até 3 mm).',
               locks='Travas de fabricação no sólido gerado', check='Trava', value='Valor', limit='Limite', ok='OK', fail='FALHA',
               verify='Cuff gerado conferido contra o scan', prov='Proveniência', files='Arquivos', msgs='Mensagens',
               knuckles='da linha dos nós', recommended='recomendado', by_tape='pela fita',
               legend_neg='negativo = invade a mão', print='Imprimir / salvar em PDF'),
}
_CSS = """
body{font:14px/1.45 system-ui,-apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#1c2526;margin:0;background:#f4f6f6}
main{max-width:980px;margin:0 auto;padding:24px;background:#fff}
h1{font-size:24px;margin:0 0 4px} h2{font-size:17px;margin:26px 0 8px;border-bottom:2px solid #116c69;padding-bottom:3px}
.badge{display:inline-block;padding:3px 12px;border-radius:14px;color:#fff;font-weight:600}
.ok{background:#1f7a3a}.bad{background:#b3261e} .muted{color:#5b6b6c;font-size:12.5px}
table{border-collapse:collapse;width:100%;margin:6px 0} th,td{border-bottom:1px solid #d9e0e0;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#eef3f3;font-weight:600} td.n{text-align:right;font-variant-numeric:tabular-nums}
tr.rec td{background:#e3f3f1;font-weight:600} .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:10px}
figure{margin:0;border:1px solid #d9e0e0;border-radius:6px;padding:6px} figcaption{font-size:12px;color:#5b6b6c}
svg{width:100%;height:auto;display:block} code{font-size:11.5px;word-break:break-all}
.kv{display:grid;grid-template-columns:230px 1fr;gap:2px 12px} .kv div:nth-child(odd){color:#5b6b6c}
ul{margin:4px 0;padding-left:20px} li.warn{color:#8a5a00} li.error{color:#b3261e}
button{font:inherit;padding:6px 14px;border:1px solid #116c69;background:#116c69;color:#fff;border-radius:6px;cursor:pointer}
@media print{body{background:#fff}main{padding:0;max-width:none}button{display:none}h2{break-after:avoid}figure,table{break-inside:avoid}}
"""


def _e(x):
    return html.escape(str(x))


def _f(x, nd=2, sign=False):
    if x is None:
        return '-'
    try:
        return ('%+.*f' if sign else '%.*f') % (nd, float(x))
    except Exception:
        return _e(x)


def _path(pts, sx, sy, close=True):
    if not pts:
        return ''
    d = 'M' + ' L'.join('%.2f,%.2f' % (sx(p[0]), sy(p[1])) for p in pts)
    return d + (' Z' if close else '')


def _section_svg(sec, t):
    allp = sec['opening_standard'] + sec['hand']
    xs = [p[0] for p in allp]
    ys = [p[1] for p in allp]
    x0, x1, y0, y1 = min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3
    k = 6.0
    w, h = (x1 - x0) * k, (y1 - y0) * k
    sx = lambda x: (x - x0) * k
    sy = lambda y: (y1 - y) * k
    g = ['<svg viewBox="0 0 %.0f %.0f" role="img" aria-label="section %.1f mm">' % (w, h, sec['distance_from_knuckles_mm'])]
    g.append('<path d="%s" fill="#f0d9cb" stroke="#9a5a3a" stroke-width="1.6"/>' % _path(sec['hand'], sx, sy))
    g.append('<path d="%s" fill="none" stroke="#8a9494" stroke-width="1.4" stroke-dasharray="6 4"/>' % _path(sec['opening_standard'], sx, sy))
    g.append('<path d="%s" fill="none" stroke="#116c69" stroke-width="2.2"/>' % _path(sec['opening_custom'], sx, sy))
    g.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#1c2526" stroke-width="1.5"/>' % (sx(x0 + 4), h - 8, sx(x0 + 14), h - 8))
    g.append('<text x="%.1f" y="%.1f" font-size="13" fill="#1c2526">10 mm</text>' % (sx(x0 + 16), h - 4))
    g.append('</svg>')
    return '<figure>%s<figcaption>%s mm %s</figcaption></figure>' % (''.join(g), _f(sec['distance_from_knuckles_mm'], 1), _e(t['knuckles']))


def _profile_svg(prof):
    X, gap, low = prof['x_mm'], prof['gap_before_mm'], prof['lowering_mm']
    pts_g = [(x, g) for x, g in zip(X, gap) if g is not None]
    pts_l = [(x, l) for x, l in zip(X, low)]
    ymax = max([3.2] + [p[1] for p in pts_g]) + 0.3
    ymin = min([0.0] + [p[1] for p in pts_g]) - 0.3
    W, H, m = 640.0, 220.0, 34.0
    sx = lambda x: m + (x - X[0]) / (X[-1] - X[0]) * (W - 2 * m)
    sy = lambda y: H - m + (y - ymin) / (ymax - ymin) * (2 * m - H)
    g = ['<svg viewBox="0 0 %d %d" role="img" aria-label="dorsal profile">' % (W, H)]
    for yv in range(int(ymin), int(ymax) + 1):
        g.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1"/>' % (m, sy(yv), W - m, sy(yv), '#1c2526' if yv == 0 else '#d9e0e0'))
        g.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="end" fill="#5b6b6c">%d</text>' % (m - 4, sy(yv) + 4, yv))
    for xv in range(-20, 21, 10):
        g.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="middle" fill="#5b6b6c">%d</text>' % (sx(xv), H - m + 14, xv))
    g.append('<text x="%.1f" y="%.1f" font-size="11" text-anchor="middle" fill="#5b6b6c">x (mm): thumb side &#8592; &#8594; little-finger side</text>' % (W / 2, H - 4))
    g.append('<path d="%s" fill="none" stroke="#2f6fb0" stroke-width="2"/>' % _path(pts_g, sx, sy, False))
    g.append('<path d="%s" fill="none" stroke="#116c69" stroke-width="2.4"/>' % _path(pts_l, sx, sy, False))
    g.append('</svg>')
    return ''.join(g)


def render(rep, lang='en'):
    t = _T.get(lang, _T['en'])
    an = rep.get('analysis') or {}
    cu = an.get('custom') or {}
    ok = rep.get('status') == 'cuff_ready'
    o = ['<!doctype html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
         '<title>%s</title><style>%s</style></head><body><main>' % (_e(lang), _e(t['title']), _CSS)]
    o.append('<h1>%s</h1><p><span class="badge %s">%s</span> &nbsp; <button onclick="window.print()">%s</button></p>'
             % (_e(t['title']), 'ok' if ok else 'bad', _e(t['ready'] if ok else t['stopped']), _e(t['print'])))
    o.append('<p class="muted">%s</p>' % _e(rep.get('notice', '')))
    sc, lm = rep.get('scan') or {}, rep.get('landmarks') or {}
    o.append('<h2>%s / %s</h2><div class="kv">' % (_e(t['scan']), _e(t['hand'])))
    rows = [('File', sc.get('file')), ('Triangles', sc.get('faces')), ('Units', '%s (x%s mm)' % (sc.get('units'), sc.get('mm_per_unit'))),
            ('Hand side', lm.get('side')), ('Around the knuckles (scan)', '%s cm' % _f(lm.get('knuckle_circumference_cm'), 1)),
            ('Tape measurement', '%s cm' % _f(rep.get('tape_cm'), 1) if rep.get('tape_cm') is not None else 'not given'),
            ('Knuckle width x thickness', '%s x %s mm' % (_f(lm.get('knuckle_width_mm'), 1), _f(lm.get('knuckle_thickness_mm'), 1))),
            ('Landmarks', 'found automatically' if lm.get('found_automatically') else 'set or confirmed by hand')]
    for k, v in rows:
        o.append('<div>%s</div><div>%s</div>' % (_e(k), _e(v)))
    o.append('</div>')
    if cu:
        p = cu.get('predicted') or {}
        o.append('<h2>%s</h2><div class="kv">' % _e(t['custom']))
        for k, v in [('Opening width W', '%s mm (%s hand, base variant %s)' % (_f(cu.get('W'), 1), cu.get('side'), cu.get('variant'))),
                     ('Spring face lowered up to', '%s mm' % _f(-(cu.get('dorsal_profile_mm_min') or 0))),
                     ('Gap under the spring, closest section (mean)', '%s mm standard face -> %s mm personal profile' % (_f(p.get('closest_section_gap_before')), _f(p.get('after')))),
                     ('Width within 0.5 mm of the spring', '%s %%' % _f(100 * (p.get('share_le_0p5') or 0), 0)),
                     ('Largest predicted overlap', '%s mm (spring travel %s mm)' % (_f(p.get('max_overlap')), _f(cu.get('spring_travel_mm'), 1))),
                     ('Side clearance / palm compression', '%s mm / %s mm' % (_f(cu.get('lateral_clearance_mm')), _f(cu.get('palm_compression_mm'))))]:
            o.append('<div>%s</div><div>%s</div>' % (_e(k), _e(v)))
        o.append('</div>')
    if an.get('sections'):
        o.append('<h2>%s</h2><div class="grid">%s</div><p class="muted">%s</p>'
                 % (_e(t['sections']), ''.join(_section_svg(s, t) for s in an['sections']), _e(t['sec_cap'])))
    if cu.get('profile'):
        o.append('<h2>%s</h2><figure>%s<figcaption>%s</figcaption></figure>' % (_e(t['profile']), _profile_svg(cu['profile']), _e(t['prof_cap'])))
    if an.get('sizes'):
        o.append('<h2>%s</h2><table><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>'
                 % tuple(_e(t[k]) for k in ('sizes', 'size', 'fits', 'rigid', 'dorsal', 'lateral', 'note')))
        for s in an['sizes']:
            tag = []
            if s['size'] == an.get('recommended_size'): tag.append(t['recommended'])
            if s['size'] == an.get('size_by_tape'): tag.append(t['by_tape'])
            o.append('<tr%s><td>%d%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td><td>%s</td></tr>'
                     % (' class="rec"' if s['size'] == an.get('recommended_size') else '', s['size'],
                        (' (' + _e(', '.join(tag)) + ')') if tag else '', _e(t['yes'] if s['fits'] else t['no']),
                        _f(s['rigid_min'], 2, True), _f(s['dorsal_min'], 2, True), _f(s['lateral_min'], 2, True), _e(s['note'])))
        o.append('</table><p class="muted">%s</p>' % _e(t['legend_neg']))
    if an.get('custom_range'):
        o.append('<h2>%s</h2><table><tr><th>W (mm)</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>'
                 % tuple(_e(t[k]) for k in ('range', 'fits', 'rigid', 'dorsal', 'lateral')))
        for g in an['custom_range']:
            o.append('<tr%s><td>%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td><td class="n">%s</td></tr>'
                     % (' class="rec"' if cu and abs(g['W'] - cu.get('W', -1)) < 1e-6 else '', _f(g['W'], 1), _e(t['yes'] if g['fits'] else t['no']),
                        _f(g['rigid_min'], 2, True), _f(g['dorsal_min'], 2, True), _f(g['lateral_min'], 2, True)))
        o.append('</table>')
    lk = rep.get('locks')
    if lk:
        o.append('<h2>%s</h2><table><tr><th>%s</th><th>%s</th><th>%s</th><th></th></tr>' % tuple(_e(t[k]) for k in ('locks', 'check', 'value', 'limit')))
        for c in lk['checks']:
            v = c.get('value')
            o.append('<tr><td>%s</td><td class="n">%s</td><td>%s %s</td><td><b style="color:%s">%s</b></td></tr>'
                     % (_e(c['name']), _f(v, 3) if isinstance(v, float) else _e('-' if v is None else v), _e(c['limit']), _e(c['unit']),
                        '#1f7a3a' if c['ok'] else '#b3261e', _e(t['ok'] if c['ok'] else t['fail'])))
        o.append('</table>')
    vf = rep.get('verification')
    if vf:
        sp, lim = vf.get('same_pose') or {}, vf.get('limits') or {}
        o.append('<h2>%s</h2><p><span class="badge %s">%s</span></p><div class="kv">' % (_e(t['verify']), 'ok' if vf.get('verdict') == 'approved' else 'bad', _e(vf.get('verdict'))))
        for k, v in [('Gap under the spring on the generated solid', '%s mm (prediction differs by %s mm; limit %s)' % (_f(sp.get('closest_section_gap')), _f(vf.get('gap_difference_mm'), 3, True), _f(lim.get('gap_difference_mm')))),
                     ('Largest overlap', '%s mm (limit %s)' % (_f(sp.get('max_overlap')), _f(lim.get('spring_travel_mm'), 1))),
                     ('Rigid minimum', '%s mm (limit %s)' % (_f(sp.get('rigid_min'), 2, True), _f(lim.get('rigid_min_mm'), 1, True))),
                     ('Side clearance', '%s mm (minimum %s)' % (_f(sp.get('lateral_min')), _f(lim.get('lateral_min_mm')))),
                     ('Hand seats in the generated opening (free search)', (vf.get('free_pose') or {}).get('seats'))]:
            o.append('<div>%s</div><div>%s</div>' % (_e(k), _e(v)))
        o.append('</div>')
        if vf.get('failures'):
            o.append('<ul>%s</ul>' % ''.join('<li class="error">%s</li>' % _e(x) for x in vf['failures']))
    if rep.get('messages'):
        o.append('<h2>%s</h2><ul>%s</ul>' % (_e(t['msgs']), ''.join('<li class="%s">%s</li>' % (_e(m.get('level')), _e(m.get('text'))) for m in rep['messages'])))
    out = rep.get('outputs') or {}
    o.append('<h2>%s</h2><div class="kv">' % _e(t['prov']))
    for k, v in [('Tool', rep.get('tool')), ('Scan sha256', sc.get('sha256')), ('Base variant', '%s  %s' % ((rep.get('variant') or {}).get('id'), (rep.get('variant') or {}).get('sha256'))),
                 ('STL', '%s  %s' % (out.get('stl'), out.get('stl_sha256'))), ('3MF', '%s  %s' % (out.get('3mf', '-'), out.get('3mf_sha256', '-'))),
                 ('Environment', json.dumps(rep.get('environment')))]:
        o.append('<div>%s</div><div><code>%s</code></div>' % (_e(k), _e(v)))
    o.append('</div><p class="muted">Program and data hashes are in report.json.</p></main></body></html>')
    return ''.join(o)


if __name__ == '__main__':
    rep = json.loads(open(sys.argv[1], encoding='utf8').read())
    open(sys.argv[2], 'w', encoding='utf8').write(render(rep, sys.argv[3] if len(sys.argv) > 3 else 'en'))
