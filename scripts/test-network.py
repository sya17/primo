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
elif a[:3] == ["--wait", "60", "connection"] or a[:2] == ["--wait", "60"] or a[:2] == ["device", "disconnect"] or a[:2] == ["radio", "wifi"]:
    open(path + ".muts", "a").write(text + "\\n")
    if st.get("mut_fail"): sys.stderr.write(st["mut_fail"] + "\\n"); sys.exit(4)
    if st.get("mut_slow"):
        import time; time.sleep(float(st["mut_slow"]) if st["mut_slow"] is not True else 30)
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
    for suffix in (".log", ".scan", ".muts"):
        Path(str(state) + suffix).write_text("")


def log():
    return Path(str(state) + ".log").read_text().splitlines()


def muts():
    return Path(str(state) + ".muts").read_text().splitlines()


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

# ---- changes: validated against the current snapshot, passed as argv, with the wait the design asks for
put(devices="wlan0:wifi:connected:Home\\:Net\nenp1s0:ethernet:disconnected:\n",
    aps=("*:AA\\:BB\\:CC\\:DD\\:EE\\:01:Home\\:Net:WPA2:71:wlan0\n"
         " :77\\:88\\:99\\:AA\\:BB\\:CC:Open Cafe:--:55:wlan0\n"
         " :12\\:12\\:12\\:12\\:12\\:12:Office:WPA2 802.1X:60:wlan0\n"),
    connections="Home\\:Net:aaaaaaaa-0000-0000-0000-000000000001:802-11-wireless:wlan0\nOld Cafe:aaaaaaaa-0000-0000-0000-000000000002:802-11-wireless:\n"
                "Wired one:aaaaaaaa-0000-0000-0000-000000000003:802-3-ethernet:\nWork VPN:aaaaaaaa-0000-0000-0000-000000000004:vpn:\n")
out = nc.activate_saved("aaaaaaaa-0000-0000-0000-000000000002", "wlan0", run)
assert out and muts() == ["--wait 60 connection up uuid aaaaaaaa-0000-0000-0000-000000000002 ifname wlan0"], muts()
out = nc.connect_ap("wlan0", "77:88:99:AA:BB:CC", run)
assert out and muts()[-1] == "--wait 60 device wifi connect 77:88:99:AA:BB:CC ifname wlan0 bssid 77:88:99:AA:BB:CC", muts()
assert nc.disconnect("wlan0", run) and muts()[-1] == "device disconnect wlan0"
assert nc.set_wifi(False, run) and muts()[-1] == "radio wifi off" and nc.set_wifi(True, run) and muts()[-1] == "radio wifi on"
before = len(muts())
for bad in (nc.activate_saved("aaaaaaaa-0000-0000-0000-000000000004", "wlan0", run),      # a VPN profile is never touched from here
            nc.activate_saved("not-a-uuid; rm -rf /", "wlan0", run),
            nc.activate_saved("aaaaaaaa-0000-0000-0000-000000000002", "--help", run),
            nc.activate_saved("aaaaaaaa-0000-0000-0000-00000000ffff", "wlan0", run),
            nc.connect_ap("wlan0", "00:00:00:00:00:00", run),                              # an access point that is not in the list any more
            nc.connect_ap("wlan0", "-h", run), nc.connect_ap("wlan9", "77:88:99:AA:BB:CC", run),
            nc.disconnect("lo", run), nc.disconnect("--help", run), nc.disconnect("wlan9", run)):
    assert not bad and bad.reason, bad
assert len(muts()) == before, "nothing was sent for any of them"
assert "no longer" in nc.connect_ap("wlan0", "00:00:00:00:00:00", run).reason
out = nc.connect_ap("wlan0", "12:12:12:12:12:12", run)                                       # enterprise Wi-Fi needs the advanced editor
assert not out and out.advice == "editor" and len(muts()) == before, out
assert not nc.set_wifi("yes", run), "the radio state is a real boolean"

# NetworkManager's words, in ours
for said, expect in (("Error: Connection activation failed: Secrets were required, but not provided.", "password"),
                     ("Error: Connection activation failed: (5) Connection 'x' is not available on device wlan0 because device has no carrier", "no carrier"),
                     ("Error: Failed to add/activate new connection: Not authorized to control networking.", "permission"),
                     ("Error: Timeout expired (60 seconds)", "too long"),
                     ("Error: Connection activation failed: No suitable device found", "device")):
    state_data = json.loads(state.read_text())
    state_data["mut_fail"] = said
    state.write_text(json.dumps(state_data))
    out = nc.activate_saved("aaaaaaaa-0000-0000-0000-000000000002", "wlan0", run)
    assert not out and expect in out.reason.lower(), (said, out)
state_data["mut_fail"] = "Error: Connection activation failed: Secrets were required, but not provided."
state.write_text(json.dumps(state_data))
out = nc.connect_ap("wlan0", "77:88:99:AA:BB:CC", run)
assert out.advice == "agent" and "password" in out.reason.lower(), out

# a slow activation is bounded by the caller's deadline
state_data["mut_fail"] = ""
state_data["mut_slow"] = True
state.write_text(json.dumps(state_data))
slow = lambda argv, **k: pc.run_bounded(argv, deadline=0.4, **k)
out = nc.activate_saved("aaaaaaaa-0000-0000-0000-000000000002", "wlan0", slow)
assert not out and "too long" in out.reason.lower(), out
joined = " ".join(muts()).lower()
assert "password" not in joined and "--ask" not in joined and "secret" not in joined, "Primo never carries a password"
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

# ---- changes from the page (the real window, fake nmcli, nothing real changes)
def mutate(**kw):
    data = json.loads(state.read_text())
    data.update(kw)
    state.write_text(json.dumps(data))

put(devices="wlan0:wifi:connected:Home\\:Net\nenp1s0:ethernet:disconnected:\n",
    aps=("*:AA\\:BB\\:CC\\:DD\\:EE\\:01:Home\\:Net:WPA2:71:wlan0\n :77\\:88\\:99\\:AA\\:BB\\:CC:Open Cafe:--:55:wlan0\n"
         " :12\\:12\\:12\\:12\\:12\\:12:Office:WPA2 802.1X:60:wlan0\n"),
    connections="Home\\:Net:aaaaaaaa-0000-0000-0000-000000000001:802-11-wireless:wlan0\nOld Cafe:aaaaaaaa-0000-0000-0000-000000000002:802-11-wireless:\n"
                "Wired one:aaaaaaaa-0000-0000-0000-000000000003:802-3-ethernet:\n")
win.refresh_network()
pump(5, until=lambda: win.net_snapshot is not None and win.net_snapshot.access_points)
toasts.clear()
offered = []
win.offer_net_editor = offered.append
rows = {r.get_title(): r for r in win.net_rows["aps"]}

# connecting shows "connecting…" until the system answers; a second click on the same device is refused; the result is read back
mutate(mut_slow=1.2)
rows["Open Cafe"].emit("activated")
pump(0.4)
assert any("connecting…" in r.get_subtitle() for r in win.net_rows["aps"]), [r.get_subtitle() for r in win.net_rows["aps"]]
rows2 = {r.get_title(): r for r in win.net_rows["aps"]}
rows2["Office"].emit("activated")
assert any("Still working on wlan0" in t for t in toasts) and len(muts()) == 1, (toasts, muts())
pump(6, until=lambda: not win.net_connecting and any("Asked NetworkManager" in t for t in toasts))
assert muts() == ["--wait 60 device wifi connect 77:88:99:AA:BB:CC ifname wlan0 bssid 77:88:99:AA:BB:CC"], muts()
assert not win.net_connecting
mutate(mut_slow=False)
pump(3, until=lambda: not win.net_reading)

# an enterprise network offers the advanced editor and sends nothing
Path(str(state) + ".muts").write_text("")
{r.get_title(): r for r in win.net_rows["aps"]}["Office"].emit("activated")
pump(4, until=lambda: offered)
assert offered and "Advanced setup" in offered[0] and not muts(), (offered, muts())

# a password that nobody asked for: the words say what to do
Path(str(state) + ".muts").write_text("")
mutate(mut_fail="Error: Connection activation failed: Secrets were required, but not provided.")
toasts.clear()
{r.get_title(): r for r in win.net_rows["aps"]}["Open Cafe"].emit("activated")
pump(4, until=lambda: any("Could not" in t for t in toasts))
assert any("needs a password" in t for t in toasts), toasts
mutate(mut_fail="")
pump(3, until=lambda: not win.net_reading)

# a saved profile is brought up by its id on the right device
Path(str(state) + ".muts").write_text("")
win.net_connect_saved(next(c for c in win.net_snapshot.connections if c.name == "Old Cafe"))
pump(4, until=lambda: muts())
assert muts() == ["--wait 60 connection up uuid aaaaaaaa-0000-0000-0000-000000000002 ifname wlan0"], muts()
pump(3, until=lambda: not win.net_connecting)

# disconnecting asks first: Cancel sends nothing, Disconnect sends it; the radio asks too
Path(str(state) + ".muts").write_text("")
win.net_disconnect_answered("cancel", "wlan0", "Home:Net")
pump(0.4)
assert not muts()
win.net_disconnect_answered("disconnect", "wlan0", "Home:Net")
pump(4, until=lambda: muts())
assert muts() == ["device disconnect wlan0"], muts()
pump(3, until=lambda: not win.net_reading)
win.net_radio_answered("cancel")
pump(3, until=lambda: not win.net_reading)
assert not [m for m in muts() if m.startswith("radio")] and win.net_radio.get_active(), muts()
win.net_set_radio(False)
pump(4, until=lambda: "radio wifi off" in muts())
assert "radio wifi off" in muts()

# closing the window while an activation runs: it is not cancelled, the application stays held until it ends
mutate(mut_slow=1.0)
holds = []
real_hold, real_release = app.hold, app.release
app.hold = lambda: (holds.append("hold"), real_hold())
app.release = lambda: (holds.append("release"), real_release())
win2 = ps.SettingsWindow(app, "network")
win2.toast = lambda t: holds.append("toast")
pump(4, until=lambda: win2.net_snapshot is not None)
win2.net_set_radio(True)
pump(0.2)
win2.on_close_request()
assert holds.count("hold") > holds.count("release"), holds
pump(4, until=lambda: holds.count("hold") == holds.count("release"))
assert holds.count("hold") == holds.count("release") and "toast" not in holds, holds
win.on_close_request()
print("network page checks passed")
