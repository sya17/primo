#!/usr/bin/env python3
"""Checks for repair_core: which Doctor findings Primo may fix, and the read-only plan for each. (Applying a plan is covered further down.)

Everything runs on a temporary HOME and a temporary copy of a repository layout; no command is ever run by a plan."""
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "config" / "hypr" / "scripts"))
import doctor_core as dc  # noqa: E402
import recovery_core as rc  # noqa: E402
import repair_core as rp  # noqa: E402


def make(good_modes=True):
    home = Path(tempfile.mkdtemp(prefix="primo-repair-"))
    repo = home / "repo"
    for g in dc.GENERATED:
        (repo / g).parent.mkdir(parents=True, exist_ok=True)
        (repo / g).write_text("generated\n")
    (repo / "themes/primo-dusk").mkdir(parents=True)
    (repo / "themes/primo-dusk/theme.conf").write_text("name=Primo Dusk\n")
    (repo / "scripts").mkdir()
    script = repo / "scripts/theme-switch"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    for d in (".config/primo", ".local/share/primo", ".local/state/hyprland-dotfiles"):
        (home / d).mkdir(parents=True)
    (home / ".local/state/hyprland-dotfiles/current").write_text("primo-dusk\n")
    (home / ".config/primo/modes.json").write_text('[{"id": "work"}]' if good_modes else "[")
    (home / ".config/primo/ui.json").write_text('{"version": 1}')
    s = dc.System(env={}, home=home, repo=repo)
    return home, repo, s


def snapshot(home):
    return rc.create_snapshot(rc.plan_snapshot(env={}, home=home), env={}, home=home)


def tree(home):
    out = {}
    for p in sorted(home.rglob("*")):
        st = p.lstat()
        out[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else "")
    return out


def no_commands():
    """Make any attempt to start a process fail loudly while a plan is made."""
    def boom(*a, **k):
        raise AssertionError("a repair plan must not run a command")
    saved = (subprocess.run, subprocess.Popen, os.system)
    subprocess.run = subprocess.Popen = os.system = boom
    return lambda: (setattr(subprocess, "run", saved[0]), setattr(subprocess, "Popen", saved[1]), setattr(os, "system", saved[2]))


# ---- the list: exactly the two reviewed findings, everything else is refused with a stable reason
assert set(rp.REPAIRABLE) == {"config.json", "theme.generated"}
home, repo, s = make()
for fid in ("service.hub", "config.links", "dependency.bar", "config.path", "theme.fonts", "config.waybar", "unit.primo-hub.service", "", "../../etc/passwd", "config.json; rm -rf /"):
    p = rp.plan_repair(fid, s)
    assert p.blocked == "not-allowlisted" and not p.steps and not p.effects, (fid, p)

# ---- config.json
before = tree(home)
undo = no_commands()
try:
    p = rp.plan_repair("config.json", s)
finally:
    undo()
assert p.blocked == "nothing-to-repair" and not p.steps
assert tree(home) == before

(home / ".config/primo/modes.json").write_text("[")                                 # now broken, and no snapshot exists
assert rp.plan_repair("config.json", s).blocked == "no-snapshot"
(home / ".config/primo/modes.json").write_text('[{"id": "work"}]')
good = snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
before = tree(home)
undo = no_commands()
try:
    p = rp.plan_repair("config.json", s)
finally:
    undo()
assert tree(home) == before, "a plan writes nothing, not even a timestamp"
assert p.blocked is None and p.finding_id == "config.json" and len(p.steps) == 1
step = p.steps[0]
assert step.kind == "restore-file" and step.target == str(home / ".config/primo/modes.json") and step.snapshot == good.id and step.name == "modes", step
assert p.effects == (step.target,) and ".bad-" in p.backup and "--rollback" in p.recovery
try:
    p.steps = ()
    raise AssertionError("a plan is immutable")
except Exception as e:
    assert type(e).__name__ == "FrozenInstanceError"

# the newest snapshot that really holds a file that parses wins; a bad copy in a newer one, an incomplete one and a tampered one are skipped
import time  # noqa: E402
time.sleep(1.1)
bad_snap = snapshot(home)                                                            # taken while modes.json was broken: its copy is no good
time.sleep(1.1)
p = rp.plan_repair("config.json", s)
assert p.blocked is None and p.steps[0].snapshot == good.id, "the older snapshot with a good copy is used"
blob = home / ".local/share/primo/snapshots" / good.id / "files" / "0"
blob.write_bytes(b"X" * blob.stat().st_size)                                         # tamper with the only good copy
p = rp.plan_repair("config.json", s)
assert p.blocked == "snapshot-file-invalid" and "modes.json" in p.blocked_detail and not p.steps
blob.write_bytes(b'[{"id": "work"}]')                                                # the original bytes again: the hash matches, the snapshot is sound
assert rp.plan_repair("config.json", s).blocked is None

# a settings file from a newer Primo needs an update, not a restore
home, repo, s = make()
snapshot(home)
(home / ".config/primo/ui.json").write_text('{"version": 99}')
p = rp.plan_repair("config.json", s)
assert p.blocked == "newer-primo" and "ui.json" in p.blocked_detail
# one fixable and one not: the plan does not do half
home, repo, s = make()
(home / ".config/primo/mine.json").write_text("{}")
snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
(home / ".config/primo/mine.json").write_text("{")
(home / ".config/primo/new.json").write_text("{")                                    # broken and never in any snapshot
p = rp.plan_repair("config.json", s)
assert p.blocked == "snapshot-file-invalid" and "new.json" in p.blocked_detail and not p.steps, p
# an incomplete snapshot is not a source
home, repo, s = make()
m = snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
d = json.loads((home / ".local/share/primo/snapshots" / m.id / "manifest.json").read_text())
d["complete"] = False
(home / ".local/share/primo/snapshots" / m.id / "manifest.json").write_text(json.dumps(d))
assert rp.plan_repair("config.json", s).blocked == "no-snapshot"

# ---- theme.generated
home, repo, s = make()
assert rp.plan_repair("theme.generated", s).blocked == "nothing-to-repair"
(repo / dc.GENERATED[0]).unlink()
(repo / dc.GENERATED[1]).write_text("color: {{accent}};\n")
before = tree(home)
undo = no_commands()
try:
    p = rp.plan_repair("theme.generated", s)
finally:
    undo()
assert tree(home) == before
assert p.blocked is None and len(p.steps) == 1 and p.steps[0].kind == "regenerate-theme"
assert p.steps[0].target == str(repo / "themes/primo-dusk") and p.steps[0].detail == f"{repo / 'scripts/theme-switch'} --no-reload primo-dusk"
assert p.effects == tuple(str(repo / g) for g in dc.GENERATED) and "git-ignored" in p.backup and "nothing is reloaded" in p.backup and "hypr-theme" in p.recovery
for bad in ("../x", "/etc", ".hidden", "no-such-theme", ""):
    (home / ".local/state/hyprland-dotfiles/current").write_text(bad + "\n")
    q = rp.plan_repair("theme.generated", s)
    assert q.blocked == "theme-missing" and not q.steps, (bad, q)
(home / ".local/state/hyprland-dotfiles/current").unlink()
assert rp.plan_repair("theme.generated", s).blocked == "theme-missing"
(home / ".local/state/hyprland-dotfiles/current").write_text("primo-dusk\n")
(repo / "scripts/theme-switch").chmod(0o644)
assert rp.plan_repair("theme.generated", s).blocked == "theme-script-missing"
(repo / "scripts/theme-switch").unlink()
assert rp.plan_repair("theme.generated", s).blocked == "theme-script-missing"
real_find = dc.find_repo
dc.find_repo = lambda _s: None
try:
    assert rp.plan_repair("theme.generated", s).blocked == "repo-not-found"
finally:
    dc.find_repo = real_find

# ---- the Doctor: only findings on the list can say they are repairable
assert dc.Result("x", "c", "t", "pass").repairable is False
# ---- the CLI: preview only, stable JSON, exit codes (0 plan, 1 nothing to repair, 2 cannot)
PRIMO = str(Path(__file__).resolve().parent / "primo")
home, repo, s = make()
cenv = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", NO_COLOR="1")
def cli(*a):
    r = subprocess.run([sys.executable, PRIMO, "doctor", *a], env=cenv, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr
assert cli("--repair", "config.json")[0] == 1
snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
before = tree(home)
code, out, _e = cli("--repair", "config.json", "--json")
doc = json.loads(out)
assert code == 0 and doc["blocked"] is None and doc["applied"] is False and doc["steps"][0]["kind"] == "restore-file" and tree(home) == before
code, out, _e = cli("--repair", "config.json")
assert code == 0 and "restore-file" in out and "nothing is written" in out and "undo:" in out
assert cli("--repair", "service.hub")[0] == 2 and "not-allowlisted" in cli("--repair", "service.hub")[1]

print("ok: repair")
