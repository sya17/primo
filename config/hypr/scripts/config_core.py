"""Safe reading and writing of the JSON files Primo keeps for you (modes, workflow settings, hub data).

A file that does not parse is never thrown away by a later save: its bytes are copied to `<name>.bad-<time>` first, so a typo in a
hand-edited file cannot erase calendar links, snippets or reminders. Writes go to a temporary file that replaces the target.
Standard library only.
"""
import itertools
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path


def _load(path, expect):
    """(data, b"") for a good file; (None, raw) when it has content that is unusable; (None, b"") when there is nothing to lose.
    Any error other than "not there" is raised: a file we cannot read must not be saved over."""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return None, b""
    if not raw.strip():
        return None, b""
    try:
        data = json.loads(raw)
    except ValueError:
        return None, raw
    return (data, b"") if isinstance(data, expect) else (None, raw)


def preserve(path, raw):
    """Keep `raw` next to `path` as `<name>.bad-<time>` (private, never overwritten); the same bytes are kept once. Returns the copy."""
    path = Path(path)
    for old in path.parent.glob(path.name + ".bad-*"):
        try:
            if old.read_bytes() == raw:
                return old
        except OSError:
            pass
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for n in itertools.count():
        copy = path.with_name(f"{path.name}.bad-{stamp}" + (f"-{n}" if n else ""))
        try:
            fd = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        return copy


_warned = set()


def _warn(key, message):
    """One line on stderr, once per problem: a resident service reads its files again and again."""
    if key not in _warned:
        _warned.add(key)
        print("primo: " + message, file=sys.stderr)


def read_json(path, expect, default):
    """The file's value when it is a good `expect` (dict or list); otherwise `default`, with a warning when there was something in the file."""
    path = Path(path)
    try:
        data, raw = _load(path, expect)
    except OSError as e:
        _warn((path, e.errno), f"cannot read {path} ({e.strerror}); using defaults, and it will not be saved over")
        return default
    if data is not None:
        return data
    if raw and (path, raw) not in _warned:
        try:
            kept = f"a copy is kept as {preserve(path, raw).name}"
        except OSError as e:
            kept = f"no copy could be made ({e.strerror}), so it will not be saved over"
        _warn((path, raw), f"{path} is not a valid {expect.__name__} of settings; {kept}; defaults are used")
    return default


def atomic_write(path, text, mode=None):
    """Replace `path` with `text` through a temporary file in the same folder. A symlink is followed, not replaced.
    `mode` defaults to the permissions the file already has, or private (0600) for a new one."""
    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, data, mode=None):
    """Save `data` atomically. If the file now on disk is one we cannot use, it is copied aside first; when that is not possible, nothing is written."""
    text = json.dumps(data, indent=1, ensure_ascii=False)
    _, raw = _load(path, type(data))
    if raw:
        preserve(path, raw)
    atomic_write(path, text, mode)
