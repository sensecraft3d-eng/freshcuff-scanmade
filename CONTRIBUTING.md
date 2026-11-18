# Contributing to FreshCuff Fit

Thank you for helping! FreshCuff is an assistive device, so the most valuable contributions are **real-world observations**, followed by fixes that make the app more robust or clearer.

## Ways to help

1. **Try the app with your own hand scan** and send a [fit feedback report](https://github.com/sensecraft3d-eng/freshcuff-fit/issues/new?template=fit-feedback.yml). Refusals and confusing messages count too.
2. **Print and dry-fit** a cuff (standard or custom) and report what you observed. Please follow the safety notes in [docs/USER_GUIDE.md](docs/USER_GUIDE.md).
3. **Report bugs** with the [bug form](https://github.com/sensecraft3d-eng/freshcuff-fit/issues/new?template=bug.yml).
4. **Improve the documentation.** Clearer wording, translations, and better scanning tips for a particular app or scanner.
5. **Code.** See below.

## Hand scans and personal data

- **Never commit a hand scan of a real person** unless that person has explicitly agreed to publish it under a licence that allows redistribution. Even then, open an issue first to discuss it.
- Local test scans should be named `*.private.*` (e.g. `myhand.private.stl`). `.gitignore` excludes these.
- Do not put names, photos or health details of wearers in issues, commits or test fixtures.

## Development setup

```bash
git clone https://github.com/sensecraft3d-eng/freshcuff-fit.git
cd freshcuff-fit
python -m pip install numpy scipy shapely trimesh matplotlib networkx pytest
python -m pytest -m "not slow"        # fast tests (what CI runs)
python -m pytest                       # everything, including slow end-to-end runs
python tools/serve.py                  # serve web/ at http://127.0.0.1:8765/
```

Use Python 3.12 if you can, the same version as the browser runtime (Pyodide 0.27.7). The browser uses numpy 2.0.2, scipy 1.14.1, shapely 2.0.6, trimesh 5.2.1, matplotlib 3.8.4 and networkx 3.4.2. If the CLI and the browser disagree, test with those versions first.

### Repository layout

| Path | What |
|---|---|
| `web/` | The static web app (what GitHub Pages serves) |
| `web/py/` | The Python core, shared by the browser, the CLI and the tests |
| `web/grade/`, `web/dados/` | Pre-built cuff width variants, base 3MF project and section data (CAD licence) |
| `web/pyodide/`, `web/vendor/` | Self-hosted Pyodide runtime and three.js (third-party licences, see NOTICE.md) |
| `fc_cli.py` | Command-line entry point |
| `cad/` | CAD generator sources and assets (OpenCascade); see `cad/README.md` |
| `tests/` | Python tests; `tests/e2e/` is the browser test |
| `tools/` | Developer tools (local server, manifest builder, vendoring scripts) |
| `launchers/` | Offline launchers for end users |
| `docs/` | User, maker, scanning, method and validation documentation |

### Rules for changes to the core

- **Keep numerical behaviour unless the change is the point.** Fit decisions and cuff geometry must not drift silently. If a change alters results on the sample scan, say so in the pull request, explain why, and update the expected values in the tests and the numbers in `docs/VALIDATION.md`.
- **Never weaken a safety check** (manufacturing checks, the re-check against the scan, refusals) without discussion in an issue first.
- **The browser and CPython must give the same answer.** Code in `web/py/` runs in Pyodide (wasm32: 32-bit integer indices, no `rtree`, no `manifold3d`, no `sklearn`, no `lxml`). Avoid dependencies that Pyodide does not ship.
- After changing anything the worker loads (`web/py/`, `web/dados/`, `web/grade/`, the sample scan), run `python tools/build_manifest.py` to refresh `web/manifesto.json`.
- **No network calls** from the app or the CLI. No analytics, no CDNs. Everything is served from the same origin.
- User-facing text is in plain English (and Portuguese where the UI offers it). Avoid internal jargon.
- Mark slow tests with `@pytest.mark.slow`.

### Pull requests

- One topic per pull request, with a short description of what changed and how you tested it.
- CI must pass: Python tests on Linux, Windows and macOS, plus the browser test.
- By contributing, you agree that your contribution is licensed under the same terms as the part of the repository it touches: PolyForm Noncommercial 1.0.0 for code, CC BY-NC-SA 4.0 for CAD and geometry. You also agree that SenseCraft may offer it under the commercial licences described in the README, as it does for the rest of the project. If you cannot agree to that, please say so in the pull request before it is merged.

## Code of conduct

Be kind and patient. Many people reading these issues live with disabilities or care for someone who does. Respect their privacy and their expertise about their own needs. Harassment or disrespect will not be tolerated, and maintainers may remove such comments.
