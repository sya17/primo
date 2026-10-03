#!/usr/bin/env bash
# Usage: screenshot.sh [area|full]
# Copies the capture to the clipboard and saves it to ~/Pictures/Screenshots.
set -euo pipefail

mode="${1:-area}"
dir="${XDG_PICTURES_DIR:-$HOME/Pictures}/Screenshots"
file="$dir/$(date +%Y-%m-%d_%H-%M-%S).png"

for cmd in grim wl-copy; do
    command -v "$cmd" >/dev/null || { notify-send -u critical "Screenshot" "Missing dependency: $cmd"; exit 1; }
done
mkdir -p "$dir"

case "$mode" in
    area)
        command -v slurp >/dev/null || { notify-send -u critical "Screenshot" "Missing dependency: slurp"; exit 1; }
        region="$(slurp)" || exit 0   # cancelled with Esc
        grim -g "$region" "$file"
        ;;
    full) grim "$file" ;;
    *) echo "usage: ${0##*/} [area|full]" >&2; exit 2 ;;
esac

wl-copy < "$file"
notify-send -i "$file" "Screenshot saved" "$file"
