#!/usr/bin/env bash
# Pick a theme from a small menu (SUPER+T). Applies it with hypr-theme.
set -uo pipefail

style="$HOME/.config/wofi/menu.css"
current="$(hypr-theme --current 2>/dev/null)"

entries=""; count=0
while read -r name mode; do
    icon=$''; [[ "$mode" == light ]] && icon=$''          # moon / sun
    mark="   "; [[ "$name" == "$current" ]] && mark=$'  '        # check on the active theme
    entries+="${mark}${icon}   ${name}"$'\n'; count=$((count + 1))
done < <(hypr-theme --list)

choice="$(printf '%s' "$entries" |
    wofi --dmenu --style "$style" --width 300 --lines "$count" --location center \
         --hide-search true --prompt "" --cache-file /dev/null)" || exit 0

name="${choice##* }"
[[ -n "$name" ]] && hypr-theme "$name"
