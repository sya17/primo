#!/usr/bin/env python3
"""Checks for the overview: its core (snapshot, target validation, actions, the stale state) and how the window is wired to workers.

Fake `hyprctl` answers and a fake runner with synthetic windows only: nothing here talks to the running compositor."""
import json
import os
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="primo ov "))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import overview_core as oc
import proc_core as pc
import settings_jobs as sj

SCRIPTS = Path(oc.__file__).resolve().parent


def client(address, cls="kitty", ws=1, **extra):
    return {"address": address, "class": cls, "title": f"{cls} title", "mapped": True, "hidden": False, "workspace": {"id": ws, "name": str(ws)}, **extra}


DESKTOP = {
    "clients": [client("0xa1", "kitty", 1), client("0xa2", "firefox", 2), client("0xa3", oc.OWN_CLASS, 1), client("0xa4", "ghost", 1, mapped=False),
                client("0xa5", "tucked", 1, hidden=True), client("0xa6", "", 1), client("0xa7", "code", 6)],
    "workspaces": [{"id": 1, "tiledLayout": "dwindle"}, {"id": 2, "tiledLayout": "dwindle"}, {"id": 6, "tiledLayout": "master"}],
    "monitors": [{"id": 0, "name": "SAMPLE-1", "width": 1920, "height": 1080}],
    "activeworkspace": {"id": 2}, "activewindow": {"address": "0xa2"},
}


class Fake:
    """A runner that answers like hyprctl -j, and records everything it was asked."""

    def __init__(self, desktop=None, **override):
        self.data = json.loads(json.dumps(desktop or DESKTOP))
        self.raw, self.calls = dict(override), []

    def __call__(self, argv, env=None, data=None):
        self.calls.append(list(argv))
        assert argv[0] == "hyprctl", argv
        if argv[1] == "dispatch":
            return self.raw.get("dispatch", pc.Run(code=0, out="ok"))
        what = argv[1]
        if what in self.raw:
            got = self.raw[what]
            return got if isinstance(got, pc.Run) else pc.Run(code=0, out=got)
        return pc.Run(code=0, out=json.dumps(self.data[what]))

    def dispatches(self):
        return [c for c in self.calls if c[1] == "dispatch"]


# ---- the snapshot: visible windows only, our own window out, nothing else asked
f = Fake()
snap = oc.snapshot(f)
assert [c["address"] for c in snap.clients] == ["0xa1", "0xa2", "0xa7"], "unmapped, hidden, nameless and the overview itself are left out"
assert snap.active_workspace == 2 and snap.active_window == "0xa2" and snap.monitors[0]["name"] == "SAMPLE-1" and len(snap.workspaces) == 3
assert [c[1] for c in f.calls] == ["clients", "workspaces", "monitors", "activeworkspace", "activewindow"] and all(c[2] == "-j" and c[0] == "hyprctl" for c in f.calls)
assert oc.workspace_ids(snap) == [1, 2, 3, 4, 5, 6], "the first four, every one in use, the active one"
assert oc.workspace_ids(oc.Snapshot(active_workspace=9)) == [1, 2, 3, 4, 9]

# an empty desktop is a valid answer, not a failure
empty = oc.snapshot(Fake(clients="[]", workspaces="[]", monitors="[]", activeworkspace="{}", activewindow="{}"))
assert empty.clients == [] and empty.workspaces == [] and empty.active_workspace is None and empty.active_window is None
assert oc.workspace_ids(empty) == [1, 2, 3, 4]
assert oc.snapshot(Fake(clients="", workspaces="", monitors="", activeworkspace="", activewindow="")).clients == [], "no output at all is empty, not an error"

# ---- failures raise with words, and each part of the answer counts
def fails(f, needle=""):
    try:
        oc.snapshot(f)
    except oc.OverviewError as e:
        assert needle in str(e), (needle, str(e))
        return
    raise AssertionError("must raise")


for part in ("clients", "workspaces", "monitors", "activeworkspace", "activewindow"):
    fails(Fake(**{part: "{ not json"}), "not JSON")
    fails(Fake(**{part: pc.Run(code=1, err="Error: no compositor\n")}), "no compositor")
    fails(Fake(**{part: pc.Run(reason="timeout")}), "too long")
    fails(Fake(**{part: '"a string"'}), "shape")
fails(Fake(clients=pc.Run(reason="missing")), "not installed")
fails(Fake(clients=json.dumps([{"address": "0xa1", "class": "x", "mapped": True}])), "cannot read")                          # no workspace
fails(Fake(clients=json.dumps([client("0xa1; reboot")])), "cannot read")                                     # an address that is not an address
fails(Fake(clients=json.dumps([{"mapped": True, "address": 5, "class": "x", "workspace": {"id": 1}}])), "cannot read")

# ---- the view: loading, current, stale; the last good content survives a failure, an empty answer is not a failure
v = oc.View()
assert v.state == "loading" and v.snapshot is None
assert v.apply(snap) is True and v.state == "ok"
assert v.apply(oc.snapshot(Fake())) is False, "the same desktop again: nothing to redraw"
assert v.apply(oc.OverviewError("Hyprland took too long to answer")) is True and v.state == "stale" and v.snapshot == snap
assert "too long" in v.error
assert v.apply(oc.OverviewError("still no")) is True and v.snapshot == snap, "failing twice still keeps the last valid"
assert v.apply(oc.snapshot(Fake())) is True and v.state == "ok" and v.error == "", "the same content after a failure redraws once to drop the notice"
assert v.apply(empty) is True and v.state == "ok" and v.snapshot.clients == []
assert oc.View(snap).state == "ok", "reopening starts from the last valid desktop"
first_fail = oc.View()
first_fail.apply(RuntimeError("boom"))
assert first_fail.state == "stale" and first_fail.snapshot is None

# ---- targets come from current data
assert oc.validate_target(snap, address="0xa1") and oc.validate_target(snap, workspace=6) and oc.validate_target(snap, "0xa2", 3)
assert oc.validate_target(snap, workspace=9) and oc.validate_target(snap, workspace=1), "the number keys 1-9 always work"
assert not oc.validate_target(snap, address="0xa3"), "our own window is not a target"
assert not oc.validate_target(snap, address="0xff") and not oc.validate_target(snap, workspace=10) and not oc.validate_target(snap, workspace=0)
assert not oc.validate_target(snap) and not oc.validate_target(snap, workspace=True) and not oc.validate_target(snap, workspace="2")
for hostile in ('0xa1" }); hl.dsp.exit(); --', "0xa1; reboot", "../x", "", 5):
    assert not oc.validate_target(snap, address=hostile), hostile
assert not oc.validate_target(snap, address=None, workspace=None)

# ---- actions: validated against a fresh read, one dispatch, nothing else
f = Fake()
assert oc.focus_window("0xa2", f) and f.dispatches() == [["hyprctl", "dispatch", 'hl.dsp.focus({ window = "address:0xa2" })']]
f = Fake()
assert oc.go_workspace(4, f) and f.dispatches() == [["hyprctl", "dispatch", "hl.dsp.focus({ workspace = 4 })"]]
f = Fake()
assert oc.move_window("0xa1", 5, f) and f.dispatches() == [["hyprctl", "dispatch", 'hl.dsp.window.move({ workspace = 5, window = "address:0xa1" })']]
f = Fake()
gone = oc.focus_window("0xdead", f)
assert not gone and "gone" in gone.reason and not f.dispatches(), "a vanished window is never dispatched"
f = Fake()
assert not oc.move_window("0xdead", 2, f) and not oc.move_window("0xa1", 99, f) and not oc.go_workspace(0, f) and not f.dispatches()
f = Fake()
assert not oc.focus_window('0xa1" }); hl.dsp.exit(); --', f) and not oc.move_window("0xa1; reboot", 2, f) and not f.dispatches()
f = Fake(clients=pc.Run(reason="timeout"))
slow = oc.go_workspace(2, f)
assert not slow and "too long" in slow.reason and not f.dispatches(), "when the compositor cannot be read, nothing is sent blind"
f = Fake(dispatch=pc.Run(code=0, out="Invalid dispatcher"))
assert not oc.focus_window("0xa1", f) and "Invalid" in oc.focus_window("0xa1", f).reason
assert not oc.focus_window("0xa1", Fake(dispatch=pc.Run(code=1, err="Error: boom")))
assert not oc.focus_window("0xa1", Fake(dispatch=pc.Run(reason="timeout")))

# ---- a slow compositor and a responsive one, with the real bounded runner and the job owner the window uses
bin_dir = work / "bin"
bin_dir.mkdir()
slow_marker = work / "slow.count"
(bin_dir / "hyprctl").write_text(f"""#!/bin/sh
case "$1" in
  clients) echo x >> "{slow_marker}"; sleep 20 ;;
  dispatch) echo ok ;;
  *) echo '[]' ;;
esac
""")
(bin_dir / "hyprctl").chmod(0o755)
os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
posted = []
post = lambda fn, *a: posted.append((fn, a))
owner = sj.JobOwner(post)
delivered = []
started = time.monotonic()
jobs_run = []


def refresh():
    def work_(cancel):
        jobs_run.append(1)
        return oc.snapshot(sj.Budget(cancel, total=8, per_child=0.4))
    return owner.submit("overview/snapshot", work_, delivered.append)


for _ in range(10):
    refresh()                                          # a burst: one running, the latest waiting, the rest replace it
quick = sj.Budget(threading.Event(), total=2, per_child=1)
t0 = time.monotonic()
assert quick(["hyprctl", "dispatch", "x"]).out.strip() == "ok" and time.monotonic() - t0 < 1, "other commands answer while a read is slow"
deadline = time.monotonic() + 6
while len(posted) < 2 and time.monotonic() < deadline:
    time.sleep(0.05)
assert len(jobs_run) == 2, ("ten requests became one running and one latest", len(jobs_run))
assert slow_marker.read_text().count("x") == 2, "the slow command ran once per job, then was killed at its deadline"
for fn, a in posted:
    fn(*a)
assert len(delivered) == 2 and all(isinstance(d, oc.OverviewError) and "too long" in str(d) for d in delivered), delivered
assert time.monotonic() - started < 8

# close and reopen: what a closed window was still reading is not delivered to anyone
owner2 = sj.JobOwner(post)
got2 = []
posted.clear()
owner2.submit("overview/snapshot", lambda cancel: oc.snapshot(sj.Budget(cancel, total=8, per_child=3)), got2.append)
time.sleep(0.3)
owner2.invalidate_prefix("overview/")
owner2.close()
t0 = time.monotonic()
while owner2.active and time.monotonic() - t0 < 3:
    time.sleep(0.05)
assert not owner2.active, "closing stops the read and its child"
for fn, a in posted:
    fn(*a)
assert got2 == [], "nothing from the old window reaches the new one"

# ---- the window is wired to all of this (no display needed: read the source)
src = (SCRIPTS / "overview.py").read_text()
assert "subprocess" not in src, "the window never runs a command itself"
assert "import overview_core" in src and "JobOwner" in src and "invalidate_prefix" in src and "REFRESH_SECONDS" in src
assert "source_remove" in src and "close-request" in src, "the refresh timer stops with the window"
assert "def snapshot" not in src and "def hypr(" not in src
check = (SCRIPTS.parent.parent.parent / "scripts" / "check.sh").read_text()
assert "test-overview.py" in check
print("overview core checks passed")

# ---- the window (needs GTK and a display; never shown), with a slow, then failing, then working fake compositor
if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (window checks)")
    sys.exit(0)
import importlib.machinery
import importlib.util
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
if not Gtk.init_check():
    print("skip: no display (window checks)")
    sys.exit(0)
log = work / "hyprctl.log"
mode = work / "mode"
data = {k: json.dumps(v) for k, v in DESKTOP.items()}
(bin_dir / "hyprctl").write_text(f"""#!/bin/sh
echo "$*" >> "{log}"
m=$(cat "{mode}" 2>/dev/null)
case "$m" in slow) sleep 1.5 ;; fail) echo "Error: no compositor" >&2; exit 1 ;; esac
case "$1" in
  clients) echo '{data["clients"]}' ;;
  workspaces) echo '{data["workspaces"]}' ;;
  monitors) echo '{data["monitors"]}' ;;
  activeworkspace) echo '{data["activeworkspace"]}' ;;
  activewindow) echo '{data["activewindow"]}' ;;
  dispatch) echo ok ;;
esac
""")
mode.write_text("slow")
here = SCRIPTS
loader = importlib.machinery.SourceFileLoader("overview_app", str(here / "overview.py"))
spec = importlib.util.spec_from_loader("overview_app", loader)
app_mod = importlib.util.module_from_spec(spec)
loader.exec_module(app_mod)
app = Adw.Application(application_id="dev.primo.OverviewTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
app.last = None
ctx_ = GLib.MainContext.default()
beats = [time.monotonic()]
GLib.timeout_add(20, lambda: (beats.append(time.monotonic()), True)[1])


def pump(seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not (until and until()):
        ctx_.iteration(False)
        time.sleep(0.002)


def cards(win):
    n, child = 0, win.grid.get_first_child()
    while child:
        n += "ws-card" in child.get_css_classes()
        child = child.get_next_sibling()
    return n


t0 = time.monotonic()
win = app_mod.OverviewWindow(app, None)
assert time.monotonic() - t0 < 0.4, "building the window never waits for Hyprland"
assert win.view.state == "loading" and cards(win) == 0
pump(1.0)
assert max(b - a for a, b in zip(beats, beats[1:])) < 0.3, "the main loop kept running while Hyprland was slow"
assert win.view.state == "loading", "still waiting: the window shows a loading note, not a frozen screen"
mode.write_text("ok")
pump(4, until=lambda: win.view.state == "ok")
assert win.view.state == "ok" and cards(win) == 6 and not win.notice_row.get_visible(), (win.view.state, cards(win))

# Hyprland stops answering: the last view stays, with a notice
mode.write_text("fail")
pump(4, until=lambda: win.view.state == "stale")
assert win.view.state == "stale" and cards(win) == 6 and win.notice_row.get_visible() and "last view" in win.notice.get_label(), win.notice.get_label()
mode.write_text("ok")
pump(4, until=lambda: win.view.state == "ok")
assert win.view.state == "ok" and not win.notice_row.get_visible(), "it recovers by itself"

# a window that is gone is refused visibly and nothing is sent; a real one is focused and the overview closes
dispatched = lambda: [l for l in log.read_text().splitlines() if l.startswith("dispatch")]
before = len(dispatched())
win.focus_window("0xdead")
pump(2, until=lambda: "gone" in win.notice.get_label())
assert "gone" in win.notice.get_label() and len(dispatched()) == before and win.notice_row.get_visible(), win.notice.get_label()
closed = []
win.close = lambda: (closed.append(1), win.on_close_request())      # a window that was never shown ignores close(): do what a close does
win.focus_window("0xa2")
pump(3, until=lambda: len(dispatched()) > before and closed)
assert dispatched()[-1] == 'dispatch hl.dsp.focus({ window = "address:0xa2" })' and closed, dispatched()[-2:]

# closing stops the refresh; the next opening starts from the last valid desktop
assert win.timer is None and app.last is not None
asked = len(log.read_text().splitlines())
pump(2.6)
assert len(log.read_text().splitlines()) == asked, "a closed overview asks Hyprland for nothing"
mode.write_text("slow")
again = app_mod.OverviewWindow(app, app.last)
assert cards(again) == 6 and again.view.state == "ok", "reopening shows the last valid desktop at once, while Hyprland is slow"
again.on_close_request()
pump(0.3)
print("overview window checks passed")
