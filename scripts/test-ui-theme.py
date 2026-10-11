#!/usr/bin/env python3
"""Checks for the shared GTK4 roles (templates/gtk/primo-ui.css.tpl): every shipped theme renders them from its current keys, GTK3 does not
get them, rendering is repeatable and fails safely on an unknown placeholder, the selectors stay inside the two pilots, the colour pairs
the roles rely on meet the contrast rules, and (with a display) GTK parses the result.

Runs scripts/theme-switch on a throw-away copy of the repository with temporary HOME/XDG folders and stubbed reload commands: nothing
here reaches the running desktop or the live generated files."""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
work = Path(tempfile.mkdtemp(prefix="primo ui "))
repo = work / "repo"
shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
env = dict(os.environ, HOME=str(work / "home"), XDG_CONFIG_HOME=str(work / "config"), XDG_DATA_HOME=str(work / "data"),
           XDG_STATE_HOME=str(work / "state"), PRIMO_NO_RELOAD="1", PRIMO_LOGIN_DIR=str(work / "login"), LIVE_LOG=str(work / "live-calls"))
for sub in ("home", "config", "data", "state"):
    (work / sub).mkdir()
stubs = work / "bin"
stubs.mkdir()
for tool in ("hyprctl", "pkill", "gsettings", "dunstctl", "swaync-client", "swayosd-server", "setsid", "notify-send", "kwriteconfig6"):
    (stubs / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "$LIVE_LOG"\n')
    (stubs / tool).chmod(0o755)
env["PATH"] = f"{stubs}:{os.environ['PATH']}"
for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
    assert env[key].startswith(str(work)) and Path(env[key]) != Path.home(), "the test must never write outside its own folder"
(work / "live-calls").write_text("")
SWITCH = repo / "scripts" / "theme-switch"
GTK4 = work / "config" / "gtk-4.0" / "gtk.css"
GTK3 = work / "config" / "gtk-3.0" / "gtk.css"
HEAD = "Primo shared UI roles"


def render(theme):
    return subprocess.run([str(SWITCH), "--no-reload", theme], env=env, capture_output=True, text=True, timeout=120)


def conf(theme):
    values = {}
    for line in (repo / "themes" / theme / "theme.conf").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            values[k.strip()] = v.split(" #")[0].strip()
    return values


def luminance(hexa):
    c = [int(hexa[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def blend(top, bottom, alpha):
    return "".join(f"{round(int(top[i:i + 2], 16) * alpha + int(bottom[i:i + 2], 16) * (1 - alpha)):02x}" for i in (0, 2, 4))


themes = sorted(p.name for p in (repo / "themes").iterdir() if (p / "theme.conf").exists())
assert {"primo-dusk", "primo-dawn"} <= set(themes), themes
rendered = {}
for theme in themes:
    done = render(theme)
    assert done.returncode == 0, (theme, done.stderr[-300:])
    css4, css3 = GTK4.read_text(), GTK3.read_text()
    v = conf(theme)
    assert HEAD in css4 and "{{" not in css4, theme
    assert HEAD not in css3 and "primo-popup" not in css3 and "mix(" not in css3, (theme, "GTK3 must not get GTK4-only roles")
    section = css4[css4.index(HEAD):]
    assert f"border-radius: {int(v['rounding']) + 6}px" in section and f"border-radius: {v['rounding']}px" in section, theme
    assert f"color: #{v['subtext']}" in section, theme
    rendered[theme] = css4
    again = render(theme)
    assert again.returncode == 0 and GTK4.read_text() == css4, (theme, "rendering twice gives the same file")

# ---- selectors stay inside the two pilots (and their policy classes)
section = rendered["primo-dusk"][rendered["primo-dusk"].index("/* ---- " + HEAD):]
body = re.sub(r"/\*.*?\*/", "", section, flags=re.S)
selectors = [s.strip() for block in body.split("}") if "{" in block for s in block.split("{")[0].split(",")]
assert selectors and all(re.match(r"^window\.(primo-launcher|primo-settings|primo-opaque|primo-reduce-motion)\b", s) for s in selectors), \
    [s for s in selectors if not s.startswith("window.primo-")]
for state in ("selected", "disabled", "error", "muted", "popup", "surface", "control", "active"):
    assert f".primo-{state}" in section, state
assert ":focus-visible" in section and "primo-opaque" in section and "primo-reduce-motion" in section

# ---- contrast of the pairs the roles use, in every shipped theme (opaque pairs; alpha over a real widget stays a visual check)
for theme in themes:
    v = conf(theme)
    pairs = {"text on window": (v["text"], v["base"], 4.5), "text on card": (v["text"], v["surface0"], 4.5), "muted on window": (v["subtext"], v["base"], 4.5),
             "text on selected row": (v["text"], blend(v["accent"], v["base"], 0.30), 4.5),
             "accent on window, large text and icons": (v["accent"], v["base"], 3.0), "error on window, large text and icons": (v["red"], v["base"], 3.0)}
    for name, (fg, bg, need) in pairs.items():
        assert contrast(fg, bg) >= need, (theme, name, round(contrast(fg, bg), 2), need)

# ---- a missing placeholder fails, and the file it would have written is left as it was
before = GTK4.read_text()
tpl = repo / "templates" / "gtk" / "primo-ui.css.tpl"
good = tpl.read_text()
tpl.write_text(good + "\nwindow.primo-launcher .primo-x { color: #{{not_a_key}}; }\n")
broken = render("primo-dusk")
assert broken.returncode != 0 and "unresolved placeholder" in broken.stderr and "not_a_key" in broken.stderr, broken
assert GTK4.read_text() == before, "a failed render leaves the previous generated file alone"
tpl.write_text(good)
assert render("primo-dusk").returncode == 0

# ---- a gtk.css that was not generated is backed up once
GTK4.write_text("/* my own css */\nwindow { color: red; }\n")
assert render("primo-dawn").returncode == 0
backup = GTK4.with_name("gtk.css.bak-primo")
assert backup.exists() and "my own css" in backup.read_text() and HEAD in GTK4.read_text()
assert render("primo-dusk").returncode == 0 and "my own css" in backup.read_text(), "the backup is made once"
reached = [l for l in (work / "live-calls").read_text().splitlines() if not l.startswith("kwriteconfig6 ")]     # kwriteconfig6 is a stub that only absorbs KDE settings
assert not reached, "nothing reached a reload command: " + "; ".join(reached[:3])

print("theme role checks passed")

# ---- with a display, GTK itself parses what was generated
if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (GTK parse check)")
    sys.exit(0)
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
if not Gtk.init_check():
    print("skip: no display (GTK parse check)")
    sys.exit(0)
for theme in themes:
    errors = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _p, section, error: errors.append((section.to_string(), error.message)))
    provider.load_from_string(rendered[theme])
    assert not errors, (theme, errors[:3])
print("GTK parses every generated stylesheet")
