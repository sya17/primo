#!/usr/bin/env python3
"""Measure Primo's resident services and two busy paths, for before/after comparisons on the same machine. Opt-in and read-only.

    scripts/perf-baseline.py idle [--seconds 300] [--every 5]   CPU (relative to one logical CPU) and PSS of the resident services,
                                                                plus the Waybar probe `activity.py --top` timed on its own
    scripts/perf-baseline.py activity [--expire 31]             the Activity collector: cold, warm, and after its 5/6/30 s caches expire
    scripts/perf-baseline.py launcher [--count 30]              launcher input-to-result latency: one call of launcher_core.collect()
                                                                per typed query (no window, no file search, no painting)
    scripts/perf-baseline.py files                              the launcher's file search in your home folder: time until the
                                                                result is delivered, CPU of the find children, children started

Prints JSON on stdout and writes nothing. Records the source revision, whether the tree has uncommitted changes, the machine, and which
Primo windows were open (counts only). Never records window titles, command lines or file names: only the names of Primo's services.
A counter that cannot be read is null ("unavailable"), never zero. Timing comparisons only mean something on the same machine and workload.
"""
import argparse
import json
import os
import re
import resource
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "config" / "hypr" / "scripts"
SERVICES = ("launcher", "switcher", "overview", "hub", "activity")
SERVICE_RX = re.compile(r"(?:^|/)python3?\S*\s+\S*scripts/(" + "|".join(SERVICES) + r")\.py\s+--daemon\b")
CLK = os.sysconf("SC_CLK_TCK")
QUERIES = ["f", "fi", "fir", "fire", "firef", "set", "sett", "setti", "settings", "12*3", "sqrt(16)", "ws ", "ws 2", "theme ", "theme du",
           "win ", "win k", "term", "termi", "termin", "night", "colour", "lock", "health", "note", "mode", "time", "rem", "remind", "calendar"]


# ----------------------------------------------------------------------------- parsing (tested in scripts/test-perf.py)
def parse_stat(text):
    """(utime + stime ticks, start time) from /proc/<pid>/stat; the name in parentheses may hold spaces and parentheses."""
    fields = text[text.rindex(")") + 2:].split()
    return int(fields[11]) + int(fields[12]), int(fields[19])


def parse_pss(text):
    m = re.search(r"^Pss:\s+(\d+) kB", text, re.M)
    return int(m.group(1)) if m else None


def service_of(cmdline):
    m = SERVICE_RX.search(cmdline)
    return m.group(1) if m else None


def compare(first, last, elapsed, clk=CLK):
    """Per service: CPU % of one logical CPU between two samples, PSS at both ends, and whether it is the same process."""
    out = {}
    for name, a in first.items():
        b = last.get(name)
        identity = "gone" if b is None else "same" if (b["pid"], b["start"]) == (a["pid"], a["start"]) else "restarted"
        cpu = round((b["ticks"] - a["ticks"]) / clk / elapsed * 100, 3) if identity == "same" else None
        out[name] = {"identity": identity, "cpu_percent_one_core": cpu, "pss_kib_start": a["pss"], "pss_kib_end": b["pss"] if b else None}
    return out


def total_pss(result):
    values = [r["pss_kib_end"] for r in result.values()]
    return None if not values or None in values else sum(values)


def spread(values):
    if not values:
        return {"count": 0}
    return {"count": len(values), "median": round(statistics.median(values), 3),
            "p95": round(statistics.quantiles(values, n=20, method="inclusive")[-1], 3) if len(values) > 1 else round(values[0], 3),
            "max": round(max(values), 3)}


# ----------------------------------------------------------------------------- reading the machine
def read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return None


def services_now():
    out, me = {}, os.getuid()
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if d.stat().st_uid != me:
                continue
            name = service_of((d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace"))
        except OSError:
            continue
        stat = read(d / "stat")
        if not name or stat is None:
            continue
        ticks, start = parse_stat(stat)
        rollup = read(d / "smaps_rollup")
        out[name] = {"pid": int(d.name), "start": start, "ticks": ticks, "pss": parse_pss(rollup) if rollup else None}
    return out


def context():
    def run(*cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=4, cwd=ROOT).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    cpu = re.search(r"^model name\s*:\s*(.+)$", read("/proc/cpuinfo") or "", re.M)
    mem = re.search(r"^MemTotal:\s+(\d+) kB", read("/proc/meminfo") or "", re.M)
    try:
        open_windows = sum(1 for c in json.loads(run("hyprctl", "clients", "-j") or "[]") if str(c.get("class", "")).startswith("dev.primo."))
    except ValueError:
        open_windows = None
    power = read("/sys/class/power_supply/AC/online") or read("/sys/class/power_supply/ACAD/online")
    return {"revision": run("git", "rev-parse", "--short", "HEAD"), "uncommitted_changes": bool(run("git", "status", "--porcelain")),
            "cpu": cpu.group(1) if cpu else None, "logical_cpus": os.cpu_count(), "mem_kib": int(mem.group(1)) if mem else None,
            "kernel": os.uname().release, "python": sys.version.split()[0], "on_ac_power": None if power is None else power.strip() == "1",
            "primo_windows_open": open_windows, "taken": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def timed(fn):
    """(result, wall ms, own CPU ms, children CPU ms) of one call."""
    own0, kids0, t0 = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN), time.perf_counter()
    result = fn()
    t1, own1, kids1 = time.perf_counter(), resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = lambda a, b: round(((b.ru_utime - a.ru_utime) + (b.ru_stime - a.ru_stime)) * 1000, 2)
    return result, round((t1 - t0) * 1000, 2), cpu(own0, own1), cpu(kids0, kids1)


# ----------------------------------------------------------------------------- the three workloads
def cmd_idle(args):
    first, t0 = services_now(), time.monotonic()
    samples = [{"t": 0.0, "pss_kib": {n: s["pss"] for n, s in first.items()}}]
    while time.monotonic() - t0 < args.seconds:
        time.sleep(min(args.every, max(0.0, args.seconds - (time.monotonic() - t0))))
        now = services_now()
        samples.append({"t": round(time.monotonic() - t0, 1), "pss_kib": {n: s["pss"] for n, s in now.items()}})
    last, elapsed = services_now(), time.monotonic() - t0
    result = compare(first, last, elapsed)
    probe = []
    for _ in range(3):      # the Waybar tooltip runs this every 30 seconds as its own short-lived process
        _r, wall, _own, kids = timed(lambda: subprocess.run([sys.executable, str(SCRIPTS / "activity.py"), "--top"], capture_output=True, timeout=10))
        probe.append({"wall_ms": wall, "cpu_ms_including_children": kids})
    return {"workload": "idle", "seconds": round(elapsed, 1), "every": args.every, "services": result, "total_pss_kib_end": total_pss(result),
            "missing_services": [s for s in SERVICES if s not in first], "pss_over_time": samples, "waybar_activity_top": probe}


def cmd_activity(args):
    sys.path.insert(0, str(SCRIPTS))
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()     # no per-machine activity.json: the same workload everywhere
    import activity_collect as ac
    sampler = ac.Sampler()

    def collect():
        procs = sampler.sample()
        return len(ac.group_apps(procs, sampler, {}))       # window titles are not queried: compositor time is not included
    runs = []
    for label, wait in (("cold", 0), ("warm", 0.2), ("warm", 0.2), ("caches expired", args.expire)):
        time.sleep(wait)
        groups, wall, own, kids = timed(collect)
        runs.append({"run": label, "wall_ms": wall, "cpu_ms": own, "children_cpu_ms": kids, "groups": groups})
    return {"workload": "activity collection (Sampler.sample + group_apps, no window lookup)", "runs": runs,
            "processes_visible": sum(1 for d in os.listdir("/proc") if d.isdigit())}


def cmd_launcher(args):
    sys.path.insert(0, str(SCRIPTS))
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()      # history of a fresh profile, so ranking is the same everywhere
    import launcher_core as lc
    ctx = lc.Context(facts=lc.Facts())
    queries = (QUERIES * (args.count // len(QUERIES) + 1))[:args.count]
    walls = [timed(lambda q=q: lc.collect(q, ctx))[1] for q in queries]
    return {"workload": "launcher input-to-result: start = collect(query) called, end = it returns; providers only (no applications list, "
                        "no window, no file search, no painting); system facts cached by the launcher for 1-30 s",
            "first_call_ms": walls[0] if walls else None, "next_calls_ms": spread(walls[1:])}


FILE_QUERIES = ["readme", "config", "zzqx-no-such-name", "notes", "png"]


def cmd_files(args):
    sys.path.insert(0, str(SCRIPTS))
    import launcher_core as lc
    runs = []
    for q in FILE_QUERIES:
        done = threading.Event()
        got = []
        search = lc.FileSearch(lambda _t, hits: (got.append(len(hits)), done.set()))
        started = []
        real_start = search._start
        search._start = lambda cmd: started.append(1) or real_start(cmd)
        _r, wall, _own, kids = timed(lambda: (search.search(q), done.wait(10)))
        runs.append({"query_length": len(q), "wall_ms": wall, "children_cpu_ms": kids, "results": got[0] if got else None, "children": len(started)})
    return {"workload": "launcher file search: FileSearch.search(query) until the result is delivered (results counted, never listed)", "runs": runs}


def main(argv=None):
    p = argparse.ArgumentParser(prog="perf-baseline.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("idle")
    sp.add_argument("--seconds", type=float, default=300)
    sp.add_argument("--every", type=float, default=5)
    sp.set_defaults(fn=cmd_idle)
    sp = sub.add_parser("activity")
    sp.add_argument("--expire", type=float, default=31, help="seconds to wait before the last run, longer than the 30 s cache")
    sp.set_defaults(fn=cmd_activity)
    sp = sub.add_parser("launcher")
    sp.add_argument("--count", type=int, default=30)
    sp.set_defaults(fn=cmd_launcher)
    sub.add_parser("files").set_defaults(fn=cmd_files)
    args = p.parse_args(argv)
    print(json.dumps({"context": context(), **args.fn(args)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
