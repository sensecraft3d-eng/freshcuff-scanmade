# -*- coding: utf-8 -*-
"""Protótipo fase 1 (LIBERADO_CAD 15/11, hash 2e32d33b0b02) · grade pré-validada da faixa B antes da V1.
W 80–84 de 0,5 em 0,5, DH = proporcional (DH extra = 0 antes da V1, G27), dorso 0, direita e esquerda = 18 variantes.
Para cada variante:
 1. gera o sólido com a CÓPIA do gerador (../faixa/gerador_copia; construir_r08a.py importado do original, só leitura);
 2. trava por peça: G01, G03–G08 e G13 pelas medidas de seção (mesmo método de ../faixa/medir.py);
 3. troca a malha no 3MF base (lisa/P1S R05b) com o trocar_malha_3mf_v4b_custom.py original (só leitura, saída nova);
 4. extrai 3D/Objects/object_1.model e Metadata/model_settings.config para variantes/<id>/ (é o que a página usa).
O modelo base vai descompactado para modelo_base/ (a página remonta o 3MF no navegador).
Uso: python gerar_grade.py   (PYTHONPATH com o OCP)"""
import json, subprocess, sys, zipfile, hashlib
from pathlib import Path
AQ = Path(__file__).resolve().parent; FX = AQ  # repository: medir.py and varredura.py are in cad/src (originally ../faixa)
sys.path.insert(0, str(FX))
import paths
BASE3MF = paths.BASE_3MF
TROCA = paths.SWAP_MESH_3MF
import varredura as V

def funcoes_medida():
    src = (FX / "medir.py").read_text(encoding="utf-8").split("saida = Path(sys.argv[1])")[0]
    ns = {}; exec(src, ns); return ns

def medir(ns, stl, dw, dh, ref):
    import numpy as np, trimesh
    m = trimesh.load(stl); M = ns["mf"](m); M4 = ns["mf"](trimesh.load(ref)); reg = ns["box"](-20, 20, -29.3, -20, -1, 27)
    n = ns["sections"](m, 13.003); th, lat, st = ns["spans"](n, dw, dh)
    fx = float(((M ^ reg) - (M4 ^ reg)).volume() + ((M4 ^ reg) - (M ^ reg)).volume())
    return dict(estanque=bool(m.is_watertight), pecas=len(m.split()), faixa_z=round(float(m.extents[2]), 3),
                abertura_L=round(float(np.ptp(ns["xvals"](n[1], 0))), 2), abertura_H=round(float(np.ptp(ns["yvals"](n[1], 0))), 2),
                lamina_min=round(min(v for _, v in th), 3), vao_lateral_min=round(min(v[-1] for v in lat), 3),
                aro_ombro_min=round(min(v for _, v in st), 3), fenda=round(float(np.ptp(ns["yvals"](n[2], 0))), 3),
                fix=round(fx, 4), maior=round(float(max(m.extents)), 1))

def trava(r):
    f = []
    if not (r["estanque"] and r["pecas"] == 1): f.append("G01")
    if not (25.95 <= r["faixa_z"] <= 26.05): f.append("G03")
    if r["lamina_min"] < 0.85: f.append("G04")
    if r["vao_lateral_min"] < 0.6: f.append("G05")
    if r["fix"] > 0.1: f.append("G06")
    if not (1.95 <= r["fenda"] <= 2.25): f.append("G07")
    if r["aro_ombro_min"] < 7.2: f.append("G08")
    if r["maior"] > 160: f.append("G13")
    return f

if __name__ == "__main__":
    saida = AQ / "geracao"; saida.mkdir(exist_ok=True); var = AQ / "variantes"; var.mkdir(exist_ok=True)
    base = AQ / "modelo_base"
    if not base.exists():
        with zipfile.ZipFile(BASE3MF) as z: z.extractall(base)
    ref = paths.reference_stl(); ns = funcoes_medida(); indice = []
    for i in range(9):
        W = 80 + 0.5 * i; dw = (W - 82) / 2; dh = round(35.5 * (W / 82 - 1), 4)
        for lado in ("dir", "esq"):
            vid = f"W{W:.1f}_{lado}"
            r = V.rodar(dict(id=vid, dw=dw, dh=dh, esquerda=(lado == "esq"), rotulo="C"), saida)
            stl = saida / vid / f"cuff_{vid}.stl"
            reg = dict(id=vid, W=W, dw=dw, dh=dh, lado=lado, gerou=bool(r.get("exportou")), segundos=r["segundos"], erro=r.get("erro"))
            if reg["gerou"]:
                reg.update(medir(ns, stl, dw, dh, ref)); reg["falhas"] = trava(reg)
                if not reg["falhas"]:
                    out3 = saida / vid / f"cuff_{vid}.3mf"
                    args = [sys.executable, str(TROCA), str(BASE3MF), str(stl), str(out3), "--costura-pulseira", "--dw", str(dw), "--dh", str(dh)]
                    if lado == "esq": args.append("--espelhado")
                    p = subprocess.run(args, capture_output=True, text=True); reg["troca_rc"] = p.returncode; reg["troca_log"] = (p.stdout + p.stderr)[-300:]
                    if p.returncode == 0:
                        (var / vid).mkdir(exist_ok=True)
                        with zipfile.ZipFile(out3) as z:
                            for nome, dest in (("3D/Objects/object_1.model", "object_1.model"), ("Metadata/model_settings.config", "model_settings.config")):
                                (var / vid / dest).write_bytes(z.read(nome))
                        reg["sha256_object"] = hashlib.sha256((var / vid / "object_1.model").read_bytes()).hexdigest()[:16]
            print(json.dumps(reg, ensure_ascii=False), flush=True); indice.append(reg)
            (AQ / "grade_relatorio.json").write_text(json.dumps(indice, indent=1, ensure_ascii=False), encoding="utf-8")
    ok = [r for r in indice if r.get("sha256_object")]
    (var / "indice.json").write_text(json.dumps([{k: r[k] for k in ("id", "W", "lado", "abertura_L", "abertura_H", "lamina_min", "sha256_object")} for r in ok], indent=1), encoding="utf-8")
    print("variantes prontas:", len(ok))
