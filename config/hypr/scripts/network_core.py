"""Network facts for the Settings page, without GTK: what NetworkManager reports, read with `nmcli` in the C locale with explicit fields.
Standard library only. Primo keeps no copy: every answer comes from NetworkManager. Never asks for secrets and never prints one.

Identity: an access point is its interface plus its BSSID (the SSID is only a name: two radios or two networks can share one, and a
hidden network has none); a saved profile is its UUID. `run(argv, env=...)` is a bounded runner returning a proc_core.Run."""
import os
import re
from dataclasses import dataclass, field

ENV = {"LC_ALL": "C"}
IFACE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.:@-]{0,31}$")        # an interface name never starts with "-"
AGENTS = {"nm-applet", "nm-tray", "plasma-nm", "gnome-shell"}        # programs that can ask for a Wi-Fi password


class NetworkError(Exception):
    """The network state could not be read; the message says why in words for the page."""


@dataclass
class Device:
    name: str
    kind: str          # "wifi", "ethernet", ...
    state: str
    connection: str


@dataclass
class AccessPoint:
    interface: str
    bssid: str
    ssid: str          # "" for a hidden network
    security: str      # "" for an open network
    signal: int
    active: bool


@dataclass
class Connection:
    uuid: str
    name: str
    kind: str          # "wifi" or "wired"
    interface: str     # "" when the profile is not active
    active: bool


@dataclass
class NetworkSnapshot:
    wifi_enabled: bool
    access_points: list = field(default_factory=list)
    connections: list = field(default_factory=list)
    devices: list = field(default_factory=list)
    wifi_interfaces: list = field(default_factory=list)


@dataclass
class Outcome:
    ok: bool
    reason: str = ""

    def __bool__(self):
        return self.ok


def split_terse(line):
    """Split one line of `nmcli -t` output: fields are separated by ":", and ":" and "\\" inside a field are escaped with "\\"."""
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]


def _why(result):
    if result.reason == "missing":
        return "nmcli is not installed"
    if result.reason == "timeout":
        return "NetworkManager took too long to answer"
    if result.reason:
        return f"nmcli was stopped ({result.reason})"
    text = (result.err.strip().splitlines() or ["nmcli failed"])[-1]
    return text.removeprefix("Error: ")[:140]


def _nmcli(run, *args):
    result = run(["nmcli", *args], env=ENV)
    if not result.ok:
        raise NetworkError(_why(result))
    return result.out


def snapshot(run):
    """The Network page's facts. Never scans: the list is what NetworkManager already knows (`--rescan no`). Raises NetworkError."""
    radio = _nmcli(run, "-t", "-f", "WIFI", "general").strip() == "enabled"
    devices = []
    for line in _nmcli(run, "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status").splitlines():
        f = split_terse(line)
        if len(f) >= 4 and f[1] in ("wifi", "ethernet"):
            devices.append(Device(f[0], f[1], f[2], f[3]))
    wifi = [d.name for d in devices if d.kind == "wifi"]
    aps = []
    if radio and wifi:
        for line in _nmcli(run, "-t", "-f", "IN-USE,BSSID,SSID,SECURITY,SIGNAL,DEVICE", "device", "wifi", "list", "--rescan", "no").splitlines():
            f = split_terse(line)
            if len(f) < 6 or not f[1]:
                continue
            aps.append(AccessPoint(f[5], f[1].upper(), f[2], "" if f[3] in ("", "--") else f[3], int(f[4]) if f[4].isdigit() else 0, f[0].strip() == "*"))
        aps.sort(key=lambda a: (not a.active, -a.signal))
    connections = []
    for line in _nmcli(run, "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show").splitlines():
        f = split_terse(line)
        kind = {"802-11-wireless": "wifi", "802-3-ethernet": "wired"}.get(f[2]) if len(f) >= 4 else None
        if kind:                                       # VPN and WireGuard profiles live on the VPN page
            connections.append(Connection(f[1], f[0], kind, f[3], bool(f[3])))
    return NetworkSnapshot(radio, aps, connections, devices, wifi)


def rescan(interface, run):
    """Ask NetworkManager to scan on one Wi-Fi interface (the page's Refresh button). The interface must be a Wi-Fi device it reports."""
    if not isinstance(interface, str) or not IFACE.match(interface):
        return Outcome(False, "not a network interface")
    try:
        known = _nmcli(run, "-t", "-f", "DEVICE,TYPE", "device", "status").splitlines()
    except NetworkError as error:
        return Outcome(False, str(error))
    if not any(split_terse(l)[:2] == [interface, "wifi"] for l in known):
        return Outcome(False, "that Wi-Fi device is no longer there")
    result = run(["nmcli", "device", "wifi", "rescan", "ifname", interface], env=ENV)
    return Outcome(result.ok, "" if result.ok else _why(result))


def secret_agent_running(proc="/proc"):
    """Is a program running that can ask for a Wi-Fi password? Looks only at process names."""
    try:
        for entry in os.listdir(proc):
            if entry.isdigit():
                try:
                    with open(os.path.join(proc, entry, "comm")) as f:
                        if f.read().strip() in AGENTS:
                            return True
                except OSError:
                    continue
    except OSError:
        pass
    return False
