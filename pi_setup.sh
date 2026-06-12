#!/bin/bash
# ==============================================================================
# Basecamp -- Raspberry Pi 4 setup script
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
        warn "raspi-config not found -- configure serial manually"
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
        warn "raspi-config not found -- enable I2C/SPI manually or via boot config"
    fi
}

# ── Step 5: Verify I2C devices ────────────────────────────────────────────────
step 5 "I2C bus scan (verify sensor wiring)"

step5_i2c_scan() {
    if ! command -v i2cdetect > /dev/null 2>&1; then
        warn "i2cdetect not found -- cannot scan I2C bus"
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
            warn "NOT found: 0x${addr} (${expected[0x${addr}]}) -- check wiring"
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
        warn "Database file not found at expected path -- check DB_PATH in server/config.py"
    fi
}

# ── Step 8: Systemd services ──────────────────────────────────────────────────
step 8 "Systemd service installation"

step8_services() {
    local svc_src="${BASECAMP_DIR}/systemd"
    if [ ! -d "${svc_src}" ]; then
        warn "systemd/ directory not found -- skipping service install"
        return
    fi

    # Copy service files
    for f in "${svc_src}"/*.service; do
        [ -f "${f}" ] || continue
        cp "${f}" /etc/systemd/system/
        ok "Copied: $(basename "${f}")"
    done

    # Copy timer files
    for f in "${svc_src}"/*.timer; do
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

    # Ensure the crash-notification template service is in place.
    # Do NOT enable or start it directly -- systemd instantiates it via OnFailure.
    sudo cp "${svc_src}/basecamp-notify@.service" /etc/systemd/system/ 2>/dev/null || true

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

    # Enable timers (basecamp-backup.service runs only via its timer)
    if [ -f "/etc/systemd/system/basecamp-backup.timer" ]; then
        systemctl enable basecamp-backup.timer
        systemctl start basecamp-backup.timer
        ok "Enabled and started: basecamp-backup.timer"
    else
        printf '  Skipped (no timer file): basecamp-backup.timer\n'
    fi

    warn "Services are NOT started yet -- reboot first (see final instructions)"
}

# ── Step 9: Hotspot setup (canonical) ─────────────────────────────────────────
step 9 "Hotspot AP setup (wlan0 = ESP32 nodes, eth0 = internet)"

# Configuration
AP_SSID="Basecamp-Node"
AP_PASS="basecamp2024"
AP_CHANNEL="6"
AP_IP="192.168.4.1"
DHCP_RANGE_START="192.168.4.2"
DHCP_RANGE_END="192.168.4.20"
DHCP_NETMASK="255.255.255.0"

step9_hotspot() {
    apt-get install -y -qq hostapd dnsmasq iptables-persistent
    ok "hostapd, dnsmasq, iptables-persistent installed"

    systemctl stop wpa_supplicant || true
    systemctl disable wpa_supplicant || true
    ok "wpa_supplicant disabled"

    DHCPCD_CONF="/etc/dhcpcd.conf"
    DHCPCD_MARKER="# Basecamp hotspot -- wlan0 static"
    if ! grep -qF "${DHCPCD_MARKER}" "${DHCPCD_CONF}" 2>/dev/null; then
        cat >> "${DHCPCD_CONF}" << EOF

${DHCPCD_MARKER}
interface wlan0
    static ip_address=${AP_IP}/24
    nohook wpa_supplicant
EOF
        ok "Added wlan0 static config to ${DHCPCD_CONF}"
    else
        ok "wlan0 static config already present"
    fi

    cat > /etc/hostapd/hostapd.conf << EOF
interface=wlan0
driver=nl80211
ssid=${AP_SSID}
hw_mode=g
channel=${AP_CHANNEL}
ieee80211n=1
wmm_enabled=0
ht_capab=[HT20]
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${AP_PASS}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
country_code=US
EOF
    ok "Written /etc/hostapd/hostapd.conf (SSID: ${AP_SSID}, channel ${AP_CHANNEL})"

    HOSTAPD_DEFAULT="/etc/default/hostapd"
    if grep -q "^#DAEMON_CONF" "${HOSTAPD_DEFAULT}" 2>/dev/null; then
        sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' "${HOSTAPD_DEFAULT}"
    elif ! grep -q "^DAEMON_CONF" "${HOSTAPD_DEFAULT}" 2>/dev/null; then
        printf 'DAEMON_CONF="/etc/hostapd/hostapd.conf"\n' >> "${HOSTAPD_DEFAULT}"
    fi
    systemctl unmask hostapd
    ok "hostapd configured"

    cat > /etc/dnsmasq.d/basecamp-hotspot.conf << EOF
# Basecamp hotspot -- DHCP for ESP32 nodes on wlan0
interface=wlan0
dhcp-range=${DHCP_RANGE_START},${DHCP_RANGE_END},${DHCP_NETMASK},24h
domain=basecamp.local
address=/gw.basecamp.local/${AP_IP}
EOF
    ok "Written /etc/dnsmasq.d/basecamp-hotspot.conf"

    SYSCTL_CONF="/etc/sysctl.d/99-basecamp-forward.conf"
    if [ ! -f "${SYSCTL_CONF}" ]; then
        printf 'net.ipv4.ip_forward=1\n' > "${SYSCTL_CONF}"
    fi
    sysctl -p "${SYSCTL_CONF}" > /dev/null
    iptables -t nat -F POSTROUTING 2>/dev/null || true
    iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
    iptables -A FORWARD -i eth0  -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT
    iptables -A FORWARD -i wlan0 -o eth0  -j ACCEPT
    netfilter-persistent save
    ok "IP forwarding and NAT rules saved"

    systemctl enable dnsmasq
    systemctl enable hostapd
    ok "hostapd and dnsmasq enabled (active after reboot)"

    printf '
  Hotspot: SSID "%s" on 2.4GHz channel %s (ESP32 nodes only)
  Pi internet: eth0 (DHCP)
  Dashboard: http://basecamp.local:5000 via LAN or http://%s:5000 via hotspot\n' \
        "${AP_SSID}" "${AP_CHANNEL}" "${AP_IP}"
}

# ── Step 10: DS3231 RTC ────────────────────────────────────────────────────────
step 10 "DS3231 RTC overlay"

step10_rtc() {
    append_if_missing "dtoverlay=i2c-rtc,ds3231" "${CONFIG_FILE}"
    ok "DS3231 RTC overlay added to boot config"

    # Disable fake-hwclock if present (conflicts with DS3231)
    if systemctl is-enabled fake-hwclock &>/dev/null; then
        systemctl disable fake-hwclock || true
        systemctl stop fake-hwclock    || true
        ok "fake-hwclock disabled (DS3231 provides hardware-backed time)"
    else
        ok "fake-hwclock not active"
    fi
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
may be a clone -- check the chip markings.
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
3. Flash ESP32s, connect to Basecamp-Node (wlan0 AP on the Pi)
4. Run SCD40 calibration (see above)
5. Run SGP40 burn-in: leave running 24h before trusting VOC readings
6. Check logs: tail -f /home/pi/basecamp/logs/*.log
7. Access morning log: http://basecamp.local:5000 (via LAN) or http://192.168.4.1:5000 (via hotspot)
8. Access dashboard: http://basecamp.local:5000/dashboard
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
    step9_hotspot
    step10_rtc
    step11_scd40
    step12_mock_hardware
    step13_summary
}

main "$@"

# ==============================================================================
# DEPRECATED APPENDIX: Router-dependent setup (v1/v2/v3 legacy)
#
# The canonical setup is the hotspot configuration above (pi_setup.sh steps 9+).
# The instructions below are retained for reference only. They configure the
# ESP32 nodes to connect to a dedicated 2.4GHz SSID on an ASUS WiFi 7 router
# rather than the Pi's own AP.
#
# Limitations of the router-dependent approach (reasons it was deprecated):
#   - Router configuration must be repeated at each location (HK, Shenzhen, Cate).
#   - Different routers produce different RF environments; CSI baselines do not
#     transfer between sites without retraining.
#   - Incompatible with school and dorm network infrastructure.
#   - Requires the ASUS router to be present; not portable.
#
# To use this approach instead of the hotspot (not recommended):
#   1. Skip step9_hotspot above.
#   2. Log into the ASUS router at 192.168.50.1.
#   3. Create a new 2.4GHz SSID: RuView-24
#      Settings: Mode=N only, Channel width=20MHz, MU-MIMO=disabled,
#      Beamforming=disabled, BSS Colouring=disabled, Airtime Fairness=disabled,
#      Smart Connect=disabled, Band Steering=disabled.
#   4. Configure ESP32 firmware with SSID=RuView-24 and UDP target = Pi LAN IP.
#   5. Set a DHCP reservation for the Pi's MAC in the router admin panel.
# ==============================================================================
