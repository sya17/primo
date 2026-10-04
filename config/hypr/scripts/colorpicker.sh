#!/usr/bin/env bash
# Pick any colour on screen (hyprpicker): copies the hex value and shows a notification with a swatch.
# Usage: colorpicker.sh
set -uo pipefail

command -v hyprpicker >/dev/null || { notify-send -u critical "Colour picker" "Install hyprpicker (pacman -S hyprpicker)"; exit 1; }
color="$(hyprpicker -a 2>/dev/null)" || exit 0          # Esc cancels
[[ "$color" =~ ^#[0-9a-fA-F]{6}$ ]] || exit 0

# A small PNG swatch for the notification icon
swatch="${XDG_RUNTIME_DIR:-/tmp}/primo-swatch.png"
python3 - "$color" "$swatch" <<'PY'
import struct, sys, zlib
hexstr, out = sys.argv[1].lstrip("#"), sys.argv[2]
r, g, b = (int(hexstr[i:i + 2], 16) for i in (0, 2, 4))
w = h = 64
rows = b"".join(b"\x00" + bytes([r, g, b]) * w for _ in range(h))
def chunk(t, d):
    body = t + d
    return struct.pack(">I", len(d)) + body + struct.pack(">I", zlib.crc32(body))
open(out, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                      + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
PY
notify-send -a "Colour picker" -i "$swatch" -t 4000 "$color" "Copied to the clipboard"
