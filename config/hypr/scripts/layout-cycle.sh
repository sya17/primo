#!/usr/bin/env bash
# Layout of the current workspace.
# Usage: layout-cycle.sh            switch to the next layout (dwindle > master > scrolling > monocle)
#        layout-cycle.sh status     JSON for Waybar
set -uo pipefail

layouts=(dwindle master scrolling monocle)
info="$(hyprctl activeworkspace)"
ws="$(awk '/^workspace ID/ {print $3; exit}' <<<"$info")"
current="$(awk -F': ' '/tiledLayout/ {print $2; exit}' <<<"$info")"

if [[ "${1:-}" == "status" ]]; then
    printf '{"text":"","alt":"%s","class":"%s","tooltip":"Layout: %s (SUPER+TAB to change)"}\n' "$current" "$current" "$current"
    exit 0
fi

next="${layouts[0]}"
for i in "${!layouts[@]}"; do
    [[ "${layouts[$i]}" == "$current" ]] && next="${layouts[$(( (i + 1) % ${#layouts[@]} ))]}"
done

hyprctl eval "hl.workspace_rule({ workspace = \"$ws\", layout = \"$next\" })" >/dev/null
pkill -RTMIN+10 waybar 2>/dev/null
notify-send -h string:x-dunst-stack-tag:layout -h string:x-canonical-private-synchronous:layout -t 1200 "Layout" "${next^}"
