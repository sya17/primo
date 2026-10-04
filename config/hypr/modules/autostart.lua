-- https://wiki.hypr.land/Configuring/Basics/Autostart/
hl.on("hyprland.start", function()
    hl.exec_cmd("~/.config/hypr/scripts/wallpaper.sh restore") -- awww if installed, hyprpaper otherwise
    hl.exec_cmd("waybar")
    -- Notification daemon: swaync (with control center) when installed, dunst otherwise.
    hl.exec_cmd("sh -c 'command -v swaync >/dev/null && exec swaync || exec dunst'")
    hl.exec_cmd("swayosd-server --style ~/.config/swayosd/style.css") -- no-op until swayosd is installed
    hl.exec_cmd("python3 ~/.config/hypr/scripts/switcher.py --daemon")  -- Alt+Tab service
    hl.exec_cmd("python3 ~/.config/hypr/scripts/launcher.py --daemon")  -- launcher service (instant open)
    hl.exec_cmd("python3 ~/.config/hypr/scripts/overview.py --daemon")  -- overview service (instant open)
    hl.exec_cmd("hypridle")
    hl.exec_cmd("wl-paste --type text --watch cliphist store")
    hl.exec_cmd("wl-paste --type image --watch cliphist store")
    hl.exec_cmd("nm-applet --indicator")
    hl.exec_cmd("sh -c 'command -v blueman-applet >/dev/null && exec blueman-applet'") -- Bluetooth pairing agent
    hl.exec_cmd("~/.config/hypr/scripts/battery-watch.sh") -- low-battery warnings, auto Power Saver
    hl.exec_cmd("/usr/lib/polkit-kde-authentication-agent-1")
end)
