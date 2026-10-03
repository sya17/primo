-- https://wiki.hypr.land/Configuring/Basics/Binds/
local programs = require("modules.programs")
local mod = "SUPER"

-- Apps
hl.bind(mod .. " + Q",      hl.dsp.exec_cmd(programs.terminal))
hl.bind(mod .. " + Return", hl.dsp.exec_cmd(programs.terminal))
hl.bind(mod .. " + E",      hl.dsp.exec_cmd(programs.fileManager))
hl.bind(mod .. " + SHIFT + E", hl.dsp.exec_cmd(programs.powerFiles))
hl.bind(mod .. " + R",      hl.dsp.exec_cmd(programs.menu))
hl.bind(mod .. " + L",      hl.dsp.exec_cmd(programs.lock))
hl.bind(mod .. " + SHIFT + V", hl.dsp.exec_cmd(programs.clipboard))
hl.bind(mod .. " + D",      hl.dsp.exec_cmd("nwg-displays"))
hl.bind(mod .. " + T",      hl.dsp.exec_cmd(programs.themeMenu))
hl.bind(mod .. " + SHIFT + T", hl.dsp.exec_cmd(programs.toggleTheme)) -- dark <-> light

-- Session: SUPER+X power menu, SUPER+M logs out (after confirmation)
hl.bind(mod .. " + X", hl.dsp.exec_cmd(programs.powerMenu))
hl.bind(mod .. " + M", hl.dsp.exec_cmd(programs.powerMenu .. " logout"))
hl.bind(mod .. " + N", hl.dsp.exec_cmd(programs.nightlight))

-- Window management
-- Confirms first when a terminal still has a program running; SHIFT forces an immediate close.
hl.bind(mod .. " + C",         hl.dsp.exec_cmd(programs.closeWindow))
hl.bind(mod .. " + SHIFT + C", hl.dsp.window.close())
hl.bind(mod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + P", hl.dsp.window.pseudo())
hl.bind(mod .. " + J", hl.dsp.layout("togglesplit")) -- dwindle only
hl.bind(mod .. " + F", hl.dsp.window.fullscreen())
hl.bind(mod .. " + Tab", hl.dsp.exec_cmd(programs.layoutCycle)) -- next layout for this workspace

-- Focus
hl.bind(mod .. " + left",  hl.dsp.focus({ direction = "left" }))
hl.bind(mod .. " + right", hl.dsp.focus({ direction = "right" }))
hl.bind(mod .. " + up",    hl.dsp.focus({ direction = "up" }))
hl.bind(mod .. " + down",  hl.dsp.focus({ direction = "down" }))

-- Workspaces: SUPER + [0-9] switches, SUPER + SHIFT + [0-9] moves the window
for i = 1, 10 do
    local key = i % 10 -- workspace 10 is on key 0
    hl.bind(mod .. " + " .. key,         hl.dsp.focus({ workspace = i }))
    hl.bind(mod .. " + SHIFT + " .. key, hl.dsp.window.move({ workspace = i }))
end

-- Scratchpad: SUPER+grave drop-down terminal, SUPER+S generic scratchpad
hl.bind(mod .. " + grave", hl.dsp.exec_cmd(programs.scratchTerm))
hl.bind(mod .. " + S",         hl.dsp.workspace.toggle_special("magic"))
hl.bind(mod .. " + ALT + S",   hl.dsp.window.move({ workspace = "special:magic" }))

hl.bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up",   hl.dsp.focus({ workspace = "e-1" }))

-- Mouse move / resize
hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- Screenshots (grim + slurp + wl-clipboard)
hl.bind(mod .. " + SHIFT + S", hl.dsp.exec_cmd(programs.screenshot .. " area"), { release = true })
hl.bind("Print",               hl.dsp.exec_cmd(programs.screenshot .. " area"))
hl.bind("SHIFT + Print",       hl.dsp.exec_cmd(programs.screenshot .. " full"))

-- Media keys: OSD feedback via osd.sh (swayosd when installed, dunst otherwise)
local locked  = { locked = true }
local repeats = { locked = true, repeating = true }
local osd = function(action) return hl.dsp.exec_cmd(programs.osd .. " " .. action) end
hl.bind("XF86AudioRaiseVolume",  osd("volume-up"),       repeats)
hl.bind("XF86AudioLowerVolume",  osd("volume-down"),     repeats)
hl.bind("XF86AudioMute",         osd("volume-mute"),     repeats)
hl.bind("XF86AudioMicMute",      osd("mic-mute"),        repeats)
hl.bind("XF86MonBrightnessUp",   osd("brightness-up"),   repeats)
hl.bind("XF86MonBrightnessDown", osd("brightness-down"), repeats)
hl.bind("XF86AudioNext",         hl.dsp.exec_cmd("playerctl next"),       locked)
hl.bind("XF86AudioPause",        hl.dsp.exec_cmd("playerctl play-pause"), locked)
hl.bind("XF86AudioPlay",         hl.dsp.exec_cmd("playerctl play-pause"), locked)
hl.bind("XF86AudioPrev",         hl.dsp.exec_cmd("playerctl previous"),   locked)
