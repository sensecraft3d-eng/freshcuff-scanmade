# -*- coding: utf-8 -*-
"""FreshCuff ScanMade - public API (English, JSON-serialisable results).  Same code in CPython and in Pyodide.

    prepare(scan_path, work_dir, opts)      -> read the scan, orient it, find the band; preview.glb
    analyze(work_dir, overrides)            -> 7 standard sizes + custom cuff parameters; analysis.glb
    build(work_dir, grid_dir, data_dir)     -> solid, manufacturing checks, 3MF, verification, report; result.glb

All paths in the results are relative to ``work_dir``.  See CORE_STATUS.md for the full contract.
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fc_core as C          # noqa: E402
import fc_mesh as M          # noqa: E402
import fc_fastfit as FF      # noqa: E402
import freshcuff_fit as F    # noqa: E402
from fc_strings import Messages, tr   # noqa: E402

API_VERSION = '1.0'
SCAN_LIMIT_MB = 150
DISPLAY_FACES = 80000
OVERRIDE_KEYS = ('side', 'dorsum', 'fingers', 'knuckle_s', 'thumb_s', 'knuckle_z', 'thumb_z', 'band_shift_mm', 'tape_cm')
_CACHE = {}          # work_dir -> in-memory session (mesh, readings); rebuilt from disk when missing


# ---------------------------------------------------------------------------------------------- helpers
def _clean(o):
    """Make a structure JSON-serialisable (numpy scalars/arrays, non-finite floats -> None)."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items() if not str(k).startswith('_')}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        o = float(o)
        return o if math.isfinite(o) else None
    return o


def _state_path(work):
    return Path(work) / 'fc_state.json'


def _load_state(work):
    p = _state_path(work)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf8'))


def _save_state(work, st):
    _state_path(work).write_text(json.dumps(_clean(st), indent=1), encoding='utf8')


def _session(work):
    key = str(Path(work).resolve())
    ses = _CACHE.get(key)
    if ses is None:
        f = Path(work) / 'fc_scan.npz'
        if not f.exists():
            return None
        d = np.load(f)
        ses = {'Vp': d['Vp'], 'F': d['F'], 'bv': d['bv'], 'nv': d['nv'] if 'nv' in d else np.zeros((0, 3)),
               'Vd': d['Vd'], 'Fd': d['Fd'], 'readings': {}}
        _CACHE[key] = ses
    return ses


def release(work_dir=None):
    """Free the in-memory meshes (all sessions, or one)."""
    import gc
    if work_dir is None:
        _CACHE.clear()
    else:
        _CACHE.pop(str(Path(work_dir).resolve()), None)
    F._INTERNO = None
    gc.collect()


def _ov_from(opts, st):
    """Normalise overrides.  knuckle_z / thumb_z (view coordinates of the latest GLB) become knuckle_s / thumb_s."""
    ov = {'side': opts.get('side') or 'auto', 'dorsum': opts.get('dorsum') or 'auto', 'fingers': opts.get('fingers') or 'auto',
          'knuckle_s': opts.get('knuckle_s'), 'thumb_s': opts.get('thumb_s'),
          'band_shift_mm': float(opts.get('band_shift_mm') or 0.0)}
    if ov['side'] not in ('auto', 'left', 'right'): raise ValueError("side must be 'auto', 'left' or 'right'")
    if ov['dorsum'] not in ('auto', 'keep', 'flip'): raise ValueError("dorsum must be 'auto', 'keep' or 'flip'")
    if ov['fingers'] not in ('auto', 'high', 'low'): raise ValueError("fingers must be 'auto', 'high' or 'low'")
    if not (math.isfinite(ov['band_shift_mm']) and abs(ov['band_shift_mm']) <= 15): raise ValueError('band_shift_mm must be within +-15 mm')
    view = (st or {}).get('view')
    memo = (st or {}).setdefault('view_memo', {}) if st is not None else {}
    for kz, ks in (('knuckle_z', 'knuckle_s'), ('thumb_z', 'thumb_s')):
        v = opts.get(kz)
        if v is not None and ov[ks] is None:
            v = float(v)
            m = memo.get(kz)
            if m and abs(m[0] - v) < 1e-9:           # same click sent again: do not re-interpret in the new frame
                ov[ks] = m[1]
            elif view:
                ov[ks] = view['a'] * v + view['b']
                memo[kz] = [v, ov[ks]]
    for ks in ('knuckle_s', 'thumb_s'):
        if ov[ks] is not None:
            ov[ks] = float(ov[ks])
            if not math.isfinite(ov[ks]): raise ValueError(ks + ' must be finite')
    return ov


def _ov_key(ov):
    return json.dumps(ov, sort_keys=True)


def _reading(ses, ov, lang):
    key = _ov_key(ov) + lang
    rd = ses['readings'].get(key)
    if rd is None:
        ses['readings'].clear()                       # one reading in memory at a time
        ses.pop('an_cache', None)
        rd = C.read_hand(ses['Vp'], ses['F'], ov, lang)
        ses['readings'][key] = rd
    return rd


def _quality(info, rd, near, n_boundary, nonmanifold, lang, band_edge=None, near_nm=0):
    T = lambda k, **kw: tr(k, lang, **kw)
    score, notes = 100.0, []
    if band_edge is not None:
        if band_edge <= 1.0: notes.append(T('q_density_fine', mm=band_edge))
        elif band_edge <= 2.5: notes.append(T('q_density_ok', mm=band_edge)); score -= 10 * (band_edge - 1.0) / 1.5
        else: notes.append(T('q_density_coarse', mm=band_edge)); score -= min(40, 10 + 10 * (band_edge - 2.5))
    if n_boundary == 0:
        notes.append(T('q_closed'))
    elif near:
        notes.append(T('q_open_near', n=near)); score -= 50
    else:
        notes.append(T('q_open_far', n=n_boundary)); score -= 3
    if info['components'] > 1:
        notes.append(T('q_components', n=info['components'], kept=info['components_kept'])); score -= 5
    else:
        notes.append(T('q_one_piece'))
    notes.append(T('q_units', units=info['units_guess'], c=100 * info['units_confidence']))
    score -= 30 * (1 - info['units_confidence'])
    if near_nm:
        notes.append(T('q_nonmanifold_near', n=near_nm)); score -= 50
    elif nonmanifold > 20:
        notes.append(T('q_nonmanifold', n=nonmanifold)); score -= 5
    if rd is not None:
        if rd.frac_open > 0.02:
            notes.append(T('q_sections_open', pct=100 * rd.frac_open)); score -= 40 * rd.frac_open
        if rd.amb or rd.dorsum_manual or rd.fingers_manual or rd.knuckle_manual:
            notes.append(T('q_orientation')); score -= 10
        else:
            notes.append(T('q_landmarks_ok'))
        if rd.gaps or not rd.complete:
            score -= 20
        if rd.drift > 8:
            score -= 10
    else:
        notes = [n for n in notes if n not in (T('q_open_far', n=n_boundary), T('q_closed'))]
        notes.insert(0, T('q_sections_open', pct=100))
        score = min(score - 50, 15)
    return {'score': int(round(max(0.0, min(100.0, score)))), 'notes': notes}


def _band_edge_length(ses, rd):
    """Mean triangle edge (mm) of the scan inside the band slab."""
    S = rd.S
    zs = [e['z'] for e in rd.stations]
    idx = S.faces_between(min(zs), max(zs))
    if len(idx) == 0:
        return None
    tri = S.V[S.F[idx]]
    e = np.linalg.norm(tri[:, 0] - tri[:, 1], axis=1)
    return float(np.median(e))


def _landmarks(rd, lang):
    sz = rd.flips[2]
    thumb_view = None if rd.z_pol is None else rd.z_nos - 12.8 - rd.z_pol
    return {'side': rd.side, 'side_confidence': round(rd.side_conf, 2),
            'fingers_end': 'high' if rd.fingers_high else 'low', 'fingers_confidence': round(rd.fingers_conf, 2),
            'dorsum': 'kept' if rd.dorsum_plus else 'flipped', 'dorsum_confidence': round(rd.dorsum_conf, 2),
            'knuckle_z': C.Z_KNUCKLE_VIEW, 'thumb_z': thumb_view, 'band': {'z0': -13.0, 'z1': 13.0},
            'knuckle_s': sz * rd.z_nos, 'thumb_s': None if rd.z_pol is None else sz * rd.z_pol,
            'knuckle_circumference_cm': round(rd.tape_scan_cm, 2), 'knuckle_width_mm': round(rd.width_mm, 1),
            'knuckle_thickness_mm': round(rd.thickness_mm, 1), 'found_automatically': bool(rd.landmarks_auto),
            'clues': dict(rd.clues, knuckle_arch_mm=[round(v, 2) for v in rd.arch],
                          finger_curl_mm=None if rd.curl_mm is None else round(rd.curl_mm, 1),
                          finger_pieces_low_high=list(rd.fingers_counts)),
            'ambiguities': rd.amb}


def _overlays(rd, Mx):
    Mfv = C.fit_to_view(rd, Mx)
    ov = {'knuckle_line': [C.apply(Mfv, C.ring3(rd.nos.exterior.coords, rd.z_nos))],
          'band': [C.apply(Mfv, C.ring3(e['poligono'].exterior.coords, e['z'])) for e in rd.stations if 'poligono' in e],
          'thumb': []}
    if rd.thumb_ring is not None:
        ov['thumb'] = [C.apply(Mfv, C.ring3(rd.thumb_ring[1], rd.thumb_ring[0]))]
    return ov


def _frame(rd, Mx, st):
    sz = rd.flips[2]
    a, b = -sz, sz * (rd.z_nos - 12.8)
    Ms = np.eye(4)
    R, c, k = np.array(st['frame']['R']), np.array(st['frame']['centre_mm']), st['frame']['mm_per_unit']
    Ms[:3, :3] = R * k
    Ms[:3, 3] = -R @ c
    st['view'] = {'a': a, 'b': b}
    return {'axis_to_view': Mx, 'scan_to_view': Mx @ Ms, 'view_to_axis_z': {'a': a, 'b': b},
            'note': 'view frame: +y back of hand, +z wrist, band centre z=0; s = a*z_view + b is the stable scan-axis coordinate for knuckle_s / thumb_s'}


def _write_glb(path, ses, Mx, colors=None, lines=None, extra=None):
    nodes = [dict(name='hand', kind='mesh', V=C.apply(Mx, ses['Vd']), F=ses['Fd'], colors=colors, rgb=C.SKIN_RGB)]
    for nd in (extra or []):
        nodes.append(nd)
    for name, rings, rgb in (lines or []):
        if rings:
            nodes.append(dict(name=name, kind='lines', rings=rings, rgb=rgb))
    return M.export_glb(path, nodes)


def _legend():
    return [{'mm': m, 'rgb': list(c)} for m, c in C.LEGEND]


def _notes_to(msgs, notes):
    for level, key, kw in notes:
        msgs.add(level, key, **kw)


# ---------------------------------------------------------------------------------------------- prepare
def prepare(scan_path, work_dir, opts=None, progress=None):
    """Read and orient the scan.  opts: mm_per_unit, side, tape_cm, lang ('en'|'pt') and optionally any override
    accepted by analyze() (dorsum, fingers, knuckle_s, thumb_s, band_shift_mm) to refresh the preview."""
    t0 = time.time()
    opts = dict(opts or {})
    lang = opts.get('lang') or 'en'
    say = progress or (lambda s: None)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    msgs = Messages(lang)
    out = {'api': API_VERSION, 'status': 'refused', 'scan': None, 'landmarks': None, 'preview_glb': None, 'frame': None, 'messages': msgs}
    scan_path = Path(scan_path)
    mb = scan_path.stat().st_size / 1e6
    if mb > SCAN_LIMIT_MB:
        msgs.error('too_big', mb=mb, limit=SCAN_LIMIT_MB)
        return _clean(out)
    sha = C.sha256_file(scan_path)
    st = _load_state(work)
    ses = _session(work) if st else None
    mmpu = opts.get('mm_per_unit')
    if not (st and ses is not None and st.get('scan_sha256') == sha and st.get('mm_per_unit_opt') == mmpu):
        say(tr('prog_read', lang))
        try:
            V, Fc, info = M.load_scan(scan_path, mmpu)
        except Exception as e:      # unreadable file
            msgs.error('load_failed', detail=str(e)[:120])
            return _clean(out)
        R, centre = C.normalised_pca(V)
        Vp = (V - centre) @ R.T
        bnd, nonman, nme = M.edge_stats(Fc, len(Vp), True)
        bv = Vp[np.unique(bnd)] if len(bnd) else np.zeros((0, 3))
        nv = Vp[np.unique(nme)] if len(nme) else np.zeros((0, 3))
        Vd, Fd, _ = M.cluster_decimate(Vp, Fc, int(opts.get('display_faces') or DISPLAY_FACES))
        np.savez(work / 'fc_scan.npz', Vp=Vp, F=Fc, bv=bv, nv=nv, Vd=Vd, Fd=Fd)
        ses = {'Vp': Vp, 'F': Fc, 'bv': bv, 'nv': nv, 'Vd': Vd, 'Fd': Fd, 'readings': {}}
        _CACHE[str(work.resolve())] = ses
        info.update(watertight=bool(len(bnd) == 0 and nonman == 0), open_edges=int(len(bnd)), nonmanifold_edges=int(nonman))
        st = {'api': API_VERSION, 'scan_name': scan_path.name, 'scan_sha256': sha, 'scan_bytes': scan_path.stat().st_size,
              'mm_per_unit_opt': mmpu, 'info': info, 'runs': 0,
              'frame': {'R': R, 'centre_mm': centre, 'mm_per_unit': info['mm_per_unit']}}
    info = st['info']
    st['opts'] = {k: opts.get(k) for k in ('side', 'tape_cm', 'lang') if opts.get(k) is not None}
    if opts.get('data_dir'):
        st['data_dir'] = str(opts['data_dir'])
    msgs.info('units', units=info['units_guess'], ext=max(info['extent_mm']))
    scan_units_unsure = info['units_confidence'] < 0.9
    if info['units_confidence'] < 0.6:
        msgs.warn('units_unsure', units=info['units_guess'], ext=max(info['extent_mm']))
    elif info['units_confidence'] < 0.9 and info['units_guess'] == 'cm':
        msgs.warn('units_cm_or_inch')
    if info['dropped_faces']:
        msgs.info('dropped_parts', n=len(info['dropped_faces']))
    scan = {'faces': info['faces'], 'vertices': info['vertices'], 'extent_mm': [round(x, 1) for x in info['extent_mm']],
            'units_guess': info['units_guess'], 'units_confidence': info['units_confidence'], 'mm_per_unit': info['mm_per_unit'],
            'watertight': info['watertight'], 'open_edges': info['open_edges'], 'open_edges_near_band': None,
            'nonmanifold_edges': info['nonmanifold_edges'], 'nonmanifold_near_band': None,
            'components': info['components'], 'sha256': sha, 'file': scan_path.name}
    out['scan'] = scan
    say(tr('prog_landmarks', lang))
    try:
        ov = _ov_from(opts, st)
        rd = _reading(ses, ov, lang)
    except C.Refusal as e:
        msgs.error(e.code, **e.kw)
        scan['quality'] = _quality(info, None, 0, info['open_edges'], info['nonmanifold_edges'], lang)
        Mx = np.eye(4)
        Mx[:3, :3] = [[1, 0, 0], [0, 1, 0], [0, 0, -1]]          # plain look at the PCA frame
        _write_glb(work / 'preview.glb', ses, Mx)
        out['preview_glb'] = 'preview.glb'
        _save_state(work, st)
        return _clean(out)
    st['overrides'] = ov
    _notes_to(msgs, rd.notes)
    near, _, near_z = C.band_edge_check(rd, ses['bv'] * np.array(rd.flips, dtype=float))
    scan['open_edges_near_band'] = near
    near_nm = C.band_edge_check(rd, ses['nv'] * np.array(rd.flips, dtype=float))[0]
    scan['nonmanifold_near_band'] = near_nm
    if near_nm:
        msgs.error('nonmanifold_near_band', n=near_nm)
    if near:
        msgs.error('open_near_band', margin=C.HOLE_MARGIN, n=near)
    elif info['open_edges']:
        msgs.info('open_far', n=info['open_edges'])
    if rd.drift > 8:
        msgs.warn('drift', mm=rd.drift)
    for a in rd.amb:
        msgs.append({'level': 'warn', 'code': 'needs_' + a['kind'], 'text': a['message']})
    scan['quality'] = _quality(info, rd, near, info['open_edges'], info['nonmanifold_edges'], lang, _band_edge_length(ses, rd), near_nm)
    Mx = C.view_matrix(rd)
    ovl = _overlays(rd, Mx)
    _write_glb(work / 'preview.glb', ses, Mx, lines=[('knuckle_line', ovl['knuckle_line'], (230, 40, 40)),
                                                     ('band', ovl['band'], (255, 150, 0)), ('thumb', ovl['thumb'], (40, 160, 60))])
    out.update(status='needs_input' if rd.amb else 'ok', landmarks=_landmarks(rd, lang), preview_glb='preview.glb',
               frame=_frame(rd, Mx, st), overlays=ovl, overrides_applied=ov, seconds=round(time.time() - t0, 2))
    _save_state(work, st)
    return _clean(out)


# ---------------------------------------------------------------------------------------------- analyze
def analyze(work_dir, overrides=None, progress=None):
    """Compare with the 7 standard sizes and prepare the custom cuff.  overrides: side, dorsum ('auto'|'keep'|'flip',
    absolute: keep = the +y of the scan axis frame is the back of the hand; simply pass a candidate's ``overrides``),
    fingers ('auto'|'high'|'low'), knuckle_s / thumb_s (stable axis coordinate) or knuckle_z / thumb_z (view
    coordinate of the latest GLB), band_shift_mm (+ = toward the wrist), tape_cm, lang."""
    t0 = time.time()
    work = Path(work_dir)
    say = progress or (lambda s: None)
    st = _load_state(work)
    ses = _session(work) if st else None
    lang = (overrides or {}).get('lang') or ((st or {}).get('opts') or {}).get('lang') or 'en'
    msgs = Messages(lang)
    out = {'api': API_VERSION, 'status': 'refused', 'sizes': [], 'recommended_size': None, 'size_by_tape': None,
           'smallest_fitting_size': None, 'custom': None, 'scale_confirmed': False, 'result_glb': None, 'legend': _legend(), 'messages': msgs}
    if st is None or ses is None:
        msgs.error('build_no_analysis')
        return _clean(out)
    merged = dict(st.get('opts') or {})                     # what prepare() was given (side, tape, lang)
    merged.update(st.get('overrides') or {})                # then the overrides already applied in this session
    merged.update({k: v for k, v in (overrides or {}).items() if k in OVERRIDE_KEYS})
    if overrides:
        for kz, ks in (('knuckle_z', 'knuckle_s'), ('thumb_z', 'thumb_s')):
            if overrides.get(kz) is not None and overrides.get(ks) is None:
                merged[ks] = None                        # a new click replaces the stored value
    tape = merged.get('tape_cm')
    st.pop('analysis', None)
    try:
        ov = _ov_from(merged, st)
        say(tr('prog_hand', lang))
        rd = _reading(ses, ov, lang)
    except C.Refusal as e:
        msgs.error(e.code, **e.kw)
        _save_state(work, st)
        return _clean(out)
    st['overrides'] = ov
    _notes_to(msgs, rd.notes)
    Mx0 = C.view_matrix(rd)
    out['landmarks'] = _landmarks(rd, lang)
    out['overrides_applied'] = ov

    def finish(status, Mx=None, colors=None, lines=None):
        Mx = Mx0 if Mx is None else Mx
        ovl = _overlays(rd, Mx)
        ls = [('knuckle_line', ovl['knuckle_line'], (230, 40, 40))] + (lines or [('band', ovl['band'], (255, 150, 0))])
        _write_glb(work / 'analysis.glb', ses, Mx, colors=colors, lines=ls)
        out.update(status=status, result_glb='analysis.glb', frame=_frame(rd, Mx, st), overlays=ovl,
                   seconds=round(time.time() - t0, 2))
        _save_state(work, st)
        (work / 'analysis.json').write_text(json.dumps(_clean(out), indent=1), encoding='utf8')
        return _clean(out)

    if rd.amb:
        for a in rd.amb:
            msgs.append({'level': 'warn', 'code': 'needs_' + a['kind'], 'text': a['message']})
        return finish('needs_input')

    # ---- tape (scale / pose check only)
    t_scan = F.tamanho_pela_fita(rd.tape_scan_cm)
    t_tape = None
    if tape is not None:
        tape = float(tape)
        if not (math.isfinite(tape) and 10.0 <= tape <= 35.0):
            msgs.error('tape_range')
            return finish('refused')
        t_tape = F.tamanho_pela_fita(tape)
        diff = rd.tape_scan_cm - tape
        if abs(diff) > C.TOL_TAPE_CM:
            msgs.error('tape_mismatch', scan=rd.tape_scan_cm, tape=tape, diff=diff, tol=C.TOL_TAPE_CM)
            return finish('refused')
        msgs.info('tape_ok', scan=rd.tape_scan_cm, tape=tape, diff=diff)
    else:
        msgs.warn('no_tape', scan=rd.tape_scan_cm)
    size_tape = t_tape or t_scan
    scale_ok = tape is not None                              # given and within tolerance (checked above)
    out['size_by_tape'] = size_tape
    out['size_by_tape_source'] = 'tape' if tape is not None else 'scan'
    out['scale_confirmed'] = scale_ok
    out['knuckle_circumference_cm'] = {'scan': round(rd.tape_scan_cm, 2), 'tape': tape}
    info = st['info']
    if not scale_ok and info['units_confidence'] < 0.9:
        msgs.warn('units_confirm', units=info['units_guess'], c=100 * info['units_confidence'])
    cm = tape if tape is not None else rd.tape_scan_cm
    msgs.info('size_by_tape', cm=cm, src=tr('src_tape' if tape is not None else 'src_scan', lang), size=size_tape)
    lim = F.fronteira(cm)
    if lim:
        msgs.info('size_border', lim=lim)

    # ---- band usable?  (no size is recommended from a band that cannot be read)
    flips = np.array(rd.flips, dtype=float)
    near = C.band_edge_check(rd, ses['bv'] * flips)[0]
    near_nm = C.band_edge_check(rd, ses['nv'] * flips)[0]
    if rd.gaps:
        msgs.error('band_gap', z0=rd.gaps[0], z1=rd.gaps[-1])
        return finish('refused')
    if not rd.complete:
        msgs.error('band_thumb' if rd.thumb_cut else 'band_incomplete')
        return finish('refused')
    if near:
        msgs.error('open_near_band', margin=C.HOLE_MARGIN, n=near)
        return finish('refused')
    if near_nm:
        msgs.error('nonmanifold_near_band', n=near_nm)
        return finish('refused')
    if rd.drift > 8:
        msgs.warn('drift', mm=rd.drift)

    # ---- geometry: 7 standard sizes + custom range.  Independent of the tape, so it is computed once per reading
    # and re-used when the user only adds or corrects the tape measurement.
    key = _ov_key(ov) + lang
    cache = ses.get('an_cache')
    if cache is None or cache['key'] != key:
        say(tr('prog_sizes', lang))
        sizes, raw, (ang, org), est_cad = C.fit_sizes(rd, lang, progress=say)
        say(tr('prog_custom', lang))
        st['runs'] = int(st.get('runs', 0)) + 1
        an_dir = work / ('analysis_%02d' % st['runs'])
        manual = ', '.join(k + '=' + str(ov[k]) for k in ('dorsum', 'fingers') if ov[k] != 'auto') or None
        data_dir = Path(st.get('data_dir') or (HERE.parent / 'dados'))
        grid_json = data_dir / 'aberturas_grade_W80_84.json'
        if not grid_json.exists():
            grid_json = HERE / 'aberturas_grade_W80_84.json'
        try:
            cu, stop = C.custom_cuff(rd, str(grid_json), an_dir, 'hand', st['scan_sha256'], None, manual, progress=say), None
        except C.CustomStop as e:
            cu, stop = None, e
        cache = ses['an_cache'] = dict(key=key, sizes=sizes, raw=raw, ang=ang, org=org, est=est_cad, cu=cu, stop=stop, an_dir=an_dir)
    sizes, raw, ang, org, est_cad, cu, stop, an_dir = (cache[k] for k in ('sizes', 'raw', 'ang', 'org', 'est', 'cu', 'stop', 'an_dir'))
    out['sizes'] = sizes
    t_geo = next((s['size'] for s in sizes if s['fits']), None)
    out['smallest_fitting_size'] = t_geo
    out['recommended_size'] = t_geo                          # only a size that PASSED the geometric check; never the tape estimate
    if t_geo is None:
        msgs.warn('size_none')
    else:
        msgs.info('size_by_shape', size=t_geo)
        if t_geo != size_tape:
            msgs.warn('size_differs', tape=size_tape, shape=t_geo)
    if rd.side == 'left':
        msgs.info('left_mirror_note')

    if cu is None:                                           # no custom cuff for this hand
        kw = dict(stop.kw)
        out['custom_range'] = kw.pop('grid', None)
        status = stop.status
        msgs.add('warn' if status == 'standard_only' else 'error', stop.code, **kw)
        if t_geo is not None:
            msgs.info('use_standard', size=t_geo)
        else:
            msgs.warn('no_verified_fit', hint=tr('tape_hint', lang, size=size_tape))
            if status == 'standard_only':
                status = 'no_verified_standard_fit'
        msgs.info('disclaimer')
        rs = raw.get(t_geo)
        if rs is not None:
            Mx = C.view_matrix(rd, C.pose_tuple(rs, ang, org))
            Vv = C.apply(Mx, ses['Vd'])
            mask, g = C.band_gap(Vv, rs['_ab'], rd.side == 'left', [(e['z_cuff'], P) for e, P in zip(est_cad, rs['_pos'])])
            col = np.tile(np.array(C.SKIN_RGB, dtype=np.uint8), (len(Vv), 1))
            col[mask] = C.gap_colors(g)
            out['heatmap_for'] = {'kind': 'standard', 'size': t_geo}
            return finish(status, Mx, col, [('cuff_outline', _outline(rs['_ab'], rd.side == 'left'), C.CUFF_RGB)])
        return finish(status)
    _notes_to(msgs, cu['notes'])
    a, b = cu['before'], cu['after']
    r = cu['r']
    out['custom_range'] = cu['grid']
    out['custom'] = {'W': cu['W'], 'side': rd.side, 'variant': 'W%.1f_%s' % (cu['W'], 'L' if rd.side == 'left' else 'R'),
                     'dorsal_profile_mm_min': -round(float(cu['low'].max()), 2),
                     'lateral_clearance_mm': round(r['lateral_min_mm'], 3), 'palm_compression_mm': round(max(0.0, -r['rigido_min_mm']), 3),
                     'pose': {'rotation_deg': r['giro_grau'], 'dx_mm': r['dx_mm'], 'dy_mm': r['dy_mm']},
                     'predicted': {'closest_section_gap_before': a['folga_media_corte_mais_proximo_mm'],
                                   'after': b['folga_media_corte_mais_proximo_mm'],
                                   'share_le_0p5': b['frac_corte_mais_proximo_ate_0_5mm'],
                                   'max_overlap': b['maior_sobreposicao_mm'],
                                   'all_sections_gap_before': a['folga_media_todos_cortes_mm'],
                                   'all_sections_gap_after': b['folga_media_todos_cortes_mm'],
                                   'raw_after': cu['after_raw']},
                     'spring_travel_mm': cu['travel'],
                     'profile': {'x_mm': cu['X'], 'gap_before_mm': cu['gap'], 'lowering_mm': cu['low']}}
    msgs.info('custom_ok', W=cu['W'], side=tr(rd.side, lang), low=float(cu['low'].max()))
    msgs.info('custom_gap', a=a['folga_media_corte_mais_proximo_mm'], b=b['folga_media_corte_mais_proximo_mm'],
              pct=100 * b['frac_corte_mais_proximo_ate_0_5mm'], ov=b['maior_sobreposicao_mm'], travel=cu['travel'])
    if not scale_ok:
        msgs.warn('custom_needs_tape', W=cu['W'], scan=rd.tape_scan_cm, tol=C.TOL_TAPE_CM)
    msgs.info('disclaimer')
    pose = C.pose_tuple(r, cu['ang'], cu['org'])
    Mx = C.view_matrix(rd, pose)
    Vv = C.apply(Mx, ses['Vd'])
    mask, g = C.band_gap(Vv, cu['ab2'], rd.side == 'left', [(e['z_cuff'], P) for e, P in zip(cu['est'], r['_pos'])])
    col = np.tile(np.array(C.SKIN_RGB, dtype=np.uint8), (len(Vv), 1))
    col[mask] = C.gap_colors(g)
    out['heatmap_for'] = {'kind': 'custom', 'W': cu['W']}
    out['sections'] = _sections_payload(cu['est'], r['_pos'], cu['ab'], cu['ab2'])
    status = 'custom_ready' if scale_ok else 'custom_needs_tape'
    if not scale_ok:
        out['needs'] = ['tape_cm']
    st['analysis'] = {'dir': an_dir.name, 'variant': out['custom']['variant'], 'pose': [pose[0], list(pose[1]), list(pose[2])],
                      'W': cu['W'], 'summary': {k: out[k] for k in ('sizes', 'recommended_size', 'size_by_tape', 'smallest_fitting_size', 'custom', 'custom_range', 'sections')},
                      'tape_cm': tape, 'tape_scan_cm': rd.tape_scan_cm, 'scale_confirmed': bool(scale_ok),
                      'landmarks': out['landmarks'], 'lang': lang, 'messages': list(msgs)}
    return finish(status, Mx, col, [('cuff_outline', _outline(cu['ab2'], rd.side == 'left'), C.CUFF_RGB)])


def _outline(ab, left):
    sx = -1.0 if left else 1.0
    return [np.c_[np.asarray(A.poly.exterior.coords)[:, 0] * sx, np.asarray(A.poly.exterior.coords)[:, 1],
                  np.full(len(A.poly.exterior.coords), z - 13.0)] for z, A in sorted(ab.items())]


def _sections_payload(est, pos, ab, ab2):
    """The 5 band sections in the seated pose with the standard and the personal opening (right-hand CAD frame,
    mm) - what the report charts draw."""
    out = []
    for e, P in zip(est, pos):
        z = e['z_cuff']
        out.append({'z_cuff': z, 'distance_from_knuckles_mm': round(-e['dz'], 2),
                    'hand': np.round(P, 3), 'opening_standard': np.round(np.asarray(ab[z].poly.exterior.coords), 3),
                    'opening_custom': np.round(np.asarray(ab2[z].poly.exterior.coords), 3)})
    return out


# ---------------------------------------------------------------------------------------------- build
def build(work_dir, grid_dir, data_dir, progress=None):
    """Make the custom cuff prepared by analyze(): solid (STL), manufacturing checks, Bambu Studio 3MF, verification
    of the generated solid against the scan, JSON + HTML report, result.glb."""
    import hashlib
    import runpy
    import trimesh
    import gerador_web as GW
    t0 = time.time()
    work = Path(work_dir)
    say = progress or (lambda s: None)
    st = _load_state(work)
    lang = ((st or {}).get('analysis') or {}).get('lang') or 'en'
    msgs = Messages(lang)
    out = {'api': API_VERSION, 'status': 'stopped', 'files': {}, 'locks': None, 'verification': None, 'result_glb': None,
           'legend': _legend(), 'messages': msgs}
    if not st or not st.get('analysis'):
        msgs.error('build_no_analysis')
        return _clean(out)
    an = st['analysis']
    # Independent scale confirmation is required before any manufacturing file exists: the tape measurement must
    # have been given and must agree with the scan (re-checked here from the stored numbers).
    tape, tscan = an.get('tape_cm'), an.get('tape_scan_cm')
    confirmed = bool(an.get('scale_confirmed')) and tape is not None and tscan is not None and \
        math.isfinite(float(tape)) and math.isfinite(float(tscan)) and abs(float(tscan) - float(tape)) <= C.TOL_TAPE_CM
    if not confirmed:
        out['status'] = 'needs_input'
        out['needs'] = ['tape_cm']
        msgs.error('build_needs_tape')
        return _clean(out)
    an_dir = work / an['dir']
    st['runs'] = int(st.get('runs', 0)) + 1
    b_dir = work / ('build_%02d' % st['runs'])
    b_dir.mkdir(parents=True)
    p = json.loads((an_dir / 'parametros.json').read_text(encoding='utf8'))
    left = bool(p['esquerda'])
    vid = an['variant']
    idx = json.loads((Path(grid_dir) / 'indice_grade_web.json').read_text(encoding='utf8'))
    var = next((v for v in idx if v['id'] == vid), None)
    stl_var = Path(grid_dir) / var['arquivo'] if var else None
    if var is None or var['falhas'] or not stl_var.exists() or C.sha256_file(stl_var) != var['sha256_refinado']:
        msgs.error('build_variant_missing', vid=vid)
        return _clean(out)
    say(tr('prog_shape', lang))
    m0 = trimesh.load(stl_var, process=True)
    dorso = json.loads((an_dir / p['dorso']).read_text(encoding='utf8'))
    m, fixmax, dmax = C.apply_dorsal(m0, p['dw'], p['dh'], dorso, left, str(Path(data_dir) / 'contornos_base.json'))
    say(tr('prog_locks', lang))
    r = GW.medir(m, p['dw'], p['dh'])
    r.update(fix_desloc_max_mm=fixmax, fix_variante_mm3=float(var['fix']), desloc_max_mm=dmax)
    fails = GW.trava(r)
    checks = [{'name': tr(key, lang), 'value': (None if mk is None else r.get(mk)), 'limit': limit, 'unit': unit,
               'ok': gid not in fails} for gid, key, mk, limit, unit in C.LOCKS]
    out['locks'] = {'checks': checks, 'failures': [c['name'] for c in checks if not c['ok']], 'raw': r,
                    'max_displacement_mm': dmax}
    stl = b_dir / 'FreshCuff_Custom_hand.stl'
    m.export(stl)
    files = {'stl': str(stl.relative_to(work))}
    hashes = {'stl_sha256': C.sha256_file(stl)}
    ver = None
    if fails:
        msgs.error('build_locks_failed', what='; '.join(out['locks']['failures']))
    else:
        say(tr('prog_3mf', lang))
        mf = b_dir / ('FreshCuff_Custom_W%.1f_%s_P1S_PETG.3mf' % (an['W'], 'L' if left else 'R'))
        args = [str(Path(data_dir) / 'FreshCuff_R08A_T4_LISA_P1S_R05b.3mf'), str(stl), str(mf), '--costura-pulseira',
                '--dw', str(p['dw']), '--dh', str(p['dh']), '--dorso', str(an_dir / p['dorso'])] + (['--espelhado'] if left else [])
        old = sys.argv
        sys.argv = ['trocar_malha'] + args
        try:
            import io, contextlib, warnings
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                runpy.run_path(str(HERE / 'trocar_malha_3mf_v4b_custom.py'), run_name='__main__')
        finally:
            sys.argv = old
        hashes['3mf_sha256'] = C.sha256_file(mf)
        say(tr('prog_verify', lang))
        ver, ab_stl, secs_stl = C.verify_against_scan(an_dir, stl)
        (b_dir / 'verification.json').write_text(json.dumps(ver, indent=2, ensure_ascii=False), encoding='utf8')
        v = ver['veredito']
        ok = v.get('resultado') == 'APROVADO'
        same = ver['a_mesma_pose_bruto']
        out['verification'] = {
            'verdict': 'approved' if ok else 'rejected',
            'failures': [tr(C.VERIFY_KEYS.get(f, f), lang) for f in v.get('falhas', [])],
            'gap_difference_mm': v.get('dif_folga_bruta_mm'),
            'same_pose': {'closest_section_gap': same.get('folga_media_corte_mais_proximo_mm'),
                          'share_le_0p5': same.get('frac_corte_mais_proximo_ate_0_5mm'),
                          'max_overlap': same.get('maior_sobreposicao_mm'), 'rigid_min': same.get('rigido_min_mm'),
                          'lateral_min': same.get('lateral_min_mm'), 'all_sections_gap': same.get('folga_media_todos_cortes_mm')},
            'free_pose': {'seats': ver['b_pose_nova'].get('viavel'), 'rigid_min': ver['b_pose_nova'].get('rigido_min_mm'),
                          'dorsal_min': ver['b_pose_nova'].get('dorso_min_mm'), 'lateral_min': ver['b_pose_nova'].get('lateral_min_mm')},
            'limits': {'gap_difference_mm': v['limites']['dif_folga_corte_proximo_mm'], 'rigid_min_mm': v['limites']['rigido_min_mm'],
                       'spring_travel_mm': v['limites']['curso_mm'], 'lateral_min_mm': v['limites']['folga_lateral_alvo_mm'] - v['limites']['lateral_tolerancia_mm']}}
        if ok:
            files['3mf'] = str(mf.relative_to(work))
            out['status'] = 'cuff_ready'
            msgs.info('build_ok', dif=v.get('dif_folga_bruta_mm') or 0.0)
        else:
            mf.rename(mf.with_suffix('.3mf.rejected'))      # never hand out a project that failed verification
            hashes.pop('3mf_sha256', None)
            msgs.error('build_verify_failed', what='; '.join(out['verification']['failures']))
        msgs.info('disclaimer')
    # ---- result.glb : hand + generated cuff in the view frame
    ses = _session(work)
    if ses is not None:
        try:
            rd = _reading(ses, st['overrides'], lang)
            pose = (an['pose'][0], tuple(an['pose'][1]), tuple(an['pose'][2]))
            Mx = C.view_matrix(rd, pose)
            Vv = C.apply(Mx, ses['Vd'])
            col = np.tile(np.array(C.SKIN_RGB, dtype=np.uint8), (len(Vv), 1))
            lines = []
            if ver is not None:
                mask, g = C.band_gap(Vv, ab_stl, left, secs_stl)
                col[mask] = C.gap_colors(g)
            Vc = np.asarray(m.vertices) - [0, 0, 13.0]
            cuff = dict(name='cuff', kind='mesh', V=Vc, F=np.asarray(m.faces), rgb=C.CUFF_RGB)
            _write_glb(work / 'result.glb', ses, Mx, colors=col, lines=lines, extra=[cuff])
            out['result_glb'] = 'result.glb'
            out['frame'] = _frame(rd, Mx, st)
        except Exception as e:      # the preview must never block the files
            msgs.warn('internal_note', detail='3D result preview not available (' + str(e)[:100] + ')')
    # ---- reports
    sha = lambda f: C.sha256_file(f)
    report = {'tool': C.VERSION, 'api': API_VERSION, 'status': out['status'],
              'scan': {'file': st['scan_name'], 'sha256': st['scan_sha256'], 'faces': st['info']['faces'],
                       'units': st['info']['units_guess'], 'mm_per_unit': st['info']['mm_per_unit']},
              'overrides': st.get('overrides'), 'analysis': an.get('summary'), 'landmarks': an.get('landmarks'),
              'tape_cm': an.get('tape_cm'),
              'variant': {'id': vid, 'sha256': var['sha256_refinado']}, 'parameters': p,
              'locks': out['locks'], 'verification': out['verification'], 'verification_raw': ver,
              'outputs': dict(hashes, **files) if out['status'] == 'cuff_ready' else {'released': False, 'diagnostic_hashes': hashes},
              'environment': GW.versoes(),
              'programs_sha256': {f.name: sha(f) for f in sorted(HERE.glob('*.py'))},
              'data_sha256': {f.name: sha(f) for f in [Path(data_dir) / 'contornos_base.json', Path(data_dir) / 'FreshCuff_R08A_T4_LISA_P1S_R05b.3mf',
                                                       Path(data_dir) / 'aberturas_grade_W80_84.json', HERE / 'cuff_openings_R08A_v2.json'] if f.exists()},
              'messages': list(an.get('messages') or []) + list(msgs),
              'notice': 'Experimental. Geometry checked in CAD against the scan; the real fit depends on a physical dry-fit. '
                        'Not a medical device. Review the 3MF in the slicer before printing.'}
    rj = b_dir / 'report.json'
    rj.write_text(json.dumps(_clean(report), indent=1, ensure_ascii=False), encoding='utf8')
    files['report_json'] = str(rj.relative_to(work))
    try:
        import report_html
        rh = b_dir / 'report.html'
        rh.write_text(report_html.render(_clean(report), lang), encoding='utf8')
        files['report_html'] = str(rh.relative_to(work))
    except Exception as e:
        msgs.warn('internal_note', detail='HTML report not available (' + str(e)[:100] + ')')
    if out['status'] != 'cuff_ready':
        # Nothing manufacturable leaves a stopped build: the solid stays in work_dir only as a diagnostic
        # (renamed so it cannot be mistaken for a released file) and is not listed in the result.
        if stl.exists():
            stl.rename(stl.with_suffix('.stl.rejected'))
        files = {k: v for k, v in files.items() if k not in ('stl', '3mf')}
        out['diagnostic_hashes'] = hashes
        hashes = {}
    out['files'] = files
    out['hashes'] = hashes
    out['seconds'] = round(time.time() - t0, 2)
    st['build'] = {'dir': b_dir.name, 'status': out['status'], 'files': files}
    _save_state(work, st)
    res = _clean(out)
    (work / 'build.json').write_text(json.dumps(res, indent=1), encoding='utf8')
    return res
