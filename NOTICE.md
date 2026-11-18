# Notices and third-party credits

FreshCuff ScanMade is copyright SenseCraft.

- Source code: PolyForm Noncommercial License 1.0.0 ([`LICENSE`](LICENSE)).
- CAD, geometry and generated cuffs: CC BY-NC-SA 4.0 ([`LICENSE-CAD.md`](LICENSE-CAD.md)).

Required Notice: Copyright SenseCraft (https://github.com/sensecraft3d-eng/freshcuff-scanmade)

The components below are included in this repository or served with the web app. Each keeps its own licence. The licence text of every Python wheel is inside the wheel itself (`*.dist-info/`), and the three.js licence is in `web/vendor/three/LICENSE`.

## Data and sample files

| Item | Where | Author / source | Licence |
|---|---|---|---|
| "Hand" sample scan | `examples/Artec_Hand.ply` (and any copy in `web/examples/`) | Artec 3D, <https://www.artec3d.com/3d-models/hand> | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) |
| Base solid of the size-4 cuff (from which all sizes and custom cuffs are derived) | `cad/assets/freshcuff_base_size4.stl` | SenseCraft | CC BY-NC-SA 4.0 |
| Anatomical dorsal profile used to shape the standard cuff | `cad/assets/perfis_anatomicos_5_planos.csv` | Derived by SenseCraft from the CeTI-Age dataset by Muschter et al., <https://doi.org/10.6084/m9.figshare.23502060.v1> (data descriptor: <https://doi.org/10.1038/s41597-023-02738-3>) | Source data [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/); derived file CC BY-NC-SA 4.0 |

**Attribution for the sample scan:** "Hand" by Artec 3D, <https://www.artec3d.com/3d-models/hand>, licensed under CC BY 3.0 as stated in the downloaded file (Artec's model page currently lists CC BY 4.0). The file is unchanged. FreshCuff ScanMade uses it only as a demonstration input. Artec 3D does not endorse this project.

## Browser runtime (served from `web/`)

| Component | Version | Licence | Project |
|---|---|---|---|
| Pyodide (CPython compiled to WebAssembly, loader and packages lock file) | 0.27.7 | MPL-2.0 | <https://pyodide.org> |
| CPython standard library (`python_stdlib.zip`, part of Pyodide) | 3.12 | PSF-2.0 | <https://www.python.org> |
| three.js and the add-ons in `web/vendor/three/addons/` (OrbitControls, STL/OBJ/PLY/GLTF/USDZ loaders, STLExporter, BufferGeometryUtils) | 0.170.0 | MIT | <https://threejs.org> |
| fflate (bundled with the three.js add-ons) | as shipped with three.js 0.170.0 | MIT | <https://github.com/101arrowz/fflate> |
| Inter font (`InterVariable.woff2`) | variable | SIL Open Font License 1.1 | <https://rsms.me/inter/> |

## Python packages (Pyodide wheels in `web/pyodide/`; installed from PyPI for the CLI and tests)

| Package | Version in `web/pyodide/` | Licence |
|---|---|---|
| numpy | 2.0.2 | BSD-3-Clause (with bundled components listed in its licence file) |
| OpenBLAS (shared library used by numpy and scipy) | 0.3.26 | BSD-3-Clause |
| scipy | 1.14.1 | BSD-3-Clause (with bundled components listed in its licence files) |
| shapely | 2.0.6 | BSD-3-Clause |
| GEOS (`libgeos`, bundled inside the shapely wheel) | as shipped with shapely 2.0.6 | LGPL-2.1 |
| trimesh | 5.2.1 | MIT |
| networkx | 3.4.2 | BSD-3-Clause |
| matplotlib | 3.8.4 | Matplotlib License (PSF-based); bundled DejaVu fonts under their own free licence |
| matplotlib-pyodide | 0.2.3 | MPL-2.0 |
| contourpy | 1.3.0 | BSD-3-Clause |
| cycler | 0.12.1 | BSD-3-Clause |
| kiwisolver | 1.4.5 | BSD-3-Clause |
| fonttools | 4.51.0 | MIT |
| pillow | 10.2.0 | HPND (MIT-CMU) |
| pyparsing | 3.1.2 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 or BSD-3-Clause (dual) |
| pytz | 2024.1 | MIT |
| decorator | 5.1.1 | BSD-2-Clause |
| packaging | 24.2 | Apache-2.0 or BSD-2-Clause (dual) |
| setuptools | 69.5.1 | MIT |
| six | 1.16.0 | MIT |

The wheels are the unmodified builds distributed with Pyodide 0.27.7 (plus trimesh 5.2.1 from PyPI). They are hosted next to the app so it works offline and without third-party requests. `web/pyodide/manifesto_dependencias.json` lists their SHA-256 hashes.

**LGPL note (GEOS):** GEOS is dynamically linked inside the shapely wheel (`shapely.libs/libgeos*.so`). You can replace it by rebuilding the shapely wheel for Pyodide from the sources at <https://github.com/shapely/shapely> and <https://github.com/libgeos/geos>, then putting it in `web/pyodide/`.

## CAD toolchain (not shipped, needed only to regenerate solids)

The CAD generator in `cad/src/` uses OpenCascade through the `cadquery-ocp` Python bindings (OCP, Apache-2.0; OpenCascade Technology, LGPL-2.1 with exception). The optional manufacturing checks in `cad/build.py` use manifold3d (Apache-2.0). These are installed by the maker and are not distributed here.

## Product and contest

FreshCuff is SenseCraft's entry in MakerWorld's "Make for Good" accessibility contest. The standard cuff, sizing rings and accessories are published at <https://makerworld.com/en/models/3595433>. MakerWorld and Bambu Lab are trademarks of their owners. Their mention here does not imply endorsement.
