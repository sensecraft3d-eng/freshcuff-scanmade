#!/usr/bin/env python3
"""FreshCuff CAD build: one command for the solids in this repository.

    python cad/build.py size 4 --out cad/out/size4          # a standard size (1-7, or "all")
    python cad/build.py custom params.json --out cad/out/me  # a custom cuff (width, side, optional dorsal profile)
    python cad/build.py grid --out cad/out/grid              # the 18 width variants used by the web app

Each build writes STEP + STL into a new folder (the output folder must not exist yet; nothing is overwritten).
Every solid is made by the original generator scripts in cad/src, each in its own Python process.
Requirements: pip install cadquery-ocp trimesh shapely scipy numpy matplotlib   (manifold3d for the checks)
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

CAD = Path(__file__).resolve().parent
SRC = CAD / 'src'
sys.path.insert(0, str(SRC))
import paths  # noqa: E402

GRID_WIDTHS = [80 + 0.5 * i for i in range(9)]       # W 80.0 ... 84.0 mm
SIDES = (('R', False), ('L', True))                  # label, mirrored (left hand)
SIZE4_W = 82.0


def width_params(W):
    """DW, DH for an opening width W (mm), relative to size 4 (W = 82 mm). Same formula as gerar_grade_rl_pc.py."""
    return (W - SIZE4_W) / 2, round(35.5 * (W / SIZE4_W - 1), 4)


def size_table():
    """{size: (W, DW, DH)} from cad/assets/verifica_tamanhos.json (the table the seven published sizes were checked against)."""
    t = json.loads(paths.SIZE_TABLE.read_text(encoding='utf-8'))
    return {int(k): (float(v['W']), float(v['DW']), float(v['DH'])) for k, v in t.items()}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_script(args, log_path=None):
    """Run a cad/src script in a new Python process. Return (ok, seconds, tail of the output)."""
    t0 = time.time()
    p = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, encoding='utf-8', errors='replace')
    dt = time.time() - t0
    out = p.stdout + p.stderr
    if log_path is not None and Path(log_path).parent.exists():
        Path(log_path).write_text(out, encoding='utf-8')
    return p.returncode == 0 and 'STEP e STL exportados' in p.stdout, dt, out.strip().splitlines()[-3:]


def fresh(out):
    out = Path(out).resolve()
    if out.exists():
        sys.exit(f'error: {out} already exists. Builds never overwrite; choose a new --out folder.')
    return out


def load_checks():
    """Manufacturing checks of the grid (gerar_grade.medir/trava). Needs manifold3d; returns None if it is missing."""
    try:
        import manifold3d  # noqa: F401
    except ImportError:
        print('note: manifold3d is not installed, so the manufacturing checks are skipped (pip install manifold3d).')
        return None
    import gerar_grade as GG
    ns = GG.funcoes_medida()
    ref = paths.reference_stl()           # built once into cad/out/_cache (about 25 s)
    return lambda stl, dw, dh: (lambda r: dict(r, falhas=GG.trava(r)))(GG.medir(ns, stl, dw, dh, ref))


# ----------------------------------------------------------------------------------------------- size
def build_size(sizes, out):
    table = size_table()
    out = fresh(out)
    multi = len(sizes) > 1
    if multi:
        out.mkdir(parents=True)
    ok_all = True
    for n in sizes:
        if n not in table:
            sys.exit(f'error: size {n} is not in {paths.SIZE_TABLE.name} (sizes {sorted(table)})')
        W, DW, DH = table[n]
        target = out / f'size{n}' if multi else out
        if n == 4:      # the base generator itself (DW = DH = 0); this is the script that made the published size 4
            args = [SRC / 'construir_r08a.py', target]
        else:
            args = [SRC / 'construir_r08a_tam.py', target, '--tam', n, '--dw', DW, '--dh', DH]
        print(f'size {n}: W {W:g} mm, DW {DW:g}, DH {DH:g} ...', flush=True)
        ok, dt, tail = run_script(args, target / 'build.log')
        stl = target / f'FreshCuff_R08A_T{n}.stl'
        print(f'  {"ok" if ok else "FAILED"} in {dt:.1f} s' + (f'  {stl}' if ok else '\n  ' + '\n  '.join(tail)), flush=True)
        ok_all &= ok
    return 0 if ok_all else 1


# ----------------------------------------------------------------------------------------------- custom
def read_params(path):
    """Accepts the parametros.json written by the web app / fc_cli.py (W, dw, dh, esquerda, rotulo, dorso)
    or a short English file: {"W": 82.5, "side": "L", "dorsal_profile": "dorso.json"} (the profile is optional)."""
    path = Path(path).resolve()
    p = json.loads(path.read_text(encoding='utf-8'))
    if 'W' not in p:
        sys.exit('error: the parameters need "W" (opening width, mm)')
    W = float(p['W'])
    side = p.get('side')
    if side is None:
        left = bool(p.get('esquerda', False))
    else:
        side = str(side).strip().lower()
        if side not in ('l', 'left', 'r', 'right'):
            sys.exit('error: "side" must be L/left or R/right')
        left = side in ('l', 'left')
    dw, dh = width_params(W)
    dw, dh = float(p.get('dw', dw)), float(p.get('dh', dh))
    prof = p.get('dorsal_profile', p.get('dorso'))
    if prof:
        prof = (path.parent / prof).resolve()
        d = json.loads(prof.read_text(encoding='utf-8'))
        if not ('x_T4' in d and 'raise' in d and len(d['x_T4']) == len(d['raise']) > 1):
            sys.exit(f'error: {prof} needs two equal-length lists "x_T4" and "raise" (mm)')
    label = p.get('rotulo') or ('L' if left else 'R')
    return dict(W=W, dw=dw, dh=dh, left=left, label=label, profile=str(prof) if prof else None)


def build_custom(params_file, out, checks=True):
    import varredura as V
    V.RUN = V.RUN.replace('import construir_r08a_custom as g', 'import construir_r08a_scan as g')
    p = read_params(params_file)
    out = fresh(out)
    if not 80.0 <= p['W'] <= 84.0:
        print(f'warning: W {p["W"]:g} mm is outside 80-84 mm, the range the web grid and its checks were validated for.')
    vid = f'W{p["W"]:.1f}_{"L" if p["left"] else "R"}'
    print(f'custom {vid}: DW {p["dw"]:g}, DH {p["dh"]:g}, profile {p["profile"] or "none"} ...', flush=True)
    out.mkdir(parents=True)
    r = V.rodar(dict(id=vid, dw=p['dw'], dh=p['dh'], esquerda=p['left'], rotulo=p['label'], dorso=p['profile']), out)
    stl = out / vid / f'cuff_{vid}.stl'
    rec = dict(id=vid, W=p['W'], dw=p['dw'], dh=p['dh'], side='left' if p['left'] else 'right', label=p['label'],
               dorsal_profile=p['profile'], built=bool(r['exportou']), seconds=r['segundos'], error=r.get('erro') or None)
    if rec['built']:
        rec['stl_sha256'] = sha256(stl)
        check = load_checks() if checks else None
        if check:
            rec['checks'] = check(stl, p['dw'], p['dh'])
    (out / 'build.json').write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding='utf-8')
    fails = (rec.get('checks') or {}).get('falhas')
    print(f'  {"ok" if rec["built"] else "FAILED"} in {rec["seconds"]} s'
          + (f'  {stl}' if rec['built'] else f'  {rec["error"]}')
          + (f'\n  checks failed: {fails}' if fails else ('\n  checks passed' if 'checks' in rec else '')), flush=True)
    return 0 if rec['built'] and not fails else 1


# ----------------------------------------------------------------------------------------------- grid
def build_grid(out, only=None, jobs=1, checks=True, web=False):
    """Same variants and file names as cad/src/gerar_grade_rl_pc.py (W 80-84 step 0.5, R and L, no dorsal profile)."""
    import varredura as V
    V.RUN = V.RUN.replace('import construir_r08a_custom as g', 'import construir_r08a_scan as g')
    cases = []
    for W in GRID_WIDTHS:
        dw, dh = width_params(W)
        for label, left in SIDES:
            cases.append(dict(id=f'W{W:.1f}_{label}', W=W, dw=dw, dh=dh, esquerda=left, rotulo=label))
    if only:
        unknown = set(only) - {c['id'] for c in cases}
        if unknown:
            sys.exit(f'error: unknown variant(s) {sorted(unknown)}; ids look like W82.0_R')
        cases = [c for c in cases if c['id'] in only]
    out = fresh(out)
    out.mkdir(parents=True)
    check = load_checks() if checks else None
    t0 = time.time()

    def one(c):
        r = V.rodar(c, out)
        print(f'{c["id"]}: {"ok" if r["exportou"] else "FAILED " + str(r.get("erro"))} in {r["segundos"]} s', flush=True)
        return c, r

    index = []
    with cf.ThreadPoolExecutor(max(1, jobs)) as ex:
        for c, r in ex.map(one, cases):
            stl = out / c['id'] / f'cuff_{c["id"]}.stl'
            rec = dict(id=c['id'], W=c['W'], dw=c['dw'], dh=c['dh'], lado='esq' if c['esquerda'] else 'dir', rotulo=c['rotulo'],
                       gerou=bool(r['exportou']), segundos=r['segundos'], erro=r.get('erro'))
            if rec['gerou']:
                if check:
                    rec.update(check(stl, c['dw'], c['dh']))
                else:
                    rec['falhas'] = []
                rec['stl_sha256'] = sha256(stl)
            index.append(rec)
    # same index name and fields as gerar_grade_rl_pc.py, so cad/src/preparar_grade_web.py can refine it for the web app
    (out / 'indice_grade_rl.json').write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding='utf-8')
    built = [r for r in index if r['gerou']]
    failed_checks = [r['id'] for r in built if r.get('falhas')]
    print(f'{len(built)} of {len(index)} built in {time.time() - t0:.0f} s'
          + ('' if check is None else f'; checks failed: {failed_checks}' if failed_checks else '; all checks passed'), flush=True)
    rc = 0 if len(built) == len(index) and not failed_checks else 1
    if web and built:
        # refined meshes as in web/grade/ (conforming subdivision; same volume) + indice_grade_web.json
        q = subprocess.run([sys.executable, str(SRC / 'preparar_grade_web.py'), str(out), str(out / 'web')])
        rc = rc or q.returncode
        print(f'web-ready meshes: {out / "web"}')
    return rc


def main(argv=None):
    ap = argparse.ArgumentParser(description='Build FreshCuff solids (STEP + STL) from the CAD sources in cad/src.',
                                 epilog='Output folders must not exist yet; nothing is overwritten. Units: mm.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('size', help='a standard size, 1-7 (or "all")')
    s.add_argument('size', help='1..7 or all')
    s.add_argument('--out', required=True, type=Path)
    c = sub.add_parser('custom', help='a custom cuff from a parameters JSON (web app / fc_cli.py parametros.json, or W/side/dorsal_profile)')
    c.add_argument('params', type=Path)
    c.add_argument('--out', required=True, type=Path)
    c.add_argument('--no-checks', action='store_true', help='skip the manufacturing checks')
    g = sub.add_parser('grid', help='the 18 width variants of the web app (W 80-84 mm, right and left)')
    g.add_argument('--out', required=True, type=Path)
    g.add_argument('--only', nargs='+', metavar='ID', help='build only these variants, e.g. W82.0_R W82.5_L')
    g.add_argument('--jobs', type=int, default=1, help='variants built in parallel (each needs about 1 GB of RAM)')
    g.add_argument('--no-checks', action='store_true', help='skip the manufacturing checks')
    g.add_argument('--web', action='store_true', help='also write the refined meshes and index used by web/grade/ into OUT/web')
    a = ap.parse_args(argv)
    if a.cmd == 'size':
        sizes = list(range(1, 8)) if a.size == 'all' else [int(a.size)]
        return build_size(sizes, a.out)
    if a.cmd == 'custom':
        return build_custom(a.params, a.out, checks=not a.no_checks)
    return build_grid(a.out, a.only, a.jobs, checks=not a.no_checks, web=a.web)


if __name__ == '__main__':
    sys.exit(main())
