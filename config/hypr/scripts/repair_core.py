"""Doctor repairs: a short, reviewed list of findings that Primo may fix by itself, and the plan for each. Standard library only.

Only two findings are on the list, because only these have a deterministic effect on files Primo owns and can be undone:
  config.json      a settings file does not parse   -> put back that file from the newest sound snapshot that holds a version that parses
  theme.generated  generated theme files are missing or unfinished -> run `scripts/theme-switch --generate-only <current theme>` (renders the files in the
                   repository and nothing else: no ~/.config, no gsettings, no login screen, no reload)
Everything else a diagnostic says stays text for a person to read; no hint string is ever run. `plan_repair` is read-only: it resolves exact
targets, checks what must be true first, and says what would be written, what is backed up and how to undo it. `apply_repair` does it, after checking the plan is still true, keeping what it replaces, and reading the result back.
"""
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import config_core as cc
import doctor_core as dc
import recovery_core as rc

REPAIRABLE = {
    "config.json": "Put a broken settings file back from a snapshot",
    "theme.generated": "Generate the theme files again",
}


@dataclass(frozen=True)
class RepairStep:
    kind: str            # "restore-file" or "regenerate-theme"
    target: str          # the file, or for regenerate-theme the theme folder
    detail: str          # one line a person can read: where it comes from / what runs
    name: str = ""       # restore-file: the inventory name of the file
    snapshot: str = ""   # restore-file: the snapshot it comes from


@dataclass(frozen=True)
class RepairPlan:
    finding_id: str
    title: str
    steps: tuple
    blocked: "str | None"            # a stable reason id (below) when the repair cannot be done now
    blocked_detail: str = ""
    effects: tuple = ()              # what will be written
    backup: str = ""                 # what is kept so it can be undone
    recovery: str = ""               # how to undo


# What `scripts/theme-switch --generate-only` writes (test-repair.py runs it on a copy and compares): the git-ignored files of the repository.
THEME_OUTPUTS = ("config/dunst/dunstrc.d/10-theme.conf", "config/hypr/confirm.css", "config/hypr/hyprlock-theme.conf", "config/hypr/hyprpaper.conf",
                 "config/hypr/logo.png", "config/hypr/logo.svg", "config/hypr/theme.env", "config/hypr/theme.lua", "config/kitty/theme.conf",
                 "config/swaync/style.css", "config/swayosd/style.css", "config/waybar/style.css", "config/waybar/theme.css", "config/wofi/menu.css",
                 "config/wofi/style.css")

BLOCKS = ("not-allowlisted", "nothing-to-repair", "no-snapshot", "snapshot-file-invalid", "newer-primo", "theme-missing", "repo-not-found", "theme-script-missing",
          "target-changed")


def _blocked(finding_id, reason, detail, title=""):
    return RepairPlan(finding_id, title or REPAIRABLE.get(finding_id, "Not something Primo repairs"), (), reason, detail)


def _parses(entry_kind, data):
    try:
        if entry_kind == "toml":
            tomllib.loads(data.decode())
        else:
            json.loads(data)
        return True
    except (ValueError, UnicodeDecodeError):
        return False


def _broken_files(s):
    """[(name, path, kind, newer)] for settings files that do not parse right now (same test as the Doctor)."""
    out = []
    for name, path, kind in cc.known_files(s.env, s.home):
        try:
            cc.load(path, kind)
        except cc.ConfigError as e:
            out.append((name, Path(path), kind, e.newer))
    return out


def _plan_config(s):
    title = REPAIRABLE["config.json"]
    broken = _broken_files(s)
    if not broken:
        return _blocked("config.json", "nothing-to-repair", "every settings file parses", title)
    newer = [p.name for _n, p, _k, nw in broken if nw]
    if newer:
        return _blocked("config.json", "newer-primo", f"{', '.join(newer)} was written by a newer Primo; that needs an update, not a restore", title)
    snaps = [x for x in rc.list_snapshots(s.env, s.home) if x.complete]
    if not snaps:
        return _blocked("config.json", "no-snapshot", "there is no complete snapshot to restore from (take one with `primo snapshot` while things work)", title)
    steps, missing = [], []
    for name, path, kind, _nw in broken:
        entry_name = next((e.name for e in rc.inventory(s.env, s.home) if rc.target_path(e, s.env, s.home) == path), None)
        found = None
        for snap in snaps:                                              # newest first
            manifest, problems = rc.load_snapshot(snap.id, s.env, s.home)
            if problems:
                continue
            f = next((f for f in manifest.files if f.name == entry_name), None)
            if f is None:
                continue
            data = (rc.snapshots_dir(s.env, s.home) / snap.id / "files" / str(f.index)).read_bytes()
            if _parses("toml" if path.suffix == ".toml" else "json", data):
                found = (snap.id, f)
                break
        if found is None:
            missing.append(path.name)
        else:
            steps.append(RepairStep("restore-file", str(path), f"from snapshot {found[0]} ({found[1].size} bytes)", entry_name, found[0]))
    if missing:
        return _blocked("config.json", "snapshot-file-invalid", f"no sound snapshot holds a good copy of: {', '.join(missing)}", title)
    return RepairPlan("config.json", title, tuple(steps), None, "", tuple(x.target for x in steps),
                      "the broken file is kept next to it as <name>.bad-<time>, and the restore is journaled with a private copy",
                      "primo restore --rollback <journal id> (printed when it is applied)")


def _plan_theme(s):
    title = REPAIRABLE["theme.generated"]
    repo = dc.find_repo(s)
    if repo is None:
        return _blocked("theme.generated", "repo-not-found", "could not find the Primo checkout (is ~/.config/hypr linked to it?)", title)
    problems = []
    for g in dc.GENERATED:
        p = repo / g
        if not p.exists():
            problems.append(g)
        else:
            try:
                if "{{" in p.read_text(errors="replace"):
                    problems.append(g)
            except OSError:
                pass
    if not problems:
        return _blocked("theme.generated", "nothing-to-repair", "every generated theme file is present and finished", title)
    state = s.home / ".local/state/hyprland-dotfiles/current"
    current = ""
    try:
        current = state.read_text().strip()
    except OSError:
        pass
    if not current or "/" in current or current.startswith(".") or not (repo / "themes" / current / "theme.conf").is_file():
        return _blocked("theme.generated", "theme-missing", f"the current theme ({current or 'none applied'}) has no folder in themes/", title)
    script = repo / "scripts" / "theme-switch"
    if not script.is_file() or not os.access(script, os.X_OK):
        return _blocked("theme.generated", "theme-script-missing", "scripts/theme-switch is not there or not executable", title)
    return RepairPlan("theme.generated", title,
                      (RepairStep("regenerate-theme", str(repo / "themes" / current), f"{script} --generate-only {current}", current),),
                      None, "", tuple(str(repo / g) for g in THEME_OUTPUTS),
                      "only the generated, git-ignored theme files in the repository are rewritten (a copy of each is kept first); nothing in ~/.config, no setting and nothing running is touched, so the desktop does not change until you apply the theme",
                      "run `hypr-theme <theme>` again; the generated files are rebuilt from themes/ each time")


def plan_repair(finding_id, s=None, env=None, home=None):
    """The reviewed plan for one finding id, or a blocked plan that says why not. Never writes, never runs a command."""
    s = s or dc.System(env=env, home=home)
    if finding_id == "config.json":
        return _plan_config(s)
    if finding_id == "theme.generated":
        return _plan_theme(s)
    return _blocked(finding_id, "not-allowlisted", "Primo does not repair this by itself; the Doctor's hint is text for you to read", "Not something Primo repairs")


# ---------------------------------------------------------------------------------------------------- apply (T068)
import shutil  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402


@dataclass(frozen=True)
class RepairResult:
    finding_id: str
    ok: bool                 # the intended condition was read back and holds (or already held)
    changed: bool            # something was written
    reason: str              # "" when done; "nothing-to-repair" when it already held; otherwise a stable id or "verification-failed"/"failed"
    detail: str = ""
    journals: tuple = ()     # restore journals (`primo restore --rollback ID` undoes them) or the copy folder of a theme repair
    steps_done: tuple = ()


def _theme_command(step):
    repo = Path(step.detail.split(" --generate-only ")[0]).parent.parent
    return str(repo / "scripts" / "theme-switch"), step.name, repo


def apply_repair(plan, s=None, env=None, home=None, now=None):
    """Do what `plan` says, but only if it is still exactly what a fresh plan says; keep what is replaced; read the result back.
    A stale or blocked plan changes nothing. Applying twice is harmless: the second time there is nothing to repair."""
    s = s or dc.System(env=env, home=home)
    if plan.finding_id not in REPAIRABLE:
        return RepairResult(plan.finding_id, False, False, "not-allowlisted", "Primo does not repair this by itself")
    if plan.blocked == "nothing-to-repair":
        return RepairResult(plan.finding_id, True, False, "nothing-to-repair", plan.blocked_detail)
    if plan.blocked:
        return RepairResult(plan.finding_id, False, False, plan.blocked, plan.blocked_detail)
    fresh = plan_repair(plan.finding_id, s)
    if fresh.blocked == "nothing-to-repair":
        return RepairResult(plan.finding_id, True, False, "nothing-to-repair", fresh.blocked_detail)
    if fresh.blocked or fresh.steps != plan.steps:
        return RepairResult(plan.finding_id, False, False, "target-changed", fresh.blocked_detail or "the files are not what the plan was made for; look at the plan again")
    return _apply_config(plan, s, now) if plan.finding_id == "config.json" else _apply_theme(plan, s, now)


def _apply_config(plan, s, now):
    by_snapshot = {}
    for st in plan.steps:
        by_snapshot.setdefault(st.snapshot, []).append(st)
    journals, done = [], []
    for snap, steps in by_snapshot.items():
        for st in steps:                                               # the broken bytes stay next to the file, as the settings code does before a save
            try:
                raw = Path(st.target).read_bytes()
                if raw:
                    cc.preserve(Path(st.target), raw)
            except OSError as e:
                return RepairResult(plan.finding_id, False, bool(done), "failed", f"could not keep a copy of {Path(st.target).name} ({e.strerror})", tuple(journals), tuple(done))
        try:
            res = rc.apply_restore(rc.plan_restore(snap, only=[st.name for st in steps], env=s.env, home=s.home), s.env, s.home, now)
        except rc.RecoveryError as e:
            return RepairResult(plan.finding_id, False, bool(done), "failed", str(e), tuple(journals), tuple(done))
        journals.append(res.journal)
        if res.failed or set(res.applied) != {st.name for st in steps}:
            why = f"the restore stopped at {res.failed}" if res.failed else "not every file could be restored: " + ", ".join(f"{n}: {r}" for n, r in res.skipped)
            return RepairResult(plan.finding_id, False, bool(res.applied) or bool(done), "failed", why + f"; undo with primo restore --rollback {res.journal}", tuple(journals), tuple(done) + tuple(res.applied))
        done += [st.name for st in steps]
    bad = [p.name for _n, p, _k, _nw in _broken_files(s)]
    if bad:                                                            # exit 0 is not enough: the files must now parse
        for jid in reversed(journals):
            rc.rollback_restore(jid, s.env, s.home)
        return RepairResult(plan.finding_id, False, False, "verification-failed", f"after the restore these still do not parse: {', '.join(bad)}; it was rolled back", tuple(journals), ())
    return RepairResult(plan.finding_id, True, True, "", f"restored {', '.join(done)}", tuple(journals), tuple(done))


def _apply_theme(plan, s, now):
    step = plan.steps[0]
    script, theme, repo = _theme_command(step)
    folder = rc.recovery_dir(s.env, s.home)
    rc._mkdir_private(folder)
    jid = rc._new_id(folder, now or time.localtime())
    jdir = folder / jid
    jdir.mkdir(mode=0o700)
    (jdir / "pre").mkdir(mode=0o700)
    kept = {}
    for n, rel in enumerate(THEME_OUTPUTS):                            # a copy of every generated file that exists now
        src = repo / rel
        if src.is_file():
            shutil.copyfile(src, jdir / "pre" / str(n))
            os.chmod(jdir / "pre" / str(n), 0o600)
            kept[rel] = n
    (jdir / "journal.json").write_text(json.dumps({"version": rc.VERSION, "id": jid, "kind": "repair-theme", "theme": theme, "kept": kept}, indent=1))
    os.chmod(jdir / "journal.json", 0o600)

    def put_back():
        for rel in THEME_OUTPUTS:
            target = repo / rel
            try:
                if rel in kept:
                    shutil.copyfile(jdir / "pre" / str(kept[rel]), target)
                elif target.exists():
                    target.unlink()
            except OSError:
                pass

    try:
        r = subprocess.run([script, "--generate-only", theme], cwd=repo, capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, PRIMO_NO_RELOAD="1"))
    except (OSError, subprocess.SubprocessError) as e:
        put_back()
        return RepairResult(plan.finding_id, False, False, "failed", f"theme-switch did not run ({type(e).__name__}); the files were put back", (jid,))
    if r.returncode != 0:
        put_back()
        return RepairResult(plan.finding_id, False, False, "failed", f"theme-switch failed (exit {r.returncode}): {(r.stderr.strip().splitlines() or [''])[-1][:160]}; the files were put back", (jid,))
    after = plan_repair("theme.generated", s)
    if after.blocked != "nothing-to-repair":                           # read it back: the files must now be there and finished
        put_back()
        return RepairResult(plan.finding_id, False, False, "verification-failed", "the generated files are still missing or unfinished; the files were put back", (jid,))
    return RepairResult(plan.finding_id, True, True, "", f"generated the files for {theme}; nothing outside the repository was touched", (jid,), (theme,))
