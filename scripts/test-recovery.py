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

print("ok: recovery")
