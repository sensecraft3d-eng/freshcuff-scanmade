# -*- coding: utf-8 -*-
"""Compatibilidade do navegador (Pyodide, wasm32): np.bincount recusa índices int64 ("Cannot cast int64 to int32 'safe'"),
o que quebra trimesh.section/graph. Aqui os inteiros viram intp (32 bits no wasm) antes do bincount. Os índices de malha
cabem com folga em 32 bits (< 2^31). No CPython de 64 bits isto não muda nada (intp já é int64)."""
import numpy as np
_bincount = np.bincount
def _bincount_intp(x, *a, **k):
    x = np.asarray(x)
    if x.dtype.kind in 'iu' and x.dtype != np.intp:
        if x.size and (x.max() > np.iinfo(np.intp).max):
            raise OverflowError('índice grande demais para bincount no navegador')
        x = x.astype(np.intp)
    return _bincount(x, *a, **k)
np.bincount = _bincount_intp
