#!/usr/bin/env python3
"""Draw the README banner, the GitHub social preview and the theme palette sheet from the real themes and the real mark.

Usage: scripts/gen-readme-assets.py        writes docs/assets/{banner-dark,banner-light,social-preview,themes}.png

Nothing here is invented: the colours come from themes/*/theme.conf, the mark from templates/logo/mark.svg.tpl.
Needs rsvg-convert (librsvg) and the Inter font; text is turned into pixels here, so GitHub needs no fonts.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "assets"
FONT = "Inter"
ORDER = ["primo-dusk", "primo-dawn", "catppuccin-mocha", "catppuccin-latte", "nord"]


def read_theme(name):
    d = {}
    for line in (ROOT / "themes" / name / "theme.conf").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = re.split(r"\s#", v)[0].strip()
    d["id"] = name
    d.setdefault("logo", d["accent"] if d["mode"] == "dark" else d["text"])
    d.setdefault("logo_accent", d["accent2"])
    return d


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mark(theme, x, y, size):
    """The Primo mark from the template, coloured for this theme."""
    svg = (ROOT / "templates" / "logo" / "mark.svg.tpl").read_text()
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    inner = re.sub(r"<!--.*?-->", "", inner, flags=re.S)
    inner = inner.replace("{{logo}}", theme["logo"]).replace("{{logo_accent}}", theme["logo_accent"])
    inner = inner.replace('fill="#', 'fill="#')
    return f'<g transform="translate({x} {y}) scale({size / 16})">{inner}</g>'


def chip(t, x, y, w, h, current):
    """One theme as a small card: its own background, name in its own text colour, three of its own colours."""
    ring = f' stroke="#{t["accent"]}" stroke-width="3"' if current else f' stroke="#{t["surface1"]}" stroke-width="1.5"'
    dots = "".join(f'<circle cx="{x + w - 36 - i * 30}" cy="{y + h / 2}" r="10" fill="#{t[k]}"/>' for i, k in enumerate(("accent2", "accent", "text")))
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="#{t["base"]}"{ring}/>'
            f'<text x="{x + 26}" y="{y + h / 2 + 8}" font-family="{FONT}" font-size="23" font-weight="500" fill="#{t["text"]}">{t["name"]}</text>' + dots)


def banner(panel, themes, w=1440, h=400, opaque=False, scale=1.0):
    """The wide banner: mark, name, one line; the five themes on the right."""
    t = panel
    assert contrast(t["text"], t["base"]) >= 7 and contrast(t["subtext"], t["base"]) >= 4.5, "banner text is too faint"
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
             f'<rect width="{w}" height="{h}" rx="{0 if opaque else 28}" fill="#{t["base"]}"/>']
    px, py = 96, 0
    mid = h / 2
    parts.append(mark(t, px, mid - 128 * scale, 104 * scale))
    parts.append(f'<text x="{px + 134 * scale}" y="{mid - 48 * scale}" font-family="{FONT}" font-size="{112 * scale}" font-weight="650" '
                 f'letter-spacing="-2.5" fill="#{t["text"]}">Primo</text>')
    parts.append(f'<text x="{px}" y="{mid + 44 * scale}" font-family="{FONT}" font-size="{42 * scale}" font-weight="400" fill="#{t["text"]}">One palette for the</text>')
    parts.append(f'<text x="{px}" y="{mid + 96 * scale}" font-family="{FONT}" font-size="{42 * scale}" font-weight="400" fill="#{t["text"]}">whole Hyprland desktop.</text>')
    cw, ch, gap = 400, 56, 14
    cx = w - 96 - cw
    top = mid - (len(themes) * ch + (len(themes) - 1) * gap) / 2
    for i, th in enumerate(themes):
        parts.append(chip(th, cx, top + i * (ch + gap), cw, ch, th["id"] == t["id"]))
    parts.append("</svg>")
    return "\n".join(parts)


def sheet(themes):
    """Every colour of every theme: one row each."""
    keys = ["base", "surface0", "surface1", "overlay", "subtext", "text", "accent", "accent2", "red", "orange", "yellow", "green", "cyan", "magenta"]
    w, rh = 1600, 132
    h = rh * len(themes) + 24
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    for i, t in enumerate(themes):
        y = 12 + i * rh
        parts.append(f'<rect x="12" y="{y}" width="{w - 24}" height="{rh - 14}" rx="18" fill="#{t["base"]}" stroke="#{t["surface1"]}" stroke-width="1.5"/>')
        parts.append(f'<text x="48" y="{y + 52}" font-family="{FONT}" font-size="30" font-weight="600" fill="#{t["text"]}">{t["name"]}</text>')
        parts.append(f'<text x="48" y="{y + 88}" font-family="{FONT}" font-size="21" fill="#{t["subtext"]}">{t["mode"]} · {t["font_sans"]}</text>')
        for j, k in enumerate(keys):
            cx = 430 + j * 82
            parts.append(f'<rect x="{cx}" y="{y + 26}" width="62" height="62" rx="14" fill="#{t[k]}" stroke="#{t["surface1"]}" stroke-width="1"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def render(svg, out, width=None):
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg)
        src = f.name
    cmd = ["rsvg-convert", src, "-o", str(out)] + (["-w", str(width)] if width else [])
    subprocess.run(cmd, check=True)
    Path(src).unlink()
    return out.stat().st_size


def main():
    if not shutil.which("rsvg-convert"):
        sys.exit("rsvg-convert is required (librsvg)")
    OUT.mkdir(parents=True, exist_ok=True)
    themes = [read_theme(n) for n in ORDER]
    by = {t["id"]: t for t in themes}
    sizes = {
        "banner-dark.png": render(banner(by["primo-dusk"], themes), OUT / "banner-dark.png"),
        "banner-light.png": render(banner(by["primo-dawn"], themes), OUT / "banner-light.png"),
        "social-preview.png": render(banner(by["primo-dusk"], themes, w=1280, h=640, opaque=True, scale=1.0), OUT / "social-preview.png"),
        "themes.png": render(sheet(themes), OUT / "themes.png"),
    }
    for name, size in sizes.items():
        print(f"  {name}  {size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
