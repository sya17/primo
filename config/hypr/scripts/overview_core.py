"""What the overview knows and does, without GTK: read the compositor with `hyprctl -j`, check a target before acting on it.
Standard library only. Primo keeps no copy of the desktop: every answer comes from Hyprland, and a read that fails never replaces
the last good one (`View`). `run(argv)` is a bounded runner (settings_jobs.Budget or proc_core.run_bounded) returning a proc_core.Run."""
import json
import re
from dataclasses import dataclass, field

import config_core as cc

OWN_CLASS = "dev.primo.Overview"
MIN_WORKSPACES = 4
REFRESH_SECONDS = 2                      # while the overview is open; nothing runs while it is hidden
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{1,16}$")
JUMP = range(1, 10)                      # the number keys always work, even for a workspace nobody has used yet


DEFAULTS = {"version": 1, "close_after_select": True}
FOCUS_GRACE = 1.0                        # seconds after a selection in which the focus loss it causes is expected


class OverviewError(Exception):
    """The desktop could not be read; the message says why in words for the window."""


@dataclass
class Snapshot:
    clients: list = field(default_factory=list)          # visible windows: address, class, title, workspace
    workspaces: list = field(default_factory=list)
    monitors: list = field(default_factory=list)
    active_workspace: int = None
    active_window: str = None


@dataclass
class Outcome:
    ok: bool
    reason: str = ""

    def __bool__(self):
        return self.ok


def _why(result):
    if result.reason == "missing":
        return "hyprctl is not installed"
    if result.reason == "timeout":
        return "Hyprland took too long to answer"
    if result.reason:
        return f"hyprctl was stopped ({result.reason})"
    return (result.err.strip().splitlines() or ["hyprctl failed"])[-1][:140]


def _read(run, what, kind):
    result = run(["hyprctl", what, "-j"])
    if not result.ok:
        raise OverviewError(_why(result))
    try:
        value = json.loads(result.out) if result.out.strip() else kind()
    except ValueError:
        raise OverviewError(f"Hyprland answered {what} with something that is not JSON") from None
    if not isinstance(value, kind):
        raise OverviewError(f"Hyprland answered {what} in a shape the overview does not know")
    return value


def _client(c):
    ws = c.get("workspace") if isinstance(c, dict) else None
    if not (isinstance(ws, dict) and isinstance(ws.get("id"), int) and isinstance(c.get("address"), str) and ADDRESS.match(c["address"])
            and isinstance(c.get("class"), str)):
        raise OverviewError("Hyprland listed a window the overview cannot read")
    return c


def snapshot(run):
    """Everything the overview shows. Raises OverviewError when any part is missing or malformed: half a desktop is never shown."""
    clients = [_client(c) for c in _read(run, "clients", list) if isinstance(c, dict) and c.get("mapped") and not c.get("hidden")]
    clients = [c for c in clients if c["class"] and c["class"] != OWN_CLASS]
    spaces = [w for w in _read(run, "workspaces", list) if isinstance(w, dict) and isinstance(w.get("id"), int)]
    monitors = [m for m in _read(run, "monitors", list) if isinstance(m, dict)]
    active = _read(run, "activeworkspace", dict).get("id")
    window = _read(run, "activewindow", dict).get("address")
    return Snapshot(clients, spaces, monitors, active if isinstance(active, int) else None, window if isinstance(window, str) and window else None)


def workspace_ids(snap):
    """The workspaces to draw: the first few, every one with a window, and the one you are on."""
    used = {c["workspace"]["id"] for c in snap.clients if c["workspace"]["id"] > 0}
    active = {snap.active_workspace} if snap.active_workspace and snap.active_workspace > 0 else set()
    return sorted(set(range(1, max([MIN_WORKSPACES, *used]) + 1)) | active)


def validate_target(snap, address=None, workspace=None):
    """May the overview act on this window and/or workspace? Both must exist in `snap` (a number key may name any of 1-9)."""
    if address is not None and not (isinstance(address, str) and ADDRESS.match(address) and any(c["address"] == address for c in snap.clients)):
        return False
    if workspace is not None and not (isinstance(workspace, int) and not isinstance(workspace, bool) and (workspace in JUMP or workspace in workspace_ids(snap))):
        return False
    return address is not None or workspace is not None


class View:
    """What the window shows: the last valid snapshot, and whether it is still loading, current or stale (the last refresh failed)."""

    def __init__(self, last=None):
        self.snapshot, self.error = last, ""

    @property
    def state(self):
        return "loading" if self.snapshot is None and not self.error else "stale" if self.error else "ok"

    def apply(self, result):
        """Take a refresh result (a Snapshot or the exception it ended with). True when what is drawn must change (a failure always does: it shows the stale notice)."""
        if isinstance(result, Snapshot):
            changed = result != self.snapshot or bool(self.error)
            self.snapshot, self.error = result, ""
            return changed
        self.error = str(result) or "Hyprland did not answer"
        return True                                     # the stale notice is part of what is drawn


def _dispatch(run, expr):
    result = run(["hyprctl", "dispatch", expr])
    text = result.out.strip().lower()
    if not result.ok:
        return Outcome(False, _why(result))
    if text.startswith(("error", "invalid", "unknown")):
        return Outcome(False, result.out.strip().splitlines()[0][:140])
    return Outcome(True)


def _fresh(run):
    try:
        return snapshot(run), None
    except OverviewError as error:
        return None, Outcome(False, str(error))


def focus_window(address, run):
    snap, error = _fresh(run)
    if error is not None:
        return error
    if not validate_target(snap, address=address):
        return Outcome(False, "that window is gone")
    return _dispatch(run, f'hl.dsp.focus({{ window = "address:{address}" }})')


def go_workspace(n, run):
    snap, error = _fresh(run)
    if error is not None:
        return error
    if not validate_target(snap, workspace=n):
        return Outcome(False, "that workspace is not available")
    return _dispatch(run, f"hl.dsp.focus({{ workspace = {n} }})")


def move_window(address, n, run):
    snap, error = _fresh(run)
    if error is not None:
        return error
    if not validate_target(snap, address=address):
        return Outcome(False, "that window is gone")
    if not validate_target(snap, workspace=n):
        return Outcome(False, "that workspace is not available")
    return _dispatch(run, f'hl.dsp.window.move({{ workspace = {n}, window = "address:{address}" }})')


# ----------------------------------------------------------------------------- search and groups
def _workspace_names(snap):
    return {w["id"]: str(w.get("name") or w["id"]) for w in snap.workspaces}


def filter_clients(snap, query):
    """The windows whose title, class or workspace name contains every word of `query` (casefolded, plain text: no patterns)."""
    words = query.casefold().split()
    names = _workspace_names(snap)
    out = []
    for c in snap.clients:
        ws = c["workspace"]["id"]
        hay = " ".join(str(x) for x in (c.get("title") or "", c["class"], c.get("initialClass") or "", names.get(ws, ws), f"workspace {ws}")).casefold()
        if all(w in hay for w in words):
            out.append(c)
    return sorted(out, key=lambda c: (c["workspace"]["id"], (c.get("title") or "").casefold()))


def group_workspaces(snap):
    """The workspaces to draw, grouped by the monitor Hyprland says they are on. A group is identified by the monitor's serial number
    (its connector when it has none), so it stays the same group when a cable moves. A workspace whose monitor is no longer listed
    keeps its own group, marked as not connected; a workspace nobody has used yet goes with the focused monitor. Every window is in one place."""
    monitors = snap.monitors
    ident = lambda m: str(m.get("serial") or m.get("name") or "")
    by_name = {m.get("name"): m for m in monitors}
    home = next((m for m in monitors if m.get("focused")), monitors[0] if monitors else None)
    entries = {w["id"]: w for w in snap.workspaces}
    names = _workspace_names(snap)
    groups = {}

    def group(key, label, connected):
        return groups.setdefault(key, {"key": key, "label": label, "connected": connected, "workspaces": []})

    for m in monitors:
        group(ident(m), str(m.get("name") or ""), True)
    for ws_id in workspace_ids(snap):
        name = entries.get(ws_id, {}).get("monitor")
        m = by_name.get(name) if name else home
        if m is not None:
            g = group(ident(m), str(m.get("name") or ""), True)
        elif name:
            g = group(name, f"{name} (not connected)", False)
        else:
            g = group("", "", True)
        label = names.get(ws_id, str(ws_id))
        g["workspaces"].append({"id": ws_id, "label": f"Workspace {ws_id}" if label == str(ws_id) else label,
                                "windows": [c for c in snap.clients if c["workspace"]["id"] == ws_id]})
    return [g for g in groups.values() if g["workspaces"]]


# ----------------------------------------------------------------------------- preferences (through config_core only)
def preferences_path():
    return cc.config_home() / "primo" / "overview.json"


def load_preferences(path=None):
    """The saved preferences, with a default for anything missing or of the wrong kind. A file that cannot be used is kept aside by config_core."""
    value = cc.read_json(path or preferences_path(), dict, {}).get("close_after_select")
    return {"version": DEFAULTS["version"], "close_after_select": value if isinstance(value, bool) else DEFAULTS["close_after_select"]}


def save_preferences(data, path=None):
    """Save the known keys only. Raises config_core.ConfigError for a file from a newer Primo, which is never written over."""
    cc.write_json(path or preferences_path(), {"version": DEFAULTS["version"], "close_after_select": bool(data.get("close_after_select", True))}, 0o600)


def closes_on_focus_loss(close_after_select, selected_at, now):
    """Should losing focus close the overview? Always, unless the preference keeps it open and this loss is the one a selection just caused."""
    return close_after_select or selected_at is None or now - selected_at > FOCUS_GRACE
