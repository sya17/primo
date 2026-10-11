#!/usr/bin/env python3
"""Checks for ui_core: the two interface preferences (reduce motion, reduce transparency), the policy they produce, and how the file is read
and saved. No display and no GTK: temporary XDG folders only; write failures are injected, never provoked with permissions."""
import itertools
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="primo ui "))
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data")):
    os.environ[var] = str(work / sub)
os.environ["HOME"] = str(work / "home")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "config" / "hypr" / "scripts"))
import config_core as cc
import ui_core as ui

assert "gi" not in sys.modules, "ui_core must not import GTK"
path = ui.preferences_path()
assert path == work / "config" / "primo" / "ui.json"
warnings = []
handler = logging.Handler()
handler.emit = lambda record: warnings.append(record.getMessage())
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.DEBUG)


def backups():
    return sorted(path.parent.glob("ui.json.bad-*")) if path.parent.exists() else []


# ---- defaults and the value types
assert ui.UiPreferences() == ui.UiPreferences(False, False)
try:
    ui.UiPreferences().reduce_motion = True
    raise AssertionError("preferences must be immutable")
except (AttributeError, TypeError):
    pass
assert ui.parse_preferences({}) == ui.UiPreferences(), "absent flags use the defaults"
assert ui.parse_preferences({"version": 1, "reduce_motion": True}) == ui.UiPreferences(True, False)
assert ui.parse_preferences({"reduce_transparency": True, "from_the_future": [1, 2]}) == ui.UiPreferences(False, True), "unknown keys are tolerated"
for bad in ("true", "false", "yes", 1, 0, None, [], {}):
    for key in ("reduce_motion", "reduce_transparency"):
        try:
            ui.parse_preferences({key: bad})
            raise AssertionError((key, bad, "must be an actual boolean"))
        except ui.UiPreferenceError as e:
            assert key in str(e)
for not_dict in ([], "x", 3, None):
    try:
        ui.parse_preferences(not_dict)
        raise AssertionError("not a table")
    except ui.UiPreferenceError:
        pass

# ---- the policy: all eight combinations
for system, motion, transparency in itertools.product((True, False), repeat=3):
    policy = ui.resolve_policy(ui.UiPreferences(motion, transparency), system)
    assert policy.animate == (system and not motion) and policy.opaque == transparency, (system, motion, transparency, policy)
assert ui.resolve_policy(ui.UiPreferences(False, False), False).animate is False, "the system setting always wins"
try:
    ui.resolve_policy(ui.UiPreferences(), None)
    raise AssertionError("the system setting must be a boolean")
except ui.UiPreferenceError:
    pass

# ---- reading: nothing is created, nothing is rewritten
assert ui.load_preferences() == ui.UiPreferences() and not path.exists() and not path.parent.exists(), "a read never creates the file or its folder"
path.parent.mkdir(parents=True)
path.write_text('{"version": 1, "reduce_motion": true}')
before = path.read_bytes()
assert ui.load_preferences() == ui.UiPreferences(True, False) and path.read_bytes() == before
path.write_text("")
assert ui.load_preferences() == ui.UiPreferences() and not backups()
path.write_text('{ "reduce_motion": tru')                              # malformed: defaults, original bytes kept, a copy beside it
bad = path.read_bytes()
del warnings[:]
for _ in range(5):
    assert ui.load_preferences() == ui.UiPreferences()
assert path.read_bytes() == bad and len(backups()) == 1 and backups()[0].read_bytes() == bad
assert 0 < len(warnings) <= 2, ("a broken file is reported, not once per read", warnings)
path.write_text('["not", "a", "table"]')
assert ui.load_preferences() == ui.UiPreferences() and path.read_text() == '["not", "a", "table"]'
path.write_text('{"version": 9, "reduce_motion": true}')               # newer: defaults, never saved over
newer = path.read_bytes()
assert ui.load_preferences() == ui.UiPreferences()
try:
    ui.save_preferences(ui.UiPreferences(True, True))
    raise AssertionError("must refuse a file from a newer Primo")
except cc.ConfigError as e:
    assert e.newer
assert path.read_bytes() == newer
path.write_text('{"reduce_motion": "false", "reduce_transparency": true}')   # a false-looking string is not false
del warnings[:]
assert ui.load_preferences() == ui.UiPreferences() and warnings and "reduce_motion" in warnings[0]
assert path.read_text() == '{"reduce_motion": "false", "reduce_transparency": true}'
path.unlink()
path.mkdir()                                                            # unreadable: a folder where the file should be
assert ui.load_preferences() == ui.UiPreferences()
try:
    ui.save_preferences(ui.UiPreferences(True, False))
    raise AssertionError("must refuse an unreadable file")
except OSError:
    pass
path.rmdir()

# ---- saving
ui.save_preferences(ui.UiPreferences(True, False))
assert json.loads(path.read_text()) == {"version": 1, "reduce_motion": True, "reduce_transparency": False}
assert oct(path.stat().st_mode & 0o777) == "0o600" and ui.load_preferences() == ui.UiPreferences(True, False)
path.write_text(json.dumps({"version": 1, "reduce_motion": False, "theme_hint": {"keep": "me"}, "reduce_transparency": False}))
ui.save_preferences(ui.UiPreferences(False, True))
assert json.loads(path.read_text()) == {"version": 1, "reduce_motion": False, "theme_hint": {"keep": "me"}, "reduce_transparency": True}, "unknown keys survive"
path.write_text("{ not json")                                           # malformed: backed up before the repair
for old in backups():
    old.unlink()
ui.save_preferences(ui.UiPreferences(True, True))
assert [b.read_text() for b in backups()] == ["{ not json"] and ui.load_preferences() == ui.UiPreferences(True, True)

# a failed write: the error reaches the caller, the previous file is intact
good = path.read_bytes()
real = cc.atomic_write
def full_disk(*a, **k): raise OSError(28, "No space left on device")
cc.atomic_write = full_disk
try:
    ui.save_preferences(ui.UiPreferences(False, False))
    raise AssertionError("a failed save must raise")
except OSError as e:
    assert e.errno == 28
finally:
    cc.atomic_write = real
assert path.read_bytes() == good and ui.load_preferences() == ui.UiPreferences(True, True)
assert not [p for p in path.parent.iterdir() if p.name.startswith(".ui.json.")], "no partial file"
try:
    ui.save_preferences({"reduce_motion": True})
    raise AssertionError("save takes UiPreferences")
except ui.UiPreferenceError:
    pass

# ---- `primo config` finds the file with the existing rules
env = {**os.environ}
run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "primo"), "config", *a], capture_output=True, text=True, env=env, timeout=30)
shown = json.loads(run("path", "--json").stdout)
assert any(f["name"] == "ui" and f["path"] == str(path) for f in shown["files"]), shown
ok = run("validate")
assert ok.returncode == 0, ok.stdout
view = json.loads(run("show", "--json").stdout)
entry = next(e for e in view["files"] if e["name"] == "ui")
assert entry["value"]["reduce_motion"] is True and entry["source"]["reduce_motion"] == str(path) and entry["source"]["version"] == str(path)
path.write_text('{"reduce_motion": ')
invalid = run("validate")
assert invalid.returncode == 2 and "ui.json" in invalid.stdout
print("ui core checks passed")
