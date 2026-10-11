#!/usr/bin/env bash
# Entry point for Activity: talks to the service (starting it if needed).
# Usage: activity.sh toggle
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Activity

. "$dir/service-lib.sh"
ensure_service activity "$dest" "$dir/activity.py"
gdbus call --session --dest "$dest" --object-path /dev/primo/Activity \
    --method org.gtk.Actions.Activate "${1:-toggle}" "[]" "{}" >/dev/null
