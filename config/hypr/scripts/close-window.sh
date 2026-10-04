#!/usr/bin/env bash
# Close the active window; ask first when it is a terminal that still has a
# program running (ssh, a build, an editor, ...).
#
# Usage: close-window.sh           close, with confirmation when busy
#        close-window.sh --check   print the busy processes of the active window
#
# SUPER+SHIFT+C bypasses this script and closes immediately.
set -uo pipefail

terminals='^(kitty|foot|footclient|Alacritty|alacritty|ghostty|com\.mitchellh\.ghostty|org\.wezfurlong\.wezterm|org\.kde\.konsole|konsole|xterm|org\.gnome\.Terminal|st-256color)$'
shells='^(bash|zsh|fish|sh|dash|ksh|tcsh|nu|kitten)$'   # shells + terminal helper processes

active="$(hyprctl activewindow 2>/dev/null)"
[[ -n "$active" ]] || exit 0
class="$(awk -F': ' '/^\s*class:/ {print $2; exit}' <<<"$active")"
pid="$(awk -F': ' '/^\s*pid:/ {print $2; exit}' <<<"$active")"

close_now() { hyprctl dispatch 'hl.dsp.window.close()' >/dev/null; }

# Names of all non-shell descendants of $1 (the terminal's own process tree).
busy_processes() {
    ps -eo pid=,ppid=,comm= | awk -v root="$1" -v shells="$shells" '
        { ppid[$1] = $2; comm[$1] = $3; kids[$2] = kids[$2] " " $1 }
        END {
            n = split(kids[root], queue, " ")
            for (i = 1; i <= n; i++) {
                p = queue[i]
                if (comm[p] !~ shells) seen[comm[p]] = 1
                m = split(kids[p], sub_, " ")
                for (j = 1; j <= m; j++) queue[++n] = sub_[j]
            }
            for (c in seen) printf "%s\n", c
        }' | sort
}

if [[ "${1:-}" == "--check" ]]; then
    [[ -n "${2:-}" ]] && pid="$2" || class="${class:-?}"
    echo "class=${class:-?} pid=${pid:-?}"
    busy_processes "${pid:-0}"
    exit 0
fi

if [[ ! "$class" =~ $terminals || -z "$pid" ]]; then
    close_now; exit 0
fi

busy="$(busy_processes "$pid" | paste -sd, - | sed 's/,/, /g')"
[[ -z "$busy" ]] && { close_now; exit 0; }

text="Still running in this terminal: ${busy}.

Closing it will stop these programs and may lose unsaved work."

confirmed() {
    local confirm="$(dirname "$0")/confirm.py"
    if [[ -x "$confirm" ]] && python3 -c 'import gi' 2>/dev/null; then
        "$confirm" --title "Close terminal?" --text "$text" --confirm "Close anyway" --danger
    elif command -v hyprland-dialog >/dev/null; then
        [[ "$(hyprland-dialog --title "Close terminal?" --text "$text" --buttons "Close anyway;Cancel" 2>/dev/null)" == "Close anyway"* ]]
    else
        return 0
    fi
}
confirmed && close_now
exit 0
