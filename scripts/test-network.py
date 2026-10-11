#!/usr/bin/env python3
"""Checks for network_core (the Network facts of Settings) through a fake `nmcli`: parsing of escaped fields, identity of networks,
refresh without scanning, failures in words. Nothing here touches a real network, and no SSID of the user's is used."""
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp())
bin_dir = work / "bin"
bin_dir.mkdir()
state = work / "state.json"
os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
os.environ["FAKE_NMCLI"] = str(state)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import network_core as nc
import proc_core as pc

FAKE = """#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_NMCLI"]
st = json.load(open(path))
a = sys.argv[1:]
open(path + ".log", "a").write(" ".join(a) + "\\n")
if os.environ.get("LC_ALL") != "C":
    sys.stderr.write("LC_ALL must be C\\n"); sys.exit(9)
if st.get("down"):
    sys.stderr.write("Error: NetworkManager is not running.\\n"); sys.exit(8)
text = " ".join(a)
if a[:3] == ["-t", "-f", "WIFI"]: print(st["radio"])
elif "device status" in text: sys.stdout.write(st["devices"])
elif "device wifi list" in text:
    if "--rescan" not in a or a[a.index("--rescan") + 1] != "no":
        open(path + ".scan", "a").write("scan\\n")
    sys.stdout.write(st["aps"])
elif "connection show" in text: sys.stdout.write(st["connections"])
elif "device wifi rescan" in text:
    open(path + ".scan", "a").write("scan " + a[-1] + "\\n")
    if st.get("rescan_fail"): sys.stderr.write("Error: Scanning not allowed immediately following previous scan.\\n"); sys.exit(1)
"""
(bin_dir / "nmcli").write_text(FAKE)
(bin_dir / "nmcli").chmod((bin_dir / "nmcli").stat().st_mode | stat.S_IEXEC)


def put(**kw):
    base = {"radio": "enabled", "devices": "", "aps": "", "connections": ""}
    base.update(kw)
    state.write_text(json.dumps(base))
    for suffix in (".log", ".scan"):
        Path(str(state) + suffix).write_text("")


def log():
    return Path(str(state) + ".log").read_text().splitlines()


def scans():
    return Path(str(state) + ".scan").read_text().splitlines()


run = lambda argv, **k: pc.run_bounded(argv, deadline=3, **k)

# ---- the terse splitter: ":" and "\\" are escaped in nmcli's output
assert nc.split_terse(r"a:b\:c:d\\e:") == ["a", "b:c", "d\\e", ""]
assert nc.split_terse("") == [""] and nc.split_terse("x") == ["x"]
assert nc.split_terse(r"AA\:BB\:CC\:DD\:EE\:01:Café ☕:WPA2") == ["AA:BB:CC:DD:EE:01", "Café ☕", "WPA2"]

# ---- a snapshot: two radios of one SSID stay two networks; hidden, colon and backslash names; the active one first
put(radio="enabled",
    devices="wlan0:wifi:connected:Home\\:Net\nwlan1:wifi:disconnected:\nenp1s0:ethernet:connected:Wired one\nlo:loopback:connected (externally):lo\np2p-dev-wlan0:wifi-p2p:disconnected:\n",
    aps=("*:AA\\:BB\\:CC\\:DD\\:EE\\:01:Home\\:Net:WPA2:71:wlan0\n"
         " :AA\\:BB\\:CC\\:DD\\:EE\\:02:Home\\:Net:WPA2:88:wlan0\n"
         " :11\\:22\\:33\\:44\\:55\\:66::WPA2:40:wlan0\n"
         " :77\\:88\\:99\\:AA\\:BB\\:CC:Open Cafe:--:55:wlan0\n"
         " :DD\\:DD\\:DD\\:DD\\:DD\\:DD:Back\\\\slash:WPA3:62:wlan1\n"),
    connections=("Home\\:Net:aaaaaaaa-0000-0000-0000-000000000001:802-11-wireless:wlan0\n"
                 "Old Cafe:aaaaaaaa-0000-0000-0000-000000000002:802-11-wireless:\n"
                 "Wired one:aaaaaaaa-0000-0000-0000-000000000003:802-3-ethernet:enp1s0\n"
                 "Work VPN:aaaaaaaa-0000-0000-0000-000000000004:vpn:\n"
                 "WG:aaaaaaaa-0000-0000-0000-000000000005:wireguard:\n"
                 "lo:aaaaaaaa-0000-0000-0000-000000000006:loopback:lo\n"))
snap = nc.snapshot(run)
assert snap.wifi_enabled is True
assert [(a.interface, a.bssid) for a in snap.access_points] == [("wlan0", "AA:BB:CC:DD:EE:01"), ("wlan0", "AA:BB:CC:DD:EE:02"), ("wlan1", "DD:DD:DD:DD:DD:DD"),
                                                                 ("wlan0", "77:88:99:AA:BB:CC"), ("wlan0", "11:22:33:44:55:66")], snap.access_points
first = snap.access_points[0]
assert first.active and first.ssid == "Home:Net" and first.security == "WPA2" and first.signal == 71, first
assert [a.signal for a in snap.access_points[1:]] == sorted([a.signal for a in snap.access_points[1:]], reverse=True), "the rest is by signal"
bssids = [a.bssid for a in snap.access_points]
assert len(bssids) == len(set((a.interface, a.bssid) for a in snap.access_points)) == 5, "no network is merged with another"
assert {a.ssid for a in snap.access_points} >= {"Home:Net", "", "Open Cafe", "Back\\slash"}
open_net = next(a for a in snap.access_points if a.ssid == "Open Cafe")
assert open_net.security == "" and next(a for a in snap.access_points if a.ssid == "").ssid == ""
assert [(c.name, c.kind, c.active) for c in snap.connections] == [("Home:Net", "wifi", True), ("Old Cafe", "wifi", False), ("Wired one", "wired", True)], snap.connections
assert snap.connections[0].uuid == "aaaaaaaa-0000-0000-0000-000000000001" and snap.connections[0].interface == "wlan0" and snap.connections[1].interface == ""
assert snap.wifi_interfaces == ["wlan0", "wlan1"] and [d.name for d in snap.devices] == ["wlan0", "wlan1", "enp1s0"], (snap.wifi_interfaces, snap.devices)
assert any("--rescan no" in l for l in log()) and not scans(), "a normal refresh never asks for a scan"
assert all(c.kind in ("wifi", "wired") for c in snap.connections), "VPN has its own page"

# ---- radio off, nothing around, no Wi-Fi hardware
put(radio="disabled", devices="enp1s0:ethernet:connected:Wired\n", aps="", connections="Wired:aaaaaaaa-0000-0000-0000-000000000003:802-3-ethernet:enp1s0\n")
snap = nc.snapshot(run)
assert snap.wifi_enabled is False and snap.access_points == [] and snap.wifi_interfaces == [] and len(snap.connections) == 1
put(devices="", aps="", connections="")
snap = nc.snapshot(run)
assert snap.access_points == [] and snap.connections == [] and snap.devices == []

# ---- NetworkManager not running, nmcli missing, too slow: errors in words, never an empty list
state.write_text(json.dumps({"down": True}))
try:
    nc.snapshot(run)
    raise AssertionError("must be an error")
except nc.NetworkError as e:
    assert "NetworkManager is not running" in str(e), str(e)
saved = os.environ["PATH"]
os.environ["PATH"] = "/nonexistent"
try:
    nc.snapshot(lambda argv, **k: pc.run_bounded(argv, **k))
    raise AssertionError("must be an error")
except nc.NetworkError as e:
    assert "nmcli is not installed" in str(e), str(e)
os.environ["PATH"] = saved
try:
    nc.snapshot(lambda argv, **k: pc.Run(reason="timeout"))
    raise AssertionError("must be an error")
except nc.NetworkError as e:
    assert "took too long" in str(e)

# ---- the commands are what the design says: explicit fields, C locale (the fake exits 9 otherwise), no secrets anywhere
put(devices="wlan0:wifi:connected:x\n", aps=" :AA\\:AA\\:AA\\:AA\\:AA\\:AA:Net:WPA2:50:wlan0\n", connections="")
nc.snapshot(run)
joined = "\n".join(log())
assert "-f IN-USE,BSSID,SSID,SECURITY,SIGNAL,DEVICE" in joined and "password" not in joined.lower() and "--show-secrets" not in joined

# ---- an explicit scan: only for a Wi-Fi interface that exists, never an option
out = nc.rescan("wlan0", run)
assert out and scans() == ["scan wlan0"], scans()
put(devices="wlan0:wifi:connected:x\nenp1s0:ethernet:connected:y\n")
assert not nc.rescan("enp1s0", run) and not nc.rescan("--help", run) and not nc.rescan("wlan9", run) and not nc.rescan("", run)
assert not scans(), "nothing was sent for an interface that is not a Wi-Fi device"
put(devices="wlan0:wifi:connected:x\n", rescan_fail=True)
out = nc.rescan("wlan0", run)
assert not out and "Scanning not allowed" in out.reason, out

# ---- the secret agent: a degradation, found without reading anything private
proc = work / "proc"
for pid, comm in ((10, "bash"), (11, "nm-applet")):
    (proc / str(pid)).mkdir(parents=True)
    (proc / str(pid) / "comm").write_text(comm + "\n")
assert nc.secret_agent_running(str(proc)) is True
(proc / "11" / "comm").write_text("firefox\n")
assert nc.secret_agent_running(str(proc)) is False
print("network core checks passed")

# ---- the Settings page (needs GTK and a display; the window is never shown)
if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (window checks)")
    sys.exit(0)
import importlib.machinery
import importlib.util
import time
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "st"), ("XDG_DATA_HOME", "data")):
    os.environ[var] = str(work / sub)
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
if not Gtk.init_check():
    print("skip: no display (window checks)")
    sys.exit(0)
here = Path(__file__).resolve().parent.parent / "config" / "hypr" / "scripts"
loader = importlib.machinery.SourceFileLoader("primo_settings", str(here / "primo-settings.py"))
spec = importlib.util.spec_from_loader("primo_settings", loader)
ps = importlib.util.module_from_spec(spec)
loader.exec_module(ps)
app = Adw.Application(application_id="dev.primo.SettingsNetworkTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
ctx = GLib.MainContext.default()


def pump(seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not (until and until()):
        ctx.iteration(False)
        time.sleep(0.002)


titles = lambda win, key: [r.get_title() for r in win.net_rows[key]]
put(devices="wlan0:wifi:connected:Home\\:Net\nenp1s0:ethernet:connected:Wired one\n",
    aps=("*:AA\\:BB\\:CC\\:DD\\:EE\\:01:Home\\:Net:WPA2:71:wlan0\n"
         " :AA\\:BB\\:CC\\:DD\\:EE\\:02:Home\\:Net:WPA2:88:wlan0\n"
         " :11\\:22\\:33\\:44\\:55\\:66::WPA2:40:wlan0\n"
         " :77\\:88\\:99\\:AA\\:BB\\:CC:Open Cafe:--:55:wlan0\n"),
    connections="Home\\:Net:aaaaaaaa-0000-0000-0000-000000000001:802-11-wireless:wlan0\nOld Cafe:aaaaaaaa-0000-0000-0000-000000000002:802-11-wireless:\n"
                "Wired one:aaaaaaaa-0000-0000-0000-000000000003:802-3-ethernet:enp1s0\nWork VPN:aaaaaaaa-0000-0000-0000-000000000004:vpn:\n")
toasts = []
win = ps.SettingsWindow(app, "appearance")
win.toast = toasts.append
t0 = time.monotonic()
win.select_page("network")
assert time.monotonic() - t0 < 0.4, "the page opens before nmcli answers"
pump(5, until=lambda: win.net_snapshot is not None)
assert win.net_summary.get_title() == "Wi-Fi is on" and "Home:Net" in win.net_summary.get_subtitle()
assert titles(win, "aps") == ["Home:Net", "Home:Net", "Open Cafe", "Hidden network"], titles(win, "aps")      # two radios of one name stay two rows
assert titles(win, "saved") == ["Home:Net", "Old Cafe", "Wired one"], "the VPN has its own page"
assert not scans(), "showing the page never scans"
assert any("--rescan no" in l for l in log())

# search narrows both lists; "Open" has no saved match
win.net_search.set_text("cafe")
assert titles(win, "aps") == ["Open Cafe"] and titles(win, "saved") == ["Old Cafe"], (titles(win, "aps"), titles(win, "saved"))
win.net_search.set_text("zzz")
assert titles(win, "aps") == ["No network matches your search"] and titles(win, "saved") == ["No saved connection matches your search"]
win.net_search.set_text("")

# Refresh scans, and only then; the page reads again afterwards
win.net_refresh_btn.emit("clicked")
pump(5, until=lambda: scans() == ["scan wlan0"])
assert scans() == ["scan wlan0"] and any("Scanning" in t for t in toasts)
pump(6, until=lambda: sum(1 for l in log() if "device wifi list" in l) >= 2)

# NetworkManager stops: a failure row with Try again; the page recovers when it is back
data = json.loads(state.read_text())
data["down"] = True
state.write_text(json.dumps(data))
win.refresh_network()
pump(5, until=lambda: not win.net_reading)
assert win.net_snapshot is None and "not running" in win.net_summary.get_subtitle() and not win.net_refresh_btn.get_sensitive()
data["down"] = False
state.write_text(json.dumps(data))
win.refresh_network()
pump(5, until=lambda: win.net_snapshot is not None)
assert win.net_snapshot is not None

# the radio is off, then no card at all: said in words
put(radio="disabled", devices="enp1s0:ethernet:connected:Wired one\n", aps="", connections="")
win.refresh_network()
pump(5, until=lambda: win.net_snapshot is not None and not win.net_snapshot.wifi_enabled)
assert win.net_summary.get_title() == "Wi-Fi is off" and titles(win, "aps") == ["Wi-Fi is off"] and not win.net_refresh_btn.get_sensitive()
put(radio="enabled", devices="enp1s0:ethernet:connected:Wired one\n", aps="", connections="")
win.refresh_network()
pump(5, until=lambda: win.net_snapshot is not None and win.net_snapshot.wifi_enabled)
assert titles(win, "aps") == ["No Wi-Fi card found"]
win.on_close_request()
print("network page checks passed")
