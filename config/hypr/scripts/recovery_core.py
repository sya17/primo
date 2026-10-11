"""Recovery of Primo's own settings: what a snapshot may hold, and (in later steps) how one is taken and put back. Standard library only, no GTK.

The scope is a fixed list of Primo's files in three folders, never a walk of HOME. Every entry has a class: portable (user intent), machine
(tied to this machine), sensitive (may hold secrets or private history; left out unless asked for). Generated files and anything that is
not Primo's are not in the list at all. Reading and planning never write. Contract: .tasks 25-0.7.0-recovery-contract (kept out of git);
the frozen shapes are the dataclasses below.
"""
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import config_core as cc

VERSION = 1
MAX_FILE = 1 << 20          # one file, bytes
MAX_TOTAL = 4 << 20         # one snapshot, bytes
SOFT_LIMIT, HARD_LIMIT = 10, 25

BASES = ("config", "data", "state")
STATUSES = ("include", "sensitive-skipped", "missing", "unreadable", "too-large", "outside-root")


@dataclass(frozen=True)
class RecoveryEntry:
    name: str
    base: str            # "config", "data" or "state"
    rel: str             # path inside the approved root of that base
    kind: str            # "json", "toml" or "text"
    cls: str             # "portable", "machine" or "sensitive"
    note: str = ""


@dataclass(frozen=True)
class PlanFile:
    entry: RecoveryEntry
    path: str
    size: "int | None"
    status: str


@dataclass(frozen=True)
class SnapshotPlan:
    files: tuple
    include_sensitive: bool
    total_bytes: int

    def included(self):
        return tuple(f for f in self.files if f.status == "include")


def _e(name, base, rel, kind, cls, note=""):
    return RecoveryEntry(name, base, rel, kind, cls, note)


# Fixed inventory, in this order. `rel` is relative to the approved root of the base (see roots()).
INVENTORY = (
    _e("modes", "config", "modes.json", "json", "portable"),
    _e("activity", "config", "activity.json", "json", "portable"),
    _e("overview", "config", "overview.json", "json", "portable"),
    _e("ui", "config", "ui.json", "json", "portable"),
    _e("workflow", "config", "workflow.json", "json", "sensitive", "calendar links and snippet text can hold secrets"),
    _e("hub", "data", "hub.json", "json", "portable", "reminders, alarms, timers, focus log"),
    _e("current", "state", "current", "text", "portable", "the applied theme"),
    _e("last-dark", "state", "last-dark", "text", "portable"),
    _e("last-light", "state", "last-light", "text", "portable"),
    _e("slideshow-interval", "state", "slideshow-interval", "text", "portable"),
    _e("video-keep-on-battery", "state", "video-keep-on-battery", "text", "portable"),
    _e("wallpaper-transition", "state", "wallpaper-transition", "text", "portable"),
    _e("battery-autosaver", "state", "battery-autosaver", "text", "portable"),
    _e("cursor", "state", "cursor", "text", "portable"),
    _e("wallpaper", "state", "wallpaper", "text", "machine", "a path on this machine"),
    _e("wallpaper-current", "state", "wallpaper-current", "text", "machine", "a path on this machine"),
    _e("slideshow-dir", "state", "slideshow-dir", "text", "machine", "a folder on this machine"),
    _e("mode-dirs", "state", "mode-dirs.json", "json", "machine", "folders on this machine"),
    _e("launcher-history", "state", "launcher-history.json", "json", "sensitive", "what you launched and searched"),
)


def roots(env=None, home=None):
    """The three approved roots, as real paths. Nothing outside them is ever read for, or written by, recovery."""
    return {"config": cc.config_home(env, home) / "primo", "data": cc.data_home(env, home) / "primo",
            "state": cc.state_home(env, home) / "hyprland-dotfiles"}


def inventory(env=None, home=None):
    """The fixed entries plus any other plain .json/.toml file in the Primo config folder (named `primo/<file>`), as portable."""
    out = list(INVENTORY)
    folder = roots(env, home)["config"]
    known = {e.rel for e in out if e.base == "config"}
    try:
        names = sorted(p.name for p in folder.iterdir() if p.suffix in (".json", ".toml") and p.name not in known)
    except OSError:
        names = []
    for n in names:
        out.append(_e(f"primo/{n}", "config", n, "toml" if n.endswith(".toml") else "json", "portable", "another settings file of yours"))
    return out


def _inside(real, root_real):
    return real == root_real or root_real in real.parents


def target_path(entry, env=None, home=None):
    """Where an entry lives. Raises ValueError for a rel that would leave its root (a tampered manifest, never the fixed list)."""
    root = roots(env, home)[entry.base]
    path = root / entry.rel
    if os.path.isabs(entry.rel) or ".." in Path(entry.rel).parts or not _inside(Path(os.path.normpath(path)), Path(os.path.normpath(root))):
        raise ValueError(f"{entry.name}: path leaves its folder")
    return path


def _inspect(entry, path, root_real, include_sensitive, budget):
    """(size or None, status) for one entry. Reads no content; `budget` is the bytes still allowed in this snapshot."""
    if entry.cls == "sensitive" and not include_sensitive:
        return None, "sensitive-skipped"
    if not os.path.lexists(path):
        return None, "missing"
    real = Path(os.path.realpath(path))
    if not _inside(real, root_real):
        return None, "outside-root"
    try:
        st = real.stat()
    except OSError:
        return None, "unreadable"
    if not stat.S_ISREG(st.st_mode) or not os.access(real, os.R_OK):
        return None, "unreadable"
    if st.st_size > MAX_FILE or st.st_size > budget:
        return st.st_size, "too-large"
    return st.st_size, "include"


def plan_snapshot(include_sensitive=False, env=None, home=None):
    """What a snapshot would hold, and why anything is left out. Writes nothing; the same files give the same plan."""
    rt = roots(env, home)
    real = {b: Path(os.path.realpath(p)) for b, p in rt.items()}
    files, total = [], 0
    for entry in inventory(env, home):
        path = target_path(entry, env, home)
        size, status = _inspect(entry, path, real[entry.base], include_sensitive, MAX_TOTAL - total)
        if status == "include":
            total += size
        files.append(PlanFile(entry, str(path), size, status))
    return SnapshotPlan(tuple(files), include_sensitive, total)
