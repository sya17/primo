# shellcheck shell=bash
# Sourced by the service wrappers (launcher.sh, switcher.sh, overview.sh, activity.sh, hub.sh).
#   ensure_service NAME DEST SCRIPT   make sure the service that owns the bus name DEST is running; otherwise exit 69 with a reason.
# The unit primo-NAME.service owns the start when it is enabled (install.sh --services); without it the service is started here, as before.
# Never both: an enabled unit that fails is reported, not followed by a second kind of start.
running() {
    gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner "$1" 2>/dev/null | grep -q true
}

ensure_service() {
    local name="$1" dest="$2" script="$3" why
    running "$dest" && return 0
    if systemctl --user is-enabled -q "primo-$name.service" 2>/dev/null; then
        systemctl --user start "primo-$name.service" >/dev/null 2>&1
        why="its systemd unit did not start it (systemctl --user status primo-$name.service)"
    else
        setsid -f python3 "$script" --daemon >/dev/null 2>&1
        why="it did not start (log: ${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles/log/$name.log)"
    fi
    for _ in $(seq 1 60); do running "$dest" && return 0; sleep 0.05; done
    echo "primo: the $name service is not available: $why" >&2
    command -v notify-send >/dev/null && notify-send -u low "Primo" "The $name service is not available"
    exit 69
}
