#!/usr/bin/env python3
"""Checks for update_core: the read-only update preflight (disposable git repositories, a temp HOME) and the release lookup.

Nothing real is read: no network, no real checkout, no real settings."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "config" / "hypr" / "scripts"))
import recovery_core as rc  # noqa: E402
import update_core as uc  # noqa: E402

AT = chr(64)   # written this way so that no sample address looks like a real email to the privacy hook
GITENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t" + AT + "example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t" + AT + "example.invalid",
              GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], env=GITENV, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def fixture():
    """(clone, remote, other): a remote, a clone tracking it and a second clone to push from. All temporary."""
    root = Path(tempfile.mkdtemp(prefix="primo-update-"))
    remote = root / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], env=GITENV, check=True)
    clone = root / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], env=GITENV, check=True, capture_output=True)
    (clone / "a.txt").write_text("one\n")
    git(clone, "add", "a.txt")
    git(clone, "commit", "-q", "-m", "first")
    git(clone, "push", "-q", "-u", "origin", "main")
    other = root / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], env=GITENV, check=True, capture_output=True)
    return clone, remote, other


def home_with_snapshot(fresh=True):
    home = Path(tempfile.mkdtemp(prefix="primo-update-home-"))
    for d in (".config/primo", ".local/share/primo", ".local/state/hyprland-dotfiles"):
        (home / d).mkdir(parents=True)
    (home / ".local/share/primo/hub.json").write_text("{}")
    env = {"HOME": str(home)}
    if fresh is not None:
        m = rc.create_snapshot(rc.plan_snapshot(env=env, home=home), env=env, home=home)
        if not fresh:
            mp = home / ".local/share/primo/snapshots" / m.id / "manifest.json"
            d = json.loads(mp.read_text())
            d["created"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 30 * 86400))
            mp.write_text(json.dumps(d))
    return home, env


def level(report, cid):
    return next(c.level for c in report.checks if c.id == cid)


def detail(report, cid):
    return next(c.detail for c in report.checks if c.id == cid)


def everything(repo):
    """Every file in the checkout, .git included, with content hash and mtime: a preflight must leave all of it exactly as it was."""
    out = {}
    for p in sorted(Path(repo).rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[str(p)] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    return out


# ---- a clean checkout that tracks its remote is ready
clone, remote, other = fixture()
home, env = home_with_snapshot()
before = everything(clone)
r = uc.preflight(clone, env, home)
assert r.verdict == "ready" and r.exit_code() == 0, [(c.id, c.level, c.detail) for c in r.checks]
assert r.branch == "main" and r.ahead == 0 and r.behind == 0 and len(r.revision) >= 7
assert everything(clone) == before, "a preflight changes nothing in the checkout: files, refs, index, mtimes"

# the git commands it ran: reads only, never fetch, pull, reset, stash, checkout, switch, merge, add, commit, gc
shim = Path(tempfile.mkdtemp(prefix="primo-update-shim-"))
log = shim / "git.log"
real_git = shutil.which("git")
(shim / "git").write_text(f'#!/usr/bin/env bash\necho "$@" >> "{log}"\nexec {real_git} "$@"\n')
(shim / "git").chmod(0o755)
old_path = os.environ["PATH"]
os.environ["PATH"] = f"{shim}:{old_path}"
try:
    uc.preflight(clone, env, home)
finally:
    os.environ["PATH"] = old_path
subs = {line.split()[2] for line in log.read_text().splitlines()}
assert subs and subs <= {"rev-parse", "status", "rev-list", "remote"}, subs

# ---- local changes: counted and named, content never shown
(clone / "a.txt").write_text("changed secret-text\n")
(clone / "new.txt").write_text("x")
r = uc.preflight(clone, env, home)
assert r.verdict == "ready-with-warnings" and level(r, "worktree") == "warn"
d = detail(r, "worktree")
assert "1 changed" in d and "1 untracked" in d and "a.txt" in d and "new.txt" in d and "secret-text" not in d, d
big = Path(clone)
for i in range(20):
    (big / f"u{i}.txt").write_text("x")
assert detail(uc.preflight(clone, env, home), "worktree").endswith("...") and detail(uc.preflight(clone, env, home), "worktree").count(".txt") <= uc.MAX_PATHS
git(clone, "checkout", "-q", "--", "a.txt")
for p in clone.glob("*.txt"):
    if p.name != "a.txt":
        p.unlink()

# ---- ahead, behind (after the fixture itself fetched), diverged, no upstream
(clone / "b.txt").write_text("b")
git(clone, "add", "b.txt")
git(clone, "commit", "-q", "-m", "local")
r = uc.preflight(clone, env, home)
assert (r.ahead, r.behind) == (1, 0) and level(r, "upstream") == "ok"
(other / "c.txt").write_text("c")
git(other, "add", "c.txt")
git(other, "commit", "-q", "-m", "remote")
git(other, "push", "-q", "origin", "main")
r = uc.preflight(clone, env, home)
assert r.behind == 0, "preflight does not fetch: a remote commit it has not seen does not exist for it"
refs_before = everything(clone)
git(clone, "fetch", "-q")                                                         # the test fetches, the preflight never does
r = uc.preflight(clone, env, home)
assert (r.ahead, r.behind) == (1, 1) and level(r, "upstream") == "warn" and "diverged" in detail(r, "upstream")
git(clone, "reset", "-q", "--hard", "origin/main")
r = uc.preflight(clone, env, home)
assert (r.ahead, r.behind) == (0, 0)
git(clone, "branch", "-q", "--unset-upstream")
assert level(uc.preflight(clone, env, home), "upstream") == "warn"

# ---- detached HEAD, merge in progress, conflicts, not a checkout
git(clone, "checkout", "-q", "--detach")
r = uc.preflight(clone, env, home)
assert r.verdict == "blocked" and r.exit_code() == 2 and level(r, "checkout") == "block" and "detached" in detail(r, "checkout")
git(clone, "checkout", "-q", "main")
(clone / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n")
assert level(uc.preflight(clone, env, home), "checkout") == "block"
(clone / ".git" / "MERGE_HEAD").unlink()
git(clone, "checkout", "-q", "-b", "side")
(clone / "a.txt").write_text("side\n")
git(clone, "commit", "-q", "-am", "side")
git(clone, "checkout", "-q", "main")
(clone / "a.txt").write_text("main\n")
git(clone, "commit", "-q", "-am", "main change")
git(clone, "merge", "side")                                                       # a real conflict
r = uc.preflight(clone, env, home)
assert r.verdict == "blocked" and level(r, "checkout") == "block", [(c.id, c.level, c.detail) for c in r.checks]
assert uc.preflight(Path(tempfile.mkdtemp(prefix="primo-update-")), env, home).verdict == "blocked"
os.environ["PRIMO_REPO"] = tempfile.mkdtemp(prefix="primo-update-")                  # the default checkout is not a git checkout (an installed copy)
r = uc.preflight(None, env, home)
del os.environ["PRIMO_REPO"]
assert r.verdict == "blocked" and "git checkout" in detail(r, "checkout")

# ---- tools: a missing required tool blocks, and says which
clone, remote, other = fixture()
real_which = shutil.which
shutil.which = lambda name, *a, **k: None if name == "git" else real_which(name, *a, **k)
try:
    r = uc.preflight(clone, env, home)
finally:
    shutil.which = real_which
assert level(r, "tools") == "block" and "git" in detail(r, "tools") and r.verdict == "blocked"

# ---- settings files: newer is an incompatibility, broken a warning, missing fine
r = uc.preflight(clone, env, home)
assert level(r, "config") == "ok" and r.verdict == "ready"
(home / ".config/primo/modes.json").write_text('[\n {"id": }\n]')
r = uc.preflight(clone, env, home)
assert level(r, "config") == "warn" and "modes.json:2" in detail(r, "config") and r.verdict == "ready-with-warnings"
assert '"id"' not in detail(r, "config"), "file content is never quoted"
(home / ".config/primo/ui.json").write_text('{"version": 99}')
r = uc.preflight(clone, env, home)
assert level(r, "config-version") == "block" and "ui.json" in detail(r, "config-version") and r.verdict == "blocked"
(home / ".config/primo/ui.json").unlink()
(home / ".config/primo/modes.json").write_text("[]")
(home / ".config/primo/mine.json").write_text("[1, 2]")                          # another settings file may be a list
assert level(uc.preflight(clone, env, home), "config") == "ok"

# ---- the snapshot: none, old, fresh, only incomplete ones
h2, e2 = home_with_snapshot(fresh=None)
assert level(uc.preflight(clone, e2, h2), "snapshot") == "warn" and "primo snapshot" in next(c.hint for c in uc.preflight(clone, e2, h2).checks if c.id == "snapshot")
h2, e2 = home_with_snapshot(fresh=False)
assert level(uc.preflight(clone, e2, h2), "snapshot") == "warn" and "30 days" in detail(uc.preflight(clone, e2, h2), "snapshot")
h2, e2 = home_with_snapshot(fresh=True)
d = detail(uc.preflight(clone, e2, h2), "snapshot")
assert level(uc.preflight(clone, e2, h2), "snapshot") == "ok" and "not the repository or packages" in d, "the snapshot is never promised to roll back the repository"
sid = rc.list_snapshots(e2, h2)[0].id
mp = h2 / ".local/share/primo/snapshots" / sid / "manifest.json"
dd = json.loads(mp.read_text()); dd["complete"] = False; mp.write_text(json.dumps(dd))
assert level(uc.preflight(clone, e2, h2), "snapshot") == "warn", "an incomplete snapshot does not count"

# ---- credentials in a remote never reach the report
for url, bad in (("https://user:ghp_SECRET123" + AT + "github.com/sya17/primo.git", "SECRET123"),
                 ("https://token" + AT + "example.com/x/y.git?access_token=SECRET456", "SECRET456"), ("git" + AT + "github.com:sya17/primo.git", "")):
    out = uc.strip_credentials(url)
    assert (not bad or bad not in out) and ("github.com" in out or "example.com" in out), out
git(clone, "remote", "set-url", "origin", "https://user:ghp_SECRET789" + AT + "example.com/x/y.git")
r = uc.preflight(clone, env, home)
assert "SECRET789" not in repr(r) and "example.com/x/y.git" in detail(r, "remote")

# ---- the CLI: verdict, exit codes, JSON, usage
PRIMO = str(Path(__file__).resolve().parent / "primo")
def cli(repo, *a):
    r = subprocess.run([sys.executable, PRIMO, "update", *a], env=dict(os.environ, PRIMO_REPO=str(repo), HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="",
                                                                          XDG_STATE_HOME="", NO_COLOR="1"), capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr
clone, remote, other = fixture()
home, env = home_with_snapshot()
code, out, _e = cli(clone, "check", "--json")
doc = json.loads(out)
assert code == 0 and doc["verdict"] == "ready" and doc["branch"] == "main" and {c["id"] for c in doc["checks"]} >= {"tools", "checkout", "worktree", "upstream", "config", "snapshot"}
code, out, _e = cli(clone, "check")
assert code == 0 and "READY" in out and "Primo does not update itself" in out and "read-only" in out
(clone / "x").write_text("1")
assert cli(clone, "check")[0] == 1
git(clone, "checkout", "-q", "--detach")
code, out, _e = cli(clone, "check")
assert code == 2 and "BLOCKED" in out and "try: git switch main" in out
assert cli(clone)[0] == 64 and cli(clone, "apply")[0] == 64

print("ok: update")
