#!/usr/bin/env bash
# Install the Primo login theme for SDDM. Needs root.
#
# Usage: sudo scripts/install-sddm-theme.sh [--dry-run]       (Settings runs it through pkexec)
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
    --uninstall) rm -rf "$dest" "$conf" /var/lib/primo-login; echo "Removed $dest and $conf (SDDM falls back to its default theme)."; exit 0 ;;
    "") ;;
    *) echo "usage: $0 [--dry-run|--uninstall]" >&2; exit 2 ;;
esac

[[ -f "$src/theme.conf" && -f "$src/logo.svg" ]] && compgen -G "$src/background.*" >/dev/null || { echo "Run 'hypr-theme <theme>' first (it generates theme.conf and the wallpaper)."; exit 1; }
(( dry )) || [[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

# Cursor for the login screen follows the desktop (set by theme-switch, falls back to Breeze).
user="${SUDO_USER:-$(id -nu "${PKEXEC_UID:-0}" 2>/dev/null)}"
cursor="$(cat "${XDG_STATE_HOME:-$(getent passwd "$user" | cut -d: -f6)/.local/state}/hyprland-dotfiles/cursor" 2>/dev/null || echo breeze_cursors)"

run() { if (( dry )); then echo "[dry-run] $*"; else "$@"; fi; }
run mkdir -p "$dest" "$(dirname "$conf")"
run rm -f "$dest"/background.*   # png or gif: only the current one
run cp -f "$src/Main.qml" "$src/metadata.desktop" "$dest/"
# Colours, logo and background live in a folder owned by you, so theme-switch and Settings update the login screen
# without sudo. The greeter only reads them (pictures and colour values; the QML stays root-owned).
live=/var/lib/primo-login
run install -d -m 755 -o "$user" "$live"
run rm -f "$live"/background.*
run install -m 644 -o "$user" "$src/theme.conf" "$src/logo.svg" "$src"/background.* "$live/"
for f in theme.conf logo.svg background.png background.gif; do run ln -sfn "$live/$f" "$dest/$f"; done
if (( dry )); then
    echo "[dry-run] write $conf: Current=primo CursorTheme=$cursor"
else
    printf '[Theme]\nCurrent=primo\nCursorTheme=%s\nCursorSize=24\n' "$cursor" > "$conf"
fi
echo "Installed. Preview without logging out (use the Qt5 greeter: it is the one SDDM really runs):"
echo "  sddm-greeter --test-mode --theme $dest"
echo "Undo:  sudo $0 --uninstall"
