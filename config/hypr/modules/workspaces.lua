-- Each workspace has a purpose and a matching layout. SUPER+TAB cycles the layout of the
-- current workspace (see scripts/layout-cycle.sh); the bar shows the active one.
-- Layouts: dwindle (binary tiling), master (one big window + stack),
--          scrolling (a horizontal strip you scroll through), monocle (one window at a time).
local presets = {
    ["1"] = "dwindle",   -- general
    ["2"] = "master",    -- code: editor large, terminals stacked beside it
    ["3"] = "scrolling", -- reading / media: windows side by side on a strip
    ["4"] = "monocle",   -- focus: one window, full screen area
}
for workspace, layout in pairs(presets) do
    hl.workspace_rule({ workspace = workspace, layout = layout })
end
