"""Where the CAD scripts find their inputs.

Every path is relative to this file (cad/src/), so the scripts run from a clean clone
on any machine, from any working directory, without PYTHONPATH tweaks.
"""
from pathlib import Path

SRC = Path(__file__).resolve().parent          # cad/src
CAD = SRC.parent                               # cad
REPO = CAD.parent                              # repository root
ASSETS = CAD / 'assets'

# Inputs of the generator (construir_r08a.py)
BASE_STL = ASSETS / 'freshcuff_base_size4.stl'            # previous revision (R07i, size 4); only its z = 3.173 section is used
GUIDE_CSV = ASSETS / 'perfis_anatomicos_5_planos.csv'     # anatomical dorsal guide, 5 planes
LOGO_DXF = ASSETS / 'SenseCraft_Icone_S_CAD_H7p00_v1_1.dxf'
SIZE_TABLE = ASSETS / 'verifica_tamanhos.json'            # W, DW, DH of the seven standard sizes
MARK_DIR = SRC                                            # folder that holds marca_num.py

# Files the PC-side scan/grid scripts read from the web app (read only)
WEB = REPO / 'web'
WEB_PY = WEB / 'py'
WEB_DATA = WEB / 'dados'
BASE_3MF = WEB_DATA / 'FreshCuff_R08A_T4_LISA_P1S_R05b.3mf'
SWAP_MESH_3MF = WEB_PY / 'trocar_malha_3mf_v4b_custom.py'

# Generated outputs (git-ignored)
OUT = CAD / 'out'
CACHE = OUT / '_cache'
# Reference solid for the fastener-region check: size-4 geometry (DW = DH = 0), label "C".
REF_ID = 'W82_ref'
REF_STL = CACHE / REF_ID / f'cuff_{REF_ID}.stl'


def reference_stl():
    """Return the W82 reference STL used by the fastener check, building it once if it is missing (about 30 s)."""
    if REF_STL.exists():
        return REF_STL
    import varredura
    CACHE.mkdir(parents=True, exist_ok=True)
    r = varredura.rodar(dict(id=REF_ID, dw=0., dh=0., esquerda=False, rotulo='C'), CACHE)
    if not REF_STL.exists():
        raise RuntimeError(f'could not build the reference solid {REF_STL}: {r.get("erro")}')
    return REF_STL
