#!/usr/bin/env bash
# Drop-down terminal: toggles the special workspace "term".
# The window rule "scratch-terminal" (modules/rules.lua) floats it and sends it there;
# on first use we start it and wait for it to appear (Hyprland then reveals the workspace).
set -uo pipefail

has_window() { hyprctl clients | grep -q 'class: scratchterm'; }

if ! has_window; then
    setsid -f kitty --class scratchterm >/dev/null 2>&1
    for _ in $(seq 1 30); do has_window && exit 0; sleep 0.1; done
    exit 1
fi
hyprctl dispatch 'hl.dsp.workspace.toggle_special("term")' >/dev/null
