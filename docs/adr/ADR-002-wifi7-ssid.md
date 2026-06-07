# ADR-002: Dedicated 2.4GHz SSID for WiFi 7 router

## Context
The home router is an ASUS RT-BE series (WiFi 7 / 802.11be). The ESP32-S3 firmware stack expects standard 802.11n behaviour on 2.4GHz. WiFi 7 introduces BSS colouring, MU-MIMO enhancements, and channel management features that interfere with CSI capture.

## Options considered
- Connect ESP32s directly to main WiFi network
- Create dedicated 2.4GHz SSID with legacy settings
- Use a separate TP-Link travel router (~80 RMB) dedicated to ESP32s

## Decision
Dedicated 2.4GHz SSID (RuView-24) with legacy mode settings on the ASUS router.

## Reasoning
The dedicated SSID approach is free, requires no additional hardware, and keeps the ESP32s on the same physical router as the Pi which connects via ethernet. Legacy mode settings (N only, 20MHz channel width, no MU-MIMO, no beamforming, no BSS colouring) replicate the 802.11n environment the ESP32 firmware expects.

## Router configuration

Apply these additional settings to the RuView-24 SSID on the ASUS router to ensure reliable CSI capture:

- Disable airtime fairness (AirTime Fairness / ATF)
- Disable Smart Connect (band steering)
- Disable band steering

## Consequences
WiFi 7 and ESP32-S3 CSI capture is untested in the RuView community. If CSI data is still corrupted after applying these settings, the fallback is a dedicated travel router (~80 RMB). This is an acceptable risk given the low cost of the fallback.
