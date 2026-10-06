#!/usr/bin/env python3
"""Idle configuration checks; no desktop commands or services are started."""
from pathlib import Path
import sys
import tempfile
import json
import subprocess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "config/hypr/scripts"))
import idle_core as idle

with tempfile.TemporaryDirectory() as directory:
    idle.CONFIG = Path(directory) / "config/primo-idle.conf"
    idle.STATE = Path(directory) / "state"
    assert idle.load() == idle.DEFAULTS
    idle.save(idle.DEFAULTS)
    assert idle.load() == idle.DEFAULTS
    assert idle.CONFIG.read_text().count("listener {") == 4
    for key in idle.DEFAULTS:
        values = dict(idle.DEFAULTS, **{key: 0})
        idle.save(values)
        assert idle.load()[key] == 0
        assert idle.CONFIG.read_text().count("listener {") == 3
    idle.save(dict.fromkeys(idle.DEFAULTS, 0))
    text = idle.CONFIG.read_text()
    assert "listener {" not in text
    assert "before_sleep_cmd = loginctl lock-session" in text
    assert "lock_cmd = pidof hyprlock || hyprlock" in text
    for invalid in (-1, 1.5, True, "300"):
        try:
            idle.save(dict(idle.DEFAULTS, sleep=invalid))
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid duration accepted")
        assert idle.CONFIG.read_text() == text
    for broken in ("broken", '# Primo idle times: {"sleep": 300}\n', text + "# manual edit\n"):
        idle.CONFIG.write_text(broken)
        try:
            idle.save(idle.DEFAULTS)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError("Unrecognized config overwritten")
        assert idle.CONFIG.read_text() == broken
    # An existing service with no Primo ownership record must never be killed.
    with patch.object(idle.subprocess, "run") as run, patch.object(idle.subprocess, "Popen") as popen, patch.object(idle.signal, "pidfd_send_signal") as kill:
        run.return_value.stdout = "12345\n"
        run.return_value.returncode = 0
        try:
            idle.start(restart=True)
        except RuntimeError as error:
            assert "Log out" in str(error)
        else:
            raise AssertionError("Foreign service replaced")
        kill.assert_not_called()
        popen.assert_not_called()
    idle.CONFIG.unlink()
    idle.save(idle.DEFAULTS)
    proc = Path(directory) / "proc/43210"
    proc.mkdir(parents=True)
    (proc / "cmdline").write_bytes(b"hypridle\0-c\0" + bytes(idle.CONFIG) + b"\0")
    (proc / "stat").write_text("43210 (hypridle) " + " ".join(["S"] + ["0"] * 18 + ["123"]))
    original_path = Path
    def fake_path(value):
        return original_path(directory) / "proc" if value == "/proc" else original_path(value)
    with patch.object(idle, "Path", side_effect=fake_path), patch.object(idle.subprocess, "run") as run, patch.object(idle.subprocess, "Popen") as popen:
        run.return_value.stdout = ""
        run.return_value.returncode = 1
        popen.return_value.pid = 43210
        popen.return_value.wait.side_effect = subprocess.TimeoutExpired("hypridle", 0.3)
        idle.start()
        assert json.loads((idle.STATE / "process.json").read_text())["started"] == "123"
        idle.start()
        assert popen.call_count == 1, "Autostart must not duplicate the service"
        with patch.object(idle.os, "pidfd_open", return_value=99), patch.object(idle.os, "close"), patch.object(idle.signal, "pidfd_send_signal") as kill, patch.object(idle.select, "select", return_value=([99], [], [])):
            idle.start(restart=True)
            kill.assert_called_once_with(99, idle.signal.SIGTERM)
            assert popen.call_count == 2
        # Reused PIDs do not give permission to signal another process.
        (proc / "stat").write_text((proc / "stat").read_text().replace("123", "456"))
        run.return_value.stdout = "43210\n"
        with patch.object(idle.signal, "pidfd_send_signal") as kill:
            try:
                idle.start(restart=True)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Reused PID accepted")
            kill.assert_not_called()
print("ok: idle defaults, Never, persistence, validation, broken config and foreign process safety")
