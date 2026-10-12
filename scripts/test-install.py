#!/usr/bin/env python3
"""Checks for scripts/install.sh on a copy of the repository and a temporary HOME, with a PATH that holds only fake tools and a few coreutils.

Nothing real is touched: the installer runs from a copy of the checkout (it writes generated files next to itself), HOME is temporary, the
external tools it might call (gsettings, kwriteconfig6, hyprctl, ...) are shims that only write a log line, and nothing is reloaded."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = "Hyprland hyprpaper hyprlock hypridle cliphist wl-paste waybar wofi dunst kitty grim slurp wl-copy notify-send".split()
OPTIONAL_SOME = "swayosd-server hyprsunset brightnessctl playerctl".split()
# the plain tools install.sh, theme-switch and configure-apps.sh use besides the fakes
COREUTILS = ("bash sh env date mkdir ln mv rm cp readlink dirname basename cat sed grep tr sort cut head tail md5sum mktemp printf touch chmod ls find "
             "uname id wc tee xargs sleep true false realpath stat awk diff comm python3 git").split()


def which_real(name):
    return shutil.which(name)


def make_checkout(parent):
    """A copy of the working tree (without git data, planning folders or caches), so the installer's generated files land in the copy."""
    dst = parent / "primo copy"                       # a space in the path on purpose (I4)
    shutil.copytree(ROOT, dst, symlinks=True, ignore=shutil.ignore_patterns(".git", ".ai", ".tasks", ".remember", "__pycache__", "*.pyc", "node_modules", "*.bak*"))
    return dst


def make_world(tools=REQUIRED + OPTIONAL_SOME, missing=()):
    """(checkout, home, env, log): a fresh copy, an empty HOME and a PATH of shims and coreutils only."""
    base = Path(tempfile.mkdtemp(prefix="primo-install-"))
    checkout = make_checkout(base)
    home = base / "home dir"
    home.mkdir()
    bindir = base / "bin"
    bindir.mkdir()
    log = base / "tools.log"
    for t in tools:
        if t in missing:
            continue
        (bindir / t).write_text(f'#!/bin/sh\necho "{t} $*" >> "{log}"\n')
        (bindir / t).chmod(0o755)
    for t in ("gsettings", "kwriteconfig6", "hyprctl", "pkill", "swaync-client", "systemctl", "dconf", "setsid", "sudo", "pacman"):
        (bindir / t).write_text(f'#!/bin/sh\necho "{t} $*" >> "{log}"\n[ "{t}" = pacman ] && exit 1\nexit 0\n')
        (bindir / t).chmod(0o755)
    (bindir / "fc-list").write_text("#!/bin/sh\necho Inter\necho 'JetBrainsMono Nerd Font'\n")
    (bindir / "fc-list").chmod(0o755)
    for t in COREUTILS:
        real = which_real(t)
        if real and not (bindir / t).exists():
            (bindir / t).symlink_to(real)
    env = {"HOME": str(home), "PATH": str(bindir), "PRIMO_NO_RELOAD": "1", "LANG": "C.UTF-8"}
    return checkout, home, env, log


def install(checkout, env, *args):
    r = subprocess.run(["bash", str(checkout / "scripts/install.sh"), *args], env=env, capture_output=True, text=True, timeout=300, cwd=str(checkout))
    return r.returncode, r.stdout, r.stderr


def snapshot_of(root):
    return {str(p.relative_to(root)): (p.is_symlink(), os.readlink(p) if p.is_symlink() else p.read_bytes()) for p in sorted(Path(root).rglob("*"))
            if p.is_symlink() or p.is_file()}


APPS = "hypr waybar wofi dunst kitty swayosd swaync fontconfig".split()

# ---- I1: dry run changes nothing, a real run links everything and renders the theme
checkout, home, env, log = make_world()
before_repo, before_home = snapshot_of(checkout), snapshot_of(home)
code, out, err = install(checkout, env, "--dry-run", "--theme", "primo-dusk")
assert code == 0, out + err
assert "[dry-run]" in out and snapshot_of(checkout) == before_repo and snapshot_of(home) == before_home, "a dry run changes nothing, in the repository or in HOME"
code, out, err = install(checkout, env, "--theme", "primo-dusk")
assert code == 0, out + err
for app in APPS:
    link = home / ".config" / app
    assert link.is_symlink() and Path(os.path.realpath(link)) == (checkout / "config" / app).resolve(), app
assert (checkout / "config/hypr/theme.lua").is_file() and "{{" not in (checkout / "config/hypr/theme.lua").read_text(), "the theme is rendered"
assert (home / ".local/share/applications/primo-settings.desktop").is_file() and (home / ".local/bin/primo").is_symlink() and (home / ".local/bin/hypr-theme").is_symlink()
assert (home / ".local/state/hyprland-dotfiles/current").read_text().strip() == "primo-dusk"
logged = log.read_text() if log.exists() else ""
assert "hyprctl" not in logged and "pkill" not in logged and "swaync-client" not in logged and "systemctl" not in logged and "sudo" not in logged, logged
assert not [p for p in (home / ".config").glob("*.bak-*")], "nothing existed, so nothing was backed up"

# ---- I2: a second run changes nothing and says so
mid_repo, mid_home = snapshot_of(checkout), snapshot_of(home)
code, out, err = install(checkout, env, "--theme", "primo-dusk")
assert code == 0 and out.count("already linked") == len(APPS), out
assert snapshot_of(home) == mid_home and snapshot_of(checkout) == mid_repo, "a repeated install changes no file, no link and no byte"
assert not list((home / ".config").glob("*.bak-*")), "a repeated install makes no backups"

# ---- I3, I5: a foreign folder and a foreign symlink are moved aside, never deleted or followed; unrelated config is untouched
checkout, home, env, log = make_world()
cfg = home / ".config"
(cfg / "hypr").mkdir(parents=True)
(cfg / "hypr" / "my.lua").write_text("my own hyprland config\n")
(cfg / "waybar").symlink_to(home / "elsewhere")                                   # a symlink somewhere else (it dangles on purpose)
(home / "elsewhere").mkdir()
(home / "elsewhere" / "keep.txt").write_text("keep me\n")
(cfg / "kitty").mkdir()
(cfg / "kitty" / "kitty.conf").write_text("font_size 14\n")
(cfg / "mozilla").mkdir()
(cfg / "mozilla" / "profile.txt").write_text("not primo's\n")
(cfg / "starship.toml").write_text("# my prompt\n")
foreign = {"mozilla/profile.txt": "not primo's\n"}
code, out, err = install(checkout, env, "--theme", "primo-dusk")
assert code == 0, out + err
baks = {p.name.split(".bak-")[0]: p for p in cfg.glob("*.bak-*") if re.search(r"\.bak-\d{8}-\d{6}$", p.name)}
assert set(baks) == {"hypr", "waybar", "kitty"}, sorted(baks)
assert (baks["hypr"] / "my.lua").read_text() == "my own hyprland config\n" and (baks["kitty"] / "kitty.conf").read_text() == "font_size 14\n"
assert baks["waybar"].is_symlink() and (home / "elsewhere" / "keep.txt").read_text() == "keep me\n", "a foreign symlink is moved as a link; its target is never followed or touched"
assert (cfg / "mozilla" / "profile.txt").read_text() == "not primo's\n", "unrelated config is untouched"
for app in ("hypr", "waybar", "kitty"):
    assert (cfg / app).is_symlink() and Path(os.path.realpath(cfg / app)) == (checkout / "config" / app).resolve()
assert (cfg / "starship.toml").exists() and (cfg / "starship.toml.bak-primo").read_text() == "# my prompt\n", "a file the theme tool replaces is kept once as .bak-primo"

# ---- I4: the checkout path has a space in it (make_checkout did that) and the home too: everything above already ran inside both
assert " " in str(checkout) and " " in str(home)

# ---- I6: a required tool missing stops before anything is changed and names the package
checkout, home, env, log = make_world(missing=("waybar", "grim"))
before_repo, before_home = snapshot_of(checkout), snapshot_of(home)
code, out, err = install(checkout, env, "--theme", "primo-dusk")
assert code == 1 and "Missing required commands: waybar grim" in out and "pacman -S" in out, out
assert snapshot_of(checkout) == before_repo and snapshot_of(home) == before_home, "nothing is changed when a required tool is missing"
code, out, err = install(checkout, env, "--dry-run")
assert code == 1 and "Missing required commands" in out, "a dry run tells you the same"

# ---- I7: optional tools missing: notes, exit 0, the install still works
checkout, home, env, log = make_world(tools=REQUIRED)
code, out, err = install(checkout, env, "--theme", "primo-dusk")
assert code == 0, out + err
for tool in ("swayosd-server", "hyprsunset", "brightnessctl"):
    assert f"note: optional '{tool}' not found" in out, tool
assert (home / ".config/hypr").is_symlink()

# ---- the flags: an unknown option is a usage error before anything is touched
checkout, home, env, log = make_world()
before_home = snapshot_of(home)
code, out, err = install(checkout, env, "--bogus")
assert code == 2 and "unknown option" in err and snapshot_of(home) == before_home
code, out, err = install(checkout, env, "--help")
assert code == 0 and "Usage" in out

for p in Path(tempfile.gettempdir()).glob("primo-install-*"):
    shutil.rmtree(p, ignore_errors=True)
print("ok: install")
