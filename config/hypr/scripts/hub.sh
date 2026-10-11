#!/usr/bin/env bash
# Entry point for the time hub: talks to the service (starting it if needed).
# Usage: hub.sh toggle | calendar | reminders | clock | focus | report | notes | new-note | standup
#        hub.sh status          JSON for the bar: a running timer or focus session (empty otherwise)
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Hub
state="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles/hub"

if [[ "${1:-}" == status ]]; then
    cat "$state/status.json" 2>/dev/null || echo '{"text":"","class":"idle"}'
    exit 0
fi

. "$dir/service-lib.sh"
ensure_service hub "$dest" "$dir/hub.py"
case "${1:-toggle}" in
    toggle|standup|workflow-reload) gdbus call --session --dest "$dest" --object-path /dev/primo/Hub --method org.gtk.Actions.Activate "${1:-toggle}" "[]" "{}" >/dev/null ;;
    *)      gdbus call --session --dest "$dest" --object-path /dev/primo/Hub --method org.gtk.Actions.Activate open "[<'$1'>]" "{}" >/dev/null ;;
esac
