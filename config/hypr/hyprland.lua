-- Hyprland entry point. Each concern lives in modules/.
-- Docs: https://wiki.hypr.land/Configuring/Start/
--
-- Machine-specific overrides (monitors, devices, ...) go in ~/.config/hypr/local.lua,
-- which is git-ignored and loaded last.

require("modules.monitors")
pcall(require, "displays") -- written by Primo Settings (git-ignored); overrides the defaults
require("modules.env")
require("modules.appearance")
require("modules.animations")
require("modules.input")
require("modules.workspaces")
require("modules.keybinds")
require("modules.rules")
require("modules.autostart")

pcall(require, "local")
