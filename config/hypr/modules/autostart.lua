-- https://wiki.hypr.land/Configuring/Basics/Autostart/
hl.on("hyprland.start", function()
    hl.exec_cmd("~/.config/hypr/scripts/wallpaper.sh restore") -- awww if installed, hyprpaper otherwise
    hl.exec_cmd("~/.config/hypr/scripts/wallpaper-rotate.sh") -- slideshow loop, idle unless enabled in Settings
    hl.exec_cmd("waybar")
    -- Notification daemon: swaync (with control center) when installed, dunst otherwise.
    hl.exec_cmd("python3 ~/.config/hypr/scripts/control_center.py start")
    hl.exec_cmd("swayosd-server --style ~/.config/swayosd/style.css") -- no-op until swayosd is installed
    hl.exec_cmd("sh -c 'systemctl --user is-enabled -q primo-switcher.service 2>/dev/null || exec python3 ~/.config/hypr/scripts/switcher.py --daemon'")  -- Alt+Tab service
    hl.exec_cmd("sh -c 'systemctl --user is-enabled -q primo-launcher.service 2>/dev/null || exec python3 ~/.config/hypr/scripts/launcher.py --daemon'")  -- launcher service (instant open)
    -- overview service (instant open): started here only while its systemd user unit is not enabled (install.sh --services)
    hl.exec_cmd("sh -c 'systemctl --user is-enabled -q primo-overview.service 2>/dev/null || exec python3 ~/.config/hypr/scripts/overview.py --daemon'")
    hl.exec_cmd("sh -c 'systemctl --user is-enabled -q primo-hub.service 2>/dev/null || exec python3 ~/.config/hypr/scripts/hub.py --daemon'")  -- time hub: keeps timers, alarms and reminders running
    hl.exec_cmd("sh -c 'systemctl --user is-enabled -q primo-activity.service 2>/dev/null || exec python3 ~/.config/hypr/scripts/activity.py --daemon'")  -- Activity service; measures only while open
    hl.exec_cmd("python3 ~/.config/hypr/scripts/idle_core.py")
    hl.exec_cmd("wl-paste --type text --watch cliphist store")
    hl.exec_cmd("wl-paste --type image --watch cliphist store")
    hl.exec_cmd("nm-applet --indicator")
    hl.exec_cmd("sh -c 'command -v blueman-applet >/dev/null && exec blueman-applet'") -- Bluetooth pairing agent
    hl.exec_cmd("~/.config/hypr/scripts/battery-watch.sh") -- low-battery warnings, auto Power Saver
    hl.exec_cmd("/usr/lib/polkit-kde-authentication-agent-1")
end)
