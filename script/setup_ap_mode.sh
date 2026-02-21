#!/usr/bin/env bash
set -euo pipefail

AP_IFACE="${AP_IFACE:-wlan0}"
AP_SSID="${AP_SSID:-TimeHacker-Setup}"
AP_PASS="${AP_PASS:-timehacker1234}"
AP_IP_CIDR="${AP_IP_CIDR:-192.168.50.1/24}"

nmcli connection delete timehacker-ap >/dev/null 2>&1 || true

nmcli connection add type wifi ifname "${AP_IFACE}" con-name timehacker-ap ssid "${AP_SSID}"
nmcli connection modify timehacker-ap \
  802-11-wireless.mode ap \
  802-11-wireless.band bg \
  wifi-sec.key-mgmt wpa-psk \
  wifi-sec.psk "${AP_PASS}" \
  ipv4.method shared \
  ipv4.addresses "${AP_IP_CIDR}" \
  ipv6.method ignore \
  connection.autoconnect yes

nmcli connection up timehacker-ap

echo "AP ready: SSID=${AP_SSID}"
echo "Open: http://192.168.50.1:8000/setup"