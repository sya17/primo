#!/usr/bin/env python3
"""Checks that a config or data file which fails to parse is copied aside before anything is saved over it, and that saves are atomic."""
import contextlib
import errno
import io
import os
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp())
os.environ["XDG_CONFIG_HOME"] = str(work / "config")
os.environ["XDG_STATE_HOME"] = str(work / "state")
os.environ.pop("PRIMO_WORKFLOW_CONFIG", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import activity_collect as ac
import config_core as cc
import hub_core
import modes_core
import workflow_core as wf


def quiet(fn, *args):
    """The result and what went to stderr."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = fn(*args)
    return out, err.getvalue()


def backups(path):
    return sorted(path.parent.glob(path.name + ".bad-*"))


def fresh(path, text=None):
    for old in list(path.parent.glob(path.name + "*")) if path.parent.exists() else []:
        old.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        path.write_text(text)


hub_path = work / "hub" / "hub.json"
# name, file, loader, saver, what a default run looks like, a valid top-level value of the wrong type
WRITERS = {
    "modes": (modes_core.CONFIG, modes_core.load_modes, lambda: modes_core.save_modes([{"id": "mine"}]),
              lambda got: got == modes_core.DEFAULT_MODES, "{}"),
    "workflow": (wf.CONFIG, wf.load, lambda: wf.save({"ics": ["https://calendar.example/private.ics"]}),
                 lambda got: got == wf.DEFAULTS, "[1, 2]"),
    "hub": (hub_path, lambda: hub_core.Store(hub_path).data, lambda: hub_core.Store(hub_path).save(),
            lambda got: got == hub_core.merged(hub_core.DEFAULTS, {}), "[1]"),
    "activity": (Path(os.environ["XDG_CONFIG_HOME"]) / "primo" / "activity.json", ac._local, None,
                 lambda got: got == {}, "[1]"),
}

for name, (path, load, save, is_default, wrong_type) in WRITERS.items():
    # a file that fails to parse: defaults for this run, a warning, the text kept next to it
    broken = '{"ics": ["https://calendar.example/private.ics"], "snippets": [ '
    fresh(path, broken)
    got, warning = quiet(load)
    assert is_default(got), (name, got)
    assert len(backups(path)) == 1 and backups(path)[0].read_text() == broken, (name, backups(path))
    assert ".bad-" in warning and path.name in warning, (name, warning)
    assert oct(backups(path)[0].stat().st_mode & 0o777) == "0o600", name
    again, warning = quiet(load)
    assert len(backups(path)) == 1 and warning == "", (name, "the same text is kept and reported once, however often it is read")
    if save:
        quiet(save)
        assert path.read_text() != broken and backups(path)[0].read_text() == broken, (name, "saving must not lose the original text")

    # valid JSON of the wrong kind of value is as unusable as a typo
    fresh(path, wrong_type)
    got, warning = quiet(load)
    assert is_default(got) and backups(path) and backups(path)[0].read_text() == wrong_type, (name, got)

    # nothing to lose: a missing or empty file is not a problem
    fresh(path)
    got, warning = quiet(load)
    assert is_default(got) and not backups(path) and warning == "", (name, "missing", warning)
    fresh(path, "")
    got, warning = quiet(load)
    assert is_default(got) and not backups(path) and warning == "", (name, "empty", warning)

# different broken text keeps both copies, even within the same second
p = modes_core.CONFIG
fresh(p, "[ first")
quiet(modes_core.load_modes)
p.write_text("[ second")
quiet(modes_core.load_modes)
assert sorted(b.read_text() for b in backups(p)) == ["[ first", "[ second"], backups(p)

# a file that went bad after it was read (an editor, another program) is still kept when the next save comes
fresh(p, "[]")
modes_core.load_modes()
p.write_text("[ oops")
modes_core.save_modes([{"id": "later"}])
assert [b.read_text() for b in backups(p)] == ["[ oops"], backups(p)
assert modes_core.load_modes() == [{"id": "later"}]

# the copy cannot be made: nothing is written
fresh(p, "[ keep me")
real = cc.preserve
def refuse(*args):
    raise OSError(errno.ENOSPC, "No space left on device")
cc.preserve = refuse
try:
    modes_core.save_modes([{"id": "x"}])
    raise AssertionError("save must fail when the broken file cannot be kept")
except OSError:
    pass
finally:
    cc.preserve = real
assert p.read_text() == "[ keep me"

# reading never fails because the copy could not be made: defaults, and the save still refuses
fresh(p, "[ keep me")
cc.preserve = refuse
try:
    got, warning = quiet(modes_core.load_modes)
finally:
    cc.preserve = real
assert got == modes_core.DEFAULT_MODES and "no copy could be made" in warning and p.read_text() == "[ keep me", (got, warning)

# unreadable is not missing: defaults for the run, and no save over what could not be read
if os.geteuid() != 0:
    fresh(p, '[{"id": "secret"}]')
    p.chmod(0)
    got, warning = quiet(modes_core.load_modes)
    assert got == modes_core.DEFAULT_MODES and warning, (got, warning)
    try:
        modes_core.save_modes([{"id": "x"}])
        raise AssertionError("save must fail when the file cannot be read")
    except PermissionError:
        pass
    p.chmod(0o600)
    assert p.read_text() == '[{"id": "secret"}]' and not backups(p)

# a save that fails half way leaves the old file and no temporary file behind
fresh(p, '[{"id": "old"}]')
real_replace = os.replace
def full(*args):
    raise OSError(errno.ENOSPC, "No space left on device")
os.replace = full
try:
    modes_core.save_modes([{"id": "new"}])
    raise AssertionError("expected the failed replace to surface")
except OSError:
    pass
finally:
    os.replace = real_replace
assert p.read_text() == '[{"id": "old"}]' and not list(p.parent.glob(".modes.json.*")), list(p.parent.iterdir())
try:
    modes_core.save_modes([object()])
except TypeError:
    pass
assert p.read_text() == '[{"id": "old"}]' and not list(p.parent.glob(".modes.json.*"))

# permissions: workflow.json is private even for a moment; other files keep what they had
fresh(wf.CONFIG)
wf.save({"ics": ["https://calendar.example/private.ics"]})
assert oct(wf.CONFIG.stat().st_mode & 0o777) == "0o600"
fresh(p, "[]")
p.chmod(0o644)
modes_core.save_modes([])
assert oct(p.stat().st_mode & 0o777) == "0o644"
fresh(p)
modes_core.save_modes([])
assert oct(p.stat().st_mode & 0o777) == "0o600"
assert modes_core.load_modes() == [], "a list of no modes is a valid choice, not a reason for the starting ones"

# a config kept in a dotfiles folder behind a symlink stays a symlink
target = work / "dotfiles" / "modes.json"
fresh(p)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("[]")
p.symlink_to(target)
modes_core.save_modes([{"id": "linked"}])
assert p.is_symlink() and modes_core.load_modes() == [{"id": "linked"}] and "linked" in target.read_text()
p.unlink()

# small state files use the same atomic write
state = work / "state" / "nested" / "state.json"
cc.atomic_write(state, '{"a": 1}')
assert state.read_text() == '{"a": 1}' and [f.name for f in state.parent.iterdir()] == ["state.json"]

# ---- one place for the XDG directories: an empty or relative value is ignored, as the specification says
home = Path.home()
saved = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")}
os.environ["XDG_CONFIG_HOME"], os.environ["XDG_DATA_HOME"], os.environ["XDG_STATE_HOME"] = "", "relative/dir", str(work / "st")
assert cc.config_home() == home / ".config" and cc.data_home() == home / ".local/share" and cc.state_home() == work / "st"
for k, v in saved.items():
    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
assert modes_core.CONFIG == cc.config_home() / "primo" / "modes.json" and hub_core.STATE_DIR == cc.state_home() / "hyprland-dotfiles" / "hub"

# every tool finds the directories through config_core, so an unusual XDG value means the same folder everywhere
scripts_dir = Path(__file__).resolve().parent
own = [f for f in sorted((scripts_dir.parent / "config" / "hypr" / "scripts").glob("*.py")) + [scripts_dir / "primo"]
       if f.name != "config_core.py" and any(v in f.read_text() for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"))]
assert not own, [f.name for f in own]

# ---- the strict loader for validation: the value, None when absent, or one error naming the file, line and column
d = work / "strict"
d.mkdir()
(d / "ok.json").write_text('{"a": 1}')
(d / "ok.toml").write_text('version = 1\nname = "Work"\n[apps]\nterm = "kitty"\n')
(d / "list.json").write_text("[1]")
assert cc.load(d / "ok.json") == {"a": 1} and cc.load(d / "ok.toml")["apps"] == {"term": "kitty"} and cc.load(d / "list.json", list) == [1]
assert cc.load(d / "absent.json") is None
(d / "empty.json").write_text("  \n")
assert cc.load(d / "empty.json") is None

(d / "bad.json").write_text('{\n  "ics": ["https://calendar.example/private.ics"],\n  "snippets": [ oops ]\n}')
try:
    cc.load(d / "bad.json")
    raise AssertionError("a broken JSON file must raise")
except cc.ConfigError as e:
    assert (e.path, e.line, e.column) == (d / "bad.json", 3, 17) and str(e).startswith(f"{d / 'bad.json'}:3:17: "), str(e)
    assert "private.ics" not in str(e) and "oops" not in str(e), "an error never repeats the content of the file"

(d / "bad.toml").write_text('version = 1\nname = \n')
try:
    cc.load(d / "bad.toml")
    raise AssertionError("a broken TOML file must raise")
except cc.ConfigError as e:
    assert e.line == 2 and "(at line" not in e.problem, str(e)

try:
    cc.load(d / "list.json")
    raise AssertionError("the wrong kind of value must raise")
except cc.ConfigError as e:
    assert "list" in e.problem and e.line is None, str(e)

(d / "new.json").write_text('{"version": 2, "a": 1}')
(d / "v1.json").write_text('{"version": 1, "a": 1}')
assert cc.load(d / "v1.json") == {"version": 1, "a": 1}
try:
    cc.load(d / "new.json")
    raise AssertionError("a file from a newer Primo must be refused")
except cc.ConfigError as e:
    assert "newer" in e.problem, str(e)

# a file from a newer Primo is neither replaced by defaults on save nor copied aside as broken
p = modes_core.CONFIG
fresh(wf.CONFIG, '{"version": 9, "ics": ["https://calendar.example/private.ics"]}')
got, warning = quiet(wf.load)
assert got == wf.DEFAULTS and "newer" in warning and not backups(wf.CONFIG), (got, warning)
try:
    wf.save({"ics": []})
    raise AssertionError("save must refuse to replace a file from a newer Primo")
except cc.ConfigError:
    pass
assert "version" in wf.CONFIG.read_text()

if os.geteuid() != 0:
    (d / "locked.json").write_text("{}")
    (d / "locked.json").chmod(0)
    try:
        cc.load(d / "locked.json")
        raise AssertionError("an unreadable file must raise")
    except cc.ConfigError as e:
        assert "cannot be read" in e.problem
    (d / "locked.json").chmod(0o600)

print("ok")
