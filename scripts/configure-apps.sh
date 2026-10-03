#!/usr/bin/env bash
# One-time (idempotent) setup of the file manager and friends. Safe to re-run.
# Usage: configure-apps.sh
set -uo pipefail

gset() { # schema key value  (skips keys that do not exist in this version)
    gsettings list-keys "$1" 2>/dev/null | grep -qx "$2" || { echo "skip: $1 $2"; return 0; }
    gsettings set "$1" "$2" "$3" 2>/dev/null && echo "set:  $1 $2 = $3"
}
has_schema() { gsettings list-schemas 2>/dev/null | grep -qx "$1"; }
has_value()  { gsettings range "$1" "$2" 2>/dev/null | grep -q "'$3'"; }

# ---- Nautilus (Files) ----
if has_schema org.gnome.nautilus.preferences; then
    p=org.gnome.nautilus.preferences
    has_value $p default-folder-viewer grid-view && gset $p default-folder-viewer "'grid-view'" || gset $p default-folder-viewer "'icon-view'"
    gset $p click-policy "'double'"
    gset $p show-image-thumbnails "'always'"
    gset $p date-time-format "'detailed'"
    gset $p sort-directories-first true
    gset $p show-create-link true
    gset $p show-delete-permanently true
    # List view: Explorer-style tree (expand folders in place) with useful columns.
    gset org.gnome.nautilus.list-view use-tree-view true
    gset org.gnome.nautilus.list-view default-visible-columns "['name', 'size', 'type', 'date_modified']"
    gset org.gnome.nautilus.list-view default-zoom-level "'medium'"
    gset org.gnome.nautilus.icon-view default-zoom-level "'medium'"
else
    echo "note: Nautilus schemas not found; install nautilus first"
fi

# ---- GTK file chooser (Open/Save dialogs in every GTK app) ----
if has_schema org.gtk.gtk4.Settings.FileChooser; then
    c=org.gtk.gtk4.Settings.FileChooser
    gset $c sort-directories-first true
    gset $c date-format "'with-time'"
    gset $c clock-format "'24h'"
fi

# ---- Sidebar favourites (Nautilus reads GTK3 bookmarks) ----
mkdir -p "$HOME/.config/gtk-3.0"
bm="$HOME/.config/gtk-3.0/bookmarks"; touch "$bm"
for d in Downloads Pictures workspace; do
    [[ -d "$HOME/$d" ]] && ! grep -q "file://$HOME/$d" "$bm" && echo "file://$HOME/$d ${d^}" >> "$bm"
done

# ---- Defaults: folders open in the file manager, "Open in Terminal" uses kitty ----
if [[ -f /usr/share/applications/org.gnome.Nautilus.desktop ]]; then
    xdg-mime default org.gnome.Nautilus.desktop inode/directory && echo "set:  inode/directory -> Nautilus"
fi
# Images and PDFs open in Loupe / Papers (same look as Nautilus) instead of the browser.
set_default() { # desktop-file mime...
    local d="$1"; shift
    [[ -f "/usr/share/applications/$d" ]] || return 0
    xdg-mime default "$d" "$@" && echo "set:  $* -> $d"
}
set_default org.gnome.Loupe.desktop image/jpeg image/png image/webp image/gif image/bmp image/tiff image/avif image/heif image/svg+xml
set_default org.gnome.Papers.desktop application/pdf

tl="$HOME/.config/xdg-terminals.list"
[[ -f "$tl" ]] || { echo "kitty.desktop" > "$tl"; echo "set:  default terminal -> kitty"; }
exit 0
