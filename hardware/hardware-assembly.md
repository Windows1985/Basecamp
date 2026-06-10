# Enclosure Assembly Guide

Step-by-step guide for assembling all hardware into the Basecamp enclosure.
Follow after `hardware/assembly.md` (Pi OS setup and daemon verification) is complete.

**Prerequisites:**
- All five daemons verified working in breadboard configuration
- All sensors passing their verification tests from `hardware/assembly.md`
- Enclosure printed and in hand (body + lid)
- All BOM components present

**Tools needed:**
- JIS/Phillips screwdriver (M2.5)
- Flush cutters or scissors (cable management)
- Tweezers
- Multimeter (continuity check on cable crimps)
- Small file or sandpaper (if any print tolerances are tight)

**Time:** Allow 3–4 hours. Do not rush the wiring pass.

---

## 0. Print Inspection

Before starting, inspect the print for the following:

- [ ] Radar membrane (front face) is approximately 1mm thick — hold it to a light source and check for even translucency. If the membrane printed too thick (>1.5mm), sand from the inside with a fine file.
- [ ] Antenna window (front face, right side) is fully open — no layer bridging across the aperture
- [ ] USB service slot (left wall) is fully open and both USB-C port openings clear
- [ ] Screen pod cavity is accessible from below — ribbon slot (20×4mm) under pod is open
- [ ] All four corner post screw holes accessible
- [ ] SCD40 chimney cap is solid — no gaps or layer separation
- [ ] All vent slots fully open — run a toothpick through each

Sand any tight-tolerance features with 400-grit before proceeding. The ESP32 recess and screen pod are the most likely to need light cleanup.

---

## 1. Install Pi Standoffs

Insert four M2.5×5mm brass standoffs into the standoff bosses on the compute zone floor. These should press-fit; if loose, add a drop of super glue around the base.

Verify the standoff pattern matches the Pi 4 mounting holes: 58×49mm, 3.5mm from each edge. Place the Pi dry (no screws) and check all four holes align before proceeding.

---

## 2. Mount the Raspberry Pi

Lower the Pi into the compute zone with the USB/ethernet ports facing the rear wall of the enclosure. Align all four mounting holes over the standoffs.

Secure with four M2.5×4mm screws. Do not overtighten — brass standoffs strip easily. Finger-tight plus a quarter turn is sufficient.

**Verify:** USB-A ports and ethernet jack are aligned with the rear I/O cutout. If any port is obstructed, the Pi position may be off-centre — loosen, re-seat, re-tighten.

---

## 3. Mount the USB Hub

Place the powered USB hub in the rear of the compute zone, to the side of the Pi. The exact position depends on your hub's form factor. Route its power cable under itself toward the USB-C power entry slot on the rear wall.

If the hub has mounting holes, use M3 screws into the floor. Otherwise cable-tie it to the Pi standoff posts using two ties in a loop. It must not shift when USB cables are plugged or unplugged.

Connect the hub's upstream USB-A port to one of the Pi's USB-A ports now, before the space gets crowded.

---

## 4. Install the Integrated ESP32 (Node 1)

Node 1 sits in the sensor zone on the two rails parallel to the front face. The board lies flat, component-side up, with the antenna end (WROOM module side) toward the front face, aligned with the antenna window.

Lower the board onto the rails with the USB-C ports facing left, aligned with the USB service slot in the left wall. The board should sit flush on the rails with the WROOM module antenna centred behind the antenna window.

**Verify alignment:**
- Looking through the antenna window from the front, you should see the WROOM module's metal can directly behind it
- Looking at the left wall service slot, both USB-C port openings should be accessible from outside

Secure with two M2.5×6mm screws through the DevKit's mounting holes (if present) into the rail. If the board has no mounting holes, use a cable tie across the board through slots in the rails.

Connect a short USB-C cable (0.5m) from Node 1's USB port to the powered hub. Route under the baffle through the 5mm gap at the bottom.

---

## 5. Install I2C Sensors (Compute Zone)

The four I2C sensors (SHT40, BH1750, SCD40, SGP40) mount in the sensor zone on the opposite side of the baffle from the ESP32. All four share GPIO 2 (SDA) and GPIO 3 (SCL).

**SCD40 placement — critical:** Mount the SCD40 inside the chimney column (right wall side, isolated from the rest of the sensor zone). The chimney's low vents at Z=8mm and Z=12mm are the air intake; the high vents at Z=58mm and Z=62mm are exhaust. The sensor must be inside this column to measure room air, not Pi-heated air.

Mount the SCD40 on a small standoff (3mm) inside the chimney, with its measurement port facing up toward the cap. Use M2×4mm screws or double-sided thermal tape. Ensure the sensor body is not bridging the chimney wall — it must sit within the isolated column.

**BH1750 placement:** Mount facing up in the sensor zone, clear of the ESP32 board. It measures ambient light through the vent grille — position it below a vent slot.

**SHT40 and SGP40:** Mount on a small breakout board or breadboard section secured to the sensor zone floor. Keep both away from the SCD40 chimney (temperature gradient would affect SHT40) and away from the Pi (same reason).

Wire all four to the Pi GPIO header. The harness routes through the 5mm baffle gap. Leave slack — the lid needs to seat without tension on cables.

---

## 6. Install the Radar

The HLK-LD2410C mounts in the sensor zone with its sensing face toward the front wall. The radar works through the 1mm membrane — it does not need an open aperture.

Mount with double-sided tape or small brackets on the sensor zone floor, centred on the radar membrane (front face centre-right). The radar face should be flush against or within 3mm of the inner front wall.

Wire TX→GPIO 15, RX→GPIO 14, VCC→5V, GND→GND. Route the cable through the baffle gap to the Pi.

**Verify:** Run `python3 -c "import serial; s = serial.Serial('/dev/ttyAMA0', 256000, timeout=2); print(len(s.read(100)))"` — should return 100.

---

## 7. Install the Microphone

The INMP441 microphone mounts in the sensor zone with the port (small hole on the component side) aligned with the 2.5mm mic hole in the front face.

Use a small bracket or folded cardboard shim to position the mic at the exact height of the mic hole (Z=35mm). The port must be within 2mm of the inner face of the front wall. Secure with tape.

Wire BCK→GPIO 18, LRCK→GPIO 19, DIN→GPIO 20, L/R→GND. Route through baffle gap.

**Verify:** `arecord -D plughw:1 -c1 -r 16000 -f S32_LE -d 2 /tmp/test.wav && aplay /tmp/test.wav`

---

## 8. Screen Preparation

Before fitting the screen, attach the SPI ribbon cable (if not already attached) and test it on the bench:

```bash
python3 server/screen.py --demo
```

Confirm the IDLE layout displays correctly. If the screen is blank, fix it now — access is much harder after the lid is on.

Thread the ribbon cable through the ribbon slot (20×4mm slot under the screen pod) from above. Route it down through the sensor zone, through the baffle gap, and to the Pi GPIO header.

---

## 9. Seat the Lid

Before screwing the lid down:

1. Lay all cables flat — nothing should be pinched between the lid and body rim
2. Check the ribbon cable is not kinked at the baffle gap
3. Confirm the SCD40 chimney cap is not in contact with any cable

Lower the lid onto the body. The screen pod sits over the sensor zone. The corner posts should align with the lid screw holes — if the lid rocks, a corner post may have printed slightly tall; file it down.

Secure with four M2.5×8mm screws through the lid corners into the body posts. Snug, not tight.

Insert the screen module into the pod from the front face side. The PCB (86×50mm) slides into the pod cavity. The active display area should be visible through the screen window in the slanted face. Secure with two M2 screws through the PCB mounting holes into the pod, or with a thin bead of hot glue along the PCB edges.

---

## 10. External Connections

With the lid on:

**Rear face:**
- Ethernet: connect the 5m cable to the Pi ethernet port through the rear I/O cutout, route to the router or switch
- USB-C power: connect the Pi PSU through the rear USB-C slot
- Node 2 exit: route the 3–5m USB-C cable for the satellite node through the top-right exit slot, feed a grommet over it, seat the grommet in the groove

**Left wall service slot:**
- Leave accessible — this is used for Node 1 firmware provisioning

**Powered hub AC adapter:**
- Routes out the rear alongside the Pi PSU; use a cable clip or velcro to keep both tidy

---

## 11. Node 2 (Satellite)

Node 2 is external — it sits on the right-side ledge at mattress height. It is not enclosed.

Mount the bare ESP32-S3 DevKit on a small 3D-printed or cardboard bracket so it sits flat at mattress height with the antenna end facing the bed. The USB-C cable routes along the skirting board to the hub inside the enclosure.

No soldering or permanent mounting needed for Node 2 — it can be repositioned.

---

## 12. Final Checks

Power everything on. With the enclosure assembled:

```bash
# All five daemons healthy
sudo systemctl status basecamp-*

# Both CSI nodes streaming
timeout 10 python3 -c "
import socket, time
from collections import defaultdict
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', 5500))
s.settimeout(2)
src = defaultdict(int)
end = time.time() + 8
while time.time() < end:
    try:
        _, addr = s.recvfrom(4096)
        src[addr[0]] += 1
    except: pass
[print(f'{ip}: {n} packets') for ip, n in src.items()]
print(f'nodes active: {len(src)}')
"

# I2C sensors still responding
sudo i2cdetect -y 1

# Screen showing IDLE layout
# (verify visually)
```

Expected: 5 daemons active, 2 UDP source IPs, all 4 I2C addresses, screen showing time.

---

## 13. Cable Management

Before calling it done:

- Zip-tie the harness from the Pi GPIO header into a single bundle through the baffle gap
- Cable-tie the Node 1 USB cable under the baffle
- Ensure no cable is under tension — every cable should have at least 20mm of slack at its shortest point
- Check that the Pi's USB-A port retaining force doesn't move the hub when plugged/unplugged

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Screen blank after lid seated | Ribbon cable kinked at baffle gap | Open lid, re-route ribbon with a gentle S-bend through the gap |
| SCD40 reads like indoor air even with window open | Sensor outside chimney column | Check sensor is seated inside the chimney, not beside it |
| Radar reads 0 bytes | Cable snagged on lid seating | Open lid, check TX/RX continuity with multimeter |
| Only 1 CSI node visible | Node 1 USB cable not routed through baffle gap | Check under baffle — hub may have lost the connection |
| I2C addresses missing after assembly | Cable tension pulled a Dupont pin | Check harness at GPIO header and at sensor breakout |
| Screen shows correct layout but touch unresponsive | IRQ pin (GPIO 17) cable caught | Re-seat GPIO 17 connection |
