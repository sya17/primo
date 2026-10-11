#!/usr/bin/env bash
# SUPER+R / SUPER+SPACE: toggle the launcher (starting its service if needed).
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Launcher

. "$dir/service-lib.sh"
ensure_service launcher "$dest" "$dir/launcher.py"
gdbus call --session --dest "$dest" --object-path /dev/primo/Launcher \
    --method org.gtk.Actions.Activate "${1:-toggle}" "[]" "{}" >/dev/null
