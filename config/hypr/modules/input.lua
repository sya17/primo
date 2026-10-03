-- https://wiki.hypr.land/Configuring/Basics/Variables/#input
hl.config({
    input = {
        kb_layout    = "us",
        follow_mouse = 1,
        sensitivity  = 0, -- -1.0 to 1.0, 0 = no modification

        touchpad = { natural_scroll = false },
    },
})

hl.gesture({
    fingers   = 3,
    direction = "horizontal",
    action    = "workspace",
})

-- Per-device overrides: https://wiki.hypr.land/Configuring/Advanced-and-Cool/Devices/
-- hl.device({ name = "my-mouse", sensitivity = -0.5 })
