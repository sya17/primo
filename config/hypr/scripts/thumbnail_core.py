"""Previews of pictures, GIFs and videos for Settings (and later the clipboard), made by an owned child under limits. Standard library only:
the picture library (GdkPixbuf) is imported only in the child, so a stuck or hostile file can be stopped without touching the window.

`render(ThumbnailRequest, cancel)` returns a ThumbnailResult: status "ok" with PNG bytes, "placeholder" with the reason (shown to the person),
or "cancelled". Limits (the 0.4 design): an encoded picture of at most 32 MiB; a header that declares at most 40 million pixels, checked
before the picture is decoded; a preview of at most 900 x 520 (the clipboard uses 72 x 48) and 4 MiB of PNG; 5 seconds for the decoder and
5 for a video helper; and the decoder child may use 256 MiB more address space than it had after its imports (where the system lets it
set that; when not, the result says so in `reason`). Videos go through ffmpegthumbnailer at a finite size. Every job works in its own
private folder, which is always removed.
"""
import os
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import proc_core as pc

MAX_INPUT_BYTES = 32 << 20
MAX_PIXELS = 40_000_000
MAX_OUTPUT = (900, 520)
CLIPBOARD_OUTPUT = (72, 48)
MAX_PNG_BYTES = 4 << 20
DECODE_DEADLINE = 5.0
VIDEO_DEADLINE = 5.0
CEILING_MIB = 256
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}
NOT_ENFORCED = "address-space limit not enforced"


@dataclass(frozen=True)
class ThumbnailRequest:
    path: Path
    width: int
    height: int


@dataclass
class ThumbnailResult:
    status: str                # "ok", "placeholder" or "cancelled"
    png: bytes = None
    reason: str = ""           # why there is no preview; for "ok" only a limit that could not be enforced


def _placeholder(reason):
    return ThumbnailResult("placeholder", None, reason)


def decoder_command(src, dst, width, height):
    return [sys.executable, str(Path(__file__).resolve()), "--decode", str(src), str(dst), str(width), str(height)]


def render(request, cancel):
    """A preview of `request.path` no larger than the request (and 900 x 520), or the reason there is none. Blocks: call from a worker."""
    if cancel.is_set():
        return ThumbnailResult("cancelled")
    path = Path(request.path)
    try:
        info = path.stat()
    except OSError:
        return _placeholder("file not found")
    if not stat.S_ISREG(info.st_mode):
        return _placeholder("not a file")
    video = path.suffix.lower() in VIDEO_EXTS
    if not video and info.st_size > MAX_INPUT_BYTES:
        return _placeholder("file too large to preview")
    width, height = min(max(request.width, 1), MAX_OUTPUT[0]), min(max(request.height, 1), MAX_OUTPUT[1])
    folder = Path(tempfile.mkdtemp(prefix="primo-thumb-"))        # private (0700) and this job's alone
    try:
        source = path
        if video:
            frame = folder / "frame.png"
            run = pc.run_bounded(["ffmpegthumbnailer", "-i", str(path), "-o", str(frame), "-s", str(max(width, height)), "-q", "6"],
                                 deadline=VIDEO_DEADLINE, cap=64 << 10, cancel=cancel, env={"TMPDIR": str(folder)})
            if run.reason == "cancelled":
                return ThumbnailResult("cancelled")
            if run.reason == "missing":
                return _placeholder("ffmpegthumbnailer is not installed")
            if run.reason == "timeout":
                return _placeholder("the video took too long to read")
            if run.reason or run.code != 0 or not frame.is_file():
                return _placeholder("the video frame could not be read")
            if frame.stat().st_size > MAX_PNG_BYTES:
                return _placeholder("the video frame is too large")
            source = frame
        out = folder / "preview.png"
        # TMPDIR points into this job's folder: the picture library (glycin) leaves temporary files when it is stopped, and they go with it
        run = pc.run_bounded(decoder_command(source, out, width, height), deadline=DECODE_DEADLINE, cap=64 << 10, cancel=cancel,
                             env={"TMPDIR": str(folder)})
        if run.reason == "cancelled":
            return ThumbnailResult("cancelled")
        if run.reason == "timeout":
            return _placeholder("the picture took too long to decode")
        if run.reason:
            return _placeholder(f"the picture could not be decoded ({run.reason})")
        if run.code is not None and run.code < 0:                    # killed by a signal: what a refused allocation does in C code
            return _placeholder("the decoder stopped, most likely out of memory")
        if run.code != 0:
            return _placeholder((run.err.strip().splitlines() or ["the picture is not readable"])[-1][:120])
        if not out.is_file() or out.stat().st_size > MAX_PNG_BYTES:
            return _placeholder("the preview is too large")
        return ThumbnailResult("ok", out.read_bytes(), NOT_ENFORCED if NOT_ENFORCED in run.out else "")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# ----------------------------------------------------------------------------- the decoding child
def _limit_memory():
    """Cap the address space at CEILING_MIB above what this process uses now. Returns "" or NOT_ENFORCED."""
    setting = os.environ.get("PRIMO_THUMB_CEILING_MIB", "")        # a check can ask for a tiny ceiling, or for "off" (unsupported)
    try:
        import resource
        if setting == "off":
            raise ValueError("pretend this system cannot limit memory")
        ceiling = int(setting) if setting else CEILING_MIB
        with open("/proc/self/status") as f:
            used_kib = next(int(line.split()[1]) for line in f if line.startswith("VmSize:"))
        resource.setrlimit(resource.RLIMIT_AS, (used_kib * 1024 + (ceiling << 20), resource.RLIM_INFINITY))
        return ""
    except (ImportError, OSError, ValueError, StopIteration):
        return NOT_ENFORCED


def _fail(code, message):
    sys.stderr.write(message + "\n")
    sys.exit(code)


def _decode(src, dst, width, height):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    note = _limit_memory()
    try:
        found = GdkPixbuf.Pixbuf.get_file_info(src)                # the header only: no picture is decoded yet
    except GLib.Error:
        found = None
    if not found or not found[0]:
        _fail(3, "the picture is not readable")
    if found[1] * found[2] > MAX_PIXELS:
        _fail(2, f"the picture has too many pixels ({found[1]} x {found[2]})")
    try:
        pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(src, width, height, True)   # size-aware: loaders that can scale while decoding do
        pix.savev(dst, "png", [], [])
    except MemoryError:
        _fail(5, "the picture needs more memory than allowed")
    except GLib.Error:
        _fail(3, "the picture is not readable")
    if os.path.getsize(dst) > MAX_PNG_BYTES:
        _fail(4, "the preview is too large")
    if note:
        sys.stdout.write(note)


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--decode":
        _decode(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
    else:
        sys.exit("usage: thumbnail_core.py --decode SOURCE DESTINATION WIDTH HEIGHT (used by Settings)")
