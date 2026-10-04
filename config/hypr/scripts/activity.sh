#!/usr/bin/env bash
# Entry point for Activity: talks to the service (starting it if needed).
# Usage: activity.sh toggle
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Activity

running() {
    gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner "$dest" 2>/dev/null | grep -q true
}

if ! running; then
    setsid -f python3 "$dir/activity.py" --daemon >/dev/null 2>&1
    for _ in $(seq 1 60); do running && break; sleep 0.05; done
fi
gdbus call --session --dest "$dest" --object-path /dev/primo/Activity \
    --method org.gtk.Actions.Activate "${1:-toggle}" "[]" "{}" >/dev/null
