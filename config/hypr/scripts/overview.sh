#!/usr/bin/env bash
# SUPER+O: toggle the workspace overview (starting its service if needed).
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Overview

running() {
    gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner "$dest" 2>/dev/null | grep -q true
}

if ! running; then
    # the unit owns the service when it is enabled; otherwise start it ourselves, as before
    if systemctl --user is-enabled -q primo-overview.service 2>/dev/null; then
        systemctl --user start primo-overview.service >/dev/null 2>&1
    else
        setsid -f python3 "$dir/overview.py" --daemon >/dev/null 2>&1
    fi
    for _ in $(seq 1 60); do running && break; sleep 0.05; done
fi
gdbus call --session --dest "$dest" --object-path /dev/primo/Overview \
    --method org.gtk.Actions.Activate "${1:-toggle}" "[]" "{}" >/dev/null
