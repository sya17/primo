#!/usr/bin/env python3
"""Checks for proc_core.run_bounded: a command with a deadline, an output cap and a cancel switch. Fake commands only (this Python itself)."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import proc_core as pc

PY = sys.executable


def py(code, *args, **kw):
    return pc.run_bounded([PY, "-c", code, *args], **kw)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


r = py("print('hello'); import sys; print('oops', file=sys.stderr)")
assert (r.ok, r.out.strip(), r.err.strip(), r.reason) == (True, "hello", "oops", ""), r

r = py("import sys; sys.exit(3)")
assert not r.ok and r.code == 3 and r.reason == "", r                      # a failing command is not a timeout

# the deadline: the child is stopped and reaped, and the call returns about when it said
t0 = time.monotonic()
r = py("import time, os; print(os.getpid(), flush=True); time.sleep(30)", deadline=0.4)
assert r.reason == "timeout" and not r.ok and time.monotonic() - t0 < 2, (r, time.monotonic() - t0)
assert not alive(int(r.out.split()[0])), "the timed-out child must be gone"

# the cap: a child that prints without end is stopped once the cap is reached, whatever the deadline
t0 = time.monotonic()
r = py("import sys\nwhile True: sys.stdout.write('x' * 65536)", cap=200_000, deadline=10)
assert r.reason == "output too large" and 200_000 <= len(r.out) + len(r.err) < 400_000 and time.monotonic() - t0 < 5, (r.reason, len(r.out))
r = py("import sys\nwhile True: sys.stderr.write('e' * 65536)", cap=100_000, deadline=10)
assert r.reason == "output too large", r.reason                              # stderr counts toward the same cap

# cancel: another thread stops it; only that child
cancel = threading.Event()
box = []
th = threading.Thread(target=lambda: box.append(py("import time, os; print(os.getpid(), flush=True); time.sleep(30)", deadline=20, cancel=cancel)))
th.start()
time.sleep(0.3)
cancel.set()
th.join(5)
assert not th.is_alive() and box[0].reason == "cancelled" and not alive(int(box[0].out.split()[0])), box
done = threading.Event()
done.set()
r = py("print('never')", cancel=done)                                        # already cancelled: it does not even start
assert r.reason == "cancelled" and r.out == "", r

# a program that does not exist
r = pc.run_bounded(["definitely-not-installed-xyz"])
assert r.reason == "missing" and not r.ok and r.code is None, r

# environment: added to the parent's, LC_ALL=C is the caller's to ask for
r = py("import os; print(os.environ.get('PRIMO_TEST_VAR'), os.environ.get('HOME') is not None)", env={"PRIMO_TEST_VAR": "yes"})
assert r.out.split() == ["yes", "True"], r

# non-UTF-8 output does not raise
r = py("import sys; sys.stdout.buffer.write(b'ok \\xff\\xfe done')")
assert r.ok and r.out.startswith("ok ") and r.out.endswith(" done"), r
# a program that closes its output and keeps running is stopped at the deadline, not left behind
t0 = time.monotonic()
r = py("import os, time; print(os.getpid(), flush=True); os.close(1); os.close(2); time.sleep(30)", deadline=0.5)
assert r.reason == "timeout" and time.monotonic() - t0 < 2.5 and not alive(int(r.out.split()[0])), (r, time.monotonic() - t0)

# many runs leave no zombies behind
for _ in range(20):
    py("print(1)")
    py("import time; time.sleep(5)", deadline=0.05)
assert not [c for c in __import__("subprocess").run(["ps", "--ppid", str(os.getpid()), "-o", "stat="], capture_output=True, text=True).stdout.split() if c.startswith("Z")]
print("bounded command checks passed")
