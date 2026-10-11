#!/usr/bin/env bash
# Alt+Tab entry point: talks to the switcher service (starting it if needed).
# Usage: switcher.sh next | prev
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Switcher

. "$dir/service-lib.sh"
ensure_service switcher "$dest" "$dir/switcher.py"
gdbus call --session --dest "$dest" --object-path /dev/primo/Switcher \
    --method org.gtk.Actions.Activate "${1:-next}" "[]" "{}" >/dev/null
