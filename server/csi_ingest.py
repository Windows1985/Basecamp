"""
CSI live ingestion daemon — overnight path.

Opens a UDP socket on CSI_UDP_PORT, receives raw CSI packets from both ESP32
nodes, computes a lightweight cross-subcarrier variance signal, downsamples
to 20 Hz, and appends each value to the csi_variance table.

In MOCK_HARDWARE=True mode the daemon generates synthetic CSI using the same
generator used by the test suite, so the whole ingestion path can be exercised
on any machine without real hardware.

Schema requirement: server/schema.sql must define the csi_variance table.
Run  python -c "from server.db import init_db; from server.config import DB_PATH; init_db(DB_PATH)"
to create it.

Usage
-----
    python server/csi_ingest.py
    # or via systemd: basecamp-csi.service

Signal handling: SIGTERM / SIGINT trigger a clean shutdown.
"""
import logging
import os
import signal
import socket
import sys
import time
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.config import (
    CSI_UDP_HOST,
    CSI_UDP_PORT,
    DB_PATH,
    MOCK_HARDWARE,
)
from server.db import get_connection, init_db
from pipeline.csi_synthetic import (
    CSI_NULL_SUBCARRIERS,
    CSI_PILOT_SUBCARRIERS,
    csi_to_variance_signal,
    generate_synthetic_csi,
)

# ── Logging ──────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [csi_ingest] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("logs/csi_ingest.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("csi_ingest")

# ── Constants ─────────────────────────────────────────────────────────────────
PACKET_RATE = 100          # expected packets/second per node
DOWNSAMPLE_RATE = 20       # target sample rate stored in DB (Hz)
BUFFER_SECONDS = 1         # how many seconds of packets to accumulate before writing
PACKETS_PER_BUFFER = PACKET_RATE * BUFFER_SECONDS
VARIANCES_PER_BUFFER = DOWNSAMPLE_RATE * BUFFER_SECONDS  # 20 values per second written

N_SUBCARRIERS = 56
MOCK_BREATH_BPM = 14.0    # synthetic breathing rate used in mock mode
MOCK_NODES = ["node_01", "node_02"]
MOCK_CHUNK_SECONDS = 30   # generate this many seconds at a time in mock mode

_shutdown = False


# ── Packet parser ─────────────────────────────────────────────────────────────

def _valid_subcarrier_mask(n_subcarriers=N_SUBCARRIERS):
    exclude = set(CSI_NULL_SUBCARRIERS) | set(CSI_PILOT_SUBCARRIERS)
    return np.array([i not in exclude for i in range(n_subcarriers)], dtype=bool)


_VALID_MASK = _valid_subcarrier_mask()


def _packet_variance(csi_row):
    """Cross-subcarrier amplitude variance for one packet (valid subcarriers only)."""
    amp = np.abs(csi_row[_VALID_MASK])
    return float(np.var(amp))


def _parse_csikit(raw_bytes):
    """
    Attempt to parse a raw UDP payload using CSIKit.
    Returns complex array [n_subcarriers] or raises RuntimeError.
    """
    try:
        from csikit import CSIKit  # type: ignore
        kit = CSIKit()
        result = kit.read_bytes(raw_bytes)
        csi = np.array(result.csi_matrix, dtype=complex)
        if csi.ndim > 1:
            csi = csi[0]
        return csi
    except ImportError:
        raise RuntimeError("CSIKit not installed")
    except Exception as exc:
        raise RuntimeError(f"CSIKit parse error: {exc}")


def _parse_csv_line(line_str):
    """
    Parse an ESP32-CSI-Tool CSV line.

    Format: ...,[imag0,real0,imag1,real1,...] where the CSI bracket is the
    last field or can be found by scanning for '['.
    Handles both space-separated and comma-separated interiors.
    """
    bracket_start = line_str.find("[")
    bracket_end = line_str.rfind("]")
    if bracket_start == -1 or bracket_end == -1:
        raise ValueError("No bracket-delimited CSI field found")

    inner = line_str[bracket_start + 1 : bracket_end].strip()
    if not inner:
        raise ValueError("Empty CSI bracket")

    # Handle space-separated or comma-separated integers
    sep = "," if "," in inner else " "
    values = [int(v) for v in inner.split(sep) if v.strip()]
    if len(values) < 2 or len(values) % 2 != 0:
        raise ValueError(f"Unexpected value count: {len(values)}")

    n = len(values) // 2
    csi = np.array(
        [complex(values[2 * i + 1], values[2 * i]) for i in range(n)],
        dtype=complex,
    )
    return csi


def parse_csi_packet(raw_data, node_hint="unknown"):
    """
    Parse a raw CSI packet (bytes or str) into a complex array [n_subcarriers].

    Tries CSIKit first; falls back to the custom CSV parser.  Logs which path
    succeeded on the first call for each node.

    Args:
        raw_data: bytes or str from the UDP socket.
        node_hint: string used in log messages only.

    Returns:
        complex ndarray [n_subcarriers], or None if both parsers fail.
    """
    if isinstance(raw_data, bytes):
        text = raw_data.decode("utf-8", errors="replace")
    else:
        text = raw_data

    # Try CSIKit
    try:
        csi = _parse_csikit(raw_data if isinstance(raw_data, bytes) else raw_data.encode())
        return csi
    except RuntimeError as exc:
        if "not installed" not in str(exc):
            logger.debug("CSIKit failed for %s: %s — trying CSV parser", node_hint, exc)

    # Fall back to CSV parser
    try:
        return _parse_csv_line(text)
    except Exception as exc:
        logger.warning("CSV parser failed for %s: %s", node_hint, exc)
        return None


# ── DB writer ─────────────────────────────────────────────────────────────────

def _write_variance_batch(db_path, rows):
    """
    Insert a batch of (timestamp, node_id, variance_value) rows into csi_variance.
    rows: list of (str, str, float)
    """
    conn = get_connection(db_path)
    try:
        conn.executemany(
            "INSERT INTO csi_variance (timestamp, node_id, variance_value) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()
    except Exception as exc:
        logger.error("DB write failed: %s", exc)
    finally:
        conn.close()


# ── Real hardware path ────────────────────────────────────────────────────────

def _run_live(db_path):
    """Receive real UDP packets from ESP32 nodes and write variance to DB."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((CSI_UDP_HOST, CSI_UDP_PORT))
    sock.settimeout(1.0)
    logger.info("Listening on UDP %s:%d", CSI_UDP_HOST, CSI_UDP_PORT)

    # Per-source-IP packet buffer: { ip -> list of complex arrays }
    buffers = {}

    while not _shutdown:
        try:
            raw, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError as exc:
            if _shutdown:
                break
            logger.error("Socket error: %s", exc)
            time.sleep(0.1)
            continue

        src_ip = addr[0]
        node_id = f"node_{src_ip.replace('.', '_')}"

        csi = parse_csi_packet(raw, node_hint=node_id)
        if csi is None:
            continue

        # Ensure correct subcarrier count
        if len(csi) != N_SUBCARRIERS:
            csi_padded = np.zeros(N_SUBCARRIERS, dtype=complex)
            n = min(len(csi), N_SUBCARRIERS)
            csi_padded[:n] = csi[:n]
            csi = csi_padded

        if src_ip not in buffers:
            buffers[src_ip] = []
        buffers[src_ip].append(csi)

        # Once we have a full buffer, compute variance and write
        if len(buffers[src_ip]) >= PACKETS_PER_BUFFER:
            batch = np.stack(buffers[src_ip][:PACKETS_PER_BUFFER], axis=0)
            buffers[src_ip] = buffers[src_ip][PACKETS_PER_BUFFER:]

            variance_signal = csi_to_variance_signal(
                batch, downsample_rate=DOWNSAMPLE_RATE, packet_rate=PACKET_RATE
            )
            now_base = datetime.now(timezone.utc)
            dt_step = 1.0 / DOWNSAMPLE_RATE
            db_rows = [
                (
                    (now_base.replace(microsecond=0).isoformat() + f".{int(i * dt_step * 1e6):06d}Z"),
                    node_id,
                    float(v),
                )
                for i, v in enumerate(variance_signal)
            ]
            _write_variance_batch(db_path, db_rows)

    sock.close()
    logger.info("Live ingestion stopped.")


# ── Mock hardware path ────────────────────────────────────────────────────────

def _run_mock(db_path, run_seconds=None):
    """
    Generate synthetic CSI for mock hardware mode.

    run_seconds: if None, runs indefinitely until SIGTERM.
                 Set to a positive number for bounded test runs.
    """
    logger.info("MOCK_HARDWARE mode: generating synthetic CSI for %s", MOCK_NODES)
    rng = np.random.default_rng(42)
    elapsed = 0.0

    while not _shutdown:
        if run_seconds is not None and elapsed >= run_seconds:
            break

        chunk_rows = []
        base_ts = datetime.now(timezone.utc)

        for node_id in MOCK_NODES:
            # Slightly different breathing rates per node to simulate real variation
            breath_bpm = MOCK_BREATH_BPM + rng.uniform(-0.5, 0.5)
            csi_chunk, _ = generate_synthetic_csi(
                duration_seconds=MOCK_CHUNK_SECONDS,
                breathing_rate_bpm=breath_bpm,
                packet_rate=PACKET_RATE,
                n_subcarriers=N_SUBCARRIERS,
                snr_db=20,
                rng_seed=int(rng.integers(0, 2**32)),
            )
            variance_signal = csi_to_variance_signal(
                csi_chunk, downsample_rate=DOWNSAMPLE_RATE, packet_rate=PACKET_RATE
            )
            dt_step = 1.0 / DOWNSAMPLE_RATE
            for i, v in enumerate(variance_signal):
                ts_offset = timedelta(seconds=elapsed + i * dt_step)
                ts = (base_ts + ts_offset).isoformat().replace("+00:00", "Z")
                chunk_rows.append((ts, node_id, float(v)))

        _write_variance_batch(db_path, chunk_rows)
        logger.info("Mock: wrote %d variance rows for %s", len(chunk_rows), MOCK_NODES)

        elapsed += MOCK_CHUNK_SECONDS
        # Sleep MOCK_CHUNK_SECONDS in real time (pace the simulation)
        deadline = time.monotonic() + MOCK_CHUNK_SECONDS
        while time.monotonic() < deadline and not _shutdown:
            time.sleep(0.5)

    logger.info("Mock ingestion stopped (%.0f s elapsed).", elapsed)


# ── Entry point ───────────────────────────────────────────────────────────────

def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %s — shutting down.", signum)
    _shutdown = True


def main(db_path=None, run_seconds=None):
    global _shutdown
    _shutdown = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if db_path is None:
        db_path = DB_PATH

    init_db(db_path)
    logger.info("CSI ingest daemon starting (mock=%s, db=%s)", MOCK_HARDWARE, db_path)

    if MOCK_HARDWARE:
        _run_mock(db_path, run_seconds=run_seconds)
    else:
        _run_live(db_path)

    logger.info("CSI ingest daemon exited.")


if __name__ == "__main__":
    main()
