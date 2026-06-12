# ADR-012: Enclosure v4 - Magnetic Lid, Hub Deletion, and Hotspot Networking

**Date:** 2026-06-12
**Status:** Accepted

---

## Context

The v3 enclosure used four M3x50 screws to close the lid, a powered USB hub to supply the ESP32 nodes, and a home router with a legacy 2.4GHz SSID to provide the WiFi network the nodes need for CSI. Three problems emerged during planning for the HK/Shenzhen data-collection sprint:

- The sprint requires dozens of lid removals to service sensors and swap SD cards. Four screws and a screwdriver for every removal is impractical at that frequency.
- The powered hub added 10mm to the body height, requires a second wall outlet, and is a single-point failure in a system that already has many power rails.
- The ASUS WiFi 7 router SSID configuration is location-specific, meaning the CSI RF environment changes between HK, Shenzhen, and Cate, making session-to-session baselines incomparable.

---

## Options Considered

### Decision 1: Lid fastener method

**Option A: Four M3x50 screws (existing v3 design).**
Reliable and proven. Rejected for daily use: requires a screwdriver for every access during the sprint. Dozens of lid removals is the expected workload, not an edge case.

**Option B: Snap clips.**
Tool-free. Rejected: FDM snap clips require tight dimensional tolerances that service bureaux do not reliably achieve; clips flex and pop under lateral stress from cable catches.

**Option C: Magnetic lid with travel screws.**
Chosen. Six N35 magnet pairs (2 front, 2 rear, 2 mid-side) hold the lid for daily access; the registration lip still aligns the parts precisely. Two M3x45 travel screws thread through the rear posts and are installed only for the three relocations (HK to Shenzhen to Cate). This separates the daily-access mechanism from the transport-locking mechanism. Body height drops 51->46mm as a side effect of deleting the hub (which was the height driver); screws shorten from 50mm to 45mm.

**Consequences of Option C:**
- Six N35 magnet pairs required (buy 20-pack for spares; polarity must be verified before gluing).
- Front corner posts deleted (also resolves ESP32 corner clearance constraint from v3).
- Two M3x45 travel screws retained, stored in the enclosure bag when not in use.
- Lid polarity error is non-recoverable without drilling; the assembly procedure requires a dry-stack polarity check before any glue is applied.

---

### Decision 2: ESP32 power source

**Option A: Powered USB hub (existing v3 design).**
Dedicated 5V supply for the nodes; handles any current transients independently. Rejected: adds 10mm to body height, requires a second wall plug, and introduces an additional failure point.

**Option B: Pi USB-A ports (direct).**
Chosen. Both nodes draw from the Pi's own USB-A ports. Combined peak is approximately 0.8A (two ESP32-S3 at WiFi TX burst), within the Pi 4's 1.2A USB budget. The official 5V/3A PSU covers total system draw (Pi ~600mA + nodes ~800mA peak = 1.4A, well within 3A).

Node 1 uses a short 25cm USB-A-to-C cable routed to the rear Pi USB-A. Node 2's 5m cable must be 20AWG or thicker; thinner wire (e.g. 28AWG) causes voltage drop at ESP32-S3 WiFi TX bursts that triggers brownout resets. 20AWG is a hard requirement, not a preference. Verify the listing specifies wire gauge before ordering.

**Consequences of Option B:**
- Hub deleted from BOM (saves approximately Y30, one wall plug, and 10mm height).
- Both rear cable slots deleted from enclosure; Node 2's 5m cable exits through the IO cutout alongside ethernet.
- A startup check in the sensor daemon logs a warning if `vcgencmd get_throttled` reports undervoltage, since both nodes now share the Pi's supply.
- NODE2_USB_POWER = True documents this configuration in config.py.

---

### Decision 3: WiFi networking architecture

**Option A: Router-dependent (existing v3 design).**
Pi connects to a dedicated 2.4GHz legacy SSID on the ASUS router. Works at home. Rejected as primary path: the SSID configuration is specific to the ASUS router and must be recreated at each location. Different routers mean different RF environments, so CSI baselines collected in HK cannot be compared to baselines collected at Cate without retraining. The ASUS WiFi 7 router also requires non-default settings (N-only, 20MHz, MU-MIMO off) that are not available on school network infrastructure.

**Option B: Pi hotspot as canonical setup.**
Chosen. wlan0 runs as an isolated access point for the ESP32 nodes only (fixed channel, 20MHz bandwidth, hidden or not per config). The WiFi network exists solely because CSI is a property of a WiFi link; no general internet traffic traverses it. eth0 is a DHCP client for internet, NTP, and dashboard access. Phone reaches the dashboard over the LAN via ethernet (home or Cate ethernet), or by joining the Pi hotspot when no ethernet is available.

This architecture produces an identical RF environment at every location: same Pi radio, same SSID, same channel, same two node MAC addresses. CSI baselines transfer between locations without retraining. It also eliminates the ASUS router configuration burden entirely.

**One-radio constraint:** The Pi 4 has a single combo radio chip (wlan0). It can operate as an AP or a station, not simultaneously both. Internet access requires eth0. The hotspot setup documented in pi_setup.sh configures NAT from wlan0 to eth0 to give the nodes internet access if needed (not required for CSI operation).

**NTP and timekeeping:** An offline Pi (no eth0) loses time on power cycles because the Pi 4 has no battery-backed real-time clock. Corrupted timestamps break session attribution and the morning pipeline. The DS3231 RTC module (I2C address 0x68, ~Y10) is added to the BOM and enabled via `dtoverlay=i2c-rtc,ds3231` in config.txt. fake-hwclock must be disabled; the DS3231 provides hardware-backed time that survives offline power cycles. This is a hard dependency of the hotspot-everywhere architecture.

**Consequences of Option B:**
- pi_setup.sh becomes the canonical setup script (merges former pi_setup_hotspot.sh). Router-mode instructions retained in a deprecated appendix.
- DS3231 RTC added to BOM and I2C bus (address 0x68; add to expected i2cdetect list).
- timedatectl check added to bring-up procedure to confirm the RTC is providing time offline.

---

### Bluetooth note

BT PAN was considered as an alternative phone-sync path and rejected. The Pi's Bluetooth radio shares the 2.4GHz band and the same combo chip as the CSI-serving AP. BT activity injects interference into the measured WiFi channel and time-slices the radio between AP and BT roles, both of which corrupt CSI readings. Bluetooth is disabled via `dtoverlay=disable-bt` in config.txt.

Optional future experiment: `rfkill block bluetooth` during measurement windows to verify the interference contribution without a permanent hardware change.

---

## Consequences

**Positive:**
- Body height 51mm -> 46mm (assembled 49mm, pod peak 74mm); smaller print, lower cost (~Y40).
- Tool-free daily lid access during the data-collection sprint.
- Identical RF environment across all deployment locations; CSI baselines transfer.
- One fewer wall plug; one fewer potential failure point.
- Offline timekeeping via DS3231 eliminates corrupted session timestamps.

**Constraints introduced:**
- Node 2 cable must be 20AWG or thicker; verify the listing before ordering.
- Magnet polarity must be checked before gluing; reversal is non-recoverable without drilling.
- Travel screws (2x M3x45) required before any relocation; keep them in the enclosure bag.
- DS3231 RTC required for correct offline operation; fake-hwclock must be disabled.
- Phone internet access requires eth0 or joining the Pi hotspot (no transparent bridging to the wider LAN via wlan0).
