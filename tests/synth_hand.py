"""Synthetic hand-like test mesh (numpy only): an implicit union of a palm, four fingers, a thumb and a wrist stub,
voxelised at 1 mm, turned into a closed triangle surface and smoothed.  It is a RIGHT hand in the reader's "fit"
frame: fingers toward +z, back of the hand toward +y, thumb at +x.  Not anatomically accurate - it only has the
features the reader relies on (thumb separation, finger separation, arched back, flatter palm)."""
import numpy as np

KNUCKLE_Z = 42.0          # where the fingers separate (the reader places the knuckle line 6 mm before)


def _capsule(P, a, b, r):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    t = np.clip(((P - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1) - r


def implicit(P, width=81.0):
    """< 0 inside.  ``width`` = palm width (mm)."""
    x, y, z = P[:, 0], P[:, 1], P[:, 2]
    hw = width / 2.0
    # palm: flat-ish below (palm), arched above (back); slightly thicker toward the wrist
    th_top = 12.0 + 2.0 * np.clip(-z / 45.0, -1, 1)
    th_bot = 13.0 + 3.0 * np.clip(-z / 45.0, -1, 1)
    ex = np.abs(x) / hw
    top = (ex ** 2.2 + (np.maximum(y, 0) / th_top) ** 2) ** 0.5
    bot = (ex ** 4.0 + (np.maximum(-y, 0) / th_bot) ** 4) ** 0.25
    lat = np.where(y >= 0, top, bot)
    zz = np.maximum(np.abs(z) / 46.0, 0)
    palm = (np.maximum(lat, 0) ** 6 + zz ** 6) ** (1 / 6.0) - 1.0
    palm = palm * 12.0
    f = palm
    s = width / 81.0
    for xc, r, ln in ((-28.5 * s, 7.6, 62), (-9.5 * s, 8.2, 76), (9.5 * s, 8.2, 82), (28.5 * s, 7.6, 70)):
        f = np.minimum(f, _capsule(P, (xc, 2.0, 30.0), (xc, 2.0, KNUCKLE_Z + ln), r))
    f = np.minimum(f, _capsule(P, (hw - 14, -6.0, -30.0), (hw + 36, -10.0, 18.0), 10.5))      # thumb
    f = np.minimum(f, _capsule(P, (0, 0.0, -40.0), (0, 0.0, -78.0), 21.0) * 1.0)                 # wrist stub
    return f


def voxel_surface(inside, origin, h):
    """Closed quad surface of a boolean voxel grid -> (V, F triangles), outward normals."""
    O = np.pad(inside, 1)
    nx, ny, nz = O.shape
    quads = []
    idx = lambda i, j, k: (i * (ny + 1) + j) * (nz + 1) + k
    for axis in range(3):
        for sign in (1, -1):
            nb = np.roll(O, -sign, axis=axis)
            I, J, K = np.nonzero(O & ~nb)
            c = [I, J, K]
            base = [I.copy(), J.copy(), K.copy()]
            if sign == 1:
                base[axis] = base[axis] + 1
            u, v = (axis + 1) % 3, (axis + 2) % 3
            def corner(du, dv):
                p = [base[0].copy(), base[1].copy(), base[2].copy()]
                p[u] = p[u] + du
                p[v] = p[v] + dv
                return idx(p[0], p[1], p[2])
            q = np.stack([corner(0, 0), corner(1, 0), corner(1, 1), corner(0, 1)], axis=1)
            if sign == -1:
                q = q[:, ::-1]
            quads.append(q)
    Q = np.concatenate(quads)
    used, inv = np.unique(Q.ravel(), return_inverse=True)
    Q = inv.reshape(-1, 4)
    k = used % (nz + 1)
    j = (used // (nz + 1)) % (ny + 1)
    i = used // ((nz + 1) * (ny + 1))
    V = origin + (np.stack([i, j, k], axis=1) - 1) * h
    F = np.concatenate([Q[:, [0, 1, 2]], Q[:, [0, 2, 3]]])
    return V.astype(np.float64), F.astype(np.int32)


def smooth(V, F, iters=12, lam=0.55, mu=-0.57):
    """Taubin smoothing (no shrink) with numpy."""
    n = len(V)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    deg = np.bincount(e[:, 0], minlength=n).astype(float)
    for it in range(iters * 2):
        acc = np.zeros_like(V)
        for c in range(3):
            acc[:, c] = np.bincount(e[:, 0], weights=V[e[:, 1], c], minlength=n)
        L = acc / deg[:, None] - V
        V = V + (lam if it % 2 == 0 else mu) * L
    return V


def make_hand(width=81.0, h=1.0):
    """Returns (V, F): closed, single-piece right hand, millimetres, fit frame."""
    lo = np.array([-width / 2 - 8, -24.0, -84.0])
    hi = np.array([width / 2 + 56, 22.0, KNUCKLE_Z + 96.0])
    n = np.ceil((hi - lo) / h).astype(int)
    gx, gy, gz = [lo[a] + (np.arange(n[a]) + 0.5) * h for a in range(3)]
    X, Y, Z = np.meshgrid(gx, gy, gz, indexing='ij')
    P = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    inside = (implicit(P, width) < 0).reshape(n)
    V, F = voxel_surface(inside, lo, h)
    return smooth(V, F), F


def rotation(seed):
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    if np.linalg.det(q) < 0:
        q[:, 0] *= -1
    return q


def write_mesh(path, V, F):
    import trimesh
    trimesh.Trimesh(V, F, process=False).export(str(path))
    return path
