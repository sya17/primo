#!/usr/bin/env bash
# Usage: screenshot.sh [area|full|edit]
#   area  select an area; copy to the clipboard, save to ~/Pictures/Screenshots
#   full  the whole screen, same
#   edit  select an area and open it straight in the annotation editor (satty)
# The notification has buttons: Annotate (satty) and Show in folder.
set -euo pipefail

mode="${1:-area}"
dir="${XDG_PICTURES_DIR:-$HOME/Pictures}/Screenshots"
file="$dir/$(date +%Y-%m-%d_%H-%M-%S).png"
here="$(dirname "$0")"

for cmd in grim wl-copy; do
    command -v "$cmd" >/dev/null || { notify-send -u critical "Screenshot" "Missing dependency: $cmd"; exit 1; }
done
mkdir -p "$dir"

select_region() {
    command -v slurp >/dev/null || { notify-send -u critical "Screenshot" "Missing dependency: slurp"; exit 1; }
    # shellcheck disable=SC1091
    [[ -f "$here/../theme.env" ]] && source "$here/../theme.env"
    # Dim the screen with the theme colour and outline the selection in the accent colour.
    slurp -b "#${P_BASE:-1e1e2e}80" -c "#${P_ACCENT:-8da2ff}ff" -s "#${P_ACCENT:-8da2ff}22" -B "#${P_BASE:-1e1e2e}80" -w 2
}

annotate() { # file
    if command -v satty >/dev/null; then
        satty --filename "$1" --output-filename "$1" --early-exit --copy-command wl-copy
    else
        notify-send -u low "Screenshot" "Install satty to annotate (pacman -S satty)"
    fi
}

case "$mode" in
    area) region="$(select_region)" || exit 0; grim -g "$region" "$file" ;;   # Esc cancels
    edit) region="$(select_region)" || exit 0; grim -g "$region" "$file"; annotate "$file"; wl-copy < "$file"; exit 0 ;;
    full) grim "$file" ;;
    *) echo "usage: ${0##*/} [area|full|edit]" >&2; exit 2 ;;
esac

wl-copy < "$file"

# Notification with actions. notify-send waits for the click, so do it detached.
(
    action="$(notify-send -a Screenshot -i "$file" -A annotate="Annotate" -A folder="Show in folder" -w \
        "Screenshot saved" "Copied to the clipboard" 2>/dev/null || true)"
    case "$action" in
        annotate) annotate "$file"; wl-copy < "$file" ;;
        folder)   command -v nautilus >/dev/null && nautilus --select "$file" || xdg-open "$dir" ;;
    esac
) >/dev/null 2>&1 &
disown
