#!/usr/bin/env python3
"""Checks for control_center: the notification panel's config is generated from the installed tools into the cache, never over the base file.

Fake tools and temporary XDG folders only; no notification daemon is started, stopped or reloaded."""
import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="primo cc "))        # a space in the path on purpose
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data")):
    os.environ[var] = str(work / sub)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import control_center as cc_
import doctor_core as dc

ROOT = Path(__file__).resolve().parent.parent
BASE_PATH = ROOT / "config" / "swaync" / "config.json"
base = json.loads(BASE_PATH.read_text())
SCRIPTS = Path(cc_.__file__).resolve().parent


def actions(config):
    return config["widget-config"]["buttons-grid"]["actions"]


def commands(config):
    return [a["command"] for a in actions(config)] if "buttons-grid" in config["widgets"] else []


everything = lambda name: True
nothing = lambda name: False
having = lambda *names: (lambda name: name in names)

# ---- every tool present: the panel's buttons open the Settings pages, nothing else lost
full = cc_.build_config(base, everything)
cmds = commands(full)
assert any("--page network" in c for c in cmds) and any("--page audio" in c for c in cmds), cmds
assert not any(c.split()[0] in ("nm-connection-editor", "pavucontrol") for c in cmds), "no external tools: the deep links replace them"
assert any("nightlight.sh" in c for c in cmds) and any("screenshot.sh" in c for c in cmds) and any("power-menu.sh" in c for c in cmds)
assert full["widgets"] == base["widgets"] or set(full["widgets"]) >= {"title", "dnd", "notifications", "volume"}
assert "dnd" in full["widgets"] and "mpris" in full["widgets"] and "notifications" in full["widgets"], "DND, media and notifications stay"

# ---- one tool at a time missing: only its button goes, derived from the feature registry
for feature, needle in (("network", "--page network"), ("audio", "--page audio"), ("nightlight", "nightlight.sh"), ("capture", "screenshot.sh")):
    required = {b for b, _pkg in dc.FEATURES_BY_ID[feature].requires}
    cfg = cc_.build_config(base, lambda name, required=required: name not in required)
    gone = [needle in c for c in commands(cfg)]
    assert not any(gone), (feature, commands(cfg))
    kept = commands(full)
    assert len(commands(cfg)) < len(kept) and all(c in kept for c in commands(cfg)), feature
assert any("power-menu.sh" in c for c in commands(cc_.build_config(base, nothing))) , "the session menu needs nothing"
# a panel with no usable quick action has no empty grid, and no volume slider without pactl
bare = cc_.build_config(base, nothing)
assert "volume" not in bare["widgets"], bare["widgets"]
assert not any("--page" in c or "nightlight" in c or "screenshot" in c for c in commands(bare))

# ---- the base is not touched, unknown keys survive, paths with spaces are quoted
snapshot_before = copy.deepcopy(base)
custom = copy.deepcopy(base)
custom["my-own-key"] = {"keep": ["me"]}
custom["widget-config"]["extra-widget"] = {"x": 1}
out = cc_.build_config(custom, everything)
assert custom == dict(copy.deepcopy(custom)) and out["my-own-key"] == {"keep": ["me"]} and out["widget-config"]["extra-widget"] == {"x": 1}
assert base == snapshot_before, "build_config must not modify its input"
assert all(str(SCRIPTS) not in c or c.count("'") >= 2 for c in commands(out) if " " in str(SCRIPTS))
for c in commands(out):
    parts = __import__("shlex").split(c)
    script = parts[1] if parts[0] == "python3" else parts[0]
    assert Path(script).exists(), c                                  # the fixed script of this repository, quoted
page_cmd = next(c for c in commands(out) if "--page network" in c)
assert __import__("shlex").split(page_cmd)[:2] == ["python3", str(SCRIPTS / "primo-settings.py")], page_cmd

# ---- write_config: atomic, only when the content changed, last good file kept on failure
cache = work / "cache" / "primo" / "swaync" / "config.json"
base_copy = work / "base config.json"
base_copy.write_text(BASE_PATH.read_text())
assert cc_.write_config(base_copy, cache, everything) is True and cache.exists()
first = cache.read_text()
assert json.loads(first)["widgets"] and cc_.write_config(base_copy, cache, everything) is False, "unchanged output: nothing to reload"
assert cc_.write_config(base_copy, cache, having("nmcli")) is True and cache.read_text() != first
good = cache.read_text()
base_copy.write_text("{ not json")
try:
    cc_.write_config(base_copy, cache, everything)
    raise AssertionError("a broken base must raise")
except cc_.ControlCenterError as e:
    assert "base_copy" not in str(e) and "config.json" in str(e), str(e)
assert cache.read_text() == good, "the last valid generated file stays"
assert base_copy.read_text() == "{ not json", "the base is never rewritten"
base_copy.write_text(BASE_PATH.read_text())
real_atomic = cc_.cc.atomic_write
def full_disk(*a, **k): raise OSError(28, "No space left on device")
cc_.cc.atomic_write = full_disk
try:
    cc_.write_config(base_copy, cache, everything)
    raise AssertionError("a failed write must raise")
except cc_.ControlCenterError:
    pass
finally:
    cc_.cc.atomic_write = real_atomic
assert cache.read_text() == good and not [p for p in cache.parent.iterdir() if p.name != "config.json"], "no partial file, last good kept"

# ---- the commands: start (swaync with the generated config, or dunst, or the defaults on a cold failure) and refresh (reload only on change)
bin_dir = work / "bin"
bin_dir.mkdir()
calls = work / "calls.log"
def fake(name, body=""):
    (bin_dir / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{calls}"\n{body}\n')
    (bin_dir / name).chmod((bin_dir / name).stat().st_mode | stat.S_IEXEC)
for name in ("swaync", "swaync-client", "dunst", "pgrep"):
    fake(name)
fake("pgrep", "exit 0")                         # "a swaync is running" for refresh
for tool in ("nmcli", "pactl", "grim", "slurp", "hyprsunset"):
    fake(tool)
env = dict(os.environ, PATH=str(bin_dir))                     # only the fakes: a real swaync or dunst must not be found
def cli(*args, **over):
    calls.write_text("") if not calls.exists() else None
    return subprocess.run([sys.executable, str(SCRIPTS / "control_center.py"), *args], env={**env, **over}, capture_output=True, text=True, timeout=20)

# the base file for the CLI is the user's linked config
cfg_dir = work / "config" / "swaync"
cfg_dir.mkdir(parents=True)
(cfg_dir / "config.json").write_text(BASE_PATH.read_text())
(cfg_dir / "style.css").write_text("/* style */")
cache.unlink()
calls.write_text("")
r = cli("start", "--dry-run")
assert r.returncode == 0 and "swaync" in r.stdout and "-c" in r.stdout and str(cache) in r.stdout and "-s" in r.stdout, (r.stdout, r.stderr)
assert not calls.read_text(), "--dry-run starts nothing"
assert cache.exists()
(cfg_dir / "config.json").write_text("{ broken")
cache.unlink()
r = cli("start", "--dry-run")
assert r.returncode == 0 and "swaync" in r.stdout and "-c" not in r.stdout, ("cold failure: swaync with its own defaults, no buttons from us", r.stdout, r.stderr)
assert "primo" in r.stderr.lower() or "config" in r.stderr.lower(), r.stderr
(cfg_dir / "config.json").write_text(BASE_PATH.read_text())
for name in ("swaync", "swaync-client"):
    (bin_dir / name).rename(bin_dir / (name + ".off"))
r = cli("start", "--dry-run")
assert r.returncode == 0 and r.stdout.split()[0] == "dunst", r.stdout
for name in ("swaync", "swaync-client"):
    (bin_dir / (name + ".off")).rename(bin_dir / name)

# refresh: regenerates when the installed tools changed, reloads only then
calls.write_text("")
cache.unlink(missing_ok=True)
r = cli("refresh")
assert r.returncode == 0 and "swaync-client -R" in calls.read_text() or "swaync-client --reload-config" in calls.read_text(), (calls.read_text(), r.stderr)
calls.write_text("")
r = cli("refresh")
assert r.returncode == 0 and "swaync-client" not in calls.read_text(), "nothing changed: no reload"
(bin_dir / "nmcli").unlink()
calls.write_text("")
cli("refresh")
assert "swaync-client" in calls.read_text() and "--page network" not in cache.read_text(), "a tool went away: the button goes, no restart"
(cfg_dir / "config.json").write_text("{ broken")
calls.write_text("")
r = cli("refresh")
assert r.returncode != 0 and "swaync-client" not in calls.read_text() and cache.exists(), "a failed refresh keeps the last good file and reloads nothing"

# ---- the wiring: the panel toggle refreshes first; the session starts the panel through this script
text = (SCRIPTS / "notifications.sh").read_text()
assert "control_center.py" in text and text.index("control_center.py") < text.index("swaync-client -t -sw"), "panel refreshes before it toggles"
assert "control_center.py start" in (SCRIPTS.parent / "modules" / "autostart.lua").read_text()
print("control center checks passed")
