#!/usr/bin/env python3
"""Checks for thumbnail_core: previews are made by an owned child with limits on input, pixels, output, time and memory.

Synthetic pictures and fake `ffmpegthumbnailer` only. The decoding child needs python-gobject with GdkPixbuf; the checks that need it are
skipped when it is missing (the parent, which these checks mostly exercise, never imports GTK)."""
import os
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
os.environ["TMPDIR"] = str(tmp_root)          # every temporary preview file must land here, and be gone afterwards
tempfile.tempdir = str(tmp_root)              # (tempfile caches the folder at its first use, which was the line above)
bin_dir = work / "bin"
bin_dir.mkdir()
os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import thumbnail_core as tc
assert "gi" not in sys.modules, "importing the controller must not import GTK or GdkPixbuf"

try:
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf  # noqa: F401
    HAVE_PIXBUF = True
except (ImportError, ValueError):
    HAVE_PIXBUF = False


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png(width, height, colour=(200, 60, 60), declared=None):
    """A real PNG; with `declared` the header claims other dimensions (a tiny file that says it is huge)."""
    w, h = declared or (width, height)
    rows = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def size_of(data):
    return struct.unpack(">II", data[16:24])


def left_over():
    return sorted(p.name for p in tmp_root.iterdir())


def fake_ffmpeg(mode, log=None):
    """A stand-in for ffmpegthumbnailer: ok writes a small picture, slow hangs, big writes 6 MiB, fail exits 1."""
    script = bin_dir / "ffmpegthumbnailer"
    script.write_text(f'''#!/usr/bin/env python3
import sys, time, struct, zlib
a = sys.argv[1:]
out = a[a.index("-o") + 1]
size = a[a.index("-s") + 1]
open({str(log)!r}, "a").write(out + " -s " + size + "\\n") if {str(log)!r} != "None" else None
mode = {mode!r}
if mode == "slow":
    time.sleep(60)
if mode == "fail":
    sys.stderr.write("cannot decode\\n"); sys.exit(1)
if mode == "big":
    open(out, "wb").write(b"\\x89PNG" + b"0" * (6 << 20)); sys.exit(0)
def chunk(k, d): return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
rows = b"".join(b"\\x00" + bytes((20, 120, 220)) * 320 for _ in range(180))
open(out, "wb").write(b"\\x89PNG\\r\\n\\x1a\\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 180, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
''')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


cancel = threading.Event()
req = lambda path, w=420, h=250: tc.ThumbnailRequest(Path(path), w, h)

# ---- the policy is the design's
assert (tc.MAX_INPUT_BYTES, tc.MAX_PIXELS, tc.MAX_OUTPUT, tc.MAX_PNG_BYTES) == (32 << 20, 40_000_000, (900, 520), 4 << 20)
assert (tc.DECODE_DEADLINE, tc.VIDEO_DEADLINE, tc.CEILING_MIB, tc.CLIPBOARD_OUTPUT) == (5.0, 5.0, 256, (72, 48))

# ---- an encoded input over the limit is refused before anything starts
big = work / "huge.png"
with open(big, "wb") as f:
    f.truncate(tc.MAX_INPUT_BYTES + 1)
started = []
real_run = tc.pc.run_bounded
tc.pc.run_bounded = lambda *a, **k: (started.append(a), real_run(*a, **k))[1]
r = tc.render(req(big), cancel)
assert (r.status, r.png) == ("placeholder", None) and "too large" in r.reason and not started and not left_over(), (r, started, left_over())
r = tc.render(req(work / "missing.png"), cancel)
assert r.status == "placeholder" and "not found" in r.reason, r
tc.pc.run_bounded = real_run

if HAVE_PIXBUF:
    # ---- a picture: scaled to fit, as PNG, inside the request, nothing left behind
    ok = work / "ok.png"
    ok.write_bytes(png(1000, 600))
    r = tc.render(req(ok), cancel)
    assert r.status == "ok" and r.reason == "" and r.png and r.png.startswith(b"\x89PNG"), r
    w, h = size_of(r.png)
    assert w <= 420 and h <= 250 and abs(w / h - 1000 / 600) < 0.05, (w, h)
    assert not left_over(), left_over()
    r = tc.render(req(ok, 5000, 5000), cancel)                        # a request above the cap is capped at 900x520
    assert max(size_of(r.png)[0] - 900, size_of(r.png)[1] - 520) <= 0, size_of(r.png)

    # ---- a tiny file that declares huge dimensions is refused from its header, fast, without allocating the picture
    bomb = work / "bomb.png"
    bomb.write_bytes(png(8, 8, declared=(60000, 60000)))
    assert bomb.stat().st_size < 1000
    t0 = time.monotonic()
    r = tc.render(req(bomb), cancel)
    assert r.status == "placeholder" and "pixels" in r.reason and time.monotonic() - t0 < 4, (r, time.monotonic() - t0)

    # ---- malformed data
    junk = work / "junk.png"
    junk.write_bytes(b"this is not a picture" * 100)
    r = tc.render(req(junk), cancel)
    assert r.status == "placeholder" and "readable" in r.reason, r
    cut = work / "cut.png"
    cut.write_bytes(png(500, 500)[:300])
    assert tc.render(req(cut), cancel).status == "placeholder"

    # ---- the address-space ceiling: a decode that needs more memory than allowed fails by itself
    os.environ["PRIMO_THUMB_CEILING_MIB"] = "4"
    wide = work / "wide.png"
    wide.write_bytes(png(3000, 3000))
    r = tc.render(req(wide, 900, 520), cancel)
    assert r.status == "placeholder" and "memory" in r.reason, r
    os.environ["PRIMO_THUMB_CEILING_MIB"] = "off"                     # a system that cannot set the limit says so instead of pretending
    r = tc.render(req(ok), cancel)
    assert r.status == "ok" and "not enforced" in r.reason, r
    del os.environ["PRIMO_THUMB_CEILING_MIB"]

    # ---- a stuck decoder is stopped at its deadline (the decoder child is replaced by one that sleeps)
    real_cmd = tc.decoder_command
    tc.decoder_command = lambda *a: [sys.executable, "-c", "import time; time.sleep(60)"]
    tc.DECODE_DEADLINE = 0.5
    t0 = time.monotonic()
    r = tc.render(req(ok), cancel)
    assert r.status == "placeholder" and "too long" in r.reason and time.monotonic() - t0 < 3 and not left_over(), (r, left_over())
    tc.decoder_command, tc.DECODE_DEADLINE = real_cmd, 5.0

# ---- videos: a finite size is asked for, the frame goes to a path of this job only, and the files are always removed
log = work / "ffmpeg.log"
video = work / "clip.mp4"
video.write_bytes(b"not really a video")
fake_ffmpeg("ok", log)
if HAVE_PIXBUF:
    r = tc.render(req(video), cancel)
    assert r.status == "ok" and size_of(r.png)[0] <= 420 and not left_over(), (r, left_over())
    line = log.read_text().strip()
    assert line.endswith("-s 420") and "primo-thumb-" in line, line      # finite target size, a private per-job folder
    # two previews at once never share a path
    log.write_text("")
    results = []
    threads = [threading.Thread(target=lambda: results.append(tc.render(req(video), threading.Event()))) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    paths = [l.split()[0] for l in log.read_text().splitlines()]
    assert len(paths) == 2 and paths[0] != paths[1] and all(r.status == "ok" for r in results) and not left_over(), (paths, results, left_over())

fake_ffmpeg("fail")
r = tc.render(req(video), cancel)
assert r.status == "placeholder" and "video" in r.reason and not left_over(), (r, left_over())
fake_ffmpeg("big")
r = tc.render(req(video), cancel)
assert r.status == "placeholder" and "large" in r.reason and not left_over(), (r, left_over())
fake_ffmpeg("slow")
tc.VIDEO_DEADLINE = 0.5
t0 = time.monotonic()
r = tc.render(req(video), cancel)
assert r.status == "placeholder" and "too long" in r.reason and time.monotonic() - t0 < 3 and not left_over(), (r, left_over())
tc.VIDEO_DEADLINE = 5.0

# ---- cancelling stops the child and cleans up; a cancelled request is not a failure to show
stop = threading.Event()
out = []
th = threading.Thread(target=lambda: out.append(tc.render(req(video), stop)))
th.start()
time.sleep(0.4)
stop.set()
th.join(5)
assert not th.is_alive() and out[0].status == "cancelled" and not left_over(), (out, left_over())
assert tc.render(req(video), stop).status == "cancelled"

# ---- many requests through the owner: two at a time, sixteen waiting, the rest refused; leaving the page stops them all
import settings_jobs as sj
import queue
ui = queue.Queue()
owner = sj.JobOwner(lambda fn, *a: ui.put((fn, a)), workers=2, pending_limit=16)
fake_ffmpeg("slow")
tc.VIDEO_DEADLINE = 20
accepted = [owner.submit(f"wallpaper-thumb/{i}", lambda c, i=i: tc.render(req(video), c), lambda r: None) for i in range(30)]
assert accepted.count(True) == 18, accepted.count(True)
time.sleep(0.6)
live = os.popen("pgrep -fc 'bin/[f]fmpegthumbnailer'").read().strip()      # the bracket keeps pgrep from counting its own shell
assert 1 <= int(live or 0) <= 2, live
owner.invalidate_prefix("wallpaper-thumb/")
time.sleep(1.0)
assert os.popen("pgrep -fc 'bin/[f]fmpegthumbnailer'").read().strip() in ("0", ""), "children of the invalidated previews are gone"
end = time.monotonic() + 3
while owner.active and time.monotonic() < end:
    time.sleep(0.05)
assert not owner.active and not left_over(), (owner.active, left_over())
tc.VIDEO_DEADLINE = 5.0
print("thumbnail checks passed" + ("" if HAVE_PIXBUF else " (picture checks skipped: no GdkPixbuf for Python)"))
