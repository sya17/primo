#!/usr/bin/env bash
# Show the current wallpaper (path written by theme-switch to <state>/wallpaper-current).
# Uses awww (animated transitions) when installed, hyprpaper otherwise.
#
# Usage: wallpaper.sh apply     animate to the current wallpaper (theme or wallpaper changed)
#        wallpaper.sh restore   no animation (used at login)
# GIFs go through awww; videos (mp4, webm, mkv, mov) through mpvpaper when installed, otherwise they are skipped.
# The transition is chosen in Settings > Wallpaper (<state>/wallpaper-transition): grow, fade, wave, wipe, none.
set -uo pipefail

state="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles"
mode="${1:-apply}"
img="$(cat "$state/wallpaper-current" 2>/dev/null || true)"

hyprpaper_fallback() {
    pkill -x hyprpaper 2>/dev/null || true
    sleep 0.2
    setsid -f hyprpaper >/dev/null 2>&1
}

is_video() { case "${1,,}" in *.mp4|*.webm|*.mkv|*.mov) return 0 ;; esac; return 1; }

if is_video "$img" && [[ -f "$img" ]] && command -v mpvpaper >/dev/null 2>&1; then
    pkill -x hyprpaper 2>/dev/null || true
    pkill -x awww-daemon 2>/dev/null || true   # two wallpaper layers would fight
    pkill -KILL -x mpvpaper 2>/dev/null || true
    sleep 0.2
    # --auto-pause: stops decoding while windows cover the whole screen
    setsid -f mpvpaper --auto-pause -o "no-audio loop hwdec=auto panscan=1.0" '*' "$img" >/dev/null 2>&1
    exit 0
fi
pkill -KILL -x mpvpaper 2>/dev/null || true
is_video "$img" && img=""   # no mpvpaper: fall through to the static wallpaper below

if ! command -v awww >/dev/null 2>&1 || [[ -z "$img" || ! -f "$img" ]]; then
    hyprpaper_fallback
    exit 0
fi

pkill -x hyprpaper 2>/dev/null || true   # awww replaces it
if ! pgrep -x awww-daemon >/dev/null; then
    setsid -f awww-daemon >/dev/null 2>&1
    for _ in $(seq 1 30); do awww query >/dev/null 2>&1 && break; sleep 0.1; done
fi

type="$(cat "$state/wallpaper-transition" 2>/dev/null || echo grow)"
[[ "$mode" == restore ]] && type=none
args=(--transition-type "$type" --transition-duration 1.2 --transition-fps 60)
if [[ "$type" == grow || "$type" == outer ]]; then
    pos="$(hyprctl cursorpos 2>/dev/null | tr -d ' ')"
    [[ "$pos" =~ ^[0-9]+,[0-9]+$ ]] && args+=(--transition-pos "$pos")
fi
awww img "$img" "${args[@]}" >/dev/null 2>&1 || hyprpaper_fallback
