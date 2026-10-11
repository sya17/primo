#!/usr/bin/env python3
"""Integrated checks for the 0.4 interactions: the notification panel, the launcher namespaces, Settings and the overview agree about
which tools exist, a missing tool leaves every surface usable, and repeated open/close of slow work leaks nothing.

Fake tools on temporary PATH folders and temporary HOME/XDG folders only: nothing here touches the running desktop. The per-window
scenarios (display needed, windows never shown) live in test-settings-window.py, test-clipboard.py and test-overview.py."""
import json
import os
import struct
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="primo interaction "))                  # a space in the path on purpose
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data")):
    os.environ[var] = str(work / sub)
os.environ["HOME"] = str(work / "home")
(work / "home").mkdir()
tmp_root = work / "tmp"
tmp_root.mkdir()
tempfile.tempdir = str(tmp_root)
os.environ["TMPDIR"] = str(tmp_root)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "config" / "hypr" / "scripts"))
import audio_core as ac
import clipboard_core as cp
import control_center as cc_
import doctor_core as dc
import launcher_core as lc
import network_core as nc
import overview_core as oc
import proc_core as pc
import settings_jobs as sj
import thumbnail_core as tc

BASE = json.loads((ROOT / "config" / "swaync" / "config.json").read_text())
ALL_TOOLS = {"nmcli", "nm-connection-editor", "pactl", "pavucontrol", "grim", "slurp", "wl-copy", "satty", "wf-recorder", "hyprsunset", "wofi", "powerprofilesctl",
             "hyprctl", "cliphist"}
real_path = os.environ["PATH"]


def tools_dir(names):
    d = Path(tempfile.mkdtemp(dir=work))
    for n in names:
        (d / n).write_text("#!/bin/sh\nexit 0\n")
        (d / n).chmod(0o755)
    return d


class Facts(lc.SampleFacts):
    """The sample machine, with tool lookups answered from one PATH folder."""
    def __init__(self, folder):
        self.folder = folder

    def has(self, binary):
        return (self.folder / binary).exists()


# ---- one tool at a time goes missing: Health, the panel and the launcher say the same thing
SURFACES = {            # feature -> (what the panel shows, launcher query, launcher title) ; None where that surface has no entry
    "network": ("--page network", "network ", "Open Network settings"),
    "audio": ("--page audio", "audio ", "Open Audio settings"),
    "vpn": (None, "vpn ", "Open VPN settings"),
    "capture": ("screenshot.sh", "capture ", "Screenshot an area"),
    "nightlight": ("nightlight.sh", "display ", "Toggle night light"),
}
for feature, (panel_text, query, title) in SURFACES.items():
    for gone in [None] + sorted({b for b, _p in dc.FEATURES_BY_ID[feature].requires}):
        present = ALL_TOOLS - {gone} if gone else ALL_TOOLS
        folder = tools_dir(present)
        system = dc.System(env={"PATH": str(folder)}, home=work / "home")
        state = next(f["state"] for f in dc.feature_states(dc.check_features(system)) if f["id"] == feature)
        panel = cc_.build_config(BASE, lambda b: (folder / b).exists())
        buttons = [a["command"] for a in panel["widget-config"]["buttons-grid"]["actions"]] if "buttons-grid" in panel["widgets"] else []
        shown_in_launcher = title in [i.title for i in lc.collect(query, lc.Context(facts=Facts(folder)))]
        expect = gone is None
        assert (state == "working") == expect, (feature, gone, state)
        assert shown_in_launcher == expect, (feature, gone, "launcher", [i.title for i in lc.collect(query, lc.Context(facts=Facts(folder)))])
        if panel_text:
            assert any(panel_text in c for c in buttons) == expect, (feature, gone, "panel", buttons)

# ---- every tool gone: nothing raises, every surface says why
empty = tools_dir([])
os.environ["PATH"] = str(empty)
try:
    run = lambda argv, **k: pc.run_bounded(argv, deadline=2, **k)
    for fn, error in ((lambda: nc.snapshot(run), nc.NetworkError), (lambda: ac.snapshot(run), ac.AudioError), (lambda: oc.snapshot(run), oc.OverviewError)):
        try:
            fn()
            raise AssertionError("must raise")
        except error as e:
            assert "not installed" in str(e), str(e)
    assert not nc.activate_saved("aaaaaaaa-0000-0000-0000-000000000001", "wlan0", run) and not ac.set_mute("source", "x", True, run) and not oc.focus_window("0xa1", run)
    entries = cp.list_entries(run)
    assert not getattr(entries, "ok", True) or list(entries) == [], entries
    live = lc.Facts()
    context = lc.Context(facts=live, launch_app=lambda i: None)
    for word in ("audio ", "network ", "vpn ", "capture ", "display ", "power ", "doctor ", "ws ", "win ", "theme ", "clip ", "firefox", "2+2"):
        lc.collect(word, context)                                  # no tool at all: an answer (maybe empty), never an exception
    assert [i.title for i in lc.collect("vpn ", context)] == ["VPN is not available here"] or "not available" in lc.collect("vpn ", context)[0].title
    bare = cc_.build_config(BASE, lambda b: False)
    assert "volume" not in bare["widgets"] and "dnd" in bare["widgets"] and "notifications" in bare["widgets"]
finally:
    os.environ["PATH"] = real_path

# ---- slow tools, repeated open and close: nothing leaks, nothing from a closed window is delivered
SLEEP = "31.7"
slow_dir = Path(tempfile.mkdtemp(dir=work))
for name in ("nmcli", "pactl", "hyprctl", "cliphist"):
    (slow_dir / name).write_text(f"#!/bin/sh\nsleep {SLEEP}\n")
    (slow_dir / name).chmod(0o755)
os.environ["PATH"] = f"{slow_dir}:{real_path}"
delivered = []
posted = []
post = lambda fn, *a: posted.append((fn, a))
threads_before = threading.active_count()
started = time.monotonic()
for cycle in range(30):
    owner = sj.JobOwner(post)
    owner.submit("network/snapshot", lambda cancel: nc.snapshot(sj.Budget(cancel)), delivered.append)
    owner.submit("audio/snapshot", lambda cancel: ac.snapshot(sj.Budget(cancel)), delivered.append)
    owner.submit("overview/snapshot", lambda cancel: oc.snapshot(sj.Budget(cancel)), delivered.append)     # the third waits: two workers
    owner.invalidate_prefix("network/")
    owner.invalidate_prefix("audio/")
    owner.invalidate_prefix("overview/")
    owner.close()
    deadline = time.monotonic() + 5
    while owner.active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not owner.active, ("work outlived its window", cycle)
assert time.monotonic() - started < 60, "closing never waits for a slow tool"
for fn, a in posted:
    fn(*a)
assert delivered == [], "a closed window receives nothing, so nothing is revived"
time.sleep(0.3)
left = os.popen(f"pgrep -f '[s]leep {SLEEP}' | wc -l").read().strip()
assert left == "0", f"{left} slow children outlived their windows"
assert threading.active_count() <= threads_before + 1, (threads_before, threading.active_count())
os.environ["PATH"] = real_path

# the same tools, left open: the deadline ends them, and the page gets a reason
os.environ["PATH"] = f"{slow_dir}:{real_path}"
t0 = time.monotonic()
try:
    nc.snapshot(sj.Budget(threading.Event(), total=2, per_child=0.4))
    raise AssertionError("must raise")
except nc.NetworkError as e:
    assert "too long" in str(e) and time.monotonic() - t0 < 1.5
os.environ["PATH"] = real_path
for _ in range(40):                                                  # the kill is sent at the deadline; give the system a moment to finish it
    if os.popen(f"pgrep -f '[s]leep {SLEEP}' | wc -l").read().strip() == "0":
        break
    time.sleep(0.05)
else:
    raise AssertionError("a slow tool survived its deadline")

# ---- an oversized picture is refused before it is decoded, and leaves no folder behind
def bomb(width, height, declared):
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes((200, 60, 60)) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", *declared, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


big = work / "enormous.png"
big.write_bytes(bomb(8, 8, (60000, 60000)))                          # a few hundred bytes that claim 3.6 billion pixels
before = set(tmp_root.iterdir())
t0 = time.monotonic()
result = tc.render(tc.ThumbnailRequest(big, 420, 250), threading.Event())
assert result.status == "placeholder" and result.png is None and time.monotonic() - t0 < 4, result
try:
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf  # noqa: F401
    assert "pixels" in result.reason, result.reason                  # refused from its header, before anything was allocated
except (ImportError, ValueError):
    pass                                                             # no GdkPixbuf here: it is still a placeholder, not a crash
assert set(tmp_root.iterdir()) == before, "no job folder is left behind"

print("interaction checks passed")
print("skip: windows are checked in test-settings-window.py, test-clipboard.py and test-overview.py (display needed)")
