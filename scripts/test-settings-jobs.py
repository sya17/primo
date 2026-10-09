#!/usr/bin/env python3
"""Checks for settings_jobs: bounded background reads for the Settings window (no GTK: the UI dispatcher is a plain queue we pump)."""
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import settings_jobs as sj

PY = sys.executable
ui = queue.Queue()                           # what GLib.idle_add would run on the GTK thread, in order
post = lambda fn, *args: ui.put((fn, args))


def pump(limit=3.0, until=None):
    """Run the UI callbacks the way the main loop would; stop when `until()` is true or nothing arrives for a moment."""
    end, ran = time.monotonic() + limit, 0
    while time.monotonic() < end:
        try:
            fn, args = ui.get(timeout=0.05)
        except queue.Empty:
            if until is None or until():
                return ran
            continue
        fn(*args)
        ran += 1
    return ran


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class Gate:
    """A job body that blocks until released or cancelled, and counts how many run at once."""
    def __init__(self):
        self.release, self.running, self.most, self.started, self.cancelled = threading.Event(), 0, 0, [], []
        self.lock = threading.Lock()

    def work(self, name):
        def run(cancel):
            with self.lock:
                self.running += 1
                self.most = max(self.most, self.running)
                self.started.append(name)
            try:
                end = time.monotonic() + 5
                while not self.release.is_set() and not cancel.is_set() and time.monotonic() < end:
                    time.sleep(0.01)
                if cancel.is_set():
                    self.cancelled.append(name)
                return name
            finally:
                with self.lock:
                    self.running -= 1
        return run


# ---- a blocked job never blocks the dispatcher: submit returns at once and the UI keeps pumping
g = Gate()
owner = sj.JobOwner(post)
got = []
t0 = time.monotonic()
assert owner.submit("power/profiles", g.work("a"), got.append) is True
assert time.monotonic() - t0 < 0.05, "submit must not wait for the work"
assert pump(0.3) == 0 and got == [], "nothing to deliver while it is blocked, and the pump is not stuck"
g.release.set()
pump(until=lambda: bool(got))
assert got == ["a"], got

# ---- caps: two active jobs, four pending keys, one active and one latest pending per key; the rest is rejected
g = Gate()
owner = sj.JobOwner(post)
got = []
deliver = lambda r: got.append(r)
assert owner.submit("a", g.work("a1"), deliver) and owner.submit("b", g.work("b1"), deliver)
time.sleep(0.1)
assert [owner.submit(k, g.work(k + "1"), deliver) for k in "cdef"] == [True] * 4
assert owner.submit("g", g.work("g1"), deliver) is False, "a fifth pending key is rejected, and the caller can say so"
assert owner.submit("c", g.work("c2"), deliver) is True, "the same key replaces its pending request"
assert owner.submit("a", g.work("a2"), deliver) is False, "a is active; its one pending slot would be the fifth pending key"
g.release.set()
pump(until=lambda: len(got) >= 6)
time.sleep(0.2)
pump(0.5)
assert g.most == 2, g.most
assert sorted(got) == ["a1", "b1", "c2", "d1", "e1", "f1"], sorted(got)      # c1 was replaced and never ran
assert "c1" not in g.started

g = Gate()
owner = sj.JobOwner(post)
got = []
for i in (1, 2, 3):
    owner.submit("k", g.work(f"k{i}"), got.append)
    time.sleep(0.05)
g.release.set()
pump(until=lambda: len(got) >= 2)
time.sleep(0.2)
pump(0.5)
assert got == ["k1", "k3"], got                  # one active (k1) and the latest pending (k3); k2 was dropped

# replace=False keeps the request that is already waiting
g = Gate()
owner = sj.JobOwner(post, workers=1)
owner.submit("x", g.work("x1"), got.append)
time.sleep(0.05)
assert owner.submit("y", g.work("y1"), got.append) is True and owner.submit("y", g.work("y2"), got.append, replace=False) is False
g.release.set()
pump(until=lambda: False, limit=0.6)

# ---- one failure is delivered as the exception, and a retry works
def boom(cancel):
    raise RuntimeError("nmcli exploded")
got = []
owner = sj.JobOwner(post)
owner.submit("vpn/list", boom, got.append)
pump(until=lambda: bool(got))
assert len(got) == 1 and isinstance(got[0], RuntimeError) and "exploded" in str(got[0]), got
owner.submit("vpn/list", lambda cancel: "second try", got.append)
pump(until=lambda: len(got) >= 2)
assert got[1] == "second try"

# ---- leaving a page: its running read is cancelled, its waiting read dropped, and nothing is delivered later
g = Gate()
owner = sj.JobOwner(post, workers=1)
got = []
owner.submit("bluetooth/devices", g.work("old"), got.append)
time.sleep(0.05)
owner.submit("bluetooth/info", g.work("pending"), got.append)
owner.submit("power/profiles", g.work("other page"), got.append)
owner.invalidate_prefix("bluetooth/")
time.sleep(0.2)
assert g.cancelled == ["old"], g.cancelled           # the running one was told to stop
g.release.set()
pump(until=lambda: bool(got))
time.sleep(0.2)
pump(0.5)
assert got == ["other page"], got                    # the old result and the waiting one never reach the page

# the same key again after leaving and coming back is a fresh request
got.clear()
owner.submit("bluetooth/devices", lambda cancel: "fresh", got.append)
pump(until=lambda: bool(got))
assert got == ["fresh"]

# ---- close and reopen: a closed owner delivers nothing and accepts nothing; the next one starts clean
g = Gate()
old_owner = sj.JobOwner(post)
got = []
old_owner.submit("health", g.work("late"), got.append)
time.sleep(0.05)
old_owner.close()
assert old_owner.submit("health", g.work("x"), got.append) is False
g.release.set()
pump(0.5)
assert got == [] and g.cancelled == ["late"], (got, g.cancelled)
new_owner = sj.JobOwner(post)
new_owner.submit("health", lambda cancel: "new window", got.append)
pump(until=lambda: bool(got))
assert got == ["new window"]

# ---- the deadline of a refresh covers all its commands (3 s each, 8 s together in the app; scaled down here)
cancel = threading.Event()
budget = sj.Budget(cancel, total=0.6, per_child=0.4)
t0 = time.monotonic()
runs = [budget([PY, "-c", "import time; time.sleep(30)"]) for _ in range(3)]
elapsed = time.monotonic() - t0
assert [r.reason for r in runs] == ["timeout", "timeout", "timeout"] and elapsed < 1.1, (runs, elapsed)
assert runs[1].out == "" and elapsed >= 0.55, "the second child got only what was left of the shared budget"
fast = sj.Budget(cancel, total=5, per_child=2)([PY, "-c", "print('ok')"])
assert fast.ok and fast.out.strip() == "ok"

# ---- stdout and stderr overflow stop the owned child
budget = sj.Budget(cancel, total=5, per_child=5, cap=100_000)
r = budget([PY, "-c", "import os, sys; print(os.getpid(), flush=True)\nwhile True: sys.stderr.write('e' * 65536)"])
assert r.reason == "output too large" and not alive(int(r.out.split()[0])), r

# ---- a cancelled owner stops its commands: the budget built from the job's cancel event kills the child
g_cancel = threading.Event()
box = []
th = threading.Thread(target=lambda: box.append(sj.Budget(g_cancel, total=20, per_child=20)([PY, "-c", "import time, os; print(os.getpid(), flush=True); time.sleep(30)"])))
th.start()
time.sleep(0.3)
g_cancel.set()
th.join(5)
assert box and box[0].reason == "cancelled" and not alive(int(box[0].out.split()[0])), box

# ---- the app's limits are the design's
assert (sj.JobOwner(post).workers, sj.JobOwner(post).pending_limit) == (2, 4)
b = sj.Budget(threading.Event())
assert (b.total, b.per_child, b.cap) == (8.0, 3.0, 1 << 20)
print("settings jobs checks passed")
