# Wiring reference

All connections are on the Raspberry Pi 4. The prototype uses an 830-point breadboard with Dupont jumper wires. All sensors are purchased as breakout boards with pre-soldered headers.

## I2C bus (GPIO 2 and GPIO 3)

Four environmental sensors share a single I2C bus. No additional wiring complexity beyond connecting each sensor to the same two data pins.

| Sensor | VCC | GND | SDA | SCL |
|--------|-----|-----|-----|-----|
| SHT40 | 3.3V | GND | GPIO 2 | GPIO 3 |
| BH1750 | 3.3V | GND | GPIO 2 | GPIO 3 |
| SCD40 | 3.3V | GND | GPIO 2 | GPIO 3 |
| SGP40 | 3.3V | GND | GPIO 2 | GPIO 3 |

All four sensors can share the same physical SDA and SCL lines because I2C is an addressable bus. Each sensor has a unique I2C address so there are no conflicts.

I2C addresses for reference:
- SHT40: 0x44
- BH1750: 0x23 (or 0x5C if ADDR pin is high)
- SCD40: 0x62
- SGP40: 0x59

## I2S (INMP441 microphone)

| INMP441 pin | Pi GPIO | Notes |
|-------------|---------|-------|
| VDD | 3.3V | |
| GND | GND | |
| SCK | GPIO 18 | Bit clock |
| WS | GPIO 19 | Word select (left/right clock) |
| SD | GPIO 20 | Serial data out |
| L/R | GND | Sets microphone to left channel |

Enable I2S in /boot/config.txt and install an appropriate ALSA/device-tree overlay for the INMP441; set dtparam=i2s=on.

## UART (HLK-LD2410C radar)

| LD2410C pin | Pi GPIO | Notes |
|-------------|---------|-------|
| VCC | 5V | Radar requires 5V, not 3.3V |
| GND | GND | |
| TX | GPIO 15 (RXD) | Radar TX to Pi RX |
| RX | GPIO 14 (TXD) | Radar RX to Pi TX |

The LD2410C outputs presence detection, moving and still target states, distance per gate, and energy levels over UART. It does not output a respiration waveform. Its role in this project is bed presence detection, bed entry and exit timestamps, and gross micro-motion detection. Breathing rate is derived from CSI and audio only.

The default baud rate is 256000, which is non-standard and requires the Pi's full hardware UART rather than the mini-UART. The Pi 4 maps the full hardware UART to Bluetooth by default, so you have two options. The simpler option is to disable Bluetooth entirely by adding dtoverlay=disable-bt to /boot/config.txt. The alternative is to remap the hardware UART away from Bluetooth using dtoverlay=miniuart-bt, which keeps Bluetooth functional but on the less reliable mini-UART.

In addition to the baud rate setup, disable the Pi serial console so the UART is free for the radar: run sudo raspi-config, go to Interface Options, Serial Port, disable login shell over serial, enable the serial port hardware. The radar will then be available at /dev/ttyAMA0.

## SPI (2.8 inch touchscreen)

| Screen pin | Pi GPIO | Notes |
|------------|---------|-------|
| VCC | 3.3V | |
| GND | GND | |
| CS | GPIO 8 (CE0) | Chip select |
| RESET | GPIO 25 | |
| DC | GPIO 24 | Data/command select |
| MOSI | GPIO 10 (MOSI) | |
| SCK | GPIO 11 (SCLK) | |
| LED | 3.3V | Backlight, always on |
| MISO | GPIO 9 (MISO) | Touch input only |
| T_CS | GPIO 7 (CE1) | Touch chip select |
| T_CLK | GPIO 11 (SCLK) | Shared with display |
| T_DIN | GPIO 10 (MOSI) | Shared with display |
| T_DO | GPIO 9 (MISO) | Shared with display |
| T_IRQ | GPIO 17 | Touch interrupt (optional) |

Enable SPI in /boot/config.txt by adding: dtparam=spi=on

The display and touch controller share the MOSI, MISO, and SCLK lines, using CE0 and CE1 as separate chip selects. If adding another SPI device in future, a third chip select pin will be needed and careful chip select management is required to avoid bus conflicts.

## ESP32-S3 nodes

The ESP32 nodes do not connect to the Pi via GPIO. They connect over WiFi on the dedicated RuView-24 2.4GHz SSID and stream raw CSI data to the Pi via UDP. Each node is powered independently via USB-C.

Node 1 (bedroom left): bedside table, powered from left wall socket
Node 2 (bedroom right): ledge at mattress height, powered via 3-5m USB-C cable routed along skirting board from left wall sockets

## Power

All sensors run on 3.3V from the Pi's 3.3V pin except the LD2410C radar which requires 5V. The Pi's 3.3V rail can comfortably supply all four I2C sensors and the INMP441 simultaneously. Total current draw from the 3.3V rail is well within the Pi 4's 500mA limit.

The Pi is powered from the official 5V/3A USB-C supply. The powered USB hub is powered independently and supplies both ESP32 nodes.

## GPIO pin summary

| GPIO | Function |
|------|----------|
| 2 | I2C SDA (all environmental sensors) |
| 3 | I2C SCL (all environmental sensors) |
| 7 | SPI CE1 (touchscreen touch) |
| 8 | SPI CE0 (touchscreen display) |
| 9 | SPI MISO |
| 10 | SPI MOSI |
| 11 | SPI SCLK |
| 14 | UART TXD (radar RX) |
| 15 | UART RXD (radar TX) |
| 17 | Touch IRQ (optional) |
| 18 | I2S BCK (microphone) |
| 19 | I2S LRCK (microphone) |
| 20 | I2S DIN (microphone) |
| 24 | SPI DC (touchscreen) |
| 25 | SPI RESET (touchscreen) |

## /boot/config.txt changes required

Add the following lines:

dtparam=i2c_arm=on
dtparam=i2s=on
dtparam=spi=on
dtoverlay=disable-bt

Then disable the serial console via raspi-config as described in the UART section above. Reboot before testing any sensors.
