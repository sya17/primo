"""Where Primo keeps its files, and safe reading and writing of them (modes, workflow settings, hub data).

Existing settings are JSON; new hand-edited definition files are TOML (read only: Primo never rewrites them).
A file that does not parse is never thrown away by a later save: its bytes are copied to `<name>.bad-<time>` first, so a typo in a
hand-edited file cannot erase calendar links, snippets or reminders. Writes go to a temporary file that replaces the target.
A file written by a newer Primo (a `version` above SUPPORTED_VERSION) is read as defaults and never saved over.
Standard library only.
"""
import itertools
import json
import os
import stat
import sys
import tempfile
import time
import tomllib
from pathlib import Path

SUPPORTED_VERSION = 1


def _xdg(var, default):
    """An XDG base directory; an empty or relative value is ignored, as the specification says."""
    value = os.environ.get(var, "")
    return Path(value) if os.path.isabs(value) else Path.home() / default


def config_home():
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_home():
    return _xdg("XDG_DATA_HOME", ".local/share")


def state_home():
    return _xdg("XDG_STATE_HOME", ".local/state")


class ConfigError(ValueError):
    """A file Primo cannot use: the path, the line and column when known, and what to do. Never quotes the file's content."""

    def __init__(self, path, problem, line=None, column=None, hint="", newer=False):
        self.path, self.problem, self.line, self.column, self.hint, self.newer = Path(path), problem, line, column, hint, newer
        where = f"{path}:{line}:{column}" if line and column else f"{path}:{line}" if line else str(path)
        super().__init__(f"{where}: {problem}" + (f" ({hint})" if hint else ""))


def _parse(path, raw, expect):
    """The value in `raw`, or ConfigError."""
    try:
        data = tomllib.loads(raw.decode()) if path.suffix == ".toml" else json.loads(raw)
    except UnicodeDecodeError:
        raise ConfigError(path, "is not UTF-8 text", hint="save it as UTF-8") from None
    except ValueError as e:      # json.JSONDecodeError and tomllib.TOMLDecodeError
        raise ConfigError(path, getattr(e, "msg", "does not parse"), getattr(e, "lineno", None), getattr(e, "colno", None),
                          "fix that line, or move the file away to start from the defaults") from None
    if not isinstance(data, expect):
        raise ConfigError(path, f"must hold a {'list' if expect is list else 'table of settings'}, not a {type(data).__name__}")
    version = data.get("version", SUPPORTED_VERSION) if isinstance(data, dict) else SUPPORTED_VERSION
    if not isinstance(version, int) or version > SUPPORTED_VERSION:
        raise ConfigError(path, f"was written by a newer Primo (version {version!r})", hint="update Primo", newer=True)
    return data


def load(path, expect=dict):
    """Strict read, for validation: the value, None when the file is absent or empty, or ConfigError."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ConfigError(path, f"cannot be read ({e.strerror})", hint="check its owner and permissions") from None
    return _parse(path, raw, expect) if raw.strip() else None


def _load(path, expect):
    """(data, b"") for a good file; (None, raw) when it has content that is unusable; (None, b"") when there is nothing to lose.
    Any error other than "not there" is raised, and so is a file from a newer Primo: neither may be saved over."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, b""
    if not raw.strip():
        return None, b""
    try:
        return _parse(path, raw, expect), b""
    except ConfigError as e:
        if e.newer:
            raise
        return None, raw


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
    except ConfigError as e:
        _warn((path, "newer"), f"{e}; using defaults, and it will not be saved over")
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
