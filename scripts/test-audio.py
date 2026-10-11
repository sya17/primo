#!/usr/bin/env python3
"""Checks for audio_core: the audio snapshot and explicit device changes through a fake `pactl`. Nothing here makes a sound or touches a real device."""
import json
import os
import stat
import sys
import tempfile
import threading
from pathlib import Path

work = Path(tempfile.mkdtemp())
bin_dir = work / "bin"
bin_dir.mkdir()
state = work / "state.json"
log = work / "calls.log"
os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
os.environ["FAKE_PACTL"] = str(state)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import audio_core as ac
import proc_core as pc

FAKE = """#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_PACTL"]
st = json.load(open(path))
open(path + ".log", "a").write(" ".join(sys.argv[1:]) + "\\n")
a = sys.argv[1:]
if st.get("down"):
    sys.stderr.write("Connection failure: Connection refused\\n"); sys.exit(1)
if a[:2] == ["--format=json", "list"]:
    kind = a[2]
    print(json.dumps(st[kind]))
elif a[:1] == ["get-default-sink"]: print(st.get("default_sink", ""))
elif a[:1] == ["get-default-source"]: print(st.get("default_source", ""))
elif a[0] in ("set-default-sink", "set-default-source"):
    if st.get("fail"): sys.stderr.write("Failure: Access denied\\n"); sys.exit(1)
    st["default_sink" if a[0].endswith("sink") else "default_source"] = a[1]; json.dump(st, open(path, "w"))
elif a[0] in ("set-sink-volume", "set-source-volume"):
    if st.get("fail"): sys.stderr.write("Failure: Access denied\\n"); sys.exit(1)
    group = "sinks" if "sink" in a[0] else "sources"
    for d in st[group]:
        if d["name"] == a[1]:
            pct = int(a[2].rstrip("%"))
            d["volume"] = {c: {"value": pct * 655, "value_percent": f"{pct}%"} for c in d["volume"]}
    json.dump(st, open(path, "w"))
elif a[0] in ("set-sink-mute", "set-source-mute"):
    if st.get("fail"): sys.stderr.write("Failure: Access denied\\n"); sys.exit(1)
    group = "sinks" if "sink" in a[0] else "sources"
    for d in st[group]:
        if d["name"] == a[1]:
            d["mute"] = a[2] == "1"
    json.dump(st, open(path, "w"))
"""
(bin_dir / "pactl").write_text(FAKE)
(bin_dir / "pactl").chmod((bin_dir / "pactl").stat().st_mode | stat.S_IEXEC)


def dev(name, desc, pct=(100, 100), mute=False, monitor=None):
    return {"name": name, "description": desc, "mute": mute, "monitor_source": monitor,
            "volume": {f"ch{i}": {"value": p * 655, "value_percent": f"{p}%"} for i, p in enumerate(pct)}}


def put(**kw):
    base = {"sinks": [], "sources": [], "default_sink": "", "default_source": ""}
    base.update(kw)
    state.write_text(json.dumps(base))
    Path(str(state) + ".log").write_text("")


def calls():
    return Path(str(state) + ".log").read_text().splitlines()


run = lambda argv, **k: pc.run_bounded(argv, deadline=3, **k)

# ---- two outputs and two microphones; a monitor source is not a microphone; the same label twice stays two devices
put(sinks=[dev("sink.speaker", "Speaker", (100, 100)), dev("sink.headset", "Speaker", (35, 45), mute=True)],
    sources=[dev("source.mic1", "Microphone"), dev("source.mic2", "Microphone", (130, 130)), dev("sink.speaker.monitor", "Monitor of Speaker", monitor="sink.speaker")],
    default_sink="sink.headset", default_source="source.mic1")
snap = ac.snapshot(run)
assert [d.name for d in snap.outputs] == ["sink.speaker", "sink.headset"] and [d.name for d in snap.inputs] == ["source.mic1", "source.mic2"]
assert snap.default_output == "sink.headset" and snap.default_input == "source.mic1"
assert snap.outputs[0].label == snap.outputs[1].label == "Speaker" and snap.outputs[0].name != snap.outputs[1].name
assert (snap.outputs[1].volume, snap.outputs[1].muted) == (45.0, True), "the loudest channel is the level shown; mute is read"
assert snap.inputs[1].volume == 130.0, "above 100 % is shown honestly"
assert snap.outputs[0].kind == "sink" and snap.inputs[0].kind == "source"

# ---- nothing plugged in, and a server that is not there
put()
snap = ac.snapshot(run)
assert snap.outputs == [] and snap.inputs == [] and snap.default_output is None
state.write_text(json.dumps({"down": True}))
try:
    ac.snapshot(run)
    raise AssertionError("a missing audio server must be an error, not an empty list")
except ac.AudioError as e:
    assert "audio server" in str(e) and "Connection" not in str(e).split(":")[0]
saved_path = os.environ["PATH"]
os.environ["PATH"] = "/nonexistent"
try:
    ac.snapshot(lambda argv, **k: pc.run_bounded(argv, **k))
    raise AssertionError("missing pactl")
except ac.AudioError as e:
    assert "pactl is not installed" in str(e)
os.environ["PATH"] = saved_path

# ---- changes: re-read the device first, then act by its name, then report what the system says
put(sinks=[dev("sink.speaker", "Speaker"), dev("sink.headset", "Headset")], sources=[dev("source.mic1", "Microphone")],
    default_sink="sink.speaker", default_source="source.mic1")
out = ac.set_default("sink", "sink.headset", run)
assert out and ac.snapshot(run).default_output == "sink.headset"
out = ac.set_volume("source", "source.mic1", 40, run)
assert out and ac.snapshot(run).inputs[0].volume == 40.0
out = ac.set_mute("source", "source.mic1", True, run)
assert out and ac.snapshot(run).inputs[0].muted is True
assert ac.set_volume("sink", "sink.headset", 250, run) and ac.snapshot(run).outputs[1].volume == 100.0, "levels are 0 to 100"
assert ac.set_volume("sink", "sink.headset", -5, run) and ac.snapshot(run).outputs[1].volume == 0.0

# a device that disappeared between choosing and applying: refused, and nothing was sent for it or for another
put(sinks=[dev("sink.speaker", "Speaker")], sources=[], default_sink="sink.speaker")
out = ac.set_default("sink", "sink.headset", run)
assert not out and "no longer" in out.reason and not [c for c in calls() if c.startswith("set-")], (out, calls())
out = ac.set_mute("source", "source.mic1", True, run)
assert not out and "no longer" in out.reason

# names that look like options or shell are never passed on
put(sinks=[dev("-h", "Odd"), dev("a b; rm -rf /", "Odd2")], default_sink="")
assert not ac.set_default("sink", "-h", run)
assert not ac.set_default("sink", "a b; rm -rf /", run)
assert not [c for c in calls() if c.startswith("set-default-sink -h")], calls()
assert not ac.set_default("monitor", "x", run) and not ac.set_default("sink", "", run)

# a failing tool is reported with its own words
put(sinks=[dev("sink.speaker", "Speaker")], default_sink="sink.speaker", fail=True)
out = ac.set_mute("sink", "sink.speaker", True, run)
assert not out and "Access denied" in out.reason, out

# an external change between two reads is simply what the next snapshot shows
put(sinks=[dev("sink.a", "A"), dev("sink.b", "B")], default_sink="sink.a")
first = ac.snapshot(run)
state_data = json.loads(state.read_text())
state_data["default_sink"] = "sink.b"
state.write_text(json.dumps(state_data))
assert first.default_output == "sink.a" and ac.snapshot(run).default_output == "sink.b"

# a stuck pactl is bounded by the caller's deadline and reported as slow
slow_run = lambda argv, **k: pc.Run(reason="timeout")
try:
    ac.snapshot(slow_run)
    raise AssertionError("timeout must surface")
except ac.AudioError as e:
    assert "took too long" in str(e)

# slider changes coalesce per device: only the newest value of a burst is sent after the one running
sent = []
gate = threading.Event()
def fake_set(kind, name, percent, run):
    sent.append((name, percent))
    gate.wait(2)
    return ac.Outcome(True)
slider = ac.VolumeCoalescer(fake_set, run)
slider.change("sink", "sink.a", 10)
import time
time.sleep(0.05)
for pct in (20, 30, 40):
    slider.change("sink", "sink.a", pct)
slider.change("sink", "sink.b", 15)
gate.set()
slider.wait(3)
assert sent == [("sink.a", 10), ("sink.b", 15), ("sink.a", 40)] or sent == [("sink.a", 10), ("sink.a", 40), ("sink.b", 15)], sent
print("audio checks passed")

# ---- the Settings page (needs GTK and a display; the window is never shown)
if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (window checks)")
    sys.exit(0)
import importlib.machinery
import importlib.util
import time
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "st"), ("XDG_DATA_HOME", "data")):
    os.environ[var] = str(work / sub)
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
if not Gtk.init_check():
    print("skip: no display (window checks)")
    sys.exit(0)
here = Path(__file__).resolve().parent.parent / "config" / "hypr" / "scripts"
loader = importlib.machinery.SourceFileLoader("primo_settings", str(here / "primo-settings.py"))
spec = importlib.util.spec_from_loader("primo_settings", loader)
ps = importlib.util.module_from_spec(spec)
loader.exec_module(ps)
app = Adw.Application(application_id="dev.primo.SettingsAudioTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
ctx = GLib.MainContext.default()
beats = [time.monotonic()]
GLib.timeout_add(20, lambda: (beats.append(time.monotonic()), True)[1])


def pump(seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not (until and until()):
        ctx.iteration(False)
        time.sleep(0.002)


put(sinks=[dev("sink.speaker", "Speaker", (80, 80)), dev("sink.headset", "Headset", (35, 45), mute=True)],
    sources=[dev("source.mic1", "Microphone", (60, 60)), dev("sink.speaker.monitor", "Monitor of Speaker", monitor="sink.speaker")],
    default_sink="sink.speaker", default_source="source.mic1")
toasts = []
win = ps.SettingsWindow(app, "appearance")
win.toast = toasts.append
t0 = time.monotonic()
win.select_page("audio")
assert time.monotonic() - t0 < 0.4, "the page opens before pactl answers"
pump(5, until=lambda: win.audio_snapshot is not None)
out, inp = win.audio_ui["sink"], win.audio_ui["source"]
assert win.audio_snapshot and out["names"] == ["sink.speaker", "sink.headset"] and inp["names"] == ["source.mic1"], (out["names"], inp["names"])
assert out["group"].get_visible() and not win.audio_status.get_visible()
assert round(out["scale"].get_value()) == 80 and out["level"].get_label() == "80%" and not out["mute"].get_active()

# choosing another output sets the system default, then shows what the system reports
out["combo"].set_selected(1)
pump(5, until=lambda: ac.snapshot(run).default_output == "sink.headset" and not win.ops.jobs.active)
assert ac.snapshot(run).default_output == "sink.headset"
pump(3, until=lambda: out["mute"].get_active())
assert out["mute"].get_active() and round(out["scale"].get_value()) == 45, "the page shows the chosen device's own level and mute"

# mute and a burst of slider moves: the system ends at the last value, with fewer commands than moves
inp["mute"].set_active(True)
pump(5, until=lambda: ac.snapshot(run).inputs[0].muted)
assert ac.snapshot(run).inputs[0].muted
Path(str(state) + ".log").write_text("")
for v in (10, 20, 30, 40, 50, 70):
    inp["scale"].set_value(v)
pump(5, until=lambda: ac.snapshot(run).inputs[0].volume == 70.0 and win.audio_volume.idle.is_set())
sets = [c for c in calls() if c.startswith("set-source-volume")]
assert ac.snapshot(run).inputs[0].volume == 70.0 and 1 <= len(sets) <= 4, sets

# a device that disappears between choosing and applying: nothing is sent, the page re-reads and says why
gone = json.loads(state.read_text())
gone["sinks"] = [d for d in gone["sinks"] if d["name"] != "sink.speaker"]
state.write_text(json.dumps(gone))
Path(str(state) + ".log").write_text("")
toasts.clear()
out["combo"].set_selected(0)                                              # still the old list in the page: index 0 is "sink.speaker"
pump(5, until=lambda: any("Could not change" in t for t in toasts))
assert any("no longer there" in t for t in toasts) and not [c for c in calls() if c.startswith("set-default")], (toasts, calls())
pump(5, until=lambda: win.audio_ui["sink"]["names"] == ["sink.headset"])
assert win.audio_ui["sink"]["names"] == ["sink.headset"]

# the sound server stops: a failure row with Try again, and the page recovers when it is back
data = json.loads(state.read_text())
data["down"] = True
state.write_text(json.dumps(data))
win.refresh_audio()
pump(5, until=lambda: not win.audio_reading)
assert win.audio_status.get_visible()
data["down"] = False
state.write_text(json.dumps(data))
win.refresh_audio()
pump(5, until=lambda: not win.audio_status.get_visible())
assert not win.audio_status.get_visible() and win.audio_ui["sink"]["names"] == ["sink.headset"]

# no devices at all is an honest empty state
put()
win.refresh_audio()
pump(5, until=lambda: win.audio_ui["sink"]["names"] == [] and not win.audio_reading)
assert not win.audio_ui["sink"]["scale"].get_sensitive() and not win.audio_status.get_visible()
win.on_close_request()
print("audio page checks passed")
