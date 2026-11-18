#!/usr/bin/env python3
"""
FreshCuff · gerador de cuff sob medida POR SCAN · R01 (v0.1) · 16/11/2026 · SenseCraft
Decisão de Pedro (16/11): o gerador só aceita scan; validação com a mão dele (V1).

Fluxo (camada CAD/TARGET; nada aqui é PHYSICAL ACTUAL):
 1. FreshCuff Fit v0.4.1 lê o scan: escala, malha, orientação, marcos e 5 cortes da faixa. Usa a ponta
    distal do cuff em z = 0,2 (convenção do CAD: polegar em −x, +z para o punho).
 2. Lado da mão: declarado (--lado) e conferido pelo lado do polegar no scan. Mão esquerda é espelhada para
    direita na análise, e o CAD sai com --esquerda.
 3. Largura: varre a grade pré-verificada W 80–84 (faixa B). Para cada W, uma posição rígida comum aos
    5 cortes (Fit). Escolhe o menor W viável com folga lateral ≥ --folga-lateral-mm (provisória).
    Se nenhum W da faixa B servir, não gera nada e indica o tamanho padrão (tabela/Fit).
 4. Perfil dorsal: na pose assentada do W escolhido, abaixa a face da mola até a pré-carga --precarga-mm,
    com limite de 3,0 mm (faixa B: perfil −3..0). Tem transição no lado do polegar (−12..−24 mm) e zero a
    partir de 20..26 mm no lado do dedo mínimo, como no estudo PaddleUp. Suaviza com σ 1,5 mm e reaplica a
    máscara. Grava o JSON --dorso (x_T4, raise) do gerador CAD.
 5. Previsão: reavalia os 5 cortes com a face abaixada (mesma pose) → folgas previstas.
 6. Emite parametros.json para o passo de CAD no PC (gerar_cuff_scan_pc.py, OCP) e o relatório.
Depois do CAD: conferir_cuff_gerado.py compara o STL gerado com o scan (malha fechada).

Uso:
  python gerador_scan.py scan.stl --lado direita --fita-cm 21.0 --saida pasta [--mm-por-unidade K]
                         [--z-nos Z --z-polegar Z] [--nome Pedro_c1]
Limites: geometria rígida; não mede pressão, conforto, retenção nem uso molhado. Faixa B até o FEA.
"""
import argparse, json, math, sys, hashlib
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon
from shapely import affinity

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import freshcuff_fit as F

VERSAO = 'FreshCuff gerador por scan R01 v0.8 (avisos no relatório Markdown; v0.7 R05-01: NaN/inf param; v0.6 R04-01: limites com valores brutos e assento com 0,05 mm de margem; v0.5: pose estável — menor giro, mão centrada; v0.4: N08; v0.3: B01–B05)'
MARGEM_ASSENTO_MM = 0.05   # R04-01: o assento fica 0,05 mm dentro da hipótese de pele (folga para a malha do STL)
FAIXA_B = dict(w_min=80.0, w_max=84.0, dorso_min=-3.0, dorso_max=0.0, h_total_max=1.5)


def smooth(x, a, b):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def x_T4_de_xW(xw, dw):
    """Inverte a deformação do dorso do gerador (x_W = x_T4 + sinal·DW·smooth(|x|,10,40)) por tabela."""
    xt = np.linspace(-45, 45, 9001)
    xm = xt + np.sign(xt) * dw * smooth(np.abs(xt), 10., 40.)
    return np.interp(xw, xm, xt)


def espelhar(p):
    return affinity.scale(p, xfact=-1, yfact=1, origin=(0, 0))


def carregar_grade(caminho):
    d = json.load(open(caminho, encoding='utf8'))
    grade = {}
    for k, v in d['sizes'].items():
        grade[float(k)] = dict(meta={kk: v[kk] for kk in ('W', 'dw', 'dh', 'sha256', 'stl')},
                               ab={float(z): Polygon(c['contour']) for z, c in v['z'].items()})
    return d, grade


def matriz_folga_dorsal(pos, estacoes, aberturas, X):
    """Folga vertical por corte e por x: face da mola (topo da abertura) − topo da mão (maior y da interseção do
    contorno com a vertical em x). NaN onde o corte não tem mão naquele x."""
    from shapely.geometry import LineString
    G = np.full((len(pos), len(X)), np.nan)
    for i, (P, e) in enumerate(zip(pos, estacoes)):
        A = aberturas[e['z_cuff']]
        poly = Polygon(P).buffer(0)
        topo = np.interp(X, A.topo_x, A.topo_y)
        for k, x in enumerate(X):
            inter = poly.intersection(LineString([(x, -100), (x, 100)]))
            if not inter.is_empty:
                G[i, k] = topo[k] - inter.bounds[3]
    return G


def perfil_dorsal(pos, estacoes, aberturas, X):
    G = matriz_folga_dorsal(pos, estacoes, aberturas, X)
    with np.errstate(all='ignore'):
        return np.where(np.all(np.isnan(G), 0), np.nan, np.nanmin(G, 0))


def resumo_folga(G, bruto=False):
    """bruto=True: sem arredondar (R04-01: todo limite compara o valor bruto; arredondar só para mostrar)."""
    g = G[~np.isnan(G)]
    gmin = np.nanmin(G, 0); gmin = gmin[~np.isnan(gmin)]
    r = (lambda v, n: float(v)) if bruto else (lambda v, n: round(float(v), n))
    return {'folga_media_todos_cortes_mm': r(g.mean(), 2), 'frac_todos_cortes_ate_0_5mm': r(np.mean(g <= 0.5), 3),
            'folga_media_corte_mais_proximo_mm': r(gmin.mean(), 2),
            'frac_corte_mais_proximo_ate_0_5mm': r(np.mean(gmin <= 0.5), 3),
            'maior_sobreposicao_mm': r(max(0.0, -g.min()), 2)}


def encaixe_lateral(estacoes, aberturas_t, angulo, origem, tol_pele, curso):
    """Rodada 3: pose estável para escolher W e desenhar o dorso. O Fit escolhe a pose pela margem rígida/dorsal (com
    empates largos), e a pose e a folga lateral saíam diferentes para o MESMO scan girado no espaço (W 82,5 × 83 × 80,5;
    perfil dorsal até 1,7 mm diferente). Aqui: menor giro viável (0° quando possível) e, nele, a mão centrada (maior folga
    lateral), palma assentada com MARGEM_ASSENTO_MM de folga dentro da hipótese de pele; dorso ≤ curso. Mesma transformação do Fit."""
    pts0 = [F.amostrar(e['poligono']) for e in estacoes]
    ab = [aberturas_t[e['z_cuff']] for e in estacoes]
    ref = aberturas_t[min(aberturas_t, key=lambda z: abs(z - 13.0))]
    ox, oy = origem

    def transf(P, da):
        t = math.radians(-angulo + da); c, s_ = math.cos(t), math.sin(t); Q = P - [ox, oy]
        return np.c_[Q[:, 0] * c - Q[:, 1] * s_, Q[:, 0] * s_ + Q[:, 1] * c]

    def avaliar(da, dx, dy):
        base = [transf(P, da) for P in pts0]
        xc = 0.5 * (base[0][:, 0].min() + base[0][:, 0].max()); ymin = min(B[:, 1].min() for B in base)
        t = np.array([ref.xc - xc + dx, ref.ybase - ymin + dy])
        r = np.array([A.medir(B + t) for B, A in zip(base, ab)])
        return r[:, 0].min(), r[:, 1].min(), r[:, 2].min(), [B + t for B in base], t

    def assentar(da, dx, passo):
        for dy in np.arange(-1, 10 + 1e-9, passo):
            rig, dors, lat, pos, t = avaliar(da, dx, dy)
            if rig + tol_pele >= MARGEM_ASSENTO_MM and dors + curso >= 0:
                return (float(lat), float(da), float(dx), float(dy), rig, dors, pos, t)
        return None

    def assentar_fino(da, dx):
        c = assentar(da, dx, 0.25)
        if c is None: return None
        for dy in np.arange(max(-1, c[3] - 0.25), c[3] + 1e-9, 0.05):   # assenta a palma com passo fino
            rig, dors, lat, pos, t = avaliar(da, dx, dy)
            if rig + tol_pele >= MARGEM_ASSENTO_MM and dors + curso >= 0:
                return (float(lat), float(da), float(dx), float(dy), rig, dors, pos, t)
        return c

    # Menor giro viável primeiro (a mão não gira à toa dentro do cuff); nesse giro, o deslocamento lateral que centra a mão
    # (maior folga lateral). Empate de 0,05 mm → menor |dx|. Assim pequenas mudanças do scan não trocam a pose.
    c1 = None
    for g in [0] + [s * k for k in range(1, 9) for s in (1, -1)]:
        cands = [c for c in (assentar_fino(float(g), float(dx)) for dx in np.arange(-5, 5.001, 0.25)) if c]
        if cands:
            lmax = max(c[0] for c in cands)
            c1 = min([c for c in cands if c[0] >= lmax - 0.05], key=lambda c: abs(c[2]))
            break
    if c1 is None:
        return {'viavel': False}
    lat, da, dx, dy, rig, dors, pos, t = c1
    return {'viavel': True, 'lateral_min_mm': lat, 'rigido_min_mm': float(rig), 'dorso_min_mm': float(dors),
            'giro_grau': da, 'dx_mm': dx, 'dy_mm': dy, 'translacao_unica_mm': [float(t[0]), float(t[1])], '_pos': pos,
            'criterio_pose': 'menor giro viável; nele, a mão centrada (maior folga lateral); palma assentada'}


def validar_parametros(a):
    """N08 (revisão 2): números finitos, positivos e coerentes, antes de criar a pasta de saída."""
    fin = lambda v: v is not None and math.isfinite(v)
    erros = []
    if not (fin(a.fita_cm) and 10.0 <= a.fita_cm <= 35.0): erros.append('--fita-cm entre 10 e 35 cm')
    if not (fin(a.precarga_mm) and 0.0 <= a.precarga_mm <= 1.0): erros.append('--precarga-mm entre 0 e 1')
    if not (fin(a.limite_dorso_mm) and 0.0 < a.limite_dorso_mm <= -FAIXA_B['dorso_min']): erros.append(f"--limite-dorso-mm entre 0 e {-FAIXA_B['dorso_min']}")
    if not (fin(a.folga_lateral_mm) and 0.0 <= a.folga_lateral_mm <= 5.0): erros.append('--folga-lateral-mm entre 0 e 5')
    if not (fin(a.folga_lateral_max_mm) and 0.0 < a.folga_lateral_max_mm <= 20.0): erros.append('--folga-lateral-max-mm entre 0 e 20')
    if fin(a.folga_lateral_mm) and fin(a.folga_lateral_max_mm) and not a.folga_lateral_mm < a.folga_lateral_max_mm:
        erros.append('--folga-lateral-mm menor que --folga-lateral-max-mm')
    if not (fin(a.margem_furo_mm) and 0.0 <= a.margem_furo_mm <= 50.0): erros.append('--margem-furo-mm entre 0 e 50')
    if a.mm_por_unidade is not None and not (fin(a.mm_por_unidade) and a.mm_por_unidade > 0): erros.append('--mm-por-unidade positivo')
    for k in ('z_nos', 'z_polegar'):
        v = getattr(a, k)
        if v is not None and not fin(v): erros.append(f'--{k.replace("_", "-")} finito')
    if erros:
        raise SystemExit('Parâmetros inválidos: ' + '; '.join(erros))


def main(argv=None):
    ap = argparse.ArgumentParser(description=VERSAO)
    ap.add_argument('scan')
    ap.add_argument('--lado', choices=['direita', 'esquerda'], required=True)
    ap.add_argument('--fita-cm', type=float, required=True, help='fita nos nós medida no dia (conferência de escala)')
    ap.add_argument('--saida', required=True)
    ap.add_argument('--nome', default=None)
    ap.add_argument('--mm-por-unidade', type=float, default=None)
    ap.add_argument('--z-nos', type=float, default=None)
    ap.add_argument('--z-polegar', type=float, default=None)
    ap.add_argument('--dedos', choices=['auto', 'alto', 'baixo'], default='auto')
    ap.add_argument('--inverter-dorso', action='store_true')
    ap.add_argument('--manter-dorso', action='store_true', help='confirma que o +y atual já é o dorso (decisão manual; conferir fit_figura.png)')
    ap.add_argument('--precarga-mm', type=float, default=0.2)
    ap.add_argument('--limite-dorso-mm', type=float, default=3.0)
    ap.add_argument('--folga-lateral-mm', type=float, default=0.5, help='mínimo obrigatório; provisório: calibrar na V1 com a T4 de Pedro')
    ap.add_argument('--folga-lateral-max-mm', type=float, default=6.0, help='acima disso no menor W a mão é estreita para a faixa B (recusa)')
    ap.add_argument('--margem-furo-mm', type=float, default=10.0, help='nenhuma borda aberta da malha a menos disso da faixa do cuff')
    ap.add_argument('--grade', default=str(AQUI / 'aberturas_grade_W80_84.json'))
    for _s in (sys.stdout, sys.stderr):          # B03: console do Windows em cp1252
        try: _s.reconfigure(encoding='utf-8')
        except Exception: pass
    a = ap.parse_args(argv)
    if a.inverter_dorso and a.manter_dorso:
        raise SystemExit('--inverter-dorso e --manter-dorso são excludentes')
    validar_parametros(a)   # N08: antes de criar qualquer pasta
    saida = Path(a.saida); saida.mkdir(parents=True, exist_ok=False)   # B02: uma pasta nova por execução; nunca regrava
    nome = a.nome or Path(a.scan).stem

    # ---------- 1. leitura do scan pelo Fit (ponta distal do cuff em z0)
    argv_fit = [a.scan, '--saida', str(saida / 'fit'), '--nome', nome, '--fita-cm', str(a.fita_cm),
                '--cuff-distal', 'z0', '--dedos', a.dedos]
    for k, v in (('--mm-por-unidade', a.mm_por_unidade), ('--z-nos', a.z_nos), ('--z-polegar', a.z_polegar)):
        if v is not None:
            argv_fit += [k, str(v)]
    if a.inverter_dorso:
        argv_fit.append('--inverter-dorso')
    if a.manter_dorso:
        argv_fit.append('--manter-dorso')
    F._INTERNO = None
    rel_fit = F.main(argv_fit)
    rel = {'ferramenta': VERSAO, 'nome': nome, 'scan': a.scan, 'scan_sha256': rel_fit.get('scan_sha256'),
           'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'parametros': vars(a), 'fit': {k: rel_fit.get(k) for k in ('conclusao', 'avisos', 'nos', 'tamanho_pela_fita_scan',
                                                                     'tamanho_pela_fita_medida', 'recomendacao_suspensa',
                                                                     'menor_tamanho_compativel_faixa', 'faixa')}}

    if a.inverter_dorso or a.manter_dorso:   # B05: decisão manual de orientação fica registrada
        rel['orientacao_manual'] = 'inverter-dorso' if a.inverter_dorso else 'manter-dorso'
        rel.setdefault('avisos', []).append(f"Orientação decidida à mão ({rel['orientacao_manual']}): confira fit/fit_figura.png (DORSO ↑) antes do G3.")

    def parar(motivo):
        rel['resultado'] = 'NAO_GERADO'; rel['motivo'] = motivo
        (saida / 'gerador_relatorio.json').write_text(json.dumps(rel, indent=2, ensure_ascii=False, default=str), encoding='utf8')
        (saida / 'gerador_relatorio.md').write_text(f'# Gerador por scan · {nome}\n\n**Não gerado.** {motivo}\n\n'
                                                     f'Leitura do scan: {rel_fit.get("conclusao")}\n', encoding='utf8')
        print('NÃO GERADO:', motivo)
        return rel

    I = F._INTERNO
    if I is None:
        return parar(f"O scan não pôde ser lido: {rel_fit.get('conclusao')} {rel_fit.get('o_que_fazer', '')}")
    if rel_fit.get('recomendacao_suspensa'):
        return parar('Fita do scan e fita medida discordam: escala ou pose em dúvida.')
    if I['lacunas'] or any(e.get('estado') != 'completo' for e in I['estacoes']):
        return parar(f"Faixa não determinada no scan ({I['determinacao']}). Precisa de nova captura ou marcos manuais.")
    # B01: furos na malha. Scan de mão costuma ser aberto no corte do punho; isso é aceito longe da faixa do cuff.
    # Qualquer borda aberta a menos de --margem-furo-mm da faixa (cortes do cuff) recusa a geração.
    from trimesh.grouping import group_rows
    mI = I['m']; bnd = group_rows(mI.edges_sorted, require_count=1)
    zs = [e['z'] for e in I['estacoes']]; z0, z1 = min(zs) - a.margem_furo_mm, max(zs) + a.margem_furo_mm
    zb = mI.vertices[np.unique(mI.edges_sorted[bnd])][:, 2] if len(bnd) else np.zeros(0)
    perto = int(((zb >= z0) & (zb <= z1)).sum())
    rel['malha'] = {'estanque': bool(mI.is_watertight), 'arestas_de_borda': int(len(bnd)),
                    'z_bordas_mm': [round(float(zb.min()), 1), round(float(zb.max()), 1)] if len(zb) else None,
                    'faixa_com_margem_z_mm': [round(z0, 1), round(z1, 1)], 'vertices_de_borda_na_faixa': perto}
    if perto:
        return parar(f'A malha do scan tem furo ou borda aberta a menos de {a.margem_furo_mm:.0f} mm da faixa do cuff '
                     f'({perto} vértices de borda). Feche a malha no app do scanner ou refaça a captura.')
    if len(bnd):
        rel.setdefault('avisos', []).append(f'Malha aberta longe da faixa ({len(bnd)} arestas de borda, z {rel["malha"]["z_bordas_mm"]}); aceito.')

    # ---------- 2. lado da mão (Fit: polegar em +x = mão direita)
    lado_scan = {'pos': 'direita', 'neg': 'esquerda'}.get(I['lado_polegar'])
    rel['lado'] = {'declarado': a.lado, 'pelo_polegar_no_scan': lado_scan}
    if lado_scan is None:
        return parar('Não achei de que lado está o polegar; confira --z-polegar.')
    if lado_scan != a.lado:
        return parar(f'Lado declarado ({a.lado}) diferente do lado do polegar no scan ({lado_scan}). Confira o lado; se o lado estiver certo, '
                     f'o dorso pode ter sido lido trocado: veja fit/fit_figura.png e rode com --inverter-dorso.')
    espelho_mao = (a.lado == 'esquerda')
    # Fit (z0) → CAD: a convenção do CAD tem polegar em −x. Mão direita: x → −x. Mão esquerda: já está com polegar em −x.
    conv = (lambda p: espelhar(p)) if not espelho_mao else (lambda p: p)
    est = []
    for e in I['estacoes']:
        est.append(dict(e, poligono=conv(e['poligono'])))
    nos = conv(I['nos'])
    angulo = F.angulo_largura(nos)
    origem = (nos.centroid.x, nos.centroid.y)

    # ---------- 3. largura: grade W 80–84
    d_g, grade = carregar_grade(a.grade)
    meia = d_g['spring']['zone_half_width_mm']; curso = d_g['spring']['travel_nominal_mm']
    res = {}
    for W in sorted(grade):
        ab = {z: F.Abertura(P, meia) for z, P in grade[W]['ab'].items()}
        r = F.encaixe_faixa(est, ab, angulo, origem, 0.5, curso)
        if r['viavel']:   # a pose do gerador: menor giro, mão centrada, assento com margem (a do Fit fica registrada)
            rl = encaixe_lateral(est, ab, angulo, origem, 0.5, curso)
            if rl['viavel']:
                r = dict(rl, pose_fit={k: r[k] for k in ('giro_grau', 'dx_mm', 'dy_mm', 'lateral_min_mm')})
            else:   # sugestão da rodada 5: registrar quando a margem de assento não cabe e vale a pose do Fit
                r = dict(r, criterio_pose=f'pose do Fit: nenhuma pose com {MARGEM_ASSENTO_MM} mm de margem de assento foi viável')
        res[W] = dict(r, _ab=ab)
    viaveis = [W for W in sorted(res) if res[W]['viavel']]
    rel['grade'] = {f'{W:.1f}': {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res[W].items()
                                 if k in ('viavel', 'rigido_min_mm', 'dorso_min_mm', 'lateral_min_mm', 'margem_mm', 'giro_grau', 'dx_mm')}
                    for W in sorted(res)}
    if not viaveis:
        t = rel_fit.get('tamanho_pela_fita_medida') or rel_fit.get('tamanho_pela_fita_scan')
        return parar(f'Nenhuma largura da faixa B (W 80–84) acomoda a faixa da mão. Use o tamanho padrão (pela fita: T{t}) e os anéis.')
    com_folga = [W for W in viaveis if res[W]['lateral_min_mm'] >= a.folga_lateral_mm]
    if not com_folga:   # B04: a folga lateral mínima é obrigatória
        t = rel_fit.get('tamanho_pela_fita_medida') or rel_fit.get('tamanho_pela_fita_scan')
        return parar(f'Nenhuma largura da faixa B dá folga lateral ≥ {a.folga_lateral_mm} mm (melhor: '
                     f"{max(res[w]['lateral_min_mm'] for w in viaveis):.2f} mm). Use o tamanho padrão (pela fita: T{t}) e os anéis.")
    W = com_folga[0]
    r = res[W]; ab = r['_ab']; meta = grade[W]['meta']
    if not all(math.isfinite(float(r[k])) for k in ('rigido_min_mm', 'dorso_min_mm', 'lateral_min_mm')):   # R05-01
        return parar('Medida não finita (NaN/inf) na pose escolhida; scan ou cortes inválidos.')
    if str(r.get('criterio_pose', '')).startswith('pose do Fit'):
        rel.setdefault('avisos', []).append(r['criterio_pose'])
    rel['escolha'] = {'W': W, 'dw': meta['dw'], 'dh': meta['dh'], 'pose_fit_para_auditoria': r.get('pose_fit'),
                      'criterio_pose': r.get('criterio_pose'), 'rigido_min_mm_bruto': float(r['rigido_min_mm']),
                      'lateral_min_mm_bruto': float(r['lateral_min_mm']), 'motivo':
                      f'menor W viável com folga lateral ≥ {a.folga_lateral_mm} mm',
                      'pose': {k: r[k] for k in ('giro_grau', 'dx_mm', 'dy_mm')}}
    if r['rigido_min_mm'] < -0.4:   # sugestão da rodada 4: aviso quando a pose usa quase toda a hipótese de pele
        rel.setdefault('avisos', []).append(f"A palma assenta com {-r['rigido_min_mm']:.2f} mm de compressão de pele: hipótese geométrica provisória (até 0,5 mm), não é medida física de pressão; calibrar na V1.")
    if r['lateral_min_mm'] > a.folga_lateral_max_mm:   # B04: mão estreita demais para a faixa B
        t = rel_fit.get('tamanho_pela_fita_medida') or rel_fit.get('tamanho_pela_fita_scan')
        return parar(f"Mão estreita para a faixa B: folga lateral {r['lateral_min_mm']:.1f} mm em W{W:.1f} (máx. {a.folga_lateral_max_mm} mm). "
                     f'Use o tamanho padrão (pela fita: T{t}) e os anéis.')

    # ---------- 4. perfil dorsal
    X = np.arange(-26, 26.001, 0.5)
    gap = perfil_dorsal(r['_pos'], est, ab, X)
    tem = ~np.isnan(gap)
    if tem.sum() < 10:
        return parar('Poucos pontos do dorso sob a mola; perfil dorsal não determinado.')
    gap_f = np.interp(X, X[tem], gap[tem])
    taper = (1 - smooth(-X, 12., 24.)) * (1 - smooth(X, 20., 26.))
    from scipy.ndimage import gaussian_filter1d
    low = np.clip(gap_f + a.precarga_mm, 0, a.limite_dorso_mm) * taper
    low = gaussian_filter1d(low, 1.5 / 0.5) * taper
    low = np.where(tem, low, 0.0)
    xt = np.arange(-39., 39.001, 0.1)
    raise_T4 = -np.interp(xt, x_T4_de_xW(X, meta['dw']), low, left=0, right=0)   # perfil medido no quadro W, levado ao quadro T4
    raise_T4 = np.clip(raise_T4, FAIXA_B['dorso_min'], FAIXA_B['dorso_max'])
    dorso_json = saida / f'dorso_{nome}.json'
    dorso_json.write_text(json.dumps({'origem': VERSAO, 'W': W, 'pose': rel['escolha']['pose'], 'precarga_mm': a.precarga_mm,
                                      'limite_mm': a.limite_dorso_mm, 'x_T4': xt.round(3).tolist(), 'raise': raise_T4.round(4).tolist(),
                                      'X_W': X.tolist(), 'folga_antes': np.round(gap, 3).tolist(), 'abaixamento': low.round(3).tolist()}),
                          encoding='utf8')

    # ---------- 5. previsão com a face abaixada (mesma pose)
    def abaixar(Aab):
        out = {}
        for z, A in Aab.items():
            c = np.array(A.poly.exterior.coords)
            sel = (c[:, 1] > A.ymeio) & (np.abs(c[:, 0] - A.xc) <= meia)
            c[sel, 1] -= np.interp(c[sel, 0], X, low)
            out[z] = F.Abertura(Polygon(c).buffer(0), meia)
        return out
    ab2 = abaixar(ab)
    G0 = matriz_folga_dorsal(r['_pos'], est, ab, X); G1 = matriz_folga_dorsal(r['_pos'], est, ab2, X)
    antes, depois = resumo_folga(G0), resumo_folga(G1)
    depois_bruto = resumo_folga(G1, bruto=True)
    rel['previsao_dorso'] = {'antes': antes, 'depois': depois, 'depois_bruto': depois_bruto, 'curso_mm': curso, 'abaixamento_max_mm': round(float(low.max()), 2),
                             'nota': 'folga vertical face da mola × topo da mão, |x| ≤ 26, nos 5 cortes, mesma pose; CAD rígido'}
    if not all(math.isfinite(v) for v in depois_bruto.values()) or not np.all(np.isfinite(raise_T4)):   # R05-01
        return parar('Previsão do dorso não finita (NaN/inf); scan ou cortes inválidos.')
    if depois_bruto['maior_sobreposicao_mm'] > curso:
        return parar('A face abaixada sobrepõe o dorso além do curso da mola. Revisar a pré-carga ou o limite.')

    # ---------- 6. saídas
    param = {'id': f'scan_{nome}', 'W': W, 'dw': meta['dw'], 'dh': meta['dh'], 'esquerda': espelho_mao,
             'rotulo': 'L' if espelho_mao else 'R',   # Pedro, opção A (16/11): letra do lado + seta para os dedos na face da placa
             'dorso': dorso_json.name, 'faixa_B': FAIXA_B, 'grade_sha256_variante': meta['sha256'],
             'folga_lateral_mm': a.folga_lateral_mm, 'curso_mm': curso,
             'manifesto': {'scan_sha256': rel_fit.get('scan_sha256'), 'gerador_scan_sha256': rel['script_sha256'],
                           'freshcuff_fit_sha256': hashlib.sha256(Path(F.__file__).read_bytes()).hexdigest(),
                           'grade_aberturas_sha256': hashlib.sha256(Path(a.grade).read_bytes()).hexdigest(),
                           'dorso_sha256': hashlib.sha256(dorso_json.read_bytes()).hexdigest(),
                           'orientacao_manual': rel.get('orientacao_manual')}}
    (saida / 'parametros.json').write_text(json.dumps(param, indent=2, ensure_ascii=False), encoding='utf8')
    rel['resultado'] = 'PARAMETROS_PRONTOS_PARA_CAD'; rel['parametros_cad'] = param
    np.savez(saida / 'mao_faixa_cad.npz', **{f'est{i}': np.array(e['poligono'].exterior.coords) for i, e in enumerate(est)},
             **{f'pos{i}': P for i, P in enumerate(r['_pos'])}, z_cuff=np.array([e['z_cuff'] for e in est]),
             dz=np.array([e['dz'] for e in est]), angulo=angulo, origem=np.array(origem), W=W, esquerda=espelho_mao,
             X=X, abaixamento=low)
    (saida / 'gerador_relatorio.json').write_text(json.dumps(rel, indent=2, ensure_ascii=False, default=str), encoding='utf8')
    figura(r['_pos'], est, ab, ab2, X, gap, low, W, nome, saida / 'gerador_figura.png', rel)
    p = rel['previsao_dorso']
    md = [f'# Gerador por scan · {nome}', '',
          f"**Parâmetros prontos para o CAD:** W {W:.1f} mm (DW {meta['dw']:+.2f}, DH {meta['dh']:+.2f}), "
          f"{'mão esquerda' if espelho_mao else 'mão direita'}, perfil dorsal até −{p['abaixamento_max_mm']:.2f} mm.", '',
          f"- Leitura do scan: {rel_fit.get('conclusao')}",
          f"- Escolha da largura: {rel['escolha']['motivo']}.",
          f"- Dorso, corte mais próximo da mola: folga média {p['antes']['folga_media_corte_mais_proximo_mm']:.2f} → "
          f"{p['depois']['folga_media_corte_mais_proximo_mm']:.2f} mm; a ≤ 0,5 mm em {p['antes']['frac_corte_mais_proximo_ate_0_5mm']*100:.0f}% → "
          f"{p['depois']['frac_corte_mais_proximo_ate_0_5mm']*100:.0f}% da largura.",
          f"- Dorso, todos os 5 cortes: folga média {p['antes']['folga_media_todos_cortes_mm']:.2f} → {p['depois']['folga_media_todos_cortes_mm']:.2f} mm "
          f"(a faixa afunila ao longo dos 26 mm; um perfil único não acompanha todos os cortes).",
          f"- Maior sobreposição prevista: {p['depois']['maior_sobreposicao_mm']:.2f} mm (curso {curso} mm).", '',
          *([ '**Avisos:**', *[f'- {x}' for x in rel.get('avisos', [])], ''] if rel.get('avisos') else []),
          '| W | Viável | Rígido mín | Dorso mín | Lateral mín |', '|---|---|---|---|---|']
    for k, v in rel['grade'].items():
        md.append(f"| {k} | {'sim' if v['viavel'] else 'não'} | {v['rigido_min_mm']:+.2f} | {v['dorso_min_mm']:+.2f} | {v['lateral_min_mm']:+.2f} |")
    md += ['', 'Próximo passo: CAD no PC (`gerar_cuff_scan_pc.py parametros.json`) e conferência do STL gerado contra o scan.',
           'Geometria rígida; folga lateral alvo e pré-carga são provisórias até a V1. Nada vai à impressora sem G3.']
    (saida / 'gerador_relatorio.md').write_text('\n'.join(md), encoding='utf8')
    print('\n'.join(md))
    return rel


def figura(pos, est, ab, ab2, X, gap, low, W, nome, caminho, rel):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(1, 2, figsize=(15, 5.5), gridspec_kw={'width_ratios': [1.3, 1]})
    A = ab[est[0]['z_cuff']]; A2 = ab2[est[0]['z_cuff']]
    x, y = A.poly.exterior.xy; axs[0].plot(x, y, color='0.6', ls='--', label=f'abertura W{W:.1f} padrão')
    x, y = A2.poly.exterior.xy; axs[0].plot(x, y, color='#116c69', lw=2, label='com o perfil dorsal')
    for P, e in zip(pos, est):
        axs[0].plot(np.r_[P[:, 0], P[0, 0]], np.r_[P[:, 1], P[0, 1]], lw=1.2 if e['dz'] == 0 else .6, color='#bb7653')
    axs[0].set_aspect('equal'); axs[0].legend(fontsize=8); axs[0].set_title('Cortes da mão na pose assentada (CAD: polegar à esquerda, dorso ↑)', fontsize=9)
    axs[1].plot(X, gap, label='folga dorsal antes (mín. entre cortes)')
    axs[1].plot(X, -low, label='perfil (−abaixamento)')
    axs[1].axhline(0, color='k', lw=.5); axs[1].grid(alpha=.3); axs[1].legend(fontsize=8)
    axs[1].set_xlabel('x no CAD (mm) · polegar ← → dedo mínimo'); axs[1].set_ylabel('mm')
    p = rel['previsao_dorso']
    fig.suptitle(f"Gerador por scan · {nome} · W {W:.1f} · corte mais próximo: folga média {p['antes']['folga_media_corte_mais_proximo_mm']:.2f} → "
                 f"{p['depois']['folga_media_corte_mais_proximo_mm']:.2f} mm · sobreposição máx. {p['depois']['maior_sobreposicao_mm']:.2f} mm (CAD, rígido)", fontsize=10)
    fig.tight_layout(); fig.savefig(caminho, dpi=120); plt.close(fig)


if __name__ == '__main__':
    main()
