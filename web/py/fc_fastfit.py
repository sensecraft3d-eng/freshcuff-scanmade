# -*- coding: utf-8 -*-
"""FreshCuff Fit - fast, exact replacements for the two pose searches of the validated code:

    fit_band(...)     == freshcuff_fit.encaixe_faixa(...)      (one rigid pose for the 5 sections, 7 sizes / 9 widths)
    fit_lateral(...)  == gerador_scan.encaixe_lateral(...)     (stable pose used to choose W and draw the dorsal profile)

The searches visit the same grid of poses in the same order and apply the same acceptance and tie rules.  What changes
is only HOW the "rigid minimum" is obtained while searching:
  * the signed distance point -> opening contour is computed exactly in numpy with a per-cell list of candidate
    segments (instead of one GEOS call per pose);
  * along the seating direction (dy) the rigid minimum is 1-Lipschitz, so most dy steps are proven irrelevant and
    skipped (they can neither be the first feasible step nor beat the best margin).
The numbers that are REPORTED for the chosen pose are then measured with the original ``Abertura.medir`` (shapely), so
for the same pose they are bit-identical to the legacy output.  tests/test_fastfit.py checks pose equality.
"""
import math
import numpy as np
import freshcuff_fit as F
import gerador_scan as G

_H = 1.5        # grid cell (mm)
_PAD = 16.0     # grid margin around the opening (mm)
_K1 = 10        # candidate segments per cell in the main table
_K2 = 32        # ... in the overflow table (cells near the medial axis); beyond that, brute force


class SignedDistance:
    """Exact signed distance to a simple closed ring: > 0 inside, < 0 outside (same sign as the legacy code).
    Holds the ring and a uniform grid whose cells list every segment that can be the nearest one for a point of
    the cell (so the answer is exact, not interpolated)."""

    def __init__(self, ring_xy):
        A = np.asarray(ring_xy, dtype=np.float64)[:, :2]
        if len(A) > 1 and np.allclose(A[0], A[-1]):
            A = A[:-1]
        keep = np.ones(len(A), dtype=bool)
        keep[1:] = np.any(np.abs(np.diff(A, axis=0)) > 0, axis=1)
        A = A[keep]
        area2 = np.sum(A[:, 0] * np.roll(A[:, 1], -1) - np.roll(A[:, 0], -1) * A[:, 1])
        if area2 < 0:
            A = A[::-1].copy()
        self.A = A
        self.M = len(A)
        D = np.roll(A, -1, axis=0) - A
        self.D = D
        self.L2 = (D ** 2).sum(1)
        self.IL2 = 1.0 / self.L2
        Dp = np.roll(D, 1, axis=0)
        cr = Dp[:, 0] * D[:, 1] - Dp[:, 1] * D[:, 0]
        tol = 1e-9 * np.sqrt(self.L2 * np.roll(self.L2, 1))
        self.conv = np.where(np.abs(cr) <= tol, 0, np.sign(cr)).astype(np.int8)   # +1 convex, -1 reflex (CCW ring)
        self.conv_next = np.roll(self.conv, -1)
        self._grid()
        self._bank = None

    def _grid(self):
        A, D, IL2 = self.A, self.D, self.IL2
        self.x0 = float(A[:, 0].min() - _PAD)
        self.y0 = float(A[:, 1].min() - _PAD)
        self.nx = int(math.ceil((A[:, 0].max() + _PAD - self.x0) / _H))
        self.ny = int(math.ceil((A[:, 1].max() + _PAD - self.y0) / _H))
        cx = self.x0 + (np.arange(self.nx) + 0.5) * _H
        cy = self.y0 + (np.arange(self.ny) + 0.5) * _H
        gx = np.repeat(cx, self.ny)[:, None]
        gy = np.tile(cy, self.nx)[:, None]
        reach = 2.0 * (_H * math.sqrt(0.5)) + 1e-6
        rx = gx - A[None, :, 0]
        ry = gy - A[None, :, 1]
        t = (rx * D[None, :, 0] + ry * D[None, :, 1]) * IL2[None]
        np.clip(t, 0.0, 1.0, out=t)
        rx -= t * D[None, :, 0]
        ry -= t * D[None, :, 1]
        d = np.sqrt(rx * rx + ry * ry)
        near = d <= (d.min(1)[:, None] + reach)
        cnt = near.sum(1)
        rows, cols = np.nonzero(near)                       # row-major: candidates of each cell, in segment order
        start = np.cumsum(cnt) - cnt
        rank = np.arange(len(rows)) - start[rows]
        first = cols[start]
        ncell = len(cnt)
        t1 = np.repeat(first[:, None], _K1, axis=1).astype(np.int32)
        m = rank < _K1
        t1[rows[m], rank[m]] = cols[m]
        over = np.full(ncell, -1, dtype=np.int32)
        ov_cells = np.flatnonzero((cnt > _K1) & (cnt <= _K2))
        over[ov_cells] = np.arange(len(ov_cells))
        over[cnt > _K2] = -2
        t2 = np.repeat(first[ov_cells, None], _K2, axis=1).astype(np.int32)
        m = (over[rows] >= 0) & (rank < _K2)
        t2[over[rows[m]], rank[m]] = cols[m]
        self.t1, self.t2, self.over = t1, t2, over

    def brute(self, px, py):
        """Signed distance against every segment (fallback and reference)."""
        A, D, IL2 = self.A, self.D, self.IL2
        out = np.empty(len(px))
        step = max(1, 400000 // self.M)
        for i0 in range(0, len(px), step):
            x = px[i0:i0 + step]
            y = py[i0:i0 + step]
            rx = x[:, None] - A[None, :, 0]
            ry = y[:, None] - A[None, :, 1]
            t = (rx * D[None, :, 0] + ry * D[None, :, 1]) * IL2[None]
            np.clip(t, 0.0, 1.0, out=t)
            qx = rx - t * D[None, :, 0]
            qy = ry - t * D[None, :, 1]
            d2 = qx * qx + qy * qy
            j = d2.argmin(1)
            r = np.arange(len(j))
            tt = t[r, j]
            cross = D[j, 0] * ry[r, j] - D[j, 1] * rx[r, j]
            vs = np.where(tt <= 0.0, self.conv[j], np.where(tt >= 1.0, self.conv_next[j], 0))
            inside = np.where(vs != 0, vs < 0, cross > 0)
            dd = np.sqrt(d2[r, j])
            out[i0:i0 + step] = np.where(inside, dd, -dd)
        return out

    def query(self, px, py):
        """Signed distance for arrays of any (equal) shape."""
        if self._bank is None:
            self._bank = _Bank([self])
        shape = np.shape(px)
        px = np.ascontiguousarray(px, dtype=np.float64).ravel()
        py = np.ascontiguousarray(py, dtype=np.float64).ravel()
        b = self._bank
        cellx, okx = b.cell_x(px, np.zeros(len(px), dtype=np.intp))
        return b.query(px, py, cellx, okx, np.zeros(len(px), dtype=np.intp)).reshape(shape)


class _Bank:
    """Several SignedDistance grids (the 5 sections of one cuff) answered by ONE vectorised query."""

    def __init__(self, sdfs):
        self.sdfs = sdfs
        seg_off = np.cumsum([0] + [s.M for s in sdfs])
        cell_off = np.cumsum([0] + [len(s.over) for s in sdfs])
        ov_off = np.cumsum([0] + [len(s.t2) for s in sdfs])
        AX = np.concatenate([s.A[:, 0] for s in sdfs])
        AY = np.concatenate([s.A[:, 1] for s in sdfs])
        DX = np.concatenate([s.D[:, 0] for s in sdfs])
        DY = np.concatenate([s.D[:, 1] for s in sdfs])
        IL = np.concatenate([s.IL2 for s in sdfs])
        self.conv = np.concatenate([s.conv for s in sdfs])
        self.conv_next = np.concatenate([s.conv_next for s in sdfs])
        t1 = np.concatenate([s.t1 + seg_off[i] for i, s in enumerate(sdfs)])
        t2 = np.concatenate([s.t2 + seg_off[i] for i, s in enumerate(sdfs)])
        over = np.concatenate([np.where(s.over >= 0, s.over + ov_off[i], s.over) for i, s in enumerate(sdfs)])
        self.over = over
        self.plain = bool((over == -1).all())
        self.T1 = (t1, AX[t1], AY[t1], DX[t1], DY[t1], IL[t1])
        self.T2 = (t2, AX[t2], AY[t2], DX[t2], DY[t2], IL[t2])
        self.x0 = np.array([s.x0 for s in sdfs])
        self.y0 = np.array([s.y0 for s in sdfs])
        self.nx = np.array([s.nx for s in sdfs], dtype=np.intp)
        self.ny = np.array([s.ny for s in sdfs], dtype=np.intp)
        self.cell_off = cell_off[:-1].astype(np.intp)

    def cell_x(self, px, st):
        """Part of the cell index that depends only on x (and on the section ``st`` of each point)."""
        ix = np.floor((px - self.x0[st]) / _H).astype(np.intp)
        okx = (ix >= 0) & (ix < self.nx[st])
        return self.cell_off[st] + ix * self.ny[st], okx

    def _eval(self, T, row, x, y):
        seg, ax, ay, dx, dy, il = T
        dx = dx[row]
        dy = dy[row]
        rx = x[:, None] - ax[row]
        ry = y[:, None] - ay[row]
        t = (rx * dx + ry * dy) * il[row]
        np.clip(t, 0.0, 1.0, out=t)
        qx = rx - t * dx
        qy = ry - t * dy
        d2 = qx * qx + qy * qy
        j = d2.argmin(1)
        r = np.arange(len(j))
        tt = t[r, j]
        sg = seg[row, j]
        cross = dx[r, j] * ry[r, j] - dy[r, j] * rx[r, j]
        vs = np.where(tt <= 0.0, self.conv[sg], np.where(tt >= 1.0, self.conv_next[sg], 0))
        inside = np.where(vs != 0, vs < 0, cross > 0)
        d = np.sqrt(d2[r, j])
        return np.where(inside, d, -d)

    def query(self, px, py, cellx, okx, st):
        """px, py, cellx, okx, st: flat arrays of the same length."""
        iy = np.floor((py - self.y0[st]) / _H).astype(np.intp)
        ok = okx & (iy >= 0) & (iy < self.ny[st])
        cell = cellx + iy
        if ok.all():
            ov = self.over[cell]
            if (ov == -1).all():
                return self._eval(self.T1, cell, px, py)
        else:
            cell = np.where(ok, cell, 0)
            ov = np.where(ok, self.over[cell], -2)
        out = np.empty(len(px))
        k = np.flatnonzero(ov == -1)
        if len(k):
            out[k] = self._eval(self.T1, cell[k], px[k], py[k])
        k = np.flatnonzero(ov >= 0)
        if len(k):
            out[k] = self._eval(self.T2, ov[k], px[k], py[k])
        k = np.flatnonzero(ov == -2)
        if len(k):
            for i, s in enumerate(self.sdfs):
                kk = k[st[k] == i]
                if len(kk):
                    out[kk] = s.brute(px[kk], py[kk])
        return out


class FastAperture(F.Abertura):
    """Legacy ``Abertura`` (same attributes, same ``medir``) plus the exact numpy signed distance."""

    def __init__(self, poly, meia_zona_mola):
        super().__init__(poly, meia_zona_mola)
        if len(poly.interiors):
            raise ValueError('opening contour with holes is not supported')
        self.sdf = SignedDistance(np.asarray(poly.exterior.coords))


def as_fast(ab):
    """dict z -> Abertura  ->  dict z -> FastAperture (re-using objects that are already fast)."""
    return {z: (A if isinstance(A, FastAperture) else FastAperture(A.poly, A.meia)) for z, A in ab.items()}


# ---------------------------------------------------------------------------------------------- pose machinery
class _Pose:
    """Hand sections rotated by one angle; evaluates batches of seating heights for one lateral offset."""

    def __init__(self, pts0, ab, ref, angulo, origem, da, bank):
        a = math.radians(-angulo + da)
        c, s_ = math.cos(a), math.sin(a)
        ox, oy = origem
        self.base = []
        for P in pts0:                                    # identical arithmetic to the legacy ``transf``
            Q = P - [ox, oy]
            self.base.append(np.c_[Q[:, 0] * c - Q[:, 1] * s_, Q[:, 0] * s_ + Q[:, 1] * c])
        self.ab = ab
        self.ref = ref
        self.bank = bank
        self.xc = 0.5 * (self.base[0][:, 0].min() + self.base[0][:, 0].max())
        self.ymin = min(B[:, 1].min() for B in self.base)
        n = [len(B) for B in self.base]
        self.st = np.repeat(np.arange(len(n)), n).astype(np.intp)
        self.bx = np.concatenate([B[:, 0] for B in self.base])
        self.by = np.concatenate([B[:, 1] for B in self.base])
        self.a_xc = np.array([A.xc for A in ab])[self.st]
        self.a_meia = np.array([A.meia for A in ab])[self.st]
        self.a_w = np.array([A.W for A in ab])[self.st]
        self.a_ymeio = np.array([A.ymeio for A in ab])[self.st]
        self.sl = np.cumsum([0] + n)

    def tx(self, dx):
        return self.ref.xc - self.xc + dx

    def ty(self, dy):
        return self.ref.ybase - self.ymin + dy

    def prepare(self, dx, dys):
        """Arrays that do not depend on the subset of dy evaluated, and the exact dorsal minimum for every dy."""
        tx = self.tx(dx)
        tys = np.array([self.ty(float(d)) for d in dys])
        x = self.bx + tx
        ax = np.abs(x - self.a_xc)
        cen = ax <= self.a_meia
        lat = np.flatnonzero(ax >= self.a_w / 2 - 8)
        always = np.flatnonzero((~cen) | ((self.by + tys.max()) <= self.a_ymeio))   # rigid for every dy here
        dors = np.full(len(dys), np.inf)
        for i, A in enumerate(self.ab):                       # same arithmetic as ``Abertura.medir``
            s = slice(self.sl[i], self.sl[i + 1])
            c = cen[s]
            if c.any():
                Y = self.by[s][None, c] + tys[:, None]
                gap = np.interp(x[s][c], A.topo_x, A.topo_y)[None, :] - Y
                g = np.where(Y > A.ymeio, gap, np.inf).min(1)
                dors = np.minimum(dors, np.where(np.isinf(g), 99.0, g))
            else:
                dors = np.minimum(dors, 99.0)
        cellx, okx = self.bank.cell_x(x, self.st)
        return tys, (x, cen, lat, always, cellx, okx), dors

    def rigid(self, st, tys, idx, want_lat=False):
        """For the dy indices ``idx``: rigid minimum, always-rigid minimum, lateral minimum (over the 5 sections)."""
        x, cen, lat, always, cellx, okx = st
        n, N = len(idx), len(x)
        Y = self.by[None, :] + tys[idx][:, None]
        if n == 1:
            s = self.bank.query(x, Y[0], cellx, okx, self.st)[None, :]
        else:
            rep = lambda a: np.broadcast_to(a, (n, N)).ravel()
            s = self.bank.query(rep(x), Y.ravel(), rep(cellx), rep(okx), rep(self.st)).reshape(n, N)
        spring = cen[None, :] & (Y > self.a_ymeio[None, :])
        r = np.where(spring, np.inf, s).min(1)
        rig = np.where(np.isinf(r), 99.0, r)
        # a section without rigid points counts 99 in the legacy code; it can only matter if every section is empty
        rig0 = s[:, always].min(1) if len(always) else np.full(n, 99.0)
        latv = (s[:, lat].min(1) if len(lat) else np.full(n, 99.0)) if want_lat else None
        return rig, rig0, latv


def _seat(pose, dx, dys, off_rig, off_dors, need_best, want_lat=False):
    """First dy (in order) with min(rig + off_rig, dors + off_dors) >= 0; if none and need_best, the first dy of
    maximum margin.  Exact, but evaluates the costly rigid term only where the Lipschitz bound cannot exclude it.
    Returns (feasible, index, margin, lateral_min) or None."""
    n = len(dys)
    tys, st, dors = pose.prepare(dx, dys)
    md = dors + off_dors
    known = np.zeros(n, dtype=bool)
    rig = np.full(n, np.nan)
    rig0 = np.full(n, np.nan)
    lat = np.full(n, np.nan)
    idx = np.array([0, n - 1]) if n > 1 else np.array([0])
    pos = np.arange(n)
    rounds = 0
    while True:
        r, r0, l = pose.rigid(st, tys, idx, want_lat)
        rig[idx], rig0[idx] = r, r0
        if want_lat:
            lat[idx] = l
        known[idx] = True
        ki = np.flatnonzero(known)
        # upper bound of the rigid minimum at every dy from the evaluated ones
        delta = np.abs(tys[:, None] - tys[None, ki])
        above = ki[None, :] >= pos[:, None]                  # evaluated dy is higher (or the same)
        ub = np.where(above, rig[ki][None, :], rig0[ki][None, :]) + delta
        ub = ub.min(1)
        m_ub = np.minimum(ub + off_rig, md)
        m = np.where(known, np.minimum(rig + off_rig, md), -np.inf)
        feas = known & (m >= 0)
        jf = int(np.argmax(feas)) if feas.any() else n
        cand = np.flatnonzero((~known) & (m_ub >= 0) & (pos < jf))
        if len(cand) == 0:
            if jf < n:
                return True, jf, float(m[jf]), float(lat[jf])
            if not need_best:
                return None
            best = m[ki].max()
            cand = np.flatnonzero((~known) & (m_ub >= best))
            if len(cand) == 0:
                j = int(np.argmax(m))                         # first maximum, as the legacy loop keeps it
                return False, j, float(m[j]), float(lat[j])
        # evaluate the earliest candidate (marching toward the first feasible step), the most promising one and,
        # when the bound prunes little (flat margin), a geometrically growing spread of the others
        rounds += 1
        k = min(len(cand), 1 << rounds)
        idx = np.unique(np.r_[cand[0], cand[int(np.argmax(m_ub[cand]))], cand[np.linspace(0, len(cand) - 1, k).astype(int)]])


def _measure_legacy(pose, dx, dy):
    """The legacy ``avaliar`` for the chosen pose (shapely), so reported numbers match the validated code exactly."""
    t = np.array([pose.ref.xc - pose.xc + dx, pose.ref.ybase - pose.ymin + dy])
    r = np.array([A.medir(B + t) for B, A in zip(pose.base, pose.ab)])
    return r[:, 0].min(), r[:, 1].min(), r[:, 2].min(), r, t


def fit_band(estacoes, aberturas_t, angulo, origem, tol_pele, curso, refino=True):
    """Drop-in for ``freshcuff_fit.encaixe_faixa`` (same result dict)."""
    aberturas_t = as_fast(aberturas_t)
    pts0 = [F.amostrar(e['poligono']) for e in estacoes]
    ab = [aberturas_t[e['z_cuff']] for e in estacoes]
    ref = aberturas_t[min(aberturas_t, key=lambda z: abs(z - 13.0))]
    bank = _Bank([A.sdf for A in ab])
    ox, oy = origem
    DA, DX, DY = (-8, 8), (-5, 5), (-1, 10)
    poses = {}

    def pose(da):
        k = float(da)
        if k not in poses:
            poses[k] = _Pose(pts0, ab, ref, angulo, origem, da, bank)
        return poses[k]

    TOL_ESCOLHA = 0.1

    def escolher(cands):
        vi = [c for c in cands if c[0]]
        pool = vi if vi else cands
        mmax = max(c[1] for c in pool)
        perto = [c for c in pool if c[1] >= mmax - TOL_ESCOLHA]
        return min(perto, key=lambda c: (abs(c[2]), abs(c[3]), -c[1]))

    cands = []
    dys = np.arange(DY[0], DY[1] + 0.01, 0.5)
    for da in np.arange(DA[0], DA[1] + 0.1, 2):
        for dx in np.arange(DX[0], DX[1] + 0.1, 1):
            v, j, mg, _ = _seat(pose(da), dx, dys, tol_pele, curso, True)
            cands.append((v, mg, float(da), float(dx), float(dys[j])))
    c0 = escolher(cands)
    if refino:
        dys = np.arange(DY[0], DY[1] + 0.01, 0.1)
        for da in np.arange(max(DA[0], c0[2] - 1.5), min(DA[1], c0[2] + 1.5) + 0.01, 0.5):
            for dx in np.arange(max(DX[0], c0[3] - 0.75), min(DX[1], c0[3] + 0.75) + 0.01, 0.25):
                v, j, mg, _ = _seat(pose(da), dx, dys, tol_pele, curso, True)
                cands.append((v, mg, float(da), float(dx), float(dys[j])))
    v, mg, da, dx, dy = escolher(cands)
    p = pose(da)
    rig, dors, lat, porest, t = _measure_legacy(p, dx, dy)
    mg_legacy = min(rig + tol_pele, dors + curso)
    limites = []
    if abs(da) >= 8 - 1e-6: limites.append('giro ±8°')
    if abs(dx) >= 5 - 1e-6: limites.append('lateral ±5 mm')
    if dy >= 10 - 1e-6 or dy <= -1 + 1e-6: limites.append('altura')
    pos = [B + t for B in p.base]
    return {'viavel': bool(v), 'rigido_min_mm': float(rig), 'dorso_min_mm': float(dors),
            'lateral_min_mm': float(lat), 'margem_mm': float(mg_legacy),
            'giro_grau': float(da), 'dx_mm': float(dx), 'dy_mm': float(dy),
            'translacao_unica_mm': [float(t[0]), float(t[1])], 'origem_giro_mm': [float(ox), float(oy)],
            'busca': {'giro_grau': DA, 'lateral_mm': DX, 'altura_mm': DY, 'no_limite': limites},
            'por_estacao': [{'dz': e['dz'], 'z_cuff': e['z_cuff'], 'rigido': round(float(r[0]), 3),
                             'dorso': round(float(r[1]), 3), 'lateral': round(float(r[2]), 3)}
                            for e, r in zip(estacoes, porest)],
            '_pos': pos}


def fit_lateral(estacoes, aberturas_t, angulo, origem, tol_pele, curso):
    """Drop-in for ``gerador_scan.encaixe_lateral`` (same result dict)."""
    aberturas_t = as_fast(aberturas_t)
    pts0 = [F.amostrar(e['poligono']) for e in estacoes]
    ab = [aberturas_t[e['z_cuff']] for e in estacoes]
    ref = aberturas_t[min(aberturas_t, key=lambda z: abs(z - 13.0))]
    off_rig = tol_pele - G.MARGEM_ASSENTO_MM
    bank = _Bank([A.sdf for A in ab])
    dys_c = np.arange(-1, 10 + 1e-9, 0.25)

    def assentar_fino(p, dx):
        c = _seat(p, dx, dys_c, off_rig, curso, False, True)
        if c is None:
            return None
        dy_c, lat_c = float(dys_c[c[1]]), c[3]
        dys_f = np.arange(max(-1, dy_c - 0.25), dy_c + 1e-9, 0.05)
        if len(dys_f):
            tys, st, dors = p.prepare(dx, dys_f)
            rig, _, lat = p.rigid(st, tys, np.arange(len(dys_f)), True)
            ok = (rig + tol_pele >= G.MARGEM_ASSENTO_MM) & (dors + curso >= 0)
            if ok.any():
                j = int(np.argmax(ok))
                return float(lat[j]), float(dx), float(dys_f[j])
        return lat_c, float(dx), dy_c

    c1 = None
    for g in [0] + [s * k for k in range(1, 9) for s in (1, -1)]:
        p = _Pose(pts0, ab, ref, angulo, origem, float(g), bank)
        cands = [c for c in (assentar_fino(p, float(dx)) for dx in np.arange(-5, 5.001, 0.25)) if c]
        if cands:
            lmax = max(c[0] for c in cands)
            c1 = min([c for c in cands if c[0] >= lmax - 0.05], key=lambda c: abs(c[1]))
            da = float(g)
            break
    if c1 is None:
        return {'viavel': False}
    _, dx, dy = c1
    rig, dors, lat, _, t = _measure_legacy(p, dx, dy)
    pos = [B + t for B in p.base]
    return {'viavel': True, 'lateral_min_mm': float(lat), 'rigido_min_mm': float(rig), 'dorso_min_mm': float(dors),
            'giro_grau': da, 'dx_mm': dx, 'dy_mm': dy, 'translacao_unica_mm': [float(t[0]), float(t[1])], '_pos': pos,
            'criterio_pose': 'menor giro viável; nele, a mão centrada (maior folga lateral); palma assentada'}
