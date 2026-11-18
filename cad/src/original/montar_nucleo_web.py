"""Monta, a partir do original (só leitura), o núcleo 2D do cuff para o navegador: funções de construir_r08a.py até contours(),
sem OCP, com a seção da base (z 3,173) e o alvo do guia (z 13) lidos de um JSON pequeno em vez do STL de 27 MB."""
import re, json, hashlib, sys, numpy as np
from pathlib import Path
ORIG = Path('/mnt/user-data/uploads/MFG-FRESHSTART/PULSEIRA/R08A_T4_P3/trabalho/construir_r08a.py')
SCAN = Path('/home/claude/gscan/construir_r08a_scan.py')
src = ORIG.read_text(encoding='utf-8'); sha = hashlib.sha256(src.encode()).hexdigest()
fim = src.index('def spline_edge(')
corpo = src[:fim]
corpo = re.sub(r'^from OCP[^\n(]*\([^)]*\)\n', '', corpo, flags=re.M)
corpo = re.sub(r'^from OCP[^\n]*\n', '', corpo, flags=re.M)
assert 'OCP' not in corpo.replace('sem OCP','')
corpo = re.sub(r"^PROJECT = .*$|^BASE = .*$|^GUIDE = .*$|^MARK = .*$", "", corpo, flags=re.M)
old_sec = "    slit, aperture, outer = xy_section(trimesh.load(BASE),3.173)\n"
old_tab = "    table = np.loadtxt(GUIDE,delimiter=',',skiprows=1)\n    target = Polygon(table[abs(table[:,0]-13)<.01,4:6])\n"
assert corpo.count(old_sec) == 1 and corpo.count(old_tab) == 1
corpo = corpo.replace(old_sec, "    slit, aperture, outer = [orient(Polygon(_BASE[k])) for k in ('slit','aperture','outer')]\n")
corpo = corpo.replace(old_tab, "    target = Polygon(_BASE['target'])\n")
s2 = SCAN.read_text(encoding='utf-8')
extra = s2[s2.index('def deformar('):s2.index('def section_wires_tam(')] + s2[s2.index('def contornos_com_dorso('):s2.index('def main(')]
extra = extra.replace('inspect.getsource(c.contours)', 'inspect.getsource(contours)').replace('ns = dict(vars(c))', 'ns = dict(globals())')
extra = extra.replace("d = _j.loads(Path(raise_json).read_text(encoding='utf-8'))", "d = raise_json if isinstance(raise_json, dict) else _j.loads(Path(raise_json).read_text(encoding='utf-8'))")
cab = f'''# -*- coding: utf-8 -*-
"""Núcleo 2D do FreshCuff R08A para o gerador web (gerado por montar_nucleo_web.py; NÃO editar à mão).
Origem: construir_r08a.py sha256 {sha[:12]} (funções até contours, sem OCP) + deformar/restaura_lamina/contornos_com_dorso
de construir_r08a_scan.py. A seção da base e o alvo do guia vêm de dados/contornos_base.json."""
import json as _json
_BASE = None
def carregar_base(caminho):
    global _BASE
    _BASE = _json.loads(open(caminho, encoding='utf-8').read())
'''
Path('py/nucleo_r08a.py').write_text(cab + corpo + '\n\n' + extra, encoding='utf-8')
# dados da base
sys.path.insert(0, '/home/claude/web'); import stub_ocp
sys.path.insert(0, str(ORIG.parent)); import construir_r08a as c, trimesh
BASE = Path('/mnt/user-data/uploads/MFG-FRESHSTART/trabalho/GERADOR_WEB_R01_20261116/base/K1c-C-PL-R07i-T4_impressao_copia.stl')
GUIDE = Path('/mnt/user-data/uploads/MFG-FRESHSTART/entregas/ESTUDO_CONTORNO_ANATOMICO_R01_20261109/perfis_anatomicos_5_planos.csv')
slit, aperture, outer = c.xy_section(trimesh.load(BASE), 3.173)
table = np.loadtxt(GUIDE, delimiter=',', skiprows=1); target = table[abs(table[:, 0]-13) < .01, 4:6]
d = {k: np.array(p.exterior.coords).tolist() for k, p in zip(('slit', 'aperture', 'outer'), (slit, aperture, outer))}
d['target'] = target.tolist(); d['origem'] = {'base_stl_sha256': hashlib.sha256(BASE.read_bytes()).hexdigest(), 'guia_sha256': hashlib.sha256(GUIDE.read_bytes()).hexdigest(), 'construir_r08a_sha256': sha}
Path('dados/contornos_base.json').write_text(json.dumps(d), encoding='utf-8')
print('ok', Path('dados/contornos_base.json').stat().st_size, 'bytes')
