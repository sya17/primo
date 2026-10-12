"""Doctor repairs: a short, reviewed list of findings that Primo may fix by itself, and the plan for each. Standard library only.

Only two findings are on the list, because only these have a deterministic effect on files Primo owns and can be undone:
  config.json      a settings file does not parse   -> put back that file from the newest sound snapshot that holds a version that parses
  theme.generated  generated theme files are missing or unfinished -> run `scripts/theme-switch --no-reload <current theme>`
Everything else a diagnostic says stays text for a person to read; no hint string is ever run. `plan_repair` is read-only: it resolves exact
targets, checks what must be true first, and says what would be written, what is backed up and how to undo it. Applying is T068.
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
                      (RepairStep("regenerate-theme", str(repo / "themes" / current), f"{script} --no-reload {current}", current),),
                      None, "", tuple(str(repo / g) for g in dc.GENERATED),
                      "only the generated, git-ignored theme files are rewritten; nothing is reloaded, so the running desktop does not change until you apply the theme",
                      "run `hypr-theme <theme>` again; the generated files are rebuilt from themes/ each time")


def plan_repair(finding_id, s=None, env=None, home=None):
    """The reviewed plan for one finding id, or a blocked plan that says why not. Never writes, never runs a command."""
    s = s or dc.System(env=env, home=home)
    if finding_id == "config.json":
        return _plan_config(s)
    if finding_id == "theme.generated":
        return _plan_theme(s)
    return _blocked(finding_id, "not-allowlisted", "Primo does not repair this by itself; the Doctor's hint is text for you to read", "Not something Primo repairs")
