"""What is running and what is it costing: a /proc sampler for the Activity window. Standard library only.

Everything here is measured, nothing is guessed:
  CPU, memory (PSS when readable), disk read/write and GPU time per process, summed per app;
  connections and listening ports (ss); microphone, camera, audio and screen-share use.
Per-app network *speed* is not available without root, so it is not shown.

Apps are found by walking each process up to the first "launcher" (Hyprland, systemd --user ...). A few
tools are lifted out of the terminal that started them (Dev Tool, Builder), so their helper servers
(lang-server, ...) show up under them instead of under `kitty`.
"""
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

CLK = os.sysconf("SC_CLK_TCK")
ME = os.getuid()
PROC = Path("/proc")

BOUNDARY = {"Hyprland", "systemd", "sddm-helper", "dbus-broker", "dbus-broker-lau"}
LIFT = {"devtool": "Dev Tool", "builder": "Builder"}
RENAME = {"start-hyprland": "Hyprland"}
SHELLS = {"bash", "zsh", "fish", "sh", "dash", "nu"}
TERMINALS = {"kitty", "foot", "alacritty", "wezterm-gui", "konsole", "gnome-terminal-"}
INTERPRETERS = {"python", "python3", "node", "bash", "sh", "ruby", "perl"}
# Never offered for quitting or freezing: the session would die with them.
PROTECTED = {"Hyprland", "systemd", "dbus-broker", "dbus-broker-lau", "pipewire", "pipewire-pulse", "wireplumber",
             "xdg-desktop-portal", "xdg-document-portal", "xdg-permission-store", "xdg-desktop-portal-hyprland",
             "xdg-desktop-portal-gtk", "start-hyprland", "sddm", "sddm-helper", "sddm-greeter", "login", "polkitd"}


@dataclass
class Proc:
    pid: int
    ppid: int
    comm: str
    state: str
    uid: int
    start: int
    ticks: int
    rss: int
    cmd: list
    cpu: float = 0.0
    io_r: float = 0.0
    io_w: float = 0.0
    gpu: float = 0.0
    pss: int = 0


@dataclass
class Group:
    key: str
    name: str
    kind: str                      # app | bg
    leaders: list
    pids: list = field(default_factory=list)
    cpu: float = 0.0
    mem: int = 0
    io_r: float = 0.0
    io_w: float = 0.0
    gpu: float = 0.0
    conns: int = 0
    hosts: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    windows: list = field(default_factory=list)
    doing: str = ""
    badges: list = field(default_factory=list)
    protected: bool = False
    frozen: bool = False
    tree: list = field(default_factory=list)      # (depth, Proc)
    heaviest: str = ""
    pids_procs: list = field(default_factory=list)

    @property
    def impact(self):
        return self.cpu + self.gpu


# ----------------------------------------------------------------------------- reading /proc
def read_proc(pid):
    try:
        raw = (PROC / str(pid) / "stat").read_text()
        head, _, rest = raw.rpartition(")")
        comm = head.split("(", 1)[1]
        f = rest.split()
        uid = (PROC / str(pid)).stat().st_uid
        try:
            cmd = [a for a in (PROC / str(pid) / "cmdline").read_bytes().decode(errors="replace").split("\0") if a]
        except OSError:
            cmd = []
        return Proc(pid=pid, ppid=int(f[1]), comm=comm, state=f[0], uid=uid, start=int(f[19]),
                    ticks=int(f[11]) + int(f[12]), rss=int(f[21]) * os.sysconf("SC_PAGE_SIZE"), cmd=cmd)
    except (OSError, ValueError, IndexError):
        return None


def read_io(pid):
    try:
        d = {}
        for line in (PROC / str(pid) / "io").read_text().splitlines():
            k, _, v = line.partition(":")
            d[k] = int(v)
        return d.get("read_bytes", 0), d.get("write_bytes", 0)
    except (OSError, ValueError):
        return None


def read_pss(pid):
    try:
        for line in (PROC / str(pid) / "smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def mem_info():
    d = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        d[k] = int(v.split()[0]) * 1024
    return {"total": d["MemTotal"], "used": d["MemTotal"] - d["MemAvailable"],
            "swap_total": d.get("SwapTotal", 0), "swap_used": d.get("SwapTotal", 0) - d.get("SwapFree", 0)}


def battery():
    """(status, watts or None) for the first battery, else None."""
    for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            status = (b / "status").read_text().strip()
        except OSError:
            continue
        watts = None
        try:   # the reading is refused ("No such device") on some machines while charging
            if (b / "power_now").exists():
                watts = int((b / "power_now").read_text()) / 1e6
            elif (b / "current_now").exists() and (b / "voltage_now").exists():
                watts = int((b / "current_now").read_text()) * int((b / "voltage_now").read_text()) / 1e12
        except (OSError, ValueError):
            pass
        return status, watts
    return None


def run(*cmd, timeout=4):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# ----------------------------------------------------------------------------- sampler
class Sampler:
    """Call sample() every couple of seconds; rates are measured between two calls."""

    def __init__(self, light=False):
        self.light = light    # CPU and RSS only: cheap enough for the Waybar tooltip
        self.prev = {}        # pid -> (start, ticks, io_r, io_w, gpu_ns)
        self.t = None
        self.pss = {}         # pid -> (time, bytes)
        self.fds = {}         # pid -> (time, drm fds, video?)
        self.slow = (0.0, {}, {})   # time, pid -> badges, pid -> (conns, hosts, ports)
        self.windows = {}

    def drm_fds(self, pid, now):
        cached = self.fds.get(pid)
        if cached and now - cached[0] < 30:
            return cached[1], cached[2]
        drm, video = [], False
        try:
            for fd in os.listdir(PROC / str(pid) / "fd"):
                try:
                    target = os.readlink(PROC / str(pid) / "fd" / fd)
                except OSError:
                    continue
                if target.startswith("/dev/dri/"):
                    drm.append(fd)
                elif target.startswith("/dev/video"):
                    video = True
        except OSError:
            pass
        self.fds[pid] = (now, drm, video)
        return drm, video

    def gpu_ns(self, pid, fds):
        seen, total = set(), 0
        for fd in fds:
            try:
                text = (PROC / str(pid) / "fdinfo" / fd).read_text()
            except OSError:
                continue
            m = re.search(r"drm-client-id:\s*(\d+)", text)
            if m and m.group(1) in seen:
                continue
            if m:
                seen.add(m.group(1))
            total += sum(int(x) for x in re.findall(r"drm-engine-(?:gfx|compute|enc|dec|video\S*):\s*(\d+)", text))
        return total

    def sample(self, windows=None):
        now = time.monotonic()
        dt = (now - self.t) if self.t else None
        self.t = now
        procs, current = {}, {}
        for entry in os.listdir(PROC):
            if not entry.isdigit():
                continue
            p = read_proc(int(entry))
            if p is None:
                continue
            procs[p.pid] = p
            if p.uid != ME:
                continue
            io = (0, 0) if self.light else (read_io(p.pid) or (0, 0))
            drm = [] if self.light else self.drm_fds(p.pid, now)[0]
            gpu = self.gpu_ns(p.pid, drm) if drm else 0
            current[p.pid] = (p.start, p.ticks, io[0], io[1], gpu)
            old = self.prev.get(p.pid)
            if old and old[0] == p.start and dt:
                p.cpu = (p.ticks - old[1]) / CLK / dt * 100
                p.io_r = max(0, io[0] - old[2]) / dt
                p.io_w = max(0, io[1] - old[3]) / dt
                p.gpu = max(0, gpu - old[4]) / 1e9 / dt * 100
            cached = self.pss.get(p.pid)
            if self.light:
                p.pss = p.rss
            elif cached and now - cached[0] < 6:
                p.pss = cached[1]
            else:
                val = read_pss(p.pid)
                p.pss = val if val is not None else p.rss
                self.pss[p.pid] = (now, p.pss)
        self.prev = current
        for table in (self.pss, self.fds):
            for pid in [k for k in table if k not in procs]:
                del table[pid]
        if not self.light and now - self.slow[0] > 5:
            self.slow = (now, self.badges(procs, now), self.net())
        self.windows = windows or {}
        return procs

    # microphone / camera / audio / screen share: slower, so every ~5 s
    def badges(self, procs, now):
        out = {}

        def add(pid, tag):
            out.setdefault(pid, set()).add(tag)

        for pid in procs:
            if procs[pid].uid == ME and self.fds.get(pid) and self.fds[pid][2]:
                add(pid, "camera")
        try:
            src = json.loads(run("pactl", "--format=json", "list", "source-outputs") or "[]")
            for s in src:
                pid = s.get("properties", {}).get("application.process.id")
                if pid and not s.get("corked") and not str(s.get("source", "")).endswith(".monitor"):
                    add(int(pid), "microphone")
            snk = json.loads(run("pactl", "--format=json", "list", "sink-inputs") or "[]")
            for s in snk:
                pid = s.get("properties", {}).get("application.process.id")
                if pid and not s.get("corked"):
                    add(int(pid), "audio")
        except (ValueError, TypeError):
            pass
        try:
            for node in json.loads(run("pw-dump") or "[]"):
                props = node.get("info", {}).get("props", {})
                if props.get("media.class") == "Stream/Input/Video" and props.get("application.process.id"):
                    add(int(props["application.process.id"]), "screen")
        except (ValueError, TypeError):
            pass
        return out

    def net(self):
        conns = {}
        for line in run("ss", "-H", "-tunp", "state", "established").splitlines():
            m = re.search(r"pid=(\d+)", line)
            cols = line.split()
            if m and len(cols) >= 4:
                c = conns.setdefault(int(m.group(1)), [0, set(), set()])
                c[0] += 1
                c[1].add(cols[3].rsplit(":", 1)[0])
        for line in run("ss", "-H", "-tlnp").splitlines():
            m = re.search(r"pid=(\d+)", line)
            cols = line.split()
            if m and len(cols) >= 4:
                c = conns.setdefault(int(m.group(1)), [0, set(), set()])
                c[2].add(cols[3].rsplit(":", 1)[1])
        return conns


# ----------------------------------------------------------------------------- grouping
def helper_name(cmd):
    text = " ".join(cmd)
    if "lang-server" in text:
        return "lang-server"
    m = re.search(r"plugins/cache/[^/]+/([^/]+)/", text)
    if m and ("helper" in text.lower() or "--stdio" in text):
        return m.group(1)
    for a in cmd[1:]:
        if "helper" in a.lower() and not a.startswith("-") and "=" not in a:
            return Path(a).stem
    return None


def script_name(p):
    """A friendlier name than 'python3' for a script."""
    if len(p.comm) >= 15 and p.cmd and p.comm not in INTERPRETERS:   # the kernel cuts comm at 15 characters
        return Path(p.cmd[0].split()[0]).name
    if p.comm in INTERPRETERS and len(p.cmd) > 1:
        for a in p.cmd[1:]:
            if not a.startswith("-"):
                return Path(a).name
    return p.comm


def leader_of(pid, procs):
    chain = [pid]
    while procs[chain[-1]].ppid in procs and procs[procs[chain[-1]].ppid].comm not in BOUNDARY:
        chain.append(procs[chain[-1]].ppid)
    for q in chain:                                # nearest lifted ancestor wins
        if procs[q].comm in LIFT:
            return q
    return chain[-1]


def children_map(procs):
    kids = {}
    for p in procs.values():
        kids.setdefault(p.ppid, []).append(p.pid)
    return kids


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def group_apps(procs, sampler, windows):
    """windows: pid -> list of {class, title, address, workspace}. Returns a list of Group, heaviest first."""
    mine = {pid: p for pid, p in procs.items() if p.uid == ME}
    kids = children_map(mine)
    groups = {}
    leader_group = {}
    for pid in mine:
        lead = leader_of(pid, mine)
        leader_group.setdefault(lead, []).append(pid)
    own = os.getpid()
    for lead, pids in leader_group.items():
        lp = mine[lead]
        wins = [w for pid in pids for w in windows.get(pid, [])]
        if lp.comm in LIFT:
            name, kind = LIFT[lp.comm], "app"
        elif wins:
            name, kind = wins[0]["class"], "app"
        else:
            name, kind = RENAME.get(script_name(lp), script_name(lp)), "bg"
        # Apps merge by name (all kitty windows). Background programs merge only when the command is identical,
        # so quitting "sleep" never reaches an unrelated sleep elsewhere.
        key = name.lower() if kind == "app" else f"{name.lower()}|{' '.join(lp.cmd)}"
        g = groups.setdefault(key, Group(key=key, name=name, kind=kind, leaders=[]))
        if kind == "app":
            g.kind = "app"
        g.leaders.append(lead)
        g.pids.extend(pids)
        g.windows.extend(wins)
        g.protected = g.protected or lp.comm in PROTECTED or own in pids
    conns = sampler.slow[2]
    badges = sampler.slow[1]
    for g in groups.values():
        hosts, ports, bset = set(), set(), set()
        for pid in g.pids:
            p = mine[pid]
            g.cpu += p.cpu
            g.mem += p.pss
            g.io_r += p.io_r
            g.io_w += p.io_w
            g.gpu += p.gpu
            if pid in conns:
                g.conns += conns[pid][0]
                hosts |= conns[pid][1]
                ports |= conns[pid][2]
            bset |= badges.get(pid, set())
        g.hosts, g.ports = sorted(hosts), sorted(ports, key=int)
        g.frozen = all(mine[pid].state == "T" for pid in g.pids)
        g.badges = [b for b in ("microphone", "camera", "screen", "audio") if b in bset]
        if g.frozen:
            g.badges.append("frozen")
        # tree for the expanded view
        for lead in g.leaders:
            def walk(pid, depth):
                g.tree.append((depth, mine[pid]))
                for k in sorted(kids.get(pid, []), key=lambda x: -mine[x].pss):
                    if leader_of(k, mine) == lead or k in g.pids:
                        walk(k, depth + 1)
            walk(lead, 0)
        g.pids_procs = [mine[pid] for pid in g.pids]
        g.tree = g.tree[:60]
        top = max((mine[pid] for pid in g.pids), key=lambda p: p.pss)
        # only worth naming when it is a helper, not the app's own main process
        g.heaviest = f"{script_name(top)} {fmt_bytes(top.pss)}" if len(g.pids) > 1 and top.pid not in g.leaders else ""
        g.doing = describe(g, mine)
    return sorted(groups.values(), key=lambda g: -(g.impact * 1000 + g.mem / 1e6))


def describe(g, mine):
    if g.name in LIFT.values():
        helper = {}
        for pid in g.pids:
            n = helper_name(mine[pid].cmd)
            # count servers, not their helper processes: only the topmost process of each one
            if n and mine[pid].comm not in LIFT and helper_name(mine.get(mine[pid].ppid, mine[pid]).cmd if mine[pid].ppid in mine else []) != n:
                helper[n] = helper.get(n, 0) + 1
        sessions = len(g.leaders)
        text = f"{sessions} session{'s' if sessions != 1 else ''}"
        if helper:
            text += " · helper: " + ", ".join(f"{n} ×{c}" if c > 1 else n for n, c in sorted(helper.items()))
        return text
    if g.windows:
        title = g.windows[0]["title"] or ""
        extra = f" (+{len(g.windows) - 1} windows)" if len(g.windows) > 1 else ""
        if g.name.lower() in TERMINALS or any(mine[l].comm in TERMINALS for l in g.leaders):
            running = sorted({script_name(mine[pid]) for pid in g.pids
                              if mine[pid].comm not in SHELLS and mine[pid].comm not in TERMINALS | {"kitten"}})
            if running:
                return "Running: " + ", ".join(running[:3])
        if g.heaviest and len(g.pids) > 3:
            return f"{title[:60]}{extra} · heaviest: {g.heaviest}" if title else f"{len(g.pids)} processes · heaviest: {g.heaviest}"
        return f"{title[:70]}{extra}" if title else f"{len(g.pids)} processes"
    lead = mine[g.leaders[0]]
    text = " ".join(lead.cmd).replace(str(Path.home()), "~")[:90] if lead.cmd else lead.comm
    if len(g.pids) > 1:
        return f"{len(g.pids)} processes · {text}"
    return text


def headline(groups):
    """One plain sentence about the heaviest thing right now, computed from the measurements."""
    if not groups:
        return "Nothing to show"
    top = max(groups, key=lambda g: g.impact)
    if top.impact < 8:
        return "All quiet"
    bits = [f"{top.cpu:.0f}% CPU"]
    if top.gpu >= 5:
        bits.append(f"{top.gpu:.0f}% GPU")
    bits.append(fmt_bytes(top.mem))
    hot = max((p for p in top.pids_procs), key=lambda p: p.cpu, default=None) if hasattr(top, "pids_procs") else None
    inner = f" (mostly {script_name(hot)})" if hot and hot.pid not in top.leaders and hot.cpu > top.cpu / 2 else ""
    return f"Busiest: {top.name}{inner} · " + " · ".join(bits)


# ----------------------------------------------------------------------------- actions
def verify(p_sample):
    """True when the pid still is the same process we sampled (guards against pid reuse) and is ours."""
    cur = read_proc(p_sample.pid)
    return cur is not None and cur.start == p_sample.start and cur.comm == p_sample.comm and cur.uid == ME


def signal_group(group, sig, only_leaders=False):
    """Send sig to the verified processes of a group. Returns how many were signalled."""
    if group.protected:
        return 0
    n = 0
    members = {p.pid: p for _d, p in group.tree}
    targets = [members[l] for l in group.leaders if l in members] if only_leaders else list(members.values())
    for p in targets:
        if verify(p):
            try:
                os.kill(p.pid, sig)
                n += 1
            except OSError:
                pass
    return n


# ----------------------------------------------------------------------------- services
def services(user):
    """Running services (and their MainPID) plus timers, via systemctl."""
    base = ["systemctl", "--user"] if user else ["systemctl"]
    try:
        units = json.loads(run(*base, "list-units", "--type=service", "--state=running", "--output=json", "--no-pager") or "[]")
    except ValueError:
        units = []
    units = [u for u in units if not u["unit"].startswith("dbus-:")]
    names = [u["unit"] for u in units]
    info = {}
    if names:
        out = run(*base, "show", "-p", "Id", "-p", "MainPID", "-p", "ActiveEnterTimestamp", *names)
        for block in out.strip().split("\n\n"):
            d = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
            if "Id" in d:
                info[d["Id"]] = d
    rows = [{"unit": u["unit"], "description": u.get("description", ""),
             "pid": int(info.get(u["unit"], {}).get("MainPID", 0) or 0),
             "since": info.get(u["unit"], {}).get("ActiveEnterTimestamp", "")} for u in units]
    try:
        timers = json.loads(run(*base, "list-timers", "--all", "--output=json", "--no-pager") or "[]")
    except ValueError:
        timers = []
    return rows, timers
