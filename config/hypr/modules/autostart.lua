-- https://wiki.hypr.land/Configuring/Basics/Autostart/
hl.on("hyprland.start", function()
    hl.exec_cmd("hyprpaper")
    hl.exec_cmd("waybar")
    -- Notification daemon: swaync (with control center) when installed, dunst otherwise.
    hl.exec_cmd("sh -c 'command -v swaync >/dev/null && exec swaync || exec dunst'")
    hl.exec_cmd("swayosd-server --style ~/.config/swayosd/style.css") -- no-op until swayosd is installed
    hl.exec_cmd("hypridle")
    hl.exec_cmd("wl-paste --type text --watch cliphist store")
    hl.exec_cmd("wl-paste --type image --watch cliphist store")
    hl.exec_cmd("nm-applet --indicator")
    hl.exec_cmd("/usr/lib/polkit-kde-authentication-agent-1")
end)
