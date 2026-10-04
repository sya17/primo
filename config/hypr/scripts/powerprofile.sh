#!/usr/bin/env bash
# Power mode via power-profiles-daemon.
# Usage: powerprofile.sh status | cycle | set <power-saver|balanced|performance>
#   status   JSON for Waybar
#   cycle    next mode (Power Saver > Balanced > Performance)
set -uo pipefail

command -v powerprofilesctl >/dev/null || exit 0
current="$(powerprofilesctl get 2>/dev/null || echo balanced)"

label() { case "$1" in power-saver) echo "Power Saver" ;; performance) echo "Performance" ;; *) echo "Balanced" ;; esac; }
available() { powerprofilesctl list 2>/dev/null | grep -qE "^\s*\*?\s*$1:"; }

case "${1:-status}" in
    status)
        printf '{"text":"","alt":"%s","class":"%s","tooltip":"Power mode: %s (click to change)"}\n' \
            "$current" "$current" "$(label "$current")" ;;
    set)
        powerprofilesctl set "${2:?profile}" && pkill -RTMIN+12 waybar 2>/dev/null
        notify-send -a "Power" -t 1500 -h string:x-canonical-private-synchronous:power "Power mode" "$(label "${2}")" ;;
    cycle)
        order=(power-saver balanced performance)
        next=balanced
        for i in "${!order[@]}"; do
            [[ "${order[$i]}" == "$current" ]] && next="${order[$(( (i + 1) % 3 ))]}"
        done
        available "$next" || next=power-saver   # performance is not offered on every machine
        "$0" set "$next" ;;
    *) echo "usage: ${0##*/} status|cycle|set <profile>" >&2; exit 2 ;;
esac
