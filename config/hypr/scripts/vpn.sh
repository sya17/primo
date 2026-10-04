#!/usr/bin/env bash
# Waybar: a shield while a VPN is connected, nothing otherwise. Click opens Settings > VPN.
# Usage: vpn.sh status
set -uo pipefail
names="$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | awk -F: '$NF=="vpn" || $NF=="wireguard" {sub(/:[^:]*$/, ""); print}' | sed 's/\\:/:/g')"
if [[ -z "$names" ]]; then
    echo '{"text":"","class":"idle","tooltip":""}'
else
    jq -nc --arg t "VPN connected: $(tr '\n' ',' <<<"$names" | sed 's/,$//; s/,/, /g')" 'def esc: gsub("&"; "&amp;") | gsub("<"; "&lt;") | gsub(">"; "&gt;");
        {text:"󰕥", class:"on", tooltip:($t | esc)}'
fi
