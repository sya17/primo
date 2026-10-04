-- https://wiki.hypr.land/Configuring/Basics/Window-Rules/
-- https://wiki.hypr.land/Configuring/Basics/Workspace-Rules/

hl.window_rule({
    name  = "suppress-maximize-events",
    match = { class = ".*" },
    suppress_event = "maximize",
})

hl.window_rule({
    name  = "fix-xwayland-drags",
    match = {
        class = "^$", title = "^$",
        xwayland = true, float = true, fullscreen = false, pin = false,
    },
    no_focus = true,
})

hl.window_rule({
    name  = "move-hyprland-run",
    match = { class = "hyprland-run" },
    move  = "20 monitor_h-120",
    float = true,
})

-- ── Utility apps: small floating windows instead of tiling ────────────────
-- Settings panels and pickers are used briefly, so they float centred at a sensible size.
local function utility(name, class, size)
    hl.window_rule({
        name  = "utility-" .. name,
        match = { class = class },
        float = true,
        center = true,
        size  = size,
    })
end

utility("pavucontrol",   "^org\\.pulseaudio\\.pavucontrol$", "820 560")
utility("nm-editor",     "^nm-connection-editor$",       "640 480")
utility("nwg-look",      "^nwg-look$",                    "900 640")
utility("nwg-displays",  "^nwg-displays$",                "1000 660")
utility("blueman",       "^blueman-manager$",             "640 480")
utility("polkit-agent",  "^org\\.kde\\.polkit-kde-authentication-agent-1$", "460 240")

-- File pickers from any app (GTK/Qt portals): float, centred, roomy.
hl.window_rule({
    name  = "file-dialogs",
    match = { title = "^(Open File|Open Files|Open Folder|Save As|Save File|Select .*|Choose .*)$" },
    float = true,
    center = true,
    size  = "900 600",
})

-- Clipboard history and Alt+Tab switcher: floating, centred, always on top of the workspace.
hl.window_rule({
    name  = "clipboard-picker",
    match = { class = "^dev\\.primo\\.Clipboard$" },
    float = true,
    size  = "620 560",
    move  = "monitor_w*0.5-310 monitor_h*0.5-280",
    stay_focused = true,
})
hl.window_rule({
    name  = "app-switcher",
    match = { class = "^dev\\.primo\\.Switcher$" },
    float = true,
    center = true,
    stay_focused = true,
    no_anim = true,
})

-- Settings window: centred, roomy.
hl.window_rule({
    name  = "settings-window",
    match = { class = "^dev\\.primo\\.Settings$" },
    float = true,
    size  = "980 660",
    move  = "monitor_w*0.5-490 monitor_h*0.5-330",
})

-- Confirmation dialogs (confirm.py): small, centred, above everything.
hl.window_rule({
    name  = "confirm-dialog",
    match = { class = "^dev\\.primo\\.Confirm$" },
    float = true,
    center = true,
    stay_focused = true,
})

-- Finder-style: the file manager opens as a centred floating window (SUPER+V tiles it).
hl.window_rule({
    name  = "files-window",
    match = { class = "^org\\.gnome\\.Nautilus$" },
    float = true,
    size  = "1100 700",
    move  = "monitor_w*0.5-550 monitor_h*0.5-330", -- GTK resizes after mapping, so `center` lands off-centre
})
-- Quick Look (select a file, press Space): floating preview in the middle of the screen.
hl.window_rule({
    name  = "quick-look",
    match = { class = "^org\\.gnome\\.NautilusPreviewer$" },
    float = true,
    center = true,
})

-- Firefox Picture-in-Picture: small, always on top, parked in the bottom-right corner.
hl.window_rule({
    name  = "firefox-pip",
    match = { class = "^firefox$", title = "^Picture-in-Picture$" },
    float = true,
    pin   = true,
    keep_aspect_ratio = true,
    size  = "480 270",
    move  = "monitor_w-496 monitor_h-286", -- size 480x270 + 16px margin
})

-- Do not lock/suspend while something is fullscreen (video, presentation, game).
hl.window_rule({
    name  = "idle-inhibit-fullscreen",
    match = { class = ".*" },
    idle_inhibit = "fullscreen",
})

-- Drop-down terminal (SUPER+grave): lives in the special workspace "term".
hl.window_rule({
    name  = "scratch-terminal",
    match = { class = "^scratchterm$" },
    float = true,
    center = true,
    size  = "monitor_w*0.75 monitor_h*0.55",
    workspace = "special:term",
})

-- Frosted-glass look: blur whatever sits behind the translucent bar, launcher and notifications.
for _, ns in ipairs({ "waybar", "wofi", "notifications", "swayosd", "swaync-control-center", "swaync-notification-window" }) do
    hl.layer_rule({
        name  = "blur-" .. ns,
        match = { namespace = "^" .. ns .. "$" },
        blur  = true,
        ignore_alpha = 0.3,
    })
end
