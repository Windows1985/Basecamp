# Bill of materials

All components purchased from Taobao. Prices are approximate and may vary by seller.

| Component | Spec | Qty | Cost (RMB) |
|-----------|------|-----|------------|
| ESP32-S3-DevKitC-1 | N16R8 -- 16MB flash, 8MB PSRAM | 2 | ~50 |
| Raspberry Pi 4 Model B | 4GB RAM | 1 | ~1000 |
| SanDisk MicroSD | 32GB Class 10 | 1 | ~25 |
| Pi power supply | Official 5V/3A USB-C | 1 | ~30 |
| INMP441 | I2S digital microphone | 1 | ~10 |
| HLK-LD2410C | 24GHz mmWave radar | 1 | ~25 |
| SHT40 | Temperature and humidity, I2C | 1 | ~15 |
| BH1750 | Light sensor, I2C, countersink mount | 1 | ~8 |
| SCD40 | CO2 sensor -- verify genuineness before use (see notes) | 1 | ~30 |
| SGP40 | VOC sensor, I2C | 1 | ~25 |
| 2.8 inch IPS SPI touchscreen | ILI9341 or ST7789 driver | 1 | ~30 |
| DS3231 RTC module | I2C real-time clock with CR2032 battery | 1 | ~10 |
| RGB LED + resistors | Recovery glow indicator (O3 lid hole) | 1 | ~2 |
| Ethernet cable 5m | Pi to router / switch | 1 | ~10 |
| 830-point breadboard | For prototype assembly | 1 | ~8 |
| Jumper wires | M-F, F-F, M-M sets | 1 set | ~10 |
| USB-A-to-C cable 25cm | Node 1 internal (Pi USB-A to Node 1) | 1 | ~5 |
| USB-A-to-C cable 5m 20AWG | Node 2 long run -- 20AWG wire gauge is a hard requirement; verify the listing specifies wire gauge, not just length | 1 | ~20 |
| Right-angle USB-C adapter | Pi power, exits through left wall slot | 1 | ~8 |
| M3 x 45mm pan-head black | Travel screws through rear posts -- install only before transport | 2 | ~5 |
| O6 x 3mm N35 disc magnets | Lid magnets -- buy 20-pack for spares; 12 used (6 pairs) | 20 | ~8 |
| O12mm adhesive rubber feet | Placed at four corners inboard | 4 | ~3 |
| VHB tape or foam tape | Screen module anti-rattle and sensor mounting | 1 sheet | ~5 |
| O8mm cable grommet | Pre-installed in chimney right wall | 1 | ~3 |
| M2.5 standoffs and screws | Pi mounting inside enclosure | 1 set | ~8 |
| Pi 4 heatsink | Compute zone ventilates through rear IO opening | 1 | ~8 |
| 3D printed enclosure v4 | Matte black PLA, 96 x 136 x 49mm assembled | 1 | ~40 |

## Total

Approximately 1410 RMB depending on sellers and shipping.

## Notes

The SCD40 is the only component where clones are a significant problem. Fake chips produce plausible-looking but inaccurate CO2 readings, which would corrupt the environmental layer of the recovery score. To verify genuineness, check the following before use.

The genuine Sensirion SCD40 has the Sensirion logo and the text SCD40 printed clearly on the chip itself. The chip is a small square package soldered onto the breakout board. If the chip markings are absent, smudged, or show a different manufacturer name, it is likely a clone. A second verification method is to run the sensor outdoors for twenty minutes and check whether the reading converges on approximately 400 to 420 ppm, which is the current atmospheric CO2 concentration. A genuine sensor will stabilise in this range. A clone will typically read too high, too low, or fail to stabilise at all.

If the sensor turns out to be a clone, a genuine replacement costs approximately 75 to 80 RMB from a reputable seller and is worth the price given how central the CO2 data is to the environmental scoring layer.

All four environmental sensors (SHT40, BH1750, SCD40, SGP40) and the DS3231 RTC share a single I2C bus, which simplifies wiring considerably. Buy all sensors as breakout boards with pre-soldered headers to avoid soldering during the prototype phase.

**Node 2 cable gauge:** The 5m USB-A-to-C cable for Node 2 must be 20AWG wire or thicker. Thin cables (28AWG is common for cheap listings) cause voltage drop during ESP32-S3 WiFi TX bursts, triggering brownout resets. Verify the listing specifies wire gauge, not just cable length.

The 3D printed enclosure can be ordered as a print service on Taobao by uploading the STL files from the hardware/enclosure folder. Request 0.2mm layer height and matte black PLA. v4 is slightly smaller than v3; expect approximately Y40.
