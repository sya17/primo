#!/usr/bin/env python3
"""Checks for recovery_core: what a snapshot may hold (the plan), and later steps' snapshot, restore and repair behavior.

Everything runs on a temporary HOME with sample files; nothing real is read, nothing outside the temp folder is written."""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "config" / "hypr" / "scripts"))
import recovery_core as rc  # noqa: E402


def make_home():
    home = Path(tempfile.mkdtemp(prefix="primo-recovery-"))
    env = {"HOME": str(home)}
    for d in (".config/primo", ".local/share/primo", ".local/state/hyprland-dotfiles"):
        (home / d).mkdir(parents=True)
    return home, env


def put(home, rel, text="{}", mode=0o644):
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    p.chmod(mode)
    return p


def tree_state(home):
    """Every path with its size, mtime and content hash: a plan must leave all of it exactly as it was."""
    out = {}
    for p in sorted(home.rglob("*")):
        st = p.lstat()
        out[str(p)] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else "")
    return out


def by_name(plan):
    return {f.entry.name: f for f in plan.files}


# ---- T061: the plan
home, env = make_home()
put(home, ".config/primo/modes.json", "[]")
put(home, ".config/primo/ui.json", '{"version": 1}')
put(home, ".config/primo/workflow.json", '{"feeds": ["https://x/?token=SECRET"]}', 0o600)
put(home, ".config/primo/extra-theme.toml", "a = 1\n")
put(home, ".config/primo/modes.json.bad-20261011-010101", "garbage")            # a kept-aside copy is not Primo's data to snapshot
put(home, ".local/share/primo/hub.json", '{"reminders": []}')
put(home, ".local/state/hyprland-dotfiles/current", "primo-dusk\n")
put(home, ".local/state/hyprland-dotfiles/wallpaper", "/home/u/pic.png\n")
put(home, ".local/state/hyprland-dotfiles/launcher-history.json", '["secret search"]', 0o600)
put(home, ".local/state/hyprland-dotfiles/mpvpaper.log", "x" * 100)               # logs are not in the inventory at all
put(home, ".local/state/hyprland-dotfiles/gh-prs.json", "{}")                       # generated
put(home, "Notes/diary.md", "private")                                              # user data outside the roots
before = tree_state(home)
plan = rc.plan_snapshot(env=env, home=home)
assert tree_state(home) == before, "a plan must not change any file, folder or timestamp"
assert rc.plan_snapshot(env=env, home=home) == plan, "the same files give the same plan"
names = by_name(plan)
assert names["modes"].status == "include" and names["ui"].status == "include" and names["hub"].status == "include" and names["current"].status == "include"
assert names["workflow"].status == "sensitive-skipped" and names["launcher-history"].status == "sensitive-skipped"
assert names["wallpaper"].status == "include" and names["wallpaper"].entry.cls == "machine"
assert names["activity"].status == "missing" and names["overview"].status == "missing"
assert "primo/extra-theme.toml" in names and names["primo/extra-theme.toml"].entry.kind == "toml" and names["primo/extra-theme.toml"].status == "include"
assert not any("bad-" in n or "mpvpaper" in n or "gh-prs" in n or "Notes" in n for n in names), sorted(names)
assert all(f.size is None for f in plan.files if f.status == "sensitive-skipped"), "a skipped secret file is not even measured"
assert plan.total_bytes == sum(f.size for f in plan.included())
wide = by_name(rc.plan_snapshot(include_sensitive=True, env=env, home=home))
assert wide["workflow"].status == "include" and wide["launcher-history"].status == "include"

# the plan carries paths, sizes and statuses, never file content
dump = repr(plan) + repr(rc.plan_snapshot(include_sensitive=True, env=env, home=home))
assert "SECRET" not in dump and "secret search" not in dump and "private" not in dump

# ---- symlinks: inside the same root they are read through; leaving it, never
home, env = make_home()
put(home, ".config/primo/real-modes.json", "[]")
(home / ".config/primo/modes.json").symlink_to(home / ".config/primo/real-modes.json")
put(home, "outside/ui.json", '{"version": 1}')
(home / ".config/primo/ui.json").symlink_to(home / "outside/ui.json")
(home / ".config/primo/overview.json").symlink_to(home / "nowhere.json")           # dangling
names = by_name(rc.plan_snapshot(env=env, home=home))
assert names["modes"].status == "include", "a link that stays inside its folder is fine"
assert names["ui"].status == "outside-root", "a link that leaves the folder is never followed"
assert names["overview"].status == "outside-root", "a dangling link that points out of the folder is not followed either"
(home / ".local/state/hyprland-dotfiles/current").mkdir()                           # a folder where a file belongs
assert by_name(rc.plan_snapshot(env=env, home=home))["current"].status == "unreadable"

# ---- limits: one big file is left out and named, the snapshot says so; the total is capped too
home, env = make_home()
put(home, ".config/primo/modes.json", "x" * (rc.MAX_FILE + 1))
put(home, ".local/share/primo/hub.json", "{}")
plan = rc.plan_snapshot(env=env, home=home)
names = by_name(plan)
assert names["modes"].status == "too-large" and names["modes"].size == rc.MAX_FILE + 1 and names["hub"].status == "include"
assert plan.total_bytes == 2
home, env = make_home()
for i in range(6):
    put(home, f".config/primo/part{i}.json", "y" * (rc.MAX_FILE - 10))
plan = rc.plan_snapshot(env=env, home=home)
assert plan.total_bytes <= rc.MAX_TOTAL and sum(f.status == "too-large" for f in plan.files) >= 2, [f.status for f in plan.files if f.entry.name.startswith("primo/")]

# ---- unreadable: reported by name and status only
home, env = make_home()
p = put(home, ".config/primo/modes.json", "[]", 0o000)
if os.geteuid() != 0:
    assert by_name(rc.plan_snapshot(env=env, home=home))["modes"].status == "unreadable"
p.chmod(0o644)

# ---- a tampered path never resolves outside its root
bad = rc.RecoveryEntry("x", "config", "../../etc/passwd", "text", "portable")
try:
    rc.target_path(bad, env, home)
    raise AssertionError("a path that leaves its folder must be refused")
except ValueError:
    pass
assert all(rc.target_path(e, env, home) for e in rc.inventory(env, home))

# ---- T062: capture
import json  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

home, env = make_home()
put(home, ".config/primo/modes.json", '[{"id": "work"}]')
put(home, ".config/primo/workflow.json", '{"feeds": ["https://x/?token=SECRET"]}', 0o600)
put(home, ".local/share/primo/hub.json", '{"reminders": [{"title": "call"}]}')
put(home, ".local/state/hyprland-dotfiles/current", "primo-dusk\n")
put(home, ".local/state/hyprland-dotfiles/mode-dirs.json", '{"work": "/home/u/code"}', 0o600)
before = tree_state(home)
plan = rc.plan_snapshot(env=env, home=home)
m = rc.create_snapshot(plan, env=env, home=home, revision="0.7.0")
assert m.complete and m.version == 1 and m.primo_revision == "0.7.0" and not m.include_sensitive
assert sorted(f.name for f in m.files) == ["current", "hub", "mode-dirs", "modes"], [f.name for f in m.files]
assert ("workflow", "sensitive-skipped") in m.skipped and ("activity", "missing") in m.skipped
snap = home / ".local/share/primo/snapshots" / m.id
assert stat.S_IMODE(snap.stat().st_mode) == 0o700 and stat.S_IMODE((snap.parent).stat().st_mode) == 0o700
assert stat.S_IMODE((snap / "manifest.json").stat().st_mode) == 0o600
for f in m.files:                                                       # bytes retained exactly, hashed, private, mode of the source recorded
    blob = (snap / "files" / str(f.index)).read_bytes()
    src = rc.target_path(rc.RecoveryEntry(f.name, f.base, f.rel, "text", f.cls), env, home)
    assert blob == src.read_bytes() and hashlib.sha256(blob).hexdigest() == f.sha256 and f.size == len(blob)
    assert stat.S_IMODE((snap / "files" / str(f.index)).stat().st_mode) == 0o600 and f.mode == stat.S_IMODE(src.stat().st_mode)
assert "SECRET" not in (snap / "manifest.json").read_text() and not any("SECRET" in p.read_text() for p in snap.rglob("*") if p.is_file()), "left-out secrets are not copied"
after = tree_state(home)
is_file = lambda k: Path(k).is_file()
assert {k: v for k, v in after.items() if "/snapshots" not in k and is_file(k)} == {k: v for k, v in before.items() if is_file(k)}, "taking a snapshot changes no source file"
assert rc.plan_rows(plan)[0][:2] == ("modes", "portable")
preview = {(n, "captured") for n, _c, st, _s in rc.plan_rows(plan) if st == "captured"}
assert preview == {(n, "captured") for n, _c, st, _s in rc.plan_rows(m) if st == "captured"}, "the preview and the result name the same files"
left = {(n, st) for n, _c, st, _s in rc.plan_rows(plan) if st != "captured"}
assert left == {(n, r) for n, r in m.skipped}, "and the same files left out, for the same reasons"

# including the sensitive ones is explicit, and recorded
m2 = rc.create_snapshot(rc.plan_snapshot(include_sensitive=True, env=env, home=home), env=env, home=home)
assert m2.include_sensitive and "workflow" in [f.name for f in m2.files] and m2.id != m.id
assert [s.id for s in rc.list_snapshots(env, home)] == [m2.id, m.id], "newest first, nothing overwritten"
assert (snap / "manifest.json").read_bytes() == json.dumps(m.to_dict(), indent=1).encode(), "the first snapshot is untouched by the second"
assert rc.read_manifest(m.id, env, home) == m

# a source that keeps changing while it is copied is never called complete
home, env = make_home()
put(home, ".config/primo/modes.json", "[1]")
put(home, ".local/share/primo/hub.json", "{}")
real = rc._read_stable
calls = []
def flaky(path):
    if str(path).endswith("modes.json"):
        calls.append(1)
        return None, "changed-during-capture"
    return real(path)
rc._read_stable = flaky
m = rc.create_snapshot(rc.plan_snapshot(env=env, home=home), env=env, home=home)
rc._read_stable = real
assert not m.complete and ("modes", "changed-during-capture") in m.skipped and [f.name for f in m.files] == ["hub"]
assert "modes" in [s.problem for s in rc.list_snapshots(env, home)][0], rc.list_snapshots(env, home)
# the real reader notices a size/mtime change between its two looks
tmpf = home / "x.txt"
tmpf.write_text("abc")
orig_stat = os.stat
state = {"n": 0}
def moving_stat(p, *a, **k):
    if str(p) == str(tmpf):
        state["n"] += 1
        if state["n"] % 2 == 0:                                  # the file grows between the first look and the second
            tmpf.write_text("abc" + "d" * state["n"])
    return orig_stat(p, *a, **k)
os.stat = moving_stat
try:
    got = rc._read_stable(tmpf)
finally:
    os.stat = orig_stat
assert got[0] is None and got[1] == "changed-during-capture", got

# a failed copy leaves nothing behind but a name we can see, and never half of a snapshot under a real id
home, env = make_home()
put(home, ".config/primo/modes.json", "[1]")
put(home, ".local/share/primo/hub.json", "{}")
real_write = rc._write_private
def failing(path, data):
    if "files" in str(path) and str(path).endswith("/1"):
        raise OSError("disk full")
    return real_write(path, data)
rc._write_private = failing
try:
    rc.create_snapshot(rc.plan_snapshot(env=env, home=home), env=env, home=home)
    raise AssertionError("the failure must reach the caller")
except OSError:
    pass
finally:
    rc._write_private = real_write
assert rc.list_snapshots(env, home) == [] and not [p for p in (home / ".local/share/primo/snapshots").iterdir()], "an owned temporary folder is cleaned up"
# an interrupted copy from a killed run is listed, and removable by its id only
(home / ".local/share/primo/snapshots/.tmp-20261012-010101").mkdir()
assert rc.list_snapshots(env, home)[0].problem.startswith("interrupted")
rc.remove_snapshot(".tmp-20261012-010101", env, home)

# limits and removal
home, env = make_home()
put(home, ".local/share/primo/hub.json", "{}")
folder = home / ".local/share/primo/snapshots"
for i in range(rc.HARD_LIMIT):
    (folder / f"20260101-0000{i:02d}").mkdir(parents=True)
try:
    rc.create_snapshot(rc.plan_snapshot(env=env, home=home), env=env, home=home)
    raise AssertionError("past the hard limit nothing is created")
except rc.RecoveryError as e:
    assert str(rc.HARD_LIMIT) in str(e)
for bad in ("../x", "20260101-000000/../..", "", "latest", ".tmp-../x"):
    try:
        rc.remove_snapshot(bad, env, home)
        raise AssertionError(f"{bad!r} must be refused")
    except rc.RecoveryError:
        pass
(folder / "20260101-000000").rmdir()
(home / "keep").mkdir()
(folder / "20260101-000001").rmdir()
(folder / "20260101-000001").symlink_to(home / "keep")
try:
    rc.remove_snapshot("20260101-000001", env, home)
    raise AssertionError("a link is never followed")
except rc.RecoveryError:
    pass
assert (home / "keep").is_dir()
home, env = make_home()
put(home, ".local/share/primo/hub.json", "{}")
m = rc.create_snapshot(rc.plan_snapshot(env=env, home=home), env=env, home=home)
rc.remove_snapshot(m.id, env, home)
assert rc.list_snapshots(env, home) == [] and (home / ".local/share/primo/hub.json").exists()

# ---- the CLI: preview and creation agree, JSON is stable, nothing leaks
PRIMO = str(Path(__file__).resolve().parent / "primo")
home, env = make_home()
put(home, ".config/primo/modes.json", "[]")
put(home, ".config/primo/workflow.json", '{"feeds": ["https://x/?token=SECRET"]}', 0o600)
put(home, ".local/share/primo/hub.json", "{}")
cenv = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", NO_COLOR="1")
def cli(*a):
    r = subprocess.run([sys.executable, PRIMO, "snapshot", *a], env=cenv, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout, r.stderr
code, out, _e = cli("--dry-run", "--json")
assert code == 0 and not (home / ".local/share/primo/snapshots").exists(), "--dry-run writes nothing"
dry = json.loads(out)
code, out, _e = cli("--json")
done = json.loads(out)
assert code == 0 and done["complete"] and done["rows"] == dry["rows"], "the preview and the result are the same table"
assert "SECRET" not in out and "SECRET" not in cli("list")[1] and "SECRET" not in cli("show", done["snapshot"])[1]
code, out, _e = cli("list", "--json")
assert [s["id"] for s in json.loads(out)["snapshots"]] == [done["snapshot"]]
assert cli("show")[0] == 64 and cli("remove")[0] == 64 and cli("nonsense")[0] == 64
assert cli("remove", "../../etc")[0] == 2 and cli("show", "20990101-000000")[0] == 2
assert cli("remove", done["snapshot"])[0] == 0 and json.loads(cli("list", "--json")[1])["snapshots"] == []

# ---- T063: validate a snapshot, preview a restore
import copy  # noqa: E402
import dataclasses  # noqa: E402


def fresh():
    h, e = make_home()
    put(h, ".config/primo/modes.json", '[{"id": "a"}]')
    put(h, ".config/primo/ui.json", '{"version": 1}')
    put(h, ".config/primo/extra.toml", "a = 1\n")
    put(h, ".local/share/primo/hub.json", '{"reminders": []}')
    put(h, ".local/state/hyprland-dotfiles/current", "primo-dusk\n")
    put(h, ".local/state/hyprland-dotfiles/wallpaper", "/home/u/a.png\n")
    man = rc.create_snapshot(rc.plan_snapshot(env=e, home=h), env=e, home=h)
    return h, e, man


def manifest_path(h, man):
    return h / ".local/share/primo/snapshots" / man.id / "manifest.json"


def edit_manifest(h, man, fn):
    path = manifest_path(h, man)
    d = json.loads(path.read_text())
    fn(d)
    path.write_text(json.dumps(d, indent=1))


def refused(h, e, man, why):
    m, problems = rc.load_snapshot(man.id, e, h)
    assert problems and why in " ".join(problems), (why, problems)
    try:
        rc.plan_restore(man.id, env=e, home=h)
        raise AssertionError(f"a snapshot with this problem ({why}) must not give a plan")
    except rc.RecoveryError as err:
        assert "cannot be restored" in str(err)


home, env, man = fresh()
m, problems = rc.load_snapshot(man.id, env, home)
assert problems == [] and m == man, problems

# every way a snapshot can be wrong is named, and no plan follows
h, e, man = fresh(); blob = h / ".local/share/primo/snapshots" / man.id / "files" / "0"
blob.write_bytes(blob.read_bytes() + b" "); refused(h, e, man, "wrong size")
h, e, man = fresh(); blob = h / ".local/share/primo/snapshots" / man.id / "files" / "0"
blob.write_bytes(b"X" * blob.stat().st_size); refused(h, e, man, "was changed")
h, e, man = fresh(); (h / ".local/share/primo/snapshots" / man.id / "files" / "1").unlink(); refused(h, e, man, "missing")
h, e, man = fresh(); (h / ".local/share/primo/snapshots" / man.id / "files" / "7").write_text("x"); refused(h, e, man, "unexpected")
h, e, man = fresh(); b = h / ".local/share/primo/snapshots" / man.id / "files" / "0"; keep = b.read_bytes(); b.unlink(); (h / "elsewhere").write_bytes(keep); b.symlink_to(h / "elsewhere"); refused(h, e, man, "missing")
for label, change, why in (
        ("path out of the folder", lambda d: d["files"][0].update(rel="../../../etc/passwd"), "not a file recovery may restore"),
        ("absolute path", lambda d: d["files"][0].update(rel="/etc/passwd"), "not a file recovery may restore"),
        ("unknown name", lambda d: d["files"][0].update(name="evil", rel="evil.sh"), "not a file recovery may restore"),
        ("extra script", lambda d: d["files"][0].update(name="primo/run.sh", rel="run.sh"), "not a file recovery may restore"),
        ("kept-aside copy", lambda d: d["files"][0].update(name="primo/modes.json.bad-1", rel="modes.json.bad-1"), "not a file recovery may restore"),
        ("class changed", lambda d: [f.update(cls="portable") for f in d["files"] if f["name"] == "wallpaper"], "not a file recovery may restore"),
        ("another base", lambda d: d["files"][0].update(base="state"), "not a file recovery may restore"),
        ("bad hash", lambda d: d["files"][0].update(sha256="zz"), "malformed"),
        ("huge size", lambda d: d["files"][0].update(size=rc.MAX_FILE + 1), "malformed"),
        ("bad mode", lambda d: d["files"][0].update(mode=0o7777), "malformed"),
        ("listed twice", lambda d: d["files"].append(copy.deepcopy(d["files"][0])), "listed twice"),
        ("incomplete", lambda d: d.update(complete=False), "incomplete")):
    h, e, man = fresh()
    edit_manifest(h, man, change)
    refused(h, e, man, why)
h, e, man = fresh()
edit_manifest(h, man, lambda d: d.update(version=2))
for call in (lambda: rc.load_snapshot(man.id, e, h), lambda: rc.plan_restore(man.id, env=e, home=h)):
    try:
        call()
        raise AssertionError("a newer snapshot version is refused, not guessed")
    except rc.RecoveryError as err:
        assert "another version" in str(err)
h, e, man = fresh()
manifest_path(h, man).write_text("{not json")
try:
    rc.load_snapshot(man.id, e, h)
    raise AssertionError
except rc.RecoveryError as err:
    assert "manifest" in str(err)

# the preview: create / replace / same / skip, from the files as they are now, and it writes nothing
home, env, man = fresh()
(home / ".config/primo/ui.json").write_text('{"version": 1, "reduce_motion": true}')       # differs now
(home / ".config/primo/modes.json").unlink()                                              # gone now
(home / ".local/state/hyprland-dotfiles/current").unlink()                               # a folder where the file was
(home / ".local/state/hyprland-dotfiles/current").mkdir()
before = tree_state(home)
plan = rc.plan_restore(man.id, env=env, home=home)
assert tree_state(home) == before, "a restore preview must not change anything"
acts = {a.name: a for a in plan.actions}
assert acts["modes"].action == "create" and acts["modes"].target_sha256 is None
assert acts["ui"].action == "replace" and acts["ui"].target_sha256 == hashlib.sha256(b'{"version": 1, "reduce_motion": true}').hexdigest()
assert acts["hub"].action == "same" and acts["primo/extra.toml"].action == "same"
assert acts["current"].action == "skip" and "folder" in acts["current"].reason
assert acts["wallpaper"].action == "skip" and acts["wallpaper"].machine and "include-machine" in acts["wallpaper"].reason
assert plan.manifest_sha256 == hashlib.sha256(manifest_path(home, man).read_bytes()).hexdigest() and plan.snapshot_id == man.id
assert [a for a in rc.plan_restore(man.id, env=env, home=home).actions] == list(plan.actions), "same inputs, same plan"
try:
    plan.actions = ()
    raise AssertionError("a plan is immutable")
except dataclasses.FrozenInstanceError:
    pass
wide = {a.name: a for a in rc.plan_restore(man.id, include_machine=True, env=env, home=home).actions}
assert wide["wallpaper"].action in ("same", "create", "replace")
only = {a.name: a for a in rc.plan_restore(man.id, only=["ui"], env=env, home=home).actions}
assert only["ui"].action == "replace" and only["modes"].action == "skip" and only["modes"].reason == "not selected"
try:
    rc.plan_restore(man.id, only=["nope"], env=env, home=home)
    raise AssertionError
except rc.RecoveryError as err:
    assert "nope" in str(err)
# a target that is a link leaving its folder is never a restore target
home, env, man = fresh()
(home / ".config/primo/ui.json").unlink()
(home / "elsewhere.json").write_text("{}")
(home / ".config/primo/ui.json").symlink_to(home / "elsewhere.json")
assert {a.name: a for a in rc.plan_restore(man.id, env=env, home=home).actions}["ui"].action == "skip"
# a link that stays inside its folder is a normal target
(home / ".config/primo/ui.json").unlink()
put(home, ".config/primo/ui-real.json", "{}")
(home / ".config/primo/ui.json").symlink_to(home / ".config/primo/ui-real.json")
assert {a.name: a for a in rc.plan_restore(man.id, env=env, home=home).actions}["ui"].action == "replace"

# the CLI preview
PRIMO = str(Path(__file__).resolve().parent / "primo")
home, env, man = fresh()
cenv = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", NO_COLOR="1")
(home / ".config/primo/ui.json").write_text("{}")
def run_cli(*a):
    r = subprocess.run([sys.executable, PRIMO, *a], env=cenv, capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout, r.stderr
before = tree_state(home)
code, out, _e = run_cli("restore", man.id)
assert code == 0 and "replace  ui" in out.replace("  ", "  ") and "nothing is written" in out and tree_state(home) == before
code, out, _e = run_cli("restore", man.id, "--json")
assert code == 0 and json.loads(out)["applied"] is False and {a["name"]: a["action"] for a in json.loads(out)["actions"]}["ui"] == "replace"
assert run_cli("restore", "20990101-000000")[0] == 2 and run_cli("restore", man.id, "--only", "nope")[0] == 2 and run_cli("restore")[0] != 0
blob = home / ".local/share/primo/snapshots" / man.id / "files" / "0"
blob.write_bytes(b"X" * blob.stat().st_size)
assert run_cli("restore", man.id)[0] == 2 and run_cli("snapshot", "show", man.id)[0] == 2 and "was changed" in run_cli("snapshot", "show", man.id)[1]

# ---- T064: apply a restore, fail in the middle, recover
import errno  # noqa: E402


def files_of(h):
    return {str(p): p.read_bytes() for p in sorted(h.rglob("*")) if p.is_file() and "/recovery/" not in str(p) and "/snapshots/" not in str(p)}


def damage(h):
    (h / ".config/primo/ui.json").write_text('{"version": 1, "reduce_motion": true}')
    (h / ".config/primo/modes.json").unlink()
    (h / ".local/share/primo/hub.json").write_text('{"reminders": ["newer"]}')


home, env, man = fresh()
good = files_of(home)
damage(home)
damaged = files_of(home)
plan = rc.plan_restore(man.id, env=env, home=home)
res = rc.apply_restore(plan, env=env, home=home)
assert res.complete and not res.failed and sorted(res.applied) == ["hub", "modes", "ui"], res
after = files_of(home)
assert {k: v for k, v in after.items() if not k.endswith("wallpaper")} == {k: v for k, v in good.items() if not k.endswith("wallpaper")}, "restored files are the snapshot's bytes"
jdir = home / ".local/share/primo/recovery" / res.journal
assert stat.S_IMODE(jdir.stat().st_mode) == 0o700 and stat.S_IMODE((jdir / "journal.json").stat().st_mode) == 0o600
assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in (jdir / "pre").iterdir()) and len(list((jdir / "pre").iterdir())) == 2, "a private copy of each replaced file"
j = json.loads((jdir / "journal.json").read_text())
assert j["status"] == "done" and {e["name"]: e["state"] for e in j["entries"]} == {"modes": "done", "ui": "done", "hub": "done"}
assert stat.S_IMODE((home / ".config/primo/ui.json").stat().st_mode) == 0o644, "the permissions of a replaced file are kept"
back = rc.rollback_restore(res.journal, env=env, home=home)
assert back.rolled_back and sorted(back.applied) == ["hub", "modes", "ui"] and files_of(home) == damaged, "rollback returns exactly to the state before"
assert json.loads((jdir / "journal.json").read_text())["status"] == "rolled-back"

# a restore changes only the planned files; everything else, mtimes included, stays
home, env, man = fresh()
damage(home)
put(home, ".config/primo/workflow.json", "{}", 0o600)
put(home, "Notes/keep.md", "mine")
pre = {k: v for k, v in tree_state(home).items() if Path(k).is_file()}
rc.apply_restore(rc.plan_restore(man.id, env=env, home=home), env=env, home=home)
post = {k: v for k, v in tree_state(home).items() if Path(k).is_file() and "/recovery/" not in k}
changed = sorted({Path(k).name for k in post if k in pre and post[k] != pre[k]} | {Path(k).name for k in post if k not in pre})
assert changed == ["hub.json", "modes.json", "ui.json"], changed

# a target edited between preview and apply is not overwritten; the others still are
home, env, man = fresh()
damage(home)
plan = rc.plan_restore(man.id, env=env, home=home)
(home / ".config/primo/ui.json").write_text("edited after the preview")
res = rc.apply_restore(plan, env=env, home=home)
assert (home / ".config/primo/ui.json").read_text() == "edited after the preview"
assert ("ui", "changed-since-preview") in res.skipped and not res.complete and not res.failed and sorted(res.applied) == ["hub", "modes"]
# ... also a file that appeared, and a link swapped in
home, env, man = fresh()
damage(home)
plan = rc.plan_restore(man.id, env=env, home=home)
put(home, ".config/primo/modes.json", "created by the user meanwhile")
(home / ".config/primo/ui.json").unlink()
(home / "outside.json").write_text("x")
(home / ".config/primo/ui.json").symlink_to(home / "outside.json")
res = rc.apply_restore(plan, env=env, home=home)
assert (home / ".config/primo/modes.json").read_text() == "created by the user meanwhile" and (home / "outside.json").read_text() == "x"
assert {n for n, _r in res.skipped} >= {"modes", "ui"} and res.applied == ("hub",)
# the snapshot changing after the preview refuses the whole apply
home, env, man = fresh()
damage(home)
plan = rc.plan_restore(man.id, env=env, home=home)
edit_manifest(home, man, lambda d: d.update(created="2000-01-01T00:00:00"))
before = files_of(home)
try:
    rc.apply_restore(plan, env=env, home=home)
    raise AssertionError
except rc.RecoveryError as err:
    assert "changed since the preview" in str(err)
assert files_of(home) == before and not (home / ".local/share/primo/recovery").exists(), "a refused apply leaves no trace"


def inject(after_calls, exc, wrong_bytes=False):
    """Make the n-th write of a restored file fail (journal writes pass through). Returns an undo function."""
    real_aw, state = rc.cc.atomic_write, {"n": 0}
    def aw(path, text, mode=None):
        if str(path).endswith("journal.json"):
            return real_aw(path, text, mode)
        state["n"] += 1
        if state["n"] == after_calls:
            if wrong_bytes:
                return real_aw(path, b"not what the snapshot holds", mode)
            raise exc
        return real_aw(path, text, mode)
    rc.cc.atomic_write = aw
    return lambda: setattr(rc.cc, "atomic_write", real_aw)

# a full disk on the second of three writes: stops, names the file, keeps the first, rollback undoes it
home, env, man = fresh()
damage(home)
damaged = files_of(home)
plan = rc.plan_restore(man.id, env=env, home=home)
undo = inject(2, OSError(errno.ENOSPC, "No space left on device"))
try:
    res = rc.apply_restore(plan, env=env, home=home)
finally:
    undo()
assert res.failed and not res.complete and len(res.applied) == 1, res
j = json.loads((home / ".local/share/primo/recovery" / res.journal / "journal.json").read_text())
states = [e["state"] for e in j["entries"]]
assert j["status"] == "partial" and states == ["done", "failed", "pending"], states
assert "No space" in j["entries"][1]["reason"] and "reduce_motion" not in j["entries"][1]["reason"], "the reason is an error, never file content"
back = rc.rollback_restore(res.journal, env=env, home=home)
assert back.rolled_back and files_of(home) == damaged
# a write that lands with the wrong bytes is a failure, and rollback restores the old file
home, env, man = fresh()
damage(home)
damaged = files_of(home)
undo = inject(1, None, wrong_bytes=True)
try:
    res = rc.apply_restore(rc.plan_restore(man.id, env=env, home=home), env=env, home=home)
finally:
    undo()
assert res.failed and rc.rollback_restore(res.journal, env=env, home=home).rolled_back and files_of(home) == damaged
# the backup copy failing stops before anything is replaced
home, env, man = fresh()
damage(home)
damaged = files_of(home)
real_copy = rc.shutil.copyfile
rc.shutil.copyfile = lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EIO, "I/O error"))
try:
    res = rc.apply_restore(rc.plan_restore(man.id, env=env, home=home), env=env, home=home)
finally:
    rc.shutil.copyfile = real_copy
assert res.failed == "ui" and res.applied == ("modes",), res
assert files_of(home) == damaged | {str(home / ".config/primo/modes.json"): b'[{"id": "a"}]'}, "only the file that needs no backup was written"
assert (home / ".config/primo/ui.json").read_text() == '{"version": 1, "reduce_motion": true}', "no file is replaced without its backup"
# a process killed in the middle of a write (not an Exception): the journal says "writing", rollback still returns to the old state
for landed in (False, True):
    home, env, man = fresh()
    damage(home)
    damaged = files_of(home)
    real_aw = rc.cc.atomic_write
    def dying(path, text, mode=None, landed=landed, real_aw=real_aw):
        if str(path).endswith("journal.json"):
            return real_aw(path, text, mode)
        if landed:
            real_aw(path, text, mode)                       # the replace happened, the process died before saying so
        raise KeyboardInterrupt
    rc.cc.atomic_write = dying
    try:
        rc.apply_restore(rc.plan_restore(man.id, env=env, home=home), env=env, home=home)
        raise AssertionError
    except KeyboardInterrupt:
        pass
    finally:
        rc.cc.atomic_write = real_aw
    jid = sorted(p.name for p in (home / ".local/share/primo/recovery").iterdir())[0]
    assert json.loads((home / ".local/share/primo/recovery" / jid / "journal.json").read_text())["entries"][0]["state"] == "writing"
    back = rc.rollback_restore(jid, env=env, home=home)
    assert back.rolled_back and files_of(home) == damaged, landed

# work done after the restore is never overwritten by a rollback
home, env, man = fresh()
damage(home)
res = rc.apply_restore(rc.plan_restore(man.id, env=env, home=home), env=env, home=home)
(home / ".config/primo/ui.json").write_text("my newer edit")
back = rc.rollback_restore(res.journal, env=env, home=home)
assert (home / ".config/primo/ui.json").read_text() == "my newer edit" and ("ui", "edited since the restore; left as it is") in back.skipped
assert not back.rolled_back and sorted(back.applied) == ["hub", "modes"] and not (home / ".config/primo/modes.json").exists()
assert json.loads((home / ".local/share/primo/recovery" / res.journal / "journal.json").read_text())["status"] == "partial-rollback"
for bad in ("../x", "nope", "", "20260101-000000"):
    try:
        rc.rollback_restore(bad, env=env, home=home)
        raise AssertionError(bad)
    except rc.RecoveryError:
        pass

# sensitive and machine files restore only when they were taken and asked for; the mode of a private file survives
home, env, man = fresh()
put(home, ".config/primo/workflow.json", '{"feeds": []}', 0o600)
man = rc.create_snapshot(rc.plan_snapshot(include_sensitive=True, env=env, home=home), env=env, home=home)
(home / ".config/primo/workflow.json").unlink()
(home / ".local/state/hyprland-dotfiles/wallpaper").write_text("/other.png\n")
res = rc.apply_restore(rc.plan_restore(man.id, env=env, home=home), env=env, home=home)
assert (home / ".config/primo/workflow.json").read_text() == '{"feeds": []}' and stat.S_IMODE((home / ".config/primo/workflow.json").stat().st_mode) == 0o600
assert (home / ".local/state/hyprland-dotfiles/wallpaper").read_text() == "/other.png\n" and "wallpaper" not in res.applied, "machine files wait for --include-machine"
res = rc.apply_restore(rc.plan_restore(man.id, include_machine=True, env=env, home=home), env=env, home=home)
assert (home / ".local/state/hyprland-dotfiles/wallpaper").read_text() == "/home/u/a.png\n" and "wallpaper" in res.applied

# the CLI: preview, apply, journal, rollback, exit codes
home, env, man = fresh()
cenv = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", NO_COLOR="1")
damage(home)
damaged = files_of(home)
code, out, _e = run_cli("restore", man.id)
assert code == 0 and "add --apply" in out and files_of(home) == damaged
code, out, _e = run_cli("restore", man.id, "--apply", "--json")
doc = json.loads(out)
assert code == 0 and doc["applied"] and doc["result"]["complete"] and sorted(doc["result"]["written"]) == ["hub", "modes", "ui"], out
assert files_of(home) != damaged
code, out, _e = run_cli("restore", "--rollback", doc["result"]["journal"])
assert code == 0 and "put back" in out and files_of(home) == damaged
assert run_cli("restore", "--rollback", "20990101-000000")[0] == 2 and run_cli("restore")[0] == 64
code, out, _e = run_cli("restore", man.id, "--apply")
assert code == 0 and "undo with: primo restore --rollback" in out and "time hub keeps its data in memory" in out

print("ok: recovery")
