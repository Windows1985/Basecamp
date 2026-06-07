"""
Synthetic CSI generator for pipeline validation.

Generates realistic complex CSI matrices with known ground-truth breathing
rates and movement events so that the feature-extraction pipeline can be
verified against known answers before real hardware is available.

Mathematical basis
------------------
Each subcarrier amplitude is modulated at the breathing frequency with a
random per-subcarrier depth drawn from U(0.15, 0.45).  All depths are
strictly positive, which ensures that the cross-subcarrier variance signal
has a dominant component at the breathing frequency f_breath:

  Var_sc(amp[t, :]) ≈ Var(A_base)·(1 + 2·mean(depth)·sin(ωt)) + O(sin²(ωt))

The O(sin²(ωt)) harmonic is ~4–5× smaller than the fundamental, so the
bandpass filter cleanly selects the breathing frequency.
"""
import numpy as np

# Default ESP32 20 MHz mode subcarrier exclusion (configurable)
CSI_NULL_SUBCARRIERS = [0, 1, 2, 3, 27, 28, 29]
CSI_PILOT_SUBCARRIERS = [7, 21, 43]


def generate_synthetic_csi(
    duration_seconds,
    breathing_rate_bpm,
    movement_events=None,
    packet_rate=100,
    n_subcarriers=56,
    snr_db=20,
    movement_duration_seconds=2.0,
    rng_seed=None,
):
    """
    Generate a synthetic complex CSI matrix with embedded breathing and movement.

    Args:
        duration_seconds: Total recording duration.
        breathing_rate_bpm: True breathing rate to embed (ground truth).
        movement_events: List of timestamps (seconds) for movement bursts.
        packet_rate: CSI packets per second from the ESP32 (default 100).
        n_subcarriers: Number of subcarriers (default 56 for ESP32 20 MHz).
        snr_db: Amplitude SNR relative to the breathing-free baseline.
        movement_duration_seconds: Duration of each movement burst.
        rng_seed: Optional seed for reproducibility.

    Returns:
        csi_matrix : complex ndarray [n_packets, n_subcarriers]
        ground_truth : dict with true breathing rate, movement timestamps, etc.
    """
    rng = np.random.default_rng(rng_seed)
    movement_events = list(movement_events) if movement_events else []

    n_packets = int(duration_seconds * packet_rate)
    t = np.arange(n_packets) / float(packet_rate)
    f_breath = breathing_rate_bpm / 60.0

    # Per-subcarrier baseline amplitude (realistic gain variation across band)
    A_base = rng.uniform(1.0, 3.0, n_subcarriers)

    # Per-subcarrier modulation depth — ALL POSITIVE so variance oscillates at
    # exactly f_breath (not 2·f_breath, which happens with symmetric ± depths).
    depth = rng.uniform(0.15, 0.45, n_subcarriers)

    # Amplitude matrix: [n_packets × n_subcarriers]
    amp = A_base[None, :] * (
        1.0 + depth[None, :] * np.sin(2.0 * np.pi * f_breath * t[:, None])
    )

    # Random static carrier phase per subcarrier (represents static multipath)
    carrier_phase = rng.uniform(0.0, 2.0 * np.pi, n_subcarriers)
    csi = amp * np.exp(1j * carrier_phase[None, :])

    # Add complex Gaussian noise at the requested SNR
    signal_power = float(np.mean(amp ** 2))
    noise_power = signal_power / (10.0 ** (snr_db / 10.0))
    noise_std = np.sqrt(noise_power / 2.0)
    noise = noise_std * (
        rng.standard_normal((n_packets, n_subcarriers))
        + 1j * rng.standard_normal((n_packets, n_subcarriers))
    )
    csi = csi + noise

    # Movement events: broadband high-amplitude burst across all subcarriers
    burst_amp = float(np.mean(A_base)) * 5.0
    burst_samples = int(movement_duration_seconds * packet_rate)
    for event_time in movement_events:
        start = int(event_time * packet_rate)
        end = min(n_packets, start + burst_samples)
        if start >= n_packets:
            continue
        burst = burst_amp * (
            rng.standard_normal((end - start, n_subcarriers))
            + 1j * rng.standard_normal((end - start, n_subcarriers))
        )
        csi[start:end, :] += burst

    ground_truth = {
        "breathing_rate_bpm": float(breathing_rate_bpm),
        "breathing_rate_hz": float(f_breath),
        "movement_events": movement_events,
        "duration_seconds": int(duration_seconds),
        "packet_rate": int(packet_rate),
        "n_subcarriers": int(n_subcarriers),
        "snr_db": float(snr_db),
    }

    return csi, ground_truth


def compute_subcarrier_variance(
    csi_row,
    null_subcarriers=None,
    pilot_subcarriers=None,
):
    """
    Variance of CSI amplitudes across valid subcarriers for one packet.

    Null and pilot subcarriers carry no useful data and are excluded before
    computing the variance, which is the core of the breathing signal.

    Args:
        csi_row: complex array [n_subcarriers] for a single packet.
        null_subcarriers: indices to exclude (defaults to ESP32 20 MHz nulls).
        pilot_subcarriers: indices to exclude (defaults to ESP32 20 MHz pilots).

    Returns:
        float variance value.
    """
    if null_subcarriers is None:
        null_subcarriers = CSI_NULL_SUBCARRIERS
    if pilot_subcarriers is None:
        pilot_subcarriers = CSI_PILOT_SUBCARRIERS

    exclude = set(null_subcarriers) | set(pilot_subcarriers)
    n = len(csi_row)
    valid_idx = np.array([i for i in range(n) if i not in exclude], dtype=np.intp)
    amp = np.abs(csi_row[valid_idx])
    return float(np.var(amp))


def csi_to_variance_signal(
    csi_matrix,
    downsample_rate=20,
    packet_rate=100,
    null_subcarriers=None,
    pilot_subcarriers=None,
):
    """
    Convert a raw CSI matrix to a downsampled cross-subcarrier variance signal.

    This is the same reduction performed by the live ingestion daemon.  Keeping
    the function here means the test suite and the daemon share identical maths.

    Args:
        csi_matrix: complex array [n_packets, n_subcarriers].
        downsample_rate: output sample rate in Hz (default 20).
        packet_rate: input packet rate in Hz (default 100).
        null_subcarriers: null subcarrier indices to exclude.
        pilot_subcarriers: pilot subcarrier indices to exclude.

    Returns:
        variance_signal: float array at downsample_rate Hz.
    """
    if null_subcarriers is None:
        null_subcarriers = CSI_NULL_SUBCARRIERS
    if pilot_subcarriers is None:
        pilot_subcarriers = CSI_PILOT_SUBCARRIERS

    exclude = set(null_subcarriers) | set(pilot_subcarriers)
    n_subs = csi_matrix.shape[1]
    valid_idx = np.array([i for i in range(n_subs) if i not in exclude], dtype=np.intp)

    # Per-packet amplitude variance across valid subcarriers
    amp = np.abs(csi_matrix[:, valid_idx])         # [n_packets, n_valid]
    per_packet_var = np.var(amp, axis=1)            # [n_packets]

    # Downsample by block-averaging
    factor = packet_rate // downsample_rate
    if factor < 1:
        factor = 1
    n_out = len(per_packet_var) // factor
    trimmed = per_packet_var[: n_out * factor]
    variance_signal = trimmed.reshape(n_out, factor).mean(axis=1)

    return variance_signal
