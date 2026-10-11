"""Recovery of Primo's own settings: what a snapshot may hold, and (in later steps) how one is taken and put back. Standard library only, no GTK.

The scope is a fixed list of Primo's files in three folders, never a walk of HOME. Every entry has a class: portable (user intent), machine
(tied to this machine), sensitive (may hold secrets or private history; left out unless asked for). Generated files and anything that is
not Primo's are not in the list at all. Reading and planning never write. Contract: .tasks 25-0.7.0-recovery-contract (kept out of git);
the frozen shapes are the dataclasses below.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import time
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


# ---------------------------------------------------------------------------------------------------- snapshots (T062)
_ID = re.compile(r"^\d{8}-\d{6}(-\d+)?$")


class RecoveryError(Exception):
    """Something recovery refuses to do or could not do; the message says what and why, never file content."""


@dataclass(frozen=True)
class ManifestFile:
    name: str
    base: str
    rel: str
    size: int
    sha256: str
    mode: int
    cls: str
    index: int


@dataclass(frozen=True)
class SnapshotManifest:
    version: int
    id: str
    created: str
    primo_revision: "str | None"
    include_sensitive: bool
    complete: bool
    files: tuple
    skipped: tuple          # ((name, reason), ...) for everything the plan did not take

    def to_dict(self):
        return {"version": self.version, "id": self.id, "created": self.created, "primo_revision": self.primo_revision,
                "include_sensitive": self.include_sensitive, "complete": self.complete,
                "files": [f.__dict__ for f in self.files], "skipped": [list(s) for s in self.skipped]}

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or d.get("version") != VERSION:
            raise RecoveryError("this snapshot was written by another version of Primo and is not read")
        try:
            return cls(d["version"], d["id"], d["created"], d.get("primo_revision"), bool(d["include_sensitive"]), bool(d["complete"]),
                       tuple(ManifestFile(**f) for f in d["files"]), tuple((str(a), str(b)) for a, b in d["skipped"]))
        except (KeyError, TypeError, ValueError) as e:
            raise RecoveryError(f"the snapshot manifest is malformed ({type(e).__name__})")


@dataclass(frozen=True)
class SnapshotSummary:
    id: str
    created: str
    complete: bool
    count: int
    bytes: int
    problem: str


def snapshots_dir(env=None, home=None):
    return cc.data_home(env, home) / "primo" / "snapshots"


def _mkdir_private(path):
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _read_stable(path):
    """(bytes, mode) of a file that did not change while it was read, or (None, reason). One retry, then it counts as changing."""
    for _attempt in range(2):
        try:
            before = os.stat(path)
            data = Path(path).read_bytes()
            after = os.stat(path)
        except OSError:
            return None, "unreadable"
        if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns) and len(data) == after.st_size:
            return (data, stat.S_IMODE(after.st_mode)), ""
    return None, "changed-during-capture"


def _write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _new_id(folder, now):
    base = time.strftime("%Y%m%d-%H%M%S", now)
    for n in range(100):
        sid = base + (f"-{n}" if n else "")
        if not (folder / sid).exists() and not (folder / f".tmp-{sid}").exists():
            return sid
    raise RecoveryError("could not choose a free snapshot name")


def create_snapshot(plan, env=None, home=None, now=None, revision=None):
    """Copy what `plan` includes into a new private snapshot and return its manifest. Never touches an existing snapshot or a source file.
    `complete` is False when a file kept changing while it was copied; such a snapshot is kept, named, and cannot be restored."""
    folder = snapshots_dir(env, home)
    existing = [p for p in folder.iterdir() if _ID.match(p.name)] if folder.is_dir() else []
    if len(existing) >= HARD_LIMIT:
        raise RecoveryError(f"there are already {len(existing)} snapshots (the limit is {HARD_LIMIT}); remove old ones with `primo snapshot remove <id>`")
    _mkdir_private(folder)
    when = now or time.localtime()
    sid = _new_id(folder, when)
    tmp = folder / f".tmp-{sid}"
    tmp.mkdir(mode=0o700)
    try:
        (tmp / "files").mkdir(mode=0o700)
        entries, skipped, complete, total = [], [(f.entry.name, f.status) for f in plan.files if f.status != "include"], True, 0
        for pf in plan.included():
            data_mode, why = _read_stable(target_path(pf.entry, env, home))
            if data_mode is None:
                skipped.append((pf.entry.name, why))
                complete = False
                continue
            data, mode = data_mode
            if len(data) > MAX_FILE or total + len(data) > MAX_TOTAL:
                skipped.append((pf.entry.name, "too-large"))
                complete = False
                continue
            index = len(entries)
            _write_private(tmp / "files" / str(index), data)
            total += len(data)
            entries.append(ManifestFile(pf.entry.name, pf.entry.base, pf.entry.rel, len(data), hashlib.sha256(data).hexdigest(), mode, pf.entry.cls, index))
        manifest = SnapshotManifest(VERSION, sid, time.strftime("%Y-%m-%dT%H:%M:%S", when), revision, plan.include_sensitive, complete,
                                    tuple(entries), tuple(skipped))
        _write_private(tmp / "manifest.json", json.dumps(manifest.to_dict(), indent=1).encode())
        dirfd = os.open(tmp, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        os.rename(tmp, folder / sid)
        return manifest
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)       # only the folder this call made
        raise


def list_snapshots(env=None, home=None):
    """Newest first. An unreadable or interrupted one is listed with a problem instead of being hidden."""
    folder = snapshots_dir(env, home)
    out = []
    try:
        names = sorted(p.name for p in folder.iterdir())
    except OSError:
        return out
    for name in names:
        path = folder / name
        if name.startswith(".tmp-"):
            out.append(SnapshotSummary(name[5:], "", False, 0, 0, "interrupted copy (remove it with `primo snapshot remove`)"))
        elif _ID.match(name) and path.is_dir() and not path.is_symlink():
            try:
                m = SnapshotManifest.from_dict(json.loads((path / "manifest.json").read_text()))
                changed = ", ".join(n for n, r in m.skipped if r == "changed-during-capture")
                out.append(SnapshotSummary(m.id, m.created, m.complete, len(m.files), sum(f.size for f in m.files),
                                           "" if m.complete else "incomplete: " + changed if changed else "incomplete"))
            except (OSError, ValueError, RecoveryError) as e:
                out.append(SnapshotSummary(name, "", False, 0, 0, f"unreadable manifest ({type(e).__name__})"))
    return sorted(out, key=lambda s: s.id, reverse=True)


def read_manifest(snapshot_id, env=None, home=None):
    """The manifest of one snapshot, parsed. Raises RecoveryError for a bad id, a missing or malformed manifest or another version."""
    if not _ID.match(snapshot_id or ""):
        raise RecoveryError("that is not a snapshot id")
    path = snapshots_dir(env, home) / snapshot_id
    if path.is_symlink() or not path.is_dir():
        raise RecoveryError("no such snapshot")
    try:
        data = json.loads((path / "manifest.json").read_text())
    except (OSError, ValueError):
        raise RecoveryError("the snapshot has no readable manifest")
    manifest = SnapshotManifest.from_dict(data)
    if manifest.id != snapshot_id:
        raise RecoveryError("the folder does not match its manifest")
    return manifest


def remove_snapshot(snapshot_id, env=None, home=None):
    """Delete one snapshot folder (or an interrupted copy) by id. Refuses anything that is not a plain folder directly inside snapshots/."""
    name = snapshot_id
    check = name[5:] if name.startswith(".tmp-") else name
    if not _ID.match(check):
        raise RecoveryError("that is not a snapshot id")
    path = snapshots_dir(env, home) / name
    if not path.is_dir() or path.is_symlink():
        raise RecoveryError("no such snapshot")
    if not name.startswith(".tmp-"):
        try:
            if json.loads((path / "manifest.json").read_text()).get("id") != name:
                raise RecoveryError("the folder does not match its manifest; it was not removed")
        except (OSError, ValueError):
            raise RecoveryError("the folder has no readable manifest; it was not removed")
    shutil.rmtree(path)


def plan_rows(plan_or_manifest):
    """One table of (name, class, state, size) for a plan and, in the same words and order, for the manifest made from it: the preview and
    the result agree. Only captured files show a size."""
    order = {e.name: i for i, e in enumerate(INVENTORY)}
    classes = {e.name: e.cls for e in INVENTORY}
    if isinstance(plan_or_manifest, SnapshotPlan):
        rows = [(f.entry.name, f.entry.cls, "captured" if f.status == "include" else f.status, f.size if f.status == "include" else None)
                for f in plan_or_manifest.files]
    else:
        m = plan_or_manifest
        rows = [(f.name, f.cls, "captured", f.size) for f in m.files] + [(n, classes.get(n, "portable"), r, None) for n, r in m.skipped]
    return sorted(rows, key=lambda r: (order.get(r[0], len(order)), r[0]))
