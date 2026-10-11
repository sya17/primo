#!/usr/bin/env bash
# SUPER+O: toggle the workspace overview (starting its service if needed).
set -uo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
dest=dev.primo.Overview

. "$dir/service-lib.sh"
ensure_service overview "$dest" "$dir/overview.py"
gdbus call --session --dest "$dest" --object-path /dev/primo/Overview \
    --method org.gtk.Actions.Activate "${1:-toggle}" "[]" "{}" >/dev/null
