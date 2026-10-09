"""Run an external command with a deadline, an output cap and a cancel switch, and always reap it. Standard library only.

Every tool that asks the system a question from a window (hyprctl, nmcli, pactl, cliphist) goes through run_bounded, so a slow or
stuck program can neither freeze a window nor outlive its owner. The child is stopped through its own handle, never by name.
"""
import os
import selectors
import subprocess
import time
from dataclasses import dataclass

DEADLINE = 3.0
CAP = 1 << 20          # stdout and stderr together


@dataclass
class Run:
    code: int = None   # the exit code; None when it never ran or was stopped
    out: str = ""
    err: str = ""
    reason: str = ""   # "", "timeout", "cancelled", "missing" or "output too large"

    @property
    def ok(self):
        return self.code == 0 and not self.reason


def run_bounded(cmd, deadline=DEADLINE, cap=CAP, cancel=None, env=None):
    """Run `cmd` (a list); returns a Run. `cancel` is a threading.Event; `env` is added to this process's environment."""
    if cancel is not None and cancel.is_set():
        return Run(reason="cancelled")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                env={**os.environ, **env} if env else None)
    except OSError:
        return Run(reason="missing")
    chunks = {proc.stdout: [], proc.stderr: []}
    size, reason, end = 0, "", time.monotonic() + deadline
    with selectors.DefaultSelector() as sel:
        for pipe in chunks:
            sel.register(pipe, selectors.EVENT_READ)
        while sel.get_map():
            if cancel is not None and cancel.is_set():
                reason = "cancelled"
            elif time.monotonic() >= end:
                reason = "timeout"
            elif size >= cap:
                reason = "output too large"
            if reason:
                break
            for key, _ in sel.select(0.05):
                data = os.read(key.fd, 65536)
                if data:
                    chunks[key.fileobj].append(data)
                    size += len(data)
                else:
                    sel.unregister(key.fileobj)
    if reason:
        proc.kill()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:     # a process that ignores SIGKILL for two seconds is not ours to wait for
        reason = reason or "timeout"
    for pipe in chunks:
        pipe.close()
    text = lambda pipe: b"".join(chunks[pipe]).decode(errors="replace")
    return Run(None if reason else proc.returncode, text(proc.stdout), text(proc.stderr), reason)
