#!/usr/bin/env bash
# SUPER+E: open the file manager. Nautilus (Finder-like) when installed, Dolphin otherwise.
if command -v nautilus >/dev/null; then
    exec nautilus --new-window "${1:-$HOME}"
fi
exec env QT_QPA_PLATFORMTHEME=kde dolphin "${1:-$HOME}"
