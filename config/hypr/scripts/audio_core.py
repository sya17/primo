"""Audio devices for the Settings page, without GTK: read the state with `pactl`, change one thing at a time by device name.
Standard library only. Primo keeps no copy of the audio state: every answer comes from the sound server, and a change is always
followed by a fresh read by the caller.

`run(argv)` is a bounded command runner (settings_jobs.Budget or proc_core.run_bounded): it returns a proc_core.Run.
A device is identified by its name (stable), never by its label (two devices can share one) or its position."""
import json
import re
import threading
from dataclasses import dataclass, field

KINDS = {"sink": "output", "source": "input"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9_][^\s;|&$`'\"\\<>]*$")      # a device name never starts with "-" and never needs a shell


class AudioError(Exception):
    """The audio state could not be read; the message says why in words for the page."""


@dataclass
class Device:
    name: str
    label: str
    kind: str                  # "sink" (output) or "source" (input)
    volume: float              # percent of the loudest channel; may be above 100
    muted: bool


@dataclass
class AudioSnapshot:
    outputs: list = field(default_factory=list)
    inputs: list = field(default_factory=list)
    default_output: str = None
    default_input: str = None


@dataclass
class Outcome:
    ok: bool
    reason: str = ""

    def __bool__(self):
        return self.ok


def _why(result, tool="pactl"):
    if result.reason == "missing":
        return f"{tool} is not installed"
    if result.reason == "timeout":
        return "the audio server took too long to answer"
    if result.reason:
        return f"{tool} was stopped ({result.reason})"
    text = (result.err.strip().splitlines() or ["failed"])[-1]
    if "Connection" in text or "refused" in text:
        return "the audio server is not running"
    return text.removeprefix("Failure: ")[:120]


def _percent(device):
    values = []
    for channel in (device.get("volume") or {}).values():
        match = re.match(r"\s*(\d+)", str(channel.get("value_percent", "")))
        if match:
            values.append(float(match.group(1)))
    return max(values) if values else 0.0


def _devices(run, group):
    result = run(["pactl", "--format=json", "list", group])
    if not result.ok:
        raise AudioError(_why(result))
    try:
        listing = json.loads(result.out or "[]")
    except ValueError:
        raise AudioError("pactl printed something that is not JSON") from None
    kind = "sink" if group == "sinks" else "source"
    devices = []
    for d in listing:
        if kind == "source" and d.get("monitor_source"):
            continue                                       # what a speaker plays, not a microphone
        if isinstance(d, dict) and d.get("name"):
            devices.append(Device(d["name"], d.get("description") or d["name"], kind, _percent(d), bool(d.get("mute"))))
    return devices


def _default(run, which):
    result = run(["pactl", f"get-default-{which}"])
    return (result.out.strip() or None) if result.ok else None


def snapshot(run):
    """Everything the Audio page shows. Raises AudioError (server missing or not running, tool missing, too slow)."""
    outputs = _devices(run, "sinks")
    inputs = _devices(run, "sources")
    return AudioSnapshot(outputs, inputs, _default(run, "sink"), _default(run, "source"))


def _present(run, kind, name):
    """Re-read the devices of this kind: is `name` still there? Returns an Outcome (ok) or the reason it is not."""
    if kind not in KINDS:
        return Outcome(False, "not an audio device kind")
    if not isinstance(name, str) or not SAFE_NAME.match(name):
        return Outcome(False, "not a valid device name")
    try:
        found = any(d.name == name for d in _devices(run, "sinks" if kind == "sink" else "sources"))
    except AudioError as error:
        return Outcome(False, str(error))
    return Outcome(True) if found else Outcome(False, f"that {KINDS[kind]} device is no longer there")


def _apply(run, argv):
    result = run(argv)
    return Outcome(result.ok, "" if result.ok else _why(result))


def set_default(kind, name, run):
    check = _present(run, kind, name)
    return check if not check else _apply(run, ["pactl", f"set-default-{kind}", name])


def set_volume(kind, name, percent, run):
    check = _present(run, kind, name)
    if not check:
        return check
    return _apply(run, ["pactl", f"set-{kind}-volume", name, f"{max(0, min(100, int(percent)))}%"])


def set_mute(kind, name, muted, run):
    check = _present(run, kind, name)
    return check if not check else _apply(run, ["pactl", f"set-{kind}-mute", name, "1" if muted else "0"])


class VolumeCoalescer:
    """A slider fires many values. One change per device runs at a time; while it runs only the newest value for that device waits.
    `apply(kind, name, percent, run)` is the real change (set_volume); `wait` is for tests and shutdown."""

    def __init__(self, apply, run, on_result=None):
        self.apply, self.run, self.on_result = apply, run, on_result
        self.lock = threading.Lock()
        self.latest = {}          # (kind, name) -> percent waiting
        self.running = set()
        self.idle = threading.Event()
        self.idle.set()

    def change(self, kind, name, percent):
        key = (kind, name)
        with self.lock:
            self.latest[key] = percent
            if key in self.running:
                return
            self.running.add(key)
            self.idle.clear()
        threading.Thread(target=self._work, args=(key,), name="audio-volume", daemon=True).start()

    def _work(self, key):
        while True:
            with self.lock:
                percent = self.latest.pop(key, None)
                if percent is None:
                    self.running.discard(key)
                    if not self.running:
                        self.idle.set()
                    return
            outcome = self.apply(key[0], key[1], percent, self.run)
            if self.on_result:
                self.on_result(key, percent, outcome)

    def wait(self, timeout=5):
        return self.idle.wait(timeout)
