#!/usr/bin/env python3
"""FreshCuff ScanMade - command line.  Runs the same functions as the web page (web/py/fc_api.py), locally.

    python fc_cli.py scan.ply --out result_dir [--side left|right|auto] [--tape-cm 18.2] [--build]

Examples
    python fc_cli.py examples/Artec_Hand.ply --out out/artec --side left --tape-cm 18.2 --build
    python fc_cli.py hand.stl --out out/hand --dorsum flip          # the back of the hand was read upside down
    python fc_cli.py hand.obj --out out/hand --mm-per-unit 25.4     # a scan saved in inches

Exit code: 0 = finished (see the status), 2 = needs your input (ambiguous orientation), 3 = refused / stopped.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / 'web' / 'py'))


def _print_messages(msgs):
    mark = {'info': '  -', 'warn': '  !', 'error': '  X'}
    for m in msgs:
        print(mark.get(m['level'], '  -'), m['text'])


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description='FreshCuff ScanMade: hand scan -> size recommendation and custom cuff (3MF).',
                                 epilog='The scan is processed on this computer only. Experimental; always dry-fit. Not a medical device.')
    ap.add_argument('scan', help='hand scan: STL, OBJ, PLY or GLB')
    ap.add_argument('--out', required=True, help='output folder (created if needed)')
    ap.add_argument('--side', choices=['auto', 'left', 'right'], default='auto', help='which hand was scanned (default: detect)')
    ap.add_argument('--tape-cm', type=float, default=None, help='tape measure around the knuckles, cm: the independent scale check (required with --build)')
    ap.add_argument('--mm-per-unit', type=float, default=None, help='force the scan units (1 = mm, 10 = cm, 1000 = m, 25.4 = inch)')
    ap.add_argument('--dorsum', choices=['auto', 'keep', 'flip'], default='auto', help='back of the hand: keep or flip the +y side of the scan axis frame')
    ap.add_argument('--fingers', choices=['auto', 'high', 'low'], default='auto', help='which end of the long axis has the fingers')
    ap.add_argument('--knuckle-s', type=float, default=None, help='knuckle line position on the scan axis (see landmarks.knuckle_s)')
    ap.add_argument('--thumb-s', type=float, default=None, help='thumb base position on the scan axis')
    ap.add_argument('--band-shift-mm', type=float, default=0.0, help='move the band toward the wrist (+) or the fingers (-)')
    ap.add_argument('--build', action='store_true', help='also build the custom cuff (STL, 3MF, report)')
    ap.add_argument('--grid', default=str(REPO / 'web' / 'grade'), help='folder with the width variants (default: web/grade)')
    ap.add_argument('--data', default=str(REPO / 'web' / 'dados'), help='data folder (default: web/dados)')
    ap.add_argument('--lang', choices=['en', 'pt'], default='en')
    ap.add_argument('--json', action='store_true', help='print the raw JSON results instead of the summary')
    ap.add_argument('--quiet', action='store_true', help='no progress lines')
    a = ap.parse_args(argv)

    import fc_api as A
    prog = (lambda s: None) if (a.quiet or a.json) else (lambda s: print('...', s, flush=True))
    opts = {'side': a.side, 'tape_cm': a.tape_cm, 'mm_per_unit': a.mm_per_unit, 'lang': a.lang, 'data_dir': a.data,
            'dorsum': a.dorsum, 'fingers': a.fingers, 'knuckle_s': a.knuckle_s, 'thumb_s': a.thumb_s, 'band_shift_mm': a.band_shift_mm}
    if not Path(a.scan).exists():
        ap.error('scan file not found: ' + a.scan)
    if a.build and a.tape_cm is None:
        ap.error('--build requires --tape-cm: no manufacturing file is released without the tape measurement that confirms the scale')
    results = {}
    p = results['prepare'] = A.prepare(a.scan, a.out, opts, progress=prog)
    code = 0
    if not a.json:
        sc = p.get('scan')
        print('\nSCAN', Path(a.scan).name)
        if sc:
            print('  %d triangles, %s, %.0f x %.0f x %.0f mm, quality %s/100' % (
                sc['faces'], sc['units_guess'], *sorted(sc['extent_mm'], reverse=True), sc.get('quality', {}).get('score', '?')))
            for n in sc.get('quality', {}).get('notes', []):
                print('    ', n)
        lm = p.get('landmarks')
        if lm:
            print('HAND  %s hand (confidence %.0f%%), fingers at the %s end, back of hand %s (confidence %.0f%%)' % (
                lm['side'] or 'unknown', 100 * lm['side_confidence'], lm['fingers_end'], lm['dorsum'], 100 * lm['dorsum_confidence']))
            print('      around the knuckles %.1f cm, width %.1f mm; knuckle_s = %.1f%s' % (
                lm['knuckle_circumference_cm'], lm['knuckle_width_mm'], lm['knuckle_s'],
                '' if lm['thumb_s'] is None else ', thumb_s = %.1f' % lm['thumb_s']))
        _print_messages(p['messages'])
        print('  preview:', Path(a.out) / 'preview.glb' if p.get('preview_glb') else '-')
    if p['status'] == 'refused':
        code = 3
    else:
        an = results['analyze'] = A.analyze(a.out, {}, progress=prog)
        if not a.json:
            print('\nANALYSIS  status:', an['status'])
            if an['status'] == 'needs_input':
                for amb in an['landmarks']['ambiguities']:
                    print('  ?', amb['message'])
                    for c in amb['candidates']:
                        flags = ' '.join('--%s %s' % (k.replace('_', '-'), v) for k, v in c['overrides'].items())
                        print('      %s %s   ->  add: %s' % ('(my guess)' if c.get('is_guess') else '          ', c['label'], flags))
            if an['sizes']:
                print('  Standard sizes (rigid fit of the 26 mm band):')
                print('    size  fits  rigid   spring  side    note')
                for s in an['sizes']:
                    print('    %s %d   %-4s %+6.2f  %+6.2f  %+6.2f  %s' % ('>' if s['size'] == an['recommended_size'] else ' ', s['size'], 'yes' if s['fits'] else 'no',
                                                                          s['rigid_min'], s['dorsal_min'], s['lateral_min'], s['note']))
                rec = an['recommended_size']
                print('  Recommended standard size: %s   (estimate by circumference alone: size %s, %s)' % (
                    rec if rec is not None else 'none - no standard size passed the geometric check', an['size_by_tape'],
                    'tape' if an.get('size_by_tape_source') == 'tape' else 'measured on the scan'))
            cu = an.get('custom')
            if cu:
                pr = cu['predicted']
                print('  Custom cuff: W %.1f mm, %s hand (base %s); spring face lowered up to %.2f mm' % (cu['W'], cu['side'], cu['variant'], -cu['dorsal_profile_mm_min']))
                print('    gap under the spring %.2f -> %.2f mm, %.0f%% of the width within 0.5 mm, max overlap %.2f mm' % (
                    pr['closest_section_gap_before'], pr['after'], 100 * pr['share_le_0p5'], pr['max_overlap']))
            _print_messages(an['messages'])
            print('  3D result:', Path(a.out) / 'analysis.glb' if an.get('result_glb') else '-')
        if an['status'] == 'needs_input':
            code = 2
        elif an['status'] == 'refused':
            code = 3
        elif an['status'] == 'custom_ready' and a.build:
            b = results['build'] = A.build(a.out, a.grid, a.data, progress=prog)
            if not a.json:
                print('\nBUILD  status:', b['status'])
                if b.get('locks'):
                    for c in b['locks']['checks']:
                        v = c['value']
                        print('    [%s] %-40s %s %s' % ('ok' if c['ok'] else 'FAIL', c['name'], ('%.3f' % v) if isinstance(v, float) else ('' if v is None else v), c['limit']))
                if b.get('verification'):
                    v = b['verification']
                    print('  Verification against the scan: %s (gap difference %+.3f mm)' % (v['verdict'], v['gap_difference_mm'] or 0))
                _print_messages(b['messages'])
                for k, f in b['files'].items():
                    print('  %-12s %s' % (k, Path(a.out) / f))
            if b['status'] != 'cuff_ready':
                code = 3
        elif a.build and not a.json:
            print('\nBUILD skipped: no custom cuff released (status %s).' % an['status'])
    if a.json:
        print(json.dumps(results, indent=1))
    A.release()
    return code


if __name__ == '__main__':
    sys.exit(main())
