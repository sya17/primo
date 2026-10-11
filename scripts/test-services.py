#!/usr/bin/env python3
"""Checks for Primo's systemd user units: the unit file, install.sh --services/--remove-services, the overview wrapper and the autostart guard.

Everything runs against a temporary HOME with fake systemctl, gdbus, setsid and python3 on PATH; nothing reaches the real session.
PRIMO_SERVICES_REAL=1 adds one run of the real overview in a private D-Bus session (two simultaneous starts, a kill, a restart); it needs a
display and reads Hyprland, so check.sh leaves it out."""
import configparser
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "config" / "hypr" / "scripts"
UNIT = ROOT / "config" / "systemd" / "user" / "primo-overview.service"


def fake(bindir, name, body):
    path = bindir / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def sandbox(manager=True, enabled=False, spawns=True):
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
  *"--user start"*) {'touch "' + str(started) + '"' if spawns else 'exit 1'} ;;
esac
''')
    fake(bindir, "gdbus", f'''echo "gdbus $*" >> "{log}"
if [[ "$*" == *NameHasOwner* ]]; then [[ -e "{started}" ]] && echo "(true,)" || echo "(false,)"; fi
''')
    fake(bindir, "setsid", f'echo "setsid $*" >> "{log}"{"; touch " + chr(34) + str(started) + chr(34) if spawns else ""}\n')
    fake(bindir, "notify-send", f'echo "notify-send $*" >> "{log}"\n')
    fake(bindir, "python3", f'echo "python3 $*" >> "{log}"\n')
    for tool in ("bash", "sh", "env", "seq", "sleep", "grep", "dirname", "readlink", "mkdir", "ln", "rm", "date", "cat", "sed", "touch", "ls"):
        found = subprocess.run(["bash", "-c", f"command -v {tool}"], capture_output=True, text=True).stdout.strip()
        if found and not (bindir / tool).exists():
            (bindir / tool).symlink_to(found)
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local" / "share"), "PATH": str(bindir)}
    return home, env, log


def calls(log):
    return log.read_text().splitlines() if log.exists() else []


def run_owned(cmd, env, timeout=30):
    """Run a command in its own process group and kill the whole group on timeout, so no private service is left behind."""
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        raise AssertionError(f"timed out after {timeout}s: {cmd[-3:]}")
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


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
assert unit["Service"]["RestartPreventExitStatus"] == "69", "a service that cannot reach its display is not retried"
bus = configparser.ConfigParser(strict=False, interpolation=None)
bus.optionxform = str
bus.read(ROOT / "config" / "systemd" / "dbus-1" / "services" / "dev.primo.Overview.service")
assert bus["D-BUS Service"]["Name"] == unit["Service"]["BusName"] and bus["D-BUS Service"]["SystemdService"] == UNIT.name
assert unit["Install"]["WantedBy"] == "graphical-session.target" and unit["Unit"]["PartOf"] == "graphical-session.target"

# ---- install: a preview changes nothing, then link + enable, then idempotent
home, env, log = sandbox()
out = install(["--services", "--dry-run"], env)
assert out.returncode == 0 and "[dry-run]" in out.stdout, out.stdout + out.stderr
assert not (home / ".config" / "systemd").exists() and not any("enable" in c for c in calls(log)), "dry run touched something"

out = install(["--services"], env)
link = home / ".config" / "systemd" / "user" / "primo-overview.service"
assert out.returncode == 0 and link.is_symlink() and link.resolve() == UNIT.resolve(), out.stdout + out.stderr
BUS = ROOT / "config" / "systemd" / "dbus-1" / "services" / "dev.primo.Overview.service"
buslink = home / ".local" / "share" / "dbus-1" / "services" / "dev.primo.Overview.service"
assert buslink.is_symlink() and buslink.resolve() == BUS.resolve(), "the bus activation file is linked with the unit"
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
assert not (home / ".local" / "share" / "dbus-1" / "services" / "dev.primo.Overview.service").exists(), "remove takes the activation file too"

# a bus activation file of the user's own survives both ways
home, env, log = sandbox()
busdir = home / ".local" / "share" / "dbus-1" / "services"
busdir.mkdir(parents=True)
(busdir / "dev.primo.Overview.service").write_text("# user's own\n")
install(["--services"], env)
install(["--remove-services"], env)
assert (busdir / "dev.primo.Overview.service").read_text() == "# user's own\n"

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

# ---- a service that cannot start says so: no guessed success, no second start, no Activate into the void
for enabled in (True, False):
    home, env, log = sandbox(enabled=enabled, spawns=False)
    out = subprocess.run(["/usr/bin/bash", str(SCRIPTS / "overview.sh")], env=env, capture_output=True, text=True, timeout=30)
    got = calls(log)
    assert out.returncode == 69 and "overview is not available" in out.stderr, (out.returncode, out.stderr)
    assert ("systemctl status" in out.stderr or "systemctl --user status" in out.stderr) == enabled, out.stderr
    assert any(c.startswith("notify-send") for c in got) and not any("Activate" in c for c in got), got
    assert sum(c.startswith("setsid") for c in got) == (0 if enabled else 1), "an enabled unit that fails is reported, not started a second way"

# ---- service_core: no bus and no display are reported with status 69, not hidden behind 0
sys.path.insert(0, str(SCRIPTS))
import service_core  # noqa: E402
assert service_core.EX_UNAVAILABLE == 69 == int(unit["Service"]["RestartPreventExitStatus"])
probe = "import sys; sys.path.insert(0, %r); import logging, service_core; service_core.require_session(logging.getLogger('t'))" % str(SCRIPTS)
clean = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
r = subprocess.run([sys.executable, "-c", probe], env=dict(clean, DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent"), capture_output=True, text=True, timeout=30)
assert r.returncode == 69 and "no session bus" in r.stderr, (r.returncode, r.stderr)
if shutil.which("dbus-run-session"):
    r = run_owned(["dbus-run-session", "--", sys.executable, "-c", probe], clean)
    assert r.returncode == 69 and "no display" in r.stderr, (r.returncode, r.stderr)
    r = run_owned(["dbus-run-session", "--", sys.executable, str(SCRIPTS / "overview.py"), "--daemon"], dict(clean, XDG_STATE_HOME=tempfile.mkdtemp(prefix="primo-services-")), timeout=15)
    assert r.returncode == 69, f"overview.py must use the check: exit {r.returncode}"
else:
    print("skipped: no display case (dbus-run-session not installed)")
r = run_owned([sys.executable, str(SCRIPTS / "overview.py"), "--daemon"], dict(clean, DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent", XDG_STATE_HOME=tempfile.mkdtemp(prefix="primo-services-")), timeout=15)
assert r.returncode == 69 and "no session bus" in r.stderr, (r.returncode, r.stderr)


# ---- the real overview in a private session: one winner of two simultaneous starts, and a free name after a kill (needs a display)
def concurrent_child():
    tmp = tempfile.mkdtemp(prefix="primo-services-")
    env = dict(os.environ, XDG_STATE_HOME=tmp + "/s", XDG_CONFIG_HOME=tmp + "/c", XDG_CACHE_HOME=tmp + "/ca", XDG_DATA_HOME=tmp + "/d",
               NO_AT_BRIDGE="1", GTK_A11Y="none", GTK_USE_PORTAL="0")
    env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)

    def owned():
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus", "--method",
                            "org.freedesktop.DBus.NameHasOwner", "dev.primo.Overview"], capture_output=True, text=True)
        return "true" in r.stdout

    def start(n):
        return [subprocess.Popen([sys.executable, str(SCRIPTS / "overview.py"), "--daemon"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(n)]

    procs = start(2)
    time.sleep(4)
    alive = [p for p in procs if p.poll() is None]
    assert len(alive) == 1 and owned(), f"{len(alive)} instances alive, name owned: {owned()}"
    alive[0].kill()
    alive[0].wait()
    time.sleep(0.5)
    assert not owned(), "a killed service must not keep its name"
    again = start(1)[0]
    time.sleep(3)
    assert again.poll() is None and owned(), "a fresh start after a kill takes the name"
    again.kill()
    again.wait()
    shutil.rmtree(tmp, ignore_errors=True)
    print("child ok")


if "--concurrent-child" in sys.argv:
    concurrent_child()
    sys.exit(0)
if not os.environ.get("PRIMO_SERVICES_REAL"):
    print("skipped: concurrent start and restart of the real overview (opt in with PRIMO_SERVICES_REAL=1; it reads Hyprland, which check.sh forbids)")
elif shutil.which("dbus-run-session") and (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")) and shutil.which("gdbus"):
    r = run_owned(["dbus-run-session", "--", sys.executable, __file__, "--concurrent-child"], os.environ.copy(), timeout=60)
    assert r.returncode == 0 and "child ok" in r.stdout, (r.stdout[-300:], r.stderr[-600:])
else:
    print("skipped: concurrent start and restart need a display, dbus-run-session and gdbus")

print("ok: services")
