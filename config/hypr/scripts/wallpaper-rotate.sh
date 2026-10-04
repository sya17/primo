#!/usr/bin/env bash
# Slideshow: switch to another picture from a folder every N minutes (Settings > Wallpaper > Slideshow).
#
# Usage: wallpaper-rotate.sh          background loop (autostart); re-reads the settings as it goes
#        wallpaper-rotate.sh next     switch right now
# State (<state>/): slideshow-on (exists = enabled), slideshow-dir, slideshow-interval (minutes, default 30)
set -uo pipefail

state="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles"
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

next() {
    local dir cur pick
    dir="$(cat "$state/slideshow-dir" 2>/dev/null)"
    [[ -d "$dir" ]] || return 1
    cur="$(cat "$state/wallpaper-current" 2>/dev/null)"
    pick="$(find -L "$dir" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) \
            | grep -vxF "$cur" | shuf -n1)"
    [[ -n "$pick" ]] || return 1   # empty folder, or the current picture is the only one
    readlink -f "$pick" > "$state/wallpaper"          # same override Settings uses, so it survives theme changes
    echo "$pick" > "$state/wallpaper-current"
    "$here/wallpaper.sh" apply
}

if [[ "${1:-}" == next ]]; then next; exit; fi

exec 9>"${XDG_RUNTIME_DIR:-/tmp}/primo-wallpaper-rotate.lock"
flock -n 9 || exit 0   # already running

last=$(date +%s)
while sleep 15; do
    [[ -e "$state/slideshow-on" ]] || { last=$(date +%s); continue; }
    now=$(date +%s)
    (( now - last >= $(cat "$state/slideshow-interval" 2>/dev/null || echo 30) * 60 )) || continue
    last=$now
    next
done
