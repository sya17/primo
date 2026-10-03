-- Motion language: spring physics for things that move (windows), short eased fades for
-- things that appear (layers), and a gentle slide+fade between workspaces.
-- https://wiki.hypr.land/Configuring/Advanced-and-Cool/Animations/
hl.config({ animations = { enabled = true } })

-- Springs feel alive: a little overshoot, then settle (the macOS/iOS feel).
hl.curve("soft",   { type = "spring", mass = 1, stiffness = 170, dampening = 22 }) -- windows opening / moving
hl.curve("snappy", { type = "spring", mass = 1, stiffness = 320, dampening = 28 }) -- small, quick elements

hl.curve("easeOutQuint", { type = "bezier", points = { {0.23, 1},    {0.32, 1} } })
hl.curve("easeInQuad",   { type = "bezier", points = { {0.55, 0.085}, {0.68, 0.53} } })
hl.curve("linear",       { type = "bezier", points = { {0, 0},       {1, 1}    } })

hl.animation({ leaf = "global",        enabled = true, speed = 10,   bezier = "default" })

-- Windows: pop in with a spring, leave quickly and quietly.
hl.animation({ leaf = "windows",       enabled = true, speed = 4.5,  spring = "soft" })
hl.animation({ leaf = "windowsIn",     enabled = true, speed = 4.2,  spring = "soft",  style = "popin 84%" })
hl.animation({ leaf = "windowsOut",    enabled = true, speed = 2.2,  bezier = "easeInQuad", style = "popin 90%" })

-- Borders / focus colour crossfade.
hl.animation({ leaf = "border",        enabled = true, speed = 6,    bezier = "easeOutQuint" })
hl.animation({ leaf = "fade",          enabled = true, speed = 3.2,  bezier = "easeOutQuint" })
hl.animation({ leaf = "fadeIn",        enabled = true, speed = 2.4,  bezier = "easeOutQuint" })
hl.animation({ leaf = "fadeOut",       enabled = true, speed = 1.8,  bezier = "linear" })

-- Bar, launcher, notifications, OSD: settle in like Control Center.
hl.animation({ leaf = "layers",        enabled = true, speed = 4,    spring = "snappy" })
hl.animation({ leaf = "layersIn",      enabled = true, speed = 4,    spring = "snappy", style = "popin 92%" })
hl.animation({ leaf = "layersOut",     enabled = true, speed = 2.5,  bezier = "easeOutQuint", style = "fade" })
hl.animation({ leaf = "fadeLayersIn",  enabled = true, speed = 2.4,  bezier = "easeOutQuint" })
hl.animation({ leaf = "fadeLayersOut", enabled = true, speed = 2,    bezier = "linear" })

-- Workspaces: slide a little while fading, so the direction reads without a hard swipe.
hl.animation({ leaf = "workspaces",    enabled = true, speed = 4,    bezier = "easeOutQuint", style = "slidefade 14%" })
hl.animation({ leaf = "specialWorkspace", enabled = true, speed = 4, bezier = "easeOutQuint", style = "slidefadevert 20%" })

hl.animation({ leaf = "zoomFactor",    enabled = true, speed = 6,    bezier = "easeOutQuint" })
