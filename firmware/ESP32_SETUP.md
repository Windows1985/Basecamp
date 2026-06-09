# ESP32 Firmware Setup and Flash Guide

Step-by-step guide for building, configuring, and flashing both ESP32-S3 nodes.

**Time required:** 1–2 hours for first-time setup including toolchain installation. Second node is 15 minutes once the first is working.

---

## 0. Prerequisites

- ESP32-S3-DevKitC-1 N16R8 × 2
- USB-C cable connected to your Windows machine
- Pi's static IP address reserved in your router's DHCP settings before starting — you need this for the UDP target config
- `RuView-24` dedicated 2.4GHz legacy SSID active on the ASUS RT-BE router

---

## 1. Install ESP-IDF on Windows

Download and run the official Windows installer from:
**https://dl.espressif.com/dl/esp-idf/**

Select **ESP-IDF v5.4** (or v5.2 — both work; v5.4 has better S3 support). The installer sets up the full toolchain, Python environment, and adds `idf.py` to your path via the ESP-IDF Command Prompt shortcut.

After installation, always open the **ESP-IDF v5.x CMD** shortcut rather than a regular terminal — it sets the environment variables correctly.

**Alternative: Docker (no local toolchain needed)**

If the installer causes issues on your restricted school device, use Docker instead. Build runs entirely in a container:

```bash
# From active_sta/ directory (Git Bash or WSL)
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/project" -w /project \
  espressif/idf:v5.4 bash -c \
  "rm -rf build sdkconfig && idf.py set-target esp32s3 && idf.py build"
```

Build output appears in `build/`. First build takes 3–5 minutes; incremental rebuilds ~30 seconds.

---

## 2. Clone ESP32-CSI-Tool

```bash
git clone https://github.com/StevenMHernandez/ESP32-CSI-Tool.git
cd ESP32-CSI-Tool/active_sta
```

All commands below run from `active_sta/`.

---

## 3. Set Target to ESP32-S3

```bash
idf.py set-target esp32s3
```

This must be run once before menuconfig or build. It generates the correct `sdkconfig` base for the S3.

---

## 4. Configure — Node 1

```bash
idf.py menuconfig
```

Navigate with arrow keys, Enter to select, Q to quit and save. Set the following:

### ESP32 CSI Tool Config
| Setting | Value |
|---------|-------|
| WiFi SSID | `RuView-24` |
| WiFi Password | your password |
| UDP Receiver IP | Pi's static IP e.g. `192.168.1.100` |
| UDP Receiver Port | `5500` |
| Node ID | `1` |

### Serial flasher config
| Setting | Value |
|---------|-------|
| Default baud rate | `921600` |

### Component config → FreeRTOS
| Setting | Value |
|---------|-------|
| Tick rate (Hz) | `1000` |

> **Important:** The FreeRTOS tick rate affects CSI timing accuracy. Default is 100Hz — change it to 1000Hz or breathing rate estimation degrades.

Save and exit menuconfig (Q → Y).

---

## 5. Build — Node 1

```bash
idf.py build
```

First build: ~5 minutes, ~1400 compilation steps. You should see `Project build complete` with no errors.

---

## 6. Flash — Node 1

Put the ESP32-S3 into download mode:
1. Hold the **BOOT** button
2. Press and release **RESET**
3. Release **BOOT**

Find your COM port: open Device Manager → Ports (COM & LPT). It will appear as `USB Serial Device (COMx)` or `CP210x (COMx)`.

```bash
python -m esptool --chip esp32s3 --port COM7 --baud 460800 \
  --before default-reset --after hard-reset \
  write-flash --flash-mode dio --flash-freq 80m --flash-size 16MB \
  0x0     build/bootloader/bootloader.bin \
  0x8000  build/partition_table/partition-table.bin \
  0x10000 build/esp32-csi-node.bin
```

Replace `COM7` with your actual port. Use `--flash-size 16MB` — the N16R8 has 16MB flash, not 4MB.

Expected output ends with:
```
Hash of data verified.
Leaving...
Hard resetting via RTS pin...
```

---

## 7. Verify Node 1

Open the serial monitor at 921600 baud:

```bash
idf.py monitor
```

Or use any serial terminal (PuTTY, Arduino IDE Serial Monitor) at 921600 baud on the same COM port.

Expected output after boot:

```
ESP32-S3 CSI Node -- Node ID: 1
WiFi STA initialized, connecting to SSID: RuView-24
Connected to WiFi
CSI streaming active -> 192.168.1.100:5500
```

If you see `WiFi connecting...` looping:
- Verify `RuView-24` is broadcasting (check router admin page)
- Verify the password in menuconfig is correct
- Verify the SSID is 2.4GHz only — the S3 cannot connect to 5GHz or WiFi 6/7 BSSes

Exit monitor with `Ctrl+]`.

On the Pi, verify packets are arriving:

```bash
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

Expected: 5 packets within 10 seconds.

---

## 8. Configure and Flash — Node 2

Node 2 is identical to Node 1 except for the Node ID. You need a full rebuild because Node ID is baked in at compile time.

```bash
# Still in active_sta/
idf.py menuconfig
```

Change only:

| Setting | Old | New |
|---------|-----|-----|
| Node ID | `1` | `2` |

Save, then:

```bash
idf.py build
```

Connect Node 2, put it into download mode, flash with the same command as Node 1 (same COM port if Node 1 is disconnected, or a different port if both are connected).

Place Node 2 on the right ledge at mattress height. Route the 3–5m USB-C cable along the skirting board to the powered USB hub.

---

## 9. Verify Both Nodes Simultaneously

With both nodes powered and connected to `RuView-24`, verify two distinct source IPs are streaming to the Pi:

```bash
timeout 15 python3 -c "
import socket, time
from collections import defaultdict
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('0.0.0.0', 5500))
s.settimeout(2)
sources = defaultdict(int)
end = time.time() + 10
while time.time() < end:
    try:
        data, addr = s.recvfrom(4096)
        sources[addr[0]] += 1
    except socket.timeout:
        pass
for ip, count in sources.items():
    print(f'{ip}: {count} packets')
print(f'Total sources: {len(sources)}')
"
```

Expected: two IPs, each with ~20 packets. If only one IP appears, the second node is not connecting to `RuView-24` — check its serial output.

---

## 10. Flash Scripts

To avoid reconstructing commands in HK, save these as `firmware/flash_node1.bat` and `firmware/flash_node2.bat`. Edit the COM port and Pi IP before use.

**flash_node1.bat**
```bat
@echo off
echo Flashing Node 1 -- make sure ESP32-S3 is in download mode (hold BOOT, press RESET)
python -m esptool --chip esp32s3 --port COM7 --baud 460800 ^
  --before default-reset --after hard-reset ^
  write-flash --flash-mode dio --flash-freq 80m --flash-size 16MB ^
  0x0     active_sta\build\bootloader\bootloader.bin ^
  0x8000  active_sta\build\partition_table\partition-table.bin ^
  0x10000 active_sta\build\esp32-csi-node.bin
pause
```

**flash_node2.bat** — identical, points to Node 2 build directory (rebuild after changing Node ID to 2 in menuconfig).

---

## Common Issues

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `A fatal error occurred: Failed to connect` | Not in download mode | Hold BOOT, press RESET, release BOOT, retry immediately |
| `No serial port found` | Wrong COM port or driver missing | Device Manager → check CP210x or CH340 driver is installed |
| `WiFi connecting...` loop | Wrong SSID/password, or 5GHz band | Verify RuView-24 is 2.4GHz legacy; check password in menuconfig |
| No UDP packets on Pi | Wrong UDP target IP, firewall | Verify Pi's IP matches menuconfig; check `ufw status` on Pi |
| Packets from only 1 node | Node 2 not connected | Check Node 2 serial output; verify Node ID was changed and reflashed |
| CSI data looks wrong / all zeros | FreeRTOS tick rate at default 100Hz | Set to 1000Hz in menuconfig, rebuild |
| `--flash-size detect` shows 4MB | Wrong flash size flag | Use `--flash-size 16MB` explicitly for N16R8 |
