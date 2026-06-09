# Hardware Assembly and Bring-Up

Step-by-step guide for assembling and verifying Basecamp from components to first overnight run.

**Time required:** Allow a full day for first assembly. Most steps have a verification command — do not skip them.

---

## 0. Pre-Assembly Checklist

### Components
Verify all BOM items are present before starting.

- [ ] Raspberry Pi 4 Model B 4GB
- [ ] SanDisk 32GB MicroSD card
- [ ] Official Pi USB-C power supply (5V/3A)
- [ ] ESP32-S3-DevKitC-1 N16R8 × 2
- [ ] INMP441 I2S microphone
- [ ] HLK-LD2410C mmWave radar
- [ ] SHT40 temperature/humidity sensor
- [ ] BH1750 light sensor
- [ ] SCD40 CO2 sensor — verify genuine Sensirion logo printed on chip before proceeding
- [ ] SGP40 VOC sensor
- [ ] 2.8" IPS SPI touchscreen (ILI9341 or ST7789 driver)
- [ ] Powered 4-port USB hub with AC adapter
- [ ] Ethernet cable 5m
- [ ] Breadboard + jumper wires (M-F, F-F, M-M)
- [ ] USB-C cables: 2× short (0.5m) + 1× long (3–5m)
- [ ] M2.5 standoffs and screws
- [ ] 3D printed enclosure (if ordered — see note below)

> **Enclosure note:** Print time plus shipping is 5–7 days. If the enclosure has not arrived, proceed with the breadboard. All verification steps work without the enclosure.

### Tools
- MicroSD card reader
- Computer with Raspberry Pi Imager installed
- A second device (phone or laptop) to access the Pi web interface
- Multimeter (optional but useful for continuity checks)

---

## 1. Flash the MicroSD Card

On your computer:

1. Download and open [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Choose OS → **Raspberry Pi OS Lite (64-bit)** — no desktop needed
3. Choose storage → your SanDisk 32GB card
4. Click the gear icon (⚙) and configure:
   - Set hostname: `basecamp`
   - Enable SSH with password authentication
   - Set username: `pi`, password: your choice
   - Configure WiFi if you want wireless access during setup (optional — ethernet is more reliable)
5. Write to card

Insert the card into the Pi. Connect ethernet to your router. Connect power.

Wait 60 seconds for first boot, then find the Pi's IP address from your router's admin page, or:

```bash
# From another machine on the same network
ping basecamp.local
```

SSH in:

```bash
ssh pi@basecamp.local
```

---

## 2. Run the Setup Script

```bash
# Clone the repo
git clone https://github.com/Windows1985/Basecamp.git /home/pi/basecamp
cd /home/pi/basecamp

# Run setup (takes 10-15 minutes, installs all dependencies and systemd services)
sudo bash pi_setup.sh
```

The script will:
- Install Python dependencies
- Configure UART for the radar (disables Bluetooth, frees `/dev/ttyAMA0`)
- Set up SPI for the touchscreen
- Enable I2C
- Install and enable all five systemd services (disabled by default until sensors are verified)

Reboot after the script completes:

```bash
sudo reboot
```

---

## 3. Configure ntfy

The morning report and crash notifications are sent via ntfy. Set up before the first overnight run.

1. Install the [ntfy app](https://ntfy.sh) on your phone
2. Subscribe to a topic name of your choice (e.g., `basecamp-ethan-2024`) — keep it unguessable
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

## 4. Verify I2C Sensors

Wire all four I2C sensors to the Pi before this step. All four share GPIO 2 (SDA) and GPIO 3 (SCL). See `hardware/wiring.md` for full pin reference.

| Sensor | I2C Address |
|--------|-------------|
| BH1750 | 0x23 |
| SHT40 | 0x44 |
| SGP40 | 0x59 |
| SCD40 | 0x62 |

```bash
sudo i2cdetect -y 1
```

Expected output shows all four addresses populated. Example:

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:          -- -- -- -- -- -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- 23 -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- 44 -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- 59 -- -- -- -- -- --
60: -- -- 62 -- -- -- -- -- -- -- -- -- -- -- -- --
```

If an address is missing, check the wiring for that sensor. SDA/SCL reversed and insufficient 3.3V power are the most common causes.

**SGP40 burn-in:** SGP40 requires 24 hours of continuous operation before VOC readings stabilise. Leave the Pi running after this step and do not trust VOC output until the following day.

---

## 5. Calibrate the SCD40

Take the Pi outdoors (or near an open window) for this step. Outdoor CO2 is approximately 420ppm — this is the calibration reference.

```bash
cd /home/pi/basecamp
python3 server/calibrate_scd40.py
```

The script runs for approximately 3 minutes and prints readings. Expected output: 400–450ppm. 

If readings are consistently outside 380–480ppm, the chip is likely a clone. A clone SCD40 will produce plausible-looking but inaccurate readings that are difficult to detect later. Replace it before proceeding.

---

## 6. Verify the Radar

The HLK-LD2410C requires **5V power** (not 3.3V) and the Pi's hardware UART. Verify `dtoverlay=disable-bt` is present in `/boot/config.txt` (pi_setup.sh adds this automatically).

Wire the radar TX→GPIO 15 (Pi RXD), RX→GPIO 14 (Pi TXD), VCC→5V pin, GND→GND.

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

Expected: reads 100 bytes of radar output. If `len(data)` is 0, check TX/RX are not swapped (a common mistake — the radar's TX connects to the Pi's RX, not its own TX).

Wave your hand in front of the radar and verify the presence daemon detects it:

```bash
cd /home/pi/basecamp
python3 -c "
from server.presence import PresenceWatcher
p = PresenceWatcher(mock=False)
print(p.read_once())
"
```

---

## 7. Verify the Microphone

Wire INMP441 to GPIO 18 (BCK), 19 (LRCK), 20 (DIN). See `hardware/wiring.md` for full pinout including L/R select.

```bash
# Record 3 seconds of audio
arecord -D plughw:1 -c1 -r 16000 -f S32_LE -d 3 /tmp/test.wav
# Play it back
aplay /tmp/test.wav
```

If the device is not found, check `arecord -l` for the device index and adjust `plughw:N` accordingly. If playback is silence, verify the L/R select pin is pulled low (ground for left channel).

---

## 8. Verify the Touchscreen

Wire the ILI9341 touchscreen to the SPI pins. See `hardware/wiring.md` for full pinout including DC (GPIO 24), RESET (GPIO 25), backlight (GPIO 22), and touch IRQ (GPIO 17).

```bash
cd /home/pi/basecamp
python3 server/screen.py --test
```

Expected: the screen should display the IDLE layout (time, no score). If the screen stays blank, check SPI is enabled (`ls /dev/spidev*` should show `/dev/spidev0.0` and `/dev/spidev0.1`) and verify the DC and RESET pins are not swapped.

---

## 9. Flash and Verify ESP32 Node 1

On your development machine, follow the instructions in `firmware/README.md` to flash the ESP32-CSI-Tool firmware to the first ESP32-S3.

Key configuration before flashing:
- Target SSID: `RuView-24` (the dedicated 2.4GHz legacy SSID on your router)
- UDP target IP: the Pi's static IP address (set this in the router's DHCP reservation)
- UDP target port: `5500` (default in `server/config.py`)

Place Node 1 on the bedside table (left side, antenna end facing the bed, at mattress height).

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
        print('Timeout — no packets received')
        break
"
```

Expected: 5 packets received within 10 seconds. If no packets arrive, verify the ESP32 is connected to `RuView-24` (check the router's connected devices list) and the UDP target IP matches the Pi's actual IP.

---

## 10. First Overnight Run (Single Node)

Do not enable the second ESP32 node yet. Run the first overnight with one node to verify the full pipeline before adding complexity.

Start all services:

```bash
sudo systemctl start basecamp-logger basecamp-presence basecamp-audio basecamp-csi basecamp-screen
```

Verify all five are running:

```bash
sudo systemctl status basecamp-*
```

Check logs for errors:

```bash
journalctl -u basecamp-logger -u basecamp-presence -u basecamp-audio -u basecamp-csi --since "1 minute ago"
```

Trigger the bedtime prompt manually (long press GPIO 26, or):

```bash
cd /home/pi/basecamp
python3 -c "
from server.sleepmode import SleepMode
s = SleepMode()
s.force_bedtime_prompt()
"
```

The screen should show the BEDTIME_PROMPT layout. Press YES.

**In the morning:** Check that:
- The morning report ntfy notification arrived on your phone
- The Flask API has data: `curl http://basecamp.local:5000/latest`
- The React dashboard shows last night's session: open `http://basecamp.local:3000` in a browser

If the pipeline failed, check:

```bash
journalctl -u basecamp-presence --since "8 hours ago" | grep -i "error\|exception\|failed"
cat /home/pi/basecamp/logs/pipeline.log | tail -50
```

---

## 11. Flash and Add ESP32 Node 2

Once the first overnight run completes without errors, flash the second ESP32-S3 with the same firmware configuration as Node 1.

Place Node 2 on the right ledge, antenna end facing the bed, at mattress height. Route the 3–5m USB-C cable along the skirting board to the powered USB hub.

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

Expected: two source IPs, each with a similar packet count. If only one IP appears, the second node is not connected to `RuView-24`.

---

## 12. Submit First Morning Log

After the second overnight run completes, open the morning log either via:
- The touchscreen (swipe to the log view, adjust four sliders)
- The web interface: `http://basecamp.local:5000`

Submit Recovery, Energy, Clarity, and Mood scores (1–10 each).

This is the first labelled data point. The ML personalisation layer activates at 14 labelled nights. The recovery predictor activates at 30.

---

## Known First-Boot Issues

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `i2cdetect` shows no addresses | I2C not enabled | Check pi_setup.sh ran without errors; verify `dtparam=i2c_arm=on` in `/boot/config.txt` |
| Radar reads 0 bytes | Bluetooth not disabled, wrong UART | Verify `dtoverlay=disable-bt` in `/boot/config.txt`; reboot; check TX/RX not swapped |
| SCD40 reads outside 380–480ppm outdoors | Clone chip | Replace sensor |
| CSI no packets | ESP32 not on RuView-24, wrong UDP IP | Check router connected devices; verify UDP target IP in firmware config |
| Screen stays blank | SPI not enabled, DC/RESET swapped | `ls /dev/spidev*`; check GPIO 24/25 wiring |
| SGP40 VOC reads erratic | Normal for first 24 hours | Wait for burn-in to complete |
| ntfy notification not received | Topic name mismatch | Verify `NTFY_TOPIC` in `server/config.py` matches the topic subscribed on phone |
