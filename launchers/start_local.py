#!/usr/bin/env python3
"""FreshCuff Fit - start the app locally, offline.

Serves the web/ folder of this repository on http://127.0.0.1:<port>/ (your own computer only, not reachable from
the network) and opens it in your default browser. Your scan is processed in the browser and never leaves this computer.

Normally started by one of the launchers next to this file:
  Windows: FreshCuff-Fit-Windows.bat   macOS: FreshCuff-Fit-macOS.command   Linux: freshcuff-fit-linux.sh

  python3 launchers/start_local.py [--port 8765] [--no-browser]

Uses tools/serve.py when present (same security headers and file types as the online site); otherwise falls back to
Python's built-in static server. Needs Python 3.8 or newer and nothing else (no pip installs, no internet).
"""
import argparse
import functools
import http.server
import importlib.util
import socket
import sys
import threading
import webbrowser
from pathlib import Path

ONLINE = 'https://sensecraft3d-eng.github.io/freshcuff-fit/'
ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'web'
SERVE = ROOT / 'tools' / 'serve.py'


def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def pick_port(first):
    for p in range(first, first + 50):
        if port_is_free(p):
            return p
    raise SystemExit(f'No free port between {first} and {first + 49}. Close other local servers or use --port.')


def load_serve_module():
    if not SERVE.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location('freshcuff_serve', SERVE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod if callable(getattr(mod, 'main', None)) else None
    except Exception as e:  # never block the user: fall back to the built-in server
        print(f'(tools/serve.py could not be loaded: {e}; using the built-in server instead)')
        return None


def serve_builtin(port):
    """Fallback: Python's static file server, bound to 127.0.0.1 only, with the MIME types the app needs."""
    class Handler(http.server.SimpleHTTPRequestHandler):
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                          '.wasm': 'application/wasm', '.mjs': 'text/javascript', '.js': 'text/javascript',
                          '.json': 'application/json', '.glb': 'model/gltf-binary', '.woff2': 'font/woff2',
                          '.whl': 'application/zip', '.zip': 'application/zip'}

        def log_message(self, fmt, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), functools.partial(Handler, directory=str(WEB)))
    print('(Using Python\'s built-in server: the app works the same, without the extra security headers.)')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(description='Start FreshCuff Fit locally (offline).')
    ap.add_argument('--port', type=int, default=8765, help='first port to try (default 8765)')
    ap.add_argument('--no-browser', action='store_true', help='do not open the browser')
    a = ap.parse_args(argv)

    if sys.version_info < (3, 8):
        raise SystemExit(f'Python 3.8 or newer is needed (found {sys.version.split()[0]}). '
                         f'Install a newer Python, or use the online version: {ONLINE}')
    if not (WEB / 'index.html').is_file():
        raise SystemExit(f'Could not find {WEB / "index.html"}. Run this from the unzipped FreshCuff Fit folder, '
                         f'or use the online version: {ONLINE}')
    if not any((WEB / 'pyodide').glob('pyodide*.js')):
        print('Warning: web/pyodide/ looks incomplete. The app needs it to run offline. '
              'Download the full repository again (Code -> Download ZIP).')

    port = pick_port(a.port)
    url = f'http://127.0.0.1:{port}/'
    print()
    print('  FreshCuff Fit is running on this computer only:')
    print(f'    {url}')
    print()
    print('  Your scan stays on this computer. Keep this window open while you use the app.')
    print('  To stop: close this window, or press Ctrl+C.')
    print()
    if not a.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()

    serve = load_serve_module()
    if serve is not None:
        try:
            return serve.main(['--port', str(port), '--host', '127.0.0.1', '--root', str(WEB)])
        except SystemExit:
            raise
        except Exception as e:
            print(f'(tools/serve.py stopped with an error: {e}; switching to the built-in server)')
    serve_builtin(port)
    return 0


if __name__ == '__main__':
    sys.exit(main())
