"""Where Primo keeps its files, and safe reading and writing of them (modes, workflow settings, hub data).

Existing settings are JSON; new hand-edited definition files are TOML (read only: Primo never rewrites them).
A file that does not parse is never thrown away by a later save: its bytes are copied to `<name>.bad-<time>` first, so a typo in a
hand-edited file cannot erase calendar links, snippets or reminders. Writes go to a temporary file that replaces the target.
A file written by a newer Primo (a `version` above SUPPORTED_VERSION) is read as defaults and never saved over.
Standard library only.
"""
import itertools
import json
import logging
import logging.handlers
import os
import stat
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

SUPPORTED_VERSION = 1


def _xdg(var, default, env=None, home=None):
    """An XDG base directory; an empty or relative value is ignored, as the specification says. `env` and `home` are for checks of another home."""
    value = (os.environ if env is None else env).get(var, "")
    return Path(value) if os.path.isabs(value) else Path(home or Path.home()) / default


def config_home(env=None, home=None):
    return _xdg("XDG_CONFIG_HOME", ".config", env, home)


def data_home(env=None, home=None):
    return _xdg("XDG_DATA_HOME", ".local/share", env, home)


def state_home(env=None, home=None):
    return _xdg("XDG_STATE_HOME", ".local/state", env, home)


# The files Primo reads: (name, base folder, path in it, kind of value). `primo config` and the Health checks list them.
FILES = [
    ("modes", "config", "primo/modes.json", list),
    ("workflow", "config", "primo/workflow.json", dict),
    ("activity", "config", "primo/activity.json", dict),
    ("hub", "data", "primo/hub.json", dict),
]


def known_files(env=None, home=None):
    """[(name, path, kind of value)] for this user (or for `home`), plus any other JSON or TOML file in the primo config folder."""
    bases = {"config": config_home(env, home), "data": data_home(env, home), "state": state_home(env, home)}
    out = [(name, bases[base] / rel, kind) for name, base, rel, kind in FILES]
    known = {p for _n, p, _k in out}
    folder = bases["config"] / "primo"
    extra = sorted(p for p in folder.glob("*") if p.suffix in (".json", ".toml") and p not in known) if folder.is_dir() else []
    return out + [(p.stem, p, (dict, list)) for p in extra]


class ConfigError(ValueError):
    """A file Primo cannot use: the path, the line and column when known, and what to do. Never quotes the file's content."""

    def __init__(self, path, problem, line=None, column=None, hint="", newer=False):
        self.path, self.problem, self.line, self.column, self.hint, self.newer = Path(path), problem, line, column, hint, newer
        self.where = f"{path}:{line}:{column}" if line and column else f"{path}:{line}" if line else str(path)
        super().__init__(f"{self.where}: {problem}" + (f" ({hint})" if hint else ""))


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


log = logging.getLogger("primo.config")
_warned = set()


def _warn(key, message):
    """One warning per problem: a resident service reads its files again and again."""
    if key not in _warned:
        _warned.add(key)
        log.warning(message)


def setup_logging(service):
    """The log of one service (call it once at start; returns its logger). `LEVEL name: message` goes to stderr, where a systemd unit
    will hand it to the journal (0.7.0). The desktop discards the stderr of what it starts today, so the same lines also go to
    <state>/hyprland-dotfiles/log/<service>.log, with a time, in at most two files of 256 KiB. Uncaught errors (a GTK callback, a worker
    thread) are logged too. PRIMO_DEBUG=1 adds debug lines."""
    root = logging.getLogger("primo")
    if root.handlers:
        return logging.getLogger(f"primo.{service}")
    root.setLevel(logging.DEBUG if os.environ.get("PRIMO_DEBUG") else logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(stream)
    try:
        folder = state_home() / "hyprland-dotfiles" / "log"
        folder.mkdir(parents=True, exist_ok=True)
        to_file = logging.handlers.RotatingFileHandler(folder / f"{service}.log", maxBytes=256 * 1024, backupCount=1, encoding="utf-8")
        to_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
        root.addHandler(to_file)
    except OSError as e:
        root.warning("no log file (%s): warnings go to stderr only", e.strerror)
    service_log = logging.getLogger(f"primo.{service}")
    sys.excepthook = lambda kind, value, tb: service_log.error("uncaught %s", kind.__name__, exc_info=(kind, value, tb))
    threading.excepthook = lambda a: service_log.error("uncaught %s in a thread", a.exc_type.__name__, exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return service_log


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
    """Replace `path` with `text` (str or bytes) through a temporary file in the same folder. A symlink is followed, not replaced.
    `mode` defaults to the permissions the file already has, or private (0600) for a new one."""
    path = Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with (os.fdopen(fd, "wb") if isinstance(text, bytes) else os.fdopen(fd, "w", encoding="utf-8")) as f:
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
