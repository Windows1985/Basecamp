"""
Audio chunker daemon — records from INMP441 I2S mic in 30-second chunks,
classifies each chunk as silence/ambient/snore, and persists to DB + disk.
"""
import os
import sys
import signal
import threading
import time
import logging
import logging.handlers
import tempfile
import subprocess
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server.config import (
    DB_PATH,
    AUDIO_SAMPLE_RATE,
    AUDIO_CHUNK_SECONDS,
    SILENCE_THRESHOLD,
    SNORE_THRESHOLD,
    SNORE_FREQ_LOW,
    SNORE_FREQ_HIGH,
    MOCK_HARDWARE,
)
from server.db import init_db, get_connection

# ---------------------------------------------------------------------------
# Hardware imports
# ---------------------------------------------------------------------------
try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False

try:
    import soundfile as sf
    _SF_AVAILABLE = True
except ImportError:
    _SF_AVAILABLE = False

try:
    from scipy.io import wavfile as _wavfile
    from scipy.signal import butter, sosfilt
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)
_handler = logging.handlers.RotatingFileHandler(
    "logs/audio.log", maxBytes=5 * 1024 * 1024, backupCount=3
)
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_stream = logging.StreamHandler()
_stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("audio")
log.setLevel(logging.INFO)
log.addHandler(_handler)
log.addHandler(_stream)

AUDIO_DIR = "data/audio"

# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _rms(arr):
    return float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))


def _snore_band_rms(arr, sample_rate):
    """Bandpass-filter arr to snore band and return RMS."""
    if _SCIPY_AVAILABLE:
        nyq = sample_rate / 2.0
        low  = SNORE_FREQ_LOW  / nyq
        high = SNORE_FREQ_HIGH / nyq
        low  = max(1e-4, min(low, 0.9999))
        high = max(low + 1e-4, min(high, 0.9999))
        sos = butter(4, [low, high], btype="band", output="sos")
        filtered = sosfilt(sos, arr.astype(np.float64))
        return float(np.sqrt(np.mean(filtered ** 2)))
    # Fallback: crude energy in frequency bins via FFT
    spectrum = np.abs(np.fft.rfft(arr.astype(np.float64)))
    freqs    = np.fft.rfftfreq(len(arr), 1.0 / sample_rate)
    mask     = (freqs >= SNORE_FREQ_LOW) & (freqs <= SNORE_FREQ_HIGH)
    if not np.any(mask):
        return 0.0
    return float(np.sqrt(np.mean(spectrum[mask] ** 2))) / len(arr)


def _classify(arr, sample_rate):
    """Returns ('silence'|'ambient'|'snore', band_rms)."""
    # Normalise 32-bit int to float [-1, 1] for threshold comparison
    if arr.dtype in (np.int32, np.int16):
        scale = float(np.iinfo(arr.dtype).max)
        farr  = arr.astype(np.float64) / scale
    else:
        farr = arr.astype(np.float64)

    chunk_rms = float(np.sqrt(np.mean(farr ** 2)))
    if chunk_rms < SILENCE_THRESHOLD:
        return "silence", 0.0

    band_rms = _snore_band_rms(farr, sample_rate)
    if band_rms >= SNORE_THRESHOLD:
        return "snore", band_rms
    return "ambient", band_rms


def _ffmpeg_available():
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except Exception:
        return False


_FFMPEG = None


def _save_audio(arr, sample_rate, ts_str, tier):
    """
    Save chunk as opus via ffmpeg, or .npz fallback.
    Returns the saved file path.
    """
    global _FFMPEG
    if _FFMPEG is None:
        _FFMPEG = _ffmpeg_available()

    os.makedirs(AUDIO_DIR, exist_ok=True)
    bitrate = "96k" if tier == "snore" else "32k"

    if _FFMPEG:
        opus_path = os.path.join(AUDIO_DIR, f"{ts_str}_{tier}.opus")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            if _SF_AVAILABLE:
                sf.write(tmp_path, arr, sample_rate, subtype="PCM_32")
            elif _SCIPY_AVAILABLE:
                _wavfile.write(tmp_path, sample_rate, arr)
            else:
                np.save(tmp_path.replace(".wav", ".npy"), arr)
                raise RuntimeError("No WAV writer available")

            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", tmp_path,
                    "-c:a", "libopus", "-b:a", bitrate,
                    opus_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return opus_path
        except Exception as e:
            log.error(f"ffmpeg encode failed: {e} — falling back to npz")
            raise
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # npz fallback
    npz_path = os.path.join(AUDIO_DIR, f"{ts_str}_{tier}.npz")
    np.savez_compressed(npz_path, audio=arr, sample_rate=np.array(sample_rate))
    return npz_path


# ---------------------------------------------------------------------------
# Mock audio generator
# ---------------------------------------------------------------------------
_chunk_counter = 0


def _generate_mock_chunk(sample_rate, chunk_seconds):
    global _chunk_counter
    import random

    n_samples = sample_rate * chunk_seconds
    _chunk_counter += 1
    roll = random.random()

    if roll < 0.6:
        # Silence
        arr = np.random.normal(0, 1e-6, n_samples)
    elif roll < 0.85:
        # Breathing: 0.25 Hz sine, low amplitude
        t   = np.linspace(0, chunk_seconds, n_samples)
        arr = 0.008 * np.sin(2 * np.pi * 0.25 * t) + np.random.normal(0, 0.002, n_samples)
    else:
        # Snoring: bandlimited noise in 60-500 Hz, higher amplitude
        noise = np.random.normal(0, 1.0, n_samples)
        if _SCIPY_AVAILABLE:
            nyq  = sample_rate / 2.0
            sos  = butter(4, [60 / nyq, 500 / nyq], btype="band", output="sos")
            arr  = sosfilt(sos, noise) * 0.15
        else:
            arr = noise * 0.05

    return arr.astype(np.float64)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _write_chunk_row(ts, tier, file_path, duration_seconds):
    try:
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                "INSERT INTO audio_chunks (timestamp, tier, duration_seconds, file_path) VALUES (?, ?, ?, ?)",
                (ts, tier, duration_seconds, file_path),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log.error(f"DB write audio_chunk failed: {e}")


def _write_possible_apnea(ts):
    try:
        conn = get_connection(DB_PATH)
        try:
            conn.execute(
                "INSERT INTO radar_events (timestamp, event_type, presence, still_distance, moving_distance) VALUES (?, ?, ?, ?, ?)",
                (ts, "possible_apnea", None, None, None),
            )
            conn.commit()
        finally:
            conn.close()
        log.warning(f"Possible apnea flagged at {ts}")
    except Exception as e:
        log.error(f"DB write apnea event failed: {e}")


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------

def _find_i2s_device():
    if not _SD_AVAILABLE:
        return None
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0 and "i2s" in d["name"].lower():
                return i
        return None  # fall back to default
    except Exception:
        return None


def _record_chunk(device, sample_rate, chunk_seconds):
    n_samples = sample_rate * chunk_seconds
    arr = sd.rec(
        n_samples,
        samplerate=sample_rate,
        channels=1,
        dtype="int32",
        device=device,
        blocking=True,
    )
    return arr[:, 0]  # flatten to 1-D


# ---------------------------------------------------------------------------
# Main daemon
# ---------------------------------------------------------------------------
_running        = True
_finish_chunk   = False


def _handle_sigterm(signum, frame):
    global _running, _finish_chunk
    log.info("SIGTERM received — will stop after current chunk")
    _running      = False
    _finish_chunk = True


def run():
    global _running
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle_sigterm)

    init_db(DB_PATH)
    os.makedirs(AUDIO_DIR, exist_ok=True)

    if MOCK_HARDWARE or not _SD_AVAILABLE:
        device_name = "MOCK"
        device_id   = None
        log.info(
            f"Audio chunker started — MOCK mode  sr={AUDIO_SAMPLE_RATE}  chunk={AUDIO_CHUNK_SECONDS}s"
        )
        print(
            f"Audio chunker started — MOCK mode  sr={AUDIO_SAMPLE_RATE}  chunk={AUDIO_CHUNK_SECONDS}s"
        )
    else:
        device_id = _find_i2s_device()
        try:
            device_info = sd.query_devices(device_id)
            device_name = device_info["name"]
        except Exception:
            device_name = "default"
        log.info(
            f"Audio chunker started — device='{device_name}'  "
            f"sr={AUDIO_SAMPLE_RATE}  chunk={AUDIO_CHUNK_SECONDS}s"
        )
        print(
            f"Audio chunker started — device='{device_name}'  "
            f"sr={AUDIO_SAMPLE_RATE}  chunk={AUDIO_CHUNK_SECONDS}s"
        )

    prev_tier = None

    while _running:
        try:
            # --- Capture / generate chunk ------------------------------------
            if MOCK_HARDWARE or not _SD_AVAILABLE:
                arr = _generate_mock_chunk(AUDIO_SAMPLE_RATE, AUDIO_CHUNK_SECONDS)
            else:
                while True:
                    try:
                        arr = _record_chunk(device_id, AUDIO_SAMPLE_RATE, AUDIO_CHUNK_SECONDS)
                        break
                    except Exception as e:
                        log.error(f"Audio capture failed: {e} — retrying in 5s")
                        time.sleep(5)
                        if not _running:
                            return

            ts_str = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            ts_iso = datetime.utcnow().isoformat()

            # --- Classify ----------------------------------------------------
            tier, _ = _classify(arr, AUDIO_SAMPLE_RATE)

            # --- Apnea check -------------------------------------------------
            if tier == "silence" and prev_tier == "snore":
                _write_possible_apnea(ts_iso)

            # --- Persist -----------------------------------------------------
            if tier == "silence":
                _write_chunk_row(ts_iso, "silence", None, AUDIO_CHUNK_SECONDS)
                log.debug(f"Chunk {ts_str}: silence")
            else:
                try:
                    file_path = _save_audio(arr, AUDIO_SAMPLE_RATE, ts_str, tier)
                except Exception as e:
                    log.error(f"Audio save failed: {e} — saving npz fallback")
                    try:
                        npz_path = os.path.join(AUDIO_DIR, f"{ts_str}_{tier}.npz")
                        np.savez_compressed(npz_path, audio=arr, sample_rate=np.array(AUDIO_SAMPLE_RATE))
                        file_path = npz_path
                    except Exception as e2:
                        log.error(f"npz fallback also failed: {e2}")
                        file_path = None
                _write_chunk_row(ts_iso, tier, file_path, AUDIO_CHUNK_SECONDS)
                log.debug(f"Chunk {ts_str}: {tier}  file={file_path}")

            prev_tier = tier

        except Exception as e:
            log.error(f"Unhandled error in audio loop: {e}")
            time.sleep(5)

    log.info("Audio chunker stopped")


if __name__ == "__main__":
    run()
