# Scanning a hand for FreshCuff Fit

The app needs a 3D scan of the hand that will wear the cuff. It looks closely at one region: a 26 mm band just behind the knuckles, plus enough of the hand around it to find the knuckles and the thumb. This guide explains how to get a scan that works.

**You do not need a scanner to use FreshCuff.** The seven standard sizes and the printed sizing rings on [MakerWorld](https://makerworld.com/en/models/3595433) work without one. A scan adds a size comparison and, for hands in the custom range, a cuff shaped to the back of the hand.

## The pose

```
          fingers straight,
          small gaps between them
              │ │ │ │
              │ │ │ │
              │ │ │ │
          ┌───┴─┴─┴─┴───┐   ← knuckles: the cuff sits just behind them
   thumb  │             │
   away ─►│   palm or   │
   from   │  back side  │
   palm   │             │
          └──┐       ┌──┘
             │       │      ← straight wrist
             │       │      ← about 5 cm of forearm
             └───────┘
```

- **Relaxed, open hand.** Fingers straight or gently relaxed, not curled. Curled fingers change the shape of the knuckles and can make the back of the hand and the palm hard to tell apart.
- **Fingers close together, but with a small gap between them.** The app finds the knuckles by looking for where the fingers separate in the scan. If the fingers touch along their whole length, they merge into one blob and the app will ask you to mark the knuckles by hand.
- **Thumb held away from the palm.** The app uses the thumb to tell left from right and back from palm. A thumb pressed against the hand also hides part of the band.
- **Straight wrist** in line with the forearm.
- **Include about 5 cm of forearm** beyond the wrist, so the whole band and some margin are in the scan.
- **Keep still.** Small movements during a scan cause doubled or smeared surfaces. Rest the elbow or forearm on a table edge, with the hand held out over the edge in the air so the scanner can go all the way round. If possible, have someone else hold the scanner or phone.
- **Same pose for the tape measurement** (see below).

## What must be in the scan

| Region | Needed? |
|---|---|
| From the finger bases to about 3 cm behind the knuckles, **all the way round**: back, palm and both sides | **Yes, and closed, with no holes.** Holes within 10 mm of the band stop the custom build. |
| Where the fingers and the thumb separate from the hand | Yes. These are the landmarks. |
| Fingertips | Helpful, not essential. Small holes are fine. |
| Forearm end | Open (cut off) is fine |
| Table, stand, arm rest, other hand | **No.** Remove them before export. Tiny loose bits are dropped automatically, but anything attached to the hand is not. |

## Phone apps

A phone can produce a usable scan if the pose is held still. Expect a smoother, slightly less exact surface than with a dedicated scanner, and always do the tape check.

| App | Platform | Notes |
|---|---|---|
| **Polycam** | iOS, Android | The free plan exports **GLB**, in **metres**. The app converts metres automatically. |
| **Scaniverse** | iOS, Android | Free. Export a mesh format the app reads (STL, OBJ, PLY or GLB), not a splat. |
| **KIRI Engine** | iOS, Android | Photo-scan mode. Check which export formats your plan allows. |
| **Heges** | iOS (Face ID devices) | Can use the front depth camera, which is made for close range. Check the export options. |
| **3d Scanner App** | iOS (LiDAR devices) | Free. Exports several mesh formats. |

Export options and plans change. Check before you scan that the app can export one of the formats in [File formats](#file-formats).

**Phone tips:**

- Use good, even, diffuse light. Avoid harsh shadows and direct sun.
- Plain, matte surroundings work best. Reflective jewellery is best removed.
- In photo mode, take many overlapping photos while circling the hand: above, below and both sides. Get **under the palm**, because it is the side most often missed.
- Process at the highest quality the app offers.

## Handheld scanners

Handheld structured-light scanners give the best results. Any of them works if it can export a mesh in millimetres:

- **Shining 3D EinScan** (my own hand is being scanned by a professional service with an EinScan Rigil)
- **Revopoint** (POP, MINI, INSPIRE, RANGE, MIRACO and others)
- **Creality** (CR-Scan series)
- **Bambu Lab S1**

**Scanner tips:**

- Follow the scanner's instructions for scanning skin and body parts (exposure, tracking mode, distance).
- Scan the whole circumference of the band. Overlap the start and end of the pass across the back of the hand rather than across the palm.
- In the scanner software: merge, **fill small holes** (especially around the knuckles and between the finger bases), remove the background and supports, and export in **millimetres**.
- Do not over-smooth: heavy smoothing flattens the knuckles.

## File formats

| Format | Read? | Note |
|---|---|---|
| STL (binary or ASCII) | Yes | No units in the file. The app guesses metres, centimetres or millimetres from the size. |
| OBJ | Yes | Texture files (`.mtl`, images) are not needed |
| PLY | Yes | Colours are ignored |
| GLB (binary glTF) | Yes | Usually in metres |
| USDZ | Yes, in the web app | Converted to a mesh in the page first |
| FBX, 3MF, STEP, point clouds (E57, XYZ), Gaussian splats | No | Convert to STL, OBJ or PLY first (e.g. in MeshLab or Blender) |

**Units.** The app guesses the units from the size of the hand (see [METHOD.md](METHOD.md#1-reading-the-scan)). If the guess is wrong, for example with an unusual unit, enter the scale by hand (millimetres per file unit) in the advanced options. On the command line, use the matching option of `fc_cli.py`.

**File size.** Up to about 150 MB. Very dense scans (several million triangles) are slower. If your scan is much denser, decimate it in the scanner software to around 1 million triangles or fewer. The sample scan has 800,000 triangles.

## Tape measure check

Measure around the knuckles with a soft tailor's tape in the **same pose** as the scan:

1. Hand open, fingers straight and together, thumb away from the palm.
2. Put the tape around the widest part of the knuckles: across the back of the hand over the four knuckles and across the palm at the same level, with the thumb outside the tape.
3. Snug but not tight: the tape lies flat on the skin without denting it.
4. Read it to the nearest millimetre (e.g. 20.8 cm).

Enter this value in the app. The app takes the same measurement on the scan, around the convex outline at the knuckle line. If the two differ by more than **0.6 cm**, the app does not trust the scale or the pose and will not build a custom cuff. Usual causes are a wrong unit guess, fingers spread differently, or the tape at a different place.

The tape also gives the standard size directly:

| Size | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| Tape around the knuckles (cm) | < 18.2 | 18.2–19.3 | 19.3–20.4 | 20.4–21.6 | 21.6–22.7 | 22.7–23.8 | ≥ 23.8 |

## Before you load the scan: checklist

- [ ] One hand only. Table and supports removed.
- [ ] Band region closed all the way round (back, palm, sides).
- [ ] Fingers and thumb visibly separate where they leave the hand.
- [ ] Exported as STL, OBJ, PLY, GLB or USDZ.
- [ ] Tape measurement around the knuckles written down.
- [ ] You know whether it is a left or right hand. The app checks it, and so should you.

## Privacy reminder

Your scan is processed in your own browser and never uploaded. If you share results with me, please share the **report file**, not the scan, unless you choose otherwise. See [PRIVACY.md](../PRIVACY.md).
