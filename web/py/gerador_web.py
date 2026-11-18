# -*- coding: utf-8 -*-
"""FreshCuff · gerador por scan · versão para o navegador R01 (16/11/2026, Claude).
Pedro escolheu (16/11, opção A): gerador online no site da SenseCraft, tudo no navegador; o scan não sai do computador.
Roda igual no CPython (testes) e no Pyodide (página). Não usa OCP. Passos:
 1. leitura do scan e parâmetros: gerador_scan.py (o MESMO arquivo do gerador do PC, cópia sem alteração);
 2. sólido: a variante pronta da grade R/L (gerada no PC pelo construtor do gerador por scan, travas aprovadas) recebe o
    campo de deslocamento do dorso pessoal calculado pela MESMA rotina 2D do CAD (nucleo_r08a.py: contours com o perfil
    somado, deformar, restaura_lamina). O campo só depende de (x, y); a malha da grade vem refinada no plano xy (≤ 1 mm)
    para seguir a curva. Validado contra o CAD completo (OCP) do caso Artec;
 3. travas: G01/G03/G04/G05/G07/G08/G13 medidas na malha final (medir.py da faixa, mesmas funções); G06 (fixadores) por
    invariância: os vértices da região dos fixadores não podem se mover (então valem as medidas da variante);
 4. 3MF: trocar_malha_3mf_v4b_custom.py (o MESMO do PC) sobre o 3MF base lisa/P1S R05b;
 5. conferência do cuff gerado contra o scan (conferir_cuff_gerado.py, o MESMO do PC).
Nada vai à impressora sem G3; publicar é G5 de Pedro."""
import json, sys, runpy, hashlib, time
from pathlib import Path
import numpy as np, trimesh
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
VERSAO = 'gerador_web R07 v0.7 (16/11/2026; gerador por scan v2h = v0.8; recusa por NaN/inf registrada)'
LIMITE_SCAN_MB = 150   # N06: ~3 milhões de faces em STL binário
FIX_BOX = (-20., 20., -29.3, -20.)            # região dos fixadores (mesma caixa de gerar_grade.medir)

def _medidas():
    src = (AQUI / 'medir_original.py').read_text(encoding='utf-8').split("saida = Path(sys.argv[1])")[0]
    src = src.replace('import sys, json, numpy as np, trimesh, manifold3d as m3', 'import sys, json, numpy as np, trimesh')
    ns = {}; exec(src, ns); return ns

def medir(m, dw, dh):
    """Valores BRUTOS (R04-01): a trava compara sem arredondar; arredondar só para mostrar (mostrar())."""
    ns = _medidas(); n = ns['sections'](m, 13.003); th, lat, st = ns['spans'](n, dw, dh)
    return dict(estanque=bool(m.is_watertight), pecas=len(m.split(only_watertight=False)), faixa_z=float(m.extents[2]),
                abertura_L=float(np.ptp(ns['xvals'](n[1], 0))), abertura_H=float(np.ptp(ns['yvals'](n[1], 0))),
                lamina_min=float(min(v for _, v in th)), vao_lateral_min=float(min(v[-1] for v in lat)),
                aro_ombro_min=float(min(v for _, v in st)), fenda=float(np.ptp(ns['yvals'](n[2], 0))),
                maior=float(max(m.extents)))

def mostrar(r):
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}

def trava(r):
    import math
    f = []
    if not all(math.isfinite(v) for v in r.values() if isinstance(v, (int, float)) and not isinstance(v, bool)):
        f.append('G00')   # R05-01: medida não finita (NaN/inf) nunca aprova
    if not (r['estanque'] and r['pecas'] == 1): f.append('G01')
    if not (25.95 <= r['faixa_z'] <= 26.05): f.append('G03')
    if r['lamina_min'] < 0.85: f.append('G04')
    if r['vao_lateral_min'] < 0.6: f.append('G05')
    if r['fix_desloc_max_mm'] > 1e-9 or r['fix_variante_mm3'] > 0.1: f.append('G06')
    if not (1.95 <= r['fenda'] <= 2.25): f.append('G07')
    if r['aro_ombro_min'] < 7.2: f.append('G08')
    if r['maior'] > 160: f.append('G13')
    return f

def aplicar_dorso(malha, dw, dh, dorso, esquerda, base_json):
    import nucleo_r08a as N, campo_dorso as C
    N.carregar_base(base_json)
    def cont(d):
        s0 = N.contornos_com_dorso(d) if d is not None else N.contours()
        s = {k: N.deformar(v, dw, dh) for k, v in s0.items()}
        return N.restaura_lamina(s, s0)
    a, b = cont(None), cont(dorso)
    V = malha.vertices.copy()
    if esquerda: V[:, 0] *= -1                      # a variante L é a direita espelhada (o construtor espelha os contornos)
    W, _ = C.deslocar(V, a, b)
    if esquerda: W[:, 0] *= -1
    d = np.linalg.norm(W - malha.vertices, axis=1)
    x0, x1, y0, y1 = FIX_BOX
    fix = (malha.vertices[:, 0] > x0) & (malha.vertices[:, 0] < x1) & (malha.vertices[:, 1] > y0) & (malha.vertices[:, 1] < y1)
    return trimesh.Trimesh(W, malha.faces, process=False), float(d[fix].max()) if fix.any() else 0.0, float(d.max())

def relatorio_final(saida, out, p, var):
    """Sugestão da rodada 5: um JSON para baixar junto do 3MF, que liga o arquivo às travas brutas, à conferência e aos
    hashes dos programas e dados usados nesta execução."""
    sha = lambda f: hashlib.sha256(Path(f).read_bytes()).hexdigest()
    rel = {'versao': VERSAO, 'resultado': out['resultado'], 'ambiente': versoes(), 'variante': var['id'],
           'variante_sha256': var['sha256_refinado'], 'parametros': p, 'stl_sha256': out.get('stl_sha256'),
           '3mf': out.get('3mf'), '3mf_sha256': out.get('3mf_sha256'), 'travas_brutas': out.get('travas_brutas'),
           'falhas_travas': out.get('travas', {}).get('falhas'), 'conferencia_veredito': out.get('conferencia', {}).get('veredito'),
           'conferencia_bruta': out.get('conferencia', {}).get('a_mesma_pose_bruto'),
           'programas_sha256': {f.name: sha(f) for f in sorted(AQUI.glob('*.py'))},
           'aviso': 'Geometria verificada em CAD; o encaixe real depende de prova física. Nada vai à impressora sem conferir o 3MF no fatiador.'}
    with open(Path(saida) / 'relatorio_final.json', 'x', encoding='utf8') as f:
        f.write(json.dumps(rel, indent=1, ensure_ascii=False, default=float))

def liberar():
    """R03-02 (rodada 3): solta todas as referências à malha da mão (Fit guarda a última em _INTERNO) e coleta a memória."""
    import gc
    try:
        import freshcuff_fit as F; F._INTERNO = None
    except Exception:
        pass
    gc.collect()

def versoes():
    """N05: versões efetivamente executadas (vão para o relatório)."""
    import platform, scipy, shapely
    return {'python': platform.python_version(), 'plataforma': sys.platform, 'numpy': np.__version__, 'scipy': scipy.__version__,
            'shapely': shapely.__version__, 'trimesh': trimesh.__version__}

def analisar(scan, lado, fita_cm, saida, dados_dir, nome=None, extra=(), progresso=print):
    """Passo 1 (scan → parâmetros). Retorna o estado; se pronto, diz qual variante da grade baixar."""
    t0 = time.time(); saida = Path(saida)
    mb = Path(scan).stat().st_size / 1e6
    if mb > LIMITE_SCAN_MB:
        raise SystemExit(f'Scan grande demais ({mb:.0f} MB; limite {LIMITE_SCAN_MB} MB). Reduza a malha no app do scanner (ex.: 1–2 milhões de faces).')
    saida.mkdir(parents=True, exist_ok=False)
    import gerador_scan as G
    progresso('Lendo o scan e escolhendo o tamanho…')
    argv = [str(scan), '--lado', lado, '--fita-cm', str(fita_cm), '--saida', str(saida / 'analise'),
            '--grade', str(Path(dados_dir) / 'aberturas_grade_W80_84.json')] + (['--nome', nome] if nome else []) + list(extra)
    rel = G.main(argv)
    out = {'versao': VERSAO, 'analise': rel.get('resultado'), 'motivo': rel.get('motivo'), 'segundos_analise': round(time.time() - t0, 1),
           'avisos': rel.get('avisos', []), 'orientacao_manual': rel.get('orientacao_manual'), 'ambiente': versoes(),
           'figuras': [str(f.relative_to(saida)) for f in sorted((saida / 'analise').rglob('*.png'))]}
    if rel.get('resultado') != 'PARAMETROS_PRONTOS_PARA_CAD':
        out['resultado'] = 'PAROU_NA_ANALISE'
    else:
        p = rel['parametros_cad']; out['variante'] = f"W{p['W']:.1f}_{'L' if p['esquerda'] else 'R'}"; out['resultado'] = 'ANALISE_PRONTA'
    (saida / 'gerador_web.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf8')
    return out

def montar(saida, grade_dir, dados_dir, progresso=print):
    """Passo 2 (parâmetros + variante da grade → STL, travas, 3MF, conferência). A variante já deve estar em grade_dir."""
    t0 = time.time(); saida = Path(saida); out = json.loads((saida / 'gerador_web.json').read_text(encoding='utf8'))
    assert out['resultado'] == 'ANALISE_PRONTA' and not (saida / 'cuff').exists(), 'montagem já feita ou análise não pronta'
    (saida / 'cuff').mkdir()
    p = json.loads((saida / 'analise' / 'parametros.json').read_text(encoding='utf8')); esq = bool(p['esquerda'])
    vid = out['variante']; idx = json.loads((Path(grade_dir) / 'indice_grade_web.json').read_text(encoding='utf8'))
    var = next(v for v in idx if v['id'] == vid)
    assert not var['falhas'], f'variante {vid} com falha na grade'
    progresso(f'Ajustando o dorso da variante {vid}…')
    stl_var = Path(grade_dir) / var['arquivo']
    assert hashlib.sha256(stl_var.read_bytes()).hexdigest() == var['sha256_refinado'], 'variante da grade diferente da publicada'
    m0 = trimesh.load(stl_var, process=True)   # junta os vértices repetidos do STL (malha fechada)
    dorso = json.loads((saida / 'analise' / p['dorso']).read_text(encoding='utf8'))
    m, fixmax, dmax = aplicar_dorso(m0, p['dw'], p['dh'], dorso, esq, str(Path(dados_dir) / 'contornos_base.json'))
    progresso('Conferindo as travas…')
    r = medir(m, p['dw'], p['dh']); r.update(fix_desloc_max_mm=fixmax, fix_variante_mm3=float(var['fix']), desloc_max_mm=dmax)
    falhas = trava(r); out['travas'] = dict(mostrar(r), falhas=falhas); out['travas_brutas'] = r
    r = {'falhas': falhas}
    stl = saida / 'cuff' / f"FreshCuff_Custom_{p['id']}.stl"; m.export(stl); out['stl_sha256'] = hashlib.sha256(stl.read_bytes()).hexdigest()
    if r['falhas']:
        out['resultado'] = 'PAROU_NAS_TRAVAS'
    else:
        progresso('Montando o 3MF…')
        mf = saida / 'cuff' / f"FreshCuff_Custom_{p['id']}_P1S_PETG.3mf"
        args = [str(Path(dados_dir) / 'FreshCuff_R08A_T4_LISA_P1S_R05b.3mf'), str(stl), str(mf), '--costura-pulseira',
                '--dw', str(p['dw']), '--dh', str(p['dh']), '--dorso', str(saida / 'analise' / p['dorso'])] + (['--espelhado'] if esq else [])
        old = sys.argv; sys.argv = ['trocar_malha'] + args
        try: runpy.run_path(str(AQUI / 'trocar_malha_3mf_v4b_custom.py'), run_name='__main__')
        finally: sys.argv = old
        out['3mf'] = str(mf.relative_to(saida)); out['3mf_sha256'] = hashlib.sha256(mf.read_bytes()).hexdigest()
        progresso('Conferindo o cuff contra o scan…')
        old = sys.argv; sys.argv = ['conferir', str(saida / 'analise'), str(stl)]
        try: runpy.run_path(str(AQUI / 'conferir_cuff_gerado.py'), run_name='__main__')
        finally: sys.argv = old
        out['conferencia'] = json.loads((saida / 'analise' / 'conferencia_stl.json').read_text(encoding='utf8'))
        v = out['conferencia'].get('veredito', {})
        out['resultado'] = 'CUFF_PRONTO' if v.get('resultado') == 'APROVADO' else 'PAROU_NA_CONFERENCIA'
        relatorio_final(saida, out, p, var)
        if out['resultado'] != 'CUFF_PRONTO':
            out['motivo'] = 'O cuff gerado não confirmou a previsão: ' + '; '.join(v.get('falhas', ['sem veredito']))
    out['segundos_montagem'] = round(time.time() - t0, 1)
    (saida / 'gerador_web_final.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf8')
    return out

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('scan'); ap.add_argument('--lado', required=True); ap.add_argument('--fita-cm', type=float, required=True)
    ap.add_argument('--saida', required=True); ap.add_argument('--grade', required=True); ap.add_argument('--dados', required=True); ap.add_argument('--nome')
    a, resto = ap.parse_known_args()
    r = analisar(a.scan, a.lado, a.fita_cm, a.saida, a.dados, a.nome, resto)
    if r['resultado'] == 'ANALISE_PRONTA':
        r = montar(a.saida, a.grade, a.dados)
    print(json.dumps(r, indent=1, ensure_ascii=False))
