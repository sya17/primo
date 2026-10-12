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
assert p.steps[0].target == str(repo / "themes/primo-dusk") and p.steps[0].detail == f"{repo / 'scripts/theme-switch'} --generate-only primo-dusk"
assert p.effects == tuple(str(repo / g) for g in rp.THEME_OUTPUTS) and set(dc.GENERATED) <= set(rp.THEME_OUTPUTS) and "git-ignored" in p.backup and "nothing in ~/.config" in p.backup and "hypr-theme" in p.recovery
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
# ---- the real theme-switch --generate-only writes exactly THEME_OUTPUTS, and nothing else anywhere
ROOT = Path(__file__).resolve().parent.parent
import shutil  # noqa: E402
T = Path(tempfile.mkdtemp(prefix="primo-repair-"))
copy = T / "repo"
(copy / "scripts").mkdir(parents=True)
shutil.copy(ROOT / "scripts/theme-switch", copy / "scripts/theme-switch")
shutil.copytree(ROOT / "templates", copy / "templates")
(copy / "themes").mkdir()
shutil.copytree(ROOT / "themes/primo-dusk", copy / "themes/primo-dusk")
for d in ("wallpaper",):
    if (ROOT / d).exists():
        shutil.copytree(ROOT / d, copy / d)
th_home = T / "home"
th_home.mkdir()
shim = T / "shim"
shim.mkdir()
shot = T / "shim.log"
for tool in ("gsettings", "kwriteconfig6", "hyprctl", "pkill", "swaync-client", "notify-send", "setsid", "dconf", "systemctl"):
    (shim / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >> "{shot}"\n')
    (shim / tool).chmod(0o755)
login = T / "login"
login.mkdir()
before_files = {str(p.relative_to(copy)) for p in copy.rglob("*") if p.is_file()}
r = subprocess.run([str(copy / "scripts/theme-switch"), "--generate-only", "primo-dusk"], cwd=copy, capture_output=True, text=True, timeout=120,
                   env=dict(os.environ, HOME=str(th_home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", PRIMO_LOGIN_DIR=str(login), PATH=f"{shim}:{os.environ['PATH']}"))
assert r.returncode == 0, r.stderr
new = {str(p.relative_to(copy)) for p in copy.rglob("*") if p.is_file()} - before_files
gone = before_files - {str(p.relative_to(copy)) for p in copy.rglob("*") if p.is_file()}
assert new == set(rp.THEME_OUTPUTS) or new == set(rp.THEME_OUTPUTS) - {"config/hypr/logo.png"}, sorted(new ^ set(rp.THEME_OUTPUTS))
assert not gone and not list(th_home.rglob("*")) and not list(login.iterdir()), "nothing outside the repository's generated files is written"
assert not shot.exists(), shot.read_text() if shot.exists() else ""      # no gsettings, no kwriteconfig6, no hyprctl, no reload
assert not (copy / "sddm").exists(), "the login screen files are not touched"
shutil.rmtree(T)

# ---- T068: apply
import errno  # noqa: E402


def fake_theme_script(repo, mode="ok"):
    """A stand-in for theme-switch: writes every output (ok), fails (fail), or exits 0 having written nothing (lazy)."""
    body = {"ok": "for f in " + " ".join(rp.THEME_OUTPUTS) + '; do mkdir -p "$(dirname "$f")"; echo rendered > "$f"; done\n', "fail": "echo boom >&2\nexit 3\n", "lazy": "exit 0\n"}[mode]
    (repo / "scripts/theme-switch").write_text("#!/bin/sh\ncd \"$(dirname \"$0\")/..\" || exit 9\n" + body)
    (repo / "scripts/theme-switch").chmod(0o755)


def journals(home):
    d = home / ".local/share/primo/recovery"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# config.json: restore, keep the broken copy, read it back, harmless to repeat
home, repo, s = make()
snap = snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
(home / ".config/primo/ui.json").write_text('{"version": 1, "reduce_motion": true}')           # a valid edit made since: must survive
isf = lambda k: Path(k).is_file()
other = {k: v for k, v in tree(home).items() if isf(k) and "modes.json" not in k and "/recovery/" not in k and "/snapshots/" not in k}
plan = rp.plan_repair("config.json", s)
res = rp.apply_repair(plan, s)
assert res.ok and res.changed and not res.reason and res.steps_done == ("modes",) and len(res.journals) == 1, res
assert (home / ".config/primo/modes.json").read_text() == '[{"id": "work"}]'
bads = list((home / ".config/primo").glob("modes.json.bad-*"))
assert len(bads) == 1 and bads[0].read_text() == "[" and stat.S_IMODE(bads[0].stat().st_mode) == 0o600, "the broken bytes are kept"
assert {k: v for k, v in tree(home).items() if isf(k) and "modes.json" not in k and "/recovery/" not in k and "/snapshots/" not in k and ".bad-" not in k} == {k: v for k, v in other.items() if ".bad-" not in k}, "nothing else changed, later edits included"
assert rp.plan_repair("config.json", s).blocked == "nothing-to-repair", "read back: the files parse now"
count = len(journals(home))
again = rp.apply_repair(plan, s)                                                               # the same, now stale, plan
assert again.ok and not again.changed and again.reason == "nothing-to-repair" and len(journals(home)) == count, "repeating is harmless and leaves no trace"
back = rc.rollback_restore(res.journals[0], env={}, home=home)
assert back.rolled_back and (home / ".config/primo/modes.json").read_text() == "[", "and the repair can be undone"

# a plan that is no longer true changes nothing
home, repo, s = make()
snap = snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
plan = rp.plan_repair("config.json", s)
time_before = tree(home)
newer_snap = None
import time as _t  # noqa: E402
_t.sleep(1.1)
(home / ".config/primo/modes.json").write_text('[{"id": "newer good"}]')
newer_snap = snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
assert rp.plan_repair("config.json", s).steps[0].snapshot == newer_snap.id != plan.steps[0].snapshot
before = tree(home)
res = rp.apply_repair(plan, s)
assert not res.ok and res.reason == "target-changed" and not res.changed and tree(home) == before, "a plan made for another snapshot is refused whole"
blob = home / ".local/share/primo/snapshots" / newer_snap.id / "files" / "0"
snapdir = home / ".local/share/primo/snapshots"
import shutil as _sh  # noqa: E402
for sid in (newer_snap.id, snap.id):
    _sh.rmtree(snapdir / sid)
res = rp.apply_repair(plan, s)
assert not res.ok and res.reason == "target-changed" and tree(home) == tree(home) and (home / ".config/primo/modes.json").read_text() == "[", "no source left: refused, untouched"
blocked_plan = rp.plan_repair("config.json", s)
res = rp.apply_repair(blocked_plan, s)
assert not res.ok and res.reason == "no-snapshot" and not res.changed
assert rp.apply_repair(rp.plan_repair("service.hub", s), s).reason == "not-allowlisted"
fake = rp.RepairPlan("rm -rf /", "x", (rp.RepairStep("restore-file", "/etc/passwd", "x"),), None)
assert rp.apply_repair(fake, s).reason == "not-allowlisted"

# failures: the restore stops, or the file still does not parse afterwards
home, repo, s = make()
snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
plan = rp.plan_repair("config.json", s)
real_apply = rc.apply_restore
def stops(restore_plan, env=None, home_=None, now=None):
    raise rc.RecoveryError("a stand-in failure")
rc.apply_restore = stops
try:
    res = rp.apply_repair(plan, s)
finally:
    rc.apply_restore = real_apply
assert not res.ok and res.reason == "failed" and "stand-in" in res.detail and (home / ".config/primo/modes.json").read_text() == "["
real_broken = rp._broken_files
calls = {"n": 0}
def still_broken(s_):
    calls["n"] += 1
    return real_broken(s_) if calls["n"] <= 1 else [("modes", home / ".config/primo/modes.json", list, False)]
rp._broken_files = still_broken
try:
    res = rp.apply_repair(plan, s)
finally:
    rp._broken_files = real_broken
assert not res.ok and res.reason == "verification-failed" and "rolled back" in res.detail and (home / ".config/primo/modes.json").read_text() == "[", res

# theme.generated: regenerate, keep copies, read back
home, repo, s = make()
fake_theme_script(repo, "ok")
(repo / dc.GENERATED[0]).unlink()
(repo / dc.GENERATED[1]).write_text("color: {{accent}};\n")
(repo / "config/hypr/hyprland.lua").write_text("my own config\n")                              # not a generated file: must stay as it is
plan = rp.plan_repair("theme.generated", s)
res = rp.apply_repair(plan, s)
assert res.ok and res.changed and res.steps_done == ("primo-dusk",), res
assert all((repo / g).read_text() == "rendered\n" for g in dc.GENERATED) and (repo / "config/hypr/hyprland.lua").read_text() == "my own config\n"
jdir = home / ".local/share/primo/recovery" / res.journals[0]
assert stat.S_IMODE(jdir.stat().st_mode) == 0o700 and any(p.read_text() == "color: {{accent}};\n" for p in (jdir / "pre").iterdir()), "a copy of what was there is kept"
assert rp.plan_repair("theme.generated", s).blocked == "nothing-to-repair"
count = len(journals(home))
assert rp.apply_repair(plan, s).reason == "nothing-to-repair" and len(journals(home)) == count
# a failing or lazy script leaves the files exactly as they were
for mode, reason in (("fail", "failed"), ("lazy", "verification-failed")):
    home, repo, s = make()
    fake_theme_script(repo, mode)
    (repo / dc.GENERATED[0]).unlink()
    (repo / dc.GENERATED[1]).write_text("color: {{accent}};\n")
    snap_files = {str(p): p.read_bytes() for p in repo.rglob("*") if p.is_file()}
    res = rp.apply_repair(rp.plan_repair("theme.generated", s), s)
    assert not res.ok and res.reason == reason and "put back" in res.detail, (mode, res)
    assert {str(p): p.read_bytes() for p in repo.rglob("*") if p.is_file()} == snap_files, mode
# the script times out
home, repo, s = make()
fake_theme_script(repo, "ok")
(repo / dc.GENERATED[0]).unlink()
plan = rp.plan_repair("theme.generated", s)
real_run = subprocess.run
subprocess.run = lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("theme-switch", 60))
try:
    res = rp.apply_repair(plan, s)
finally:
    subprocess.run = real_run
assert not res.ok and res.reason == "failed" and not (repo / dc.GENERATED[0]).exists(), res


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

# ---- the Doctor itself never repairs: no import, no default action
assert "import repair_core" not in Path(dc.__file__).read_text() and "apply_repair" not in Path(dc.__file__).read_text()

home, repo, s = make()
cenv = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", NO_COLOR="1")
snapshot(home)
(home / ".config/primo/modes.json").write_text("[")
assert cli("--apply")[0] == 64, "--apply alone is a usage error"
code, out, _e = cli("--repair", "config.json", "--apply")
assert code == 0 and "done" in out and "journal:" in out and (home / ".config/primo/modes.json").read_text() == '[{"id": "work"}]', out
code, out, _e = cli("--repair", "config.json", "--apply", "--json")
doc = json.loads(out)
assert code == 0 and doc["result"]["ok"] and not doc["result"]["changed"] and doc["result"]["reason"] == "nothing-to-repair" and doc["applied"] is False
assert cli("--repair", "service.hub", "--apply")[0] == 2


# ---- acceptance: one story end to end, the read-only commands stay read-only, and no secret or private file ever reaches a snapshot
home, repo, s = make()
cenv = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", NO_COLOR="1", PRIMO_REPO=str(repo))
SECRET = "S3CR3T-" + "TOKEN"
(home / ".config/primo/workflow.json").write_text(json.dumps({"ics": ["https://calendar.invalid/feed?token=" + SECRET], "snippets": [{"text": SECRET}]}))
(home / ".config/primo/workflow.json").chmod(0o600)
(home / ".local/state/hyprland-dotfiles/launcher-history.json").write_text(json.dumps(["search " + SECRET]))
(home / ".local/share/primo/hub.json").write_text(json.dumps({"reminders": [{"title": "call", "due": None}]}))
for private in (".ai/rules.md", ".tasks/plan.md", "Notes/diary.md", ".config/keepassxc/db.kdbx", ".config/mozilla/prefs.js", "workspace/secret.txt", ".ssh/id_ed25519"):
    (home / private).parent.mkdir(parents=True, exist_ok=True)
    (home / private).write_text("private " + SECRET)
def run(*a, extra=None):
    r = subprocess.run([sys.executable, PRIMO, *a], env=dict(cenv, **(extra or {})), capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr
before = tree(home)
for cmd in (("config", "path"), ("config", "show"), ("config", "validate"), ("snapshot", "--dry-run"), ("snapshot", "list"), ("update", "check"), ("doctor", "--repair", "config.json"),
            ("doctor", "--repair", "theme.generated"), ("doctor", "--repair", "nope")):
    run(*cmd)
assert tree(home) == before, "the read-only commands change nothing, not even a timestamp"
code, out, _e = run("snapshot")
assert code == 0
snap_dir = home / ".local/share/primo/snapshots"
everything = b"".join(p.read_bytes() for p in snap_dir.rglob("*") if p.is_file())
assert SECRET.encode() not in everything and b"private " not in everything and b"diary" not in everything, "no secret, private file or planning folder is in a snapshot"
sid = rc.list_snapshots(env={}, home=home)[0].id
man = rc.read_manifest(sid, {}, home)
assert {f.name for f in man.files} == {"modes", "ui", "hub", "current"} and ("workflow", "sensitive-skipped") in man.skipped
code, out, _e = run("snapshot", "--include-sensitive")
assert code == 0 and SECRET.encode() in b"".join(p.read_bytes() for p in snap_dir.rglob("*") if p.is_file()), "taken only when asked for"
# the story: settings break, the Doctor's plan fixes them, a restore brings back an older hub, a rollback undoes it, an update check reads all of it
(home / ".config/primo/modes.json").write_text("[")
(home / ".local/share/primo/hub.json").write_text(json.dumps({"reminders": []}))
code, out, _e = run("doctor", "--repair", "config.json", "--apply")
assert code == 0 and (home / ".config/primo/modes.json").read_text() == '[{"id": "work"}]', out
code, out, _e = run("restore", sid, "--only", "hub", "--apply")
assert code == 0 and json.loads((home / ".local/share/primo/hub.json").read_text())["reminders"][0]["title"] == "call", out
code, out, _e = run("restore", "--rollback", sorted(p.name for p in (home / ".local/share/primo/recovery").iterdir())[-1])
assert code == 0 and json.loads((home / ".local/share/primo/hub.json").read_text())["reminders"] == []
code, out, _e = run("update", "check", "--json")
doc = json.loads(out)
assert {c["id"]: c["level"] for c in doc["checks"]}["config"] == "ok" and {c["id"] for c in doc["checks"]} >= {"snapshot", "checkout", "tools"}
# nothing in the commands claims more than they do
help_text = run("snapshot", "--help")[1] + run("restore", "--help")[1] + run("update", "--help")[1] + run("doctor", "--help")[1]
assert "rollback" in run("restore", "--help")[1] and "package" not in help_text.lower().replace("not the repository or packages", "")

print("ok: repair")
