#!/usr/bin/env python3
"""Checks for modes: what starting and ending one does, with a recording runner instead of the real system."""
import os
import subprocess
import sys
import tempfile

work = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(work, "config")
os.environ["XDG_STATE_HOME"] = os.path.join(work, "state")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import modes_core as mc

calls = []
def run(cmd, **kw):
    calls.append(cmd)
    out = {"powerprofilesctl get": "balanced\n", "swaync-client -D": "false\n", "nmcli -t -f NAME connection show --active": "wifi\n"}.get(" ".join(cmd[:4]) if cmd[0] == "nmcli" else " ".join(cmd[:2]), "")
    return subprocess.CompletedProcess(cmd, 0, out, "")

assert mc.expand("code {dir}", "/p/my proj") == "code '/p/my proj'"
assert mc.expand("code {dir}", None) == "code" and mc.expand("kitty --directory {dir}", None) == "kitty"
modes = mc.load_modes()
assert [m["id"] for m in modes] == ["work", "research", "writing", "relax"]     # starting points on first use

work_mode = dict(mc.get_mode("work"), vpn="office")
st = mc.start(work_mode, "/tmp", run=run, running=[{"class": "com.microsoft.VSCode"}], now=1000.0)
flat = [" ".join(c) for c in calls]
assert any(c.startswith("nmcli --wait 1 connection up id office") for c in flat), flat
assert any(c == "powerprofilesctl set performance" for c in flat) and st["power_was"] == "balanced"
assert any(c == "swaync-client -dn" for c in flat) and st["dnd_set"]
assert any("kitty --directory /tmp" in c and "workspace = \"1 silent\"" in c for c in flat), flat
assert not any("code /tmp" in c for c in flat), "an app that is already open must not be started again"
assert any("focus-start" in c and "Work · tmp|Work" in c for c in flat)
assert mc.current()["name"] == "Work" and mc.project_dirs()[0] == "/tmp"

calls.clear(); mc.end(run=run); flat = [" ".join(c) for c in calls]
assert "powerprofilesctl set balanced" in flat and "swaync-client -df" in flat and "nmcli connection down id office" in flat
assert any("focus-end" in c for c in flat) and mc.current() is None
assert mc.end(run=run) is None                                                  # ending twice is harmless

calls.clear(); relax = mc.get_mode("relax"); mc.start(relax, run=run, running=[])
assert not any(c[0] in ("nmcli", "powerprofilesctl") for c in calls) and mc.current()["name"] == "Relax"
calls.clear(); mc.start(mc.get_mode("writing"), run=run, running=[])             # starting another ends the first
assert mc.current()["name"] == "Writing"
print("mode checks passed")
