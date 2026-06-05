# Bill of materials

All components purchased from Taobao. Prices are approximate and may vary by seller.

| Component | Spec | Qty | Cost (RMB) |
|-----------|------|-----|------------|
| ESP32-S3-DevKitC-1 | N16R8 — 16MB flash, 8MB PSRAM | 2 | ~50 |
| Raspberry Pi 4 Model B | 4GB RAM | 1 | ~1000 |
| SanDisk MicroSD | 32GB Class 10 | 1 | ~25 |
| Pi power supply | Official 5V/3A USB-C | 1 | ~30 |
| INMP441 | I2S digital microphone | 1 | ~10 |
| HLK-LD2410C | 24GHz mmWave radar | 1 | ~25 |
| SHT40 | Temperature and humidity, I2C | 1 | ~15 |
| BH1750 | Light sensor, I2C | 1 | ~8 |
| SCD40 | CO2 sensor — verify genuineness before use (see notes) | 1 | ~30 |
| SGP40 | VOC sensor, I2C | 1 | ~25 |
| 2.8 inch IPS SPI touchscreen | ILI9341 or ST7789 driver | 1 | ~30 |
| Powered 4-port USB hub | With AC adapter | 1 | ~25 |
| Ethernet cable 5m | Pi to router | 1 | ~10 |
| 830-point breadboard | For prototype assembly | 1 | ~8 |
| Jumper wires | M-F, F-F, M-M sets | 1 set | ~10 |
| USB-C cable 0.5m | ESP32 to hub, x2 | 2 | ~12 |
| USB-C cable 3-5m | Long run to right bedroom node | 1 | ~15 |
| M2.5 standoffs and screws | Pi mounting inside enclosure | 1 set | ~8 |
| 3D printed enclosure | Matte black PLA, 150x100x70mm | 1 | ~60 |
| Cable grommets | Clean cable entry points | 1 set | ~5 |

## Total

Approximately 1400 RMB depending on sellers and shipping.

## Notes

The SCD40 is the only component where clones are a significant problem. Fake chips produce plausible-looking but inaccurate CO2 readings, which would corrupt the environmental layer of the recovery score. To verify genuineness, check the following before use.

The genuine Sensirion SCD40 has the Sensirion logo and the text SCD40 printed clearly on the chip itself. The chip is a small square package soldered onto the breakout board. If the chip markings are absent, smudged, or show a different manufacturer name, it is likely a clone. A second verification method is to run the sensor outdoors for twenty minutes and check whether the reading converges on approximately 400 to 420 ppm, which is the current atmospheric CO2 concentration. A genuine sensor will stabilise in this range. A clone will typically read too high, too low, or fail to stabilise at all.

If the sensor turns out to be a clone, a genuine replacement costs approximately 75 to 80 RMB from a reputable seller and is worth the price given how central the CO2 data is to the environmental scoring layer.

All four environmental sensors (SHT40, BH1750, SCD40, SGP40) share a single I2C bus, which simplifies wiring considerably. Buy all sensors as breakout boards with pre-soldered headers to avoid soldering during the prototype phase.

The 3D printed enclosure can be ordered as a print service on Taobao by uploading the STL file from the /hardware/enclosure folder. Request 0.12mm layer height and matte black PLA for the best finish.

The Raspberry Pi 4 is significantly more expensive in China than its official retail price due to import costs and reseller markup. This is expected and unavoidable when buying from Taobao.
