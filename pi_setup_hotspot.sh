#!/bin/bash
# ==============================================================================
# Basecamp — Hotspot configuration for Cate School
#
# RUN THIS ONLY AT CATE. DO NOT RUN AT HOME.
#
# This script turns the Pi's wlan0 into a 2.4GHz access point so the ESP32
# nodes can connect (SSID: Basecamp-Node, password: basecamp2024) while the Pi
# itself reaches the internet via its ethernet port (eth0).
#
# Run as: sudo bash pi_setup_hotspot.sh
# ==============================================================================
set -euo pipefail

# ── Output helpers ─────────────────────────────────────────────────────────────
step() { printf '\n\033[1;34m━━━ %s ━━━\033[0m\n' "$1"; }
ok()   { printf '  \033[0;32m✓ %s\033[0m\n' "$1"; }
warn() { printf '  \033[1;33m⚠ %s\033[0m\n' "$1"; }
die()  { printf '\n\033[0;31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

# ── Pre-flight ─────────────────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    die "Run as root: sudo bash pi_setup_hotspot.sh"
fi
if ! grep -qi "raspberry pi" /proc/cpuinfo 2>/dev/null; then
    die "Must be run on a Raspberry Pi."
fi

# ── Configuration ──────────────────────────────────────────────────────────────
AP_SSID="Basecamp-Node"
AP_PASS="basecamp2024"
AP_CHANNEL="6"
AP_IP="192.168.4.1"
DHCP_RANGE_START="192.168.4.2"
DHCP_RANGE_END="192.168.4.20"
DHCP_NETMASK="255.255.255.0"

printf '\033[1;33m'
printf '%s\n' "══════════════════════════════════════════════"
printf '%s\n' " WARNING: Hotspot mode — Cate School only"
printf '%s\n' "══════════════════════════════════════════════"
printf '\033[0m'
printf 'SSID:     %s\n' "${AP_SSID}"
printf 'Password: %s\n' "${AP_PASS}"
printf 'AP IP:    %s\n' "${AP_IP}"
printf 'Internet: via eth0 (school network)\n\n'
printf 'Press Ctrl-C within 5 seconds to cancel...\n'
sleep 5

# ── Step 1: Install packages ───────────────────────────────────────────────────
step "Step 1: Install hostapd and dnsmasq"

apt-get update -qq
apt-get install -y -qq hostapd dnsmasq iptables-persistent
ok "hostapd, dnsmasq, iptables-persistent installed"

# ── Step 2: Stop wpa_supplicant on wlan0 ──────────────────────────────────────
step "Step 2: Disable wpa_supplicant on wlan0"

# wpa_supplicant manages wlan0 in client mode; AP mode needs it off
if [ -f /etc/wpa_supplicant/wpa_supplicant.conf ]; then
    cp /etc/wpa_supplicant/wpa_supplicant.conf \
       /etc/wpa_supplicant/wpa_supplicant.conf.home_backup
    ok "Backed up wpa_supplicant.conf → wpa_supplicant.conf.home_backup"
fi
systemctl stop wpa_supplicant || true
systemctl disable wpa_supplicant || true
ok "wpa_supplicant disabled"

# ── Step 3: Static IP for wlan0 ───────────────────────────────────────────────
step "Step 3: Configure wlan0 static IP (${AP_IP}/24)"

DHCPCD_CONF="/etc/dhcpcd.conf"
DHCPCD_MARKER="# Basecamp hotspot — wlan0 static"

if ! grep -qF "${DHCPCD_MARKER}" "${DHCPCD_CONF}"; then
    cat >> "${DHCPCD_CONF}" << EOF

${DHCPCD_MARKER}
interface wlan0
    static ip_address=${AP_IP}/24
    nohook wpa_supplicant
EOF
    ok "Added wlan0 static config to ${DHCPCD_CONF}"
else
    ok "wlan0 static config already present in ${DHCPCD_CONF}"
fi

# ── Step 4: hostapd configuration ─────────────────────────────────────────────
step "Step 4: Write hostapd configuration"

HOSTAPD_CONF="/etc/hostapd/hostapd.conf"

cat > "${HOSTAPD_CONF}" << EOF
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
ok "Written: ${HOSTAPD_CONF}"

# Point the hostapd daemon at its config
HOSTAPD_DEFAULT="/etc/default/hostapd"
if grep -q "^#DAEMON_CONF" "${HOSTAPD_DEFAULT}" 2>/dev/null; then
    sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' "${HOSTAPD_DEFAULT}"
elif ! grep -q "^DAEMON_CONF" "${HOSTAPD_DEFAULT}" 2>/dev/null; then
    printf 'DAEMON_CONF="/etc/hostapd/hostapd.conf"\n' >> "${HOSTAPD_DEFAULT}"
fi
ok "DAEMON_CONF set in ${HOSTAPD_DEFAULT}"

systemctl unmask hostapd
ok "hostapd unmasked"

# ── Step 5: dnsmasq configuration ─────────────────────────────────────────────
step "Step 5: Write dnsmasq configuration"

DNSMASQ_CONF="/etc/dnsmasq.d/basecamp-hotspot.conf"

cat > "${DNSMASQ_CONF}" << EOF
# Basecamp hotspot — DHCP for ESP32 nodes on wlan0
interface=wlan0
dhcp-range=${DHCP_RANGE_START},${DHCP_RANGE_END},${DHCP_NETMASK},24h
domain=basecamp.local
address=/gw.basecamp.local/${AP_IP}
EOF
ok "Written: ${DNSMASQ_CONF}"

# ── Step 6: IP forwarding (wlan0 → eth0) ─────────────────────────────────────
step "Step 6: Enable IP forwarding"

SYSCTL_CONF="/etc/sysctl.d/99-basecamp-forward.conf"
if [ ! -f "${SYSCTL_CONF}" ]; then
    printf 'net.ipv4.ip_forward=1\n' > "${SYSCTL_CONF}"
    ok "Created ${SYSCTL_CONF}"
else
    ok "IP forwarding config already present"
fi
sysctl -p "${SYSCTL_CONF}" > /dev/null
ok "IP forwarding active"

# ── Step 7: iptables NAT (ESP32s → internet via eth0) ─────────────────────────
step "Step 7: iptables NAT rules"

# Flush then re-apply so this is idempotent
iptables -t nat -F POSTROUTING 2>/dev/null || true
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
iptables -A FORWARD -i eth0   -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i wlan0  -o eth0  -j ACCEPT
netfilter-persistent save
ok "NAT rules saved (persist across reboots)"

# ── Step 8: Enable and start services ─────────────────────────────────────────
step "Step 8: Enable hostapd and dnsmasq"

systemctl enable dnsmasq
systemctl enable hostapd
ok "Services enabled (will start on reboot)"

# ── Summary ────────────────────────────────────────────────────────────────────
printf '\n\033[1;32m'
printf '%s\n' "═══════════════════════════════════════"
printf '%s\n' " Hotspot configuration complete"
printf '%s\n' "═══════════════════════════════════════"
printf '\033[0m'
cat << 'EOF'
Reboot to activate:
  sudo reboot

After reboot:
  SSID "Basecamp-Node" will appear on 2.4GHz
  ESP32 nodes connect to it automatically
  Pi reaches internet via eth0 (school ethernet)

To revert at home:
  sudo systemctl disable hostapd dnsmasq
  sudo systemctl enable wpa_supplicant
  Remove the wlan0 block from /etc/dhcpcd.conf
  sudo reboot
EOF
