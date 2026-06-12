# Sensor Notes

Calibration quirks, known offsets, and environmental effects for the Basecamp sensor suite.

---

## CO2 lag (SCD40)

The SCD40 chimney equilibrates by diffusion plus passive stack effect. Expect 5-15 minutes of lag behind room CO2 changes. This is acceptable for overnight trend logging; the slow drift of room CO2 during sleep is the signal of interest, not step changes.

The chimney uses low intake vents (base-level floor slots) and exhausts through the rear wall. The labyrinth-seal plug on the lid side blocks bulk airflow while allowing the sensor to equilibrate over the measurement timescale. Do not enlarge the chimney vents to speed up equilibration -- this would also increase RH variation and condensation risk for the fragile SCD40 PCB.

---

## Temperature offset calibration (SHT40)

The sensor zone runs approximately 0.5-1 degC above ambient due to ESP32 and general enclosure warmth. The offset is stable because the v4 ventilation architecture guarantees air flows room->sensor->compute->out, never compute->sensor (see Ventilation section below). The sensor-zone readings are upstream of the Pi heat source; only the two ESP32 nodes contribute warmth to the sensor zone.

Calibrate against a reference thermometer on the first night and record the offset in `server/config.py` as `TEMP_OFFSET_C`. The adaptive threshold system absorbs a stable bias; what matters is consistency, not absolute accuracy.

---

## SGP40 burn-in

The SGP40 VOC sensor requires approximately 24 hours of continuous operation before readings stabilise. The sensor runs a conditioning algorithm during this period. Do not log or act on VOC index values until the burn-in completes. The sensor logger marks readings as `pre_burnin = True` for the first 24 hours after first power-on.

---

## Screen rotation

The 2.8" ILI9341 display is mounted in the screen pod with the cable at the bottom. The pod tilts 19 degrees toward the bed. `SCREEN_ROTATION = 90` in `server/config.py` compensates for the physical rotation of the PCB within the pod. Change this constant (valid values: 0, 90, 180, 270) if the display orientation is incorrect after assembly; do not edit the rendering code directly.

---

## Air purifier interference

If a HEPA air purifier runs in the room, it will reduce CO2 variation (the purifier recirculates air but does not change CO2 levels -- this is fine) and may introduce acoustic noise in the 60-500 Hz band that overlaps with snore detection. If the purifier is running, check the snore detection threshold; you may need to raise `SNORE_THRESHOLD` in `server/config.py` to avoid false positives.

---

## Ventilation (v4 architecture)

v4 moved ventilation intake from the side walls to the base, and chimney exhaust from the top to the rear wall. The resulting airflow path is:

```
room air -> base intake slots -> sensor zone -> under-baffle gap -> compute zone -> rear IO opening
```

Pi warmth drives this flow via natural convection: the Pi heats the compute zone, which draws cooler air from the sensor zone, which draws fresh room air through the base intakes. The direction is guaranteed because the Pi (the largest heat source) sits at the downstream end of the path.

**What this means for sensor readings:**

- Temperature and humidity readings from SHT40 represent upstream (pre-Pi) room air. They are not contaminated by Pi heat.
- CO2 readings from the SCD40 chimney also sample upstream air; the chimney has its own dedicated base floor slot.
- VOC readings from SGP40 may capture a small contribution from ESP32 node outgassing, but this is a stable bias that calibrates out.

Left and right walls are blank in v4 (left wall has only the ESP32 USB service slot and the Pi power slot; right wall is blank). This eliminates side-wall cross-drafts that could disrupt the vertical convection path.

---

## DS3231 RTC and timestamps

The Pi 4 has no battery-backed real-time clock. Without the DS3231, an offline Pi loses time on every power cycle. Corrupted timestamps break session attribution (the morning pipeline uses bed-exit time to identify which overnight session to process) and make multi-night trend analysis unreliable.

The DS3231 provides hardware-backed time that survives offline power cycles. It is enabled by `dtoverlay=i2c-rtc,ds3231` in `/boot/config.txt` and sits on I2C address 0x68.

**fake-hwclock must be disabled.** The fake-hwclock service saves the system clock to a file on shutdown and restores it on boot, but it will overwrite the DS3231 time if both are active. Disable it:

```bash
sudo systemctl disable fake-hwclock
sudo systemctl stop fake-hwclock
```

After disabling fake-hwclock, verify the RTC is providing correct time after an offline reboot:

```bash
sudo hwclock -r       # read RTC time directly
timedatectl           # confirm system clock matches
```

If the RTC time drifts more than a few minutes per week, the CR2032 battery may be low. Replace it; the DS3231 draws microamps from the battery and a CR2032 should last several years.

---

## Radar and antenna membranes

The front face uses 1mm PLA membranes over the HLK-LD2410C radar aperture (24 x 17mm) and the ESP32 antenna window (18 x 14mm). PLA at 1mm is effectively transparent at 2.4GHz and 24GHz. Do not remove the membranes to "improve signal" -- they protect the sensors and the open-hole aesthetics are worse.

---

## INMP441 mic funnel

The v4 enclosure adds a O6->O2.5 waveguide in the front wall behind the INMP441 mounting position. The funnel maintains acoustic directionality toward the bed while reducing susceptibility to near-field noise from the enclosure interior. Mount the INMP441 flush against the funnel opening; foam tape secures the rear face.
