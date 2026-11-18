# -*- coding: utf-8 -*-
"""FreshCuff · gerador por scan R01 · passo de CAD no PC · v6 (16/11/2026, Claude). v6: medida não finita reprova (R05-01). v5: travas com valores brutos (R04-01). v4: confere o manifesto (N05). v3: hashes dos parâmetros e do construtor no relatório.
v2: usa construir_r08a_scan.py desta pasta (letra R/L + seta para os dedos na face da placa, opção A de Pedro).
Lê parametros.json (gerado por gerador_scan.py) e:
 1. gera o sólido com a CÓPIA do gerador (GERADOR_PUBLICO_R01\\faixa\\gerador_copia, via varredura.rodar; construir_r08a.py
    importado do original, só leitura);
 2. aplica as mesmas travas por peça da grade (G01, G03–G08, G13; medir/trava de gerar_grade.py);
 3. troca a malha no 3MF base (lisa/P1S R05b) com trocar_malha_3mf_v4b_custom.py (original, só leitura), com --dorso e,
    se for mão esquerda, --espelhado; nome do objeto em inglês;
 4. grava tudo numa pasta nova (nunca sobrescreve).
Uso (PYTHONPATH com o OCP, Python 3.12):  python gerar_cuff_scan_pc.py <pasta_com_parametros.json>"""
import json, subprocess, sys, hashlib
from pathlib import Path
PASTA = Path(sys.argv[1]).resolve()
# Repository layout: varredura.py, gerar_grade.py and construir_r08a_scan.py are in cad/src (this folder);
# the manifest files and conferir_cuff_gerado.py are in web/py and web/dados (see paths.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths
import varredura as V
V.RUN = V.RUN.replace('import construir_r08a_custom as g', 'import construir_r08a_scan as g')
assert 'construir_r08a_scan' in V.RUN and 'gerador_copia' not in V.RUN, 'troca do gerador falhou'
import gerar_grade as GG


def trava_finita(r):
    """R05-01: gerar_grade.trava (só leitura) compara com < e >, e NaN passaria; aqui qualquer medida não finita reprova (G00)."""
    import math
    nums = [v for k, v in r.items() if isinstance(v, float)]
    return (['G00'] if not all(math.isfinite(v) for v in nums) else []) + GG.trava(r)


def medir_bruto(ns, stl, dw, dh, ref):
    """Mesmas medidas de gerar_grade.medir (só leitura), sem arredondar: a trava compara o valor bruto."""
    import numpy as np, trimesh
    m = trimesh.load(stl); M = ns["mf"](m); M4 = ns["mf"](trimesh.load(ref)); reg = ns["box"](-20, 20, -29.3, -20, -1, 27)
    n = ns["sections"](m, 13.003); th, lat, st = ns["spans"](n, dw, dh)
    fx = float(((M ^ reg) - (M4 ^ reg)).volume() + ((M4 ^ reg) - (M ^ reg)).volume())
    return dict(estanque=bool(m.is_watertight), pecas=len(m.split()), faixa_z=float(m.extents[2]),
                abertura_L=float(np.ptp(ns["xvals"](n[1], 0))), abertura_H=float(np.ptp(ns["yvals"](n[1], 0))),
                lamina_min=float(min(v for _, v in th)), vao_lateral_min=float(min(v[-1] for v in lat)),
                aro_ombro_min=float(min(v for _, v in st)), fenda=float(np.ptp(ns["yvals"](n[2], 0))),
                fix=fx, maior=float(max(m.extents)))

p = json.loads((PASTA / "parametros.json").read_text(encoding="utf-8"))
# N05 (revisão 2): o manifesto dos parâmetros tem de bater com os arquivos atuais antes de gerar
_m = p.get("manifesto") or {}
_aq = paths.WEB_PY
_conf = {"gerador_scan_sha256": _aq / "gerador_scan.py", "freshcuff_fit_sha256": _aq / "freshcuff_fit.py",
         "grade_aberturas_sha256": paths.WEB_DATA / "aberturas_grade_W80_84.json", "dorso_sha256": PASTA / p["dorso"]}
_dif = [k for k, f in _conf.items() if _m.get(k) != hashlib.sha256(f.read_bytes()).hexdigest()]
assert not _dif, f"manifesto não confere com os arquivos atuais: {_dif} (parâmetros gerados por outra versão?)"
fb = p["faixa_B"]
assert fb["w_min"] <= p["W"] <= fb["w_max"], "W fora da faixa B"
dorso = PASTA / p["dorso"]
d = json.loads(dorso.read_text(encoding="utf-8"))
assert min(d["raise"]) >= fb["dorso_min"] - 1e-9 and max(d["raise"]) <= fb["dorso_max"] + 1e-9, "perfil dorsal fora da faixa B"
saida = PASTA / "cad"; saida.mkdir(exist_ok=False)
caso = dict(id=p["id"], dw=p["dw"], dh=p["dh"], esquerda=p["esquerda"], rotulo=p.get("rotulo", "C"), dorso=str(dorso))
r = V.rodar(caso, saida)
reg = dict(caso, rc=r["rc"], segundos=r["segundos"], exportou=r["exportou"], erro=r.get("erro"))
reg["parametros_sha256"] = hashlib.sha256((PASTA / "parametros.json").read_bytes()).hexdigest()
reg["construtor_sha256"] = hashlib.sha256((Path(__file__).resolve().parent / "construir_r08a_scan.py").read_bytes()).hexdigest()
stl = saida / p["id"] / f"cuff_{p['id']}.stl"
if r["exportou"]:
    ns = GG.funcoes_medida()
    ref = paths.reference_stl()
    bruto = medir_bruto(ns, stl, p["dw"], p["dh"], ref)            # R04-01: travas com valores brutos
    reg.update({k: (round(v, 3) if isinstance(v, float) else v) for k, v in bruto.items()}); reg["medidas_brutas"] = bruto
    reg["falhas"] = trava_finita(bruto)
    reg["stl_sha256"] = hashlib.sha256(stl.read_bytes()).hexdigest()
    if not reg["falhas"]:
        out3 = saida / p["id"] / f"FreshCuff_Custom_{p['id']}_P1S_PETG.3mf"
        args = [sys.executable, str(GG.TROCA), str(GG.BASE3MF), str(stl), str(out3), "--costura-pulseira",
                "--dw", str(p["dw"]), "--dh", str(p["dh"]), "--dorso", str(dorso)]
        if p["esquerda"]:
            args.append("--espelhado")
        q = subprocess.run(args, capture_output=True, text=True)
        reg["troca_rc"] = q.returncode; reg["troca_log"] = (q.stdout + q.stderr)[-400:]
        if q.returncode == 0:
            reg["3mf"] = str(out3); reg["3mf_sha256"] = hashlib.sha256(out3.read_bytes()).hexdigest()
if r["exportou"] and not reg.get("falhas"):   # conferência do STL contra o scan, com veredito automático
    q = subprocess.run([sys.executable, str(paths.WEB_PY / "conferir_cuff_gerado.py"), str(PASTA), str(stl)],
                       capture_output=True, text=True, encoding="utf-8", env=dict(__import__("os").environ, PYTHONIOENCODING="utf-8"))
    try:
        conf = json.loads((PASTA / "conferencia_stl.json").read_text(encoding="utf-8")); reg["conferencia_veredito"] = conf["veredito"]
    except Exception as e:
        reg["conferencia_veredito"] = {"resultado": "ERRO", "falhas": [str(e)[:200], (q.stderr or "")[-300:]]}
(saida / "cad_relatorio.json").write_text(json.dumps(reg, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(reg, ensure_ascii=False))
