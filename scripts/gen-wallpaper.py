#!/usr/bin/env python3
"""Generate a license-free gradient wallpaper from a theme's palette.

Usage: gen-wallpaper.py <theme> [WIDTHxHEIGHT]   (default 1920x1080)
Writes themes/<theme>/wallpaper.png. Pure standard library.

Style comes from `wallpaper_style` in theme.conf:
  gradient  soft palette glows (default)
  lines     the same glows plus thin flowing contour lines in the accent colours
"""
import math, pathlib, random, struct, sys, zlib

root = pathlib.Path(__file__).resolve().parent.parent
theme = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
w, h = map(int, (sys.argv[2] if len(sys.argv) > 2 else "1920x1080").split("x"))

pal = {}
for line in (root / "themes" / theme / "theme.conf").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        pal[k.strip()] = v.strip()
rgb = lambda k: tuple(int(pal[k][i:i + 2], 16) for i in (0, 2, 4))
base, deep, a1, a2 = rgb("base"), rgb("crust"), rgb("accent"), rgb("accent2")

# Two soft glows: (cx, cy, radius, colour, strength)
glows = [(0.22 * w, 0.30 * h, 0.55 * w, a1, 0.38), (0.80 * w, 0.75 * h, 0.50 * w, a2, 0.32)]
style = pal.get("wallpaper_style", "gradient")
rnd = random.Random(7)
rows = []
for y in range(h):
    row = bytearray([0])
    for x in range(w):
        t = (x / w * 0.4 + y / h * 0.6)
        c = [deep[i] + (base[i] - deep[i]) * (1 - t) for i in range(3)]
        for cx, cy, r, col, s in glows:
            d = math.hypot(x - cx, y - cy) / r
            if d < 1:
                k = s * (1 - d) ** 2
                c = [c[i] + (col[i] - c[i]) * k for i in range(3)]
        n = rnd.random() - 0.5  # dither to hide banding
        row += bytes(max(0, min(255, int(v + n))) for v in c)
    rows.append(row)

if style == "lines":
    # Flowing contour lines: each curve is a few summed sines, drawn column by column with a
    # soft 1.6px falloff. Colour blends accent -> accent2 across the stack, fading toward the edges.
    n = 15
    for k in range(n):
        t = k / (n - 1)
        col = [a1[i] + (a2[i] - a1[i]) * t for i in range(3)]
        base_y = h * (0.20 + 0.62 * t)
        ph = 0.55 * k
        strength = 0.10 + 0.20 * math.sin(math.pi * t)   # strongest mid-stack
        for x in range(w):
            u = x / w
            y0 = (base_y + 0.085 * h * math.sin(u * 5.2 + ph)
                  + 0.040 * h * math.sin(u * 11.0 - ph * 1.7) + 0.05 * h * (u - 0.5) * (1 - 2 * t))
            fade = math.sin(math.pi * u) ** 0.8              # lines dissolve at the left/right edges
            for dy in range(-3, 4):
                yy = int(y0) + dy
                if 0 <= yy < h:
                    cov = max(0.0, 1.0 - abs(yy + 0.5 - y0) / 1.6) * strength * fade
                    if cov > 0:
                        o = 1 + x * 3
                        r = rows[yy]
                        for i in range(3):
                            r[o + i] = int(r[o + i] + (col[i] - r[o + i]) * cov)

def chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
    + chunk(b"IDAT", zlib.compress(b"".join(bytes(r) for r in rows), 9)) + chunk(b"IEND", b"")
out = root / "themes" / theme / "wallpaper.png"
out.write_bytes(png)
print(f"wrote {out} ({len(png) // 1024} KiB)")
