#!/usr/bin/env python3
"""Upgrade checks: the settings and data that earlier Primo releases wrote are read, kept and restorable by this one.

The fixtures in scripts/fixtures/upgrade/<tag>/ were written by each release's own code (`python3 scripts/test-upgrade.py --regenerate`, which needs a
checkout with the release tags). The checks themselves need only the fixtures. Sample data only: no real settings, no secrets."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "scripts" / "fixtures" / "upgrade"
SCRIPTS = ROOT / "config" / "hypr" / "scripts"
PRIMO = str(ROOT / "scripts" / "primo")
TAGS = ["v0.2.0", "v0.3.0", "v0.4.0", "v0.5.0", "v0.6.0", "v0.7.0"]

GEN = r'''
import json, os, sys
from pathlib import Path
out = Path(sys.argv[1]); tag = sys.argv[2]
os.environ.update(XDG_CONFIG_HOME=str(out / "config"), XDG_DATA_HOME=str(out / "data"), XDG_STATE_HOME=str(out / "state"), HOME=str(out / "home"))
import config_core as cc, modes_core as mc, workflow_core as wc, hub_core as hc
mc.save_modes(mc.DEFAULT_MODES + [{"id": "docs", "name": "Docs", "icon": "document-edit", "ask_dir": False, "vpn": "", "power": "", "dnd": False, "focus": False,
                                   "category": "Work", "apps": [{"cmd": "kitty", "ws": 3, "match": ""}]}])
wc.save({**wc.DEFAULTS, "ics": ["https://calendar.invalid/work.ics"], "snippets": [{"trigger": "sig", "text": "Thanks, and regards"}]})
hub_path = (out / "state" / "hyprland-dotfiles" / "hub" / "hub.json") if tag == "v0.2.0" else (out / "data" / "primo" / "hub.json")
s = hc.Store(hub_path)
s["reminders"].append({"id": "r1", "title": "call the dentist", "due": "2026-10-20T09:00", "repeat": None, "done": False, "fired": False})
s["reminders"].append({"id": "r2", "title": "water plants", "due": "2026-10-13T08:00", "repeat": "daily", "done": False, "fired": False})
s["alarms"].append({"id": "a1", "time": "07:30", "label": "wake up", "days": [0, 1, 2, 3, 4], "on": True, "next": None})
s["timers"].append({"id": "t1", "total": 600, "end": 0, "left": 300.0})
s.save()
for name, base, rel, kind in getattr(cc, "FILES", []):
    if name in ("activity", "overview", "ui"):
        cc.write_json(out / {"config": "config", "data": "data", "state": "state"}[base] / rel, {"version": 1})
st = out / "state" / "hyprland-dotfiles"; st.mkdir(parents=True, exist_ok=True)
(st / "current").write_text("primo-dusk\n"); (st / "last-dark").write_text("primo-dusk\n")
'''


def regenerate():
    for tag in TAGS:
        out = FIX / tag
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        tree = Path(tempfile.mkdtemp(prefix="primo-upgrade-gen-"))
        tar = subprocess.run(["git", "-C", str(ROOT), "archive", tag, "config/hypr/scripts"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(tree)], input=tar.stdout, check=True)
        env = dict(os.environ, PYTHONPATH=str(tree / "config/hypr/scripts"))
        subprocess.run([sys.executable, "-c", GEN, str(out), tag], env=env, check=True, capture_output=True, cwd=tree)
        shutil.rmtree(tree)
        shutil.rmtree(out / "home", ignore_errors=True)
        for p in out.rglob("*"):
            if p.is_file() and p.name.startswith(".") or p.suffix == ".pyc":
                p.unlink()
        print("wrote", out.relative_to(ROOT), sum(1 for p in out.rglob("*") if p.is_file()), "files")


if "--regenerate" in sys.argv:
    regenerate()
    sys.exit(0)


def put_home(tag):
    """A temporary HOME holding what that release wrote."""
    home = Path(tempfile.mkdtemp(prefix="primo-upgrade-"))
    for src, dst in (("config", ".config"), ("data", ".local/share"), ("state", ".local/state")):
        if (FIX / tag / src).is_dir():
            shutil.copytree(FIX / tag / src, home / dst)
    return home


def files(home):
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(home).rglob("*")) if p.is_file()}


def run(home, *args, extra=None):
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", NO_COLOR="1", PYTHONPATH=str(SCRIPTS), **(extra or {}))
    r = subprocess.run([sys.executable, *args], env=env, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout, r.stderr


READ = r'''
import json, sys
import config_core as cc, modes_core as mc, workflow_core as wc, hub_core as hc
bad = []
for name, path, kind in cc.known_files():
    try:
        cc.load(path, kind)
    except cc.ConfigError as e:
        bad.append(f"{name}: {e.problem}")
path, notice = hc.migrate()
store = hc.Store(path)
print(json.dumps({"bad": bad, "hub": str(path), "notice": notice, "reminders": [r["title"] for r in store["reminders"]], "alarms": [a["label"] for a in store["alarms"]],
                  "timers": [t["id"] for t in store["timers"]], "modes": [m["id"] for m in mc.load_modes()], "ics": wc.load()["ics"],
                  "snippets": [s.get("text") for s in wc.load()["snippets"]]}))
'''

if not (FIX / TAGS[0]).is_dir():
    print("skipped: the upgrade fixtures are missing")
    sys.exit(0)

for tag in TAGS:
    assert (FIX / tag).is_dir(), f"no fixture for {tag}; run --regenerate in a checkout with the tags"
    home = put_home(tag)
    before = files(home)
    code, out, err = run(home, "-c", READ)
    assert code == 0, (tag, err)
    seen = json.loads(out)
    # U1: what that release wrote is read whole by this one
    assert seen["bad"] == [], (tag, seen["bad"])
    assert seen["reminders"] == ["call the dentist", "water plants"] and seen["alarms"] == ["wake up"] and seen["timers"] == ["t1"], (tag, seen)
    assert seen["modes"][-1] == "docs" and {"work", "research", "writing", "relax"} <= set(seen["modes"]), (tag, seen["modes"])
    assert seen["ics"] == ["https://calendar.invalid/work.ics"] and seen["snippets"] == ["Thanks, and regards"], (tag, seen)
    after = files(home)
    if tag == "v0.2.0":
        # the hub data lived in the state folder: it is moved once, the old file kept, the notice absent, and the content identical
        assert seen["hub"].endswith(".local/share/primo/hub.json") and (home / ".local/share/primo/hub.json").is_file(), seen
        assert any(k.endswith("hub.json.bak-primo") for k in after), "the old hub file is kept as a backup, never deleted"
        moved = [v for k, v in after.items() if k.endswith("share/primo/hub.json")][0]
        assert moved == [v for k, v in before.items() if k.endswith("hub/hub.json")][0], "moved byte for byte"
    else:
        assert after == before, f"{tag}: reading settings and data must not rewrite them"
    # U5/U6 with real old data: a snapshot, losing everything, a restore that gives the same bytes back
    code, out, err = run(home, PRIMO, "snapshot", "--include-sensitive", "--json")
    assert code == 0 and json.loads(out)["complete"], (tag, out, err)
    sid = json.loads(out)["snapshot"]
    snapshot_files = files(home)
    for p in list((home / ".config/primo").glob("*.json")) + [home / ".local/share/primo/hub.json"]:
        p.unlink()
    code, out, err = run(home, PRIMO, "restore", sid, "--apply", "--include-machine")
    assert code == 0, (tag, out, err)
    restored = files(home)
    for k, v in snapshot_files.items():
        if "/snapshots/" in k or "/recovery/" in k:
            continue
        assert restored.get(k) == v, f"{tag}: {k} did not come back byte for byte"
    code, out, err = run(home, PRIMO, "config", "validate")
    assert code == 0, (tag, out, err)
    shutil.rmtree(home)

# ---- U2: older, newer and malformed files
sys.path.insert(0, str(SCRIPTS))
import config_core as cc  # noqa: E402
home = put_home("v0.7.0")
env = {"HOME": str(home)}
ui = home / ".config/primo/ui.json"
ui.write_text('{"version": 2, "reduce_motion": true}')
try:
    cc.load(ui, dict)
    raise AssertionError("a newer file is a named incompatibility")
except cc.ConfigError as e:
    assert e.newer
before = ui.read_bytes()
try:
    cc.write_json(ui, {"version": 1})
    raise AssertionError("a file from a newer Primo is never saved over")
except cc.ConfigError:
    pass
assert ui.read_bytes() == before and not list(ui.parent.glob("ui.json.bad-*"))
modes = home / ".config/primo/modes.json"
modes.write_text('[{"id": "x",\n')                                                  # malformed: kept aside before any save
cc.write_json(modes, [{"id": "new"}])
kept = list(modes.parent.glob("modes.json.bad-*"))
assert len(kept) == 1 and kept[0].read_text() == '[{"id": "x",\n' and json.loads(modes.read_text()) == [{"id": "new"}]
code, out, err = run(home, PRIMO, "update", "check", "--json", extra={"PRIMO_REPO": str(home)})
ui.write_text('{"version": 2}')
code, out, err = run(home, PRIMO, "update", "check", "--json", extra={"PRIMO_REPO": str(home)})
assert {c["id"]: c["level"] for c in json.loads(out)["checks"]}["config-version"] == "block", "the update check calls a newer file an incompatibility"
shutil.rmtree(home)

# ---- U4: units, foreign links and disabled services around an upgrade in place
home = Path(tempfile.mkdtemp(prefix="primo-upgrade-"))
bindir = home / "bin"
bindir.mkdir()
log = home / "calls.log"
(bindir / "systemctl").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n[ "$*" = "--user show-environment" ] && exit 0\nexit 0\n')
(bindir / "systemctl").chmod(0o755)
for tool in ("bash", "env", "ln", "rm", "mkdir", "readlink", "dirname", "sed", "cat", "date", "grep"):
    (bindir / tool).symlink_to(shutil.which(tool))
env = {"HOME": str(home), "PATH": str(bindir)}
units = home / ".config/systemd/user"
units.mkdir(parents=True)
(units / "primo-hub.service").write_text("# mine\n")                              # the user's own unit with a Primo name
(units / "other.service").write_text("# unrelated\n")
(units / "primo-hub.service.d").mkdir()
for i in range(2):                                                                  # install twice: an upgrade in place re-runs it
    r = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), "--services"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
assert (units / "primo-hub.service").read_text() == "# mine\n" and (units / "other.service").read_text() == "# unrelated\n" and (units / "primo-hub.service.d").is_dir()
assert (units / "primo-launcher.service").is_symlink(), "the others are linked"
r = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), "--remove-services"], env=env, capture_output=True, text=True, timeout=60)
assert r.returncode == 0 and (units / "primo-hub.service").read_text() == "# mine\n" and not (units / "primo-launcher.service").exists()
calls = log.read_text()
assert " start " not in calls and " stop " not in calls and " restart " not in calls and "mask" not in calls, "installing and removing never start, stop or restart a service"
shutil.rmtree(home)

# ---- U7: the recovery, update and repair code has no way to rewrite refs, reset a checkout, stash, pull, fetch, install packages or run shell text
import re  # noqa: E402
banned_git = {"reset", "stash", "pull", "fetch", "checkout", "clean", "rebase", "merge", "commit", "add", "push", "gc", "config", "apply", "switch", "restore", "tag", "branch"}
update_text = (SCRIPTS / "update_core.py").read_text()
git_args = set(re.findall(r'_git\(repo, "([a-z-]+)"', update_text))
assert git_args and git_args <= {"rev-parse", "status", "rev-list", "remote"}, git_args
assert not (git_args & banned_git)
assert update_text.count("subprocess.run(") == 1 and "def _git" in update_text.split("subprocess.run(")[0].rsplit("def ", 1)[-1] + "def _git", "git is the only process update_core starts"
assert "subprocess" not in (SCRIPTS / "recovery_core.py").read_text(), "recovery starts no process at all"
repair_text = (SCRIPTS / "repair_core.py").read_text()
assert repair_text.count("subprocess.run(") == 1 and 'subprocess.run([script, "--generate-only", theme]' in repair_text, "the only process repair starts is the reviewed theme command"
for name in ("recovery_core.py", "update_core.py", "repair_core.py"):
    text = (SCRIPTS / name).read_text()
    for needle in ("shell=True", "os.system", "os.popen", "eval(", "exec("):   # a hint string may name pacman; only code that could run it matters
        assert needle not in text.replace("tomllib.loads", ""), (name, needle)

print("ok: upgrade")
