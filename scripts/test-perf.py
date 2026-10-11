#!/usr/bin/env python3
"""Checks for the measurement helper (scripts/perf-baseline.py): /proc parsing, CPU and PSS deltas, restarted processes, unavailable counters.

Uses sample /proc text only; never measures the real machine."""
import importlib.machinery
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("perf_baseline", str(ROOT / "scripts" / "perf-baseline.py"))
spec = importlib.util.spec_from_loader("perf_baseline", loader)
pb = importlib.util.module_from_spec(spec)
loader.exec_module(pb)


def stat_line(pid, comm, utime, stime, start):
    fields = ["S", "1", "1", "1", "0", "-1", "4194560", "0", "0", "0", "0", str(utime), str(stime), "0", "0", "20", "0", "1", "0", str(start)]
    return f"{pid} ({comm}) " + " ".join(fields)


# a process name with spaces and parentheses does not shift the fields
assert pb.parse_stat(stat_line(42, "python3 (x) y", 120, 30, 9999)) == (150, 9999)
assert pb.parse_pss("Rss:   2048 kB\nPss:   1536 kB\nShared_Clean: 1 kB\n") == 1536
assert pb.parse_pss("Rss: 2048 kB\n") is None                     # no Pss line: unavailable, never zero

# which resident service a command line belongs to; anything else is not ours
assert pb.service_of("python3 /home/u/.config/hypr/scripts/hub.py --daemon") == "hub"
assert pb.service_of("/usr/bin/python3 /repo/config/hypr/scripts/launcher.py --daemon") == "launcher"
assert pb.service_of("python3 /repo/config/hypr/scripts/activity.py --top") is None     # the Waybar probe is measured separately
assert pb.service_of("vim /repo/config/hypr/scripts/hub.py") is None

# CPU relative to one logical CPU, from two samples of the same process
first = {"hub": {"pid": 10, "start": 500, "ticks": 100, "pss": 70000}}
last = {"hub": {"pid": 10, "start": 500, "ticks": 106, "pss": 70500}}
r = pb.compare(first, last, elapsed=30.0, clk=100)["hub"]
assert r["cpu_percent_one_core"] == 0.2 and r["pss_kib_start"] == 70000 and r["pss_kib_end"] == 70500 and r["identity"] == "same"

# a process that restarted (same PID reused, another start time) or went away is labelled, not averaged
r = pb.compare(first, {"hub": {"pid": 10, "start": 777, "ticks": 5, "pss": 1}}, elapsed=30.0, clk=100)["hub"]
assert r["identity"] == "restarted" and r["cpu_percent_one_core"] is None
r = pb.compare(first, {}, elapsed=30.0, clk=100)["hub"]
assert r["identity"] == "gone" and r["cpu_percent_one_core"] is None

# a PSS that could not be read stays unavailable in the totals
r = pb.compare({"a": {"pid": 1, "start": 1, "ticks": 0, "pss": None}}, {"a": {"pid": 1, "start": 1, "ticks": 0, "pss": None}}, 10.0, 100)
assert r["a"]["pss_kib_end"] is None and pb.total_pss(r) is None
assert pb.total_pss(pb.compare(first, last, 30.0, 100)) == 70500

# median and 95th percentile of a list of timings
s = pb.spread([float(n) for n in range(1, 101)])
assert s["count"] == 100 and s["median"] == 50.5 and s["p95"] == 95.05 and s["max"] == 100.0
assert pb.spread([]) == {"count": 0}

# every workload runs on sample data: the file search, in a temporary home folder
import os
import tempfile
home = Path(tempfile.mkdtemp())
(home / "docs").mkdir()
(home / "docs" / "readme.txt").write_text("x")
os.environ["HOME"] = str(home)
files = pb.cmd_files(None)
assert [r["query_length"] for r in files["runs"]] == [len(q) for q in pb.FILE_QUERIES] and files["runs"][0]["results"] == 1 and files["runs"][2]["results"] == 0, files
assert all(r["children"] == 1 for r in files["runs"])

# ---- render-context: observable facts only, null plus a reason when missing, nothing identifying
import json
sys.path.insert(0, str(ROOT / "config" / "hypr" / "scripts"))
import proc_core
MONITOR = {"id": 0, "name": "SAMPLE-1", "description": "Sample Maker Panel 0000", "make": "Sample", "model": "Panel", "serial": "SN-123456",
           "width": 2560, "height": 1440, "refreshRate": 143.9, "scale": 1.5, "transform": 0, "vrr": True, "currentFormat": "XRGB8888", "x": 0, "y": 0}
ANSWERS = {
    ("hyprctl", "version", "-j"): proc_core.Run(code=0, out=json.dumps({"version": "0.56.2", "tag": "v0.56.2", "commit": "abcdef0", "buildAt": "x"})),
    ("hyprctl", "monitors", "-j"): proc_core.Run(code=0, out=json.dumps([MONITOR, {**MONITOR, "name": "SAMPLE-2", "serial": "SN-9"}])),
    ("hyprctl", "getoption", "animations:enabled", "-j"): proc_core.Run(code=0, out='{"option": "animations:enabled", "bool": true, "set": true }'),
    ("pkg-config", "--modversion", "gtk4"): proc_core.Run(code=0, out="4.22.5\n"),
    ("pkg-config", "--modversion", "libadwaita-1"): proc_core.Run(code=0, out="1.9.4\n"),
    ("powerprofilesctl", "get"): proc_core.Run(code=0, out="balanced\n"),
    ("gsettings", "get", "org.gnome.desktop.interface", "enable-animations"): proc_core.Run(code=0, out="true\n"),
}
fake = lambda answers: (lambda argv: answers.get(tuple(argv), proc_core.Run(reason="missing")))
env = {"XDG_SESSION_TYPE": "wayland"}
ctx = pb.render_context(fake(ANSWERS), env, drm=None)
assert ctx["versions"] == {"hyprland": "0.56.2", "gtk4": "4.22.5", "libadwaita": "1.9.4", "python": pb.sys.version.split()[0]}, ctx["versions"]
assert ctx["monitors"] == [{"width": 2560, "height": 1440, "refresh_hz": 143.9, "scale": 1.5, "transform": 0, "vrr": True, "format": "XRGB8888"}] * 2
assert ctx["compositor_animations"] is True and ctx["gtk_animations"] is True and ctx["power_profile"] == "balanced" and ctx["session"] == "wayland"
text = json.dumps(ctx)
for secret in ("SN-123456", "SN-9", "SAMPLE-1", "Sample Maker", "Panel", str(Path.home())):
    assert secret not in text, secret
assert ctx["unavailable"] == {"gpu": "no DRM device was given or found"} or "gpu" in ctx["unavailable"]

# a tool that is missing, slow, or answers nonsense: null and why, never a guess
for tool, field, reason in ((("hyprctl", "monitors", "-j"), "monitors", "not installed"), (("hyprctl", "version", "-j"), "versions.hyprland", "not installed")):
    answers = {k: v for k, v in ANSWERS.items() if k != tool}
    got = pb.render_context(fake(answers), env, drm=None)
    assert reason in got["unavailable"][field], (field, got["unavailable"])
timeout = {**ANSWERS, **{("hyprctl", "monitors", "-j"): proc_core.Run(reason="timeout")}}
got = pb.render_context(fake(timeout), env, drm=None)
assert got["monitors"] is None and "took too long" in got["unavailable"]["monitors"]
bad = {**ANSWERS, **{("hyprctl", "monitors", "-j"): proc_core.Run(code=0, out="{ not json")}}
got = pb.render_context(fake(bad), env, drm=None)
assert got["monitors"] is None and "not JSON" in got["unavailable"]["monitors"]
no_refresh = {**ANSWERS, **{("hyprctl", "monitors", "-j"): proc_core.Run(code=0, out=json.dumps([{"width": 1920, "height": 1080, "scale": 1.0}]))}}
got = pb.render_context(fake(no_refresh), env, drm=None)
assert got["monitors"] == [{"width": 1920, "height": 1080, "refresh_hz": None, "scale": 1.0, "transform": None, "vrr": None, "format": None}] and "refresh_hz" in got["unavailable"]["monitors[0]"]
odd = pb.render_context(fake({**ANSWERS, ("hyprctl", "getoption", "animations:enabled", "-j"): proc_core.Run(code=0, out="{}")}), env, drm=None)
assert odd["compositor_animations"] is None and "did not report" in odd["unavailable"]["compositor_animations"]
nothing = pb.render_context(fake({}), {}, drm=None)
assert all(nothing[k] is not None or k in nothing["unavailable"] for k in ("monitors", "compositor_animations", "gtk_animations", "power_profile", "session", "gpu")), "a null always has a reason"
assert nothing["monitors"] is None and nothing["session"] is None and nothing["gtk_animations"] is None and all(isinstance(v, str) and v for v in nothing["unavailable"].values())
# the GPU: only the driver name and PCI ids from a DRM folder
drm = Path(tempfile.mkdtemp())
dev = drm / "card1" / "device"
dev.mkdir(parents=True)
(dev / "vendor").write_text("0x1002\n")
(dev / "device").write_text("0x1638\n")
(drm / "drivers" / "amdgpu").mkdir(parents=True)
(dev / "driver").symlink_to(drm / "drivers" / "amdgpu")
(drm / "card1-eDP-1").mkdir()
got = pb.render_context(fake(ANSWERS), env, drm=drm)
assert got["gpu"] == {"driver": "amdgpu", "vendor_id": "0x1002", "device_id": "0x1638"} and "gpu" not in got["unavailable"], got["gpu"]
assert "eDP" not in json.dumps(got), "connector names stay out"

# the frame probe: with a display it reports real frames, without one it says so (never a made-up number)
class A:
    seconds = 0.8
if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
    probe = pb.cmd_frame_probe(A)
    assert probe["available"] and probe["frame_interval_ms"]["count"] > 10 and probe["with_presentation_time"] <= probe["frames_reported"], probe
else:
    saved = {k: os.environ.pop(k, None) for k in ("WAYLAND_DISPLAY", "DISPLAY")}
    try:
        probe = pb.cmd_frame_probe(A)
    finally:
        os.environ.update({k: v for k, v in saved.items() if v})
    assert probe["available"] is False and "reason" in probe, probe

print("measurement helper checks passed")
