#!/usr/bin/env bash
# SUPER+R / SUPER+SPACE: toggle the launcher (starting its service if needed).
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Launcher

running() {
    gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner "$dest" 2>/dev/null | grep -q true
}

if ! running; then
    setsid -f python3 "$dir/launcher.py" --daemon >/dev/null 2>&1
    for _ in $(seq 1 60); do running && break; sleep 0.05; done
fi
gdbus call --session --dest "$dest" --object-path /dev/primo/Launcher \
    --method org.gtk.Actions.Activate "${1:-toggle}" "[]" "{}" >/dev/null
