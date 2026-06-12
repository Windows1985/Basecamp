# Hardware Assembly and Bring-Up

Step-by-step guide for assembling and verifying Basecamp from components to first overnight run.

**Time required:** Allow a full day for first assembly. Most steps have a verification command -- do not skip them.

---

## 0. Pre-Assembly Checklist

### Components
Verify all BOM items are present before starting.

- [ ] Raspberry Pi 4 Model B 4GB
- [ ] SanDisk 32GB MicroSD card
- [ ] Official Pi USB-C power supply (5V/3A)
- [ ] Right-angle USB-C adapter
- [ ] ESP32-S3-DevKitC-1 N16R8 x 2
- [ ] INMP441 I2S microphone
- [ ] HLK-LD2410C mmWave radar
- [ ] SHT40 temperature/humidity sensor
- [ ] BH1750 light sensor
- [ ] SCD40 CO2 sensor -- verify genuine Sensirion logo printed on chip before proceeding
- [ ] SGP40 VOC sensor
- [ ] DS3231 RTC module with CR2032 battery installed
- [ ] RGB LED + resistors
- [ ] 2.8" IPS SPI touchscreen (ILI9341 or ST7789 driver)
- [ ] USB-A-to-C cable 25cm (Node 1 internal)
- [ ] USB-A-to-C cable 5m 20AWG (Node 2 long run) -- verify listing states wire gauge
- [ ] Ethernet cable 5m
- [ ] 12x O6x3 N35 disc magnets (plus spares from 20-pack)
- [ ] 2x M3x45 pan-head screws (travel screws)
- [ ] O12mm adhesive rubber feet x4
- [ ] VHB tape / foam tape
- [ ] Breadboard + jumper wires (M-F, F-F, M-M)
- [ ] M2.5 standoffs and screws
- [ ] 3D printed enclosure v4 (if ordered -- see note below)

> **Enclosure note:** Print time plus shipping is 5-7 days. If the enclosure has not arrived, proceed with the breadboard. All verification steps work without the enclosure.

### Tools
- MicroSD card reader
- Computer with Raspberry Pi Imager installed
- A second device (phone or laptop) to access the Pi web interface
- Multimeter (optional but useful for continuity checks)

---

## 1. Flash the MicroSD Card

On your computer:

1. Download and open [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Choose OS -> **Raspberry Pi OS Lite (64-bit)** -- no desktop needed
3. Choose storage -> your SanDisk 32GB card
4. Click the gear icon and configure:
   - Set hostname: `basecamp`
   - Enable SSH with password authentication
   - Set username: `pi`, password: your choice
5. Write to card

Insert the card into the Pi. Connect ethernet to your router or switch. Connect power via the right-angle USB-C adapter through the left wall slot.

Wait 60 seconds for first boot, then find the Pi's IP address from your router's admin page, or:

```bash
# From another machine on the same network
ping basecamp.local
```

SSH in:

```bash
ssh pi@basecamp.local
```

**Magnet assembly (if enclosure has arrived):** Before mounting any electronics, install and glue the lid magnets.

1. Dry-stack all 12 magnets into their body and lid pockets without glue.
2. Close the lid and verify it seats and releases cleanly at all six points.
3. Open the lid carefully. Mark the outward-facing face of each magnet with a permanent marker before removing them.
4. Glue body-side magnets mark-up (recessed 0.8mm into wall-boss pocket), lid-side magnets mark-down (proud 0.8mm from lid underside). Use CA glue or epoxy. Hold 30 seconds per magnet.
5. Allow full cure before closing the lid again.

---

## 2. Run the Setup Script

```bash
# Clone the repo
git clone https://github.com/Windows1985/Basecamp.git /home/pi/basecamp
cd /home/pi/basecamp

# Run setup (takes 10-15 minutes)
sudo bash pi_setup.sh
```

The script configures wlan0 as an isolated AP for the ESP32 nodes, sets eth0 as a DHCP client for internet and NTP, enables the DS3231 RTC overlay, installs all Python dependencies, configures UART for the radar, enables I2C/SPI, and installs systemd services.

Pi power enters through the left wall slot via the right-angle USB-C adapter -- no internal routing needed.

Reboot after the script completes:

```bash
sudo reboot
```

---

## 3. Configure ntfy

The morning report and crash notifications are sent via ntfy. Set up before the first overnight run.

1. Install the [ntfy app](https://ntfy.sh) on your phone
2. Subscribe to a topic name of your choice (e.g., `basecamp-ethan-2024`) -- keep it unguessable
3. Edit the config on the Pi:

```bash
nano /home/pi/basecamp/server/config.py
```

Set `NTFY_TOPIC` to your chosen topic name. Save and close.

Test the notification:

```bash
curl -d "Basecamp test notification" ntfy.sh/YOUR_TOPIC_NAME
```

You should receive a notification on your phone within a few seconds.

---

## 4. Node power verification

Both ESP32 nodes draw power directly from the Pi's rear USB-A ports.

- Node 1: 25cm USB-A-to-C cable from rear Pi USB-A port, routed internally.
- Node 2: 5m 20AWG USB-A-to-C cable from the other rear Pi USB-A port, exiting through the IO cutout.

Before powering the nodes, verify the Node 2 cable gauge:

```bash
# Measure voltage at the Node 2 connector end while the node is running
# Should read >= 4.75V under WiFi TX load; if below 4.6V the cable is too thin
```

If voltage sags below 4.6V under load, the cable is not 20AWG -- replace it before proceeding.

---

## 5. Verify I2C Sensors and RTC

Wire all I2C devices to the Pi before this step. All share GPIO 2 (SDA) and GPIO 3 (SCL). See `hardware/wiring.md` for full pin reference.

| Device | I2C Address |
|--------|-------------|
| BH1750 | 0x23 |
| SHT40 | 0x44 |
| SGP40 | 0x59 |
| SCD40 | 0x62 |
| DS3231 RTC | 0x68 |

```bash
sudo i2cdetect -y 1
```

Expected output shows all five addresses populated. Example:

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:          -- -- -- -- -- -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- 23 -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- 44 -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- 59 -- -- -- -- -- --
60: -- -- 62 -- -- -- -- -- 68 -- -- -- -- -- -- --
```

If an address is missing, check the wiring for that device. SDA/SCL reversed and insufficient 3.3V power are the most common causes.

**SGP40 burn-in:** SGP40 requires 24 hours of continuous operation before VOC readings stabilise. Leave the Pi running after this step and do not trust VOC output until the following day.

---

## 6. Verify RTC timekeeping

After the DS3231 is detected on the I2C bus, verify the RTC is providing time:

```bash
# Write current time to the RTC
sudo hwclock -w

# Check timedatectl shows RTC time
timedatectl

# Simulate offline power cycle: disconnect ethernet, reboot, check time is correct
sudo reboot
```

After rebooting without ethernet, run:

```bash
timedatectl
# "RTC time" should match wall clock within a few seconds
# "System clock synchronized: no" is expected when offline -- that is correct
```

If the time is wrong by hours or days after an offline reboot, fake-hwclock may still be active. Disable it:

```bash
sudo systemctl disable fake-hwclock
sudo systemctl stop fake-hwclock
sudo update-rc.d fake-hwclock disable
```

---

## 7. Calibrate the SCD40

Take the Pi outdoors (or near an open window) for this step. Outdoor CO2 is approximately 420ppm -- this is the calibration reference.

```bash
cd /home/pi/basecamp
python3 server/calibrate_scd40.py
```

The script runs for approximately 3 minutes and prints readings. Expected output: 400-450ppm.

If readings are consistently outside 380-480ppm, the chip is likely a clone. Replace it before proceeding.

---

## 8. Verify the Radar

The HLK-LD2410C requires **5V power** (not 3.3V) and the Pi's hardware UART. Verify `dtoverlay=disable-bt` is present in `/boot/config.txt` (pi_setup.sh adds this automatically).

Wire the radar TX->GPIO 15 (Pi RXD), RX->GPIO 14 (Pi TXD), VCC->5V pin, GND->GND.

```bash
python3 -c "
import serial, time
s = serial.Serial('/dev/ttyAMA0', 256000, timeout=2)
time.sleep(0.5)
data = s.read(100)
print(f'Read {len(data)} bytes: {data.hex()}')
s.close()
"
```

Expected: reads 100 bytes of radar output. If `len(data)` is 0, check TX/RX are not swapped.

---

## 9. Verify the Microphone

Wire INMP441 to GPIO 18 (BCK), 19 (LRCK), 20 (DIN). See `hardware/wiring.md` for full pinout including L/R select.

```bash
# Record 3 seconds of audio
arecord -D plughw:1 -c1 -r 16000 -f S32_LE -d 3 /tmp/test.wav
# Play it back
aplay /tmp/test.wav
```

---

## 10. Verify the Touchscreen

Wire the ILI9341 touchscreen to the SPI pins. See `hardware/wiring.md` for full pinout.

```bash
cd /home/pi/basecamp
python3 server/screen.py --test
```

Expected: the screen displays the IDLE layout (time, no score).

---

## 11. Flash and Verify ESP32 Node 1

Follow the instructions in `firmware/README.md` to flash the ESP32-CSI-Tool firmware.

Key configuration before flashing:
- Target SSID: `Basecamp-Node` (the Pi's own hotspot)
- UDP target IP: `192.168.4.1` (the Pi's AP address)
- UDP target port: `5500` (default in `server/config.py`)

On the Pi, verify the CSI stream is arriving:

```bash
cd /home/pi/basecamp
timeout 10 python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', 5500))
s.settimeout(2)
count = 0
while True:
    try:
        data, addr = s.recvfrom(4096)
        count += 1
        print(f'Packet {count}: {len(data)} bytes from {addr}')
        if count >= 5:
            break
    except socket.timeout:
        print('Timeout -- no packets received')
        break
"
```

Expected: 5 packets received within 10 seconds. If no packets arrive, verify the ESP32 is connected to `Basecamp-Node` (check `hostapd` logs for association events).

---

## 12. First Overnight Run (Single Node)

Start all services:

```bash
sudo systemctl start basecamp-logger basecamp-presence basecamp-audio basecamp-csi basecamp-screen
```

Verify all are running:

```bash
sudo systemctl status basecamp-*
```

**Final assembly (if enclosure has arrived):**

1. Close lid by lowering it onto the body. Listen for the magnetic click at all six points -- front two, rear two, mid-side two.
2. Travel screws are NOT installed unless transporting.
3. Rubber feet go at the four corners inboard; counterbores are at the two rear posts only.

---

## 13. Flash and Add ESP32 Node 2

Once the first overnight run completes without errors, flash Node 2 with the same firmware configuration as Node 1.

Place Node 2 on the right ledge, antenna end facing the bed, at mattress height. Route the 5m 20AWG USB-A-to-C cable to the rear Pi USB-A port through the IO cutout.

Verify both nodes are streaming simultaneously:

```bash
cd /home/pi/basecamp
timeout 15 python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', 5500))
s.settimeout(2)
from collections import defaultdict
sources = defaultdict(int)
import time; end = time.time() + 10
while time.time() < end:
    try:
        data, addr = s.recvfrom(4096)
        sources[addr[0]] += 1
    except socket.timeout:
        pass
for ip, count in sources.items():
    print(f'{ip}: {count} packets')
"
```

Expected: two source IPs, each with a similar packet count.

---

## 14. Submit First Morning Log

After the second overnight run completes, open the morning log via the touchscreen or the web interface:

```
http://basecamp.local:5000
```

Submit Recovery, Energy, Clarity, and Mood scores (1-10 each).

---

## Known First-Boot Issues

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `i2cdetect` shows no addresses | I2C not enabled | Verify `dtparam=i2c_arm=on` in `/boot/config.txt`; reboot |
| DS3231 (0x68) not detected | RTC not wired or overlay missing | Add `dtoverlay=i2c-rtc,ds3231` to `/boot/config.txt`; reboot |
| Radar reads 0 bytes | Bluetooth not disabled, wrong UART | Verify `dtoverlay=disable-bt` in `/boot/config.txt`; check TX/RX not swapped |
| SCD40 reads outside 380-480ppm outdoors | Clone chip | Replace sensor |
| CSI no packets | ESP32 not on Basecamp-Node, wrong UDP IP | Check `hostapd` association log; verify UDP target is 192.168.4.1 |
| Screen stays blank | SPI not enabled, DC/RESET swapped | `ls /dev/spidev*`; check GPIO 24/25 wiring |
| SGP40 VOC reads erratic | Normal for first 24 hours | Wait for burn-in to complete |
| ntfy notification not received | Topic name mismatch | Verify `NTFY_TOPIC` in `server/config.py` matches phone subscription |
| Node 2 brownout resets during WiFi TX | 5m cable is too thin | Replace with 20AWG cable; verify listing states wire gauge |
| Lid doesn't seat flush | Magnet glued proud on body side | Press body-side magnet deeper into pocket with a flat tool; re-glue if loose |
| Time wrong after offline power cycle | RTC battery flat or fake-hwclock still active | Replace CR2032; disable fake-hwclock via systemctl |
