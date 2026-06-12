# Enclosure v4

Parametric CadQuery generator for the Basecamp bedside enclosure. Two-part matte black FDM print: body and lid.

**Final dimensions:** 96 x 136 x 49mm assembled, screen pod peak 74mm.

---

## Files

| File | Description |
|------|-------------|
| `enclosure_v4.py` | Parametric source of truth. All geometry driven by named constants at the top of the file. Edit here, never in the STEP/STL exports. |
| `basecamp_body_v4.step` | Body STEP for SolidWorks import or direct slicing |
| `basecamp_lid_v4.step` | Lid STEP |
| `basecamp_body_v4.stl` | Body STL for direct upload to print service |
| `basecamp_lid_v4.stl` | Lid STL |
| `validate.py` | Collision and watertightness test suite. Run after any geometry change. |
| `previews/` | Render images: body, lid, assembled (3 views each), 2D cross-sections |
| `archive/v3/` | v3 files retained for the build-log narrative |

---

## Generating the STL/STEP exports

```bash
pip install cadquery
python enclosure_v4.py
# Outputs: basecamp_body_v4.step/.stl, basecamp_lid_v4.step/.stl
```

Run validate.py afterward before sending to the printer:

```bash
pip install trimesh manifold3d
python validate.py
# All checks should print OK
```

---

## Print settings

### Body

- Orientation: flat on the base (no supports needed)
- Layer height: 0.2mm
- Infill: 20% gyroid
- Perimeters: 3 (ensures walls are solid at 3mm)
- Material: matte black PLA or PETG

### Lid

- Orientation: top face down on the build plate
- Supports: required under registration lip, boss columns, and pod interior cavity
- Layer height: 0.15mm for the pod slope (0.2mm acceptable elsewhere)
- Infill: 20% gyroid
- Perimeters: 3
- Material: same material as body -- thermal expansion must match

### Clearances

The design assumes 0.3-0.4mm FDM tolerance. Key mating features:

| Feature | Clearance |
|---------|-----------|
| Registration lip (body seat to lid lip) | 0.25mm per side |
| Chimney plug (lid plug to chimney walls) | 0.40mm per side |
| Magnet boss pocket (body-side recess) | 0.1mm per side |

If the lip binds after printing: sand the outer face of the lid lip with 400-grit, test fit, repeat. Do not sand the body seat.

---

## Magnet assembly procedure

The lid is held by 6 pairs of O6x3 N35 magnets (2 front, 2 rear, 2 mid-side). Body-side magnets sit recessed 0.8mm in wall-boss pockets; lid-side magnets glue in proud 0.8mm so the faces meet flush when the lid seats.

**CHECK POLARITY BEFORE GLUING.**

1. Dry-stack all 12 magnets into their intended pockets without glue.
2. Close the lid and verify it seats and releases cleanly.
3. Open the lid carefully without disturbing the magnets.
4. Mark the same face of each magnet (the face pointing away from the body wall) with a permanent marker.
5. Remove magnets one at a time, apply a small drop of CA glue or epoxy to the pocket, and replace each magnet mark-up on the body side and mark-down on the lid side.
6. Hold each pair in place for 30 seconds before moving to the next.
7. Allow full cure (CA: 5 minutes; epoxy: per package) before closing the lid.

Polarity error means two magnets repel instead of attract. If a pair repels after gluing, the magnet must be drilled out and replaced -- there is no non-destructive fix.

---

## Travel screws

Two M3x45 pan-head screws thread upward through the two rear hollow posts for transport (HK to Shenzhen to California relocations). Install only before travel; remove after arrival. Screw heads sit in counterbores under the base covered by rubber feet. The front posts were deleted in v4; only the two rear posts accept screws.

To install: remove the two rear rubber feet, drive M3x45 from below through the post bores, tighten to finger-tight plus a quarter turn. Replace feet over the counterbores after arrival.

---

## Assembly order

1. Mount Pi 4 on the four floor standoffs (M2.5 x 5mm). GPIO edge faces right (toward chimney), USB-C power port faces left.
2. Cable the Pi: right-angle USB-C adapter plugs into the Pi's USB-C port and exits through the left wall power slot (zero internal routing). Ethernet exits through the rear IO cutout.
3. Mount ESP32 nodes on their floor rails. Node 1 short USB-A-to-C cable (25cm) plugs directly into a rear Pi USB-A port. Node 2's 5m 20AWG USB-A-to-C cable plugs into the other rear Pi USB-A port and exits through the IO cutout.
4. Press SCD40 into the chimney card slot (foam wedge or Blu-Tack to hold it). Route wires through the grommet. Do this before flipping the box.
5. Mount SHT40 and SGP40 on the accessory boss grid (M2 self-tap, right side sensor zone floor).
6. Mount BH1750 under the lid light hole position, aligned to the countersink.
7. Mount INMP441 behind the mic funnel recess. The O6->O2.5 waveguide locates it; foam tape to secure.
8. Mount DS3231 RTC module on the I2C bus (address 0x68). Confirm CR2032 battery is installed before closing the lid.
9. Install RGB glow LED in the O3 hole in the lid, in front of the pod. Connect to GPIO pins defined in config.py.
10. Flip box. Drive 2x M3x45 pan-head from below through the rear posts only. Torque to finger-tight plus a quarter turn. Stick O12mm adhesive rubber feet over the counterbores (2 rear posts + 2 front corners inboard).
11. Slide screen module forward onto the rails until it stops against the front wall. Glass sits 0.7mm below the outer face. Apply a single strip of tape across the rear edge (anti-rattle only). Connect ribbon cable before inserting.
12. Close lid. Listen for the magnetic click at all six points. The registration lip aligns the parts; magnets provide the closing force. Travel screws are NOT installed unless transporting.

SD card is accessible through the 8mm gap under the baffle without removing the lid.

---

## Ventilation (v4)

Intake air enters through base slots (sensor-zone floor slots and chimney floor slot), hidden by the foot gap. Chimney exhaust exits through the rear wall. The sensor zone vents through the under-baffle gap into the compute zone and out the rear IO opening. Pi warmth drives a continuous room->sensor->compute->out flow; air never flows compute->sensor, so sensor-zone readings are upstream of all heat sources except the ESP32 nodes.

Left wall has only the ESP32 USB service slot and the Pi power slot. Right wall is blank.

---

## Geometry reference

Key internal coordinates (X = width, Y = length, Z = up from floor):

| Feature | Position |
|---------|----------|
| Inner cavity | X +-45, Y +-65, Z 3-46 |
| Baffle (sensor/compute split) | Y -29 (front face), 8mm cable gap at floor |
| Pi PCB footprint | X -28..28, Y -20..65, ports flush with inner rear wall |
| Pi standoffs | (+-24.5, -18.5), (+-24.5, 39.5) |
| Rear IO cutout | 58mm wide, Z 8-27 |
| ESP32 rails | X -38..18, Y -57.5..-29.5 |
| USB service slot (left wall) | Y -57.5, Z 5-14 |
| Pi power slot (left wall) | beside USB-C port, Z 5-14 |
| Chimney interior | X -45..-29, Y 30..65 |
| SCD40 card slot ribs | X -38..-33.8, Y 36..54 |
| Grommet | left chimney wall, Y 45, Z 13 |
| Rear corner posts (travel screws) | (+-40.7, -61.35), O6.5 |
| Screen pod Y span | Y -22..36 (low edge front, faces bed) |
| BH1750 countersink | lid, sensor zone |
| Mic funnel | front wall, O6->O2.5 waveguide |
| Recovery glow LED hole | lid, O3, in front of pod |
| Condensation drain | front wall, O2, at floor level |
| Magnet bosses (body) | 2 front wall, 2 rear wall, 2 mid side walls |

See `hardware/bom.md` for the full component BOM.
