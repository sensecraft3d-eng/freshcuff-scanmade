# -*- coding: utf-8 -*-
"""Varredura da faixa valida do gerador interno (15/11/2026, Claude) - GERADOR_PUBLICO_R01.
Roda uma COPIA de construir_r08a_custom.py (gerador_copia/, hash EDC9C282...) importando construir_r08a.py do
lugar original (PULSEIRA/R08A_T4_P3/trabalho, so leitura). Cada caso roda num subprocesso com tempo limite.
Uso: python varredura.py casos.json saida_dir
Requer PYTHONPATH com o OCP (cadquery-ocp 7.9.3, cp312)."""
import json, subprocess, sys, time, os
from pathlib import Path
AQUI = Path(__file__).resolve().parent
# Repository layout: construir_r08a.py and the builders are all in cad/src (this folder); originally E:\...\trabalho and gerador_copia/.
ORIG = AQUI
RUN = r'''
import sys; sys.path.insert(0, r"%s"); sys.path.insert(0, r"%s")
import construir_r08a_custom as g
from pathlib import Path
a = %r
g.main(Path(a["out"]), a["rotulo"], a["dw"], a["dh"], a.get("esquerda", False), a.get("nome"), a.get("dorso"))
''' % (str(ORIG), str(AQUI), None)

def rodar(caso, saida, limite=900):
    out = saida / caso["id"]
    a = dict(out=str(out), rotulo=caso.get("rotulo", "C"), dw=float(caso["dw"]), dh=float(caso["dh"]),
             esquerda=bool(caso.get("esquerda", False)), nome="cuff_" + caso["id"], dorso=caso.get("dorso"))
    code = RUN.replace("a = None", "a = " + repr(a))
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=limite)
        rc, so, se = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, so, se = "timeout", "", ""
    dt = round(time.time() - t0, 1)
    etapas = [l.split()[0] for l in so.splitlines() if l.endswith("valido")]
    erro = (se.strip().splitlines() or [""])[-1][:300]
    r = dict(caso, rc=rc, segundos=dt, etapas_validas=etapas, exportou=("STEP e STL exportados" in so), erro=erro)
    return r

if __name__ == "__main__":
    casos = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); saida = Path(sys.argv[2]); saida.mkdir(exist_ok=True)
    res = []
    for c in casos:
        r = rodar(c, saida); res.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
        (saida / "varredura_resultado.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
