# Networking

Basecamp uses a split-radio architecture: wlan0 is an isolated AP for the ESP32 nodes only, and eth0 is a DHCP client for internet, NTP, and dashboard access.

---

## Why the WiFi network exists at all

CSI (channel state information) is a property of a WiFi link. There is no way to collect CSI without a working 802.11 association between the ESP32 nodes and an access point. The Pi's wlan0 AP is that access point. The network carries no general traffic -- only the UDP CSI stream from each ESP32 node to the Pi, and DHCP/DNS for the nodes themselves.

The AP runs on a fixed channel (channel 6, 20MHz bandwidth, N-only) so the RF environment is identical at every deployment location. This is what makes CSI baselines portable between HK, Shenzhen, and Cate without retraining.

---

## Interface roles

| Interface | Role |
|-----------|------|
| wlan0 | AP for ESP32 nodes only. SSID: Basecamp-Node. Fixed IP 192.168.4.1. No internet routing from this interface to the wider LAN. |
| eth0 | DHCP client. Internet, NTP, and dashboard access. Phone and laptop reach the dashboard here. |

The Pi has one radio (combo chip). It cannot be simultaneously an AP on wlan0 and a station client on a router's SSID. All internet access requires eth0.

---

## Reaching the dashboard by location

**Home (ethernet connected):**
- Pi's eth0 gets a LAN IP from the home router.
- Phone on the same LAN opens `http://basecamp.local:5000` or the Pi's LAN IP.

**Cate School (dorm room, ethernet connected):**
- Same as home: eth0 on the school LAN, dashboard accessible from any device on the same LAN segment.
- ESP32 nodes connect to Basecamp-Node (wlan0); they do not need internet access.

**No ethernet available:**
- Join the Pi hotspot (SSID: Basecamp-Node) on the phone.
- Dashboard accessible at `http://192.168.4.1:5000`.
- Note: the phone will have no internet while on this hotspot (the AP is isolated).

---

## NTP and timekeeping

NTP syncs over eth0 when available. The DS3231 RTC module (I2C 0x68) maintains time when eth0 is not connected. On power cycle without ethernet, the system clock is loaded from the RTC within seconds of boot -- no manual time-set needed.

If neither ethernet nor RTC is available (flat CR2032 battery), the Pi will boot with an incorrect time and session timestamps will be wrong. Replace the CR2032 battery immediately if `timedatectl` shows a clock far from the real time after an offline reboot.

---

## Bluetooth

Bluetooth is disabled (`dtoverlay=disable-bt` in config.txt). The Pi's BT radio shares the 2.4GHz band and the same combo chip as the CSI-serving AP. BT activity injects interference into the measured WiFi channel and time-slices the radio, corrupting CSI readings.

**Optional future experiment:** `rfkill block bluetooth` during measurement windows (23:00 to 08:00) without a permanent hardware change, to quantify the interference contribution. This would require a cron job or a systemd timer that calls rfkill on the measurement schedule.

---

## Deprecated: router-dependent setup

The original v1/v2/v3 setup used a dedicated 2.4GHz legacy SSID on an ASUS WiFi 7 router (SSID: RuView-24, N-only, 20MHz, MU-MIMO off). This required manual router configuration at every location, produced different RF environments at each site, and was incompatible with school network infrastructure.

The router-mode configuration is retained in the pi_setup.sh deprecated appendix in case a router is available and preferred. The hotspot setup in pi_setup.sh is the canonical path.
