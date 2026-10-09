"""Bounded background reads for the Settings window. Standard library only, no GTK: GTK objects never enter worker code.

A page asks for what it shows with `JobOwner.submit(key, work, deliver)`: `work(cancel)` runs on a worker thread (it may run commands
through a `Budget`), `deliver(result)` runs on the UI thread through `post` (GLib.idle_add in the app). Keys are `<page>/<what>`.
Limits: two jobs at a time, four waiting keys, and per key one running and the latest waiting request; anything beyond that is
rejected (submit returns False) so the page can say it is busy. Leaving a page calls `invalidate_prefix("<page>/")`: its running
reads are told to stop, its waiting ones dropped, and nothing they produce is delivered. When `work` raises, `deliver` gets the
exception object instead of a result.
"""
import threading
import time

import proc_core as pc

WORKERS = 2
PENDING = 4
TOTAL = 8.0            # seconds for all the commands of one refresh
PER_COMMAND = 3.0
CAP = 1 << 20          # stdout and stderr of one command together


class Budget:
    """The commands of one refresh: each may take `per_child` seconds, all of them together `total`. Call it with an argv list."""

    def __init__(self, cancel, total=TOTAL, per_child=PER_COMMAND, cap=CAP):
        self.cancel, self.total, self.per_child, self.cap = cancel, total, per_child, cap
        self.end = time.monotonic() + total

    def __call__(self, argv, env=None):
        left = self.end - time.monotonic()
        if left <= 0:
            return pc.Run(reason="timeout")
        return pc.run_bounded(argv, deadline=min(self.per_child, left), cap=self.cap, cancel=self.cancel, env=env)


class _Job:
    def __init__(self, key, work, deliver, generation):
        self.key, self.work, self.deliver, self.generation = key, work, deliver, generation
        self.cancel = threading.Event()


class JobOwner:
    def __init__(self, post, workers=WORKERS, pending_limit=PENDING):
        self.post, self.workers, self.pending_limit = post, workers, pending_limit
        self.lock = threading.Lock()
        self.active = {}       # key -> _Job
        self.pending = {}      # key -> _Job, the latest request per key, oldest key first
        self.generation = {}   # key -> number; a job whose number is behind was invalidated
        self.closed = False

    def submit(self, key, work, deliver, *, replace=True):
        """True when the request was accepted (running or waiting); False when it was rejected (too many, closed, or replace=False
        and one is already waiting for this key)."""
        with self.lock:
            if self.closed:
                return False
            job = _Job(key, work, deliver, self.generation.get(key, 0))
            if key not in self.active and len(self.active) < self.workers:
                self._start(job)
                return True
            if key in self.pending:
                if not replace:
                    return False
            elif len(self.pending) >= self.pending_limit:
                return False
            self.pending[key] = job
            return True

    def invalidate(self, key):
        with self.lock:
            self._invalidate(key)

    def invalidate_prefix(self, prefix):
        with self.lock:
            for key in set(self.active) | set(self.pending):
                if key.startswith(prefix):
                    self._invalidate(key)

    def close(self):
        with self.lock:
            self.closed = True
            for job in self.active.values():
                job.cancel.set()
            self.pending.clear()

    def _invalidate(self, key):
        self.generation[key] = self.generation.get(key, 0) + 1
        self.pending.pop(key, None)
        if key in self.active:
            self.active[key].cancel.set()

    def _start(self, job):
        self.active[job.key] = job
        threading.Thread(target=self._run, args=(job,), name="settings-job", daemon=True).start()

    def _run(self, job):
        try:
            result = job.work(job.cancel)
        except Exception as exc:          # handed to the page, which shows it and offers a retry
            result = exc
        with self.lock:
            del self.active[job.key]
            for key, waiting in list(self.pending.items()):      # oldest waiting request whose key is free
                if key not in self.active and len(self.active) < self.workers and not self.closed:
                    del self.pending[key]
                    self._start(waiting)
                    break
        self.post(self._deliver, job, result)

    def _deliver(self, job, result):
        """On the UI thread: only for a job that was not invalidated and an owner that is still open."""
        with self.lock:
            current = not self.closed and job.generation == self.generation.get(job.key, 0) and not job.cancel.is_set()
        if current:
            job.deliver(result)
