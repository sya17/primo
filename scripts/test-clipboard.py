#!/usr/bin/env python3
"""Checks for the clipboard picker: its core (list, copy, delete, wipe, preview) and, with a display, the window.

Fake `cliphist` and `wl-copy` on a temporary PATH with synthetic entries only: nothing here touches the real clipboard or its history."""
import importlib.machinery
import importlib.util
import os
import resource
import stat
import struct
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

work = Path(tempfile.mkdtemp())
tmp_root = work / "tmp"
tmp_root.mkdir()
tempfile.tempdir = str(tmp_root)
os.environ["TMPDIR"] = str(tmp_root)
tools = work / "bin"
tools.mkdir()
state = work / "state"
state.mkdir()
os.environ["PATH"] = f"{tools}:{os.environ['PATH']}"
os.environ["FAKE_STATE"] = str(state)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import clipboard_core as cp
import proc_core as pc

CLIPHIST = """#!/usr/bin/env python3
import os, sys, time
st = os.environ["FAKE_STATE"]
has = lambda n: os.path.exists(os.path.join(st, n))
def log(n, text): open(os.path.join(st, n), "a").write(text)
a = sys.argv[1:]
if a[:1] == ["list"]:
    if has("list.slow"): time.sleep(1.2)
    if has("list.huge"):
        for i in range(60000): sys.stdout.write(f"{i + 1}\\tline number {i} " + "x" * 60 + "\\n")
        sys.exit(0)
    sys.stdout.write(open(os.path.join(st, "list.txt")).read() if has("list.txt") else "")
elif a[:1] == ["decode"]:
    if a[1] in open(os.path.join(st, "expired")).read().split() if has("expired") else False:
        sys.stderr.write("no such entry\\n"); sys.exit(1)
    if has("decode.slow"): log("decode.log", "start " + a[1] + " " + str(os.getpid()) + "\\n"); time.sleep(30)
    if has("decode.big"):
        chunk = b"z" * 65536
        for _ in range(640): sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush(); sys.exit(0)
    p = os.path.join(st, "entry-" + a[1])
    sys.stdout.buffer.write(open(p, "rb").read() if os.path.exists(p) else b"sample text " + a[1].encode())
elif a[:1] == ["delete"]:
    data = sys.stdin.read()
    if has("delete.fail"): sys.stderr.write("cannot delete\\n"); sys.exit(1)
    log("deleted.log", data)
elif a[:1] == ["wipe"]:
    log("wiped.log", "wipe\\n")
    if has("wipe.fail"): sys.exit(1)
"""
WLCOPY = """#!/usr/bin/env python3
import os, sys
st = os.environ["FAKE_STATE"]
if os.path.exists(os.path.join(st, "copy.fail")):
    sys.stderr.write("compositor refused\\n"); sys.exit(1)
n = 0
while True:
    b = sys.stdin.buffer.read(65536)
    if not b: break
    n += len(b)
open(os.path.join(st, "copied.log"), "a").write(str(n) + "\\n")
"""
for name, body in (("cliphist", CLIPHIST), ("wl-copy", WLCOPY)):
    (tools / name).write_text(body)
    (tools / name).chmod((tools / name).stat().st_mode | stat.S_IEXEC)


def flag(name, on=True):
    path = state / name
    path.write_text("1") if on else path.unlink(missing_ok=True)


def read_log(name):
    path = state / name
    return path.read_text() if path.exists() else ""


def left_over():
    return sorted(p.name for p in tmp_root.iterdir())


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png(width, height):
    rows = b"".join(b"\x00" + bytes((90, 160, 60)) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


LINES = ["1\tfirst entry", "2\thttps://example.invalid/page", "3\t[[ binary data 12 KiB png 10x10 ]]", "4\ttext with\ttabs"]
(state / "list.txt").write_text("\n".join(LINES) + "\n")
cancel = threading.Event()
run = lambda cmd, cancel=None, **k: pc.run_bounded(cmd, deadline=3, cancel=cancel, **k)

# ---- the list: parsed, capped, honest about why it is short
entries = cp.list_entries(run)
assert [e["id"] for e in entries] == ["1", "2", "3", "4"] and entries[3]["text"] == "text with\ttabs" and entries.state == "ok" and not entries.truncated
assert entries[0]["line"] == LINES[0] and cp.is_image(entries[2]["text"]) and not cp.is_image(entries[0]["text"])
(state / "list.txt").write_text("\n".join(f"{i}\tentry {i}" for i in range(1, 131)) + "\nnot an id\tline\n-x\tline\n")
entries = cp.list_entries(run)
assert len(entries) == cp.MAX_ENTRIES == 120 and entries.truncated and entries[0]["id"] == "1" and entries.state == "ok"
(state / "list.txt").write_text("\n".join(f"{i}\tentry {i}" for i in range(1, 4)) + "\nnot an id\tline\n-x\tline\n")
assert [e["id"] for e in cp.list_entries(run)] == ["1", "2", "3"], "lines without a numeric id are ignored (an id is never an option)"
flag("list.huge")                                                         # millions of bytes of history: stops at the output cap, keeps the newest
t0 = time.monotonic()
entries = cp.list_entries(run)
assert len(entries) == 120 and entries.truncated and time.monotonic() - t0 < 4, (len(entries), time.monotonic() - t0)
flag("list.huge", False)
flag("list.slow")                                                         # a slow tool gives "timeout", not an empty history
t0 = time.monotonic()
entries = cp.list_entries(lambda cmd, cancel=None, **k: pc.run_bounded(cmd, deadline=0.4, cancel=cancel))
assert entries.state == "timeout" and not entries and time.monotonic() - t0 < 2, (entries.state, time.monotonic() - t0)
flag("list.slow", False)
(state / "list.txt").write_text("")
entries = cp.list_entries(run)
assert entries.state == "ok" and len(entries) == 0, "an empty history is a good answer"
saved_path = os.environ["PATH"]
os.environ["PATH"] = "/nonexistent"
assert cp.list_entries(lambda cmd, cancel=None, **k: pc.run_bounded(cmd, cancel=cancel)).state == "missing"
os.environ["PATH"] = saved_path
(state / "list.txt").write_text("\n".join(LINES) + "\n")

# ---- copying: cliphist into a private file, then wl-copy from that file, never through this process
(state / "entry-1").write_bytes(b"hello clipboard")
outcome = cp.copy_entry("1")
assert outcome and read_log("copied.log").split() == ["15"], (outcome, read_log("copied.log"))
(state / "copied.log").unlink()
flag("decode.big")                                                        # 40 MiB: far over the preview limit, copied anyway, in bounded memory
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
outcome = cp.copy_entry("1")
growth_mib = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
assert outcome and read_log("copied.log").split() == [str(640 * 65536)] and growth_mib < 12, (outcome, read_log("copied.log"), growth_mib)
flag("decode.big", False)
(state / "copied.log").unlink()
(state / "expired").write_text("77\n")                                    # an entry that left the history meanwhile
outcome = cp.copy_entry("77")
assert not outcome and "no longer" in outcome.reason and not read_log("copied.log"), outcome   # wl-copy was never started: no empty clipboard
flag("copy.fail")                                                         # wl-copy refusing is reported, not hidden
outcome = cp.copy_entry("1")
assert not outcome and "wl-copy" in outcome.reason, outcome
flag("copy.fail", False)
assert not cp.copy_entry("1; rm -rf /") and not cp.copy_entry("-h"), "an id is a number, never an option or a command"
flag("decode.slow")
t0 = time.monotonic()
outcome = cp.copy_entry("1", deadline=0.4)
assert not outcome and "too long" in outcome.reason and time.monotonic() - t0 < 3, (outcome, time.monotonic() - t0)
flag("decode.slow", False)
leftover = [int(l.split()[2]) for l in read_log("decode.log").splitlines()]
for pid in leftover:                                                       # the pipeline must have stopped the producer itself
    try:
        os.kill(pid, 0)
        raise AssertionError("the producer of a timed-out copy must be gone")
    except ProcessLookupError:
        pass
(state / "decode.log").unlink(missing_ok=True)

# ---- deleting and wiping report what the tool said
assert cp.delete_entry(LINES[0], run) and read_log("deleted.log") == LINES[0] + "\n", read_log("deleted.log")
flag("delete.fail")
outcome = cp.delete_entry(LINES[1], run)
assert not outcome and "cliphist" in outcome.reason and LINES[1] not in read_log("deleted.log")
flag("delete.fail", False)
assert cp.wipe(run) and read_log("wiped.log") == "wipe\n"
flag("wipe.fail")
assert not cp.wipe(run)
flag("wipe.fail", False)

# ---- previews: through thumbnail_core (T024's limits), from a private file that is always removed
try:
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf  # noqa: F401
    have_pixbuf = True
except (ImportError, ValueError):
    have_pixbuf = False
if have_pixbuf:
    (state / "entry-3").write_bytes(png(300, 200))
    r = cp.preview("3", cancel)
    assert r.status == "ok" and struct.unpack(">II", r.png[16:24])[0] <= 72 and struct.unpack(">II", r.png[16:24])[1] <= 48 and not left_over(), (r, left_over())
(state / "entry-5").write_bytes(b"not a picture at all")
r = cp.preview("5", cancel)
assert r.status == "placeholder" and not left_over(), r
r = cp.preview("77", cancel)
assert r.status == "placeholder" and "no longer" in r.reason, r
flag("decode.big")                                                        # a 40 MiB "image": refused while reading, the tool stopped, nothing left
t0 = time.monotonic()
r = cp.preview("1", cancel)
assert r.status == "placeholder" and "too large" in r.reason and time.monotonic() - t0 < 4 and not left_over(), (r, left_over())
flag("decode.big", False)
flag("decode.slow")                                                       # closing the picker stops the decoder
stop = threading.Event()
out = []
th = threading.Thread(target=lambda: out.append(cp.preview("1", stop)))
th.start()
time.sleep(0.5)
assert read_log("decode.log").startswith("start 1"), "the fake decoder was running"
stop.set()
th.join(5)
pid = int(read_log("decode.log").split()[2])
assert not th.is_alive() and out[0].status == "cancelled" and not left_over(), (out, left_over())
try:
    os.kill(pid, 0)
    raise AssertionError("the decoder child must be gone")
except ProcessLookupError:
    pass
flag("decode.slow", False)
(state / "decode.log").unlink()
print("clipboard core checks passed" + ("" if have_pixbuf else " (picture previews skipped: no GdkPixbuf for Python)"))

# ---- the window (needs GTK and a display; never shown)
if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (window checks)")
    sys.exit(0)
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
loader = importlib.machinery.SourceFileLoader("clipboard_app", str(here / "clipboard.py"))
spec = importlib.util.spec_from_loader("clipboard_app", loader)
app_mod = importlib.util.module_from_spec(spec)
loader.exec_module(app_mod)
app = Adw.Application(application_id="dev.primo.ClipboardTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
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


def titles(picker):
    return [r.entry["id"] for r in picker.rows()]


(state / "list.txt").write_text("\n".join(LINES) + "\n")
flag("list.slow")                                                         # a slow history: the window is up at once, filled when it arrives
t0 = time.monotonic()
picker = app_mod.Picker(app)
assert time.monotonic() - t0 < 0.4 and titles(picker) == [], "the window must not wait for cliphist"
assert picker.status.get_visible() and "Loading" in picker.status.get_label(), picker.status.get_label()
pump(5, until=lambda: titles(picker))
assert titles(picker) == ["1", "2", "3", "4"] and not picker.status.get_visible(), (titles(picker), picker.status.get_label())
assert max(b - a for a, b in zip(beats, beats[1:])) < 0.2, "the main loop stalled while the history was slow"
flag("list.slow", False)

# keyboard filtering still works; the selected row is the first
picker.search.set_text("https")
pump(0.2)
assert [r.entry["id"] for r in picker.visible_rows()] == ["2"]
picker.search.set_text("")

# a delete that fails keeps the row and says so; one that works removes it
flag("delete.fail")
picker.listbox.select_row(next(picker.rows()))
picker.delete_selected()
pump(3, until=lambda: "Could not delete" in picker.status.get_label())
assert titles(picker) == ["1", "2", "3", "4"] and "Could not delete" in picker.status.get_label() and picker.status.get_visible(), picker.status.get_label()
flag("delete.fail", False)
picker.delete_selected()
pump(3, until=lambda: titles(picker) == ["2", "3", "4"])
assert titles(picker) == ["2", "3", "4"] and read_log("deleted.log").endswith(LINES[0] + "\n")

# copying: the picker stays open when it fails, and closes only after it worked
closed = []
picker.close = lambda: closed.append(1)
flag("copy.fail")
picker.copy(picker.entries_by_id["2"])
pump(3, until=lambda: "Could not copy" in picker.status.get_label())
assert not closed and "Could not copy" in picker.status.get_label(), (closed, picker.status.get_label())
flag("copy.fail", False)
picker.copy(picker.entries_by_id["2"])
pump(3, until=lambda: closed)
assert closed == [1]

# Clear all asks first: Cancel runs nothing, Clear runs the wipe and closes
(state / "wiped.log").unlink(missing_ok=True)
picker.wipe_answered("cancel")
pump(0.5)
assert not read_log("wiped.log"), "cancelling the confirmation must not start a child"
picker.wipe_answered("wipe")
pump(3, until=lambda: read_log("wiped.log"))
assert read_log("wiped.log") == "wipe\n"

# a thumbnail that arrives for a row that was deleted or replaced is ignored
if have_pixbuf:
    gone = next(picker.rows())
    picker.listbox.remove(gone)
    picker.apply_thumb(gone, "3", cp.ThumbnailResult("ok", png(72, 48), ""))
    assert gone.get_parent() is None

# closing the picker while previews are decoding stops them and shows nothing afterwards
(state / "list.txt").write_text("3\t[[ binary data 12 KiB png 10x10 ]]\n")
flag("decode.slow")
picker2 = app_mod.Picker(app)
pump(2, until=lambda: read_log("decode.log"))
assert read_log("decode.log").startswith("start 3"), "the preview decoder started"
pid = int(read_log("decode.log").split()[2])
picker2.on_close_request()
pump(1.0)
try:
    os.kill(pid, 0)
    raise AssertionError("closing the picker must stop the decoder child")
except ProcessLookupError:
    pass
flag("decode.slow", False)

# an empty history and a missing tool are said in words
(state / "list.txt").write_text("")
picker3 = app_mod.Picker(app)
pump(3, until=lambda: picker3.status.get_visible() and "Loading" not in picker3.status.get_label())
assert "Nothing copied yet" in picker3.status.get_label(), picker3.status.get_label()
os.environ["PATH"] = "/nonexistent"
picker4 = app_mod.Picker(app)
pump(3, until=lambda: picker4.status.get_visible() and "Loading" not in picker4.status.get_label())
os.environ["PATH"] = saved_path
assert "cliphist is not installed" in picker4.status.get_label(), picker4.status.get_label()
assert not left_over(), left_over()
print("clipboard window checks passed (longest main-loop gap %.0f ms)" % (max(b - a for a, b in zip(beats, beats[1:])) * 1000))
