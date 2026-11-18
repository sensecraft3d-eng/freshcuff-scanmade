#!/usr/bin/env python3
"""
FreshCuff Fit · nível 1 · v0.4 · 15/11/2026 · SenseCraft

Lê o scan 3D de uma mão (STL, OBJ, PLY, GLB), acha a linha dos nós, mede a volta como uma fita
e compara a FAIXA de 26 mm (5 cortes, numa única posição rígida comum) com as aberturas locais
dos 7 tamanhos do FreshCuff R08A.

Saídas em --saida: fit_relatorio.json, fit_relatorio.md, fit_figura.png

O que o resultado É: compatibilidade geométrica de cortes rígidos do scan com o contorno CAD,
sob duas hipóteses declaradas (pele cede até --tol-pele mm; o dorso central pode subir até
2,1 mm num envelope hipotético da mola). O que NÃO É: pressão, conforto, retenção, uso molhado,
simulação elástica da mola, ou decisão de tamanho. Quem decide é a prova dos anéis e do cuff.
"""
import argparse, hashlib, json, math, platform, sys
_INTERNO = None
from pathlib import Path
import numpy as np
import trimesh
import shapely
from shapely.geometry import Polygon, LineString, box
from shapely import affinity

VERSAO = 'FreshCuff Fit nível 1 v0.4.3 (UTF-8 no console; expõe _INTERNO; 2ª pista de dorso pelo polegar)'
AQUI = Path(__file__).resolve().parent
TABELA_CM = [(1, None, 18.2), (2, 18.2, 19.3), (3, 19.3, 20.4), (4, 20.4, 21.6),
             (5, 21.6, 22.7), (6, 22.7, 23.8), (7, 23.8, None)]
ANEIS = {1: '1–2', 2: '1–3', 3: '2–4', 4: '3–5', 5: '4–6', 6: '5–7', 7: '6–7'}


class Inconclusivo(Exception):
    def __init__(self, msg, causa='marcos'):
        super().__init__(msg)
        self.causa = causa      # malha | orientacao | marcos | escala


# ================================================================ malha e cortes
def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def carregar(caminho, mm_por_unidade=None):
    m = trimesh.load(str(caminho), process=True, force='mesh')
    if isinstance(m, trimesh.Scene):
        m = m.dump(concatenate=True)
    partes = m.split(only_watertight=False)
    descartadas = []
    if len(partes) > 1:
        maior = max(len(p.faces) for p in partes)
        descartadas = [len(p.faces) for p in partes if len(p.faces) < 0.02 * maior]
        m = trimesh.util.concatenate([p for p in partes if len(p.faces) >= 0.02 * maior])
    ext = float(np.max(m.extents))
    if mm_por_unidade is not None:
        if not (np.isfinite(mm_por_unidade) and mm_por_unidade > 0):
            raise SystemExit('--mm-por-unidade precisa ser número positivo')
        escala, regra = mm_por_unidade, 'manual'
    elif ext < 2.0:
        escala, regra = 1000.0, 'parece metros'
    elif ext < 40.0:
        escala, regra = 10.0, 'parece centímetros'
    else:
        escala, regra = 1.0, 'parece milímetros'
    m.apply_scale(escala)
    info = {'partes_descartadas_faces': descartadas, 'escala_inicial': escala, 'regra_escala': regra,
            'estanque': bool(m.is_watertight)}
    return m, info


def corte(m, z, area_min=15.0):
    """Polígonos fechados e trechos abertos (buracos da malha) do corte em z."""
    s = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if s is None:
        return [], 0.0
    polys = []
    for v in s.discrete:                      # trimesh: só caminhos fechados
        if len(v) < 4:
            continue
        p = Polygon(v[:, :2])
        if not p.is_valid:
            p = p.buffer(0)
        for g in getattr(p, 'geoms', [p]):
            if g.area > area_min:
                polys.append(g)
    # trechos abertos (bordas de buraco) ficam em s.dangling
    aberto = float(sum(s.entities[i].length(s.vertices) for i in s.dangling)) if len(s.dangling) else 0.0
    return sorted(polys, key=lambda p: -p.area), aberto


def alinhar_pca(m):
    centro = m.vertices.mean(0)
    v = m.vertices - centro
    _, E = np.linalg.eigh(np.cov(v.T))
    E = E[:, ::-1]
    R = np.stack([E[:, 1], E[:, 2], E[:, 0]])     # x largura, y espessura, z comprimento
    if np.linalg.det(R) < 0:
        R[0] *= -1
    m = m.copy()
    m.vertices = v @ R.T
    return m, R, centro


def lado_dos_dedos(m):
    zmin, zmax = m.bounds[0, 2], m.bounds[1, 2]
    L = zmax - zmin

    def multiplos(z0, z1):
        return sum(max(0, len(corte(m, z)[0]) - 1) for z in np.linspace(z0, z1, 10))
    baixo = multiplos(zmin + 0.05 * L, zmin + 0.35 * L)
    alto = multiplos(zmax - 0.35 * L, zmax - 0.05 * L)
    return baixo, alto


def perfil(m, passo=1.5):
    zmin, zmax = m.bounds[0, 2], m.bounds[1, 2]
    rows = []
    for z in np.arange(zmin + 3, zmax - 3, passo):
        ps, aberto = corte(m, z)
        if not ps:
            rows.append({'z': float(z), 'vazio': True, 'aberto_mm': aberto})
            continue
        p = ps[0]
        b = p.bounds
        rows.append({'z': float(z), 'vazio': False, 'area': p.area, 'largura': b[2] - b[0],
                     'espessura': b[3] - b[1], 'n': len(ps), 'fita': p.convex_hull.length,
                     'aberto_mm': aberto, 'pecas': [(q.area, q.centroid.x, q.bounds) for q in ps[1:4]]})
    return rows


def perfil_fino(m, z0, z1, passo=0.5):
    """Cobertura da faixa: cortes a cada 0,5 mm entre z0 e z1 (vazio ou borda aberta = lacuna)."""
    out = []
    for z in np.arange(z0, z1 + 1e-9, passo):
        ps, aberto = corte(m, z)
        out.append({'z': float(z), 'vazio': not ps, 'aberto_mm': aberto})
    return out


def achar_marcos(rows, z_nos=None, z_polegar=None, recuo=6.0):
    """Quedas bruscas de largura do pedaço principal (> 15%): 1ª = polegar se separa,
    2ª = dedos se separam. Precisa das duas, ou dos marcos manuais."""
    ok = [r for r in rows if not r['vazio']]
    quedas = []
    for a, b in zip(ok, ok[1:]):
        if a['largura'] > 50 and b['largura'] < 0.85 * a['largura'] and b['n'] >= 2:
            if not quedas or b['z'] - quedas[-1] > 4.5:
                quedas.append(b['z'])
    info = {'quedas_z': [round(q, 1) for q in quedas], 'recuo_mm': recuo}
    if z_nos is None:
        if len(quedas) < 2:
            buracos = [r['z'] for r in rows if r['aberto_mm'] > 5]
            if buracos:
                raise Inconclusivo(f'Achei {len(quedas)} separação(ões), e {len(buracos)} cortes têm borda aberta '
                                   f'(z {min(buracos):.0f} a {max(buracos):.0f}): buraco na malha.', 'malha')
            raise Inconclusivo(
                f'Achei {len(quedas)} separação(ões) no perfil; preciso de 2 (polegar e dedos). '
                'Causas comuns: dedos colados no scan, polegar junto da mão, malha aberta. '
                'Ver fit_falha.png e informar --z-nos e --z-polegar.')
        z_pol = quedas[0] if z_polegar is None else z_polegar
        z_nos = quedas[1] - recuo
        info['metodo'] = f'automático: 2ª separação − {recuo:.0f} mm'
    else:
        z_pol = z_polegar if z_polegar is not None else (quedas[0] if quedas and quedas[0] < z_nos else None)
        info['metodo'] = 'manual (--z-nos)'
    info['z_nos'] = round(z_nos, 1)
    info['z_polegar'] = None if z_pol is None else round(z_pol, 1)
    return z_nos, z_pol, info


def flechas(p):
    """Dorso nos nós é arqueado; palma mais plana/côncava. Retorna (flecha_topo, flecha_fundo)."""
    x0, y0, x1, y1 = p.bounds
    topo, fundo = [], []
    for x in np.linspace(x0 + 0.2 * (x1 - x0), x1 - 0.2 * (x1 - x0), 21):
        inter = p.intersection(LineString([(x, y0 - 5), (x, y1 + 5)]))
        if not inter.is_empty:
            topo.append(inter.bounds[3]); fundo.append(inter.bounds[1])
    if len(topo) < 6:
        return 0.0, 0.0
    t, f = np.array(topo), np.array(fundo)
    n = len(t); mid = slice(n // 3, 2 * n // 3)
    return float(t[mid].mean() - 0.5 * (t[0] + t[-1])), float(0.5 * (f[0] + f[-1]) - f[mid].mean())


def angulo_largura(p):
    r = np.array(p.minimum_rotated_rectangle.exterior.coords)[:4]
    lados = [r[1] - r[0], r[2] - r[1]]
    v = max(lados, key=lambda q: np.hypot(*q))
    a = math.degrees(math.atan2(v[1], v[0]))
    return (a + 90) % 180 - 90


# ================================================================ aberturas e encaixe
def carregar_aberturas(caminho):
    d = json.load(open(caminho, encoding='utf8'))
    abert = {}
    for t, v in d['sizes'].items():
        abert[int(t)] = {float(z): Polygon(c['contour']) for z, c in v['z'].items()}
    return d, abert


class Abertura:
    """Uma abertura local (um corte do cuff) com zonas: mola central no dorso, resto rígido."""

    def __init__(self, poly, meia_zona_mola):
        self.poly = poly
        b = poly.bounds
        self.xc = 0.5 * (b[0] + b[2]); self.ymeio = 0.5 * (b[1] + b[3])
        self.W = b[2] - b[0]; self.ybase = b[1]
        self.meia = meia_zona_mola
        xs = np.linspace(self.xc - meia_zona_mola, self.xc + meia_zona_mola, 105)
        ys = []
        for x in xs:
            inter = poly.exterior.intersection(LineString([(x, self.ymeio), (x, b[3] + 5)]))
            ys.append(max(g.y for g in getattr(inter, 'geoms', [inter])) if not inter.is_empty else b[3])
        self.topo_x, self.topo_y = xs, np.array(ys)

    def medir(self, P):
        """P: pontos (N,2) do contorno da mão já posicionados. Retorna mínimos (mm)."""
        x, y = P[:, 0], P[:, 1]
        na_mola = (np.abs(x - self.xc) <= self.meia) & (y > self.ymeio)
        d = shapely.distance(self.poly.exterior, shapely.points(P))
        dentro = shapely.contains_xy(self.poly, x, y)
        s = np.where(dentro, d, -d)
        rig = s[~na_mola].min() if (~na_mola).any() else 99.0
        if na_mola.any():
            gap = np.interp(x[na_mola], self.topo_x, self.topo_y) - y[na_mola]   # vertical
            dors = gap.min()
        else:
            dors = 99.0
        lat = s[np.abs(x - self.xc) >= self.W / 2 - 8]
        return rig, dors, (lat.min() if lat.size else 99.0)


def amostrar(p, passo=1.0):
    ext = p.exterior
    n = max(80, int(ext.length / passo))
    return np.array([ext.interpolate(i / n, normalized=True).coords[0] for i in range(n)])


def encaixe_faixa(estacoes, aberturas_t, angulo, origem, tol_pele, curso, refino=True):
    """UMA transformação rígida (giro da em torno da origem comum + translação única) para TODOS os cortes.
    As aberturas ficam nas coordenadas do CAD; a translação de referência usa a abertura do meio (z = 13).
    Viável: em todos os cortes, parte rígida invade ≤ tol_pele e dorso central sobe ≤ curso (envelope).
    Para cada giro e lateral, a palma assenta (menor altura viável: a mola empurra a mão para baixo);
    entre essas, a de maior margem (empate dentro de 0,1 mm → menor giro, depois menor deslocamento);
    sem viável, a de menor violação."""
    pts0 = [amostrar(e['poligono']) for e in estacoes]
    ab = [aberturas_t[e['z_cuff']] for e in estacoes]
    ref = aberturas_t[min(aberturas_t, key=lambda z: abs(z - 13.0))]
    ox, oy = origem
    DA, DX, DY = (-8, 8), (-5, 5), (-1, 10)

    def transf(P, da):
        a = math.radians(-angulo + da)
        c, s_ = math.cos(a), math.sin(a)
        Q = P - [ox, oy]
        return np.c_[Q[:, 0] * c - Q[:, 1] * s_, Q[:, 0] * s_ + Q[:, 1] * c]

    def translacao(base, dx, dy):
        xc = 0.5 * (base[0][:, 0].min() + base[0][:, 0].max())     # corte dos nós centrado
        ymin = min(B[:, 1].min() for B in base)                     # palma mais baixa na base
        return np.array([ref.xc - xc + dx, ref.ybase - ymin + dy])

    def avaliar(da, dx, dy):
        base = [transf(P, da) for P in pts0]
        t = translacao(base, dx, dy)
        r = np.array([A.medir(B + t) for B, A in zip(base, ab)])
        return r[:, 0].min(), r[:, 1].min(), r[:, 2].min(), r

    def margem(res):
        return min(res[0] + tol_pele, res[1] + curso)

    def assentar(da, dx, dys):
        melhor_local = None
        for dy in dys:
            res = avaliar(da, dx, dy)
            if margem(res) >= 0:
                return True, dy, res
            if melhor_local is None or margem(res) > margem(melhor_local[1]):
                melhor_local = (dy, res)
        return False, melhor_local[0], melhor_local[1]

    TOL_ESCOLHA = 0.1   # mm: margens a menos de 0,1 mm da melhor contam como empate; aí vence menor giro/deslocamento

    def escolher(cands):
        vi = [c for c in cands if c[0]]
        pool = vi if vi else cands
        mmax = max(c[1] for c in pool)
        perto = [c for c in pool if c[1] >= mmax - TOL_ESCOLHA]
        return min(perto, key=lambda c: (abs(c[2]), abs(c[3]), -c[1]))

    cands = []
    for da in np.arange(DA[0], DA[1] + 0.1, 2):
        for dx in np.arange(DX[0], DX[1] + 0.1, 1):
            v, dy, res = assentar(da, dx, np.arange(DY[0], DY[1] + 0.01, 0.5))
            cands.append((v, margem(res), float(da), float(dx), float(dy), res))
    c0 = escolher(cands)
    if refino:
        for da in np.arange(max(DA[0], c0[2] - 1.5), min(DA[1], c0[2] + 1.5) + 0.01, 0.5):
            for dx in np.arange(max(DX[0], c0[3] - 0.75), min(DX[1], c0[3] + 0.75) + 0.01, 0.25):
                v, dy, res = assentar(da, dx, np.arange(DY[0], DY[1] + 0.01, 0.1))
                cands.append((v, margem(res), float(da), float(dx), float(dy), res))
    v, mg, da, dx, dy, res = escolher(cands)
    melhor = ((int(v), mg), da, dx, dy, res)
    k, da, dx, dy, (rig, dors, lat, porest) = melhor
    limites = []
    if abs(da) >= 8 - 1e-6: limites.append('giro ±8°')
    if abs(dx) >= 5 - 1e-6: limites.append('lateral ±5 mm')
    if dy >= 10 - 1e-6 or dy <= -1 + 1e-6: limites.append('altura')
    base = [transf(P, da) for P in pts0]
    t = translacao(base, dx, dy)
    pos = [B + t for B in base]
    return {'viavel': bool(k[0] == 1), 'rigido_min_mm': float(rig), 'dorso_min_mm': float(dors),
            'lateral_min_mm': float(lat), 'margem_mm': float(k[1]),
            'giro_grau': float(da), 'dx_mm': float(dx), 'dy_mm': float(dy),
            'translacao_unica_mm': [float(t[0]), float(t[1])], 'origem_giro_mm': [float(ox), float(oy)],
            'busca': {'giro_grau': DA, 'lateral_mm': DX, 'altura_mm': DY, 'no_limite': limites},
            'por_estacao': [{'dz': e['dz'], 'z_cuff': e['z_cuff'], 'rigido': round(float(r[0]), 3),
                             'dorso': round(float(r[1]), 3), 'lateral': round(float(r[2]), 3)}
                            for e, r in zip(estacoes, porest)],
            '_pos': pos}


RESOLUCAO = 0.05   # mm: abaixo disso, tratado como contato


def classificar(r, tol, curso):
    """Usa os valores brutos e o MESMO critério da busca (r['viavel'])."""
    rig, dors = r['rigido_min_mm'], r['dorso_min_mm']
    if not r['viavel']:
        motivo = []
        if rig < -tol: motivo.append(f'invasão rígida {-rig:.2f} mm > {tol} mm')
        if dors < -curso: motivo.append(f'dorso sobe {-dors:.2f} mm > {curso} mm')
        return 'nenhuma posição compatível encontrada na busca (' + '; '.join(motivo) + ')'
    partes = []
    if rig < -RESOLUCAO:
        partes.append(f'interferência rígida {-rig:.2f} mm, dentro da hipótese de pele')
    elif rig < 0:
        partes.append('contato rígido (abaixo da resolução de 0,05 mm)')
    else:
        partes.append('sem interferência rígida')
    if dors < -RESOLUCAO:
        partes.append(f'dorso sobe {-dors:.2f} mm, dentro do envelope hipotético da mola')
    elif dors < RESOLUCAO:
        partes.append('dorso encostando na mola')
    else:
        partes.append(f'folga dorsal {dors:.1f} mm')
    return 'compatível na hipótese: ' + '; '.join(partes)


# ================================================================ figura
def figura(m, rows, marcos, estacoes, aberturas, resultados, saida, titulo, nota, exploratorio=False):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(17, 9.5))
    gs = fig.add_gridspec(2, 7, height_ratios=[1.3, 1])
    ax0 = fig.add_subplot(gs[0, 0:2])
    v = m.vertices[np.random.default_rng(0).choice(len(m.vertices), min(40000, len(m.vertices)), replace=False)]
    dors = v[v[:, 1] > np.median(v[:, 1])]
    ax0.scatter(dors[:, 0], dors[:, 2], s=.2, c=dors[:, 1], cmap='Greys')
    for e in estacoes:
        ax0.axhline(e['z'], color='orange', lw=.8)
    ax0.axhline(marcos['z_nos'], color='r', lw=1.5)
    if marcos.get('z_polegar') is not None:
        ax0.axhline(marcos['z_polegar'], color='g', ls='--', lw=1)
    ax0.set_aspect('equal'); ax0.set_title('Vista do dorso: vermelho = nós; laranja = 5 cortes da faixa', fontsize=8)
    ax0.set_xlabel('mm'); ax0.set_ylabel('punho → dedos (mm)')
    ax1 = fig.add_subplot(gs[0, 2:5])
    ok = [r for r in rows if not r['vazio']]
    ax1.plot([r['z'] for r in ok], [r['largura'] for r in ok], label='largura do pedaço principal')
    ax1.plot([r['z'] for r in ok], [r['fita'] / 2.4 for r in ok], ':', label='fita ÷ 2,4')
    ax1.axvline(marcos['z_nos'], color='r', lw=2, label='nós')
    ax1.axvspan(marcos['z_nos'] - 26, marcos['z_nos'], color='orange', alpha=.15, label='faixa 26 mm')
    for q in marcos['quedas_z']:
        ax1.axvline(q, color='0.5', ls=':', lw=1)
    if marcos.get('z_polegar') is not None:
        ax1.axvline(marcos['z_polegar'], color='g', ls='--', label='polegar se separa')
    ax1.legend(fontsize=7); ax1.grid(alpha=.3); ax1.set_xlabel('punho → dedos (mm)'); ax1.set_title('Perfil', fontsize=9)
    ax2 = fig.add_subplot(gs[0, 5:7])
    for e in estacoes:
        if 'original' in e:
            x, y = e['original'].exterior.xy
            ax2.plot(x, y, lw=.7, ls='--', color='tab:red')
        if 'poligono' not in e:
            continue
        x, y = e['poligono'].exterior.xy
        ax2.plot(x, y, lw=1.6 if e['dz'] == 0 else .7, color='k' if e['dz'] == 0 else '0.6')
    ax2.set_aspect('equal'); ax2.set_title('5 cortes da faixa (preto = nós; tracejado = parte removida), DORSO ↑', fontsize=8)
    for i, t in enumerate(sorted(aberturas)):
        ax = fig.add_subplot(gs[1, i])
        r = resultados[t]
        if r is None:
            ax.axis('off'); continue
        A = aberturas[t][estacoes[0]['z_cuff']]   # abertura distal (nós)
        x, y = A.exterior.xy; ax.plot(x, y, color='0.3')
        cor = '#2e7d32' if r['viavel'] else '#c62828'
        for P, e in zip(r['_pos'], estacoes):
            ax.plot(np.r_[P[:, 0], P[0, 0]], np.r_[P[:, 1], P[0, 1]], color=cor, lw=1.2 if e['dz'] == 0 else .5)
        ax.set_aspect('equal'); ax.axis('off')
        ax.set_title(f"T{t}{' (EXPLORATÓRIO)' if exploratorio else ''}: {'compatível' if r['viavel'] else 'sem posição compatível'}\n"
                     f"rígido {r['rigido_min_mm']:+.1f} · dorso {r['dorso_min_mm']:+.1f} · lado {r['lateral_min_mm']:+.1f}",
                     fontsize=7)
    import textwrap
    fig.suptitle(titulo + '\n' + '\n'.join(textwrap.wrap(nota, 190)), fontsize=9)
    fig.subplots_adjust(left=.04, right=.98, top=.88, bottom=.03, hspace=.35, wspace=.3)
    fig.savefig(saida, dpi=120)
    plt.close(fig)


def figura_perfil(rows, saida):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    ok = [r for r in rows if not r['vazio']]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot([r['z'] for r in ok], [r['largura'] for r in ok], label='largura')
    ax.plot([r['z'] for r in ok], [r['n'] * 10 for r in ok], '.', label='nº de pedaços × 10')
    ax.legend(); ax.grid(alpha=.3); ax.set_xlabel('z (mm) — use estes valores em --z-nos / --z-polegar')
    fig.savefig(saida, dpi=110); plt.close(fig)


# ================================================================ principal
def tamanho_pela_fita(cm):
    for t, lo, hi in TABELA_CM:
        if (lo is None or cm >= lo) and (hi is None or cm < hi):
            return t


def fronteira(cm, margem=0.3):
    for t, lo, hi in TABELA_CM:
        for lim in (lo, hi):
            if lim is not None and abs(cm - lim) <= margem:
                return lim
    return None


def preparar(m, a, rows_cache=None):
    rows = perfil(m)
    return rows


def falha(m, saida, nome, rel, e, rows=None):
    """Mesmo na falha: vista da mão com o eixo z (para escolher marcos) e o perfil, e instrução pela causa."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    instr = {
        'malha': 'Precisa de NOVA CAPTURA (palma e dorso fechados). Marcos manuais não resolvem.',
        'orientacao': 'Conforme a mensagem: lado dos dedos com --dedos alto|baixo, ou dorso com --inverter-dorso / --manter-dorso. Ver fit_falha.png.',
        'marcos': 'Informe --z-nos e --z-polegar lendo o eixo z de fit_falha.png (mesma orientação desta execução; '
                  'repita os mesmos --dedos/--inverter-dorso/--mm-por-unidade).',
        'escala': 'Conferir --fita-cm e a escala do scan (--mm-por-unidade pela referência rígida medida).',
    }[e.causa]
    fig, (a0, a1) = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={'width_ratios': [1, 2]})
    v = m.vertices[np.random.default_rng(0).choice(len(m.vertices), min(40000, len(m.vertices)), replace=False)]
    a0.scatter(v[:, 0], v[:, 2], s=.2, c=v[:, 1], cmap='Greys')
    a0.set_aspect('equal'); a0.set_ylabel('z (mm) — eixo usado por --z-nos/--z-polegar'); a0.grid(alpha=.3)
    a0.set_title('Mão (vista de cima) no eixo desta execução', fontsize=9)
    rows = rows if rows is not None else perfil(m)
    ok = [r for r in rows if not r['vazio']]
    if ok:
        a1.plot([r['z'] for r in ok], [r['largura'] for r in ok], label='largura do maior pedaço')
        a1.plot([r['z'] for r in ok], [r['n'] * 10 for r in ok], '.', label='nº de pedaços × 10')
    a1.grid(alpha=.3); a1.legend(); a1.set_xlabel('z (mm)')
    fig.suptitle(f'INCONCLUSIVO ({e.causa}): {e}\n{instr}', fontsize=8)
    fig.savefig(saida / 'fit_falha.png', dpi=110); plt.close(fig)
    rel.update({'conclusao': f'INCONCLUSIVO ({e.causa}): {e}', 'o_que_fazer': instr})
    (saida / 'fit_relatorio.json').write_text(json.dumps(rel, indent=2, ensure_ascii=False, default=str), encoding='utf8')
    (saida / 'fit_relatorio.md').write_text(f'# FreshCuff Fit · {nome}\n\n**INCONCLUSIVO ({e.causa}).** {e}\n\n'
                                            f'O que fazer: {instr}\n', encoding='utf8')
    print(f'INCONCLUSIVO ({e.causa}):', e, '\n', instr)
    return rel


def checar_z(m, z, nome_param):
    if z is None:
        return
    if not np.isfinite(z) or not (m.bounds[0, 2] + 2 < z < m.bounds[1, 2] - 2):
        raise Inconclusivo(f'{nome_param}={z} fora da mão (z entre {m.bounds[0,2]:.0f} e {m.bounds[1,2]:.0f}).', 'marcos')
    ps, aberto = corte(m, z)
    if aberto > 5:
        raise Inconclusivo(f'{nome_param}={z}: corte com {aberto:.0f} mm de borda aberta (buraco na malha).', 'malha')
    if not ps:
        raise Inconclusivo(f'{nome_param}={z}: sem corte fechado nessa posição.', 'marcos')


def corte_valido(m, z, contexto):
    """Maior polígono fechado do corte em z, ou Inconclusivo com causa."""
    ps, aberto = corte(m, z)
    if aberto > 5:
        raise Inconclusivo(f'{contexto} (z={z:.1f}): {aberto:.0f} mm de borda aberta (buraco na malha).', 'malha')
    if not ps:
        raise Inconclusivo(f'{contexto} (z={z:.1f}): sem corte fechado.', 'marcos')
    return ps[0]


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):          # console do Windows em cp1252 (revisão GPT B03)
        try: _s.reconfigure(encoding='utf-8')
        except Exception: pass
    ap = argparse.ArgumentParser(description=VERSAO)
    ap.add_argument('scan')
    ap.add_argument('--saida', default='fit_saida')
    ap.add_argument('--nome', default=None)
    ap.add_argument('--fita-cm', type=float, default=None, help='volta medida com fita nos nós, na mesma pose do scan')
    ap.add_argument('--escalar-pela-fita', action='store_true', help='scan sem escala confiável: usa --fita-cm para fixar a escala; só a FORMA vem do scan')
    ap.add_argument('--mm-por-unidade', type=float, default=None)
    ap.add_argument('--dedos', choices=['auto', 'alto', 'baixo'], default='auto', help='lado dos dedos no eixo z (ver fit_falha.png)')
    ap.add_argument('--z-nos', type=float, default=None, help='marco manual: linha dos nós (eixo z da execução)')
    ap.add_argument('--z-polegar', type=float, default=None, help='marco manual: onde o polegar se separa')
    ap.add_argument('--recuo-mm', type=float, default=6.0, help='nós = separação dos dedos − recuo (padrão 6)')
    ap.add_argument('--inverter-dorso', action='store_true')
    ap.add_argument('--manter-dorso', action='store_true', help='confirma que o +y atual já é o dorso (resolve a ambiguidade)')
    ap.add_argument('--cuff-distal', choices=['z26', 'z0'], default='z26', help='qual ponta do cuff fica nos nós (padrão z=25,8)')
    ap.add_argument('--tol-pele', type=float, default=0.5, help='invasão rígida aceita como pele cedendo (mm, provisório)')
    ap.add_argument('--tol-fita-cm', type=float, default=0.6, help='diferença fita scan × medida que suspende a recomendação')
    ap.add_argument('--aberturas', default=str(AQUI / 'cuff_openings_R08A_v2.json'))
    a = ap.parse_args(argv)
    saida = Path(a.saida); saida.mkdir(parents=True, exist_ok=True)
    nome = a.nome or Path(a.scan).stem
    if a.fita_cm is not None and not (np.isfinite(a.fita_cm) and 10 < a.fita_cm < 40):
        raise SystemExit('--fita-cm fora do razoável (10–40 cm)')
    if a.escalar_pela_fita and a.fita_cm is None:
        raise SystemExit('--escalar-pela-fita precisa de --fita-cm')
    if not (0 <= a.tol_pele <= 3 and 0 < a.recuo_mm < 30):
        raise SystemExit('--tol-pele (0–3) ou --recuo-mm (0–30) fora do razoável')

    rel = {'ferramenta': VERSAO, 'script_sha256': sha256(__file__), 'nome': nome, 'scan': str(a.scan),
           'scan_sha256': sha256(a.scan), 'aberturas': a.aberturas, 'aberturas_sha256': sha256(a.aberturas),
           'parametros': {k: v for k, v in vars(a).items()},
           'versoes': {'python': platform.python_version(), 'trimesh': trimesh.__version__,
                       'shapely': shapely.__version__, 'numpy': np.__version__}}
    m, info_malha = carregar(a.scan, a.mm_por_unidade)
    m, R, centro_pca = alinhar_pca(m)
    rel['malha'] = info_malha
    if a.escalar_pela_fita:          # passo adimensional antes de qualquer limiar em mm
        f0 = 185.0 / float(m.extents[2]); m.apply_scale(f0); info_malha['pre_normalizacao'] = round(f0, 6)
    avisos = []
    rows = None
    try:
        rows0 = perfil(m, passo=4.0)
        vazios = sum(r['vazio'] or r['aberto_mm'] > 5 for r in rows0) / max(1, len(rows0))
        if vazios > 0.4:
            raise Inconclusivo(f'Malha aberta: {vazios:.0%} dos cortes não fecham ou têm borda aberta.', 'malha')
        baixo, alto = lado_dos_dedos(m)
        if a.dedos == 'auto':
            if baixo == alto:
                raise Inconclusivo(f'Lado dos dedos ambíguo (pedaços separados: ponta baixa {baixo} × alta {alto}).', 'orientacao')
            gira = baixo > alto
        else:
            gira = (a.dedos == 'baixo')
        if gira:   # 180° em torno de y: dedos passam para z+
            m.vertices[:, [0, 2]] *= -1
        rows = perfil(m)
        checar_z(m, a.z_nos, '--z-nos'); checar_z(m, a.z_polegar, '--z-polegar')
        z_nos, z_pol, marcos = achar_marcos(rows, a.z_nos, a.z_polegar, a.recuo_mm)
        if a.escalar_pela_fita:
            f_total = 1.0
            for it in range(4):
                fita_atual = corte_valido(m, z_nos, 'Calibração pela fita').convex_hull.length
                f = a.fita_cm * 10 / fita_atual
                if abs(f - 1) < 1e-3:
                    break
                m.apply_scale(f); f_total *= f
                rows = perfil(m)
                z_nos, z_pol, marcos = achar_marcos(rows, None if a.z_nos is None else a.z_nos * f_total,
                                                    None if a.z_polegar is None else a.z_polegar * f_total, a.recuo_mm)
            residuo = corte_valido(m, z_nos, 'Calibração pela fita').convex_hull.length / 10 - a.fita_cm
            info_malha['escala_pela_fita'] = round(f_total, 6); info_malha['residuo_fita_cm'] = round(residuo, 3)
            info_malha['iteracoes_escala'] = it + 1
            info_malha['mm_por_unidade_efetivo'] = round(info_malha['escala_inicial'] * f0 * f_total, 8)
            if abs(residuo) > 0.1:
                raise Inconclusivo(f'Escala pela fita não convergiu (resíduo {residuo:+.2f} cm).', 'escala')
        ps_nos, aberto_nos = corte(m, z_nos)
        if not ps_nos:
            raise Inconclusivo('Corte nos nós vazio.', 'marcos')
        if aberto_nos > 5:
            raise Inconclusivo(f'Corte nos nós tem {aberto_nos:.0f} mm de borda aberta (buraco na malha).', 'malha')
        nos = ps_nos[0]
        f_marcos = f_total if a.escalar_pela_fita else 1.0
        ref_marcos = {'fator_final_sobre_referencial_de_marcos': round(f_marcos, 6),
                      'z_nos_no_referencial_de_marcos': round(z_nos / f_marcos, 2),
                      'z_polegar_no_referencial_de_marcos': None if z_pol is None else round(z_pol / f_marcos, 2),
                      'nota': ('com --escalar-pela-fita, --z-nos/--z-polegar são lidos no referencial de marcos '
                               '(o da fit_falha.png deste modo), não no eixo da fit_figura.png; para corrigir marcos '
                               'com a figura final, rode com --mm-por-unidade = mm_por_unidade_efetivo e sem --escalar-pela-fita')
                      if a.escalar_pela_fita else 'referencial de marcos = eixo da fit_figura.png'}
        ft, ff = flechas(nos)
        # 2ª pista (v0.4.2): o polegar fica do lado da palma. Compara o centro do polegar separado com o da palma.
        pista_polegar = None
        if z_pol is not None:
            r_sep0 = min((r for r in rows if not r['vazio'] and r['z'] >= z_pol and r.get('pecas')), key=lambda r: r['z'], default=None)
            if r_sep0:
                _, _, bp = max(r_sep0['pecas'], key=lambda q: q[0])
                palma = corte(m, r_sep0['z'])[0][0]
                dy_pol = 0.5 * (bp[1] + bp[3]) - palma.centroid.y
                if abs(dy_pol) > 3:
                    pista_polegar = dy_pol < 0          # True: polegar abaixo → dorso em +y
        pista_flechas = ft >= ff
        if (not a.inverter_dorso) and (not a.manter_dorso) and pista_polegar is not None and pista_polegar != pista_flechas:
            raise Inconclusivo(f'Dorso × palma ambíguo: o arco dos nós indica um lado (flechas {ft:.1f} × {ff:.1f} mm) e a posição '
                               f'do polegar indica o outro. Veja fit_falha.png (o polegar fica do lado da palma) e use '
                               f'--inverter-dorso se o dorso estiver para baixo, ou --manter-dorso se estiver para cima.', 'orientacao')
        dorso_pos = (pista_flechas ^ a.inverter_dorso) if not a.manter_dorso else True
        if abs(ft - ff) < 1.0 and not a.inverter_dorso:
            avisos.append(f'Dorso × palma pouco claro (flechas {ft:.1f} × {ff:.1f} mm): conferir "DORSO ↑" na figura.')
        if not dorso_pos:
            m.vertices[:, [0, 1]] *= -1
            nos = corte_valido(m, z_nos, 'Corte nos nós')
            rows = perfil(m)
    except Inconclusivo as e:
        return falha(m, saida, nome, rel, e, rows)

    # ---------------- fita
    fita_scan = nos.convex_hull.length / 10
    t_scan = tamanho_pela_fita(fita_scan)
    t_manual = tamanho_pela_fita(a.fita_cm) if a.fita_cm else None
    discrep = None if a.fita_cm is None else fita_scan - a.fita_cm
    suspensa = (a.fita_cm is not None and not a.escalar_pela_fita and abs(discrep) > a.tol_fita_cm)
    if suspensa:
        avisos.append(f'Fita do scan ({fita_scan:.2f}) e fita medida ({a.fita_cm:.2f}) diferem {discrep:+.2f} cm: '
                      'recomendação automática suspensa (conferir escala, pose, posição da fita).')

    # ---------------- estações da faixa (uma relação axial: z_mão = z_nós − distância ao plano distal do cuff)
    d_ab, ab_raw = carregar_aberturas(a.aberturas)
    meia = d_ab['spring']['zone_half_width_mm']; curso = d_ab['spring']['travel_nominal_mm']
    zc = sorted(float(z) for z in d_ab['stations_z'])
    z_dist = zc[-1] if a.cuff_distal == 'z26' else zc[0]
    angulo = angulo_largura(nos)
    origem = (nos.centroid.x, nos.centroid.y)
    lado_polegar = x_lim = None
    if z_pol is not None:
        r_sep = min((r for r in rows if not r['vazio'] and r['z'] >= z_pol and r.get('pecas')),
                    key=lambda r: r['z'], default=None)
        if r_sep:
            _, cx_pol, _ = max(r_sep['pecas'], key=lambda q: q[0])
            ps = corte(m, r_sep['z'])[0]
            b = ps[0].bounds
            lado_polegar = 'neg' if cx_pol < ps[0].centroid.x else 'pos'
            x_lim = (b[0] - 1.0) if lado_polegar == 'neg' else (b[2] + 1.0)
    estacoes = []
    for zcf in sorted(zc, key=lambda z: abs(z - z_dist)):          # do plano distal (nós) para o punho
        dz = -abs(z_dist - zcf)
        z = z_nos + dz
        ps, aberto = corte(m, z)
        e = {'dz': round(dz, 2), 'z': round(z, 2), 'z_cuff': zcf, 'aberto_mm': round(aberto, 1)}
        if not ps:
            e['estado'] = 'sem corte'; estacoes.append(e); continue
        p = ps[0]
        if aberto > 5:
            e['estado'] = 'corte aberto (buraco na malha)'
        elif z_pol is not None and z < z_pol:
            if lado_polegar:
                caixa = box(x_lim, -1e3, 1e3, 1e3) if lado_polegar == 'neg' else box(-1e3, -1e3, x_lim, 1e3)
                p2 = p.intersection(caixa)
                p2 = max(getattr(p2, 'geoms', [p2]), key=lambda g: g.area)
                e['estado'] = 'recorte exploratório: base do polegar removida'
                e['largura_original_mm'] = round(p.bounds[2] - p.bounds[0], 1)
                e['original'] = p
                p = p2
            else:
                e['estado'] = 'polegar unido, lado desconhecido'
        else:
            e['estado'] = 'completo'
        e['poligono'] = p
        e['largura_mm'] = round(p.bounds[2] - p.bounds[0], 1); e['espessura_mm'] = round(p.bounds[3] - p.bounds[1], 1)
        estacoes.append(e)
    cx = [e['poligono'].centroid.x for e in estacoes if e.get('estado') == 'completo']
    deriva = (max(cx) - min(cx)) if len(cx) > 1 else 0.0
    if deriva > 8:
        avisos.append(f'Os cortes da faixa se deslocam {deriva:.0f} mm de lado ao longo de 26 mm: a faixa pode estar oblíqua à mão '
                      '(punho dobrado, antebraço puxando o eixo). Conferir na figura; o protocolo pede punho reto.')
    z_ini, z_fim = min(e['z'] for e in estacoes) - 0.5, max(e['z'] for e in estacoes) + 0.5
    lacunas = [round(r['z'], 1) for r in perfil_fino(m, z_ini, z_fim) if r['vazio'] or r['aberto_mm'] > 5]
    completos = all(e['estado'] == 'completo' for e in estacoes) and not lacunas
    exploratorio = (not completos) and not lacunas and all(e['estado'] in ('completo', 'recorte exploratório: base do polegar removida') for e in estacoes)
    determinacao = ('determinado' if completos else
                    f'não determinado (buraco na malha entre os cortes, z ≈ {lacunas[0]} a {lacunas[-1]})' if lacunas else
                    'não determinado; resultado com recorte exploratório do polegar' if exploratorio else
                    'não determinado (faixa incompleta no scan)')
    if a.cuff_distal == 'z0':
        # cuff virado de ponta: rotação de 180° em torno do eixo dorso-palma (z → −z e x → −x), det = +1
        ab_raw = {t: {z: affinity.scale(P, xfact=-1, yfact=1, origin=(0, 0)) for z, P in zz.items()} for t, zz in ab_raw.items()}
    aberturas = {t: {z: Abertura(P, meia) for z, P in zz.items()} for t, zz in ab_raw.items()}
    resultados = {}
    for t in sorted(aberturas):
        if not (completos or exploratorio):
            resultados[t] = None; continue
        r = encaixe_faixa(estacoes, aberturas[t], angulo, origem, a.tol_pele, curso)
        r['classe'] = classificar(r, a.tol_pele, curso)
        if r['busca']['no_limite']:
            r['classe'] += ' [melhor posição no limite da busca: ' + ', '.join(r['busca']['no_limite']) + ']'
        resultados[t] = r
    t_geo = next((t for t in sorted(resultados) if resultados[t] and resultados[t]['viavel']), None) if completos else None
    t_exp = next((t for t in sorted(resultados) if resultados[t] and resultados[t]['viavel']), None) if exploratorio else None

    # ---------------- conclusão
    t_ref = t_manual if (a.fita_cm and not suspensa) else t_scan
    lim = fronteira(a.fita_cm if a.fita_cm else fita_scan)
    c = []
    if suspensa:
        c.append('Recomendação suspensa: fita do scan e fita medida discordam.')
    else:
        orig = 'fita medida' if a.fita_cm else 'fita do scan'
        c.append(f'Pela {orig}: T{t_ref} (provar anéis {ANEIS[t_ref]}).'
                 + (f' A ≤ 0,3 cm da fronteira de {lim:.1f} cm: provar também o vizinho.' if lim else ''))
    if completos:
        if t_geo is None:
            c.append('Forma da faixa (determinado): nenhuma posição compatível encontrada na busca realizada, em nenhum tamanho.')
        else:
            rel_t = '' if suspensa else (' (igual à fita)' if t_geo == t_ref else ' (menor que pela fita)' if t_geo < t_ref
                                         else ' (maior que pela fita)')
            c.append(f'Forma da faixa (determinado): menor tamanho compatível com as hipóteses = T{t_geo}{rel_t}'
                     + (' — escala em dúvida, não usar.' if suspensa else '.'))
    elif exploratorio:
        c.append('Forma da faixa: não determinada (parte da faixa cai na base do polegar). '
                 + (f'Só como exploração, com o polegar recortado: T{t_exp}.' if t_exp else
                    'Mesmo com o recorte exploratório do polegar, nenhuma posição compatível foi encontrada.'))
    else:
        c.append('Forma da faixa: não determinada (faixa incompleta no scan).')
    c.append('Decidir só depois de provar os anéis e vestir o cuff (retenção e conforto); o scan não decide sozinho.')
    conclusao = ' '.join(c)
    if a.escalar_pela_fita:
        avisos.append('Escala vinda da fita medida: a fita do scan não é independente; só a forma é informativa.')
    if info_malha['partes_descartadas_faces']:
        avisos.append(f"Descartei {len(info_malha['partes_descartadas_faces'])} pedaços soltos pequenos da malha.")

    limpar = lambda r: None if r is None else {k: (round(v, 3) if isinstance(v, float) else v)
                                               for k, v in r.items() if k != '_pos'}
    rel.update({
        'conclusao': conclusao, 'avisos': avisos,
        'alinhamento': {'R_pca': np.round(R, 6).tolist(), 'dedos_girados_180_em_y': bool(gira), 'pedacos_ponta_baixa': baixo,
                        'pedacos_ponta_alta': alto, 'flecha_topo_mm': round(ft, 2), 'flecha_fundo_mm': round(ff, 2), 'pista_polegar_dorso_em_y_mais': pista_polegar,
                        'dorso_girado_180_em_z': bool(not dorso_pos), 'angulo_largura_grau': round(angulo, 3),
                        'centro_pca_removido_mm': [float(x) for x in centro_pca],
                        'transformacao': 'p_final = S·Rz(dorso)·Ry(dedos)·R_pca·(s0·p_original − centro_pca); '
                                         's0 = escala_inicial; S = pre_normalizacao·escala_pela_fita (modo fita) ou 1; '
                                         'Ry(dedos): x,z → −x,−z se dedos_girados; Rz(dorso): x,y → −x,−y se dorso_girado',
                        **marcos},
        'referencial_marcos': ref_marcos,
        'nos': {'fita_scan_cm': round(fita_scan, 3), 'largura_mm': round(nos.bounds[2] - nos.bounds[0], 1),
                'espessura_mm': round(nos.bounds[3] - nos.bounds[1], 1), 'borda_aberta_mm': round(aberto_nos, 1)},
        'fita_medida_cm': a.fita_cm, 'diferenca_scan_menos_medida_cm': None if discrep is None else round(discrep, 3),
        'tamanho_pela_fita_scan': t_scan, 'tamanho_pela_fita_medida': t_manual,
        'faixa': {'determinacao': determinacao, 'deriva_lateral_mm': round(deriva, 1),
                  'estacoes': [{k: v for k, v in e.items() if k not in ('poligono', 'original')} for e in estacoes]},
        'recomendacao_suspensa': bool(suspensa),
        'menor_tamanho_compativel_faixa': None if suspensa else t_geo,
        'diagnostico_forma_com_escala_em_duvida': t_geo if suspensa else None,
        'exploratorio_polegar_recortado': t_exp,
        'encaixe_por_tamanho': {t: limpar(r) for t, r in resultados.items()},
        'hipoteses': {'tol_pele_mm': a.tol_pele, 'resolucao_mm': RESOLUCAO, 'mola_curso_nominal_mm': curso,
                      'mola_zona_meia_largura_mm': meia,
                      'mola': 'zona central do dorso pode subir até o curso nominal (envelope hipotético, sem simulação elástica)',
                      'posicao': 'giro em torno do centroide do corte dos nós + uma translação única para os 5 cortes; '
                                 'aberturas nas coordenadas do CAD; palma assentada'},
    })
    (saida / 'fit_relatorio.json').write_text(json.dumps(rel, indent=2, ensure_ascii=False), encoding='utf8')
    figura(m, rows, marcos, estacoes, {t: {z: A.poly for z, A in aa.items()} for t, aa in aberturas.items()},
           resultados, saida / 'fit_figura.png', f'FreshCuff Fit · {nome} · fita no scan {fita_scan:.2f} cm',
           conclusao, exploratorio)
    md = [f'# FreshCuff Fit · {nome}', '', f'**{conclusao}**', ''] + [f'> Aviso: {x}' for x in avisos] + ['',
          f'- Fita nos nós no scan: {fita_scan:.2f} cm → T{t_scan}' + (f' · fita medida {a.fita_cm:.2f} cm → T{t_manual} (diferença {discrep:+.2f} cm)' if a.fita_cm else ''),
          f"- Nós: largura {rel['nos']['largura_mm']} mm · espessura {rel['nos']['espessura_mm']} mm · faixa: {determinacao}",
          (f"- Referencial de marcos (modo fita): z_nós = {ref_marcos['z_nos_no_referencial_de_marcos']}, "
           f"z_polegar = {ref_marcos['z_polegar_no_referencial_de_marcos']}; mm_por_unidade_efetivo = {info_malha.get('mm_por_unidade_efetivo')}"
           if a.escalar_pela_fita else ''), '',
          ('Tabela **exploratória** (polegar recortado; não vale como resultado):' if exploratorio else ''),
          '| Tamanho | Resultado | Rígido mín (mm) | Dorso mín (mm) | Lateral mín (mm) |', '|---|---|---|---|---|']
    for t in sorted(resultados):
        r = resultados[t]
        md.append(f'| T{t} | não avaliado |  |  |  |' if r is None else
                  f"| T{t} | {r['classe']} | {r['rigido_min_mm']:+.2f} | {r['dorso_min_mm']:+.2f} | {r['lateral_min_mm']:+.2f} |")
    md += ['', 'Rígido: negativo = invade a parte rígida (aceito até a hipótese de pele). Dorso: negativo = sobe a zona central '
           'da mola (aceito até o curso nominal, envelope hipotético). Resultado geométrico; não mede pressão, conforto nem retenção.',
           'Conferir na figura: vermelho na linha dos nós, cortes laranja onde o cuff fica, DORSO ↑.']
    (saida / 'fit_relatorio.md').write_text('\n'.join(md), encoding='utf8')
    print('\n'.join(md))
    global _INTERNO
    _INTERNO = dict(m=m, estacoes=estacoes, nos=nos, angulo=angulo, origem=origem, z_nos=z_nos, z_pol=z_pol,
                    lado_polegar=lado_polegar, determinacao=determinacao, lacunas=lacunas, fita_scan=fita_scan)
    return rel


if __name__ == '__main__':
    main()
