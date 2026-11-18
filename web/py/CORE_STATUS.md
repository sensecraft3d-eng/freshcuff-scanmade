# FreshCuff ScanMade core — status for integrators

Last update: all phases done (API, fixtures, fast engine, robustness, no-dead-end orientation, quality score, strings,
CLI, tests, HTML report). Verified in CPython 3.13 and in the vendored Pyodide 0.27.7 under Node (`tests/run_pyodide_node.mjs`).

## Files to load (all in `web/py/`)

New (must be added to `manifesto.json` and written to `/app/py` by the worker):
`fc_api.py`, `fc_core.py`, `fc_fastfit.py`, `fc_mesh.py`, `fc_strings.py`, `report_html.py`.
Still required, unchanged (validated code): `freshcuff_fit.py`, `gerador_scan.py`, `gerador_web.py`, `nucleo_r08a.py`,
`campo_dorso.py`, `medir_original.py`, `conferir_cuff_gerado.py`, `trocar_malha_3mf_v4b_custom.py`,
`cuff_openings_R08A_v2.json`, `compat_wasm.py`. Data: `dados/aberturas_grade_W80_84.json`, `dados/contornos_base.json`,
`dados/FreshCuff_R08A_T4_LISA_P1S_R05b.3mf`, `grade/indice_grade_web.json` + the chosen `grade/W??.?_[RL].stl`.

Directory layout expected: `py/` and `dados/` are siblings (analyze() looks for `../dados/aberturas_grade_W80_84.json`
relative to `fc_api.py`; override with `opts.data_dir` in prepare()).
matplotlib is no longer imported by the main path (it can be dropped from `loadPackage` to save start-up time;
networkx is still needed by trimesh sections).

## Calling sequence (worker)

```python
import compat_wasm, json, fc_api as A
p = A.prepare('/work/scan.ply', '/work/job1', {'side': 'auto', 'tape_cm': None, 'mm_per_unit': None, 'lang': 'en'}, progress=cb)
# p.status: 'ok' | 'needs_input' | 'refused'      -> show /work/job1/preview.glb
a = A.analyze('/work/job1', {overrides}, progress=cb)
# a.status: 'custom_ready' | 'standard_only' | 'refused' | 'needs_input'   -> /work/job1/analysis.glb
# if custom_ready: fetch grade/<a.custom.variant>.stl into grid_dir, then
b = A.build('/work/job1', '/app/grade', '/app/dados', progress=cb)
# b.status: 'cuff_ready' | 'stopped'   -> files.3mf / files.stl / files.report_json / files.report_html, /work/job1/result.glb
A.release('/work/job1')     # free the meshes when the job is closed
```
Every function returns a plain dict (already JSON-safe: `json.dumps(result)` works). All paths in results are
relative to `work_dir`. `progress` is an optional callable receiving a short English string.
Re-running is allowed: prepare() with the same file re-uses the loaded mesh; analyze()/build() write to new
sub-folders (`analysis_NN/`, `build_NN/`) and overwrite only `preview.glb`, `analysis.glb`, `result.glb`,
`analysis.json`, `build.json`, `fc_state.json`.

### prepare(scan_path, work_dir, opts) → dict
`opts`: `mm_per_unit` (float|None), `side` ('auto'|'left'|'right'), `tape_cm` (float|None), `lang` ('en'|'pt'),
`display_faces` (default 80000), `data_dir`, plus any analyze() override (to refresh the preview after a flip/click).

```
status            'ok' | 'needs_input' | 'refused'
scan              {file, sha256, faces, vertices, extent_mm[3], units_guess ('mm'|'cm'|'m'|'inch'|'custom'), units_confidence,
                   mm_per_unit, watertight, open_edges, open_edges_near_band, components,
                   quality:{score 0-100, notes:[str]}}
landmarks         {side 'left'|'right'|null, side_confidence, fingers_end 'high'|'low', fingers_confidence,
                   dorsum 'kept'|'flipped', dorsum_confidence,
                   knuckle_z (view, always -12.8), thumb_z (view|null), band:{z0:-13, z1:13},
                   knuckle_s, thumb_s (stable scan-axis coordinates, see "Clicks"),
                   knuckle_circumference_cm, knuckle_width_mm, knuckle_thickness_mm, found_automatically,
                   clues:{arch,thumb,curl:{back_is_plus_y, weight}, knuckle_arch_mm, finger_curl_mm, finger_pieces_low_high},
                   ambiguities:[{kind:'dorsum'|'fingers'|'side'|'knuckles'|'thumb', message,
                                 candidates:[{label, overrides:{...}, is_guess:bool, side?}]}]}
preview_glb       'preview.glb'  nodes: 'hand' (mesh, vertex colours), 'knuckle_line' (line), 'band_0'..'band_4' (lines),
                  'thumb' (line, where the thumb leaves the palm)
overlays          {knuckle_line:[ring], band:[5 rings], thumb:[ring]}   each ring = [[x,y,z],...] in the view frame
                  (same geometry as the line nodes, for custom drawing, e.g. fat lines)
frame             {axis_to_view: 4x4, scan_to_view: 4x4 (file units → view mm), view_to_axis_z:{a,b}}
overrides_applied the normalised overrides used for this reading
messages          [{level:'info'|'warn'|'error', code, text}]
seconds
```
`needs_input`: show `landmarks.ambiguities[*].message` and one button per `candidates[*].label`; on click call
analyze(work_dir, candidate.overrides) (or prepare() again with them to refresh the preview first). The preview always
shows the best guess (`is_guess: true`). `refused` (unreadable file, one-sided/open surface): only `messages` (and a
plain preview when a mesh could be loaded).

### analyze(work_dir, overrides) → dict
`overrides` (all optional; merged over what prepare() got): `side`, `dorsum` ('auto'|'keep'|'flip'), `fingers`
('auto'|'high'|'low'), `knuckle_s`, `thumb_s`, `knuckle_z`, `thumb_z`, `band_shift_mm` (+ = toward the wrist, ±15),
`tape_cm`, `lang`.
* `dorsum` / `fingers` are absolute with respect to the scan axis frame; you never need to reason about them: use a
  candidate's `overrides`, or toggle relative to `landmarks.dorsum` ('kept' → send 'flip') / `landmarks.fingers_end`.
* `tape_cm` missing → warning only. Given and off by more than 0.6 cm → status 'refused' (scale/pose in doubt).

```
status              'custom_ready' | 'standard_only' | 'refused' | 'needs_input' (ambiguity not yet resolved: same
                    landmarks.ambiguities as prepare; nothing is computed until the user picks)
sizes               [{size 1..7, fits, rigid_min, dorsal_min, lateral_min, rotation_deg, at_search_limit[], note}]
recommended_size    smallest standard size that fits by shape (falls back to the tape size)
size_by_tape, smallest_fitting_size, knuckle_circumference_cm:{scan, tape}
custom              null | {W, side, variant ('W82.0_L' → grade/W82.0_L.stl), dorsal_profile_mm_min (≤0, ≥-3),
                     lateral_clearance_mm, palm_compression_mm, pose:{rotation_deg, dx_mm, dy_mm}, spring_travel_mm,
                     predicted:{closest_section_gap_before, after, share_le_0p5, max_overlap,
                                all_sections_gap_before, all_sections_gap_after, raw_after},
                     profile:{x_mm[], gap_before_mm[], lowering_mm[]}}
custom_range        [{W, fits, rigid_min, dorsal_min, lateral_min}]  (the 9 widths W 80–84)
sections            5 × {z_cuff, distance_from_knuckles_mm, hand[[x,y]], opening_standard[[x,y]], opening_custom[[x,y]]}
                    (right-hand CAD frame, seated pose; used by the report charts)
result_glb          'analysis.glb'  nodes: 'hand' (band zone coloured by predicted gap), 'knuckle_line',
                    'cuff_outline_0..4' (inner contour of the chosen cuff at the 5 sections)
heatmap_for         {kind:'custom', W} | {kind:'standard', size}
legend              [{mm, rgb:[r,g,b]}]  gap colour stops (negative = cuff presses into the skin)
landmarks, frame, overlays, overrides_applied, messages, seconds
```
### build(work_dir, grid_dir, data_dir) → dict
```
status         'cuff_ready' | 'stopped'
files          {stl, 3mf (only when cuff_ready), report_json, report_html}
locks          {checks:[{name, value, limit, unit, ok}], failures:[name], raw:{...}, max_displacement_mm}
verification   {verdict 'approved'|'rejected', failures[], gap_difference_mm, same_pose:{...}, free_pose:{...}, limits:{...}}
result_glb     'result.glb'  nodes: 'hand' (band coloured by gap to the GENERATED solid), 'cuff' (the generated solid)
hashes         {stl_sha256, 3mf_sha256}
legend, frame, messages, seconds
```
A lock failure or a rejected verification gives status 'stopped' with the reason in `messages`; no 3MF is handed out.

## View frame (all GLBs, overlays, cuff)
Millimetres. +y = back of the hand, +z = toward the wrist, band centre at z = 0 (band z ∈ [-13, 13], knuckle end at
z = -12.8). x: right hand → thumb at -x, little finger at +x; left hand → thumb at +x (true geometry; the left cuff
is the mirrored solid). It is the coordinate frame of the cuff that is produced, shifted by -13 mm in z, so
`result.glb` 'cuff' vertices = STL vertices - (0,0,13). preview.glb uses a nominal seating (hand upright and centred);
analysis.glb / result.glb use the computed seating, so reload the camera target but keep the camera.
GLB meshes have per-vertex colours (COLOR_0) and **no normals**: call `geometry.computeVertexNormals()` and use
`vertexColors: true`. Lines are GL line primitives (1 px in WebGL); use `overlays` to draw thicker ones.
The hand mesh in GLBs is a vertex-clustered copy for display (≤ 80k faces); measurements always use the full scan.

## Clicks (knuckle line / thumb base)
Take the clicked point in view coordinates and send its `z`:
`analyze(work, {knuckle_z: p.z})` (or `thumb_z`). Internally this becomes the stable coordinate
`knuckle_s = frame.view_to_axis_z.a * z + frame.view_to_axis_z.b`; you may send `knuckle_s` yourself instead (it does
not depend on later flips or frame changes). To undo a click send `knuckle_s: null, knuckle_z: null` via prepare().

## Fixtures (full run on examples/Artec_Hand.ply, side left, tape 18.2)
`tests/fixtures/artec/prepare.json`, `analyze.json`, `build.json`, `report.json`, `report.html`,
`preview.glb` (1.3 MB), `analysis.glb` (1.3 MB), `result.glb` (3.1 MB). Regenerate: `python tests/make_fixtures.py`.

## Numbers (Artec sample, 800k faces, 2 cores)
| | legacy R07 | new core |
|---|---|---|
| CPython 3.13 | 128 s (analysis 115, build 12.6) | ≈ 19–20 s (prepare 3, analyze 11, build 6) |
| Pyodide 0.27.7 (Node 22 / V8, wasm32) | 300–450 s in Chrome (reported) | 33 s (prepare 5.4, analyze 17.5, build 10.5) + 4 s boot |

Same result as legacy: variant W82.0_L, gap 2.52 → 0.72 mm, max overlap 0.44 mm, locks identical, verification
approved (gap difference +0.005 mm), generated STL sha256 identical (9f9de1ad…762c) in CPython **and** in Pyodide.
The 3MF differs from the legacy one only in the embedded object name.

## Behaviour notes for the UI
* `needs_input` never blocks: the preview shows the best guess; every ambiguity has a message and (for
  dorsum/side/fingers) candidate buttons whose `overrides` you pass straight to analyze() or prepare().
  `knuckles` / `thumb` ambiguities have no candidates: ask for a click and send `knuckle_z` / `thumb_z`.
* If the user tells the hand side (`side: 'left'|'right'`), back/palm is decided by the thumb side and most scans
  need no question at all. With `side: 'auto'` a scan whose clues disagree (e.g. a fist) returns `needs_input`.
* Overrides persist for the session (work_dir): later analyze() calls only need what changed.
* `refused` reasons are about the scan itself (open surface, hole in the band, band on the thumb base, tape mismatch);
  each message says what to do. For `band_thumb`, offer `band_shift_mm` (negative = toward the fingers).
* `standard_only`: `custom` is null, `sizes`/`recommended_size` are valid, the heat map shows the recommended size.
* Left hands: the 7 standard sizes are compared as mirrored prints (message `left_mirror_note`). The legacy reader
  compared left hands against the un-mirrored openings; this is a deliberate change — confirm it matches how left
  users are told to print standard sizes.
* Languages: `lang: 'en'` (complete) or `'pt'` (same keys; falls back to English). `messages[*].code` is stable.
* `scan.quality.score`: 100 minus penalties (triangle size at the band, holes at the band −50, loose pieces,
  units confidence, open sections, manual/uncertain orientation, incomplete band, oblique band).

## Tests
`python -m pytest tests -m "not slow"` (34 tests, ≈ 1 min) · `python -m pytest tests -m slow` (16 tests, ≈ 3.5 min,
Artec end-to-end vs the legacy reference, rotation/units/mirror, CLI) · `FC_RUN_LEGACY=1 pytest -m legacy` re-runs the
original code (2 min) · `node tests/run_pyodide_node.mjs [scan side tape]` runs the pipeline in the vendored Pyodide.
`tests/synth_hand.py` builds a synthetic hand (numpy voxel union) used by the fast tests.

## Known limits
* Pose selection keeps the validated 0.25 mm lateral grid with tie-breaks: a re-sampled copy of the same scan
  (float32 file in metres) may seat one step aside → predicted gaps move by up to ≈ 0.06 mm; W did not change in tests.
* Units: centimetres vs inches cannot be told apart between 15 and 20 units (cm assumed, warning shown).
* A fist / curled hand (PaddleUp scan) is oriented correctly with the side given or one click, but its band section
  includes the folded fingers and that scan has a hole in the band → refused with the hole message.
* One-sided scans (S53) are refused with the open-surface message.
* Hands slower than Artec: a thin hand in a tall opening needs more pose evaluations (synthetic hand: analyze ≈ 23 s
  CPython). Next optimisation, not done: prune contour points with the same Lipschitz bound.

## Progress
- [x] Phase 1: API, GLBs, fixtures.
- [x] Phase 2(a) speed · (b) units, rotation, mirror, open meshes, loose pieces · (c) needs_input + overrides ·
      (d) quality score · (e) optional tape · (f) string table en/pt, no internal codes.
- [x] Phase 3: `fc_cli.py`, pytest suite, `report_html.py` (build() returns `files.report_html`).

## Release gates (cross-review round, 2026-11-18) — what changed for the UI
* **analyze() statuses**: `custom_ready` (custom possible AND tape given and within 0.6 cm of the scan) ·
  `custom_needs_tape` (custom possible, scale not confirmed: `custom`, `sizes`, heat map are returned, `needs:['tape_cm']`;
  call analyze(work, {tape_cm}) again — the geometry is cached, it returns in about a second) · `standard_only`
  (no custom; at least one standard size passed) · `no_verified_standard_fit` (no custom and no standard size passed:
  `recommended_size` is null, message `no_verified_fit`) · `refused` · `needs_input`.
* **recommended_size** is only ever a size that passed the geometric check; otherwise null (also null on `refused`).
  `size_by_tape` stays as a separate estimate, with `size_by_tape_source: 'tape'|'scan'`. New field `scale_confirmed`.
* **build()**: returns `status:'needs_input'`, `needs:['tape_cm']`, `files:{}` when the scale is not confirmed (nothing
  is built). On `stopped`, `files` holds only `report_json` / `report_html`, `hashes` is empty (`diagnostic_hashes`
  has them) and the solid is kept in work_dir as `*.stl.rejected` / `*.3mf.rejected`.
* Ambiguous units (confidence < 0.9) add message `units_confirm`; the tape is what unblocks manufacturing.
* Non-manifold edges at the band refuse the scan (`nonmanifold_near_band`); `scan.nonmanifold_edges`,
  `scan.nonmanifold_near_band` added to prepare().
* CLI: `--build` requires `--tape-cm` (argparse error, exit 2).
* Tests: `tests/test_release_gates.py`.
