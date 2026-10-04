#!/usr/bin/env bash
# Entry point for the time hub: talks to the service (starting it if needed).
# Usage: hub.sh toggle | calendar | reminders | clock | focus | notes | new-note
#        hub.sh status          JSON for the bar: a running timer or focus session (empty otherwise)
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Hub
state="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles/hub"

if [[ "${1:-}" == status ]]; then
    cat "$state/status.json" 2>/dev/null || echo '{"text":"","class":"idle"}'
    exit 0
fi

running() {
    gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner "$dest" 2>/dev/null | grep -q true
}

if ! running; then
    setsid -f python3 "$dir/hub.py" --daemon >/dev/null 2>&1
    for _ in $(seq 1 60); do running && break; sleep 0.05; done
fi
case "${1:-toggle}" in
    toggle) gdbus call --session --dest "$dest" --object-path /dev/primo/Hub --method org.gtk.Actions.Activate toggle "[]" "{}" >/dev/null ;;
    *)      gdbus call --session --dest "$dest" --object-path /dev/primo/Hub --method org.gtk.Actions.Activate open "[<'$1'>]" "{}" >/dev/null ;;
esac
