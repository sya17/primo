#!/usr/bin/env python3
"""Checks for the Activity collector worker: collection off the GTK thread, one at a time, requests coalesced, errors recovered.

No GTK and no live system: the jobs are fakes that sleep or fail; `post` stands in for GLib.idle_add."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import activity_collect as ac

posted = []                       # what would run on the GTK thread, in order
post = lambda fn, *args: posted.append((fn, args))
running, overlap = [0], [0]
callers = set()


class FakeSampler:
    pass


def job(name, seconds=0.0, fail=False):
    def run(sampler):
        assert isinstance(sampler, FakeSampler), "the job gets the collector's own sampler"
        callers.add(threading.current_thread().name)
        running[0] += 1
        overlap[0] = max(overlap[0], running[0])
        time.sleep(seconds)
        running[0] -= 1
        if fail:
            raise RuntimeError(f"{name} failed")
        return name
    return run


def done(name):
    return lambda result, error: (name, result, error)


def settle(col, limit=5.0):
    end = time.time() + limit
    while col.busy and time.time() < end:
        time.sleep(0.01)
    assert not col.busy, "the worker did not finish"


def results():
    return [fn(*args) for fn, args in posted]


col = ac.Collector(FakeSampler(), post)
t0 = time.monotonic()
col.request(job("slow", 0.4), done("slow"))
returned = time.monotonic() - t0
assert returned < 0.05, f"request() must not wait for the collection ({returned:.3f} s)"     # the GTK thread stays free
assert threading.main_thread().name not in callers

# while a slow collection runs, requests pile up into one: only the latest runs next, the others are dropped
for i in range(5):
    col.request(job(f"tick {i}"), done(f"tick {i}"))
settle(col)
assert results() == [("slow", "slow", None), ("tick 4", "tick 4", None)], results()
assert overlap[0] == 1, "never two collections at once"

# a failure reaches the caller as an error, and the next request works again
posted.clear()
col.request(job("broken", fail=True), done("broken"))
settle(col)
col.request(job("again"), done("again"))
settle(col)
(name, result, error), second = results()
assert name == "broken" and result is None and isinstance(error, RuntimeError) and second == ("again", "again", None), results()


# a result for a window that was closed (or replaced by a new one) is not applied
class Window:
    def __init__(self):
        self.alive, self.applied = True, []

    def on_snapshot(self, result, error):
        if self.alive and error is None:
            self.applied.append(result)


posted.clear()
old = Window()
col.request(job("for the old window", 0.2), old.on_snapshot)
time.sleep(0.05)
old.alive = False                 # closed before the collection finished
new = Window()
col.request(job("for the new window"), new.on_snapshot)
settle(col)
for fn, args in posted:
    fn(*args)
assert old.applied == [] and new.applied == ["for the new window"], (old.applied, new.applied)

# ---- the real window stays responsive while a collection is slow (needs GTK; skipped without a display)
if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("activity collector checks passed (window check skipped: no display)")
    sys.exit(0)
import tempfile
work = tempfile.mkdtemp()
for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
    os.environ[var] = os.path.join(work, var.lower())
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk
if not Gtk.init_check():
    print("activity collector checks passed (window check skipped: no display)")
    sys.exit(0)
import activity

calls = []
def slow_snapshot(sampler):       # a collection that takes far longer than a frame
    calls.append(time.monotonic())
    time.sleep(0.8)
    return {}, []
activity.snapshot = slow_snapshot
app = activity.Service(False)
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)      # never the running Activity service's name; no window is shown
app.register(None)
app.collector.sampler = type("S", (), {"sample": lambda self: {}})()
win = activity.ActivityWindow(app)
beats = [time.monotonic()]
def beat():
    beats.append(time.monotonic())
    return True
GLib.timeout_add(20, beat)
ctx = GLib.MainContext.default()
end = time.monotonic() + 3.5
while time.monotonic() < end:
    ctx.iteration(False)
    time.sleep(0.002)
gaps = [b - a for a, b in zip(beats, beats[1:])]
assert len(calls) >= 2 and max(gaps) < 0.2, (len(calls), max(gaps))      # collections ran, the main loop never waited for them
assert min(b - a for a, b in zip(calls, calls[1:])) >= 0.75, "one collection at a time, never overlapping"
win.close()
seen = len(calls)
end = time.monotonic() + 2.5
while time.monotonic() < end:
    ctx.iteration(False)
    time.sleep(0.002)
assert len(calls) <= seen + 1, "a closed window stops asking for collections"
print("activity collector checks passed (window stayed responsive: longest main-loop gap %.0f ms)" % (max(gaps) * 1000))
