# Example scan

## `Artec_Hand.ply`

**"Hand" by Artec 3D**: <https://www.artec3d.com/3d-models/hand>
Licensed under **Creative Commons Attribution 3.0** (CC BY 3.0): <https://creativecommons.org/licenses/by/3.0/>

The file is included unchanged so that anyone can try FreshCuff Fit without a scanner ("Try with a sample hand" in the app). Artec 3D does not endorse this project. If you reuse the file, credit Artec 3D as above. This sample is **not** covered by the FreshCuff licences.

| Property | Value |
|---|---|
| Format | PLY, binary little-endian |
| Size | 15.2 MB (15,200,290 bytes) |
| Mesh | 400,002 vertices, 800,000 triangles, closed (watertight) |
| Units | millimetres (about 183 × 158 × 48 mm) |
| Hand | **left** (as read by the app from the thumb position) |
| SHA-256 | `66d3291d5285a05fbaa9137972cc80c38cb42f640cb96fd59377beea23465109` |

The person whose hand was scanned is unknown. Nobody has worn a cuff made from this scan. It is a demonstration and test input only.

### Run it

- **Browser:** open the app and click **Try with a sample hand**.
- **Command line:**

  ```bash
  python fc_cli.py examples/Artec_Hand.ply --out out/artec --side left --tape-cm 18.2 --build
  ```

  The tape value of 18.2 cm is the circumference the app measures on the scan itself (18.22 cm). There is no physical tape measurement for this hand.

Expected results for the current version are listed in [docs/VALIDATION.md](../docs/VALIDATION.md).

## Your own scans

Do not add scans of real people to this folder unless they have agreed to publish them under a licence that allows redistribution. For local testing, name files `*.private.*` (for example `myhand.private.stl`). Git ignores them.
