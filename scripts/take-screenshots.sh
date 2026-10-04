#!/usr/bin/env bash
# Take the README screenshots on a clean, empty workspace with the theme's own wallpaper.
#
# Run it while you are NOT using the computer: it jumps to workspace 9, applies each theme, opens a few
# windows, captures them to docs/screenshots/, then puts your workspace, theme and wallpaper back.
#
# Usage: scripts/take-screenshots.sh [theme ...]      default: primo-dusk primo-dawn
set -uo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
scripts="$root/config/hypr/scripts"
out="$root/docs/screenshots"
state="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles"
themes=("$@"); (( ${#themes[@]} )) || themes=(primo-dusk primo-dawn)
shot_ws=9

command -v grim >/dev/null || { echo "grim is required"; exit 1; }
[[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || { echo "Run this inside your Hyprland session."; exit 1; }
mkdir -p "$out"

# ---- remember the current state and always restore it
orig_ws="$(hyprctl activeworkspace -j | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
orig_theme="$(cat "$state/current" 2>/dev/null || echo catppuccin-mocha)"
orig_wall="$(cat "$state/wallpaper" 2>/dev/null || true)"
restore() {
    close_class dev.primo.Settings; close_class scratchterm; pkill -x wofi 2>/dev/null || true
    swaync-client -cp >/dev/null 2>&1 || true; swaync-client -C >/dev/null 2>&1 || true
    "$root/scripts/theme-switch" "$orig_theme" >/dev/null 2>&1
    [[ -n "$orig_wall" ]] && "$root/scripts/theme-switch" --wallpaper "$orig_wall" >/dev/null 2>&1
    hyprctl dispatch "hl.dsp.focus({ workspace = $orig_ws })" >/dev/null 2>&1
    echo "Restored: workspace $orig_ws, theme $orig_theme."
}
trap restore EXIT

# ---- helpers
close_class() { # close ONLY windows of this exact class, by PID
    local pid
    for pid in $(hyprctl clients -j | python3 -c "
import json, sys
print(' '.join(str(c['pid']) for c in json.load(sys.stdin) if c['class'] == '$1'))"); do kill "$pid" 2>/dev/null; done
    sleep 0.6
}
snap() { grim "$out/$1.png" && echo "  $1.png"; }   # $1 = name without extension
wait_class() { for _ in $(seq 1 40); do hyprctl clients -j | grep -q "\"class\": \"$1\"" && return 0; sleep 0.25; done; return 1; }
daemon() { gdbus call --session --dest "$1" --object-path "/${1//./\/}" --method org.gtk.Actions.Activate "$2" "[]" "{}" >/dev/null 2>&1; }

hyprctl dispatch "hl.dsp.focus({ workspace = $shot_ws })" >/dev/null; sleep 1

for t in "${themes[@]}"; do
    echo "== $t"
    "$root/scripts/theme-switch" "$t" >/dev/null && "$root/scripts/theme-switch" --wallpaper reset >/dev/null
    sleep 2.5
    tag="${t#primo-}"

    snap "$tag-desktop"

    # Launcher with a query already typed
    daemon dev.primo.Launcher quit; sleep 1
    PRIMO_LAUNCHER_QUERY="fire" setsid -f python3 "$scripts/launcher.py" --daemon >/dev/null 2>&1; sleep 2.5
    "$scripts/launcher.sh" toggle; sleep 1.6; snap "$tag-launcher"; "$scripts/launcher.sh" toggle; sleep 0.8
    daemon dev.primo.Launcher quit; sleep 1; setsid -f python3 "$scripts/launcher.py" --daemon >/dev/null 2>&1

    # Settings pages
    for page in appearance wallpaper displays; do
        setsid -f python3 "$scripts/primo-settings.py" --page "$page" >/dev/null 2>&1
        wait_class dev.primo.Settings && { sleep 2; snap "$tag-settings-$page"; }
        close_class dev.primo.Settings
    done

    # Terminal with fastfetch and the prompt
    setsid -f kitty --class scratchterm bash -ic 'cd ~; clear; fastfetch; ll | head -5; exec bash -i' >/dev/null 2>&1
    wait_class scratchterm && { sleep 3.5; snap "$tag-terminal"; }
    close_class scratchterm

    # Notification centre with a few notifications
    notify-send -a Primo "Primo $tag" "Notification centre"; notify-send -a Kitty "Build finished" "No errors"
    notify-send -u critical "Battery low" "Plug in the charger"; sleep 1.2
    swaync-client -op >/dev/null 2>&1; sleep 1.6; snap "$tag-notifications"; swaync-client -cp >/dev/null 2>&1; swaync-client -C >/dev/null 2>&1

    # Power menu
    setsid -f "$scripts/power-menu.sh" >/dev/null 2>&1; sleep 1.8; snap "$tag-power-menu"; pkill -x wofi 2>/dev/null; sleep 0.6
done

echo "Done. Screenshots are in $out"
