# ADR-011: Enclosure Design Decisions

**Date:** 2026-06-10
**Status:** Accepted

## Context

The enclosure was designed parametrically using CadQuery before hardware arrived, based on verified component dimensions. Three decisions deviated from the original spec during modelling.

## Decision 1: Compute zone depth is 101mm, not 60mm

The original spec stated a 40mm sensor zone + 60mm compute zone = 100mm internal length. This does not sum to the 144mm internal length of a 150mm outer box with 3mm walls. Additionally, the Pi 4 (85mm long) plus rear connector clearance (ethernet plug boot ~25mm) requires at least 95mm. The compute zone is derived as whatever remains after the sensor zone and baffle: approximately 101mm.

**Alternative considered:** Shrinking outer_L to ~110mm. Rejected — insufficient rear cable bend radius and USB hub has no home.

## Decision 2: Chimney relocated to right wall, self-capped

The original spec placed the SCD40 chimney venting through the lid. The screen pod (92mm wide, covering most of the lid) occupies the space above the sensor zone. The chimney was moved to the right wall with low intake and high exhaust slots, and given a solid cap at 66mm to prevent pod cavity air from bypassing the isolation. Convection path is functionally equivalent.

**Alternative considered:** Reducing pod width to preserve lid chimney. Rejected — pod must accommodate the full 86x50mm PCB, not just the 57.6x43.2mm active area.

## Decision 3: Screen pod sized to full PCB (86x50mm), not active area

The ILI9341 2.8" module PCB is 86x50x14.3mm (verified from datasheets). The original pod (66mm wide) was sized to the active display area only and would not have fit the module. Pod inner width is 87.6mm (1.6mm clearance).

## Decision 4: ESP32 node integrated with antenna window and USB service slot

Node 1 is integrated into the enclosure. The front face has an 18x12mm open antenna window aligned with the WROOM module's antenna end, placing no plastic in the CSI radiation path toward the bed. The left wall has a 22x9mm service slot aligned with the board's two USB-C ports, allowing flashing and provisioning without disassembly. Node 2 remains a satellite.

## Decision 5: Radar hidden behind 1mm membrane

The LD2410C radar is concealed behind a 1mm plastic membrane (inner pocket cut from 3mm wall). 24GHz signals penetrate thin PLA with negligible attenuation — this is standard practice for commercial mmWave products. Benefit: clean blank front face consistent with Apple-style design intent.

## Consequences

- `hardware/enclosure/enclosure_v2.py` is the canonical parametric source; edit variables and re-run to regenerate STEP files
- All aperture positions are derived from component dimensions verified against datasheets, not estimates
- Standoff positions match Pi 4 mounting hole pattern exactly (58x49mm, 3.5mm from edges)
- Rear I/O cutout raised to z=27mm to clear USB-A stack height above PCB
- If antenna window position needs adjustment (clone DevKit boards vary ±1-2mm), change `ANT_WIN_CX` in the script and reprint
