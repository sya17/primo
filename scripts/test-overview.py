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

# ---- search: title, class and workspace name, casefolded, every word must match
two = json.loads(json.dumps(DESKTOP))
two["monitors"] = [{"id": 0, "name": "eDP-1", "serial": "S1", "focused": True, "description": "Laptop panel"},
                   {"id": 1, "name": "HDMI-A-1", "serial": "S2", "focused": False, "description": "Sample TV"}]
two["workspaces"] = [{"id": 1, "name": "1", "monitor": "eDP-1", "tiledLayout": "dwindle"}, {"id": 2, "name": "web", "monitor": "HDMI-A-1"},
                     {"id": 6, "name": "6", "monitor": "eDP-1"}]
two["clients"] = [client("0xa1", "kitty", 1, title="Straße notes"), client("0xa2", "firefox", 2, title="Docs 2024"), client("0xa7", "code", 6, title="Ünïcode ÅNGSTRÖM")]
tsnap = oc.snapshot(Fake(two))
addrs = lambda q: [c["address"] for c in oc.filter_clients(tsnap, q)]
assert addrs("") == ["0xa1", "0xa2", "0xa7"] and addrs("   ") == addrs(""), "no query: everything, in workspace order"
assert addrs("STRASSE") == ["0xa1"] and addrs("straße") == ["0xa1"], "casefold, not lower"
assert addrs("ångström") == ["0xa7"] and addrs("ÅNGSTRÖM") == ["0xa7"] and addrs("ünï") == ["0xa7"]
assert addrs("fire") == ["0xa2"] and addrs("FireFox docs") == ["0xa2"] and addrs("firefox kitty") == [], "every word must match"
assert addrs("web") == ["0xa2"], "the workspace name Hyprland gave it"
assert addrs("workspace 6") == ["0xa7"] and addrs("2024") == ["0xa2"], "digits are text, not jumps"
assert addrs("zzz") == [] and addrs("[") == [] and addrs(".*") == [], "no pattern language: brackets and dots are just text"
assert addrs("0xa1") == [], "the address is not something to search"

# ---- groups: windows by monitor, workspaces by Hyprland's own names, nothing twice
def shape(groups):
    return [(g["key"], g["connected"], [(w["id"], w["label"], [c["address"] for c in w["windows"]]) for w in g["workspaces"]]) for g in groups]


groups = oc.group_workspaces(tsnap)
assert shape(groups) == [("S1", True, [(1, "Workspace 1", ["0xa1"]), (3, "Workspace 3", []), (4, "Workspace 4", []), (5, "Workspace 5", []), (6, "Workspace 6", ["0xa7"])]),
                         ("S2", True, [(2, "web", ["0xa2"])])], shape(groups)
assert [g["label"] for g in groups] == ["eDP-1", "HDMI-A-1"]
every = [c["address"] for g in groups for w in g["workspaces"] for c in w["windows"]]
assert sorted(every) == ["0xa1", "0xa2", "0xa7"], "each window once"

# one monitor: one group, no need for a header
one = oc.group_workspaces(snap)
assert len(one) == 1 and one[0]["label"] == "SAMPLE-1" and [w["id"] for w in one[0]["workspaces"]] == oc.workspace_ids(snap)
# no monitor information at all: still one group, nothing lost
bare = oc.group_workspaces(oc.Snapshot(clients=snap.clients, workspaces=snap.workspaces))
assert len(bare) == 1 and bare[0]["label"] == "" and sorted(c["address"] for w in bare[0]["workspaces"] for c in w["windows"]) == ["0xa1", "0xa2", "0xa7"]

# a monitor unplugged: its workspace still shows, once, under a name that says it is not connected
gone = json.loads(json.dumps(two))
gone["monitors"] = gone["monitors"][:1]
g2 = oc.group_workspaces(oc.snapshot(Fake(gone)))
assert [(g["label"], g["connected"]) for g in g2] == [("eDP-1", True), ("HDMI-A-1 (not connected)", False)], [(g["label"], g["connected"]) for g in g2]
assert sorted(c["address"] for g in g2 for w in g["workspaces"] for c in w["windows"]) == ["0xa1", "0xa2", "0xa7"]
# a window moved to the other monitor's workspace: it follows, and is still only in one place
moved = json.loads(json.dumps(two))
moved["clients"][0] = client("0xa1", "kitty", 2, title="Straße notes")
g3 = oc.group_workspaces(oc.snapshot(Fake(moved)))
assert [c["address"] for g in g3 for w in g["workspaces"] for c in w["windows"]].count("0xa1") == 1
assert [(w["id"], [c["address"] for c in w["windows"]]) for w in g3[1]["workspaces"]] == [(2, ["0xa2", "0xa1"])] or [(w["id"], sorted(c["address"] for c in w["windows"])) for w in g3[1]["workspaces"]] == [(2, ["0xa1", "0xa2"])]
# the same workspace name on two monitors is two workspaces, never merged
dup = json.loads(json.dumps(two))
dup["workspaces"].append({"id": 7, "name": "web", "monitor": "eDP-1"})
dup["clients"].append(client("0xb1", "evince", 7))
g4 = oc.group_workspaces(oc.snapshot(Fake(dup)))
assert [(g["label"], w["id"]) for g in g4 for w in g["workspaces"] if w["label"] == "web"] == [("eDP-1", 7), ("HDMI-A-1", 2)]
assert [c["address"] for w in g4[0]["workspaces"] if w["id"] == 7 for c in w["windows"]] == ["0xb1"]
# two identical monitors with no serial are told apart by connector
same = json.loads(json.dumps(two))
for m in same["monitors"]:
    m["serial"] = ""
assert [g["key"] for g in oc.group_workspaces(oc.snapshot(Fake(same)))] == ["eDP-1", "HDMI-A-1"]

# ---- preferences: through config_core only, defaults when absent, bad or newer files never overwritten by a read
import config_core as cc
prefs_path = work / "prefs" / "primo" / "overview.json"
os.environ["XDG_CONFIG_HOME"] = str(work / "prefs")
assert oc.preferences_path() == prefs_path
assert oc.load_preferences() == {"version": 1, "close_after_select": True} == oc.DEFAULTS
oc.save_preferences({"close_after_select": False})
assert json.loads(prefs_path.read_text()) == {"version": 1, "close_after_select": False} and oc.load_preferences()["close_after_select"] is False
assert oct(prefs_path.stat().st_mode & 0o777) == "0o600"
oc.save_preferences({"close_after_select": True, "junk": 1, "version": 9})
assert json.loads(prefs_path.read_text()) == {"version": 1, "close_after_select": True}, "only known keys, always the current version"
prefs_path.write_text('{"version": 1, "close_after_select": "no"}')
assert oc.load_preferences()["close_after_select"] is True, "a value of the wrong kind falls back to the default"
prefs_path.write_text('{ broken')
assert oc.load_preferences() == oc.DEFAULTS and list(prefs_path.parent.glob("overview.json.bad-*")), "a broken file is kept aside and defaults are used"
prefs_path.write_text('{"version": 7, "close_after_select": false}')
assert oc.load_preferences() == oc.DEFAULTS
try:
    oc.save_preferences({"close_after_select": False})
    raise AssertionError("a file from a newer Primo must not be saved over")
except cc.ConfigError as e:
    assert e.newer
assert json.loads(prefs_path.read_text())["version"] == 7
src_core = (SCRIPTS / "overview_core.py").read_text()
assert "open(" not in src_core and "read_text" not in src_core and "json.load(" not in src_core, "no raw file reads: config_core does that"

# ---- keeping the overview open: a selection and the focus loss it causes
assert oc.closes_on_focus_loss(True, None, 100.0) and oc.closes_on_focus_loss(True, 99.9, 100.0), "default: the overview goes away when you leave it"
assert not oc.closes_on_focus_loss(False, 99.5, 100.0), "kept open: the focus loss caused by the selection itself does not close it"
assert oc.closes_on_focus_loss(False, 90.0, 100.0), "kept open: but clicking away later still closes it"
assert oc.closes_on_focus_loss(False, None, 100.0), "kept open: nothing was selected, so leaving closes it"

print("overview core checks passed")

# ---- the window (needs GTK and a display; never shown), with a slow, then failing, then working fake compositor
if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (window checks)")
    sys.exit(0)
import importlib.machinery
import importlib.util
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
if not Gtk.init_check():
    print("skip: no display (window checks)")
    sys.exit(0)
log = work / "hyprctl.log"
mode = work / "mode"
dd = work / "desktop"
dd.mkdir()


def show(desktop):
    for k, v in desktop.items():
        (dd / k).write_text(json.dumps(v))


show(DESKTOP)
(bin_dir / "hyprctl").write_text(f"""#!/bin/sh
echo "$*" >> "{log}"
m=$(cat "{mode}" 2>/dev/null)
case "$m" in slow) sleep 1.5 ;; fail) echo "Error: no compositor" >&2; exit 1 ;; esac
case "$1" in
  dispatch) echo ok ;;
  *) cat "{dd}/$1" ;;
esac
""")
os.environ["XDG_CONFIG_HOME"] = str(work / "prefs-window")
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


def walk(widget):
    child = widget.get_first_child()
    while child:
        yield child
        yield from walk(child)
        child = child.get_next_sibling()


def count(win, css):
    return sum(css in w.get_css_classes() for w in walk(win.grid))


cards = lambda win: count(win, "ws-card")


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

# ---- two monitors: groups with headers, search, keyboard, and the keep-open preference
show(two)
mode.write_text("ok")
win = app_mod.OverviewWindow(app, None)
closed = []
win.close = lambda: (closed.append(1), win.on_close_request())
pump(4, until=lambda: win.view.state == "ok")
assert cards(win) == 6 and count(win, "ov-group") == 2, "two monitors: a header for each group"
assert [w.get_label() for w in walk(win.grid) if "ov-group" in w.get_css_classes()] == ["eDP-1", "HDMI-A-1"]
assert [w.get_label() for w in walk(win.grid) if "ws-name" in w.get_css_classes()].count("web") == 1, "Hyprland's own workspace name"

win.entry.set_text("fire")
pump(0.3)
assert win.query == "fire" and [c["address"] for c in win.matches] == ["0xa2"] and count(win, "win-tile") == 1 and count(win, "selected") == 1 and cards(win) == 0
win.entry.set_text("2024")
pump(0.3)
assert [c["address"] for c in win.matches] == ["0xa2"], "digits typed into the search are text"
assert win.on_key(None, Gdk.KEY_2, 0, Gdk.ModifierType(0)) is False, "a plain digit goes on to the search entry"
win.entry.set_text("zzz")
pump(0.3)
assert win.matches == [] and any("No window matches" in w.get_label() for w in walk(win.grid) if isinstance(w, Gtk.Label))
win.entry.set_text("o")                                         # kitty? no: titles/classes with an o: firefox, code ("Straße notes" has o too)
pump(0.3)
found = [c["address"] for c in win.matches]
assert len(found) >= 2 and win.sel == 0
before = len(dispatched())
assert win.on_key(None, Gdk.KEY_Down, 0, Gdk.ModifierType(0)) is True and win.sel == 1
assert win.on_key(None, Gdk.KEY_Up, 0, Gdk.ModifierType(0)) is True and win.on_key(None, Gdk.KEY_Up, 0, Gdk.ModifierType(0)) is True and win.sel == len(found) - 1, "arrows wrap"
win.sel = 1
win.render()
assert win.on_key(None, Gdk.KEY_Return, 0, Gdk.ModifierType(0)) is True
pump(3, until=lambda: len(dispatched()) > before and closed)
assert dispatched()[-1] == f'dispatch hl.dsp.focus({{ window = "address:{found[1]}" }})' and closed, "Enter focuses the selected window and closes"
win = app_mod.OverviewWindow(app, None)
win.close = lambda: (closed.append(1), win.on_close_request())
pump(3, until=lambda: win.view.state == "ok")
before = len(dispatched())
assert win.on_key(None, Gdk.KEY_3, 0, Gdk.ModifierType.ALT_MASK) is True
pump(3, until=lambda: len(dispatched()) > before)
assert dispatched()[-1] == "dispatch hl.dsp.focus({ workspace = 3 })", "Alt+digit still jumps"
assert win.on_key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0)) is True

# the preference: saved through config_core, and a kept-open overview survives its own selection and the focus loss it causes
del closed[:]
win = app_mod.OverviewWindow(app, None)
win.close = lambda: (closed.append(1), win.on_close_request())
pump(3, until=lambda: win.view.state == "ok")
assert win.prefs["close_after_select"] is True and win.keep.get_active()
win.keep.set_active(False)
prefs = oc.preferences_path()
pump(3, until=lambda: prefs.exists() and json.loads(prefs.read_text())["close_after_select"] is False)
assert json.loads(prefs.read_text()) == {"version": 1, "close_after_select": False}
before = len(dispatched())
win.focus_window("0xa2")
pump(3, until=lambda: len(dispatched()) > before)
pump(0.3)
assert not closed, "kept open: a successful selection does not close it"
assert win.close_if_left() is False and not closed, "kept open: nor does the focus loss the selection caused"
win.selected_at = time.monotonic() - 5
win.close_if_left()
assert closed, "kept open: leaving later still closes it"
again = app_mod.OverviewWindow(app, None)
assert again.prefs["close_after_select"] is False and not again.keep.get_active(), "the choice is remembered"
again.on_close_request()
# a kept-open window can still be closed on purpose
again.close = lambda: closed.append(2)
assert again.on_key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0)) is True and closed[-1] == 2
print("overview window checks passed")
