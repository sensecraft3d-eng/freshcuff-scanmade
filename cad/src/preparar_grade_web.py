"""Prepara a grade R/L (gerada no PC por gerar_grade_rl_pc.py) para a página: refina no plano xy (arestas ≤ 1 mm na região
dorsal, divisão conforme, a malha continua fechada e com o mesmo volume) e grava grade/indice_grade_web.json com hashes.
Uso: python preparar_grade_web.py <pasta grade_rl> <pasta site/grade>"""
import sys, json, hashlib
from pathlib import Path
import trimesh, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent)); import subdiv
src, dst = Path(sys.argv[1]), Path(sys.argv[2]); dst.mkdir(parents=True, exist_ok=True)
idx = json.loads((src / 'indice_grade_rl.json').read_text(encoding='utf8')); out = []
for r in idx:
    f = src / r['id'] / f"cuff_{r['id']}.stl"
    if not f.exists() or not r.get('gerou'): continue
    assert hashlib.sha256(f.read_bytes()).hexdigest() == r['stl_sha256'], r['id']
    m = trimesh.load(f); m2 = subdiv.refinar_xy(m, 1.0)
    assert m2.is_watertight and abs(m2.volume - m.volume) < 1e-6 * m.volume, r['id']
    nome = f"{r['id']}.stl"; alvo = dst / nome; assert not alvo.exists(), f'{alvo} já existe'
    m2.export(alvo); b = alvo.read_bytes()
    out.append(dict(r, arquivo=nome, faces=len(m2.faces), bytes=len(b), sha256_refinado=hashlib.sha256(b).hexdigest(), refino='xy ≤ 1,0 mm, y > 1 mm'))
    print(r['id'], len(m.faces), '→', len(m2.faces), len(b))
(dst / 'indice_grade_web.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf8')
