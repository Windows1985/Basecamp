#!/usr/bin/env python3
"""
SCD40 CO2 sensor forced-recalibration tool.

Place the sensor near an open window or outdoors, then run:
    python3 server/calibrate_scd40.py

The script takes 6 readings over ~3 minutes, then performs forced
recalibration (FRC) if the mean is within 100 ppm of 419 ppm (current
atmospheric average).  If the mean is outside that range the sensor is
likely indoors or a counterfeit chip — the script exits without calibrating.

Usage:
    python3 server/calibrate_scd40.py           # real hardware (I2C bus 1)
    python3 server/calibrate_scd40.py --dry-run  # simulate, no I2C calls
"""
import sys
import time
import argparse

# ── Constants ──────────────────────────────────────────────────────────────────
SCD40_ADDR         = 0x62
I2C_BUS            = 1
ATMOSPHERIC_CO2    = 419    # ppm — current global average (2024)
TOLERANCE          = 100    # ppm — acceptable deviation for safe calibration
N_READINGS         = 6
INTERVAL_S         = 30     # seconds between measurements
SIMULATED_READINGS = [418, 421, 415, 423, 417, 420]   # used in dry-run only

# SCD40 I2C command bytes (from Sensirion datasheet)
_CMD_STOP_MEASUREMENT  = (0x3F, 0x86)
_CMD_START_MEASUREMENT = (0x21, 0xB1)
_CMD_DATA_READY        = (0xE4, 0xB8)
_CMD_READ_MEASUREMENT  = (0xEC, 0x05)
_CMD_FRC               = (0x36, 0x2F)


# ── CRC-8 (polynomial 0x31, init 0xFF) — required for SCD40 protocol ──────────
def _crc8(data: bytes) -> int:
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) if (crc & 0x80) else (crc << 1)
            crc &= 0xFF
    return crc


# ── Low-level I2C helpers ──────────────────────────────────────────────────────

def _write_cmd(bus, addr: int, cmd: tuple) -> None:
    bus.write_i2c_block_data(addr, cmd[0], [cmd[1]])
    time.sleep(0.001)


def _read_measurement(bus, addr: int) -> tuple:
    """
    Read one SCD40 measurement.
    Returns (co2_ppm, temperature_c, humidity_pct).
    Raises IOError on CRC mismatch.
    """
    _write_cmd(bus, addr, _CMD_READ_MEASUREMENT)
    time.sleep(0.001)
    raw = bus.read_i2c_block_data(addr, 0, 9)

    for offset in (0, 3, 6):
        calculated = _crc8(bytes(raw[offset:offset + 2]))
        if calculated != raw[offset + 2]:
            raise IOError(
                f"SCD40 CRC mismatch at byte offset {offset}: "
                f"expected 0x{raw[offset + 2]:02X}, got 0x{calculated:02X}"
            )

    co2  = (raw[0] << 8) | raw[1]
    temp = -45.0 + 175.0 * ((raw[3] << 8) | raw[4]) / 65535.0
    hum  = 100.0 * ((raw[6] << 8) | raw[7]) / 65535.0
    return co2, temp, hum


def _is_data_ready(bus, addr: int) -> bool:
    _write_cmd(bus, addr, _CMD_DATA_READY)
    time.sleep(0.001)
    rdy = bus.read_i2c_block_data(addr, 0, 3)
    return bool(rdy[1] & 0x07)


# ── Real calibration (hardware path) ──────────────────────────────────────────

def calibrate_real() -> None:
    try:
        import smbus2
    except ImportError:
        print("ERROR: smbus2 not installed.")
        print("       Run: pip install smbus2")
        sys.exit(1)

    print(f"Initialising SCD40 on I2C bus {I2C_BUS} (addr 0x{SCD40_ADDR:02X})...")
    bus = smbus2.SMBus(I2C_BUS)

    # Stop any running measurement before issuing configuration commands
    _write_cmd(bus, SCD40_ADDR, _CMD_STOP_MEASUREMENT)
    time.sleep(0.5)

    # Start periodic measurement (one reading every 5 s)
    _write_cmd(bus, SCD40_ADDR, _CMD_START_MEASUREMENT)

    print(f"\nTaking {N_READINGS} readings at {INTERVAL_S}s intervals.")
    print("Place the sensor near an open window or outdoors first.\n")

    readings: list = []
    for i in range(1, N_READINGS + 1):
        # Wait for the next 30 s window
        time.sleep(INTERVAL_S)

        # Poll until data is ready (up to 6 extra seconds)
        waited = 0
        while not _is_data_ready(bus, SCD40_ADDR) and waited < 6:
            time.sleep(1)
            waited += 1

        co2, temp, hum = _read_measurement(bus, SCD40_ADDR)
        print(f"  Reading {i}/{N_READINGS}: {co2} ppm  "
              f"({temp:.1f}°C  {hum:.0f}% RH)")
        readings.append(co2)

    mean = sum(readings) / len(readings)
    lo   = ATMOSPHERIC_CO2 - TOLERANCE
    hi   = ATMOSPHERIC_CO2 + TOLERANCE
    print(f"\nMean CO2: {mean:.1f} ppm")
    print(f"Acceptable range for calibration: {lo}–{hi} ppm")

    if not (lo <= mean <= hi):
        _write_cmd(bus, SCD40_ADDR, _CMD_STOP_MEASUREMENT)
        bus.close()
        print(
            f"\nWARNING: Mean {mean:.1f} ppm is outside the acceptable range.\n"
            "Do NOT calibrate — the sensor may be:\n"
            "  • Measuring indoor air (CO2 too high)\n"
            "  • A counterfeit chip with a drifted reference\n"
            "\nMove the sensor outdoors and retry, or inspect the chip markings.\n"
            "Genuine Sensirion SCD40 chips are marked 'SCD40' on a white ceramic package."
        )
        sys.exit(1)

    # Stop periodic measurement before sending FRC command
    _write_cmd(bus, SCD40_ADDR, _CMD_STOP_MEASUREMENT)
    time.sleep(0.5)

    # Forced Recalibration: command 0x362F + uint16 target + CRC
    target_hi = (ATMOSPHERIC_CO2 >> 8) & 0xFF
    target_lo = ATMOSPHERIC_CO2 & 0xFF
    crc = _crc8(bytes([target_hi, target_lo]))
    print(f"\nRunning forced recalibration at {ATMOSPHERIC_CO2} ppm...")
    bus.write_i2c_block_data(
        SCD40_ADDR, _CMD_FRC[0],
        [_CMD_FRC[1], target_hi, target_lo, crc]
    )
    time.sleep(0.4)

    # Read back the FRC correction value (3 bytes)
    frc_result = bus.read_i2c_block_data(SCD40_ADDR, 0, 3)
    correction = ((frc_result[0] << 8) | frc_result[1]) - 0x8000
    print(f"FRC correction applied: {correction:+d} ppm")
    print("\nCalibration complete.")
    print("Restart the logger to use the corrected baseline:")
    print("  sudo systemctl restart basecamp-logger")

    bus.close()


# ── Dry-run (no I2C) ───────────────────────────────────────────────────────────

def calibrate_dry_run() -> None:
    print("=== DRY RUN MODE — no I2C calls will be made ===\n")
    print(f"Would initialise SCD40 on I2C bus {I2C_BUS} (addr 0x{SCD40_ADDR:02X})")
    print(f"Would send STOP_MEASUREMENT (0x{_CMD_STOP_MEASUREMENT[0]:02X}"
          f"{_CMD_STOP_MEASUREMENT[1]:02X})")
    print(f"Would send START_MEASUREMENT (0x{_CMD_START_MEASUREMENT[0]:02X}"
          f"{_CMD_START_MEASUREMENT[1]:02X})")
    print(f"\nWould take {N_READINGS} readings at {INTERVAL_S}s intervals:\n")

    for i, co2 in enumerate(SIMULATED_READINGS, 1):
        print(f"  Reading {i}/{N_READINGS}: {co2} ppm  (simulated)")

    mean = sum(SIMULATED_READINGS) / len(SIMULATED_READINGS)
    lo   = ATMOSPHERIC_CO2 - TOLERANCE
    hi   = ATMOSPHERIC_CO2 + TOLERANCE
    print(f"\nMean CO2: {mean:.1f} ppm")
    print(f"Range check {lo}–{hi} ppm: {'PASS' if lo <= mean <= hi else 'FAIL'}")

    if lo <= mean <= hi:
        print(f"\nWould send STOP_MEASUREMENT then FRC at {ATMOSPHERIC_CO2} ppm")
        target_hi = (ATMOSPHERIC_CO2 >> 8) & 0xFF
        target_lo = ATMOSPHERIC_CO2 & 0xFF
        crc = _crc8(bytes([target_hi, target_lo]))
        print(f"  Command bytes: 0x{_CMD_FRC[0]:02X} 0x{_CMD_FRC[1]:02X} "
              f"0x{target_hi:02X} 0x{target_lo:02X} 0x{crc:02X} (CRC)")
        print("\n[DRY RUN] Calibration would succeed.")
    else:
        print(f"\n[DRY RUN] Would exit without calibrating (mean out of range).")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate the SCD40 CO2 sensor against outdoor atmospheric air "
            f"({ATMOSPHERIC_CO2} ppm).  Run outdoors or near an open window."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what the script would do without making any I2C calls.",
    )
    args = parser.parse_args()

    if args.dry_run:
        calibrate_dry_run()
    else:
        calibrate_real()


if __name__ == "__main__":
    main()
