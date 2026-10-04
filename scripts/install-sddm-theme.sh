#!/usr/bin/env bash
# Install the Primo login theme for SDDM. Needs root.
#
# Usage: sudo scripts/install-sddm-theme.sh [--dry-run]
#        sudo scripts/install-sddm-theme.sh --uninstall
#
# The theme copies the palette and wallpaper of the theme that was active the last time
# `hypr-theme` ran, so re-run this after switching if you want the login screen to follow.
# It never touches your existing SDDM config: everything goes in one drop-in file.
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
src="$root/sddm/primo"
dest="/usr/share/sddm/themes/primo"
conf="/etc/sddm.conf.d/10-primo.conf"
dry=0

case "${1:-}" in
    --dry-run)   dry=1 ;;
    --uninstall) rm -rf "$dest" "$conf"; echo "Removed $dest and $conf (SDDM falls back to its default theme)."; exit 0 ;;
    "") ;;
    *) echo "usage: $0 [--dry-run|--uninstall]" >&2; exit 2 ;;
esac

[[ -f "$src/theme.conf" && -f "$src/background.png" && -f "$src/logo.svg" ]] || { echo "Run 'hypr-theme <theme>' first (it generates theme.conf and the wallpaper)."; exit 1; }
(( dry )) || [[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

# Cursor for the login screen follows the desktop (set by theme-switch, falls back to Breeze).
cursor="$(cat "${XDG_STATE_HOME:-${SUDO_USER:+/home/$SUDO_USER/.local/state}}/hyprland-dotfiles/cursor" 2>/dev/null || echo breeze_cursors)"

run() { if (( dry )); then echo "[dry-run] $*"; else "$@"; fi; }
run mkdir -p "$dest" "$(dirname "$conf")"
run cp -f "$src/Main.qml" "$src/metadata.desktop" "$src/theme.conf" "$src/background.png" "$src/logo.svg" "$dest/"
if (( dry )); then
    echo "[dry-run] write $conf: Current=primo CursorTheme=$cursor"
else
    printf '[Theme]\nCurrent=primo\nCursorTheme=%s\nCursorSize=24\n' "$cursor" > "$conf"
fi
echo "Installed. Preview without logging out (use the Qt5 greeter: it is the one SDDM really runs):"
echo "  sddm-greeter --test-mode --theme $dest"
echo "Undo:  sudo $0 --uninstall"
