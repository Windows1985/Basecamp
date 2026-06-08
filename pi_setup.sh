#!/bin/bash
# ==============================================================================
# Basecamp — Raspberry Pi 4 setup script
# Run as: sudo bash pi_setup.sh
# Target: Raspberry Pi OS Lite 64-bit (Debian Bookworm), user "pi"
# Repo must already be cloned to /home/pi/basecamp before running.
# ==============================================================================
set -euo pipefail

# ── Constants ──────────────────────────────────────────────────────────────────
BASECAMP_DIR="/home/pi/basecamp"
VENV_DIR="${BASECAMP_DIR}/venv"
PYTHON="${VENV_DIR}/bin/python3"
PIP="${VENV_DIR}/bin/pip"
SCRIPT_START=$(date +%s)

# ── Output helpers ─────────────────────────────────────────────────────────────
step()  { printf '\n\033[1;34m━━━ Step %s: %s ━━━\033[0m\n' "$1" "$2"; }
ok()    { printf '  \033[0;32m✓ %s\033[0m\n' "$1"; }
warn()  { printf '  \033[1;33m⚠ %s\033[0m\n' "$1"; }
die()   { printf '\n\033[0;31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }
banner() {
    printf '\n\033[1;36m'
    printf '%s\n' "═══════════════════════════════════════"
    printf '%s\n' "$1"
    printf '%s\n' "═══════════════════════════════════════"
    printf '\033[0m'
}

# ── Pre-flight checks ──────────────────────────────────────────────────────────
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        die "This script must be run as root.  Use: sudo bash pi_setup.sh"
    fi
    ok "Running as root"
}

check_raspberry_pi() {
    if ! grep -qi "raspberry pi" /proc/cpuinfo 2>/dev/null; then
        die "This script must be run on a Raspberry Pi (not detected in /proc/cpuinfo)."
    fi
    local model
    model=$(grep -m1 "Model" /proc/cpuinfo | cut -d: -f2 | xargs || true)
    ok "Raspberry Pi detected: ${model}"
}

check_repo() {
    if [ ! -d "${BASECAMP_DIR}" ]; then
        die "Repository not found at ${BASECAMP_DIR}.  Clone it first:
  git clone <repo-url> ${BASECAMP_DIR}"
    fi
    if [ ! -f "${BASECAMP_DIR}/requirements.txt" ]; then
        die "requirements.txt not found in ${BASECAMP_DIR}.  Is the repo complete?"
    fi
    ok "Repository found at ${BASECAMP_DIR}"
}

find_boot_config() {
    # Bookworm uses /boot/firmware/config.txt; older releases use /boot/config.txt
    if [ -f /boot/firmware/config.txt ]; then
        CONFIG_FILE="/boot/firmware/config.txt"
    elif [ -f /boot/config.txt ]; then
        CONFIG_FILE="/boot/config.txt"
    else
        die "Cannot find boot config file at /boot/firmware/config.txt or /boot/config.txt"
    fi
    ok "Boot config: ${CONFIG_FILE}"
}

# Append a line to a file if it is not already present (exact match)
append_if_missing() {
    local line="$1"
    local file="$2"
    if ! grep -qxF "${line}" "${file}"; then
        printf '%s\n' "${line}" >> "${file}"
        ok "Added to ${file}: ${line}"
    else
        printf '  Already present: %s\n' "${line}"
    fi
}

# ── Step 1: System update and packages ────────────────────────────────────────
step 1 "System update and packages"

step1_packages() {
    apt-get update -qq
    apt-get upgrade -y -qq
    apt-get install -y -qq \
        python3-pip python3-venv git \
        python3-pygame python3-pil python3-numpy python3-scipy \
        libportaudio2 portaudio19-dev ffmpeg \
        python3-sdnotify i2c-tools
    ok "System packages installed"
}

# ── Step 2: Python venv and dependencies ──────────────────────────────────────
step 2 "Python virtual environment and pip dependencies"

step2_venv() {
    if [ ! -d "${VENV_DIR}" ]; then
        sudo -u pi python3 -m venv "${VENV_DIR}"
        ok "Created venv at ${VENV_DIR}"
    else
        ok "Venv already exists at ${VENV_DIR}"
    fi

    sudo -u pi "${PIP}" install --upgrade pip -q
    sudo -u pi "${PIP}" install -q -r "${BASECAMP_DIR}/requirements.txt"
    ok "requirements.txt installed"

    sudo -u pi "${PIP}" install -q \
        RPi.GPIO gpiozero spidev luma.lcd smbus2 \
        scd4x-python sgp40 sounddevice pyserial \
        adafruit-circuitpython-bh1750
    ok "Pi hardware libraries installed"
}

# ── Step 3: /boot/config.txt ──────────────────────────────────────────────────
step 3 "Boot config (${CONFIG_FILE})"

step3_boot_config() {
    append_if_missing "dtparam=i2c_arm=on"  "${CONFIG_FILE}"
    append_if_missing "dtparam=i2s=on"      "${CONFIG_FILE}"
    append_if_missing "dtparam=spi=on"      "${CONFIG_FILE}"
    append_if_missing "dtoverlay=disable-bt" "${CONFIG_FILE}"

    # Enable hardware serial, disable login shell over serial
    if command -v raspi-config > /dev/null 2>&1; then
        raspi-config nonint do_serial_hw 0  || warn "do_serial_hw failed (non-fatal)"
        raspi-config nonint do_serial_cons 1 || warn "do_serial_cons failed (non-fatal)"
        ok "Serial port: hardware enabled, login shell disabled"
    else
        warn "raspi-config not found — configure serial manually"
    fi
}

# ── Step 4: Enable I2C and SPI ────────────────────────────────────────────────
step 4 "Enable I2C and SPI via raspi-config"

step4_interfaces() {
    if command -v raspi-config > /dev/null 2>&1; then
        raspi-config nonint do_i2c 0 || warn "do_i2c failed (non-fatal)"
        raspi-config nonint do_spi 0 || warn "do_spi failed (non-fatal)"
        ok "I2C enabled"
        ok "SPI enabled"
    else
        warn "raspi-config not found — enable I2C/SPI manually or via boot config"
    fi
}

# ── Step 5: Verify I2C devices ────────────────────────────────────────────────
step 5 "I2C bus scan (verify sensor wiring)"

step5_i2c_scan() {
    if ! command -v i2cdetect > /dev/null 2>&1; then
        warn "i2cdetect not found — cannot scan I2C bus"
        return
    fi

    printf '\nI2C bus 1 scan:\n'
    local i2c_output
    i2c_output=$(i2cdetect -y 1 2>&1) || true
    printf '%s\n\n' "${i2c_output}"

    # Expected addresses from server/config.py and hardware/wiring.md
    local -A expected=(
        ["0x23"]="BH1750 (light sensor)"
        ["0x44"]="SHT40 (temp/humidity)"
        ["0x59"]="SGP40 (VOC)"
        ["0x62"]="SCD40 (CO2)"
    )

    for addr in "23" "44" "59" "62"; do
        if printf '%s' "${i2c_output}" | grep -qi " ${addr}"; then
            ok "Found 0x${addr} (${expected[0x${addr}]})"
        else
            warn "NOT found: 0x${addr} (${expected[0x${addr}]}) — check wiring"
        fi
    done
}

# ── Step 6: Create directories ────────────────────────────────────────────────
step 6 "Directories and permissions"

step6_directories() {
    mkdir -p "${BASECAMP_DIR}/data/audio"
    mkdir -p "${BASECAMP_DIR}/logs"
    chown -R pi:pi "${BASECAMP_DIR}/data"
    chown -R pi:pi "${BASECAMP_DIR}/logs"
    # Ensure log directory gitkeep is preserved
    if [ ! -f "${BASECAMP_DIR}/logs/.gitkeep" ]; then
        touch "${BASECAMP_DIR}/logs/.gitkeep"
        chown pi:pi "${BASECAMP_DIR}/logs/.gitkeep"
    fi
    ok "data/ and logs/ ready, owned by pi:pi"
}

# ── Step 7: Initialise database ───────────────────────────────────────────────
step 7 "Database initialisation"

step7_database() {
    (
        cd "${BASECAMP_DIR}"
        sudo -u pi "${PYTHON}" -c \
            "from server.db import init_db, migrate_schema; \
             from server.config import DB_PATH; \
             init_db(DB_PATH); \
             migrate_schema(DB_PATH); \
             print('  DB path:', DB_PATH)"
    )

    local db_path="${BASECAMP_DIR}/data/basecamp.db"
    if [ -f "${db_path}" ]; then
        ok "Database created: ${db_path}"
    else
        warn "Database file not found at expected path — check DB_PATH in server/config.py"
    fi
}

# ── Step 8: Systemd services ──────────────────────────────────────────────────
step 8 "Systemd service installation"

step8_services() {
    local svc_src="${BASECAMP_DIR}/systemd"
    if [ ! -d "${svc_src}" ]; then
        warn "systemd/ directory not found — skipping service install"
        return
    fi

    # Copy service files
    for f in "${svc_src}"/*.service; do
        [ -f "${f}" ] || continue
        cp "${f}" /etc/systemd/system/
        ok "Copied: $(basename "${f}")"
    done

    # Update ExecStart to use the venv Python
    for f in /etc/systemd/system/basecamp-*.service; do
        [ -f "${f}" ] || continue
        sed -i "s|/usr/bin/python3|${PYTHON}|g" "${f}"
    done
    ok "Service files updated to use venv Python (${PYTHON})"

    systemctl daemon-reload

    # Enable services (skip any that aren't present)
    local services=(
        basecamp-logger
        basecamp-presence
        basecamp-audio
        basecamp-csi-ingest
        basecamp-sleepmode
    )
    for svc in "${services[@]}"; do
        if [ -f "/etc/systemd/system/${svc}.service" ]; then
            systemctl enable "${svc}"
            ok "Enabled (will start after reboot): ${svc}"
        else
            printf '  Skipped (no service file): %s\n' "${svc}"
        fi
    done

    warn "Services are NOT started yet — reboot first (see final instructions)"
}

# ── Step 9: Hotspot reminder ───────────────────────────────────────────────────
step 9 "Hotspot configuration note"

step9_hotspot_note() {
    if [ -f "${BASECAMP_DIR}/pi_setup_hotspot.sh" ]; then
        ok "pi_setup_hotspot.sh is present in the repo"
    fi
    printf '
  At Cate School (no local router access):
    sudo bash %s/pi_setup_hotspot.sh
  This turns the Pi into an access point on wlan0 (SSID: Basecamp-Node)
  and routes internet via eth0.  Do NOT run at home.\n' "${BASECAMP_DIR}"
}

# ── Step 10: Router reminder ───────────────────────────────────────────────────
step 10 "Router configuration reminder"

step10_router() {
banner "ROUTER SETUP REQUIRED (home network)"
cat << 'EOF'
Log into router at 192.168.50.1
Create new 2.4GHz SSID: RuView-24
Settings:
  Mode: N only (not AX or BE)
  Channel width: 20MHz
  MU-MIMO: disabled
  Beamforming: disabled
  BSS Colouring: disabled
  Airtime Fairness: disabled
  Smart Connect: disabled
  Band Steering: disabled
ESP32s connect to RuView-24
Pi connects via ethernet only
EOF
printf '\033[1;36m%s\033[0m\n' "═══════════════════════════════════════"
}

# ── Step 11: SCD40 calibration reminder ───────────────────────────────────────
step 11 "SCD40 calibration reminder"

step11_scd40() {
banner "SCD40 CALIBRATION REQUIRED"
cat << 'EOF'
Before first overnight run:
1. Place Pi near an open window or outside
2. Run: python3 server/calibrate_scd40.py
3. Wait 3 minutes for reading to stabilise
4. Confirm reading is between 400-450ppm
If reading is outside this range the sensor
may be a clone — check the chip markings.
EOF
printf '\033[1;36m%s\033[0m\n' "═══════════════════════════════════════"
}

# ── Step 12: MOCK_HARDWARE reminder ───────────────────────────────────────────
step 12 "MOCK_HARDWARE flag"

step12_mock_hardware() {
    local cfg="${BASECAMP_DIR}/server/config.py"
    if grep -q "MOCK_HARDWARE = True" "${cfg}"; then
        warn "MOCK_HARDWARE is still True in server/config.py"
        warn "Set MOCK_HARDWARE = False before running services on the Pi:"
        printf '  sed -i "s/MOCK_HARDWARE = True/MOCK_HARDWARE = False/" %s\n' "${cfg}"
    else
        ok "MOCK_HARDWARE is already False"
    fi
}

# ── Step 13: Final summary ─────────────────────────────────────────────────────
step 13 "Setup complete"

step13_summary() {
banner "BASECAMP SETUP COMPLETE"
cat << 'EOF'
Next steps:
1. Reboot: sudo reboot
2. After reboot verify services: systemctl status basecamp-*
3. Flash ESP32s and connect to RuView-24
4. Run SCD40 calibration (see above)
5. Run SGP40 burn-in: leave running 24h before trusting VOC readings
6. Check logs: tail -f /home/pi/basecamp/logs/*.log
7. Access morning log: http://<pi-ip>:5000
8. Access dashboard: http://<pi-ip>:5000/dashboard
EOF
printf '\033[1;36m%s\033[0m\n' "═══════════════════════════════════════"

    local script_end elapsed mins secs
    script_end=$(date +%s)
    elapsed=$((script_end - SCRIPT_START))
    mins=$((elapsed / 60))
    secs=$((elapsed % 60))
    printf '\nTotal time: %dm %ds\n' "${mins}" "${secs}"
}

# ── Main ───────────────────────────────────────────────────────────────────────
main() {
    printf '\033[1;37m'
    printf '%s\n' "══════════════════════════════════════════════"
    printf '%s\n' " Basecamp Pi Setup"
    printf '%s\n' "══════════════════════════════════════════════"
    printf '\033[0m'

    check_root
    check_raspberry_pi
    check_repo
    find_boot_config

    step1_packages
    step2_venv
    step3_boot_config
    step4_interfaces
    step5_i2c_scan
    step6_directories
    step7_database
    step8_services
    step9_hotspot_note
    step10_router
    step11_scd40
    step12_mock_hardware
    step13_summary
}

main "$@"
