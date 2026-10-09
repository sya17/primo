#!/usr/bin/env python3
"""Checks for the measurement helper (scripts/perf-baseline.py): /proc parsing, CPU and PSS deltas, restarted processes, unavailable counters.

Uses sample /proc text only; never measures the real machine."""
import importlib.machinery
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("perf_baseline", str(ROOT / "scripts" / "perf-baseline.py"))
spec = importlib.util.spec_from_loader("perf_baseline", loader)
pb = importlib.util.module_from_spec(spec)
loader.exec_module(pb)


def stat_line(pid, comm, utime, stime, start):
    fields = ["S", "1", "1", "1", "0", "-1", "4194560", "0", "0", "0", "0", str(utime), str(stime), "0", "0", "20", "0", "1", "0", str(start)]
    return f"{pid} ({comm}) " + " ".join(fields)


# a process name with spaces and parentheses does not shift the fields
assert pb.parse_stat(stat_line(42, "python3 (x) y", 120, 30, 9999)) == (150, 9999)
assert pb.parse_pss("Rss:   2048 kB\nPss:   1536 kB\nShared_Clean: 1 kB\n") == 1536
assert pb.parse_pss("Rss: 2048 kB\n") is None                     # no Pss line: unavailable, never zero

# which resident service a command line belongs to; anything else is not ours
assert pb.service_of("python3 /home/u/.config/hypr/scripts/hub.py --daemon") == "hub"
assert pb.service_of("/usr/bin/python3 /repo/config/hypr/scripts/launcher.py --daemon") == "launcher"
assert pb.service_of("python3 /repo/config/hypr/scripts/activity.py --top") is None     # the Waybar probe is measured separately
assert pb.service_of("vim /repo/config/hypr/scripts/hub.py") is None

# CPU relative to one logical CPU, from two samples of the same process
first = {"hub": {"pid": 10, "start": 500, "ticks": 100, "pss": 70000}}
last = {"hub": {"pid": 10, "start": 500, "ticks": 106, "pss": 70500}}
r = pb.compare(first, last, elapsed=30.0, clk=100)["hub"]
assert r["cpu_percent_one_core"] == 0.2 and r["pss_kib_start"] == 70000 and r["pss_kib_end"] == 70500 and r["identity"] == "same"

# a process that restarted (same PID reused, another start time) or went away is labelled, not averaged
r = pb.compare(first, {"hub": {"pid": 10, "start": 777, "ticks": 5, "pss": 1}}, elapsed=30.0, clk=100)["hub"]
assert r["identity"] == "restarted" and r["cpu_percent_one_core"] is None
r = pb.compare(first, {}, elapsed=30.0, clk=100)["hub"]
assert r["identity"] == "gone" and r["cpu_percent_one_core"] is None

# a PSS that could not be read stays unavailable in the totals
r = pb.compare({"a": {"pid": 1, "start": 1, "ticks": 0, "pss": None}}, {"a": {"pid": 1, "start": 1, "ticks": 0, "pss": None}}, 10.0, 100)
assert r["a"]["pss_kib_end"] is None and pb.total_pss(r) is None
assert pb.total_pss(pb.compare(first, last, 30.0, 100)) == 70500

# median and 95th percentile of a list of timings
s = pb.spread([float(n) for n in range(1, 101)])
assert s["count"] == 100 and s["median"] == 50.5 and s["p95"] == 95.05 and s["max"] == 100.0
assert pb.spread([]) == {"count": 0}

print("measurement helper checks passed")
