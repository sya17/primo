"""Run external commands with a deadline, an output cap and a cancel switch, and always reap them. Standard library only.

Every tool that asks the system a question or changes something from a window (hyprctl, nmcli, pactl, cliphist, wl-copy) goes through
here, so a slow or stuck program can neither freeze a window nor outlive its owner. A child is stopped through its own handle, never by name.
"""
import os
import selectors
import signal
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


def _supervise(procs, outputs, stdin, data, deadline, cap, cancel):
    """Drive already started programs until their outputs end or a limit is reached; always leaves them stopped and reaped, and the
    pipes closed. `outputs` are the pipes to collect, `stdin` the pipe to feed `data` to (or None). Returns (reason, {pipe: [chunks]})."""
    chunks = {pipe: [] for pipe in outputs}
    size, reason, end = 0, "", time.monotonic() + deadline
    pending = memoryview(data) if data is not None and stdin is not None else None
    try:
        with selectors.DefaultSelector() as sel:
            for pipe in outputs:
                sel.register(pipe, selectors.EVENT_READ)
            if pending is not None:
                os.set_blocking(stdin.fileno(), False)
                sel.register(stdin, selectors.EVENT_WRITE)
            elif stdin is not None:
                stdin.close()
            while True:
                if cancel is not None and cancel.is_set():
                    reason = "cancelled"
                elif time.monotonic() >= end:
                    reason = "timeout"
                elif size >= cap:
                    reason = "output too large"
                elif not sel.get_map() and all(p.poll() is not None for p in procs):
                    break              # every pipe is closed and every program is gone: done
                if reason:
                    break
                for key, _ in sel.select(0.05):
                    if key.fileobj is stdin:
                        try:
                            pending = pending[os.write(stdin.fileno(), pending[:65536]):]
                        except BlockingIOError:
                            continue
                        except OSError:            # the program closed its input: nothing more to give it
                            pending = pending[len(pending):]
                        if not len(pending):
                            sel.unregister(stdin)
                            stdin.close()
                        continue
                    data_in = os.read(key.fd, 65536)
                    if data_in:
                        chunks[key.fileobj].append(data_in)
                        size += len(data_in)
                    else:
                        sel.unregister(key.fileobj)
    finally:
        for proc in procs:
            try:
                os.killpg(proc.pid, signal.SIGKILL)   # its own group (run_bounded starts a new session): helpers it started go too
            except OSError:
                if proc.poll() is None:
                    proc.kill()
            proc.wait()                # SIGKILL cannot be ignored: this returns, and the child is reaped
        for pipe in list(outputs) + ([stdin] if stdin is not None else []):
            pipe.close()
    return reason, chunks


def _text(chunks, pipe):
    return b"".join(chunks[pipe]).decode(errors="replace")


def run_bounded(cmd, deadline=DEADLINE, cap=CAP, cancel=None, env=None, data=None):
    """Run `cmd` (a list); returns a Run. `cancel` is a threading.Event; `env` is added to this process's environment; `data` (bytes) is
    given to the program on its standard input."""
    if cancel is not None and cancel.is_set():
        return Run(reason="cancelled")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                env={**os.environ, **env} if env else None, start_new_session=True)
    except OSError:
        return Run(reason="missing")
    reason, chunks = _supervise([proc], [proc.stdout, proc.stderr], proc.stdin, data, deadline, cap, cancel)
    return Run(None if reason else proc.returncode, _text(chunks, proc.stdout), _text(chunks, proc.stderr), reason)
