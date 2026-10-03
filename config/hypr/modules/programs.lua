-- Default applications, shared by keybinds and rules.
return {
    terminal    = "kitty",
    fileManager = "dolphin",
    menu        = "pkill wofi || wofi --show drun",
    clipboard   = "cliphist list | wofi --dmenu -p Clipboard | cliphist decode | wl-copy",
    lock        = "pidof hyprlock || hyprlock",
    closeWindow = "~/.config/hypr/scripts/close-window.sh",
    toggleTheme = "hypr-theme toggle",
    screenshot  = "~/.config/hypr/scripts/screenshot.sh",
}
