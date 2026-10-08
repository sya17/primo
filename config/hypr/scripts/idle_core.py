"""Idle preferences and the hypridle process started by Primo."""
import fcntl
import json
import os
from pathlib import Path
import signal
import select
import subprocess
import sys

import config_core as cc

DEFAULTS = {"dim": 150, "lock": 300, "screen": 330, "sleep": 1800}
CONFIG = cc.config_home() / "hypr" / "primo-idle.conf"
STATE = cc.state_home() / "hyprland-dotfiles" / "idle"
BASE = Path(__file__).resolve().parents[1] / "hypridle.conf"


def render(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS) or any(type(v) is not int or v < 0 for v in values.values()):
        raise ValueError("Idle times must be nonnegative whole seconds")
    text = "# Primo idle times: " + json.dumps(values, sort_keys=True) + "\n"
    text += '''general {
    lock_cmd = pidof hyprlock || hyprlock
    before_sleep_cmd = loginctl lock-session
    after_sleep_cmd = hyprctl dispatch 'hl.dsp.dpms({ action = "on" })'
}
'''
    commands = {
        "dim": ("brightnessctl -s set 10%", "brightnessctl -r"),
        "lock": ("loginctl lock-session", None),
        "screen": ('''hyprctl dispatch 'hl.dsp.dpms({ action = "off" })' ''',
                   '''hyprctl dispatch 'hl.dsp.dpms({ action = "on" })' '''),
        "sleep": ("systemctl suspend", None),
    }
    for key in DEFAULTS:
        seconds = values[key]
        if seconds:
            timeout, resume = commands[key]
            text += f"\nlistener {{\n    timeout = {seconds}\n    on-timeout = {timeout.strip()}\n"
            if resume:
                text += f"    on-resume = {resume.strip()}\n"
            text += "}\n"
    return text


def load():
    try:
        text = CONFIG.read_text()
    except FileNotFoundError:
        return DEFAULTS.copy()
    prefix = "# Primo idle times: "
    if not text.startswith(prefix):
        raise ValueError("Unrecognized Primo idle config; restore or rename primo-idle.conf first")
    values = json.loads(text.splitlines()[0][len(prefix):])
    if render(values) != text:
        raise ValueError("Primo idle config was edited manually; restore or rename it first")
    return values


def save(values):
    text = render(values)
    if CONFIG.exists():
        load()  # Do not overwrite a configuration we cannot understand.
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(CONFIG)


def start(restart=False):
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = STATE / "process.json"
        try:
            data = json.loads(record.read_text())
            pid = data["pid"]
            if type(pid) is not int or pid <= 0:
                raise ValueError("Invalid idle process record")
            # The config path can change after the first Apply.
            proc = Path("/proc") / str(pid)
            args = proc.joinpath("cmdline").read_bytes().split(b"\0")
            expected = [b"hypridle", b"-c", os.fsencode(data["config"]), b""]
            if proc.stat().st_uid != os.getuid() or args != expected:
                raise ValueError("Unrecognized idle process")
            if proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19] != data["started"]:
                raise ValueError("Stale idle process record")
        except (OSError, ValueError, KeyError, TypeError):
            pid = None
        if pid is not None:
            if not restart:
                return
            descriptor = os.pidfd_open(pid)
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                if not select.select([descriptor], [], [], 2)[0]:
                    raise RuntimeError("Idle service did not stop; try Apply again")
            finally:
                os.close(descriptor)
        # An older session may have started hypridle directly. Leave it to the user.
        others = subprocess.run(["pgrep", "-x", "-u", str(os.getuid()), "hypridle"], capture_output=True, text=True)
        if others.returncode not in (0, 1):
            raise RuntimeError("Cannot check the existing idle service")
        if any(int(p) != pid for p in others.stdout.split()):
            raise RuntimeError("Saved. Log out and back in to replace the existing idle service")
        config = CONFIG if CONFIG.exists() else BASE
        with (STATE / "hypridle.log").open("a") as log:
            process = subprocess.Popen(["hypridle", "-c", str(config)], stdout=log, stderr=log, start_new_session=True)
            try:
                process.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                proc = Path("/proc") / str(process.pid)
                started = proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
                record.write_text(json.dumps({"pid": process.pid, "started": started, "config": str(config)}))
                return
            raise RuntimeError(f"Idle service failed to start. See {STATE / 'hypridle.log'}")


if __name__ == "__main__":
    try:
        start(restart="--restart" in sys.argv)
    except (OSError, ValueError, RuntimeError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
