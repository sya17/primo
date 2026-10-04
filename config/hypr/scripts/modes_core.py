"""Modes: one action that sets the machine up for what you are about to do, and puts it back when you are done.

A mode is a recipe: apps on workspaces, a VPN, a power profile, do-not-disturb, a focus session. Work on a project,
research, writing, relaxing: the recipes are yours (Settings > Modes); a few starting points are created the first time.

Standard library only. The functions take a `run` callable so the tests can check what would happen without doing it.
"""
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "primo" / "modes.json"
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprland-dotfiles" / "mode.json"
RECENT = STATE.parent / "mode-dirs.json"

POWER = {"": "Leave as is", "power-saver": "Power saver", "balanced": "Balanced", "performance": "Performance"}
CATEGORIES = ["Work", "Research", "Learning", "Personal", "Other"]

DEFAULT_MODES = [
    {"id": "work", "name": "Work", "icon": "applications-engineering", "ask_dir": True, "vpn": "", "power": "performance",
     "dnd": True, "focus": True, "category": "Work",
     "apps": [{"cmd": "kitty --directory {dir}", "ws": 1, "match": ""},
              {"cmd": "code {dir}", "ws": 2, "match": "com.microsoft.VSCode"}]},
    {"id": "research", "name": "Research", "icon": "system-search", "ask_dir": False, "vpn": "", "power": "balanced",
     "dnd": True, "focus": True, "category": "Research",
     "apps": [{"cmd": "firefox", "ws": 2, "match": "firefox"}, {"cmd": "obsidian", "ws": 3, "match": "obsidian"},
              {"cmd": "kitty", "ws": 1, "match": ""}]},
    {"id": "writing", "name": "Writing", "icon": "document-edit", "ask_dir": False, "vpn": "", "power": "",
     "dnd": True, "focus": True, "category": "Work",
     "apps": [{"cmd": "obsidian", "ws": 1, "match": "obsidian"}]},
    {"id": "relax", "name": "Relax", "icon": "applications-multimedia", "ask_dir": False, "vpn": "", "power": "",
     "dnd": False, "focus": False, "category": "Personal", "apps": []},
]


# ----------------------------------------------------------------------------- storage
def load_modes():
    try:
        data = json.loads(CONFIG.read_text())
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass
    return json.loads(json.dumps(DEFAULT_MODES))


def save_modes(modes):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(modes, indent=1, ensure_ascii=False))


def get_mode(mode_id):
    return next((m for m in load_modes() if m["id"] == mode_id), None)


def current():
    """The running mode's state, or None."""
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None


def project_dirs():
    """Folders worth offering for a mode that asks for one: ~/workspace/* and the ones used recently."""
    out = []
    try:
        for d in json.loads(RECENT.read_text()):
            if Path(d).is_dir() and d not in out:
                out.append(d)
    except (OSError, ValueError):
        pass
    base = Path.home() / "workspace"
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and str(d) not in out:
                out.append(str(d))
    return out


def remember_dir(path):
    dirs = [path] + [d for d in project_dirs() if d != path]
    RECENT.parent.mkdir(parents=True, exist_ok=True)
    RECENT.write_text(json.dumps(dirs[:12]))


def apps_to_text(apps):
    """One app per line: 'workspace | command | window class (optional)'."""
    return "\n".join(f"{a.get('ws') or ''} | {a['cmd']} | {a.get('match', '')}".rstrip(" |") for a in apps)


def text_to_apps(text):
    apps = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[1]:
            apps.append({"cmd": parts[1], "ws": int(parts[0]) if parts[0].isdigit() else 0, "match": parts[2] if len(parts) > 2 else ""})
        elif len(parts) == 1 and parts[0] and not parts[0].isdigit():
            apps.append({"cmd": parts[0], "ws": 0, "match": ""})
    return apps


def slug(name, taken):
    base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "mode"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}-{n}", n + 1
    return out


# ----------------------------------------------------------------------------- doing things
def sh(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 8), **kw)
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(cmd, 1, "", "")


def clients():
    try:
        return json.loads(sh(["hyprctl", "clients", "-j"]).stdout or "[]")
    except ValueError:
        return []


def expand(cmd, directory):
    """{dir} becomes the chosen folder; without one, the word and any option that wants it are dropped."""
    if directory:
        return cmd.replace("{dir}", shlex.quote(directory))
    words = [w for w in shlex.split(cmd) if "{dir}" not in w]
    if words and words[-1] in ("--directory", "-d", "--cwd"):
        words.pop()
    return shlex.join(words)


def start(mode, directory=None, run=sh, running=None, now=None):
    """Set the machine up for `mode`. Returns the state that `end` needs to put things back."""
    running = running if running is not None else clients()
    now = now or time.time()
    prev = current()
    if prev:
        end(run=run)
    state = {"id": mode["id"], "name": mode["name"], "start": now, "dir": directory or "", "category": mode.get("category", "Other"),
             "label": (mode["name"] + (" · " + Path(directory).name if directory else "")),
             "power_was": None, "dnd_set": False, "vpn_up": [], "steps": []}

    vpn = mode.get("vpn", "")
    if vpn:
        active = run(["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"]).stdout.splitlines()
        if vpn not in active:
            run(["nmcli", "--wait", "1", "connection", "up", "id", vpn])
            state["vpn_up"].append(vpn)
            state["steps"].append(f"VPN {vpn}")

    if mode.get("power"):
        state["power_was"] = (run(["powerprofilesctl", "get"]).stdout or "").strip() or None
        run(["powerprofilesctl", "set", mode["power"]])
        state["steps"].append(POWER.get(mode["power"], mode["power"]))

    if mode.get("dnd"):
        if (run(["swaync-client", "-D"]).stdout or "").strip() != "true":
            run(["swaync-client", "-dn"])
            state["dnd_set"] = True
        state["steps"].append("Do not disturb")

    first_ws = None
    for app in mode.get("apps", []):
        match = app.get("match", "")
        if match and any(re.search(match, c.get("class", "")) for c in running):
            continue                        # already open: leave it where it is
        cmd = expand(app["cmd"], directory)
        if not cmd:
            continue
        ws = int(app.get("ws") or 0)
        first_ws = first_ws or ws or None
        arg = f', {{ workspace = "{ws} silent" }}' if ws else ""
        run(["hyprctl", "dispatch", f'hl.dsp.exec_cmd({json.dumps(cmd)}{arg})'])
        state["steps"].append(cmd.split()[0])
    if first_ws:
        run(["hyprctl", "dispatch", f"hl.dsp.focus({{ workspace = {first_ws} }})"])

    if mode.get("focus"):
        run(["gdbus", "call", "--session", "--dest", "dev.primo.Hub", "--object-path", "/dev/primo/Hub", "--method",
             "org.gtk.Actions.Activate", "focus-start", f"[<'{state['label']}|{state['category']}'>]", "{}"])
        state["steps"].append("Focus session")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))
    if directory:
        remember_dir(directory)
    run(["notify-send", "-a", "Modes", "-i", mode.get("icon", "emblem-ok"), f"{mode['name']} mode",
         ", ".join(state["steps"]) or "Started"])
    return state


def end(run=sh):
    """Put back what the mode changed. Apps stay open: closing them is up to you."""
    st = current()
    if not st:
        return None
    if st.get("power_was"):
        run(["powerprofilesctl", "set", st["power_was"]])
    if st.get("dnd_set"):
        run(["swaync-client", "-df"])
    for vpn in st.get("vpn_up", []):
        run(["nmcli", "connection", "down", "id", vpn])
    run(["gdbus", "call", "--session", "--dest", "dev.primo.Hub", "--object-path", "/dev/primo/Hub", "--method",
         "org.gtk.Actions.Activate", "focus-end", "[]", "{}"])
    try:
        STATE.unlink()
    except OSError:
        pass
    run(["notify-send", "-a", "Modes", "-i", "emblem-ok", f"{st['name']} mode ended", "Settings put back"])
    return st


def elapsed(st, now=None):
    return int((now or time.time()) - st["start"])
