# -*- coding: utf-8 -*-
"""FreshCuff ScanMade - mesh utilities (load, units, components, fast plane sections, display decimation, GLB export).

Runs unchanged in CPython and in Pyodide (numpy, scipy, shapely, trimesh only; no rtree / manifold3d /
fast_simplification).  Sections are numerically identical to ``freshcuff_fit.corte`` (same trimesh routine), but only
the faces that straddle the plane are handed to trimesh, so a section of an 800k-face scan costs a few milliseconds.
"""
from types import SimpleNamespace
import numpy as np
import trimesh
from shapely.geometry import Polygon

# plausible length (mm) of the longest side of a hand scan, with or without part of the forearm
_LEN_MIN, _LEN_MAX = 120.0, 650.0
_UNITS = (('mm', 1.0), ('cm', 10.0), ('m', 1000.0), ('inch', 25.4))


# ------------------------------------------------------------------ units
def guess_units(extent_max, mm_per_unit=None):
    """Return (mm_per_unit, units_name, confidence 0-1, rule).  Same thresholds as the legacy reader whenever the
    legacy choice is plausible for a hand; only implausible cases (e.g. inches) are decided differently."""
    if mm_per_unit is not None:
        if not (np.isfinite(mm_per_unit) and mm_per_unit > 0):
            raise ValueError('mm_per_unit must be a positive number')
        name = next((n for n, k in _UNITS if abs(k - mm_per_unit) < 1e-9), 'custom')
        return float(mm_per_unit), name, 1.0, 'manual'
    ext = float(extent_max)
    legacy = ('m', 1000.0) if ext < 2.0 else ('cm', 10.0) if ext < 40.0 else ('mm', 1.0)
    fits = [(n, k) for n, k in _UNITS if _LEN_MIN <= ext * k <= _LEN_MAX]
    if any(n == legacy[0] for n, _ in fits):
        others = [n for n, _ in fits if n != legacy[0]]
        return legacy[1], legacy[0], (0.95 if not others else 0.7), 'extent'
    if fits:
        return fits[0][1], fits[0][0], 0.5, 'extent (unusual size)'
    return legacy[1], legacy[0], 0.3, 'extent (size not typical of a hand)'


# ------------------------------------------------------------------ topology
def edge_stats(F, n_vertices, return_nonmanifold=False):
    """Boundary (open) edges and non-manifold edges (shared by more than two faces).
    Returns (boundary_edges (k,2), n_nonmanifold) or, with return_nonmanifold, (boundary, n, nonmanifold_edges (j,2))."""
    F = np.asarray(F, dtype=np.int64)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e.sort(axis=1)
    key = e[:, 0] * np.int64(n_vertices) + e[:, 1]
    uniq, counts = np.unique(key, return_counts=True)
    b = uniq[counts == 1]
    boundary = np.column_stack([b // n_vertices, b % n_vertices])
    if return_nonmanifold:
        nm = uniq[counts > 2]
        return boundary, int(len(nm)), np.column_stack([nm // n_vertices, nm % n_vertices])
    return boundary, int((counts > 2).sum())


def vertex_components(F, n_vertices):
    """Connected components over shared vertices.  Returns labels per vertex (int32) and the number of components."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    F = np.asarray(F)
    i = np.concatenate([F[:, 0], F[:, 1]]).astype(np.int32)
    j = np.concatenate([F[:, 1], F[:, 2]]).astype(np.int32)
    g = coo_matrix((np.ones(len(i), dtype=np.int8), (i, j)), shape=(n_vertices, n_vertices)).tocsr()
    n, lab = connected_components(g, directed=False)
    return lab.astype(np.int32), int(n)


def keep_hand_component(V, F):
    """Keep the largest connected piece (by face count) plus pieces that belong to the same surface (>= 2 % of its
    faces and centred inside its bounding box).  Loose objects, scanner debris and far fragments are dropped.
    Returns (V, F, info)."""
    lab, n = vertex_components(F, len(V))
    if n <= 1:
        return V, F, {'components': 1, 'kept': 1, 'dropped_faces': []}
    flab = lab[F[:, 0]]
    counts = np.bincount(flab.astype(np.intp), minlength=n)
    used = np.flatnonzero(counts > 0)                       # unreferenced vertices make empty labels
    big = int(used[np.argmax(counts[used])])
    vb = V[lab == big]
    lo, hi = vb.min(0), vb.max(0)
    keep = [big]
    dropped = []
    for c in used:
        if c == big:
            continue
        if counts[c] >= 0.02 * counts[big]:
            ctr = V[lab == c].mean(0)
            if np.all(ctr >= lo) and np.all(ctr <= hi):
                keep.append(int(c))
                continue
        dropped.append(int(counts[c]))
    fmask = np.isin(flab, keep)
    F2 = F[fmask]
    used_v = np.zeros(len(V), dtype=bool)
    used_v[F2.ravel()] = True
    remap = np.cumsum(used_v) - 1
    return V[used_v], remap[F2].astype(F.dtype), {'components': int(len(used)), 'kept': len(keep),
                                                  'dropped_faces': sorted(dropped, reverse=True)[:20]}


def load_scan(path, mm_per_unit=None):
    """Load STL / OBJ / PLY / GLB, merge duplicate vertices, drop loose pieces, convert to millimetres.
    Returns (V float64 (n,3) in mm, F int32 (m,3), info dict)."""
    m = trimesh.load(str(path), process=True, force='mesh')
    if isinstance(m, trimesh.Scene):
        m = m.dump(concatenate=True)
    V = np.asarray(m.vertices, dtype=np.float64)
    F = np.asarray(m.faces, dtype=np.int32)
    if len(F) == 0:
        raise ValueError('no triangles in file')
    faces_in, verts_in = int(len(F)), int(len(V))
    V, F, comp = keep_hand_component(V, F)
    ext = V.max(0) - V.min(0)
    k, name, conf, rule = guess_units(float(ext.max()), mm_per_unit)
    V = V * k
    info = {'faces_in_file': faces_in, 'vertices_in_file': verts_in, 'faces': int(len(F)), 'vertices': int(len(V)),
            'components': comp['components'], 'components_kept': comp['kept'], 'dropped_faces': comp['dropped_faces'],
            'mm_per_unit': float(k), 'units_guess': name, 'units_confidence': float(conf), 'units_rule': rule,
            'extent_mm': [float(x) for x in (ext * k)]}
    return V, F, info


# ------------------------------------------------------------------ alignment
def pca_frame(V):
    """Same alignment as the legacy reader: x = width, y = thickness, z = length.  Returns (R (3,3), centre)."""
    centre = V.mean(0)
    v = V - centre
    _, E = np.linalg.eigh(np.cov(v.T))
    E = E[:, ::-1]
    R = np.stack([E[:, 1], E[:, 2], E[:, 0]])
    if np.linalg.det(R) < 0:
        R[0] *= -1
    return R, centre


# ------------------------------------------------------------------ sections
class Slicer:
    """Plane sections z = const of a triangle mesh.  ``section(z)`` returns exactly what the legacy
    ``freshcuff_fit.corte(mesh, z)`` returns (closed polygons sorted by area, open length), with a cache."""

    def __init__(self, V, F):
        self.V = np.ascontiguousarray(V, dtype=np.float64)
        self.F = np.ascontiguousarray(F)
        self._prep()

    def _prep(self):
        z = self.V[:, 2]
        fz = z[self.F]
        self.fmin = fz.min(1)
        self.fmax = fz.max(1)
        self.zmin, self.zmax = float(z.min()), float(z.max())
        self._ns = SimpleNamespace(vertices=self.V, faces=self.F)
        self._cache = {}

    def flip(self, sx=1, sy=1, sz=1):
        """Multiply coordinates by +-1 per axis (in place, like the legacy reader does) and reset the cache."""
        for ax, s in enumerate((sx, sy, sz)):
            if s < 0:
                self.V[:, ax] *= -1
        self._prep()

    @property
    def bounds(self):
        return np.array([self.V.min(0), self.V.max(0)])

    def faces_between(self, z0, z1):
        return np.flatnonzero((self.fmax >= z0) & (self.fmin <= z1))

    def path(self, z):
        from trimesh import intersections
        from trimesh.path.exchange.misc import lines_to_path
        from trimesh.path.path import Path3D
        local = np.flatnonzero((self.fmin <= z + 1e-6) & (self.fmax >= z - 1e-6))
        if len(local) == 0:
            return None
        lines = intersections.mesh_plane(mesh=self._ns, plane_normal=[0, 0, 1], plane_origin=[0, 0, z],
                                         return_faces=False, local_faces=local, cached_dots=self.V[:, 2] - z)
        if len(lines) == 0:
            return None
        return Path3D(**lines_to_path(lines))

    def section(self, z, area_min=15.0):
        key = (float(z), float(area_min))
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        s = self.path(z)
        if s is None:
            out = ([], 0.0)
        else:
            polys = []
            for v in s.discrete:
                if len(v) < 4:
                    continue
                p = Polygon(v[:, :2])
                if not p.is_valid:
                    p = p.buffer(0)
                for g in getattr(p, 'geoms', [p]):
                    if g.area > area_min:
                        polys.append(g)
            opened = float(sum(s.entities[i].length(s.vertices) for i in s.dangling)) if len(s.dangling) else 0.0
            out = (sorted(polys, key=lambda p: -p.area), opened)
        self._cache[key] = out
        return out


# ------------------------------------------------------------------ display mesh
def cluster_decimate(V, F, max_faces=80000, attrs=None):
    """Vertex-clustering decimation in numpy (Pyodide has no mesh simplifier).  For display only: never used for
    measurement.  Returns (V2, F2, index of the cluster of every input vertex)."""
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F)
    if len(F) <= max_faces:
        return V.copy(), F.copy(), np.arange(len(V))
    lo = V.min(0)
    # start from the mean edge length scaled by the wanted reduction
    e = np.linalg.norm(V[F[:, 0]] - V[F[:, 1]], axis=1).mean()
    cell = e * np.sqrt(len(F) / float(max_faces)) * 1.15
    best = None
    for _ in range(6):
        q = np.floor((V - lo) / cell).astype(np.int64)
        dims = q.max(0) + 1
        key = (q[:, 0] * dims[1] + q[:, 1]) * dims[2] + q[:, 2]
        uniq, inv = np.unique(key, return_inverse=True)
        inv = inv.reshape(-1)
        F2 = inv[F]
        ok = (F2[:, 0] != F2[:, 1]) & (F2[:, 1] != F2[:, 2]) & (F2[:, 0] != F2[:, 2])
        F2 = F2[ok]
        n = len(uniq)
        fs = np.sort(F2, axis=1)
        fk = (fs[:, 0] * np.int64(n) + fs[:, 1]) * np.int64(n) + fs[:, 2]
        _, first = np.unique(fk, return_index=True)
        F2 = F2[np.sort(first)]
        best = (inv, n, F2)
        if len(F2) <= max_faces:
            break
        cell *= max(1.08, np.sqrt(len(F2) / float(max_faces)))
    inv, n, F2 = best
    cnt = np.bincount(inv.astype(np.intp), minlength=n).astype(np.float64)
    V2 = np.column_stack([np.bincount(inv.astype(np.intp), weights=V[:, k], minlength=n) / cnt for k in range(3)])
    return V2, F2.astype(np.int32), inv


def vertex_normals(V, F):
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    out = np.zeros_like(V)
    for k in range(3):
        for c in range(3):
            out[:, c] += np.bincount(F[:, k].astype(np.intp), weights=n[:, c], minlength=len(V))
    ln = np.linalg.norm(out, axis=1)
    ln[ln == 0] = 1.0
    return out / ln[:, None]


def ring_path(points, rgb):
    """Closed poly-line as a trimesh Path3D (exported as a GL line primitive)."""
    from trimesh.path.entities import Line
    from trimesh.path.path import Path3D
    P = np.asarray(points, dtype=np.float64)
    idx = np.r_[np.arange(len(P)), 0]
    col = np.array([list(rgb) + [255]], dtype=np.uint8)
    return Path3D(entities=[Line(idx)], vertices=P, colors=col, process=False)


def export_glb(path, nodes):
    """nodes: list of dicts {name, kind:'mesh'|'lines', V, F?, colors? (n,3|4 uint8) | rgb, rings?}.
    Meshes carry per-vertex colours (COLOR_0); no normals are stored (call computeVertexNormals() in three.js)."""
    scene = trimesh.Scene()
    for nd in nodes:
        if nd['kind'] == 'mesh':
            V = np.asarray(nd['V'], dtype=np.float64)
            m = trimesh.Trimesh(V, np.asarray(nd['F']), process=False)
            if nd.get('colors') is not None:
                c = np.asarray(nd['colors'], dtype=np.uint8)
            else:
                c = np.tile(np.array(nd.get('rgb', (200, 200, 200)), dtype=np.uint8), (len(V), 1))
            if c.shape[1] == 3:
                c = np.column_stack([c, np.full(len(c), 255, dtype=np.uint8)])
            m.visual = trimesh.visual.ColorVisuals(mesh=m, vertex_colors=c)
            scene.add_geometry(m, node_name=nd['name'], geom_name=nd['name'])
        else:
            for i, ring in enumerate(nd['rings']):
                nm = nd['name'] if len(nd['rings']) == 1 else '%s_%d' % (nd['name'], i)
                scene.add_geometry(ring_path(ring, nd.get('rgb', (255, 0, 0))), node_name=nm, geom_name=nm,
                                   parent_node_name=None)
    data = scene.export(file_type='glb')
    with open(path, 'wb') as f:
        f.write(data)
    return len(data)
