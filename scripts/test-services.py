#!/usr/bin/env python3
"""Checks for Primo's systemd user units: the unit file, install.sh --services/--remove-services, the overview wrapper and the autostart guard.

Everything runs against a temporary HOME with fake systemctl, gdbus, setsid and python3 on PATH; nothing reaches the real session."""
import configparser
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "config" / "hypr" / "scripts"
UNIT = ROOT / "config" / "systemd" / "user" / "primo-overview.service"


def fake(bindir, name, body):
    path = bindir / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def sandbox(manager=True, enabled=False):
    """A temp HOME and a PATH whose systemctl, gdbus, setsid and python3 only record what they were asked."""
    home = Path(tempfile.mkdtemp(prefix="primo-services-"))
    bindir = home / "bin"
    bindir.mkdir()
    log = home / "calls.log"
    state = home / "enabled"
    if enabled:
        state.touch()
    started = home / "started"
    if manager:
        fake(bindir, "systemctl", f'''echo "systemctl $*" >> "{log}"
case "$*" in
  *show-environment*) exit 0 ;;
  *is-enabled*) [[ -e "{state}" ]] ;;
  *"--user enable"*) touch "{state}" ;;
  *"--user disable"*) rm -f "{state}" ;;
  *"--user start"*) touch "{started}" ;;
esac
''')
    fake(bindir, "gdbus", f'''echo "gdbus $*" >> "{log}"
if [[ "$*" == *NameHasOwner* ]]; then [[ -e "{started}" ]] && echo "(true,)" || echo "(false,)"; fi
''')
    fake(bindir, "setsid", f'echo "setsid $*" >> "{log}"; touch "{started}"\n')
    fake(bindir, "python3", f'echo "python3 $*" >> "{log}"\n')
    for tool in ("bash", "sh", "env", "seq", "sleep", "grep", "dirname", "readlink", "mkdir", "ln", "rm", "date", "cat", "sed", "touch", "ls"):
        found = subprocess.run(["bash", "-c", f"command -v {tool}"], capture_output=True, text=True).stdout.strip()
        if found and not (bindir / tool).exists():
            (bindir / tool).symlink_to(found)
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "PATH": str(bindir)}
    return home, env, log


def calls(log):
    return log.read_text().splitlines() if log.exists() else []


def install(args, env):
    return subprocess.run(["/usr/bin/bash", str(ROOT / "scripts" / "install.sh"), *args], env=env, capture_output=True, text=True)


# ---- the unit file itself
unit = configparser.ConfigParser(strict=False, interpolation=None)
unit.optionxform = str
unit.read(UNIT)
assert unit["Service"]["Type"] == "dbus"
sys.path.insert(0, str(SCRIPTS))
import overview_core  # noqa: E402
assert unit["Service"]["BusName"] == overview_core.OWN_CLASS, "the unit waits for the bus name the service really owns"
assert unit["Service"]["ExecStart"].endswith("scripts/overview.py --daemon") and (SCRIPTS / "overview.py").exists()
assert unit["Service"]["Restart"] == "on-failure"
assert int(unit["Unit"]["StartLimitBurst"]) <= 5 and int(unit["Unit"]["StartLimitIntervalSec"]) > 0, "restarts are finite"
assert unit["Install"]["WantedBy"] == "graphical-session.target" and unit["Unit"]["PartOf"] == "graphical-session.target"

# ---- install: a preview changes nothing, then link + enable, then idempotent
home, env, log = sandbox()
out = install(["--services", "--dry-run"], env)
assert out.returncode == 0 and "[dry-run]" in out.stdout, out.stdout + out.stderr
assert not (home / ".config" / "systemd").exists() and not any("enable" in c for c in calls(log)), "dry run touched something"

out = install(["--services"], env)
link = home / ".config" / "systemd" / "user" / "primo-overview.service"
assert out.returncode == 0 and link.is_symlink() and link.resolve() == UNIT.resolve(), out.stdout + out.stderr
assert any(c.endswith("--user enable primo-overview.service") for c in calls(log)) and any("daemon-reload" in c for c in calls(log))
assert not any(" start " in c for c in calls(log)), "installing must not start or stop a running service"
before = len(calls(log))
out = install(["--services"], env)
assert out.returncode == 0 and "already linked" in out.stdout and link.is_symlink()
assert not any("daemon-reload" in c for c in calls(log)[before:]), "second run changed nothing, so no reload"

# ---- a user's own unit or drop-in is never replaced or removed
home, env, log = sandbox()
unit_dir = home / ".config" / "systemd" / "user"
(unit_dir / "primo-overview.service.d").mkdir(parents=True)
(unit_dir / "primo-overview.service.d" / "mine.conf").write_text("[Service]\nRestartSec=5\n")
mine = unit_dir / "primo-overview.service"
mine.write_text("# user's own\n")
out = install(["--services"], env)
assert out.returncode == 0 and "left alone" in out.stdout and not mine.is_symlink() and mine.read_text() == "# user's own\n"
out = install(["--remove-services"], env)
assert mine.read_text() == "# user's own\n" and (unit_dir / "primo-overview.service.d" / "mine.conf").exists()

# ---- remove: disables and drops only our own link, keeps drop-ins
home, env, log = sandbox()
install(["--services"], env)
(home / ".config" / "systemd" / "user" / "primo-overview.service.d").mkdir()
out = install(["--remove-services"], env)
assert out.returncode == 0 and not (home / ".config" / "systemd" / "user" / "primo-overview.service").exists()
assert (home / ".config" / "systemd" / "user" / "primo-overview.service.d").is_dir()
assert any(c.endswith("--user disable primo-overview.service") for c in calls(log))

# ---- no user manager: the fallback is named, nothing is installed
home, env, log = sandbox(manager=False)
out = install(["--services"], env)
assert out.returncode == 0 and "keep starting from the Hyprland autostart" in out.stdout
assert not (home / ".config" / "systemd").exists()

# ---- the wrapper: the unit starts the service when enabled, the old path otherwise; never both
for enabled in (True, False):
    home, env, log = sandbox(enabled=enabled)
    out = subprocess.run(["/usr/bin/bash", str(SCRIPTS / "overview.sh")], env=env, capture_output=True, text=True, timeout=20)
    got = calls(log)
    assert out.returncode == 0, out.stderr
    assert any("--user start primo-overview.service" in c for c in got) == enabled, got
    assert any(c.startswith("setsid") for c in got) == (not enabled), got
    assert any("Activate" in c for c in got), "the toggle is still delivered"

home, env, log = sandbox(enabled=True)
(home / "started").touch()                                  # already running: neither path starts anything
subprocess.run(["/usr/bin/bash", str(SCRIPTS / "overview.sh")], env=env, capture_output=True, text=True, timeout=20)
assert not any(c.startswith(("setsid", "systemctl --user start")) for c in calls(log)), "a running service is never started twice"

# ---- the autostart line: skipped while the unit is enabled, the old command otherwise; the other services are untouched
lua = (ROOT / "config" / "hypr" / "modules" / "autostart.lua").read_text()
line = re.search(r'hl\.exec_cmd\("(sh -c \'systemctl --user is-enabled -q primo-overview\.service[^"]*)"\)', lua)
assert line, "autostart.lua must guard the overview start with the unit check"
command = line.group(1).replace("~", "$HOME")
for enabled in (True, False):
    home, env, log = sandbox(enabled=enabled)
    subprocess.run(["/usr/bin/sh", "-c", command.replace("sh -c '", "", 1).rsplit("'", 1)[0]], env=env, capture_output=True, text=True, timeout=20)
    started = [c for c in calls(log) if c.startswith("python3")]
    assert bool(started) == (not enabled) and (not started or "overview.py --daemon" in started[0]), (enabled, calls(log))
for name in ("switcher", "launcher", "hub", "activity"):
    assert f'hl.exec_cmd("python3 ~/.config/hypr/scripts/{name}.py --daemon")' in lua, f"{name} must still start from autostart"

print("ok: services")
