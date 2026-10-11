"""Network facts for the Settings page, without GTK: what NetworkManager reports, read with `nmcli` in the C locale with explicit fields.
Standard library only. Primo keeps no copy: every answer comes from NetworkManager. Never asks for secrets and never prints one.

Identity: an access point is its interface plus its BSSID (the SSID is only a name: two radios or two networks can share one, and a
hidden network has none); a saved profile is its UUID. `run(argv, env=...)` is a bounded runner returning a proc_core.Run."""
import os
import re
from dataclasses import dataclass, field

ENV = {"LC_ALL": "C"}
UUID = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
BSSID = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
WAIT = "60"                                                           # seconds nmcli waits for an activation; the caller's deadline is a little longer
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
    advice: str = ""           # "editor": needs the advanced connection editor; "agent": needs a program that asks for the password

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


# ----------------------------------------------------------------------------- changes
def _words(result):
    """NetworkManager's refusal in words for the person, and what could help."""
    if result.reason == "timeout":
        return "NetworkManager is taking too long to finish. What is shown is the real state.", ""
    if result.reason == "missing":
        return "nmcli is not installed", ""
    if result.reason:
        return f"nmcli was stopped ({result.reason})", ""
    text = (result.err.strip().splitlines() or ["nmcli failed"])[-1].removeprefix("Error: ")
    low = text.lower()
    if "secrets were required" in low or "no secrets" in low:
        return ("The network needs a password and none was given. Start a program that can ask for it (nm-applet) and try again, "
                "or use Advanced setup."), "agent"
    if "not authorized" in low or "not authorised" in low or "permission" in low:
        return "You do not have permission to change the network from here.", ""
    if "timeout expired" in low:
        return "The connection took too long (60 seconds).", ""
    if "no carrier" in low:
        return "The cable is not connected (no carrier).", ""
    if "no suitable device" in low:
        return "No device can make this connection right now.", ""
    return text[:140], ""


def _apply(run, argv):
    result = run(argv, env=ENV)
    if result.ok:
        return Outcome(True)
    reason, advice = _words(result)
    return Outcome(False, reason, advice)


def _interface_ok(snap, interface, kinds=("wifi", "ethernet")):
    return isinstance(interface, str) and bool(IFACE.match(interface)) and any(d.name == interface and d.kind in kinds for d in snap.devices)


def _fresh(run):
    try:
        return snapshot(run), None
    except NetworkError as error:
        return None, Outcome(False, str(error))


def activate_saved(uuid, interface, run):
    """Bring up a saved Wi-Fi or wired profile on an interface, by its UUID. A VPN profile is not touched from here."""
    snap, error = _fresh(run)
    if error:
        return error
    if not isinstance(uuid, str) or not UUID.match(uuid) or not any(c.uuid == uuid for c in snap.connections):
        return Outcome(False, "that saved connection is no longer there")
    if not _interface_ok(snap, interface):
        return Outcome(False, "that network device is no longer there")
    return _apply(run, ["nmcli", "--wait", WAIT, "connection", "up", "uuid", uuid, "ifname", interface])


def connect_ap(interface, bssid, run):
    """Connect to a network that is in the list (no password handling: NetworkManager asks its own program when one is needed)."""
    snap, error = _fresh(run)
    if error:
        return error
    ap = next((a for a in snap.access_points if a.interface == interface and a.bssid == str(bssid).upper()), None) \
        if isinstance(bssid, str) and BSSID.match(bssid.upper()) else None
    if ap is None or not _interface_ok(snap, interface, ("wifi",)):
        return Outcome(False, "that network is no longer in the list")
    if "802.1X" in ap.security or "EAP" in ap.security:
        return Outcome(False, "This network needs company or school sign-in settings. Use Advanced setup.", "editor")
    return _apply(run, ["nmcli", "--wait", WAIT, "device", "wifi", "connect", ap.bssid, "ifname", interface, "bssid", ap.bssid])


def disconnect(interface, run):
    snap, error = _fresh(run)
    if error:
        return error
    if not _interface_ok(snap, interface):
        return Outcome(False, "that network device is no longer there")
    return _apply(run, ["nmcli", "device", "disconnect", interface])


def set_wifi(enabled, run):
    if not isinstance(enabled, bool):
        return Outcome(False, "not a valid Wi-Fi state")
    return _apply(run, ["nmcli", "radio", "wifi", "on" if enabled else "off"])
