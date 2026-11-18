# -*- coding: utf-8 -*-
"""FreshCuff · gerador web R01 · grade R/L para o navegador (16/11/2026, Claude).
Pedro escolheu (16/11, opção A) o gerador online no site, tudo no navegador: o scan não sai do computador da pessoa.
O navegador não roda o OCP; ele parte de uma variante pronta desta grade (W 80–84 de 0,5 em 0,5, faixa B, dorso 0)
e aplica o campo de deslocamento do dorso pessoal (mesma rotina 2D do CAD). Esta grade usa o MESMO construtor do
gerador por scan (v2b/construir_r08a_scan.py: letra R ou L + seta para os dedos), sem dorso.
Para cada variante: gera o sólido, aplica as travas da grade (gerar_grade.medir/trava) e grava STL/STEP numa pasta nova.
Uso (PYTHONPATH com o OCP, Python 3.12):  python gerar_grade_rl_pc.py"""
import json, sys, hashlib
from pathlib import Path
AQ = Path(__file__).resolve().parent
GP = Path(r"E:\SenseCraft\05_Projetos\MFG-FRESHSTART\trabalho\GERADOR_PUBLICO_R01_20261115")
V2B = Path(r"E:\SenseCraft\05_Projetos\MFG-FRESHSTART\trabalho\GERADOR_SCAN_R01_20261116\v2b")
sys.path.insert(0, str(GP / "faixa")); sys.path.insert(0, str(GP / "prototipo_fase1"))
import varredura as V
V.RUN = V.RUN.replace(str(GP / 'faixa' / 'gerador_copia'), str(V2B)).replace('import construir_r08a_custom as g', 'import construir_r08a_scan as g')
assert 'construir_r08a_scan' in V.RUN and 'gerador_copia' not in V.RUN, 'troca do gerador falhou'
import gerar_grade as GG

saida = AQ / "grade_rl"; saida.mkdir(exist_ok=False)
ns = GG.funcoes_medida(); ref = GP / "faixa" / "saida_0" / "W82_ref" / "cuff_W82_ref.stl"; indice = []
for i in range(9):
    W = 80 + 0.5 * i; dw = (W - 82) / 2; dh = round(35.5 * (W / 82 - 1), 4)
    for lado, rot in (("dir", "R"), ("esq", "L")):
        vid = f"W{W:.1f}_{rot}"
        r = V.rodar(dict(id=vid, dw=dw, dh=dh, esquerda=(lado == "esq"), rotulo=rot), saida)
        stl = saida / vid / f"cuff_{vid}.stl"
        reg = dict(id=vid, W=W, dw=dw, dh=dh, lado=lado, rotulo=rot, gerou=bool(r.get("exportou")), segundos=r["segundos"], erro=r.get("erro"))
        if reg["gerou"]:
            reg.update(GG.medir(ns, stl, dw, dh, ref)); reg["falhas"] = GG.trava(reg)
            reg["stl_sha256"] = hashlib.sha256(stl.read_bytes()).hexdigest()
        indice.append(reg); print(json.dumps(reg, ensure_ascii=False), flush=True)
        (saida / "indice_grade_rl.json").write_text(json.dumps(indice, indent=1, ensure_ascii=False), encoding="utf-8")
print("FIM", sum(1 for r in indice if r.get("gerou") and not r["falhas"]), "de", len(indice), "sem falha")
