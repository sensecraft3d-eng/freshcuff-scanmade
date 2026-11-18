#!/usr/bin/env python3
"""Local dev/test server for FreshCuff ScanMade.

Serves web/ with the same security headers as web/_headers (CSP etc.) and correct MIME types
(.wasm, .mjs, .glb, .3mf ...). Nothing here is needed in production (Cloudflare Pages reads _headers).

  python3 tools/serve.py [--port 8765] [--root web] [--dev]

--dev also mounts tests/e2e/mock/ at /__mock/ (used only by the UI mock mode, ?mock=1).
"""
import argparse, http.server, os, socketserver, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
MIME = {'.wasm': 'application/wasm', '.mjs': 'text/javascript', '.js': 'text/javascript', '.json': 'application/json',
        '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.3mf': 'model/3mf', '.stl': 'model/stl',
        '.ply': 'application/octet-stream', '.whl': 'application/zip', '.zip': 'application/zip',
        '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.css': 'text/css', '.html': 'text/html; charset=utf-8',
        '.md': 'text/markdown; charset=utf-8', '.usdz': 'model/vnd.usdz+zip'}


def read_headers(root: Path):
    """Parse the '/*' block of a Cloudflare-style _headers file."""
    out, on = [], False
    f = root / '_headers'
    if not f.exists():
        return out
    for line in f.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith((' ', '\t')):
            on = line.strip() == '/*'
            continue
        if on and ':' in line:
            k, v = line.strip().split(':', 1)
            out.append((k.strip(), v.strip()))
    return out


def make_handler(root: Path, dev: bool):
    headers = read_headers(root)
    mock = HERE / 'tests' / 'e2e' / 'mock'

    class H(http.server.SimpleHTTPRequestHandler):
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **MIME}

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def translate_path(self, path):
            p = path.split('?', 1)[0].split('#', 1)[0]
            if dev and p.startswith('/__mock/'):
                rel = p[len('/__mock/'):]
                return str((mock / rel).resolve())
            return super().translate_path(path)

        def end_headers(self):
            for k, v in headers:
                self.send_header(k, v)
            self.send_header('Cache-Control', 'no-cache')
            super().end_headers()

        def log_message(self, fmt, *args):
            if os.environ.get('FC_SERVE_LOG'):
                super().log_message(fmt, *args)

    return H


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--root', default=str(HERE / 'web'))
    ap.add_argument('--dev', action='store_true')
    a = ap.parse_args(argv)
    root = Path(a.root).resolve()
    with Server((a.host, a.port), make_handler(root, a.dev)) as httpd:
        print(f'FreshCuff ScanMade: serving {root} at http://{a.host}:{a.port}/', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    sys.exit(main())
