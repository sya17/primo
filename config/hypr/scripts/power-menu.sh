#!/usr/bin/env bash
# Power menu in the launcher style; destructive actions ask for confirmation.
# Usage: power-menu.sh            show the menu
#        power-menu.sh logout     log out (with confirmation), e.g. for a keybind
set -uo pipefail

style="$HOME/.config/wofi/menu.css"

confirm() { # "Question" "Button"
    if command -v hyprland-dialog >/dev/null; then
        [[ "$(hyprland-dialog --title "$1" --text "$1" --buttons "$2;Cancel" 2>/dev/null)" == "$2"* ]]
    else
        return 0
    fi
}

logout() {
    command -v hyprshutdown >/dev/null 2>&1 && exec hyprshutdown
    hyprctl dispatch 'hl.dsp.exit()'
}

run() {
    case "$1" in
        lock)     pidof hyprlock >/dev/null || hyprlock ;;
        suspend)  systemctl suspend ;;
        logout)   confirm "Log out of Hyprland?" "Log out" && logout ;;
        reboot)   confirm "Restart the computer?" "Restart" && systemctl reboot ;;
        shutdown) confirm "Shut down the computer?" "Shut down" && systemctl poweroff ;;
    esac
}

[[ "${1:-}" == "logout" ]] && { run logout; exit 0; }

choice="$(printf '%s\n' \
    $'  Lock' \
    $'  Suspend' \
    $'  Log out' \
    $'  Restart' \
    $'  Shut down' |
    wofi --dmenu --style "$style" --width 230 --lines 5 --location center \
         --hide-search true --prompt "" --cache-file /dev/null)" || exit 0

case "$choice" in
    *Lock)      run lock ;;
    *Suspend)   run suspend ;;
    *"Log out") run logout ;;
    *Restart)   run reboot ;;
    *"Shut down") run shutdown ;;
esac
