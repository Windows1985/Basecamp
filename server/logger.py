"""
Sensor logger daemon -- reads all four environmental sensors every 30 seconds
and writes one row to sensor_readings. Runs overnight on the Pi.
"""
import os
import sys
import signal
import threading
import time
import logging
import logging.handlers
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.config import (
    DB_PATH, I2C_BUS, SHT40_ADDR, BH1750_ADDR, SCD40_ADDR, SGP40_ADDR,
    MOCK_HARDWARE, WATCHDOG_INTERVAL_SECONDS, HEARTBEAT_INTERVAL_SECONDS,
)
from server.db import init_db, get_connection

# ---------------------------------------------------------------------------
# Hardware imports (optional -- fall back to mock if unavailable)
# ---------------------------------------------------------------------------
try:
    import smbus2
    _SMBUS_AVAILABLE = True
except ImportError:
    _SMBUS_AVAILABLE = False

try:
    from sensirion_i2c_driver import I2cConnection, LinuxI2cTransceiver
    from sensirion_i2c_scd4x import Scd4xI2cDevice
    _SCD4X_LIB = True
except ImportError:
    _SCD4X_LIB = False

try:
    from sensirion_i2c_sgp4x import Sgp40I2cDevice
    _SGP40_LIB = True
except ImportError:
    _SGP40_LIB = False

try:
    from voc_algorithm import VocAlgorithm
    _VOC_ALG = True
except ImportError:
    _VOC_ALG = False

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "logs/logger.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("logger")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.addHandler(_stream)

# ---------------------------------------------------------------------------
# Mock state (shared across calls for realistic drift)
# ---------------------------------------------------------------------------
_mock = {
    "temp": 20.0,
    "humidity": 65.0,
    "co2": 420.0,
    "voc": 100.0,
    "start_time": None,
}


def _mock_readings():
    import random
    import math

    now = time.time()
    if _mock["start_time"] is None:
        _mock["start_time"] = now

    elapsed_hours = (now - _mock["start_time"]) / 3600.0

    _mock["temp"] += random.uniform(-0.05, 0.05)
    _mock["temp"] = max(19.0, min(21.0, _mock["temp"]))

    _mock["humidity"] += random.uniform(-0.1, 0.1)
    _mock["humidity"] = max(60.0, min(70.0, _mock["humidity"]))

    _mock["co2"] = 420.0 + elapsed_hours * 200.0 + random.uniform(-20, 20)
    _mock["co2"] = max(380.0, _mock["co2"])

    _mock["voc"] += random.uniform(-2, 2)
    _mock["voc"] = max(80.0, min(120.0, _mock["voc"]))

    # Light near zero overnight; brief spike around 3 am (simulated as 3h after start)
    light = 0.0
    if 2.9 <= elapsed_hours <= 3.1:
        light = 50.0 + random.uniform(0, 20)
    else:
        light = random.uniform(0, 0.5)

    import random as _r
    max_lux = round(light + _r.uniform(0, light * 0.2 + 0.1), 2)
    return {
        "temperature": round(_mock["temp"], 2),
        "humidity": round(_mock["humidity"], 2),
        "co2_ppm": round(_mock["co2"], 1),
        "voc_index": round(_mock["voc"], 1),
        "light_lux": round(light, 2),
        "max_lux": max_lux,
    }


# ---------------------------------------------------------------------------
# Real sensor reads
# ---------------------------------------------------------------------------

def _crc8(data):
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _read_sht40(bus):
    bus.write_byte(SHT40_ADDR, 0xFD)
    time.sleep(0.01)
    data = bus.read_i2c_block_data(SHT40_ADDR, 0, 6)
    if _crc8(data[0:2]) != data[2] or _crc8(data[3:5]) != data[5]:
        raise ValueError("SHT40 CRC mismatch")
    raw_t = (data[0] << 8) | data[1]
    raw_h = (data[3] << 8) | data[4]
    temp = -45.0 + 175.0 * raw_t / 65535.0
    hum = -6.0 + 125.0 * raw_h / 65535.0
    return round(temp, 2), round(max(0.0, min(100.0, hum)), 2)


def _read_bh1750(bus):
    bus.write_byte(BH1750_ADDR, 0x10)
    time.sleep(0.18)
    data = bus.read_i2c_block_data(BH1750_ADDR, 0, 2)
    raw = (data[0] << 8) | data[1]
    return round(raw / 1.2, 2)


def _read_scd40_direct(bus):
    # Stop any ongoing measurement first
    bus.write_i2c_block_data(SCD40_ADDR, 0x3F, [0x86])
    time.sleep(0.5)
    # Start periodic measurement
    bus.write_i2c_block_data(SCD40_ADDR, 0x21, [0xB1])
    time.sleep(5.0)
    for _ in range(20):
        bus.write_i2c_block_data(SCD40_ADDR, 0xE4, [0xB8])
        time.sleep(0.01)
        rdy = bus.read_i2c_block_data(SCD40_ADDR, 0, 3)
        if rdy[1] & 0x07:
            break
        time.sleep(1.0)
    bus.write_i2c_block_data(SCD40_ADDR, 0xEC, [0x05])
    time.sleep(0.01)
    data = bus.read_i2c_block_data(SCD40_ADDR, 0, 9)
    if _crc8(data[0:2]) != data[2]:
        raise ValueError("SCD40 CO2 CRC mismatch")
    co2 = (data[0] << 8) | data[1]
    return float(co2)


def _read_sgp40_direct(bus):
    # Default compensation: T=25C encoded, RH=50% encoded
    comp = [0x66, 0x66, 0x93, 0x80, 0x00, 0xA2]
    bus.write_i2c_block_data(SGP40_ADDR, 0x26, [0x0F] + comp)
    time.sleep(0.03)
    data = bus.read_i2c_block_data(SGP40_ADDR, 0, 3)
    if _crc8(data[0:2]) != data[2]:
        raise ValueError("SGP40 CRC mismatch")
    raw = (data[0] << 8) | data[1]
    return float(raw)


# ---------------------------------------------------------------------------
# Undervoltage check (both ESP32 nodes now share the Pi's USB supply in v4)
# ---------------------------------------------------------------------------

def _check_undervoltage():
    try:
        import subprocess as _sp
        result = _sp.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True, text=True, timeout=3,
        )
        val = result.stdout.strip()
        # get_throttled returns hex bitmask; bit 0 = currently under-voltage
        if "=" in val:
            bits = int(val.split("=")[1], 16)
            if bits & 0x1:
                log.warning(
                    "Pi undervoltage detected (vcgencmd get_throttled=%s). "
                    "Both ESP32 nodes share the Pi USB supply in v4 -- "
                    "verify the PSU is the official 5V/3A adapter and "
                    "the Node 2 cable is 20AWG or thicker.",
                    val,
                )
            else:
                log.info("Power supply OK (get_throttled=%s)", val)
    except Exception as e:
        log.debug("vcgencmd check skipped: %s", e)


# ---------------------------------------------------------------------------
# Daemon state
# ---------------------------------------------------------------------------
_running = True
_bus = None
_voc_algorithm = None


def _handle_sigterm(signum, frame):
    global _running
    log.info("SIGTERM received, shutting down")
    _running = False


def _init_hardware():
    global _bus, _voc_algorithm
    sensors_ok = []
    sensors_fail = []

    if not _SMBUS_AVAILABLE:
        log.warning("smbus2 not available -- hardware init skipped")
        return sensors_ok, sensors_fail

    try:
        _bus = smbus2.SMBus(I2C_BUS)
        sensors_ok.append("I2C bus")
    except Exception as e:
        log.error(f"Failed to open I2C bus: {e}")
        return sensors_ok, sensors_fail

    for name, addr, probe_cmd in [
        ("SHT40", SHT40_ADDR, 0xFD),
        ("BH1750", BH1750_ADDR, 0x10),
    ]:
        try:
            _bus.write_byte(addr, probe_cmd)
            sensors_ok.append(name)
        except Exception as e:
            log.warning(f"{name} init failed: {e}")
            sensors_fail.append(name)

    for name, addr in [("SCD40", SCD40_ADDR), ("SGP40", SGP40_ADDR)]:
        sensors_ok.append(name)  # initialised on first read

    if _VOC_ALG:
        _voc_algorithm = VocAlgorithm()

    return sensors_ok, sensors_fail


def _read_all_sensors():
    results = {
        "temperature": None,
        "humidity": None,
        "co2_ppm": None,
        "voc_index": None,
        "light_lux": None,
        "max_lux": None,
    }

    if MOCK_HARDWARE or not _SMBUS_AVAILABLE or _bus is None:
        return _mock_readings()

    try:
        temp, hum = _read_sht40(_bus)
        results["temperature"] = temp
        results["humidity"] = hum
    except Exception as e:
        log.error(f"SHT40 read error: {e}")

    try:
        results["light_lux"] = _read_bh1750(_bus)
    except Exception as e:
        log.error(f"BH1750 read error: {e}")

    try:
        results["co2_ppm"] = _read_scd40_direct(_bus)
    except Exception as e:
        log.error(f"SCD40 read error: {e}")

    try:
        raw_voc = _read_sgp40_direct(_bus)
        if _voc_algorithm is not None:
            results["voc_index"] = float(_voc_algorithm.process(raw_voc))
        else:
            results["voc_index"] = raw_voc
    except Exception as e:
        log.error(f"SGP40 read error: {e}")

    return results


def _write_heartbeat():
    try:
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                """INSERT INTO service_heartbeats (service_name, last_heartbeat, status)
                   VALUES ('logger', ?, 'running')
                   ON CONFLICT(service_name) DO UPDATE
                   SET last_heartbeat=excluded.last_heartbeat, status=excluded.status""",
                (time.time(),),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log.debug(f"Heartbeat write failed: {e}")


def _write_reading(readings):
    ts = datetime.utcnow().isoformat()
    sql = """
        INSERT INTO sensor_readings
        (timestamp, temperature, humidity, co2_ppm, voc_index, light_lux, max_lux)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    params = (
        ts,
        readings["temperature"],
        readings["humidity"],
        readings["co2_ppm"],
        readings["voc_index"],
        readings["light_lux"],
        readings.get("max_lux"),
    )
    for attempt in range(2):
        try:
            conn = get_connection(DB_PATH)
            try:
                conn.execute(sql, params)
                conn.commit()
            finally:
                conn.close()
            return
        except Exception as e:
            log.error(f"DB write failed (attempt {attempt + 1}): {e}")
            if attempt == 0:
                time.sleep(5)
    log.error("DB write failed after retry, dropping reading")


def _collect_bh1750_1hz(bus, n_samples=30):
    """
    Collect n_samples BH1750 readings at ~1 Hz.
    Returns (mean_lux, max_lux). Falls back to a single reading on error.
    """
    readings = []
    for _ in range(n_samples):
        try:
            lux = _read_bh1750(bus)
            readings.append(lux)
        except Exception as e:
            log.debug(f"BH1750 1Hz sample error: {e}")
        time.sleep(1.0)
    if not readings:
        return None, None
    return round(sum(readings) / len(readings), 2), round(max(readings), 2)


def run():
    global _running
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle_sigterm)

    init_db(DB_PATH)

    if MOCK_HARDWARE:
        log.info("Starting sensor logger in MOCK mode")
        print("Sensor logger started -- MOCK mode")
    else:
        _check_undervoltage()
        sensors_ok, sensors_fail = _init_hardware()
        msg = f"Sensor logger started -- OK: {sensors_ok}"
        if sensors_fail:
            msg += f"  FAILED: {sensors_fail}"
        log.info(msg)
        print(msg)

    try:
        import sdnotify as _sdnotify
        _notifier = _sdnotify.SystemdNotifier()
    except ImportError:
        _notifier = None

    last_watchdog = time.monotonic()
    last_heartbeat = time.monotonic()

    while _running:
        # --- BH1750 1Hz collection (takes ~30s, matches the loop cadence) ---
        if not MOCK_HARDWARE and _SMBUS_AVAILABLE and _bus is not None:
            mean_lux, max_lux = _collect_bh1750_1hz(_bus, n_samples=30)
        else:
            mean_lux, max_lux = None, None
            # In mock mode still wait the 30-second window
            for _ in range(30):
                if not _running:
                    break
                time.sleep(1)

        readings = _read_all_sensors()
        # Overwrite light_lux with the mean from 1Hz collection if available
        if mean_lux is not None:
            readings["light_lux"] = mean_lux
            readings["max_lux"] = max_lux
        _write_reading(readings)
        log.debug(f"Reading: {readings}")

        now_mono = time.monotonic()
        if now_mono - last_watchdog >= WATCHDOG_INTERVAL_SECONDS:
            last_watchdog = now_mono
            try:
                if _notifier:
                    _notifier.notify("WATCHDOG=1")
            except Exception:
                pass
        if now_mono - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
            last_heartbeat = now_mono
            _write_heartbeat()

    log.info("Sensor logger stopped")


if __name__ == "__main__":
    run()
