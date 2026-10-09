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
    f.write(f"start {name} {os.getpid()} {time.monotonic():.3f} {' '.join(args)}\\n")
if name == "hyprctl" and os.path.exists(%(slow)r + "-hyprctl"):
    time.sleep(5)
if os.path.exists(%(slow)r) or (args[:1] == ["set"] and os.path.exists(%(slow)r + "-set")):
    time.sleep(3.0 if args[:1] == ["set"] and os.path.exists(%(slow)r + "-set") else 1.0)
if args[:1] == ["set"] and os.path.exists(%(slow)r + "-fail"):
    sys.stderr.write("Error: set failed\\n")
    sys.exit(1)
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
for tool in ("hyprctl", "powerprofilesctl", "bluetoothctl", "nmcli", "pacman", "pkill", "gdbus", "theme-switch"):
    path = tools / tool
    path.write_text(FAKE % {"log": str(log), "slow": str(slow)})
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
home = work / "home"
(home / "Pictures" / "Wallpapers").mkdir(parents=True)
os.environ["HOME"] = str(home)             # the wallpaper gallery lists ~/Pictures: sample pictures, never the user's own
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data")):
    os.environ[var] = str(work / sub)
os.environ["PATH"] = f"{tools}:{os.environ['PATH']}"      # the fakes come first; every tool a page may call has a fake (a real pkill or hyprctl would act on the live desktop)
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
ps.THEME_SWITCH = tools / "theme-switch"      # never the real theme-switch: it changes the live desktop

app = Adw.Application(application_id="dev.primo.SettingsTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
holds = []
real_hold, real_release = app.hold, app.release
app.hold = lambda: (holds.append("hold"), real_hold())
app.release = lambda: (holds.append("release"), real_release())
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
        kind, name, pid, _t = line.split(None, 4)[:4]
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

# ---- the wallpaper gallery: previews are made by owned children, two at a time, and a file that cannot be previewed still gets a tile
import struct, zlib
def _png(w, h, declared=None):
    chunk = lambda k, d: struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
    dw, dh = declared or (w, h)
    rows = b"".join(b"\x00" + bytes((30, 90, 200)) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", dw, dh, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
pics = home / "Pictures" / "Wallpapers"
(pics / "one.png").write_bytes(_png(800, 450))
(pics / "two.png").write_bytes(_png(640, 360))
(pics / "bomb.png").write_bytes(_png(8, 8, declared=(60000, 60000)))
(pics / "junk.png").write_bytes(b"not a picture" * 50)
slow.unlink(missing_ok=True)
most_children, themes_count = [0], len(list((here.parent.parent.parent / "themes").glob("*/wallpaper.png")))
win.select_page("wallpaper")
t0 = time.monotonic()
while time.monotonic() - t0 < 30 and (win.wp_queue or win.wp_inflight):
    pump(0.1)
    most_children[0] = max(most_children[0], int(os.popen("pgrep -fc '[t]humbnail_core.py --decode'").read().strip() or 0))
assert not win.wp_queue and not win.wp_inflight, (len(win.wp_queue), len(win.wp_inflight))
assert len(win.wp_buttons) == themes_count + 4, (len(win.wp_buttons), themes_count)
assert most_children[0] <= 2, most_children
tips = {Path(k).name: b.get_tooltip_text() for k, b in win.wp_buttons.items()}
assert "No preview: the picture has too many pixels" in tips["bomb.png"] and "No preview: the picture is not readable" in tips["junk.png"], tips
assert tips["one.png"] == str(pics / "one.png"), tips["one.png"]
assert os.popen("pgrep -fc '[t]humbnail_core.py --decode'").read().strip() in ("0", ""), "no decoder child is left"
assert not [p for p in Path(tempfile.gettempdir()).glob("primo-thumb-*")], "no preview folder is left"

# leaving the page mid-way stops the decoders; coming back asks again for what was not delivered
for extra in range(10):
    (pics / f"more{extra}.png").write_bytes(_png(900, 500))
win.wp_flow.remove_all() if hasattr(win.wp_flow, "remove_all") else None
win.wp_buttons.clear()
win.wp_queue = list(win.find_wallpapers())
win.wp_inflight.clear()
win.feed_thumbs()
pump(0.15)
win.select_page("appearance")
pump(1.0)
assert os.popen("pgrep -fc '[t]humbnail_core.py --decode'").read().strip() in ("0", ""), "the previews were stopped when the page was left"
assert win.incomplete & {k for k in win.incomplete if k.startswith("wallpaper/")}, win.incomplete
win.select_page("wallpaper")
t0 = time.monotonic()
while time.monotonic() - t0 < 40 and (win.wp_queue or win.wp_inflight):
    pump(0.1)
assert not win.wp_queue and not win.wp_inflight and len(win.wp_buttons) == themes_count + 14, (len(win.wp_queue), len(win.wp_inflight), len(win.wp_buttons))
for extra in range(10):
    (pics / f"more{extra}.png").unlink()
win.select_page("appearance")
pump(0.3)

# ---- changes to the system (T023): off the UI thread, one at a time per resource, honest about failure, held until done
def log_lines(tool, *first):
    return [l for l in (log.read_text().splitlines() if log.exists() else []) if l.startswith("start " + tool) and (not first or l.split(None, 4)[4:5] == [" ".join(first)] or " ".join(first) in l)]

slow.unlink(missing_ok=True)
toasts.clear()
win.select_page("appearance")
log.write_text("")
slow.write_text("1")
t0 = time.monotonic()
win.apply_theme("primo-dusk", "Primo Dusk")
win.apply_theme("primo-dawn", "Primo Dawn")                             # a second Apply while the first runs is refused, visibly
assert time.monotonic() - t0 < 0.3, "applying returned at once"
assert toasts.count("Still applying the last change") == 1, toasts
pump(4, until=lambda: "Primo Dusk applied" in toasts)
assert "Primo Dusk applied" in toasts and len(log_lines("theme-switch")) == 1, (toasts, log_lines("theme-switch"))
assert max(b - a for a, b in zip(beats, beats[1:])) < 0.2, "the main loop kept running during the apply"

# a failed apply says so and shows the real state; nothing claims success
slow.unlink()
(slow.parent / "slow-fail").write_text("1")
toasts.clear()
win.select_page("power")
pump(1)
win.set_profile("performance")
pump(3, until=lambda: any("Could not change" in t for t in toasts))
assert any("Could not change the power mode: set failed" in t for t in toasts) and "performance" not in " ".join(t for t in toasts if "changed" in t), toasts
pump(2, until=lambda: "power/profile" not in win.incomplete)
assert win.power_rows[0].get_title() == "Mode", "the page asked the system for the real state afterwards"
(slow.parent / "slow-fail").unlink()

# a tool that is too slow is an error, not success and not a rollback; the real state is read afterwards; the limit is the operation's own
(slow.parent / "slow-set").write_text("1")
ps.sj.ORDINARY = 0.5
toasts.clear()
t0 = time.monotonic()
win.set_profile("power-saver")
pump(4, until=lambda: any("taking too long" in t for t in toasts))
assert any("Could not change the power mode: it is taking too long" in t for t in toasts) and time.monotonic() - t0 < 2.5, (toasts, time.monotonic() - t0)
(slow.parent / "slow-set").unlink()
ps.sj.ORDINARY = 10.0

# the power toggle clicked three times: the first and the latest run, never the middle one
log.write_text("")
(slow.parent / "slow-set").write_text("1")
ps.sj.ORDINARY = 6.0
win.set_profile("power-saver")
win.set_profile("balanced")
win.set_profile("performance")
pump(8, until=lambda: len(log_lines("powerprofilesctl", "set")) >= 2 and not win.ops.jobs.active)
sets = [l.split(None, 4)[4] for l in log_lines("powerprofilesctl", "set")]
assert sets == ["set power-saver", "set performance"], sets
(slow.parent / "slow-set").unlink()
pump(1)
ps.sj.ORDINARY = 10.0

# declining a confirmation starts nothing; confirming runs it
log.write_text("")
win.vpn_remove_answered("cancel", "11111111-2222-3333-4444-555555555555", "Sample VPN")
pump(0.5)
assert not log_lines("nmcli", "connection delete"), log_lines("nmcli")
win.vpn_remove_answered("remove", "11111111-2222-3333-4444-555555555555", "Sample VPN")
pump(3, until=lambda: "Removed Sample VPN" in toasts)
assert "Removed Sample VPN" in toasts and len(log_lines("nmcli", "connection delete")) == 1

# a display change that cannot be applied keeps nothing and asks nothing
confirmed = []
win.confirm_displays = lambda specs, previous: confirmed.append(specs)
real_run = ps.ran
win.select_page("displays")
pump(5, until=lambda: not win.incomplete)
log.write_text("")
win.on_apply_displays()
win.on_apply_displays()                                                 # the same resource: refused while the first runs
pump(4, until=lambda: confirmed)
assert len(confirmed) == 1 and len(log_lines("hyprctl", "eval")) == len(win.collect_specs()), (len(confirmed), log_lines("hyprctl"))
confirmed.clear()
(slow.parent / "slow-hyprctl").write_text("1")                          # a hyprctl that never answers in time (the fake; the real one is never reached)
ps.sj.ORDINARY = 0.5
toasts.clear()
win.on_apply_displays()
pump(4, until=lambda: any("Could not apply" in t for t in toasts))
(slow.parent / "slow-hyprctl").unlink()
ps.sj.ORDINARY = 10.0
assert confirmed == [] and any("Could not apply the display settings: it is taking too long" in t for t in toasts), (confirmed, toasts)
assert not ps.DISPLAYS_LUA.exists(), "nothing was saved for a change that was never applied"

# the window closes while a change runs: the application stays held until it ends, nothing is shown afterwards
holds.clear()
toasts.clear()
(slow.parent / "slow-set").write_text("1")
ps.sj.ORDINARY = 6.0
win.select_page("power")
win.set_profile("balanced")
pump(0.3)
win.on_close_request()
assert holds.count("hold") - holds.count("release") >= 1, holds
pump(5, until=lambda: holds.count("hold") == holds.count("release"))
assert holds.count("hold") == holds.count("release") and not toasts, (holds, toasts)
(slow.parent / "slow-set").unlink()
ps.sj.ORDINARY = 10.0

# closing the window cancels what is still running and delivers nothing afterwards
win2 = ps.SettingsWindow(app, "bluetooth")
slow.write_text("1")
pump(0.3)
win2.on_close_request()                    # what GTK's close-request runs (an unshown window ignores close())
pump(1.5)
assert win2.jobs.closed and not any(p for p in subprocess.run(["pgrep", "-f", str(tools)], capture_output=True, text=True).stdout.split()), "no fake tool left running"
print("settings window checks passed (longest main-loop gap %.0f ms)" % (max(b - a for a, b in zip(beats, beats[1:])) * 1000))
