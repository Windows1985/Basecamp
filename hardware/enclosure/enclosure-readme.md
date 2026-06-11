# Enclosure

Parametric CadQuery generator for the Basecamp bedside enclosure. Two-part matte black FDM print: body and lid.

**Final dimensions:** 96 x 136 x 54mm assembled, screen pod peak 79mm.

---

## Files

| File | Description |
|------|-------------|
| `enclosure_v3.py` | Parametric source of truth. All geometry is driven by named constants at the top of the file. Edit here, never in the STEP/STL exports. |
| `basecamp_body_v3.step` | Body STEP for SolidWorks import or direct slicing |
| `basecamp_lid_v3.step` | Lid STEP |
| `basecamp_body_v3.stl` | Body STL for direct upload to print service |
| `basecamp_lid_v3.stl` | Lid STL |
| `validate.py` | Collision and watertightness test suite. Run after any geometry change. |
| `previews/` | Render images: body, lid, assembled (3 views each), 2D cross-sections |

---

## Generating the STL/STEP exports

```bash
pip install cadquery
python enclosure_v3.py
# Outputs: basecamp_body_v3.step/.stl, basecamp_lid_v3.step/.stl
```

Running validate.py afterward is strongly recommended before sending to the printer:

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
| M3 bore through posts | 3.4mm (M3 thread-forming, no insert needed) |

If the lip binds after printing: sand the outer face of the lid lip with 400-grit, test fit, repeat. Do not sand the body seat.

---

## Assembly order

1. Mount Pi 4 on the four floor standoffs (M2.5 x 5mm). GPIO edge faces right (toward chimney), power/HDMI edge faces left.
2. Cable the Pi: right-angle USB-C adapter for power (exits through rear slot), ethernet through rear slot, any GPIO breakout through the Ø8 grommet in the chimney right wall.
3. Mount ESP32 nodes on their floor rails. USB-C service port aligns with the left wall slot.
4. Place the powered USB hub on edge in the right margin (max 85 x 30 x 15mm). Route hub power cable through rear slot.
5. Press SCD40 into the chimney card slot (foam wedge or Blu-Tack to hold it). Route wires through the grommet. Do this before flipping the box, or the SCD40 will fall out.
6. Mount SHT40 and SGP40 on the accessory boss grid (M2 self-tap, right side sensor zone floor).
7. Mount BH1750 under the lid light hole position (foam tape, align to Ø6mm hole).
8. Mount INMP441 behind the mic alignment recess (front face, left side). The 16 x 13mm recess locates it; foam tape to secure.
9. Flip box, drive 4x M3x50 pan-head from below. Torque to finger-tight plus a quarter turn. Stick Ø12mm adhesive rubber feet over the counterbores (4x, inboard of the posts).
10. Slide screen module forward until the front edge seats against the front pod wall (this is the alignment stop). Foam tape or VHB to the pod floor. Connect ribbon cable before inserting.
11. Set lid on body, check registration lip seats evenly all the way around.

SD card is accessible through the 8mm gap under the baffle without removing the lid.

---

## Sensor notes

**CO2 lag:** The SCD40 chimney equilibrates by diffusion plus passive stack effect. Expect 5-15 minutes of lag behind room CO2 changes. This is acceptable for overnight trend logging; the slow drift of room CO2 during sleep is the signal of interest, not step changes.

**Temperature offset:** The sensor zone will run approximately 0.5-1 degC above ambient due to ESP32 and general enclosure warmth. The offset is stable. Calibrate against a reference thermometer on the first night and record the offset. The adaptive threshold system absorbs a stable bias; what matters is consistency, not absolute accuracy.

**Radar and antenna membranes:** The front face uses 1mm PLA membranes over the HLK-LD2410C radar aperture (24 x 17mm) and the ESP32 antenna window (18 x 14mm). PLA at 1mm is effectively transparent at 2.4GHz and 24GHz. Do not remove the membranes to "improve signal" -- they protect the sensors and the open-hole aesthetics are worse.

---

## BOM additions (enclosure-specific)

| Item | Qty | Notes |
|------|-----|-------|
| M3 x 50mm pan-head black | 4 | Thread-forming into 3.4mm bore, no insert |
| Right-angle USB-C adapter | 1 | Required for Pi power, left wall clearance |
| Ø12mm adhesive rubber feet | 4 | Placed inboard of corner posts |
| VHB tape or foam tape | 1 sheet | Screen module and sensor mounting |
| Ø8mm cable grommet | 1 | Pre-installed in chimney right wall |
| Pi 4 heatsink | 1 | Compute zone ventilates through rear IO opening |

See `hardware/bom.md` for the full component BOM.

---

## Geometry reference

Key internal coordinates (X = width, Y = length, Z = up from floor):

| Feature | Position |
|---------|----------|
| Inner cavity | X +-45, Y +-65, Z 3-51 |
| Baffle (sensor/compute split) | Y -29 (front face), 8mm cable gap at floor |
| Pi PCB footprint | X -28..28, Y -20..65, ports flush with inner rear wall |
| Pi standoffs | (+-24.5, -18.5), (+-24.5, 39.5) |
| Rear IO cutout | 58mm wide, Z 8-27 |
| ESP32 rails | X -38..18, Y -57.5..-29.5 |
| USB-C service slot | left wall, Y -57.5, Z 5-14 |
| Chimney interior | X -45..-29, Y 30..65 |
| SCD40 card slot ribs | X -38..-33.8, Y 36..54 |
| Grommet | left chimney wall, Y 45, Z 13 |
| Corner posts | (+-40.7, +-61.35), Ø6.5, top Z 41 |
| Screen pod Y span | Y -22..36 (low edge front, faces bed) |
| BH1750 light hole | X -25, Y -45 (lid, Ø6mm) |
