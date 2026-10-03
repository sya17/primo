#!/usr/bin/env bash
# Do-not-disturb via dunst.
# Usage: dnd.sh toggle | status   ("status" prints JSON for Waybar)
set -uo pipefail

swaync() { command -v swaync-client >/dev/null && pgrep -x swaync >/dev/null; }
paused() { if swaync; then [[ "$(swaync-client -D 2>/dev/null)" == "true" ]]; else [[ "$(dunstctl is-paused 2>/dev/null)" == "true" ]]; fi; }

case "${1:-status}" in
    toggle) if swaync; then swaync-client -d -sw >/dev/null; else dunstctl set-paused toggle; fi; pkill -RTMIN+8 waybar 2>/dev/null ;;
    status)
        if paused; then
            printf '{"text":"","alt":"on","class":"on","tooltip":"Do not disturb: on"}\n'
        else
            printf '{"text":"","alt":"off","class":"off","tooltip":"Do not disturb: off"}\n'
        fi ;;
esac
