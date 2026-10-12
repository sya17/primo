"""Is this Primo ready to be updated by hand, and (only when asked) is there a newer release? Standard library only.

`preflight` is read-only: it looks at the git checkout, the settings files, the tools Primo needs and the last snapshot, and says
ready / ready-with-warnings / blocked with the reasons. It never runs fetch, pull, reset, stash or checkout, never installs anything and never
writes a file (git runs with optional locks off, so even `git status` does not refresh the index). Primo does not apply updates: the user runs
`git pull` after reading this. `check_release` (the only network access) is added below, behind an explicit command.
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import config_core as cc
import recovery_core as rc

OK, WARN, BLOCK = "ok", "warn", "block"
MAX_PATHS = 8             # changed files named in a report; the rest is a count
SNAPSHOT_FRESH_DAYS = 7
GIT_TIMEOUT = 5
OUT_CAP = 64 * 1024


@dataclass(frozen=True)
class UpdateCheck:
    id: str
    level: str            # "ok", "warn" or "block"
    title: str
    detail: str = ""
    hint: str = ""


@dataclass(frozen=True)
class UpdateReport:
    verdict: str          # "ready", "ready-with-warnings" or "blocked"
    revision: str
    branch: str
    ahead: "int | None"
    behind: "int | None"
    checks: tuple

    def exit_code(self):
        return {"ready": 0, "ready-with-warnings": 1, "blocked": 2}[self.verdict]


def default_repo():
    """The checkout this file lives in; PRIMO_REPO points checks at another one."""
    repo = Path(os.environ.get("PRIMO_REPO") or Path(__file__).resolve().parents[3])
    return repo if (repo / ".git").exists() else None


def strip_credentials(url):
    """A remote URL without the user:password part (and without a token in a query string), for showing."""
    url = re.sub(r"^([a-z][a-z0-9+.-]*://)[^/@\s]*@", r"\1", url.strip(), flags=re.I)
    return re.sub(r"[?#].*$", "", url)[:200]


def _git(repo, *args, strip=True):
    """(exit code, stdout) of one read-only git call; bounded in time and size; never prompts."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=GIT_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    text = r.stdout[:OUT_CAP].decode(errors="replace")
    return r.returncode, text.strip() if strip else text.rstrip("\n")


def _status(repo):
    """(tracked changes, untracked, conflicts, sample of paths) from porcelain v1; the paths are names only."""
    code, out = _git(repo, "status", "--porcelain=v1", "--untracked-files=normal", strip=False)
    if code != 0:
        return None
    changed = untracked = conflicts = 0
    names = []
    for line in out.splitlines():
        xy, name = line[:2], line[3:]
        if xy == "??":
            untracked += 1
        elif "U" in xy or xy in ("AA", "DD"):
            conflicts += 1
        else:
            changed += 1
        if len(names) < MAX_PATHS:
            names.append(name[:120])
    return changed, untracked, conflicts, names


def _age_days(path):
    try:
        return (time.time() - path.stat().st_mtime) / 86400
    except OSError:
        return None


def preflight(repo=None, env=None, home=None, now=None):
    """Everything worth knowing before a manual update, read-only. `repo` is the checkout (default: the one this file lives in)."""
    repo = Path(repo) if repo else default_repo()
    checks, ahead, behind, revision, branch = [], None, None, "", ""

    # tools Primo needs: missing ones are blockers, optional ones never
    missing = [n for n, ok in (("git", bool(shutil.which("git"))), ("python3", bool(shutil.which("python3"))),
                               ("gi (python-gobject)", importlib.util.find_spec("gi") is not None)) if not ok]
    if sys.version_info < (3, 11):
        missing.append("python 3.11 or newer")
    checks.append(UpdateCheck("tools", BLOCK if missing else OK, "Required tools", "missing: " + ", ".join(missing) if missing else "git, python3 and PyGObject are installed",
                              "sudo pacman -S git python python-gobject" if missing else ""))

    # the checkout
    if repo is None or not shutil.which("git"):
        checks.append(UpdateCheck("checkout", BLOCK, "Git checkout", "Primo was not installed from a git checkout here, so there is nothing to update with git",
                                  "install from https://github.com/sya17/primo (docs/INSTALL.md)"))
    else:
        code, top = _git(repo, "rev-parse", "--show-toplevel")
        code_b, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        _c, revision = _git(repo, "rev-parse", "--short", "HEAD")
        busy = [n for n in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "BISECT_LOG") if (repo / ".git" / n).exists()] + \
               [n for n in ("rebase-merge", "rebase-apply") if (repo / ".git" / n).exists()]
        if code != 0 or code_b != 0:
            checks.append(UpdateCheck("checkout", BLOCK, "Git checkout", "git cannot read this checkout", "look at `git status` yourself"))
        elif branch == "HEAD":
            checks.append(UpdateCheck("checkout", BLOCK, "Git checkout", "HEAD is detached (not on a branch)", "git switch main, then check again"))
        elif busy:
            checks.append(UpdateCheck("checkout", BLOCK, "Git checkout", "a " + busy[0].lower().replace("_head", "").replace("-", " ") + " is in progress", "finish or abort it first"))
        else:
            checks.append(UpdateCheck("checkout", OK, "Git checkout", f"on {branch} at {revision}"))
            st = _status(repo)
            if st is None:
                checks.append(UpdateCheck("worktree", WARN, "Local changes", "git status could not be read"))
            else:
                changed, untracked, conflicts, names = st
                if conflicts:
                    checks.append(UpdateCheck("worktree", BLOCK, "Local changes", f"{conflicts} file(s) with merge conflicts", "resolve them first"))
                elif changed or untracked:
                    parts = ([f"{changed} changed"] if changed else []) + ([f"{untracked} untracked"] if untracked else [])
                    checks.append(UpdateCheck("worktree", WARN, "Local changes", ", ".join(parts) + ": " + ", ".join(names) + (" ..." if changed + untracked > len(names) else ""),
                                              "commit or move them before `git pull`; a pull may refuse or conflict"))
                else:
                    checks.append(UpdateCheck("worktree", OK, "Local changes", "none"))
            code_u, upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
            if code_u != 0:
                checks.append(UpdateCheck("upstream", WARN, "Upstream", f"{branch} does not track a remote branch", "git branch --set-upstream-to origin/main"))
            else:
                _c, counts = _git(repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
                try:
                    ahead, behind = (int(x) for x in counts.split())
                except ValueError:
                    ahead = behind = None
                fetched = _age_days(repo / ".git" / "FETCH_HEAD")
                seen = "never fetched" if fetched is None else f"last fetched {fetched:.0f} day(s) ago" if fetched >= 1 else "fetched today"
                if ahead is None:
                    checks.append(UpdateCheck("upstream", WARN, "Upstream", f"{upstream}: could not compare"))
                elif ahead and behind:
                    checks.append(UpdateCheck("upstream", WARN, "Upstream", f"{ahead} local and {behind} remote commit(s): the branches have diverged ({seen})",
                                              "`git pull --rebase` or merge by hand; Primo will not do it"))
                else:
                    checks.append(UpdateCheck("upstream", OK, "Upstream", f"{upstream}: {behind} commit(s) behind, {ahead} ahead, as of the last fetch ({seen})"))
            code_r, remote = _git(repo, "remote", "get-url", "origin")
            if code_r == 0 and remote:
                checks.append(UpdateCheck("remote", OK, "Remote", strip_credentials(remote)))

    # settings files: a file from a newer Primo is an incompatibility, a broken one a warning; a missing one is fine
    bad, newer = [], []
    for name, path, kind in cc.known_files(env, home):
        first = None
        for expect in (kind if isinstance(kind, tuple) else (kind,)):          # a file may be a table or a list
            try:
                cc.load(path, expect)
                first = None
                break
            except cc.ConfigError as e:
                first = first or e
        if first is not None:
            (newer if first.newer else bad).append(f"{Path(path).name}" + (f":{first.line}" if first.line else ""))
    if newer:
        checks.append(UpdateCheck("config-version", BLOCK, "Settings from a newer Primo", ", ".join(newer) + " were written by a newer version; this one would read them as defaults",
                                  "update Primo before using it again, and do not save settings with this version"))
    if bad:
        checks.append(UpdateCheck("config", WARN, "Settings files", "do not parse: " + ", ".join(bad), "primo config validate"))
    if not newer and not bad:
        checks.append(UpdateCheck("config", OK, "Settings files", "all parse"))

    # a snapshot of the settings (not of the repository or packages)
    snaps = [s for s in rc.list_snapshots(env, home) if s.complete]
    if not snaps:
        checks.append(UpdateCheck("snapshot", WARN, "Settings snapshot", "no complete snapshot of your Primo settings", "primo snapshot"))
    else:
        try:
            age = ((now or time.time()) - time.mktime(time.strptime(snaps[0].created, "%Y-%m-%dT%H:%M:%S"))) / 86400
        except ValueError:
            age = None
        if age is None or age > SNAPSHOT_FRESH_DAYS:
            checks.append(UpdateCheck("snapshot", WARN, "Settings snapshot", f"the last one ({snaps[0].id}) is {'of unknown age' if age is None else f'{age:.0f} days old'}", "primo snapshot"))
        else:
            checks.append(UpdateCheck("snapshot", OK, "Settings snapshot", f"{snaps[0].id}, {age:.0f} day(s) old; it covers your Primo settings, not the repository or packages"))

    verdict = "blocked" if any(c.level == BLOCK for c in checks) else "ready-with-warnings" if any(c.level == WARN for c in checks) else "ready"
    return UpdateReport(verdict, revision, branch, ahead, behind, tuple(checks))


# ---------------------------------------------------------------------------------------------------- release lookup (T066)
# The only network access in Primo's update code, and only when the user asks (`primo update check --remote`): one GET, no redirects, a short
# timeout and a size cap, nothing sent but a User-Agent, nothing run or applied from what comes back.
RELEASES_URL = "https://api.github.com/repos/sya17/primo/releases/latest"
RELEASE_PAGE = "https://github.com/sya17/primo/releases/"
REMOTE_TIMEOUT = 5
REMOTE_CAP = 64 * 1024
NOTES_CAP = 2000
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T[0-9:.]+Z?)?$")


@dataclass(frozen=True)
class RemoteResult:
    status: str               # newer, current, ahead, unknown, offline, rate-limited, redirected, too-large, malformed
    current: str
    latest: str = ""
    published: str = ""
    name: str = ""
    notes: str = ""           # untrusted text from the release, shortened and made printable; never executed
    url: str = ""
    breaking: bool = False    # the notes mention a breaking change
    detail: str = ""
    last_known: str = ""      # from the cache, only when this lookup gave no answer; never a proof of "up to date"


def releases_url(override=""):
    """The release page to ask: GitHub's, unless a test points PRIMO_RELEASES_URL at this machine (any other override is ignored)."""
    return override if re.match(r"^http://(127\.0\.0\.1|localhost)[:/]", override or "") else RELEASES_URL


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _fetch(url, timeout):
    """(status code, headers, body bytes) for one GET, or raises URLError/OSError. Never follows a redirect (a 3xx comes back as its code)."""
    req = urllib.request.Request(url, headers={"User-Agent": "primo-update-check", "Accept": "application/vnd.github+json"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(REMOTE_CAP + 1)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read(REMOTE_CAP + 1)


def printable(text, limit):
    """Remote text made safe to print: control characters (escape sequences included) become '?', length capped."""
    clean = "".join(ch if ch == "\n" or ch >= " " and ch != "\x7f" else "?" for ch in text.replace("\r", ""))
    return clean if len(clean) <= limit else clean[:limit].rstrip() + " [shortened]"


def parse_version(text):
    m = _VERSION.match((text or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def current_version(repo=None):
    """The installed version, from the changelog heading (the same source as `primo --version`)."""
    repo = Path(repo) if repo else default_repo()
    try:
        m = re.search(r"^##\s+\[?(\d+\.\d+\.\d+)", (repo / "CHANGELOG.md").read_text(), re.M)
        return m.group(1) if m else ""
    except (OSError, TypeError):
        return ""


def _cache_path(env=None, home=None):
    return cc.state_home(env, home) / "hyprland-dotfiles" / "update-check.json"


def check_release(current, url=RELEASES_URL, fetch=_fetch, env=None, home=None, now=None):
    """Ask for the latest release once and say what it is, honestly: a lookup that fails is `offline`, `rate-limited`, `redirected`, `too-large`
    or `malformed`, never "up to date". After a failure the last answer is shown as `last_known` with its age, as a hint only."""
    now = now or time.time()
    cache = _cache_path(env, home)

    def failed(status, detail):
        known = ""
        try:
            old = json.loads(cache.read_text())
            if isinstance(old.get("latest"), str) and parse_version(old["latest"]) and isinstance(old.get("checked_at"), (int, float)):
                known = f"{old['latest']} (looked up {max(0, (now - old['checked_at']) / 86400):.0f} day(s) ago)"
        except (OSError, ValueError, AttributeError):
            pass
        return RemoteResult(status, current, detail=detail, last_known=known)

    try:
        code, headers, body = fetch(url, REMOTE_TIMEOUT)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return failed("offline", f"could not reach the release page ({type(e).__name__})")
    low = {str(k).lower(): str(v) for k, v in headers.items()}
    if 300 <= code < 400:
        return failed("redirected", "the release page answered with a redirect; it was not followed")
    if code == 429 or (code == 403 and low.get("x-ratelimit-remaining") == "0"):
        return failed("rate-limited", "GitHub is limiting requests from this address; try again later")
    if len(body) > REMOTE_CAP:
        return failed("too-large", "the answer was larger than expected and was dropped")
    if code != 200:
        return failed("unknown", f"the release page answered HTTP {code}")
    try:
        doc = json.loads(body.decode("utf-8"))
        tag, published = doc["tag_name"], doc.get("published_at") or ""
        latest = parse_version(tag)
        if not isinstance(doc, dict) or latest is None or not isinstance(published, str) or (published and not _DATE.match(published)):
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return failed("malformed", "the answer is not a release description")
    name = printable(str(doc.get("name") or "")[:200], 120)
    notes = printable(str(doc.get("body") or ""), NOTES_CAP)
    page = doc.get("html_url") if isinstance(doc.get("html_url"), str) and doc["html_url"].startswith(RELEASE_PAGE) else ""
    mine = parse_version(current)
    status = "unknown" if mine is None else "newer" if latest > mine else "current" if latest == mine else "ahead"
    tag_text = "{}.{}.{}".format(*latest)
    try:
        cc.atomic_write(cache, json.dumps({"latest": tag_text, "checked_at": now, "published": published}), 0o600)
    except OSError:
        pass
    return RemoteResult(status, current, tag_text, published, name, notes, page, bool(re.search(r"BREAKING[ -]CHANGE", notes, re.I)),
                        "" if mine is not None else "the installed version could not be read")
