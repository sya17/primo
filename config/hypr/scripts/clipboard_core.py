"""The clipboard picker without GTK: listing the history, copying, deleting, wiping and previews, all through bounded commands.
Standard library only (previews use thumbnail_core, which keeps the picture library out of this process).

Entry ids are numbers made by cliphist and always travel as list items, never through a shell; a line that does not start with a
number is ignored, so an id can never be an option. Nothing here logs or stores what you copied."""
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import proc_core as pc
import thumbnail_core as tc
from thumbnail_core import ThumbnailRequest, ThumbnailResult  # noqa: F401  (the picker builds results of this type)

MAX_ENTRIES = 120
MAX_THUMBS = 14
COPY_DEADLINE = 10.0
COPY_LIMIT = 256 << 20                   # the largest entry copied (a preview is limited much more tightly)
DECODE_DEADLINE = 5.0
IMAGE_RE = re.compile(r"^\[\[ binary data .*(png|jpe?g|webp|gif|bmp).* \]\]$")


@dataclass
class Outcome:
    ok: bool
    reason: str = ""

    def __bool__(self):
        return self.ok


class Entries(list):
    """The entries of the history, newest first, plus how the read went: state "ok", "missing" (no cliphist), "timeout" or "error";
    `truncated` when there were more than were kept (or the output hit its cap)."""
    state = "ok"
    truncated = False


def is_image(text):
    return bool(IMAGE_RE.match(text))


def _words(run, tool):
    """What went wrong with `run`, for the person."""
    if run.reason == "missing":
        return f"{tool} is not installed"
    if run.reason == "timeout":
        return f"{tool} took too long"
    if run.reason:
        return f"{tool} was stopped ({run.reason})"
    return f"{tool}: " + (run.err.strip().splitlines() or ["failed"])[-1][:120].removeprefix(f"{tool}: ")


def list_entries(run=pc.run_bounded, cancel=None):
    """The history through `run(cmd, cancel=...)`. Never raises; `.state` says whether an empty answer is a real empty history."""
    entries = Entries()
    result = run(["cliphist", "list"], cancel=cancel)             # proc_core's cap (1 MiB) bounds the output
    if result.reason == "missing":
        entries.state = "missing"
        return entries
    if result.reason == "timeout":
        entries.state = "timeout"
        return entries
    if result.reason == "cancelled" or (result.reason != "output too large" and result.code != 0):
        entries.state = "error"
        return entries
    lines = result.out.split("\n")
    if result.reason == "output too large":
        lines = lines[:-1]                       # the last line was cut off by the cap
        entries.truncated = True
    for line in lines:
        ident, _, preview = line.partition("\t")
        if not ident.isdigit():
            continue
        if len(entries) >= MAX_ENTRIES:
            entries.truncated = True
            break
        entries.append({"line": line, "id": ident, "text": preview})
    return entries


def _decode_to_file(entry_id, dest, cancel, deadline, limit):
    """`cliphist decode ID` into the file `dest`, stopped when it runs too long, is cancelled or grows past `limit` bytes. Returns "" when it
    worked, else "cancelled", "timeout", "too large", "missing" or "failed" (the entry is gone). The data never passes through this process."""
    try:
        with open(dest, "wb") as out:
            proc = subprocess.Popen(["cliphist", "decode", str(entry_id)], stdout=out, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            end, reason = time.monotonic() + deadline, ""
            try:
                while proc.poll() is None:
                    if cancel is not None and cancel.is_set():
                        reason = "cancelled"
                    elif time.monotonic() >= end:
                        reason = "timeout"
                    elif dest.stat().st_size > limit:
                        reason = "too large"
                    if reason:
                        break
                    time.sleep(0.02)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
    except OSError:
        return "missing"
    if reason:
        return reason
    if dest.stat().st_size > limit:
        return "too large"
    return "" if proc.returncode == 0 else "failed"


def copy_entry(entry_id, cancel=None, deadline=COPY_DEADLINE):
    """Copy an entry to the clipboard. cliphist decodes it into a private file (up to 256 MiB, never through this process), and only when
    that worked does wl-copy get it as its input, so a vanished entry can never empty the clipboard. All within `deadline` seconds."""
    if not str(entry_id).isdigit():
        return Outcome(False, "not a clipboard entry")
    end = time.monotonic() + deadline
    folder = Path(tempfile.mkdtemp(prefix="primo-clip-"))
    try:
        source = folder / "entry"
        reason = _decode_to_file(entry_id, source, cancel, deadline, COPY_LIMIT)
        if reason:
            return Outcome(False, {"cancelled": "cancelled", "timeout": "copying took too long", "too large": "the entry is too large to copy",
                                   "missing": "cliphist is not installed", "failed": "the entry is no longer in the history"}[reason])
        errors = folder / "errors"
        try:
            with open(source, "rb") as data, open(errors, "wb") as err:
                # wl-copy forks a background process that keeps serving the clipboard; its own session keeps it alive after this window closes
                proc = subprocess.Popen(["wl-copy"], stdin=data, stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
                try:
                    proc.wait(timeout=max(0.1, end - time.monotonic()))
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    return Outcome(False, "copying took too long")
        except OSError:
            return Outcome(False, "wl-copy is not installed")
        if proc.returncode != 0:
            message = (errors.read_text(errors="replace").strip().splitlines() or ["failed"])[-1][:120].removeprefix("wl-copy: ")
            return Outcome(False, "wl-copy: " + message)
        return Outcome(True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def delete_entry(line, run=pc.run_bounded):
    """Remove one entry (cliphist wants its whole listing line on stdin)."""
    result = run(["cliphist", "delete"], data=(line + "\n").encode())
    return Outcome(result.ok, "" if result.ok else _words(result, "cliphist"))


def wipe(run=pc.run_bounded):
    result = run(["cliphist", "wipe"])
    return Outcome(result.ok, "" if result.ok else _words(result, "cliphist"))


def preview(entry_id, cancel):
    """A small preview of an image entry (72 x 48), or the reason there is none. The entry is decoded into a private file first, at
    most as large as a still picture may be; a bigger one is stopped while it is read. Blocks: call from a worker."""
    if not str(entry_id).isdigit():
        return ThumbnailResult("placeholder", None, "not a clipboard entry")
    folder = Path(tempfile.mkdtemp(prefix="primo-clip-"))
    try:
        source = folder / "entry"
        reason = _decode_to_file(entry_id, source, cancel, DECODE_DEADLINE, tc.MAX_INPUT_BYTES)
        if reason == "cancelled":
            return ThumbnailResult("cancelled")
        if reason:
            return ThumbnailResult("placeholder", None, {"timeout": "reading the entry took too long", "too large": "the image is too large to preview",
                                                         "missing": "cliphist is not installed", "failed": "the entry is no longer in the history"}[reason])
        return tc.render(ThumbnailRequest(source, *tc.CLIPBOARD_OUTPUT), cancel)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
