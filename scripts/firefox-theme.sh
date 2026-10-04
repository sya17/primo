#!/usr/bin/env bash
# Turn the Primo Firefox styling off/on, to compare it with stock Firefox. Restart Firefox afterwards.
# Usage: firefox-theme.sh off | on | status
set -euo pipefail

base="${XDG_CONFIG_HOME:-$HOME/.config}/mozilla/firefox"; [[ -d "$base" ]] || base="$HOME/.mozilla/firefox"
rel="$(awk -F= '/^Default=/ {print $2; exit}' "$base/installs.ini" 2>/dev/null || true)"
profile="${FIREFOX_PROFILE:-${rel:+$base/$rel}}"
[[ -d "${profile:-}" ]] || { echo "Firefox profile not found (set FIREFOX_PROFILE)."; exit 1; }
chrome="$profile/chrome"

case "${1:-status}" in
    off)
        for f in userChrome userContent; do [[ -f "$chrome/$f.css" ]] && mv "$chrome/$f.css" "$chrome/$f.css.off"; done
        echo "Primo styling OFF. Quit Firefox completely (Ctrl+Q) and start it again." ;;
    on)
        for f in userChrome userContent; do [[ -f "$chrome/$f.css.off" ]] && mv "$chrome/$f.css.off" "$chrome/$f.css"; done
        echo "Primo styling ON. Quit Firefox completely (Ctrl+Q) and start it again." ;;
    status)
        if   [[ -f "$chrome/userChrome.css" ]];     then echo "on  ($profile)"
        elif [[ -f "$chrome/userChrome.css.off" ]]; then echo "off ($profile)"
        else echo "not installed ($profile)"; fi ;;
    *) echo "usage: ${0##*/} off|on|status" >&2; exit 2 ;;
esac
