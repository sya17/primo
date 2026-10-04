#!/usr/bin/env bash
# Screen recording with wf-recorder.
# Usage: record.sh toggle [area|full] [--audio]   start, or stop if already recording
#        record.sh stop
#        record.sh status                          JSON for Waybar
# Files go to ~/Videos/Recordings. The bar shows a red timer while recording.
set -uo pipefail

dir="${XDG_VIDEOS_DIR:-$HOME/Videos}/Recordings"
pidfile="${XDG_RUNTIME_DIR:-/tmp}/primo-recorder.pid"
filefile="${XDG_RUNTIME_DIR:-/tmp}/primo-recorder.file"
here="$(dirname "$0")"

recording() { [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; }
refresh_bar() { pkill -RTMIN+11 waybar 2>/dev/null || true; }

status() {
    if recording; then
        local secs=$(( $(date +%s) - $(stat -c %Y "$pidfile") ))
        printf '{"text":"\\uf111 %02d:%02d","class":"recording","tooltip":"Recording. Click to stop."}\n' $((secs / 60)) $((secs % 60))
    else
        printf '{"text":"","class":"idle","tooltip":""}\n'
    fi
}

start() { # mode audio
    command -v wf-recorder >/dev/null || { notify-send -u critical "Recording" "Install wf-recorder (pacman -S wf-recorder)"; exit 1; }
    mkdir -p "$dir"
    local file="$dir/$(date +%Y-%m-%d_%H-%M-%S).mp4" args=(-f "$file")
    if [[ "$1" == area ]]; then
        # shellcheck disable=SC1091
        [[ -f "$here/../theme.env" ]] && source "$here/../theme.env"
        local region
        region="$(slurp -b "#${P_BASE:-1e1e2e}80" -c "#${P_RED:-ff6b81}ff" -s "#${P_RED:-ff6b81}22" -w 2)" || exit 0
        args+=(-g "$region")
    fi
    [[ "$2" == yes ]] && args+=(-a)
    setsid -f wf-recorder "${args[@]}" >/dev/null 2>&1
    sleep 0.4
    pgrep -nx wf-recorder > "$pidfile" || { notify-send -u critical "Recording" "wf-recorder did not start"; exit 1; }
    echo "$file" > "$filefile"
    notify-send -a Recording -t 2500 "Recording started" "Press the shortcut again or click the red timer to stop"
    refresh_bar
}

stop() {
    recording || { rm -f "$pidfile"; return 0; }
    local pid file; pid="$(cat "$pidfile")"; file="$(cat "$filefile" 2>/dev/null)"
    kill -INT "$pid" 2>/dev/null
    for _ in $(seq 1 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    rm -f "$pidfile"; refresh_bar
    (
        action="$(notify-send -a Recording -A play="Play" -A folder="Show in folder" -w \
            "Recording saved" "${file##*/}" 2>/dev/null || true)"
        case "$action" in
            play)   xdg-open "$file" ;;
            folder) command -v nautilus >/dev/null && nautilus --select "$file" || xdg-open "$dir" ;;
        esac
    ) >/dev/null 2>&1 &
    disown
}

case "${1:-status}" in
    status) status ;;
    stop) stop ;;
    toggle)
        if recording; then stop; exit 0; fi
        mode=area; audio=no
        for a in "${@:2}"; do case "$a" in area|full) mode="$a" ;; --audio) audio=yes ;; esac; done
        start "$mode" "$audio" ;;
    *) echo "usage: ${0##*/} toggle [area|full] [--audio] | stop | status" >&2; exit 2 ;;
esac
