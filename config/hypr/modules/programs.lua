-- Default applications, shared by keybinds and rules.
return {
    terminal    = "kitty",
    fileManager = "~/.config/hypr/scripts/files.sh",            -- Nautilus, falls back to Dolphin
    powerFiles  = "env QT_QPA_PLATFORMTHEME=kde dolphin",       -- split view, tabs, bulk rename, ...
    menu        = "pkill wofi || wofi --show drun",
    clipboard   = "cliphist list | wofi --dmenu -p Clipboard | cliphist decode | wl-copy",
    lock        = "pidof hyprlock || hyprlock",
    closeWindow = "~/.config/hypr/scripts/close-window.sh",
    osd         = "~/.config/hypr/scripts/osd.sh",
    powerMenu   = "~/.config/hypr/scripts/power-menu.sh",
    nightlight  = "~/.config/hypr/scripts/nightlight.sh toggle",
    scratchTerm = "~/.config/hypr/scripts/scratch-terminal.sh",
    themeMenu   = "~/.config/hypr/scripts/theme-menu.sh",
    layoutCycle = "~/.config/hypr/scripts/layout-cycle.sh",
    toggleTheme = "hypr-theme toggle",
    screenshot  = "~/.config/hypr/scripts/screenshot.sh",
}
