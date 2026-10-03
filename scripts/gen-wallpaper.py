#!/usr/bin/env python3
"""Generate a license-free gradient wallpaper from a theme's palette.

Usage: gen-wallpaper.py <theme> [WIDTHxHEIGHT]   (default 1920x1080)
Writes themes/<theme>/wallpaper.png. Pure standard library.
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
    rows.append(bytes(row))

def chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
    + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
out = root / "themes" / theme / "wallpaper.png"
out.write_bytes(png)
print(f"wrote {out} ({len(png) // 1024} KiB)")
