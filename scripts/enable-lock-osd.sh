#!/usr/bin/env bash
# Show an on-screen indicator for Caps Lock / Num Lock / Scroll Lock.
# swayosd needs its libinput backend service, which runs as root. Needs sudo once.
#
# Usage: sudo scripts/enable-lock-osd.sh [--disable]
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }
if [[ "${1:-}" == "--disable" ]]; then
    systemctl disable --now swayosd-libinput-backend.service
    echo "Disabled."
else
    systemctl enable --now swayosd-libinput-backend.service
    echo "Enabled. Press Caps Lock to see the indicator (restart swayosd-server if it does not show)."
fi
