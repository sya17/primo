#!/usr/bin/env bash
# Notification state and actions for the bar. Works with swaync (control center) and falls
# back to dunst (do-not-disturb only) when swaync is not installed / running.
#
# Usage: notifications.sh          stream JSON for Waybar (long-running)
#        notifications.sh panel    toggle the control center (dunst: toggle do-not-disturb)
#        notifications.sh dnd      toggle do-not-disturb
set -uo pipefail

have_swaync() { command -v swaync-client >/dev/null && pgrep -x swaync >/dev/null; }

case "${1:-stream}" in
    panel) have_swaync && swaync-client -t -sw || "$(dirname "$0")/dnd.sh" toggle ;;
    dnd)   have_swaync && swaync-client -d -sw >/dev/null || "$(dirname "$0")/dnd.sh" toggle ;;
    stream)
        if have_swaync; then exec swaync-client -swb; fi
        # dunst fallback: poll
        while :; do
            if [[ "$(dunstctl is-paused 2>/dev/null)" == "true" ]]; then
                printf '{"text":"","alt":"dnd-none","class":"dnd-none","tooltip":"Do not disturb: on"}\n'
            else
                printf '{"text":"","alt":"none","class":"none","tooltip":"Do not disturb: off"}\n'
            fi
            sleep 3
        done ;;
    *) echo "usage: ${0##*/} [stream|panel|dnd]" >&2; exit 2 ;;
esac
