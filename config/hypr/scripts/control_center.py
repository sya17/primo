#!/usr/bin/env python3
"""The notification panel's quick buttons follow what is installed. Standard library only (plus doctor_core's feature list).

The base config (~/.config/swaync/config.json, linked to the repository) is never rewritten. A copy with only the buttons that can work is
generated into $XDG_CACHE_HOME/primo/swaync/config.json and swaync is started with it:

    control_center.py start [--dry-run]   start swaync with the generated config (dunst when swaync is missing)
    control_center.py refresh             regenerate; reload swaync only when the content changed

The network and audio buttons open the Settings pages. A button needs the tools of its feature (doctor_core.FEATURES). When the config
cannot be generated, the last good file is used; with none, swaync starts with its own defaults: notifications only, no buttons of ours.
"""
import copy
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_core as cc  # noqa: E402
import doctor_core as dc  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
SETTINGS = SCRIPTS / "primo-settings.py"
# how a button of the base config is recognised -> (feature it needs or None, the command it gets)
KNOWN = [("nm-connection-editor", "network", f"python3 {shlex.quote(str(SETTINGS))} --page network"),
         ("pavucontrol", "audio", f"python3 {shlex.quote(str(SETTINGS))} --page audio"),
         ("nightlight.sh", "nightlight", None), ("screenshot.sh", "capture", None), ("power-menu.sh", None, None)]


class ControlCenterError(Exception):
    """The panel config could not be generated; the message says which file and why."""


def _command(action, feature_and_command):
    feature, command = feature_and_command
    if command:
        return command
    text = action["command"]
    if text.startswith("~/.config/hypr/scripts/"):                    # the fixed script of this repository, quoted for the shell
        name, _, rest = text[len("~/.config/hypr/scripts/"):].partition(" ")
        return shlex.quote(str(SCRIPTS / name)) + (" " + rest if rest else "")
    return text


def build_config(base, available):
    """A copy of `base` whose buttons all can work. `available(name)` says whether a program is installed. `base` is not changed."""
    config = copy.deepcopy(base)
    grid = config.get("widget-config", {}).get("buttons-grid", {})
    kept = []
    for action in grid.get("actions", []):
        match = next(((fid, cmd) for needle, fid, cmd in KNOWN if needle in action.get("command", "")), None)
        if match is None:
            kept.append(action)                                         # a button the user added is theirs
            continue
        feature, command = match
        needs = [b for b, _pkg in dc.FEATURES_BY_ID[feature].requires] if feature else []
        if all(available(b) for b in needs):
            action = dict(action, command=_command(action, match))
            kept.append(action)
    if "actions" in grid:
        grid["actions"] = kept
    if not kept and "buttons-grid" in config.get("widgets", []):
        config["widgets"].remove("buttons-grid")
    if not available("pactl") and "volume" in config.get("widgets", []):
        config["widgets"].remove("volume")                              # the slider talks to the sound server
    return config


def write_config(base_path, cache_path, available):
    """Generate the config into `cache_path`. True when the content changed. Raises ControlCenterError; the old file stays then."""
    import json
    try:
        base = cc.load(base_path, dict)
    except cc.ConfigError as error:
        raise ControlCenterError(str(error)) from None
    if base is None:
        raise ControlCenterError(f"{base_path}: missing or empty")
    text = json.dumps(build_config(base, available), indent=2, ensure_ascii=False) + "\n"
    cache_path = Path(cache_path)
    try:
        if cache_path.exists() and cache_path.read_text() == text:
            return False
        cc.atomic_write(cache_path, text, 0o600)
    except OSError as error:
        raise ControlCenterError(f"{cache_path}: {error.strerror}") from None
    return True


def paths():
    config = cc.config_home() / "swaync"
    return config / "config.json", config / "style.css", cc.cache_home() / "primo" / "swaync" / "config.json"


def start(dry_run=False):
    if not shutil.which("swaync"):
        command = ["dunst"]
    else:
        base, style, cache = paths()
        command = ["swaync"]
        try:
            write_config(base, cache, shutil.which)
        except ControlCenterError as error:
            print(f"primo: notification panel config: {error}; using the last good one or swaync's own defaults", file=sys.stderr)
        if cache.exists():
            command += ["-c", str(cache)]
        if style.exists():
            command += ["-s", str(style)]
    if dry_run:
        print(shlex.join(command))
        return 0
    os.execvp(command[0], command)


def refresh():
    if not shutil.which("swaync-client"):
        return 0
    base, _style, cache = paths()
    try:
        changed = write_config(base, cache, shutil.which)
    except ControlCenterError as error:
        print(f"primo: notification panel config: {error}", file=sys.stderr)
        return 1
    if changed and subprocess.run(["pgrep", "-x", "swaync"], capture_output=True).returncode == 0:
        subprocess.run(["swaync-client", "-R", "-sw"], capture_output=True)
    return 0


def main(argv):
    if argv[:1] == ["start"]:
        return start("--dry-run" in argv)
    if argv[:1] == ["refresh"]:
        return refresh()
    print("usage: control_center.py start [--dry-run] | refresh", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
