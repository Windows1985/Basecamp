# ADR-011: Enclosure Architecture

**Date:** 2026-06-11
**Status:** Accepted

---

## Context

The Basecamp enclosure needs to house a Raspberry Pi 4, two ESP32-S3 nodes, six environmental sensors, a 2.8" ILI9341 touchscreen, a powered USB hub, and all associated cabling in a bedside form factor. It must be printable on a standard FDM service, assembleable by one person without specialist tools, and presentable enough to be left on a bedside table indefinitely.

Several competing constraints shaped the design:

- No fan permitted: a fan introduces a constant noise floor directly beside the INMP441 microphone, corrupting the acoustic sensing channel.
- Screen must be readable from bed without the user sitting up.
- All sensors must measure room air, not enclosure-modified air, so thermal isolation from the Pi compute zone is required.
- The SCD40 CO2 sensor requires access to ambient air but cannot be left in an open cavity (RH condensation risk, and it needs a stable micro-environment).
- The Pi 4's USB/Ethernet ports must remain accessible for initial setup and SD card access in the field.
- The enclosure will be printed at a Taobao service in Hong Kong and must arrive print-ready.

---

## Options Considered

### Fastener style

**Option A: Top-entry M3 screws with visible heads.**
Simple to assemble, standard practice for project enclosures. Rejected: visible screw heads on the top face break the Apple aesthetic goal and create snagging points.

**Option B: Side-clip lid.**
No fasteners visible from any angle. Rejected: clips require tight dimensional tolerances that FDM printing does not reliably achieve, and the lid would flex and pop under lateral pressure from a cable catch.

**Option C: Bottom-entry M3x50 through hollow corner posts, heads hidden under adhesive feet.**
Chosen. Zero visible fasteners from any angle. The post geometry (Ø6.5, 41mm tall) is printable in-place, and the screw pattern (4x at ±40.7, ±61.35) gives a registration force that pulls the lid lip evenly into the body seat. M3x50 pan-heads sit flush in counterbores under the base; feet are placed inboard of the posts rather than over them.

### Screen orientation

**Option A: Screen facing away from bed (toward the room).**
Avoids light pollution during sleep. Rejected: requires the user to get up to read recovery scores, defeating the main UX goal of a score readable on waking.

**Option B: Screen facing the bed.**
Chosen, on the condition that the backlight is off during sleep. `screen.py` implements GPIO22 backlight control, keeping the display dark until the user taps to activate. With this in place there is no light-hygiene argument for facing the screen away. The pod low-edge sits at the front (bed side), tilting the display at 19 degrees toward the user.

### SCD40 housing

**Option A: Open hole in sensor zone wall.**
Simple. Rejected: condensation ingress risk and no physical protection for the fragile SCD40 carrier board.

**Option B: Fully sealed chimney box with lid fixed in place.**
Reviewed and found to be a build blocker: a fully sealed chimney makes the sensor uninstallable and provides no wire path to the Pi GPIO header.

**Option C: Chimney with open top (body walls stop below lid), lid-mounted plug cap (labyrinth seal), Ø8 grommet for wiring, and card-slot ribs for the SCD40 PCB.**
Chosen. The chimney occupies the left-rear dead zone beside the Pi (interior 14 x 33.5mm), using two body walls and two added walls. The lid plug drops 4mm into the chimney opening with 0.4mm clearance, forming a labyrinth seal that blocks bulk airflow while allowing the sensor to equilibrate. Low intake vents (z 8, 12) and high exhaust vents (z 40, 44) on the left wall drive passive stack-effect ventilation. The grommet routes SCD40 wiring directly to the Pi GPIO edge without entering the main cavity.

### Apertures for radar and ESP32 antenna

**Option A: Open windows.**
Maximises RF transparency. Rejected: open holes collect dust, break the front face aesthetics, and create a direct acoustic path into the mic cavity.

**Option B: 1mm PLA membrane.**
Chosen. PLA at 1mm is effectively RF-transparent at 2.4GHz and 24GHz (skin depth >> wall thickness). The front face has zero open holes except the 2.5mm mic port with its alignment recess. The radar pocket (24 x 17mm) and ESP32 antenna window (18 x 14mm) both sit behind flush membrane surfaces.

---

## Decision

96 x 136 x 54mm assembled body + lid, pod peak 79mm. Matte black FDM print, two-part body/lid split. Specific dimensions driven by:

- Width (96mm): 86mm ILI9341 screen module + 2.2mm pod wall each side + 2mm reveal.
- Length (136mm): 38mm sensor zone + 3mm baffle + 95mm compute zone (85mm Pi PCB + 4mm front gap + 3mm rear wall).
- Height (54mm): Pi 4 USB-A stack (25.4mm) + 5mm standoff + 3mm floor + headroom; hub stands on edge in the 17mm right margin beside the Pi.

Zero visible fasteners (bottom-entry M3x50). Screen pod faces bed at 19 degrees, activated by tap via GPIO22. SCD40 in left-rear chimney with labyrinth plug seal. All apertures behind 1mm membranes except the mic port. 1.8 x 2.5mm registration lip for a repeatable lid seam.

---

## Consequences

**Positive:**
- Passes boolean collision validation: lid-on-body intersection volume 0.0mm3; all component envelopes (Pi, ESP32, hub, SCD40, screen module) clear both parts.
- Both parts watertight (trimesh). Body prints support-free; lid prints top-face-up with supports under lip, bosses, and pod interior.
- 35% volume reduction vs the v2 concept (156cm3 vs 241cm3), lower print cost and mass.
- Screen readable from bed without sitting up.
- SCD40 serviceable by lifting lid; SD card reachable through the 8mm under-baffle gap.

**Constraints introduced:**
- Hub must be <=85 x 30 x 15mm to fit on edge in the right margin. Verify dimensions against Taobao listing before ordering.
- Right-angle USB-C adapter required for the Pi power input to avoid the cable fouling the left wall.
- Screen module assembly: slide module forward until it seats against the front wall stop, then foam-tape. Do not tape before positioning -- the pod is a sloped cavity and the module must seat on the slope, not hang in the air.
- 0.3-0.4mm clearances on lip and chimney plug assume a calibrated FDM printer. If the print service runs hot, the lip may bind; a light pass with 400-grit sandpaper on the mating face resolves this.
- Temp/humidity readings will show a stable warm bias of approximately +0.5 to +1 degC from ESP32 and general enclosure warmth. Calibrate against a reference on the first night; the adaptive threshold system absorbs a stable offset.

**Validated by:**
`hardware/enclosure/validate.py` -- boolean intersection tests for lid-vs-body and all component envelopes, run against the STEP exports. Re-run this after any geometry edit before sending to the print service.
