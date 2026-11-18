# -*- coding: utf-8 -*-
"""FreshCuff Fit - core engine (English orchestration of the validated Portuguese modules).

The numerical behaviour of the validated code is kept: the same sections (fc_mesh.Slicer == freshcuff_fit.corte),
the same landmark rule (freshcuff_fit.achar_marcos), the same pose searches (fc_fastfit == encaixe_faixa /
encaixe_lateral), the same dorsal profile arithmetic (gerador_scan), the same solid, locks, 3MF and verification
(gerador_web, trocar_malha_3mf_v4b_custom, conferir_cuff_gerado.veredito).  What is new here:
  * the reading never dead-ends on orientation: it always produces a best guess, a confidence and the list of
    candidate interpretations, and accepts overrides (fingers end, back of hand, hand side, knuckle line, thumb);
  * speed (fast sections and fast exact pose search); no matplotlib figures in the main path;
  * English results, GLB previews in one canonical frame.

Frames
  scan    : coordinates of the file (any unit)
  axis    : PCA frame in mm (x width, y thickness, z length), sign-normalised so it is the same on every platform.
            Stable for a scan; "s" coordinates (knuckle_s, thumb_s) are z in this frame.
  fit     : axis frame flipped so that fingers point to +z and the back of the hand to +y (the legacy "Fit" frame;
            in it the thumb of a RIGHT hand is at +x)
  view    : canonical display frame = frame of the cuff actually produced, shifted so the band centre is at z = 0:
            +y back of the hand, +z toward the wrist, thumb at -x for a right hand (+x = little finger) and at +x
            for a left hand (the left cuff is the mirrored solid).  Knuckle end of the band at z = -12.8.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from shapely.geometry import Polygon, box

import freshcuff_fit as F
import gerador_scan as G
import fc_fastfit as FF
import fc_mesh as M
from fc_strings import tr

HERE = Path(__file__).resolve().parent
VERSION = 'FreshCuff Fit core 1.0 (2026-11-18)'
TOL_SKIN = 0.5            # mm, provisional skin-compression assumption (legacy --tol-pele)
TOL_TAPE_CM = 0.6         # legacy --tol-fita-cm
SETBACK = 6.0             # knuckles = finger separation - 6 mm (legacy --recuo-mm)
PRELOAD = 0.2             # mm (legacy --precarga-mm)
DORSAL_LIMIT = 3.0        # mm (legacy --limite-dorso-mm)
LATERAL_MIN = 0.5         # mm (legacy --folga-lateral-mm)
LATERAL_MAX = 6.0         # mm (legacy --folga-lateral-max-mm)
HOLE_MARGIN = 10.0        # mm (legacy --margem-furo-mm)
Z_KNUCKLE_VIEW = 0.2 - 13.0

LEGEND = [(-1.0, (150, 0, 30)), (-0.5, (220, 50, 40)), (0.0, (255, 235, 150)), (0.5, (120, 200, 120)),
          (1.5, (70, 150, 200)), (4.0, (40, 70, 160))]
SKIN_RGB = (224, 190, 168)
CUFF_RGB = (17, 108, 105)


class Refusal(Exception):
    """The scan cannot be used as it is (not an orientation question)."""

    def __init__(self, code, **kw):
        super().__init__(code)
        self.code = code
        self.kw = kw


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 20), b''):
            h.update(blk)
    return h.hexdigest()


def normalised_pca(V):
    """Legacy PCA frame with a deterministic sign: each of z and x points to the positive side of its dominant
    file axis; y follows from a right-handed frame.  (The legacy reader ends in the same final frame.)"""
    R, centre = M.pca_frame(V)
    for row in (2, 0):
        k = int(np.argmax(np.abs(R[row])))
        if R[row, k] < 0:
            R[row] *= -1
    if np.linalg.det(R) < 0:
        R[1] *= -1
    return R, centre


# ============================================================================================ reading
def profile(S, step=1.5):
    """== freshcuff_fit.perfil"""
    rows = []
    for z in np.arange(S.zmin + 3, S.zmax - 3, step):
        ps, opened = S.section(z)
        if not ps:
            rows.append({'z': float(z), 'vazio': True, 'aberto_mm': opened})
            continue
        p = ps[0]
        b = p.bounds
        rows.append({'z': float(z), 'vazio': False, 'area': p.area, 'largura': b[2] - b[0],
                     'espessura': b[3] - b[1], 'n': len(ps), 'fita': p.convex_hull.length,
                     'aberto_mm': opened, 'pecas': [(q.area, q.centroid.x, q.bounds) for q in ps[1:4]]})
    return rows


def fingers_count(S):
    """== freshcuff_fit.lado_dos_dedos : extra pieces near the low end, near the high end."""
    zmin, zmax = S.zmin, S.zmax
    L = zmax - zmin

    def multi(z0, z1):
        return sum(max(0, len(S.section(z)[0]) - 1) for z in np.linspace(z0, z1, 10))
    return multi(zmin + 0.05 * L, zmin + 0.35 * L), multi(zmax - 0.35 * L, zmax - 0.05 * L)


def _thumb_piece(S, rows, z_pol):
    """First profile row at/after the thumb separation that has a separate piece: (row, thumb piece, palm polygon)."""
    if z_pol is None:
        return None
    r = min((r for r in rows if not r['vazio'] and r['z'] >= z_pol and r.get('pecas')), key=lambda r: r['z'], default=None)
    if r is None:
        return None
    piece = max(r['pecas'], key=lambda q: q[0])
    palm = S.section(r['z'])[0][0]
    return r, piece, palm


class Reading:
    pass


def read_hand(Vp, Fc, ov, lang='en'):
    """Orient the hand and find the landmarks.  ``ov``: fingers 'auto'|'high'|'low', dorsum 'auto'|'keep'|'flip',
    side 'auto'|'left'|'right', knuckle_s, thumb_s (axis-frame z, or None), band_shift_mm.
    Always returns a Reading with a best guess; ``ambiguities`` lists what the user should confirm."""
    rd = Reading()
    rd.amb = []                 # dicts {kind, message, candidates}
    rd.notes = []               # (level, key, kwargs)
    S = M.Slicer(np.array(Vp, dtype=np.float64, copy=True), Fc)
    rd.S = S
    T = lambda k, **kw: tr(k, lang, **kw)

    # ---- open surface?
    rows0 = profile(S, 4.0)
    frac_open = sum(r['vazio'] or r['aberto_mm'] > 5 for r in rows0) / max(1, len(rows0))
    rd.frac_open = float(frac_open)
    if frac_open >= 0.9:
        raise Refusal('open_surface', pct=100 * frac_open)
    if frac_open > 0.4:
        rd.notes.append(('warn', 'open_sections_warn', {'pct': 100 * frac_open}))

    # ---- fingers end
    low, high = fingers_count(S)
    rd.fingers_counts = (int(low), int(high))
    if ov.get('fingers') in ('high', 'low'):
        fingers_high, rd.fingers_conf, rd.fingers_manual = (ov['fingers'] == 'high'), 1.0, True
    else:
        rd.fingers_manual = False
        if low != high:
            fingers_high = high > low
            rd.fingers_conf = float(abs(high - low) / float(high + low))
        else:   # no separated fingers on either end: guess the thinner end (a wrist cut is thick), ask the user
            ok = [r for r in rows0 if not r['vazio']]
            third = max(1, len(ok) // 4)
            a_low = np.mean([r['area'] for r in ok[:third]]) if ok else 0
            a_high = np.mean([r['area'] for r in ok[-third:]]) if ok else 0
            fingers_high = a_high <= a_low
            rd.fingers_conf = 0.0
            rd.amb.append({'kind': 'fingers', 'message': T('amb_fingers'),
                           'candidates': [{'label': T('cand_fingers', end=T(e)), 'overrides': {'fingers': e},
                                           'is_guess': (e == 'high') == fingers_high} for e in ('high', 'low')]})
    rd.fingers_high = bool(fingers_high)
    sx = sy = sz = 1
    if not fingers_high:
        S.flip(-1, 1, -1)
        sx, sz = -1, -1
    rows = profile(S)

    # ---- landmarks (legacy rule; fall back to a guess + question instead of a refusal)
    def manual_z(key, name):
        v = ov.get(key)
        if v is None:
            return None
        z = sz * float(v)
        try:
            F_checar_z(S, z)
            return z
        except F.Inconclusivo:
            rd.amb.append({'kind': 'knuckles' if key == 'knuckle_s' else 'thumb', 'message': T('bad_z', name=name), 'candidates': []})
            return None
    zn_m = manual_z('knuckle_s', 'knuckle line')
    zp_m = manual_z('thumb_s', 'thumb base')
    rd.knuckle_manual, rd.thumb_manual = zn_m is not None, zp_m is not None
    try:
        z_nos, z_pol, marks = F.achar_marcos(rows, zn_m, zp_m, SETBACK)
        rd.landmarks_auto = zn_m is None
    except F.Inconclusivo:
        drops = _drops(rows)
        ok = [r for r in rows if not r['vazio']]
        if not ok:
            raise Refusal('open_surface', pct=100.0)
        upper = [r for r in ok if r['z'] > S.zmin + 0.35 * (S.zmax - S.zmin)] or ok
        z_nos = max(upper, key=lambda r: r['largura'])['z']
        if len(drops) == 1 and drops[0] > z_nos - 5:       # the only separation is distal: take it as the fingers
            z_nos = drops[0] - SETBACK
        z_pol = zp_m if zp_m is not None else next((q for q in drops if q < z_nos), None)
        marks = {'quedas_z': [round(q, 1) for q in drops], 'recuo_mm': SETBACK, 'metodo': 'guess: widest section',
                 'z_nos': round(z_nos, 1), 'z_polegar': None if z_pol is None else round(z_pol, 1)}
        rd.landmarks_auto = False
        rd.amb.append({'kind': 'knuckles', 'message': T('amb_knuckles', why=T('amb_knuckles_why', n=len(drops))), 'candidates': []})
    shift = float(ov.get('band_shift_mm') or 0.0)
    if shift:
        z_nos = z_nos - shift                               # positive shift moves the band toward the wrist
    ps_nos, open_nos = S.section(z_nos)
    if not ps_nos:
        raise Refusal('band_incomplete')
    rd.open_knuckle = float(open_nos)
    nos = ps_nos[0]

    # ---- back of the hand: clues
    ft, ff = F.flechas(nos)
    rd.arch = (float(ft), float(ff))
    clues = {}
    clues['arch'] = (ft >= ff, min(1.0, abs(ft - ff) / 2.0))
    tp = _thumb_piece(S, rows, z_pol)
    thumb_side_pre = None
    if tp is not None:
        r_sep, (_, cx_pol, bp), palm = tp
        dy_pol = 0.5 * (bp[1] + bp[3]) - palm.centroid.y
        if abs(dy_pol) > 3:
            clues['thumb'] = (dy_pol < 0, 1.2)                    # thumb lies on the palm side (legacy 2nd clue)
        thumb_side_pre = 'neg' if cx_pol < palm.centroid.x else 'pos'
        rd.thumb_dy = float(dy_pol)
    zz = S.V[:, 2]
    far = zz > z_nos + 25.0
    rd.curl_mm = None
    if far.sum() > 50:
        # Curled fingers reach beyond the thickness of the knuckle section on the PALM side (a flat hand does not
        # protrude on either side).  Positive value = they protrude toward +y.
        yf = S.V[far, 1]
        p_lo = max(0.0, nos.bounds[1] - float(np.percentile(yf, 2)))
        p_hi = max(0.0, float(np.percentile(yf, 98)) - nos.bounds[3])
        disp = p_hi - p_lo
        rd.curl_mm = float(disp)
        if abs(disp) >= 6.0:
            clues['curl'] = (disp < 0, min(2.0, abs(disp) / 6.0))
    score = sum((1 if up else -1) * w for up, w in clues.values())
    wsum = sum(w for _, w in clues.values())
    guess_plus = score >= 0 if abs(score) > 1e-9 else bool(clues['arch'][0])
    conf = float(abs(score) / wsum) if wsum > 0 else 0.0
    disagree = [k for k, (up, w) in clues.items() if w >= 0.5 and up != guess_plus]
    rd.clues = {k: {'back_is_plus_y': bool(up), 'weight': round(float(w), 2)} for k, (up, w) in clues.items()}
    side_decl = ov.get('side') if ov.get('side') in ('left', 'right') else None

    def side_for(plus):                      # hand side implied by the thumb if +y (plus) or -y is the back
        if thumb_side_pre is None:
            return None
        pos = (thumb_side_pre == 'pos') == plus      # flipping the back negates x
        return 'right' if pos else 'left'

    rd.dorsum_manual = ov.get('dorsum') in ('keep', 'flip')
    if rd.dorsum_manual:
        plus = ov['dorsum'] == 'keep'
        rd.dorsum_conf = 1.0
        rd.notes.append(('warn', 'manual_orientation', {'what': 'back of hand: ' + ov['dorsum']}))
        if side_decl and side_for(plus) and side_for(plus) != side_decl:
            other = 'flip' if plus else 'keep'
            rd.amb.append({'kind': 'side', 'message': T('amb_side', declared=T(side_decl), found=T(side_for(plus))),
                           'candidates': [
                               {'label': T('cand_side_other', side=T(side_for(plus))), 'overrides': {'side': side_for(plus), 'dorsum': ov['dorsum']}, 'is_guess': True},
                               {'label': T('cand_side_keep', side=T(side_decl)), 'overrides': {'side': side_decl, 'dorsum': other}, 'is_guess': False}]})
    elif side_decl and thumb_side_pre is not None:
        plus = side_for(True) == side_decl               # chirality: declared side + thumb side fix the back
        others = [(up, w) for k, (up, w) in clues.items()]
        against = sum(w for up, w in others if up != plus)
        favour = sum(w for up, w in others if up == plus)
        rd.dorsum_conf = float((favour + 2.0) / (favour + against + 2.0))
        if against >= 1.5 and favour < 0.5:              # every shape clue contradicts the declared side
            wrong = 'left' if side_decl == 'right' else 'right'
            rd.amb.append({'kind': 'side', 'message': T('amb_side', declared=T(side_decl), found=T(wrong)),
                           'candidates': [
                               {'label': T('cand_side_other', side=T(wrong)), 'overrides': {'side': wrong, 'dorsum': 'keep' if not plus else 'flip'}, 'is_guess': True},
                               {'label': T('cand_side_keep', side=T(side_decl)), 'overrides': {'side': side_decl, 'dorsum': 'keep' if plus else 'flip'}, 'is_guess': False}]})
            plus = not plus                               # show the reading the shape supports; the user decides
    else:
        plus = guess_plus
        rd.dorsum_conf = conf
        if disagree or wsum < 0.5:
            if 'thumb' in disagree or ('thumb' in clues and clues['thumb'][0] != clues['arch'][0]):
                why = T('amb_dorsum_why', ft=ft, ff=ff, other=T('clue_thumb'))
            elif 'curl' in disagree or 'curl' in clues and clues['curl'][0] != clues['arch'][0]:
                why = T('amb_dorsum_why', ft=ft, ff=ff, other=T('clue_curl'))
            else:
                why = T('clue_weak')
            cands = []
            for p_ in (plus, not plus):
                sd = side_for(p_)
                key = 'cand_dorsum_keep' if p_ == plus else 'cand_dorsum_flip'
                c = {'label': T(key, side=T(sd) if sd else '?'), 'overrides': {'dorsum': 'keep' if p_ else 'flip'},
                     'is_guess': p_ == plus}
                if sd:
                    c['overrides']['side'] = sd
                    c['side'] = sd
                cands.append(c)
            rd.amb.append({'kind': 'dorsum', 'message': T('amb_dorsum', why=why), 'candidates': cands})
        elif abs(ft - ff) < 1.0:
            rd.notes.append(('warn', 'dorsum_weak', {'ft': ft, 'ff': ff}))
    rd.dorsum_plus = bool(plus)
    if not plus:
        S.flip(-1, -1, 1)
        sx, sy = -sx, -1
        nos = S.section(z_nos)[0][0]
        rows = profile(S)
    rd.flips = (sx, sy, sz)
    rd.rows, rd.marks, rd.z_nos, rd.z_pol, rd.nos = rows, marks, float(z_nos), (None if z_pol is None else float(z_pol)), nos

    # ---- thumb side / hand side (legacy: thumb at +x in the fit frame = right hand)
    rd.thumb_side = rd.x_lim = None
    rd.thumb_ring = None
    tp = _thumb_piece(S, rows, z_pol)
    if tp is not None:
        r_sep, (_, cx_pol, bp), palm = tp
        b = palm.bounds
        rd.thumb_side = 'neg' if cx_pol < palm.centroid.x else 'pos'
        rd.x_lim = (b[0] - 1.0) if rd.thumb_side == 'neg' else (b[2] + 1.0)
        pcs = S.section(r_sep['z'])[0][1:]
        if pcs:
            tpoly = min(pcs, key=lambda q: abs(q.centroid.x - cx_pol))
            rd.thumb_ring = (float(r_sep['z']), np.asarray(tpoly.exterior.coords))
    side_thumb = {'pos': 'right', 'neg': 'left'}.get(rd.thumb_side)
    rd.side_from_thumb = side_thumb
    if side_thumb:
        rd.side = side_thumb
        rd.side_conf = float(rd.dorsum_conf)
        if side_decl and side_decl != side_thumb and not any(a['kind'] == 'side' for a in rd.amb):
            rd.amb.append({'kind': 'side', 'message': T('amb_side', declared=T(side_decl), found=T(side_thumb)),
                           'candidates': [
                               {'label': T('cand_side_other', side=T(side_thumb)), 'overrides': {'side': side_thumb, 'dorsum': 'keep' if plus else 'flip'}, 'is_guess': True},
                               {'label': T('cand_side_keep', side=T(side_decl)), 'overrides': {'side': side_decl, 'dorsum': 'flip' if plus else 'keep'}, 'is_guess': False}]})
    elif side_decl and not any(a['kind'] == 'dorsum' for a in rd.amb):
        rd.side, rd.side_conf = side_decl, 0.5           # thumb not found: trust the declared side
    else:
        rd.side, rd.side_conf = side_decl, 0.0
        rd.amb.append({'kind': 'thumb', 'message': T('amb_thumb'), 'candidates': []})

    # ---- tape and stations
    rd.tape_scan_cm = float(nos.convex_hull.length / 10)
    rd.width_mm, rd.thickness_mm = float(nos.bounds[2] - nos.bounds[0]), float(nos.bounds[3] - nos.bounds[1])
    _stations(rd)
    return rd


def F_checar_z(S, z):
    if not np.isfinite(z) or not (S.zmin + 2 < z < S.zmax - 2):
        raise F.Inconclusivo('outside', 'marcos')
    ps, opened = S.section(z)
    if opened > 5 or not ps:
        raise F.Inconclusivo('hole', 'malha')


def _drops(rows):
    ok = [r for r in rows if not r['vazio']]
    out = []
    for a, b in zip(ok, ok[1:]):
        if a['largura'] > 50 and b['largura'] < 0.85 * a['largura'] and b['n'] >= 2:
            if not out or b['z'] - out[-1] > 4.5:
                out.append(b['z'])
    return out


_ZC = None


def openings_std():
    global _ZC
    if _ZC is None:
        _ZC = F.carregar_aberturas(str(HERE / 'cuff_openings_R08A_v2.json'))
    return _ZC


def _stations(rd):
    """The 5 sections of the 26 mm band (cuff distal end z = 0.2 at the knuckle line), as the legacy reader."""
    S = rd.S
    d_ab, _ = openings_std()
    zc = sorted(float(z) for z in d_ab['stations_z'])
    z_dist = zc[0]
    est = []
    for zcf in sorted(zc, key=lambda z: abs(z - z_dist)):
        dz = -abs(z_dist - zcf)
        z = rd.z_nos + dz
        ps, opened = S.section(z)
        e = {'dz': round(dz, 2), 'z': round(z, 2), 'z_cuff': zcf, 'aberto_mm': round(opened, 1), '_z': z}
        if not ps:
            e['estado'] = 'sem corte'
            est.append(e)
            continue
        p = ps[0]
        if opened > 5:
            e['estado'] = 'corte aberto (buraco na malha)'
        elif rd.z_pol is not None and z < rd.z_pol:
            if rd.thumb_side:
                cx = box(rd.x_lim, -1e3, 1e3, 1e3) if rd.thumb_side == 'neg' else box(-1e3, -1e3, rd.x_lim, 1e3)
                p2 = p.intersection(cx)
                p2 = max(getattr(p2, 'geoms', [p2]), key=lambda g: g.area)
                e['estado'] = 'recorte exploratório: base do polegar removida'
                e['original'] = p
                p = p2
            else:
                e['estado'] = 'polegar unido, lado desconhecido'
        else:
            e['estado'] = 'completo'
        e['poligono'] = p
        e['largura_mm'] = round(p.bounds[2] - p.bounds[0], 1)
        e['espessura_mm'] = round(p.bounds[3] - p.bounds[1], 1)
        est.append(e)
    rd.stations = est
    cx = [e['poligono'].centroid.x for e in est if e.get('estado') == 'completo']
    rd.drift = float(max(cx) - min(cx)) if len(cx) > 1 else 0.0
    z_ini, z_fim = min(e['z'] for e in est) - 0.5, max(e['z'] for e in est) + 0.5
    gaps = []
    for z in np.arange(z_ini, z_fim + 1e-9, 0.5):
        ps, opened = S.section(z)
        if not ps or opened > 5:
            gaps.append(round(float(z), 1))
    rd.gaps = gaps
    rd.complete = all(e['estado'] == 'completo' for e in est) and not gaps
    rd.thumb_cut = (not rd.complete) and not gaps and all(
        e['estado'] in ('completo', 'recorte exploratório: base do polegar removida') for e in est)


def band_edge_check(rd, boundary_fit):
    """Open-edge points near the band.  Legacy rule B01 refuses any open edge whose z is within HOLE_MARGIN of the
    band; here the point must ALSO be within HOLE_MARGIN (in the section plane) of the band contour itself, so a
    hole in a curled fingertip or in a loose flap that merely shares the band's z range does not count.
    ``boundary_fit``: (n,3) open-edge vertices in the fit frame.  Returns (count, (z0, z1), count by the z-only rule)."""
    import shapely
    zs = [e['z'] for e in rd.stations]
    z0, z1 = min(zs) - HOLE_MARGIN, max(zs) + HOLE_MARGIN
    if len(boundary_fit) == 0:
        return 0, (z0, z1), 0
    B = np.asarray(boundary_fit)
    inz = (B[:, 2] >= z0) & (B[:, 2] <= z1)
    n_z = int(inz.sum())
    polys = [(e['z'], e.get('original', e.get('poligono'))) for e in rd.stations if e.get('poligono') is not None]
    if n_z == 0 or not polys:
        return n_z, (z0, z1), n_z
    P = B[inz]
    zst = np.array([z for z, _ in polys])
    k = np.abs(P[:, 2][:, None] - zst[None, :]).argmin(1)
    near = np.zeros(len(P), dtype=bool)
    for i, (_, poly) in enumerate(polys):
        sel = k == i
        if sel.any():
            d = shapely.distance(poly.exterior, shapely.points(P[sel, :2]))
            near[sel] = d <= HOLE_MARGIN
    return int(near.sum()), (z0, z1), n_z


# ============================================================================================ view frame
def view_matrix(rd, pose=None):
    """4x4 matrix: axis frame (mm) -> view frame.  ``pose`` = (angle_deg_total, origin(x,y), translation(x,y)) of
    the 2D seating in the CAD frame; None = nominal pose (hand upright, knuckle section centred on the opening)."""
    sx, sy, sz = rd.flips
    left = rd.side == 'left'
    Mf = np.diag([sx, sy, sz, 1.0])                       # axis -> fit
    cx = 1.0 if left else -1.0                            # fit -> CAD (right-hand frame): x -> -x for a right hand
    Mc = np.diag([cx, 1.0, -1.0, 1.0])
    Mc[2, 3] = rd.z_nos + 0.2                             # z_cad = z_nos + 0.2 - z_fit
    if pose is None:
        nos = rd.nos if left else G.espelhar(rd.nos)
        ang = F.angulo_largura(nos)
        a = math.radians(-ang)
        c, s = math.cos(a), math.sin(a)
        ox, oy = nos.centroid.x, nos.centroid.y
        P = np.array(nos.exterior.coords) - [ox, oy]
        Q = np.c_[P[:, 0] * c - P[:, 1] * s, P[:, 0] * s + P[:, 1] * c]
        _, ab = openings_std()
        ref = ab[4][13.0].bounds
        t = (0.5 * (ref[0] + ref[2]) - 0.5 * (Q[:, 0].min() + Q[:, 0].max()),
             0.5 * (ref[1] + ref[3]) - 0.5 * (Q[:, 1].min() + Q[:, 1].max()))
    else:
        ang_total, (ox, oy), t = pose
        a = math.radians(ang_total)
        c, s = math.cos(a), math.sin(a)
    Mp = np.eye(4)
    Mp[:2, :2] = [[c, -s], [s, c]]
    Mp[0, 3] = t[0] - (c * ox - s * oy)
    Mp[1, 3] = t[1] - (s * ox + c * oy)
    Mv = np.diag([-1.0 if left else 1.0, 1.0, 1.0, 1.0])  # the left cuff is the mirrored solid
    Mv[2, 3] = -13.0
    return Mv @ Mp @ Mc @ Mf


def apply(Mx, P):
    P = np.asarray(P, dtype=np.float64)
    return P @ Mx[:3, :3].T + Mx[:3, 3]


def fit_to_view(rd, Mx):
    """Matrix fit -> view (to place section rings, which live in the fit frame)."""
    sx, sy, sz = rd.flips
    return Mx @ np.diag([sx, sy, sz, 1.0])                # diag is its own inverse


def ring3(xy, z, n_max=240):
    xy = np.asarray(xy)[:, :2]
    if len(xy) > n_max:
        xy = xy[np.linspace(0, len(xy) - 1, n_max).astype(int)]
    return np.c_[xy, np.full(len(xy), z)]


def gap_colors(g):
    """Vertex colours (uint8 RGB) for a gap in mm, by the LEGEND stops (linear in between)."""
    xs = np.array([m for m, _ in LEGEND])
    out = np.empty((len(g), 3), dtype=np.uint8)
    for k in range(3):
        out[:, k] = np.interp(g, xs, [c[k] for _, c in LEGEND]).astype(np.uint8)
    return out


BAND_NEAR_MM = 4.0        # heat map only on skin within this distance of the band sections (keeps the thumb out)


def band_gap(Vview, apertures, left, sections=None):
    """Signed gap skin -> cuff inner surface for display vertices inside the band (z in [-13, 13] of the view frame):
    exact distance to the opening contour of the two neighbouring sections, interpolated along z.
    Returns (mask, gap_mm)."""
    z = Vview[:, 2] + 13.0
    mask = (z >= 0.0) & (z <= 26.0)
    if sections:
        # ``sections``: [(z_cuff, (n,2) seated hand section in the right-hand CAD frame)].  A thumb tip or a curled
        # finger that merely shares the band's z range is not part of the band and stays skin-coloured.
        import shapely
        idx = np.flatnonzero(mask)
        xs = Vview[idx, 0] * (-1.0 if left else 1.0)
        ys = Vview[idx, 1]
        zst = np.array([zc for zc, _ in sections])
        k = np.abs(z[idx][:, None] - zst[None, :]).argmin(1)
        keep = np.zeros(len(idx), dtype=bool)
        for i, (_, P) in enumerate(sections):
            sel = k == i
            if sel.any():
                poly = Polygon(P).buffer(0)
                keep[sel] = shapely.distance(poly, shapely.points(np.c_[xs[sel], ys[sel]])) <= BAND_NEAR_MM
        mask = np.zeros(len(z), dtype=bool)
        mask[idx[keep]] = True
    x = Vview[mask, 0] * (-1.0 if left else 1.0)           # back to the right-hand CAD frame of the openings
    y = Vview[mask, 1]
    zz = z[mask]
    zs = sorted(apertures)
    sd = np.column_stack([apertures[k].sdf.query(x, y) for k in zs])
    zs = np.array(zs)
    j = np.clip(np.searchsorted(zs, zz) - 1, 0, len(zs) - 2)
    w = np.clip((zz - zs[j]) / (zs[j + 1] - zs[j]), 0.0, 1.0)
    r = np.arange(len(zz))
    return mask, sd[r, j] * (1 - w) + sd[r, j + 1] * w


# ============================================================================================ sizes + custom
def size_note(r, tol, travel, lang):
    T = lambda k, **kw: tr(k, lang, **kw)
    rig, dors = r['rigido_min_mm'], r['dorso_min_mm']
    if not r['viavel']:
        why = []
        if rig < -tol: why.append(T('note_rigid_in', mm=-rig, tol=tol))
        if dors < -travel: why.append(T('note_dors_up', mm=-dors, lim=travel))
        return T('note_nofit', why='; '.join(why) or '-')
    parts = [T('note_rigid_press', mm=-rig) if rig < -F.RESOLUCAO else T('note_rigid_touch') if rig < 0 else T('note_rigid_free'),
             T('note_dors_lift', mm=-dors) if dors < -F.RESOLUCAO else T('note_dors_touch') if dors < F.RESOLUCAO else T('note_dors_gap', mm=dors)]
    s = T('note_fit', parts='; '.join(parts))
    if r['busca']['no_limite']:
        s += ' [' + T('note_at_limit', what=', '.join(r['busca']['no_limite'])) + ']'
    return s


def cad_sections(rd):
    """Band sections in the right-hand CAD frame (thumb at -x): the legacy generator's ``est``/``nos``/angle/origin."""
    left = rd.side == 'left'
    conv = (lambda p: p) if left else G.espelhar
    est = [dict(e, poligono=conv(e['poligono'])) for e in rd.stations]
    nos = conv(rd.nos)
    return est, nos, F.angulo_largura(nos), (nos.centroid.x, nos.centroid.y)


def fit_sizes(rd, lang='en', progress=None):
    """Rigid fit of the band against the 7 standard sizes (same search as the legacy reader, in the CAD frame)."""
    d_ab, ab_raw = openings_std()
    half, travel = d_ab['spring']['zone_half_width_mm'], d_ab['spring']['travel_nominal_mm']
    est, nos, ang, org = cad_sections(rd)
    out, raw = [], {}
    for t in sorted(ab_raw):
        if progress:
            progress('size %d' % t)
        ab = {z: FF.FastAperture(P, half) for z, P in ab_raw[t].items()}
        r = FF.fit_band(est, ab, ang, org, TOL_SKIN, travel)
        r['_ab'] = ab
        raw[t] = r
        out.append({'size': int(t), 'fits': bool(r['viavel']), 'rigid_min': round(r['rigido_min_mm'], 3),
                    'dorsal_min': round(r['dorso_min_mm'], 3), 'lateral_min': round(r['lateral_min_mm'], 3),
                    'rotation_deg': r['giro_grau'], 'at_search_limit': list(r['busca']['no_limite']),
                    'note': size_note(r, TOL_SKIN, travel, lang)})
    return out, raw, (ang, org), est


def pose_tuple(r, ang, org):
    return (-ang + r['giro_grau'], org, tuple(r['translacao_unica_mm']))


class CustomStop(Exception):
    def __init__(self, status, code, **kw):
        super().__init__(code)
        self.status, self.code, self.kw = status, code, kw


def custom_cuff(rd, grid_json, out_dir, name, scan_sha, std_size, manual_note=None, progress=None):
    """Legacy gerador_scan steps 3-6 (width in the grid W 80-84, dorsal profile, prediction, parameter files), same
    arithmetic, with the fast searches.  Writes parametros.json, dorso_<name>.json, mao_faixa_cad.npz,
    gerador_relatorio.json into out_dir.  Raises CustomStop when no custom cuff should be made."""
    out_dir = Path(out_dir)
    est, nos, ang, org = cad_sections(rd)
    left = rd.side == 'left'
    d_g, grade = G.carregar_grade(grid_json)
    half, travel = d_g['spring']['zone_half_width_mm'], d_g['spring']['travel_nominal_mm']
    rel = {'ferramenta': G.VERSAO + ' via ' + VERSION, 'nome': name, 'scan_sha256': scan_sha, 'avisos': []}
    res = {}
    for W in sorted(grade):
        if progress:
            progress('W %.1f' % W)
        ab = {z: FF.FastAperture(P, half) for z, P in grade[W]['ab'].items()}
        r = FF.fit_band(est, ab, ang, org, 0.5, travel)
        if r['viavel']:
            rl = FF.fit_lateral(est, ab, ang, org, 0.5, travel)
            if rl['viavel']:
                r = dict(rl, pose_fit={k: r[k] for k in ('giro_grau', 'dx_mm', 'dy_mm', 'lateral_min_mm')})
            else:
                r = dict(r, criterio_pose=f'pose do Fit: nenhuma pose com {G.MARGEM_ASSENTO_MM} mm de margem de assento foi viável')
        res[W] = dict(r, _ab=ab)
    viable = [W for W in sorted(res) if res[W]['viavel']]
    rel['grade'] = {f'{W:.1f}': {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res[W].items()
                                 if k in ('viavel', 'rigido_min_mm', 'dorso_min_mm', 'lateral_min_mm', 'margem_mm', 'giro_grau', 'dx_mm')}
                    for W in sorted(res)}
    grid_table = [{'W': W, 'fits': bool(res[W]['viavel']), 'rigid_min': round(float(res[W].get('rigido_min_mm', float('nan'))), 3),
                   'dorsal_min': round(float(res[W].get('dorso_min_mm', float('nan'))), 3),
                   'lateral_min': round(float(res[W].get('lateral_min_mm', float('nan'))), 3)} for W in sorted(res)]
    if not viable:
        raise CustomStop('standard_only', 'custom_none', size=std_size, grid=grid_table)
    with_clear = [W for W in viable if res[W]['lateral_min_mm'] >= LATERAL_MIN]
    if not with_clear:
        raise CustomStop('standard_only', 'custom_lateral', need=LATERAL_MIN, size=std_size, grid=grid_table,
                         best=max(res[w]['lateral_min_mm'] for w in viable))
    W = with_clear[0]
    r = res[W]
    ab = r['_ab']
    meta = grade[W]['meta']
    if not all(math.isfinite(float(r[k])) for k in ('rigido_min_mm', 'dorso_min_mm', 'lateral_min_mm')):
        raise CustomStop('refused', 'custom_nan')
    notes = []
    if str(r.get('criterio_pose', '')).startswith('pose do Fit'):
        notes.append(('warn', 'custom_pose_fallback', {}))
    rel['escolha'] = {'W': W, 'dw': meta['dw'], 'dh': meta['dh'], 'pose_fit_para_auditoria': r.get('pose_fit'),
                      'criterio_pose': r.get('criterio_pose'), 'rigido_min_mm_bruto': float(r['rigido_min_mm']),
                      'lateral_min_mm_bruto': float(r['lateral_min_mm']),
                      'motivo': f'menor W viável com folga lateral ≥ {LATERAL_MIN} mm',
                      'pose': {k: r[k] for k in ('giro_grau', 'dx_mm', 'dy_mm')}}
    if r['rigido_min_mm'] < -0.4:
        notes.append(('warn', 'custom_palm', {'mm': -r['rigido_min_mm']}))
    if r['lateral_min_mm'] > LATERAL_MAX:
        raise CustomStop('standard_only', 'custom_narrow', lat=r['lateral_min_mm'], W=W, mx=LATERAL_MAX, size=std_size, grid=grid_table)

    # ---- dorsal profile (legacy step 4, same arithmetic)
    X = np.arange(-26, 26.001, 0.5)
    gap = G.perfil_dorsal(r['_pos'], est, ab, X)
    has = ~np.isnan(gap)
    if has.sum() < 10:
        raise CustomStop('refused', 'custom_few_points')
    gap_f = np.interp(X, X[has], gap[has])
    taper = (1 - G.smooth(-X, 12., 24.)) * (1 - G.smooth(X, 20., 26.))
    from scipy.ndimage import gaussian_filter1d
    low = np.clip(gap_f + PRELOAD, 0, DORSAL_LIMIT) * taper
    low = gaussian_filter1d(low, 1.5 / 0.5) * taper
    low = np.where(has, low, 0.0)
    xt = np.arange(-39., 39.001, 0.1)
    raise_T4 = -np.interp(xt, G.x_T4_de_xW(X, meta['dw']), low, left=0, right=0)
    raise_T4 = np.clip(raise_T4, G.FAIXA_B['dorso_min'], G.FAIXA_B['dorso_max'])
    out_dir.mkdir(parents=True, exist_ok=True)
    dorso_json = out_dir / f'dorso_{name}.json'
    dorso_json.write_text(json.dumps({'origem': G.VERSAO, 'W': W, 'pose': rel['escolha']['pose'], 'precarga_mm': PRELOAD,
                                      'limite_mm': DORSAL_LIMIT, 'x_T4': xt.round(3).tolist(), 'raise': raise_T4.round(4).tolist(),
                                      'X_W': X.tolist(), 'folga_antes': np.round(gap, 3).tolist(), 'abaixamento': low.round(3).tolist()}),
                          encoding='utf8')

    # ---- prediction with the lowered face (legacy step 5)
    def lowered(Aab):
        o = {}
        for z, A in Aab.items():
            c = np.array(A.poly.exterior.coords)
            sel = (c[:, 1] > A.ymeio) & (np.abs(c[:, 0] - A.xc) <= half)
            c[sel, 1] -= np.interp(c[sel, 0], X, low)
            o[z] = FF.FastAperture(Polygon(c).buffer(0), half)
        return o
    ab2 = lowered(ab)
    G0 = G.matriz_folga_dorsal(r['_pos'], est, ab, X)
    G1 = G.matriz_folga_dorsal(r['_pos'], est, ab2, X)
    before, after = G.resumo_folga(G0), G.resumo_folga(G1)
    after_raw = G.resumo_folga(G1, bruto=True)
    rel['previsao_dorso'] = {'antes': before, 'depois': after, 'depois_bruto': after_raw, 'curso_mm': travel,
                             'abaixamento_max_mm': round(float(low.max()), 2),
                             'nota': 'folga vertical face da mola × topo da mão, |x| ≤ 26, nos 5 cortes, mesma pose; CAD rígido'}
    if not all(math.isfinite(v) for v in after_raw.values()) or not np.all(np.isfinite(raise_T4)):
        raise CustomStop('refused', 'custom_nan')
    if after_raw['maior_sobreposicao_mm'] > travel:
        raise CustomStop('refused', 'custom_overlap')

    # ---- outputs (same files as the legacy generator, so the build step and the audit trail are unchanged)
    param = {'id': f'scan_{name}', 'W': W, 'dw': meta['dw'], 'dh': meta['dh'], 'esquerda': left,
             'rotulo': 'L' if left else 'R', 'dorso': dorso_json.name, 'faixa_B': G.FAIXA_B,
             'grade_sha256_variante': meta['sha256'], 'folga_lateral_mm': LATERAL_MIN, 'curso_mm': travel,
             'manifesto': {'scan_sha256': scan_sha,
                           'gerador_scan_sha256': sha256_file(G.__file__), 'freshcuff_fit_sha256': sha256_file(F.__file__),
                           'fc_core_sha256': sha256_file(__file__), 'fc_fastfit_sha256': sha256_file(FF.__file__),
                           'grade_aberturas_sha256': sha256_file(grid_json),
                           'dorso_sha256': sha256_file(dorso_json), 'orientacao_manual': manual_note}}
    (out_dir / 'parametros.json').write_text(json.dumps(param, indent=2, ensure_ascii=False), encoding='utf8')
    rel['resultado'] = 'PARAMETROS_PRONTOS_PARA_CAD'
    rel['parametros_cad'] = param
    np.savez(out_dir / 'mao_faixa_cad.npz', **{f'est{i}': np.array(e['poligono'].exterior.coords) for i, e in enumerate(est)},
             **{f'pos{i}': P for i, P in enumerate(r['_pos'])}, z_cuff=np.array([e['z_cuff'] for e in est]),
             dz=np.array([e['dz'] for e in est]), angulo=ang, origem=np.array(org), W=W, esquerda=left, X=X, abaixamento=low)
    (out_dir / 'gerador_relatorio.json').write_text(json.dumps(rel, indent=2, ensure_ascii=False, default=str), encoding='utf8')
    return {'W': W, 'meta': meta, 'r': r, 'ab': ab, 'ab2': ab2, 'X': X, 'gap': gap, 'low': low, 'before': before, 'after': after,
            'after_raw': after_raw, 'travel': travel, 'param': param, 'rel': rel, 'est': est, 'ang': ang, 'org': org,
            'notes': notes, 'grid': grid_table}


# ============================================================================================ build
LOCKS = [  # (legacy id, string key, measurement key, limit text, unit)
    ('G00', 'lock_finite', None, 'finite', ''),
    ('G01', 'lock_closed', 'pecas', 'closed, 1 piece', ''),
    ('G03', 'lock_height', 'faixa_z', '25.95 - 26.05', 'mm'),
    ('G04', 'lock_leaf', 'lamina_min', '>= 0.85', 'mm'),
    ('G05', 'lock_sidegap', 'vao_lateral_min', '>= 0.6', 'mm'),
    ('G06', 'lock_fasteners', 'fix_desloc_max_mm', 'displacement 0; variant deviation <= 0.1 mm3', 'mm'),
    ('G07', 'lock_slit', 'fenda', '1.95 - 2.25', 'mm'),
    ('G08', 'lock_shoulder', 'aro_ombro_min', '>= 7.2', 'mm'),
    ('G13', 'lock_size', 'maior', '<= 160', 'mm'),
]
VERIFY_KEYS = {'previsão de folga dorsal não confirmada no STL': 'ver_gap',
               'sobreposição dorsal acima do curso da mola': 'ver_overlap',
               'parte rígida invade além da hipótese de pele': 'ver_rigid',
               'folga lateral abaixo do mínimo': 'ver_lateral',
               'a mão não assenta com as aberturas do STL (pose nova)': 'ver_seat',
               'métrica ausente ou não finita (NaN/inf) na conferência': 'ver_nan'}


def displace_fast(V, flat, dorsal):
    """== campo_dorso.deslocar, evaluated once per distinct (x, y): the cuff is close to an extrusion, so most
    vertices share their (x, y) with others.  Bit-identical result."""
    import campo_dorso as C
    xy = np.ascontiguousarray(V[:, :2])
    key = xy.view([('x', xy.dtype), ('y', xy.dtype)]).ravel()
    _, first, inv = np.unique(key, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    Wu, best = C.deslocar(V[first], flat, dorsal)
    W = V.copy()
    W[:, :2] = Wu[inv, :2]
    return W, best[inv]


def apply_dorsal(mesh, dw, dh, dorso, left, base_json):
    """== gerador_web.aplicar_dorso (same contours, same field), with displace_fast."""
    import trimesh
    import nucleo_r08a as N
    import gerador_web as GW
    N.carregar_base(base_json)

    def cont(d):
        s0 = N.contornos_com_dorso(d) if d is not None else N.contours()
        s = {k: N.deformar(v, dw, dh) for k, v in s0.items()}
        return N.restaura_lamina(s, s0)
    a, b = cont(None), cont(dorso)
    V = mesh.vertices.copy()
    if left:
        V[:, 0] *= -1
    W, _ = displace_fast(np.asarray(V), a, b)
    if left:
        W[:, 0] *= -1
    d = np.linalg.norm(W - mesh.vertices, axis=1)
    x0, x1, y0, y1 = GW.FIX_BOX
    fix = (mesh.vertices[:, 0] > x0) & (mesh.vertices[:, 0] < x1) & (mesh.vertices[:, 1] > y0) & (mesh.vertices[:, 1] < y1)
    return trimesh.Trimesh(W, mesh.faces, process=False), float(d[fix].max()) if fix.any() else 0.0, float(d.max())


def verify_against_scan(case_dir, stl):
    """== conferir_cuff_gerado.main (same measurements, same verdict function), with the fast pose search.
    Returns (report dict, openings of the generated solid, same-pose sections)."""
    import trimesh
    import conferir_cuff_gerado as CC
    from shapely.geometry import Point
    case_dir, stl = Path(case_dir), Path(stl)
    d = np.load(case_dir / 'mao_faixa_cad.npz')
    n = len(d['z_cuff'])
    zc = [float(z) for z in d['z_cuff']]
    est = [dict(poligono=Polygon(d[f'est{i}']), z_cuff=zc[i], dz=float(d['dz'][i]), estado='completo') for i in range(n)]
    pos = [d[f'pos{i}'] for i in range(n)]
    m = trimesh.load(stl)
    if bool(d['esquerda']):
        m.vertices[:, 0] *= -1
        m.invert()
    ab = {}
    for z in sorted(set(zc)):
        s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        g = min([Polygon(v[:, :2]) for v in s.discrete if len(v) > 3 and Polygon(v[:, :2]).is_valid and Polygon(v[:, :2]).contains(Point(0, 0))],
                key=lambda g: g.area).simplify(0.02)
        ab[z] = FF.FastAperture(g, 26)
    X = d['X']
    Ga = G.matriz_folga_dorsal(pos, est, ab, X)
    rig = [ab[e['z_cuff']].medir(P) for P, e in zip(pos, est)]
    a_raw = G.resumo_folga(Ga, bruto=True)
    a_raw.update({'rigido_min_mm': float(min(r[0] for r in rig)), 'lateral_min_mm': float(min(r[2] for r in rig))})
    b = FF.fit_band(est, ab, float(d['angulo']), tuple(d['origem']), 0.5, 2.1)
    Gb = G.matriz_folga_dorsal(b['_pos'], est, ab, X)
    rel_g = json.loads((case_dir / 'gerador_relatorio.json').read_text(encoding='utf8'))
    prev = rel_g['previsao_dorso']
    prev_raw = prev.get('depois_bruto') or prev['depois']
    par = json.loads((case_dir / 'parametros.json').read_text(encoding='utf8'))
    show = lambda dct, k=3: {kk: (round(v, k) if isinstance(v, float) and math.isfinite(v) else v) for kk, v in dct.items()}
    v = CC.veredito(a_raw, bool(b['viavel']), prev_raw, par)
    out = {'stl': stl.name, 'stl_sha256': sha256_file(stl), 'parametros_sha256': sha256_file(case_dir / 'parametros.json'),
           'a_mesma_pose': show(a_raw, 2), 'a_mesma_pose_bruto': a_raw,
           'b_pose_nova': dict(show({k: b[k] for k in ('viavel', 'rigido_min_mm', 'dorso_min_mm', 'lateral_min_mm', 'giro_grau', 'dx_mm', 'dy_mm')}),
                               **G.resumo_folga(Gb)),
           'previsto_depois': prev['depois'],
           'dif_folga_media_corte_proximo_mm': None if v['dif_folga_bruta_mm'] is None else round(v['dif_folga_bruta_mm'], 3),
           'veredito': v}
    out = CC.json_seguro(out)
    return out, ab, [(zc[i], pos[i]) for i in range(n)]
