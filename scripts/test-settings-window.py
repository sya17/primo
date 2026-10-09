#!/usr/bin/env python3
"""The Settings window with slow tools: building a page never waits for them, the main loop keeps running, at most two reads run at once,
leaving a page cancels its reads, and coming back reads again. Fake tools on a temporary PATH; the window is never shown.

Needs GTK and a display (skipped without one, like the hub service test)."""
import importlib.machinery
import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display")
    sys.exit(0)

work = Path(tempfile.mkdtemp())
tools = work / "bin"
tools.mkdir()
log = work / "tools.log"
slow = work / "slow"                    # while this file exists every fake tool takes a second to answer
slow.write_text("1")

FAKE = """#!/usr/bin/env python3
import os, sys, time
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(%(log)r, "a") as f:
    f.write(f"start {name} {os.getpid()} {time.monotonic():.3f}\\n")
if os.path.exists(%(slow)r):
    time.sleep(1.0)
out = ""
if name == "hyprctl" and args[:1] == ["monitors"]:
    out = '[{"name": "SAMPLE-1", "description": "Sample display", "width": 1920, "height": 1080, "refreshRate": 60.0, "scale": 1.0, "transform": 0, "x": 0, "y": 0, "disabled": false, "availableModes": ["1920x1080@60.00Hz", "1280x720@60.00Hz"]}]'
elif name == "powerprofilesctl":
    out = "  performance:\\n* balanced:\\n  power-saver:\\n" if args == ["list"] else "balanced\\n"
elif name == "bluetoothctl":
    out = {"show": "Controller AA:BB:CC:DD:EE:FF\\n\\tPowered: yes\\n", "devices": "Device 11:22:33:44:55:66 Sample Headset\\n", "info": "Connected: no\\n"}.get(args[0], "")
elif name == "nmcli":
    out = "" if "--active" in args else "Sample VPN:11111111-2222-3333-4444-555555555555:vpn\\n"
elif name == "pacman":
    sys.exit(1)
sys.stdout.write(out)
with open(%(log)r, "a") as f:
    f.write(f"end {name} {os.getpid()} {time.monotonic():.3f}\\n")
"""
for tool in ("hyprctl", "powerprofilesctl", "bluetoothctl", "nmcli", "pacman"):
    path = tools / tool
    path.write_text(FAKE % {"log": str(log), "slow": str(slow)})
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data")):
    os.environ[var] = str(work / sub)
os.environ["PATH"] = f"{tools}:{os.environ['PATH']}"
os.environ["PRIMO_SHOT_MODE"] = "1"      # the Health page shows its sample results: no real checks

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
if not Gtk.init_check():
    print("skip: no display")
    sys.exit(0)

here = Path(__file__).resolve().parent.parent / "config" / "hypr" / "scripts"
sys.path.insert(0, str(here))
loader = importlib.machinery.SourceFileLoader("primo_settings", str(here / "primo-settings.py"))
spec = importlib.util.spec_from_loader("primo_settings", loader)
ps = importlib.util.module_from_spec(spec)
loader.exec_module(ps)

app = Adw.Application(application_id="dev.primo.SettingsTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
ctx = GLib.MainContext.default()
beats = [time.monotonic()]
GLib.timeout_add(20, lambda: (beats.append(time.monotonic()), True)[1])


def pump(seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not (until and until()):
        ctx.iteration(False)
        time.sleep(0.002)


def concurrent_most():
    live, most = set(), 0
    for line in log.read_text().splitlines() if log.exists() else []:
        kind, name, pid, _t = line.split()
        (live.add if kind == "start" else live.discard)(pid)
        most = max(most, len(live))
    return most


win = ps.SettingsWindow(app, "appearance")
spent = {}
for page in ("displays", "power", "bluetooth", "vpn", "health"):
    t0 = time.monotonic()
    win.select_page(page)
    spent[page] = time.monotonic() - t0
    assert spent[page] < 0.5, spent                                   # the builder returned at once; the tools take a second each
    if page == "displays":
        assert win.monitors == [] and win.disp_loading is not None, "loading, not stale or invented data"
    pump(0.5)
    assert max(b - a for a, b in zip(beats, beats[1:])) < 0.2, "the main loop stalled while the tools were slow"
    pump(8, until=lambda p=page: not any(k.startswith(p + "/") for k in win.incomplete))
    assert not any(k.startswith(page + "/") for k in win.incomplete), (page, win.incomplete)
assert [m["name"] for m in win.monitors] == ["SAMPLE-1"] and win.disp_loading is None, win.monitors
assert win.power_rows and win.power_rows[0].get_title() == "Mode" and win.vpn_rows and win.bt_rows
assert win.vpn_need.get_visible(), "pacman said the OpenVPN plugin is not installed"
assert concurrent_most() <= 2, concurrent_most()

# limits: two running, four waiting, the rest refused with a visible message
toasts = []
win.toast = toasts.append
win.select_page("bluetooth")
pump(10, until=lambda: not win.incomplete and not win.jobs.active)     # the page's own read and the VPN page's periodic one finish first
assert not win.jobs.active
accepted = []
for i in range(8):
    win.read(f"bluetooth/probe{i}", lambda cancel: (cancel.wait(5), "x")[1], lambda r: None)
assert len(win.jobs.active) == 2 and len(win.jobs.pending) == 4 and toasts == ["Busy, try again in a moment"] * 2, (len(win.jobs.active), len(win.jobs.pending), toasts)
win.select_page("appearance")                                         # leaving the page cancels all of them
pump(0.5)
assert not win.jobs.active and not win.jobs.pending, (win.jobs.active, win.jobs.pending)
win.select_page("power")
pump(3, until=lambda: not win.incomplete)

# leaving a page cancels its read: nothing arrives for it, and it is read again when the page is shown again
win.select_page("power")
log.write_text("")
win.refresh_power()
pump(0.2)
win.select_page("appearance")                                         # the power read is still running (a second per tool)
pump(2.5)
assert "power/profile" in win.incomplete, win.incomplete
slow.unlink()                                                         # tools answer at once from now on
win.select_page("power")
pump(3, until=lambda: "power/profile" not in win.incomplete)
assert "power/profile" not in win.incomplete, "coming back read the page again"

# a tool that fails shows the failure with a retry, and the next read recovers
(tools / "powerprofilesctl").write_text("#!/bin/sh\necho 'daemon not running' >&2\nexit 1\n")
win.refresh_power()
pump(3, until=lambda: "power/profile" not in win.incomplete)
assert win.power_rows and "Could not" in win.power_rows[0].get_title(), [r.get_title() for r in win.power_rows]
(tools / "powerprofilesctl").write_text(FAKE % {"log": str(log), "slow": str(slow)})
win.refresh_power()
pump(3, until=lambda: "power/profile" not in win.incomplete)
assert win.power_rows and win.power_rows[0].get_title() == "Mode"

# closing the window cancels what is still running and delivers nothing afterwards
slow.write_text("1")
win.refresh_bluetooth()
pump(0.2)
win.on_close_request()                     # what GTK's close-request runs (an unshown window ignores close())
pump(1.5)
assert win.jobs.closed and not any(p for p in subprocess.run(["pgrep", "-f", str(tools)], capture_output=True, text=True).stdout.split()), "no fake tool left running"
print("settings window checks passed (longest main-loop gap %.0f ms)" % (max(b - a for a, b in zip(beats, beats[1:])) * 1000))
