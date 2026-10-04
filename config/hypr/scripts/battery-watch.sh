#!/usr/bin/env bash
# Low-battery warnings and automatic Power Saver. Started at login; harmless on desktops (no battery).
#   20%  notification, and Power Saver until you plug in (turn it off in Settings > Power)
#   10%  critical notification
#    4%  critical notification, then suspend after 30 s unless the charger is connected
#
# Environment (for tests): BATTERY_DIR, BATTERY_POLL (seconds, default 60)
set -uo pipefail

bat="${BATTERY_DIR:-$(ls -d /sys/class/power_supply/BAT* 2>/dev/null | head -1)}"
[[ -n "$bat" && -r "$bat/capacity" ]] || exit 0
poll="${BATTERY_POLL:-60}"
state="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles"
notified=100          # lowest threshold already announced during this discharge
saver_on=0 prev_profile=""

note() { notify-send -a Battery -u "$1" -h string:x-canonical-private-synchronous:battery -i battery-caution "$2" "$3"; }

while :; do
    cap="$(cat "$bat/capacity")"; status="$(cat "$bat/status")"
    if [[ "$status" == Discharging ]]; then
        if (( cap <= 4 && notified > 4 )); then
            notified=4; note critical "Battery critically low ($cap%)" "Suspending in 30 seconds. Plug in the charger."
            sleep 30
            [[ "$(cat "$bat/status")" == Discharging ]] && systemctl suspend
        elif (( cap <= 10 && notified > 10 )); then
            notified=10; note critical "Battery low ($cap%)" "Plug in the charger soon."
        elif (( cap <= 20 && notified > 20 )); then
            notified=20; note normal "Battery at $cap%" "Switching to Power Saver."
            if [[ "$(cat "$state/battery-autosaver" 2>/dev/null || echo on)" != off ]] && command -v powerprofilesctl >/dev/null; then
                prev_profile="$(powerprofilesctl get 2>/dev/null)"; powerprofilesctl set power-saver && saver_on=1
            fi
        fi
    else                                   # charging, full or unknown: start over
        notified=100
        if (( saver_on )); then
            [[ -n "$prev_profile" ]] && powerprofilesctl set "$prev_profile" 2>/dev/null
            saver_on=0
        fi
    fi
    sleep "$poll"
done
