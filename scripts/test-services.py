#!/usr/bin/env python3
"""Checks for Primo's systemd user units: the unit file, install.sh --services/--remove-services, the overview wrapper and the autostart guard.

Everything runs against a temporary HOME with fake systemctl, gdbus, setsid and python3 on PATH; nothing reaches the real session.
PRIMO_SERVICES_REAL=1 adds one run of the real overview in a private D-Bus session (two simultaneous starts, a kill, a restart); it needs a
display and reads Hyprland, so check.sh leaves it out."""
import configparser
import json
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
UNITS = ROOT / "config" / "systemd" / "user"
BUSES = ROOT / "config" / "systemd" / "dbus-1" / "services"
# service name -> bus name
SERVICES = {"overview": "dev.primo.Overview", "launcher": "dev.primo.Launcher", "switcher": "dev.primo.Switcher", "activity": "dev.primo.Activity",
            "hub": "dev.primo.Hub"}


def fake(bindir, name, body):
    path = bindir / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def sandbox(manager=True, enabled=False, spawns=True, delay=0, activate_fails=False):
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
  *"--user start"*) {('(sleep ' + str(delay) + '; touch "' + str(started) + '") >/dev/null 2>&1 &' if delay else 'touch "' + str(started) + '"') if spawns else 'exit 1'} ;;
esac
''')
    fake(bindir, "gdbus", f'''echo "gdbus $*" >> "{log}"
if [[ "$*" == *NameHasOwner* ]]; then [[ -e "{started}" ]] && echo "(true,)" || echo "(false,)"; fi
{'if [[ "$*" == *Activate* ]]; then echo "Error: the service went away" >&2; exit 1; fi' if activate_fails else ''}
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


def ini(path):
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(path)
    return cp


def wrapper(name, env, timeout=30):
    return subprocess.run(["/usr/bin/bash", str(SCRIPTS / f"{name}.sh")], env=env, capture_output=True, text=True, timeout=timeout)


sys.path.insert(0, str(SCRIPTS))
import service_core  # noqa: E402

# ---- the unit files themselves
for name, busname in SERVICES.items():
    unit = ini(UNITS / f"primo-{name}.service")
    assert unit["Service"]["Type"] == "dbus" and unit["Service"]["BusName"] == busname
    source = (SCRIPTS / f"{name}.py").read_text()
    assert f'"{busname}"' in source or "OWN_CLASS" in source, f"{name}: the unit waits for a bus name the service does not own"
    assert unit["Service"]["ExecStart"].endswith(f"scripts/{name}.py --daemon")
    assert unit["Service"]["Restart"] == "on-failure"
    assert int(unit["Unit"]["StartLimitBurst"]) <= 5 and int(unit["Unit"]["StartLimitIntervalSec"]) > 0, "restarts are finite"
    assert unit["Service"]["RestartPreventExitStatus"] == str(service_core.EX_UNAVAILABLE) == "69", "no retry for a missing display"
    assert unit["Install"]["WantedBy"] == "graphical-session.target" and unit["Unit"]["PartOf"] == "graphical-session.target"
    bus = ini(BUSES / f"{busname}.service")
    assert bus["D-BUS Service"]["Name"] == busname and bus["D-BUS Service"]["SystemdService"] == f"primo-{name}.service"
    assert "require_session" in source, f"{name}.py must check its session before it starts"
assert ini(UNITS / "primo-overview.service")["Service"]["BusName"] == __import__("overview_core").OWN_CLASS

# ---- install: a preview changes nothing, then link + enable every unit, then idempotent
home, env, log = sandbox()
out = install(["--services", "--dry-run"], env)
assert out.returncode == 0 and "[dry-run]" in out.stdout, out.stdout + out.stderr
assert not (home / ".config" / "systemd").exists() and not any("enable" in c for c in calls(log)), "dry run touched something"

out = install(["--services"], env)
assert out.returncode == 0, out.stdout + out.stderr
for name, busname in SERVICES.items():
    link = home / ".config" / "systemd" / "user" / f"primo-{name}.service"
    assert link.is_symlink() and link.resolve() == (UNITS / f"primo-{name}.service").resolve(), name
    buslink = home / ".local" / "share" / "dbus-1" / "services" / f"{busname}.service"
    assert buslink.is_symlink() and buslink.resolve() == (BUSES / f"{busname}.service").resolve(), "the bus activation file is linked with the unit"
    assert any(c.endswith(f"--user enable primo-{name}.service") for c in calls(log)), name
assert any("daemon-reload" in c for c in calls(log))
assert not any(" start " in c or " stop " in c for c in calls(log)), "installing must not start or stop a running service"
before = len(calls(log))
out = install(["--services"], env)
assert out.returncode == 0 and out.stdout.count("already linked") == 2 * len(SERVICES)
assert not any("daemon-reload" in c for c in calls(log)[before:]), "second run changed nothing, so no reload"

# ---- a user's own unit, activation file or drop-in is never replaced or removed
home, env, log = sandbox()
unit_dir = home / ".config" / "systemd" / "user"
(unit_dir / "primo-launcher.service.d").mkdir(parents=True)
(unit_dir / "primo-launcher.service.d" / "mine.conf").write_text("[Service]\nRestartSec=5\n")
(unit_dir / "primo-launcher.service").write_text("# user's own\n")
busdir = home / ".local" / "share" / "dbus-1" / "services"
busdir.mkdir(parents=True)
(busdir / "dev.primo.Switcher.service").write_text("# user's own\n")
out = install(["--services"], env)
assert out.returncode == 0 and "left alone" in out.stdout and not (unit_dir / "primo-launcher.service").is_symlink()
assert (unit_dir / "primo-overview.service").is_symlink(), "one foreign file does not block the other services"
install(["--remove-services"], env)
assert (unit_dir / "primo-launcher.service").read_text() == "# user's own\n" and (unit_dir / "primo-launcher.service.d" / "mine.conf").exists()
assert (busdir / "dev.primo.Switcher.service").read_text() == "# user's own\n"

# ---- remove: disables and drops only our own links, keeps drop-ins
home, env, log = sandbox()
install(["--services"], env)
(home / ".config" / "systemd" / "user" / "primo-activity.service.d").mkdir()
out = install(["--remove-services"], env)
assert out.returncode == 0
for name, busname in SERVICES.items():
    assert not (home / ".config" / "systemd" / "user" / f"primo-{name}.service").exists(), name
    assert not (home / ".local" / "share" / "dbus-1" / "services" / f"{busname}.service").exists(), "remove takes the activation file too"
    assert any(c.endswith(f"--user disable primo-{name}.service") for c in calls(log)), name
assert (home / ".config" / "systemd" / "user" / "primo-activity.service.d").is_dir()

# ---- no user manager: the fallback is named, nothing is installed
home, env, log = sandbox(manager=False)
out = install(["--services"], env)
assert out.returncode == 0 and "keep starting from the Hyprland autostart" in out.stdout
assert not (home / ".config" / "systemd").exists()

# ---- each wrapper: the unit starts its service when enabled, the old path otherwise; never both; a running service is left alone
for name, busname in SERVICES.items():
    for enabled in (True, False):
        home, env, log = sandbox(enabled=enabled)
        out = wrapper(name, env)
        got = calls(log)
        assert out.returncode == 0, (name, out.stderr)
        assert any(f"--user start primo-{name}.service" in c for c in got) == enabled, (name, got)
        assert sum(c.startswith("setsid") for c in got) == (0 if enabled else 1), (name, got)
        assert any("Activate" in c and busname in c for c in got), f"{name}: the action is still delivered to its own bus name"
    home, env, log = sandbox(enabled=True)
    (home / "started").touch()
    wrapper(name, env)
    assert not any(c.startswith(("setsid", "systemctl --user start")) for c in calls(log)), f"{name}: a running service is never started twice"

# ---- a service that cannot start says so: no guessed success, no second start, no Activate into the void
for name in SERVICES:
    for enabled in (True, False):
        home, env, log = sandbox(enabled=enabled, spawns=False)
        out = wrapper(name, env)
        got = calls(log)
        assert out.returncode == 69 and f"the {name} service is not available" in out.stderr, (name, out.returncode, out.stderr)
        assert (f"systemctl --user status primo-{name}.service" in out.stderr) == enabled, out.stderr
        assert any(c.startswith("notify-send") for c in got) and not any("Activate" in c for c in got), got
        assert sum(c.startswith("setsid") for c in got) == (0 if enabled else 1), "an enabled unit that fails is reported, not started a second way"

# ---- a slow start is waited for (within the wrapper's limit); a service that disappears under the request is an error, not a success
for name in SERVICES:
    home, env, log = sandbox(enabled=True, delay=1)
    out = wrapper(name, env)
    assert out.returncode == 0 and any("Activate" in c for c in calls(log)), (name, "a start that takes a second is waited for", out.stderr)
    time.sleep(1.2)                                               # let the fake's background start finish before the sandbox is dropped
    home, env, log = sandbox(enabled=True, activate_fails=True)
    (home / "started").touch()
    out = wrapper(name, env)
    assert out.returncode != 0 and "went away" in out.stderr, (name, out.returncode, out.stderr)

# ---- the autostart lines: skipped while the unit is enabled, the old command otherwise
lua = (ROOT / "config" / "hypr" / "modules" / "autostart.lua").read_text()
for name in SERVICES:
    line = re.search(r'hl\.exec_cmd\("(sh -c \'systemctl --user is-enabled -q primo-%s\.service[^"]*)"\)' % name, lua)
    assert line, f"autostart.lua must guard the {name} start with the unit check"
    command = line.group(1).replace("~", "$HOME").replace("sh -c '", "", 1).rsplit("'", 1)[0]
    for enabled in (True, False):
        home, env, log = sandbox(enabled=enabled)
        subprocess.run(["/usr/bin/sh", "-c", command], env=env, capture_output=True, text=True, timeout=20)
        started = [c for c in calls(log) if c.startswith("python3")]
        assert bool(started) == (not enabled) and (not started or f"{name}.py --daemon" in started[0]), (name, enabled, calls(log))

# ---- service_core: no bus and no display are reported with status 69, not hidden behind 0
probe = "import sys; sys.path.insert(0, %r); import logging, service_core; service_core.require_session(logging.getLogger('t'))" % str(SCRIPTS)
clean = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS")}
r = subprocess.run([sys.executable, "-c", probe], env=dict(clean, DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent"), capture_output=True, text=True, timeout=30)
assert r.returncode == 69 and "no session bus" in r.stderr, (r.returncode, r.stderr)
has_run_session = bool(shutil.which("dbus-run-session"))
if has_run_session:
    r = run_owned(["dbus-run-session", "--", sys.executable, "-c", probe], clean)
    assert r.returncode == 69 and "no display" in r.stderr, (r.returncode, r.stderr)
else:
    print("skipped: no display case (dbus-run-session not installed)")
for name in SERVICES:   # the services really use it: every one of them exits 69, none runs on
    r = run_owned([sys.executable, str(SCRIPTS / f"{name}.py"), "--daemon"],
                  dict(clean, DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent", XDG_STATE_HOME=tempfile.mkdtemp(prefix="primo-services-")), timeout=15)
    assert r.returncode == 69 and "no session bus" in r.stderr, (name, r.returncode, r.stderr)
    if has_run_session:
        r = run_owned(["dbus-run-session", "--", sys.executable, str(SCRIPTS / f"{name}.py"), "--daemon"],
                      dict(clean, XDG_STATE_HOME=tempfile.mkdtemp(prefix="primo-services-")), timeout=15)
        assert r.returncode == 69, f"{name}.py must exit 69 without a display, not {r.returncode}"


# ---- the real services in a private session: one winner of two simultaneous starts, and a free name after a kill (needs a display)
def concurrent_child():
    tmp = tempfile.mkdtemp(prefix="primo-services-")
    env = dict(os.environ, XDG_STATE_HOME=tmp + "/s", XDG_CONFIG_HOME=tmp + "/c", XDG_CACHE_HOME=tmp + "/ca", XDG_DATA_HOME=tmp + "/d",
               NO_AT_BRIDGE="1", GTK_A11Y="none", GTK_USE_PORTAL="0")
    env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)

    def owned(busname):
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path", "/org/freedesktop/DBus", "--method",
                            "org.freedesktop.DBus.NameHasOwner", busname], capture_output=True, text=True)
        return "true" in r.stdout

    def start(name, n):
        return [subprocess.Popen([sys.executable, str(SCRIPTS / f"{name}.py"), "--daemon"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(n)]

    for name, busname in SERVICES.items():
        procs = start(name, 2)
        time.sleep(4)
        alive = [p for p in procs if p.poll() is None]
        try:
            assert len(alive) == 1 and owned(busname), f"{name}: {len(alive)} instances alive, name owned: {owned(busname)}"
        finally:
            for p in alive:
                p.kill()
                p.wait()
        time.sleep(0.5)
        assert not owned(busname), f"{name}: a killed service must not keep its name"
        again = start(name, 1)[0]
        time.sleep(3)
        try:
            assert again.poll() is None and owned(busname), f"{name}: a fresh start after a kill takes the name"
        finally:
            again.kill()
            again.wait()
    # an isolated crash leaves the others alone
    every = {name: start(name, 1)[0] for name in SERVICES}
    time.sleep(4)
    try:
        assert all(owned(b) for b in SERVICES.values()), "all of them own their names"
        every["launcher"].kill()
        every["launcher"].wait()
        time.sleep(0.5)
        assert not owned(SERVICES["launcher"]) and all(owned(b) for n, b in SERVICES.items() if n != "launcher"), "one crash must not take another service down"
    finally:
        for p in every.values():
            p.kill()
            p.wait()
    shutil.rmtree(tmp, ignore_errors=True)
    print("child ok")


# ---- the real time hub: reminders fire with no window open, a killed hub restarts without repeating or losing any (needs a display)
def hub_child():
    tmp = Path(tempfile.mkdtemp(prefix="primo-services-"))
    shim = tmp / "bin"
    shim.mkdir()
    shots = tmp / "notifications.log"
    fake(shim, "notify-send", f'echo "$*" >> "{shots}"\n')   # what a notification daemon would have been asked to show
    env = dict(os.environ, XDG_STATE_HOME=str(tmp / "s"), XDG_CONFIG_HOME=str(tmp / "c"), XDG_CACHE_HOME=str(tmp / "ca"), XDG_DATA_HOME=str(tmp / "d"),
               PRIMO_HUB_MUTE="1", PRIMO_NOTES_DIR=str(tmp / "notes"), NO_AT_BRIDGE="1", GTK_A11Y="none", GTK_USE_PORTAL="0",
               PATH=f"{shim}:{os.environ['PATH']}")
    env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
    store = tmp / "d" / "primo" / "hub.json"
    store.parent.mkdir(parents=True)
    from datetime import datetime, timedelta
    soon = (datetime.now() + timedelta(seconds=3)).isoformat(timespec="seconds")
    rem = lambda i, title, due: {"id": i, "title": title, "due": due, "repeat": None, "done": False, "fired": False}
    store.write_text(json.dumps({"reminders": [rem("a", "due soon", soon)], "timers": [{"id": "t", "total": 600, "end": time.time() + 600, "left": None}]}))

    def hub():
        return subprocess.Popen([sys.executable, str(SCRIPTS / "hub.py"), "--daemon"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def shown(title):
        return sum(title in line for line in shots.read_text().splitlines()) if shots.exists() else 0

    first = hub()
    try:
        time.sleep(8)                                             # no window was ever opened
        assert first.poll() is None and shown("due soon") == 1, shots.read_text() if shots.exists() else "nothing shown"
        assert json.loads(store.read_text())["reminders"][0]["fired"] is True, "the fired state is saved when it happens"
    finally:
        first.kill()
        first.wait()
    data = json.loads(store.read_text())                          # a kill leaves a whole, readable file with the timer still in it
    assert [t["id"] for t in data["timers"]] == ["t"]
    data["reminders"].append(rem("b", "while down", (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")))
    store.write_text(json.dumps(data))
    for round_ in (1, 2):                                         # the second start finds everything already handled
        again = hub()
        try:
            time.sleep(5)
            assert again.poll() is None
            assert shown("due soon") == 1, f"round {round_}: a fired reminder came back"
            assert shown("while down") == 1, f"round {round_}: the missed reminder was shown {shown('while down')} times"
        finally:
            again.kill()
            again.wait()
    assert [t["id"] for t in json.loads(store.read_text())["timers"]] == ["t"], "the running timer survived two kills"
    shutil.rmtree(tmp, ignore_errors=True)
    print("hub child ok")


if "--hub-child" in sys.argv:
    hub_child()
    sys.exit(0)
if "--concurrent-child" in sys.argv:
    concurrent_child()
    sys.exit(0)
if not os.environ.get("PRIMO_SERVICES_REAL"):
    print("skipped: concurrent start and restart of the real services (opt in with PRIMO_SERVICES_REAL=1; they read Hyprland, which check.sh forbids)")
elif has_run_session and (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")) and shutil.which("gdbus"):
    r = run_owned(["dbus-run-session", "--", sys.executable, __file__, "--concurrent-child"], os.environ.copy(), timeout=120)
    assert r.returncode == 0 and "child ok" in r.stdout, (r.stdout[-300:], r.stderr[-600:])
    r = run_owned(["dbus-run-session", "--", sys.executable, __file__, "--hub-child"], os.environ.copy(), timeout=120)
    assert r.returncode == 0 and "hub child ok" in r.stdout, (r.stdout[-300:], r.stderr[-800:])
else:
    print("skipped: concurrent start and restart need a display, dbus-run-session and gdbus")

print("ok: services")
