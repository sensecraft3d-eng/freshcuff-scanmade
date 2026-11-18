# -*- coding: utf-8 -*-
"""Servidor local de TESTE que aplica os cabeçalhos do arquivo _headers (como o Cloudflare Pages faria), para provar a CSP.
Uso: python servir_com_csp.py <pasta_raiz> <pasta_do_site_relativa> <porta>"""
import sys, http.server, functools
from pathlib import Path
raiz, site, porta = Path(sys.argv[1]), sys.argv[2].strip('/'), int(sys.argv[3])
cab = {}
for l in (raiz / site / '_headers').read_text(encoding='utf-8').splitlines():
    if l.startswith('  ') and ':' in l:
        k, v = l.strip().split(':', 1); cab[k.strip()] = v.strip()
class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.wasm': 'application/wasm', '.mjs': 'text/javascript', '.js': 'text/javascript'}
    def end_headers(self):
        if self.path.startswith('/' + site + '/'):
            for k, v in cab.items(): self.send_header(k, v)
        super().end_headers()
http.server.ThreadingHTTPServer(('127.0.0.1', porta), functools.partial(H, directory=str(raiz))).serve_forever()
