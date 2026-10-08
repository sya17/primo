#!/usr/bin/env python3
"""Checks for the Doctor and the `primo` command: classification, exit codes, read-only behaviour, JSON shape. Uses a fake machine, never the real one."""
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "config" / "hypr" / "scripts"))
import doctor_core as dc

READ_ONLY = {("hyprctl", "version"), ("hyprctl", "configerrors"), ("systemctl", "--user"), ("systemctl", "is-active"), ("fc-list", ":"), ("python3", "-c")}


class Fake(dc.System):
    def __init__(self, home, tools, procs, session=True, fonts="Inter\nJetBrainsMono Nerd Font", active=(), configerrors="", version="Hyprland 0.56.2", free=0.5, repo=None):
        super().__init__(env={"HYPRLAND_INSTANCE_SIGNATURE": "x"} if session else {}, home=home, repo=repo)
        self.tools, self.procs, self.active, self._fonts_text, self.cfgerr, self.ver, self.free = set(tools), procs, set(active), fonts, configerrors, version, free
        self.calls = []

    def which(self, name): return f"/usr/bin/{name}" if name in self.tools else None
    def run(self, *cmd, timeout=4):
        self.calls.append(cmd)
        if cmd[:2] == ("hyprctl", "version"): return 0, self.ver
        if cmd[:2] == ("hyprctl", "configerrors"): return 0, self.cfgerr
        if cmd[0] == "python3": return 0, ""
        if cmd[0] == "systemctl" and "list-units" in cmd: return 0, "wayland-wm@%s.service loaded active running" % "hyprland.desktop"
        return 0, ""
    def processes(self): return self.procs
    def unit_active(self, unit, user=False): return unit in self.active
    def fonts(self): return self._fonts_text
    def exists(self, path): return str(path).startswith("/usr/") or Path(path).exists()          # /usr is the same on every machine the test runs on
    def disk_free(self, path="/"): return self.free


ALL_TOOLS = {b for f in dc.FEATURES for b, _p in f.requires} | {o[0] for f in dc.FEATURES for o in f.optional} | {"hypr-theme", "primo", "python3", "swaync", "git", "ufw"}
ALL_PROCS = ["waybar", "python3 /h/.config/hypr/scripts/launcher.py --daemon", "python3 /h/scripts/switcher.py --daemon", "python3 /h/scripts/overview.py --daemon",
             "python3 /h/scripts/hub.py --daemon", "python3 /h/scripts/activity.py --daemon", "swaync", "hypridle", "wl-paste --type text --watch cliphist store",
             "swayosd-server", "/bin/bash /h/battery-watch.sh", "/usr/lib/polkit-kde-authentication-agent-1"]
UNITS = {"bluetooth.service", "power-profiles-daemon.service", "NetworkManager.service", "ufw.service"}


def home_with(repo_files=True):
    h = Path(tempfile.mkdtemp())
    repo = h / "repo"
    (repo / "themes" / "primo-dusk").mkdir(parents=True)
    (repo / "themes" / "primo-dusk" / "theme.conf").write_text("name=Primo Dusk\n")
    if repo_files:
        for g in dc.GENERATED:
            (repo / g).parent.mkdir(parents=True, exist_ok=True)
            (repo / g).write_text("ok\n")
    for app in dc.LINKED_APPS:
        (repo / "config" / app).mkdir(parents=True, exist_ok=True)
        (h / ".config").mkdir(exist_ok=True)
        (h / ".config" / app).symlink_to(repo / "config" / app)
    (h / ".local/state/hyprland-dotfiles").mkdir(parents=True)
    (h / ".local/state/hyprland-dotfiles/current").write_text("primo-dusk\n")
    return h, repo


def status_of(results, rid): return next(r.status for r in results if r.id == rid)


# ---- a healthy machine
h, repo = home_with()
s = Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo)
res = dc.run_all(s)
sm = dc.summary(res)
assert sm["health"] == "HEALTHY" and sm["exit_code"] == 0, [(r.id, r.status, r.message) for r in res if r.status in ("warning", "fail")]
assert all(tuple(c[:2]) in READ_ONLY or c[0] in {"python3"} for c in s.calls), [c for c in s.calls if tuple(c[:2]) not in READ_ONLY][:3]   # nothing but reads

# ---- a required tool of a core feature is missing: failure, with the package to install
s = Fake(h, ALL_TOOLS - {"waybar"}, ALL_PROCS, active=UNITS, repo=repo)
res = dc.run_all(s)
dep = next(r for r in res if r.id == "dependency.bar")
assert dep.status == "fail" and dep.fix == "sudo pacman -S waybar" and dc.summary(res)["exit_code"] == 2

# ---- an optional tool is missing: never a failure
s = Fake(h, ALL_TOOLS - {"mpvpaper", "docker", "satty"}, ALL_PROCS, active=UNITS, repo=repo)
res = dc.run_all(s)
assert dc.summary(res)["exit_code"] == 0 and "mpvpaper" in next(r for r in res if r.id == "dependency.wallpaper").message

# ---- a non-core resident service is not running: warning with the start command
s = Fake(h, ALL_TOOLS, [p for p in ALL_PROCS if "hub.py" not in p], active=UNITS, repo=repo)
res = dc.run_all(s)
svc = next(r for r in res if r.id == "service.hub")
assert svc.status == "warning" and "hub.py --daemon" in svc.fix and dc.summary(res)["exit_code"] == 1
states = {f["id"]: f for f in dc.feature_states(res)}
assert states["hub"]["state"] == "stopped" and states["bar"]["state"] == "working"
states = {f["id"]: f for f in dc.feature_states(dc.run_all(Fake(h, ALL_TOOLS - {"cliphist"}, ALL_PROCS, active=UNITS, repo=repo)))}
assert states["clipboard"]["state"] == "unavailable"

# ---- outside a Hyprland session: one clear failure, runtime checks skipped
res = dc.run_all(Fake(h, ALL_TOOLS, [], session=False, active=UNITS, repo=repo))
assert status_of(res, "session.hyprland") == "fail" and status_of(res, "service.all") == "skipped"

# ---- Hyprland problems
res = dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo, configerrors="config: line 4: bad value"))
assert status_of(res, "session.configerrors") == "fail"
res = dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo, version="Hyprland 0.54.1"))
assert status_of(res, "session.version") == "warning"

# ---- configuration: broken JSON, broken link, private file mode, unresolved placeholders, missing generated files
(h / ".config/primo").mkdir()
(h / ".config/primo/modes.json").write_text("{ not json")
assert status_of(dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo)), "config.json") == "fail"
(h / ".config/primo/modes.json").write_text("[]")

# ---- the configuration check goes through the loader: path, line and a hint; shape and version count; absent files are fine
def config_result(): return next(r for r in dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo)) if r.id == "config.json")
assert config_result().status == "pass"
(h / ".config/primo/workflow.json").write_text('{\n "ics": ["https://calendar.example/private.ics"],\n "snippets": [ x ]\n}')
r = config_result()
assert r.status == "fail" and "workflow.json:3:" in r.message and "private.ics" not in r.message and r.fix, (r.message, r.fix)
(h / ".config/primo/workflow.json").write_text("{}")
(h / ".config/primo/modes.json").write_text("{}")
r = config_result()
assert r.status == "fail" and "modes.json" in r.message and "list" in r.message, r.message      # valid JSON, wrong kind of value
(h / ".config/primo/modes.json").write_text("[]")
(h / ".config/primo/extra.toml").write_text("version = 1\nname =\n")
r = config_result()
assert r.status == "fail" and "extra.toml:2:" in r.message, r.message                             # TOML definition files too
(h / ".config/primo/extra.toml").write_text('version = 3\nname = "x"\n')
assert "newer" in config_result().message
(h / ".config/primo/extra.toml").unlink()
(h / ".config/primo/workflow.json").unlink()
wf = h / ".config/primo/workflow.json"; wf.write_text("{}"); wf.chmod(0o644)
assert status_of(dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo)), "config.secret-file") == "warning"
wf.chmod(0o600)
assert status_of(dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo)), "config.secret-file") == "pass"
(repo / "config" / "waybar").rename(repo / "config" / "waybar.gone")
assert status_of(dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo)), "config.links") == "fail"
(repo / "config" / "waybar.gone").rename(repo / "config" / "waybar")
(repo / dc.GENERATED[0]).write_text("color = {{accent}}\n")
t = next(r for r in dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo)) if r.id == "theme.generated")
assert t.status == "fail" and "placeholders" in t.message and "primo-dusk" in t.fix
(repo / dc.GENERATED[0]).write_text("ok\n")

# ---- system and theme extras
assert status_of(dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo, free=0.03)), "system.disk") == "fail"
assert status_of(dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo, fonts="DejaVu")), "theme.fonts") == "warning"
assert status_of(dc.run_all(Fake(h, ALL_TOOLS, ALL_PROCS, active=UNITS - {"bluetooth.service"}, repo=repo)), "unit.bluetooth.service") == "warning"

# ---- a check that crashes is reported, the others still run
class Crash(Fake):
    def fonts(self): raise RuntimeError("boom")
res = dc.run_all(Crash(h, ALL_TOOLS, ALL_PROCS, active=UNITS, repo=repo))
assert any(r.id == "check.check_theme" and r.status == "fail" for r in res) and any(r.id == "session.hyprland" for r in res)

# ---- the registry itself
assert len({f.id for f in dc.FEATURES}) == len(dc.FEATURES)
for f in dc.FEATURES:
    assert f.name and f.summary and all(len(r) == 2 for r in f.requires) and all(len(o) == 3 for o in f.optional), f.id

# ---- the sample Health page for documentation screenshots: every feature works, and it cannot drift from the registry
sample = dc.sample_results()
assert dc.summary(sample)["health"] == "HEALTHY" and all(r.status == dc.PASS for r in sample)
states = dc.feature_states(sample)
assert [f["id"] for f in states] == [f.id for f in dc.FEATURES] and all(f["state"] == "working" and not f["notes"] for f in states)
assert {r.feature for r in sample if r.id.startswith("service.")} == {f.id for f in dc.FEATURES if f.process}

# ---- the command: JSON shape, exit codes, usage errors, no colour when piped
loader = importlib.machinery.SourceFileLoader("primo_cli", str(ROOT / "scripts" / "primo"))
spec = importlib.util.spec_from_loader("primo_cli", loader); cli = importlib.util.module_from_spec(spec); loader.exec_module(cli)
real_run_all = dc.run_all          # the CLI shares this module object, so keep the real function before replacing it
cli.dc.run_all = lambda s=None: real_run_all(Fake(h, ALL_TOOLS, [p for p in ALL_PROCS if "hub.py" not in p], active=UNITS, repo=repo))
buf = io.StringIO()
with redirect_stdout(buf):
    code = cli.main(["doctor", "--json"])
data = json.loads(buf.getvalue())
assert code == 1 and data["health"] == "DEGRADED" and data["version"] == 1 and {"id", "category", "title", "status", "message", "fix", "feature"} <= set(data["checks"][0]) and len(data["features"]) == len(dc.FEATURES)
buf = io.StringIO()
with redirect_stdout(buf):
    code = cli.main(["doctor"])
assert code == 1 and "\033[" not in buf.getvalue() and "try: python3" in buf.getvalue() and "Health: DEGRADED" in buf.getvalue()
buf = io.StringIO()
with redirect_stdout(buf):
    assert cli.main(["status", "--json"]) == 1
assert json.loads(buf.getvalue())["resident_services"] == {"running": 4, "total": 5}
assert cli.main(["doctor", "--category", "nope"]) == 64 and cli.main([]) == 64

# ---- primo config: path, show, validate (temp XDG folders; reads only, private values hidden)
cfg_home = Path(tempfile.mkdtemp())
os.environ.update({"XDG_CONFIG_HOME": str(cfg_home / "config"), "XDG_STATE_HOME": str(cfg_home / "state"), "XDG_DATA_HOME": str(cfg_home / "data")})
def run_cli(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(argv))
    return code, buf.getvalue()

code, text = run_cli("config", "validate")
assert code == 0 and "absent" in text, text                                      # nothing written yet: every file absent, all fine
code, data = run_cli("config", "path", "--json")
data = json.loads(data)
assert code == 0 and data["folders"]["config"] == str(cfg_home / "config") and {f["name"] for f in data["files"]} >= {"modes", "workflow", "activity", "hub"}
primo_dir = cfg_home / "config" / "primo"
primo_dir.mkdir(parents=True)
(primo_dir / "workflow.json").write_text(json.dumps({"ics": [{"name": "Work", "url": "https://calendar.example/private-token.ics"}],
                                                      "snippets": [{"name": "API key", "text": "sk-sample-secret"}]}))
code, text = run_cli("config", "show")
assert code == 0 and "private-token" not in text and "sk-sample-secret" not in text and "API key" in text and "Work" in text, text
code, data = run_cli("config", "show", "--json")
data = json.loads(data)
wf_entry = next(f for f in data["files"] if f["name"] == "workflow")
assert wf_entry["source"]["ics"] == str(primo_dir / "workflow.json") and wf_entry["source"]["ics_alert"] == "default", wf_entry["source"]
assert "private-token" not in json.dumps(data) and "sk-sample-secret" not in json.dumps(data)
modes_entry = next(f for f in data["files"] if f["name"] == "modes")
assert modes_entry["from"] == "defaults" and modes_entry["value"], modes_entry                 # no modes.json: the starting modes
(primo_dir / "modes.json").write_text('[\n {"id": "x",\n  "name": }\n]')
code, text = run_cli("config", "validate")
assert code == 2 and "modes.json:3:" in text, text
code, data = run_cli("config", "validate", "--json")
data = json.loads(data)
bad = next(f for f in data["files"] if f["name"] == "modes")
assert code == 2 and not data["valid"] and bad["status"] == "invalid" and bad["line"] == 3 and bad["path"] == str(primo_dir / "modes.json")
assert sorted(p.name for p in primo_dir.iterdir()) == ["modes.json", "workflow.json"], "primo config never writes, not even a copy of a broken file"
code, text = run_cli("config", "show")
assert code == 2 and "modes.json:3:" in text, text
assert cli.main(["config"]) == 64 and cli.main(["config", "nope"]) == 64
print("doctor checks passed")
