-- Look and feel. Values come from the active theme (generated theme.lua);
-- the fallback keeps Hyprland usable before `theme-switch` has ever run.
-- https://wiki.hypr.land/Configuring/Basics/Variables/
local ok, theme = pcall(require, "theme")
if not ok and not tostring(theme):find("module 'theme' not found", 1, true) then
    error(theme) -- theme.lua exists but is broken: do not hide it
end
if not ok then
    theme = {
        border_size = 2, gaps_in = 5, gaps_out = 12, rounding = 10,
        blur_size = 3, blur_passes = 1,
        colors = {
            active_border   = { "rgba(33ccffee)" },
            inactive_border = "rgba(595959aa)",
            shadow          = "rgba(1a1a1aee)",
        },
    }
end

hl.config({
    general = {
        gaps_in     = theme.gaps_in,
        gaps_out    = theme.gaps_out,
        border_size = theme.border_size,

        col = {
            active_border   = { colors = theme.colors.active_border, angle = 45 },
            inactive_border = theme.colors.inactive_border,
        },

        resize_on_border = false,
        allow_tearing    = false,
        layout           = "dwindle",
    },

    decoration = {
        rounding       = theme.rounding,
        rounding_power = 2,

        active_opacity   = 1.0,
        inactive_opacity = 1.0,

        shadow = {
            enabled      = true,
            range        = 4,
            render_power = 3,
            color        = theme.colors.shadow,
        },

        blur = {
            enabled  = true,
            size     = theme.blur_size,
            passes   = theme.blur_passes,
            vibrancy = 0.1696,
        },
    },

    dwindle = { preserve_split = true },
    master  = { new_status = "master" },

    misc = {
        force_default_wallpaper = 0,
        disable_hyprland_logo   = true,
    },
})
