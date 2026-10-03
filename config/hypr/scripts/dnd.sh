#!/usr/bin/env bash
# Do-not-disturb via dunst.
# Usage: dnd.sh toggle | status   ("status" prints JSON for Waybar)
set -uo pipefail

case "${1:-status}" in
    toggle) dunstctl set-paused toggle; pkill -RTMIN+8 waybar 2>/dev/null ;;
    status)
        if [[ "$(dunstctl is-paused 2>/dev/null)" == "true" ]]; then
            printf '{"text":"","alt":"on","class":"on","tooltip":"Do not disturb: on"}\n'
        else
            printf '{"text":"","alt":"off","class":"off","tooltip":"Do not disturb: off"}\n'
        fi ;;
esac
