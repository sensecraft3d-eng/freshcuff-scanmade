# FreshCuff maker guide

*For the person who prints, assembles and checks a FreshCuff, especially a custom one from FreshCuff Fit, before handing it to a user.*

> **Experimental.** Custom cuffs are checked in CAD and software only. Nobody has worn one yet. Treat every custom cuff as a prototype for a **supervised dry fit**. Read the [User guide](USER_GUIDE.md) safety section, and go through it with the user.

## What you need

| Item | Source |
|---|---|
| Custom cuff `.3mf` (or `.stl`) and the **fit report** | From the user, made by FreshCuff Fit |
| Latch plate, heads (soft brush, comb, sponge basket, universal head) and the hardware listed for the kit | FreshCuff kit on MakerWorld: <https://makerworld.com/en/models/3595433>. The custom cuff uses the **same fastener region** as the standard cuffs, so the standard plate and heads fit unchanged. |
| PETG filament, about 0.4 mm nozzle | Any good PETG. The 3MF uses the Bambu PETG HF profile. |
| Bambu Studio | <https://bambulab.com/en/download/studio> (or another slicer, using the STL) |
| Flush cutters, a deburring tool or fine sandpaper (400–600 grit), calipers | Workshop |

## 1. Check the files

1. Open the fit report. Check that it says the cuff was **accepted**. The app only writes files for an accepted cuff, but a report travels separately and may be from another run.
2. Check that the hand side in the report (**right/left**) matches the user, and note the width **W**.
3. The report lists SHA-256 hashes of the `.3mf` and `.stl`. If you received the files by e-mail or chat, you can check them (Windows: `certutil -hashfile file.3mf SHA256`; macOS/Linux: `shasum -a 256 file.3mf`).

## 2. Print settings (already in the 3MF)

The 3MF is a complete Bambu Studio project. **Use it as is** unless you have a reason to change something.

| Setting | Value in the 3MF |
|---|---|
| Printer | Bambu Lab P1S, 0.4 mm nozzle |
| Process | 0.20 mm layers (0.20 mm first layer) |
| Filament | PETG (Bambu PETG HF profile), nozzle 240 °C |
| Plate | Textured PEI, bed 80 °C |
| Walls | 4 loops, Arachne wall generator |
| Top / bottom shells | 5 / 5 layers |
| Infill | 15% gyroid, plus a **100% infill modifier around the fastener housings** (a separate modifier part; keep it) |
| Supports | None |
| Brim | None |
| Seam | Aligned, with **seam painting** on the cuff (keep it) |
| Orientation | As placed: standing on one edge of the band. **Do not lay it flat or rotate it.** The cuff, the spring leaf and the print settings are set up for this orientation. |

### Printing on another Bambu Lab printer (X1 series, A1 series, P1P)

1. Open the 3MF in Bambu Studio.
2. In the **Prepare** tab, select your printer in the printer box (top left) and keep a **0.4 mm nozzle**.
3. Choose a PETG profile for that printer, e.g. *Bambu PETG HF @BBL <your printer>*, or your own calibrated PETG.
4. Check that the plate type matches your plate, and that the modifier part and the seam painting are still there.
5. Slice, and check the preview: the walls of the spring leaf should be continuous, and nothing should be floating.

On other slicers, import the `.stl` and match the table above as closely as you can. Add a modifier with 100% infill around the fastener housings.

### Dry PETG

Wet PETG strings and makes weak, rough layers. If your PETG has been open for a while, dry it according to the manufacturer's instructions.

## 3. Post-processing

1. Let the plate cool, then remove the part.
2. **Spring slot:** the narrow slot (about 2.1 mm) behind the spring leaf must be completely clear. Remove any strings bridging it. The leaf must move freely.
3. **Skin-contact edges:** lightly deburr the edges of the opening, especially at the ends of the band, where it meets the skin. Do not thin the spring leaf.
4. Check the **engraving** under the latch-plate area: a custom cuff shows **R** or **L** and an arrow pointing to the fingers.
5. Wash with mild soap and water and let it dry.

## 4. Assembly

Follow the FreshCuff assembly instructions on the [MakerWorld page](https://makerworld.com/en/models/3595433). For a custom cuff, one extra rule applies:

- **The triangle on the latch plate goes on the side of the engraved arrow.** That way, when the cuff is worn with the fingers up, the triangle still marks "up" as on the standard cuffs.

Then attach the head the user needs.

## 5. Checks before handing the cuff to the user

| # | Check | Pass |
|---|---|---|
| 1 | One piece, no cracks, no layer separation, especially where the spring leaf joins the frame | ☐ |
| 2 | Spring leaf: press the middle gently toward the slot. It moves freely, does not touch anything before its stop, and springs back fully. | ☐ |
| 3 | No sharp edges, strings or blobs on any surface that touches the skin | ☐ |
| 4 | Inner opening width across the band, measured with calipers, is close to the **W** in the report. A difference of more than about 0.5 mm suggests a printer calibration or shrinkage issue: fix that before fitting. | ☐ |
| 5 | Letter **R/L** matches the user's hand | ☐ |
| 6 | Latch plate locks as on a standard cuff. Each head attaches and stays put under a firm tug. | ☐ |
| 7 | Cuff washed and dry | ☐ |

## 6. First fitting (with the user)

Do the first fitting **together**, following the user guide's [dry fit table](USER_GUIDE.md#dry-fit-what-to-look-for):

1. Explain how to take it off before putting it on.
2. Dry fit for a few minutes without the head, then with the head and gentle brushing movements.
3. Take it off and check the skin. Wait about 20 minutes and check again.
4. If anything is wrong, **do not modify the cuff with heat or tools**. Note what happened and report it (see below). A different width or a standard size may be the answer.

## 7. Please report back

A short **[fit feedback report](https://github.com/sensecraft3d-eng/freshcuff-fit/issues/new?template=fit-feedback.yml)** from you or the user is the most useful contribution you can make: printer, filament, what fitted and what did not. Attach the app's report JSON if the user agrees. **Do not attach the user's scan** without their explicit consent.

## Licence reminder

The cuff geometry is licensed **CC BY-NC-SA 4.0**. You can print it for a user free of charge. **Selling** printed cuffs needs SenseCraft's commercial licence. See [LICENSE-CAD.md](../LICENSE-CAD.md).
