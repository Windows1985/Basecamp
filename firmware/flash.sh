#!/usr/bin/env bash
# firmware/flash.sh
# Flash ESP32-CSI-Tool firmware to Node 1 or Node 2.
# Usage: ./flash.sh <node_id> <port>
# Example (Linux/Mac): ./flash.sh 1 /dev/ttyUSB0
# Example (WSL):       ./flash.sh 2 /dev/ttyUSB1
# Example (Windows Git Bash): ./flash.sh 1 COM7
#
# Prerequisites: pip install esptool
# Run from repo root.

set -e

NODE_ID=$1
PORT=$2

if [[ -z "$NODE_ID" || -z "$PORT" ]]; then
  echo "Usage: ./flash.sh <node_id> <port>"
  echo "  node_id: 1 or 2"
  echo "  port:    /dev/ttyUSB0 (Linux) | /dev/cu.usbserial-* (Mac) | COM7 (Windows)"
  exit 1
fi

if [[ "$NODE_ID" != "1" && "$NODE_ID" != "2" ]]; then
  echo "Error: node_id must be 1 or 2"
  exit 1
fi

BUILD_DIR="firmware/active_sta/build"

if [[ ! -f "$BUILD_DIR/esp32-csi-node.bin" ]]; then
  echo "Error: build not found at $BUILD_DIR"
  echo "Run 'idf.py build' from firmware/active_sta/ first."
  exit 1
fi

echo "Flashing Node $NODE_ID to $PORT..."
echo "Make sure the ESP32-S3 is in download mode: hold BOOT, press RESET, release BOOT."
echo ""

python -m esptool \
  --chip esp32s3 \
  --port "$PORT" \
  --baud 460800 \
  --before default-reset \
  --after hard-reset \
  write-flash \
  --flash-mode dio \
  --flash-freq 80m \
  --flash-size 16MB \
  0x0     "$BUILD_DIR/bootloader/bootloader.bin" \
  0x8000  "$BUILD_DIR/partition_table/partition-table.bin" \
  0x10000 "$BUILD_DIR/esp32-csi-node.bin"

echo ""
echo "Flash complete. Now provision Node $NODE_ID:"
echo "  python firmware/provision.py --port $PORT --node-id $NODE_ID --ssid RuView-24 --password YOUR_PASSWORD --target-ip YOUR_PI_IP"
