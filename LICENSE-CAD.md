# Licence for CAD, geometry and generated cuffs

**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)**

Copyright SenseCraft.

- Full legal code (canonical): <https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode>
- Plain-text copy in this repository: [`docs/licenses/CC-BY-NC-SA-4.0.txt`](docs/licenses/CC-BY-NC-SA-4.0.txt)
- Human-readable summary (not a substitute for the legal code): <https://creativecommons.org/licenses/by-nc-sa/4.0/>

## What this licence covers

| Path | What it is |
|---|---|
| `cad/**` | CAD generator sources, CAD assets and CAD documentation |
| `web/grade/*.stl` and `web/grade/*.json` | Pre-built cuff width variants used by the web app, and their index |
| `web/dados/**` | Print-ready base project (`.3mf`) and cuff section / opening data (`.json`) |
| `web/py/cuff_openings_*.json` | Cuff opening contours of the seven standard sizes, used for the size comparison |
| Any cuff produced by the app or the CLI (`.stl`, `.3mf`) | Generated cuffs are adaptations of the FreshCuff design and carry the same licence |

Everything else that is source code (`web/**/*.py`, `web/**/*.js`, `web/**/*.html`, `fc_cli.py`, `tests/**`, `tools/**`, `launchers/**`) is under the PolyForm Noncommercial License 1.0.0 in [`LICENSE`](LICENSE).

Third-party material keeps its own licence, listed in [`NOTICE.md`](NOTICE.md). In particular:

- `cad/assets/perfis_anatomicos_5_planos.csv` is derived from the CeTI-Age dataset (CC0). The derived profile is shared under CC BY-NC-SA 4.0. The CC0 source data stays free for anyone to use.
- `examples/Artec_Hand.ply` is "Hand" by Artec 3D under CC BY 3.0. It is **not** covered by this file.

## Attribution

When you share a FreshCuff cuff, a remix or a print photo, please credit it like this:

> FreshCuff by SenseCraft, https://github.com/sensecraft3d-eng/freshcuff-scanmade, licensed CC BY-NC-SA 4.0

If you changed the geometry, say so ("modified from FreshCuff by SenseCraft").

## Printing and selling

- Printing a cuff for yourself, for a family member, or for someone you help **without charging for it** is non-commercial use.
- Selling printed cuffs, or including them in a paid product or service, is commercial use and needs a separate licence. SenseCraft offers a commercial licence for prints through its MakerWorld membership. See the FreshCuff model page: <https://makerworld.com/en/models/3595433>.
- For any other commercial use, open a discussion or an issue on GitHub and ask.

## Trademarks

The SenseCraft name and the "S" logo (including `cad/assets/SenseCraft_Icone_S_CAD_H7p00_v1_1.dxf`) identify SenseCraft. The CC licence covers copyright only. It does not grant trademark rights (see Section 2(b)(2) of the legal code). Remixes must not suggest that SenseCraft made or endorses them.

## No warranty

As stated in Section 5 of the legal code, the material is provided as-is. FreshCuff is not a medical device. See the safety notes in [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).
