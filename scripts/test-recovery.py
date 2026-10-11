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

print("ok: recovery")
