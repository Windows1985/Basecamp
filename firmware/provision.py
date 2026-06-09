#!/usr/bin/env python3
"""
firmware/provision.py

Write node-specific config to the ESP32-S3's NVS partition without reflashing.
Flash the same firmware binary to both nodes, then provision each one separately.

Usage:
    python firmware/provision.py --port COM7 --node-id 1 \\
        --ssid RuView-24 --password YOUR_PASSWORD \\
        --target-ip 192.168.1.100 --target-port 5500

    python firmware/provision.py --port COM8 --node-id 2
    (SSID/password/IP are remembered from previous provision — only node-id changes)

Requirements:
    pip install esptool nvs-partition-gen
    (nvs-partition-gen is included with ESP-IDF; also installable standalone)
"""

import argparse
import csv
import os
import struct
import subprocess
import sys
import tempfile

# NVS partition address for ESP32-S3 with ESP32-CSI-Tool partition table.
# Verify against your partition table: idf.py partition-table
NVS_PARTITION_ADDRESS = "0x9000"
NVS_PARTITION_SIZE   = "0x6000"   # 24KB default NVS partition

# NVS namespace used by ESP32-CSI-Tool for tool-specific config.
# These keys map to the menuconfig entries the firmware reads at boot.
NVS_NAMESPACE = "csi_cfg"

# Keys written to NVS. The firmware reads these at boot and overrides
# the compiled-in Kconfig defaults if present.
# Key names must be ≤15 characters (NVS limit).
KEY_SSID        = "wifi_ssid"
KEY_PASSWORD    = "wifi_pass"
KEY_TARGET_IP   = "udp_ip"
KEY_TARGET_PORT = "udp_port"
KEY_NODE_ID     = "node_id"


def build_nvs_csv(entries: dict) -> str:
    """
    Build a CSV string in the format expected by nvs_partition_gen.py.
    Returns the CSV content as a string.
    """
    rows = [["key", "type", "encoding", "value"]]
    rows.append([NVS_NAMESPACE, "namespace", "", ""])
    for key, (enc, value) in entries.items():
        rows.append([key, "data", enc, str(value)])

    lines = []
    for row in rows:
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


def generate_nvs_binary(csv_content: str, output_path: str) -> None:
    """
    Call nvs_partition_gen.py to turn the CSV into a binary NVS partition.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        csv_path = f.name

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "esp_idf_nvs_partition_gen",
                "--input", csv_path,
                "--output", output_path,
                "--size", NVS_PARTITION_SIZE,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Try the alternative module name
            result = subprocess.run(
                [
                    sys.executable, "-c",
                    f"from nvs_partition_gen import nvs_part_gen; "
                    f"nvs_part_gen(['--input', '{csv_path}', '--output', '{output_path}', '--size', '{NVS_PARTITION_SIZE}'])"
                ],
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            print("Error generating NVS binary:")
            print(result.stderr)
            print()
            print("Make sure nvs_partition_gen is installed:")
            print("  pip install esp-idf-nvs-partition-gen")
            print("Or install ESP-IDF and use its tools.")
            sys.exit(1)
    finally:
        os.unlink(csv_path)


def flash_nvs(port: str, nvs_binary_path: str) -> None:
    """
    Flash the NVS binary partition to the device using esptool.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "esptool",
            "--chip", "esp32s3",
            "--port", port,
            "--baud", "460800",
            "--before", "default-reset",
            "--after", "hard-reset",
            "write-flash",
            "--flash-mode", "dio",
            "--flash-freq", "80m",
            NVS_PARTITION_ADDRESS, nvs_binary_path,
        ],
        capture_output=False,  # Show output in real time
    )
    if result.returncode != 0:
        print("Error flashing NVS partition.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Provision ESP32-S3 CSI node with WiFi credentials and network config.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full provision of Node 1
  python firmware/provision.py --port COM7 --node-id 1 \\
      --ssid RuView-24 --password secret \\
      --target-ip 192.168.1.100 --target-port 5500

  # Provision Node 2 — only change node-id (re-pass credentials)
  python firmware/provision.py --port COM8 --node-id 2 \\
      --ssid RuView-24 --password secret \\
      --target-ip 192.168.1.100 --target-port 5500

  # Cate School hotspot — update target IP only (Pi hotspot changes the subnet)
  python firmware/provision.py --port COM7 --node-id 1 \\
      --ssid Basecamp-Pi --password secret \\
      --target-ip 10.42.0.1 --target-port 5500
        """,
    )
    parser.add_argument("--port", required=True,
        help="Serial port. COM7 (Windows), /dev/ttyUSB0 (Linux), /dev/cu.usbserial-* (Mac)")
    parser.add_argument("--node-id", required=True, type=int, choices=[1, 2],
        help="Node ID: 1 (left bedside) or 2 (right ledge)")
    parser.add_argument("--ssid", required=True,
        help="WiFi SSID. Use RuView-24 at home, Basecamp-Pi at Cate.")
    parser.add_argument("--password", required=True,
        help="WiFi password")
    parser.add_argument("--target-ip", required=True,
        help="Pi IP address for UDP stream. Check router DHCP or use 10.42.0.1 for Pi hotspot.")
    parser.add_argument("--target-port", type=int, default=5500,
        help="UDP port (default: 5500, matches server/config.py)")
    parser.add_argument("--dry-run", action="store_true",
        help="Print the NVS CSV and exit without flashing")

    args = parser.parse_args()

    # Validate
    parts = args.target_ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        print(f"Error: invalid IP address: {args.target_ip}")
        sys.exit(1)

    entries = {
        KEY_SSID:        ("string", args.ssid),
        KEY_PASSWORD:    ("string", args.password),
        KEY_TARGET_IP:   ("string", args.target_ip),
        KEY_TARGET_PORT: ("u16",    args.target_port),
        KEY_NODE_ID:     ("u8",     args.node_id),
    }

    csv_content = build_nvs_csv(entries)

    print("NVS config to be written:")
    print(f"  Node ID:     {args.node_id}")
    print(f"  SSID:        {args.ssid}")
    print(f"  Password:    {'*' * len(args.password)}")
    print(f"  Target IP:   {args.target_ip}")
    print(f"  Target port: {args.target_port}")
    print(f"  Port:        {args.port}")
    print()

    if args.dry_run:
        print("--- NVS CSV (dry run) ---")
        print(csv_content)
        return

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        nvs_bin_path = f.name

    try:
        print("Generating NVS binary...")
        generate_nvs_binary(csv_content, nvs_bin_path)

        print(f"Flashing NVS partition to {args.port}...")
        print("(Device does not need to be in download mode for NVS-only flash)")
        print()
        flash_nvs(args.port, nvs_bin_path)

        print()
        print(f"Node {args.node_id} provisioned successfully.")
        print(f"Power-cycle the ESP32 and verify in serial monitor:")
        print(f"  idf.py monitor --port {args.port}")
        print(f"Expected: 'CSI streaming active -> {args.target_ip}:{args.target_port}'")
    finally:
        if os.path.exists(nvs_bin_path):
            os.unlink(nvs_bin_path)


if __name__ == "__main__":
    main()
