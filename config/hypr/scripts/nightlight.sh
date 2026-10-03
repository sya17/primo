#!/usr/bin/env bash
# Night light via hyprsunset.
# Usage: nightlight.sh toggle | status   ("status" prints JSON for Waybar)
set -uo pipefail
temp="${NIGHTLIGHT_TEMP:-4000}"

on() { pgrep -x hyprsunset >/dev/null; }

case "${1:-status}" in
    toggle)
        command -v hyprsunset >/dev/null || { notify-send "Night light" "hyprsunset is not installed"; exit 1; }
        if on; then pkill -x hyprsunset; else setsid -f hyprsunset -t "$temp" >/dev/null 2>&1; fi
        pkill -RTMIN+9 waybar 2>/dev/null
        ;;
    status)
        if on; then printf '{"text":"","alt":"on","class":"on","tooltip":"Night light on (%sK)"}\n' "$temp"
        else        printf '{"text":"","alt":"off","class":"off","tooltip":"Night light off"}\n'; fi
        ;;
esac
