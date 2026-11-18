import numpy as np, trimesh

def dividir_arestas(v, f, marcar):
    """Divide ao meio as arestas marcadas (conforme: cada aresta partilhada é dividida nas duas faces). Retorna (v, f)."""
    e = np.sort(np.stack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]], 1).reshape(-1, 2), axis=1)
    ue, inv = np.unique(e, axis=0, return_inverse=True); inv = inv.reshape(-1, 3)
    sp = marcar(v[ue[:, 0]], v[ue[:, 1]])
    if not sp.any(): return v, f, 0
    mid = np.full(len(ue), -1); idx = np.where(sp)[0]
    mid[idx] = len(v) + np.arange(len(idx)); v = np.vstack([v, (v[ue[idx, 0]] + v[ue[idx, 1]]) / 2])
    out = []
    for fi, (a, b, c) in enumerate(f):
        m = mid[inv[fi]]; ab, bc, ca = m
        n = int(ab >= 0) + int(bc >= 0) + int(ca >= 0)   # (np.bool_ + np.bool_ é OU lógico)
        if n == 0: out.append((a, b, c)); continue
        if n == 3: out += [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]; continue
        # rotaciona para que a primeira aresta dividida seja ab
        verts = [a, b, c]; mids = [ab, bc, ca]
        r = [i for i in range(3) if mids[i] >= 0][0] if n == 1 else [i for i in range(3) if mids[i] < 0][0]
        if n == 1:
            A, B, C = verts[r], verts[(r+1) % 3], verts[(r+2) % 3]; M = mids[r]
            out += [(A, M, C), (M, B, C)]
        else:  # n == 2: a aresta não dividida é r
            A, B, C = verts[r], verts[(r+1) % 3], verts[(r+2) % 3]   # aresta AB não dividida
            Mbc, Mca = mids[(r+1) % 3], mids[(r+2) % 3]
            out += [(Mca, Mbc, C)]
            # quadrilátero A,B,Mbc,Mca: diagonal mais curta
            if np.linalg.norm(v[A]-v[Mbc]) < np.linalg.norm(v[B]-v[Mca]): out += [(A, B, Mbc), (A, Mbc, Mca)]
            else: out += [(A, B, Mca), (B, Mbc, Mca)]
    return v, np.array(out), len(idx)

def refinar_xy(m, max_xy=1.0, y_min=1.0, iters=12):
    """Refina só arestas com projeção no plano xy > max_xy na região dorsal (o campo do dorso só depende de x,y)."""
    v, f = m.vertices.copy(), m.faces.copy()
    marcar = lambda p, q: (np.linalg.norm((p - q)[:, :2], axis=1) > max_xy) & (np.maximum(p[:, 1], q[:, 1]) > y_min)
    for _ in range(iters):
        v, f, n = dividir_arestas(v, f, marcar)
        if n == 0: break
    return trimesh.Trimesh(v, f, process=False)
