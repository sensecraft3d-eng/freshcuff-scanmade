#!/usr/bin/env python3
"""Regenerates web/manifesto.json (sha256 of every file the worker loads into Python, plus page assets the
page checks itself). Run after changing anything in web/py, web/dados, web/grade or web/examples.

  python3 tools/build_manifest.py [--check]

Keys:
  arquivos  -> files the worker copies into the Python file system (py/**, dados/**, grade/**). Grid variants
               (grade/W*.stl) are fetched only when needed, but are still checked against this list.
  pagina    -> files the page fetches directly and checks (sample scan).
"""
import hashlib, json, sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / 'web'
PY_EXT = {'.py', '.json', '.txt', '.csv', '.npz', '.npy'}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def collect():
    files = {}
    for p in sorted((WEB / 'py').rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix in PY_EXT:
            files[p.relative_to(WEB).as_posix()] = sha(p)
    for d in ('dados', 'grade'):
        for p in sorted((WEB / d).rglob('*')):
            if p.is_file():
                files[p.relative_to(WEB).as_posix()] = sha(p)
    page = {}
    for p in sorted((WEB / 'examples').glob('*')):
        if p.is_file() and p.suffix.lower() in {'.ply', '.stl', '.obj', '.glb'}:
            page[p.relative_to(WEB).as_posix()] = sha(p)
    return {'gerador': 'FreshCuff Fit web', 'arquivos': files, 'pagina': page}


def main():
    new = collect()
    out = WEB / 'manifesto.json'
    if '--check' in sys.argv:
        old = json.loads(out.read_text(encoding='utf-8'))
        bad = [k for k in set(old.get('arquivos', {})) | set(new['arquivos'])
               if old.get('arquivos', {}).get(k) != new['arquivos'].get(k)]
        bad += [k for k in set(old.get('pagina', {})) | set(new['pagina']) if old.get('pagina', {}).get(k) != new['pagina'].get(k)]
        print('manifest OK' if not bad else 'manifest out of date: ' + ', '.join(sorted(bad)))
        return 1 if bad else 0
    out.write_text(json.dumps(new, indent=1) + '\n', encoding='utf-8')
    print(f"wrote {out} ({len(new['arquivos'])} python-side files, {len(new['pagina'])} page files)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
