"""Primo Doctor: the list of Primo's features and the checks that say whether the desktop is healthy. Standard library only, read-only.

Used by the `primo` command (`primo status`, `primo doctor`, `primo features`) and by the Health page in Settings. Nothing here changes the system:
a check reads a file, asks `hyprctl`, `systemctl` or `fc-list`, or looks at the process list. A fix is only ever a command *suggested* to the user.

A check returns a Result with a status: pass, warning, fail or skipped. An optional dependency that is missing is `skipped`, never a failure.
Exit-code contract of the CLI: 0 healthy (pass and skipped only), 1 warnings, 2 at least one failure.
"""
import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

PASS, WARNING, FAIL, SKIPPED = "pass", "warning", "fail", "skipped"
CATEGORIES = ["Session", "Services", "Features", "Configuration", "Theme", "System"]
LINKED_APPS = ["hypr", "waybar", "wofi", "dunst", "kitty", "swayosd", "swaync", "fontconfig"]
GENERATED = ["config/hypr/theme.lua", "config/hypr/theme.env", "config/hypr/confirm.css", "config/waybar/theme.css", "config/waybar/style.css",
             "config/wofi/style.css", "config/kitty/theme.conf", "config/swaync/style.css"]

SCRIPTS = "~/.config/hypr/scripts"


@dataclass
class Feature:
    id: str
    name: str
    summary: str
    core: bool = False
    requires: tuple = ()          # (binary, pacman package): needed for the feature to work at all
    optional: tuple = ()          # (binary, pacman package, what it adds)
    process: str = ""             # regex over the command line of the process that must be running
    tool: tuple = ()              # the process is only expected when one of these is installed (a name on PATH, or an absolute path)
    start: str = ""               # a command that starts it (shown as a hint)
    page: str = ""                # Settings page, if any
    keybind: str = ""


FEATURES = [
    Feature("bar", "Bar", "Waybar: workspaces, clock, tray, status icons", core=True, requires=(("waybar", "waybar"),), process=r"(^|/)waybar( |$)", start="waybar"),
    Feature("launcher", "Launcher", "Apps, calculator, actions, files, snippets, web", core=True, process=r"scripts/launcher\.py", start=f"python3 {SCRIPTS}/launcher.py --daemon",
            requires=(("python3", "python"),), keybind="Super+Space"),
    Feature("switcher", "Window switcher", "Hold Alt, tap Tab: windows, most recent first", process=r"scripts/switcher\.py", start=f"python3 {SCRIPTS}/switcher.py --daemon", keybind="Alt+Tab"),
    Feature("overview", "Overview", "Every workspace and its windows", process=r"scripts/overview\.py", start=f"python3 {SCRIPTS}/overview.py --daemon", keybind="Super+O"),
    Feature("settings", "Settings", "Appearance, wallpaper, displays, power, Bluetooth, modes, workflow, VPN", keybind="Super+,"),
    Feature("hub", "Time hub", "Calendar, reminders, clock, focus, report, notes", process=r"scripts/hub\.py", start=f"python3 {SCRIPTS}/hub.py --daemon",
            requires=(("notify-send", "libnotify"),), optional=(("pw-play", "pipewire", "alarm and reminder sounds"), ("swaync-client", "swaync", "do-not-disturb while focusing"),
                                                              ("wl-copy", "wl-clipboard", "copy a report summary")), keybind="Super+Ctrl+H"),
    Feature("activity", "Activity", "What runs and what it costs; ports; containers", process=r"scripts/activity\.py", start=f"python3 {SCRIPTS}/activity.py --daemon",
            optional=(("ss", "iproute2", "connections and listening ports"), ("pactl", "libpulse", "microphone and audio badges"), ("docker", "docker", "container list")), keybind="Super+Shift+Esc"),
    Feature("modes", "Modes", "One action sets up apps, VPN, power, do-not-disturb and a focus session", requires=(("hyprctl", "hyprland"),),
            optional=(("nmcli", "networkmanager", "VPN step"), ("powerprofilesctl", "power-profiles-daemon", "power step"), ("swaync-client", "swaync", "do-not-disturb step")),
            page="modes", keybind="Super+Ctrl+W"),
    Feature("workflow", "Workflow", "Calendar feeds, apps on workspaces, snippets, notes backup", optional=(("git", "git", "notes backup"), ("gh", "github-cli", "review requests in the bar")),
            page="workflow"),
    Feature("notifications", "Notifications", "swaync notification centre (dunst as fallback)", core=True, process=r"(^|/)(swaync|dunst)( |$)", start="swaync", tool=("swaync", "dunst"),
            optional=(("swaync", "swaync", "control centre and history"),)),
    Feature("lock", "Lock and idle", "hyprlock and hypridle", requires=(("hyprlock", "hyprlock"), ("hypridle", "hypridle")), process=r"(^|/)hypridle( |$)", start="hypridle", keybind="Super+L"),
    Feature("wallpaper", "Wallpaper", "awww (animated) or hyprpaper; slideshow, GIF", requires=(),
            optional=(("awww", "awww", "animated transitions and GIFs"), ("hyprpaper", "hyprpaper", "fallback wallpaper"), ("mpvpaper", "mpvpaper", "video wallpapers")), page="wallpaper"),
    Feature("clipboard", "Clipboard history", "cliphist picker", requires=(("wl-copy", "wl-clipboard"), ("cliphist", "cliphist")), process=r"wl-paste .*cliphist", start="wl-paste --type text --watch cliphist store",
            keybind="Super+Shift+V"),
    Feature("capture", "Screenshots and recording", "Area screenshots, annotation, screen recording", requires=(("grim", "grim"), ("slurp", "slurp")),
            optional=(("satty", "satty", "annotation"), ("wf-recorder", "wf-recorder", "screen recording")), keybind="Super+Shift+S"),
    Feature("osd", "On-screen display", "Volume, brightness and lock key indicators", optional=(("swayosd-server", "swayosd", "volume and brightness pop-ups"),), process=r"swayosd-server", start="swayosd-server", tool=("swayosd-server",)),
    Feature("power", "Power mode", "Power Saver, Balanced, Performance", requires=(("powerprofilesctl", "power-profiles-daemon"),), page="power"),
    Feature("battery", "Battery warnings", "Warns at 20, 10 and 4 percent", process=r"battery-watch\.sh", start=f"{SCRIPTS}/battery-watch.sh"),
    Feature("bluetooth", "Bluetooth", "Devices and pairing", requires=(("bluetoothctl", "bluez-utils"),), optional=(("blueman-manager", "blueman", "pairing window"),), page="bluetooth"),
    Feature("vpn", "VPN", "NetworkManager VPN connections", requires=(("nmcli", "networkmanager"),), page="vpn"),
    Feature("nightlight", "Night light", "Warmer screen colours", optional=(("hyprsunset", "hyprsunset", "the filter itself"),), keybind="Super+N"),
    Feature("colorpicker", "Colour picker", "Pick a colour from the screen", optional=(("hyprpicker", "hyprpicker", "the picker itself"),), keybind="Super+Ctrl+P"),
    Feature("files", "File manager", "Nautilus as a floating window; Dolphin for heavy work", optional=(("nautilus", "nautilus", "Quick Look window"), ("dolphin", "dolphin", "split view")), keybind="Super+E"),
    Feature("polkit", "Authentication prompts", "Polkit agent for password dialogs", process=r"polkit-.*authentication-agent", start="/usr/lib/polkit-kde-authentication-agent-1",
            tool=("/usr/lib/polkit-kde-authentication-agent-1",)),
]
FEATURES_BY_ID = {f.id: f for f in FEATURES}

# system units worth looking at, only when the matching tool is installed: (feature, unit, user unit?)
UNITS = [("bluetooth", "bluetooth.service", False), ("power", "power-profiles-daemon.service", False), ("vpn", "NetworkManager.service", False)]


@dataclass
class Result:
    id: str
    category: str
    title: str
    status: str
    message: str = ""
    fix: str = ""               # a command to suggest, never run
    feature: str = ""


class System:
    """The real machine. Tests pass a fake with the same methods."""

    def __init__(self, env=None, home=None, repo=None):
        self.env = env if env is not None else os.environ
        self.home = Path(home) if home else Path.home()
        self.repo = Path(repo) if repo else None
        self._procs = None
        self._fonts = None

    def which(self, name):
        return shutil.which(name, path=self.env.get("PATH"))

    def run(self, *cmd, timeout=4):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=dict(self.env))
            return r.returncode, r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return 127, ""

    def processes(self):
        """Command lines (as one string each) of every process of this user."""
        if self._procs is None:
            out, uid = [], os.getuid()
            for d in Path("/proc").iterdir():
                if d.name.isdigit():
                    try:
                        if d.stat().st_uid != uid:
                            continue
                        out.append((d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip())
                    except OSError:
                        continue
            self._procs = [c for c in out if c]
        return self._procs

    def unit_active(self, unit, user=False):
        code, out = self.run("systemctl", *(["--user"] if user else []), "is-active", unit)
        return out == "active"

    def fonts(self):
        if self._fonts is None:
            self._fonts = self.run("fc-list", ":", "family")[1]
        return self._fonts

    def exists(self, path):
        return Path(path).exists()

    def read(self, path):
        return Path(path).read_text()

    def disk_free(self, path="/"):
        u = shutil.disk_usage(path)
        return u.free / u.total


def strip_jsonc(text):
    return re.sub(r"^\s*//.*\n", "", text, flags=re.M)


def in_session(s):
    return bool(s.env.get("HYPRLAND_INSTANCE_SIGNATURE"))


def find_repo(s):
    """The Primo repository: where ~/.config/hypr points, else the folder that holds this file."""
    if s.repo:
        return s.repo
    link = s.home / ".config" / "hypr"
    try:
        if link.is_symlink():
            return link.resolve().parent.parent
    except OSError:
        pass
    here = Path(__file__).resolve().parents[3]
    return here if (here / "themes").is_dir() else None


# ----------------------------------------------------------------------------- checks
def check_session(s):
    out = []
    if not in_session(s):
        out.append(Result("session.hyprland", "Session", "Hyprland session", FAIL, "Not running inside a Hyprland session (run this from a terminal on the desktop)"))
        return out
    code, text = s.run("hyprctl", "version")
    m = re.search(r"Hyprland\s+(\d+)\.(\d+)\.(\d+)", text)
    if code != 0 or not m:
        out.append(Result("session.hyprland", "Session", "Hyprland session", FAIL, "hyprctl does not answer", "hyprctl version"))
        return out
    ver = tuple(int(x) for x in m.groups())
    out.append(Result("session.hyprland", "Session", "Hyprland session", PASS, f"Hyprland {'.'.join(map(str, ver))} is running"))
    out.append(Result("session.version", "Session", "Hyprland version", PASS if ver >= (0, 55, 0) else WARNING,
                      "Lua configuration is supported" if ver >= (0, 55, 0) else "Primo's Lua configuration needs Hyprland 0.55 or newer", "" if ver >= (0, 55, 0) else "sudo pacman -Syu hyprland"))
    code, errs = s.run("hyprctl", "configerrors")
    errs = errs.strip()
    out.append(Result("session.configerrors", "Session", "Hyprland configuration", PASS if not errs else FAIL,
                      "No configuration errors" if not errs else errs.splitlines()[0][:160], "" if not errs else "hyprctl configerrors"))
    uwsm = s.run("systemctl", "--user", "list-units", "wayland-wm@*.service", "--no-legend")[1]
    out.append(Result("session.uwsm", "Session", "Session manager", PASS if uwsm else SKIPPED,
                      "UWSM manages the session (systemd user units are available)" if uwsm else "Not started through UWSM: resident services start from the Hyprland config"))
    return out


def check_services(s):
    out = []
    if not in_session(s):
        return [Result("service.all", "Services", "Resident services", SKIPPED, "Skipped outside a Hyprland session")]
    procs = s.processes()
    for f in FEATURES:
        if not f.process:
            continue
        if f.id == "battery" and not any(s.exists(p) for p in ("/sys/class/power_supply/BAT0", "/sys/class/power_supply/BAT1")):
            out.append(Result(f"service.{f.id}", "Services", f.name, SKIPPED, "No battery on this machine", feature=f.id))
            continue
        if f.requires and any(not s.which(b) for b, _p in f.requires):
            out.append(Result(f"service.{f.id}", "Services", f.name, SKIPPED, "A required tool is missing (see Features)", feature=f.id))
            continue
        if f.tool and not any((s.exists(t) if t.startswith("/") else s.which(t)) for t in f.tool):
            out.append(Result(f"service.{f.id}", "Services", f.name, SKIPPED, "Not installed", feature=f.id))
            continue
        rx = re.compile(f.process)
        running = any(rx.search(c) for c in procs)
        if running:
            out.append(Result(f"service.{f.id}", "Services", f.name, PASS, "Running", feature=f.id))
        else:
            out.append(Result(f"service.{f.id}", "Services", f.name, FAIL if f.core else WARNING, "Not running", f.start, f.id))
    for fid, unit, user in UNITS:
        f = FEATURES_BY_ID[fid]
        if not all(s.which(b) for b, _p in f.requires):
            continue
        active = s.unit_active(unit, user)
        out.append(Result(f"unit.{unit}", "Services", unit, PASS if active else WARNING, "Active" if active else "Not active",
                          "" if active else f"sudo systemctl enable --now {unit}", fid))
    return out


def check_features(s):
    out = []
    for f in FEATURES:
        missing = [(b, p) for b, p in f.requires if not s.which(b)]
        if missing:
            out.append(Result(f"dependency.{f.id}", "Features", f.name, FAIL if f.core else WARNING,
                              "Missing: " + ", ".join(b for b, _ in missing), "sudo pacman -S " + " ".join(sorted({p for _b, p in missing})), f.id))
        else:
            absent = [(b, p, why) for b, p, why in f.optional if not s.which(b)]
            if absent:
                out.append(Result(f"dependency.{f.id}", "Features", f.name, SKIPPED if len(absent) == len(f.optional) and not f.requires else PASS,
                                  "Optional, not installed: " + ", ".join(f"{b} ({why})" for b, _p, why in absent),
                                  "sudo pacman -S " + " ".join(sorted({p for _b, p, _w in absent})), f.id))
            else:
                out.append(Result(f"dependency.{f.id}", "Features", f.name, PASS, "Everything it uses is installed", feature=f.id))
    code, _o = s.run("python3", "-c", "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Adw")
    out.append(Result("dependency.gtk", "Features", "GTK 4 and libadwaita for Python", PASS if code == 0 else FAIL,
                      "Available" if code == 0 else "The Primo windows cannot start", "" if code == 0 else "sudo pacman -S python-gobject libadwaita gtk4"))
    return out


def check_configuration(s):
    out = []
    repo = find_repo(s)
    cfg = s.home / ".config"
    broken, unlinked, ok = [], [], 0
    for app in LINKED_APPS:
        p = cfg / app
        if p.is_symlink() and not p.exists():
            broken.append(app)
        elif p.is_symlink():
            ok += 1
        elif p.exists():
            unlinked.append(app)
    if broken:
        out.append(Result("config.links", "Configuration", "Linked configuration", FAIL, "Broken link: " + ", ".join(broken), "scripts/install.sh --dry-run"))
    else:
        note = f"; not linked to the repository: {', '.join(unlinked)}" if unlinked else ""
        out.append(Result("config.links", "Configuration", "Linked configuration", PASS, f"{ok} app folders linked{note}"))
    path_missing = [n for n in ("hypr-theme", "primo") if not s.which(n)]
    out.append(Result("config.path", "Configuration", "Commands on PATH", PASS if not path_missing else WARNING,
                      "hypr-theme and primo are on PATH" if not path_missing else "Not on PATH: " + ", ".join(path_missing), "" if not path_missing else "scripts/install.sh"))
    bad = []
    for p in sorted((cfg / "primo").glob("*.json")) + [s.home / ".local/state/hyprland-dotfiles/hub/hub.json"]:
        if s.exists(p):
            try:
                json.loads(s.read(p))
            except ValueError as exc:
                bad.append(f"{p.name}: {exc}")
    out.append(Result("config.json", "Configuration", "Settings files", PASS if not bad else FAIL,
                      "All settings files parse" if not bad else "; ".join(bad)[:200], "" if not bad else "Fix or move the file; Primo does not overwrite a broken one"))
    wb = cfg / "waybar" / "config.jsonc"
    if s.exists(wb):
        try:
            json.loads(strip_jsonc(s.read(wb)))
            out.append(Result("config.waybar", "Configuration", "Waybar configuration", PASS, "Valid"))
        except ValueError as exc:
            out.append(Result("config.waybar", "Configuration", "Waybar configuration", FAIL, str(exc)[:160]))
    wf = cfg / "primo" / "workflow.json"
    if s.exists(wf):
        mode = Path(wf).stat().st_mode & 0o077
        out.append(Result("config.secret-file", "Configuration", "Private settings file", PASS if not mode else WARNING,
                          "workflow.json is readable only by you" if not mode else "workflow.json (it can hold a private calendar link) is readable by others", "" if not mode else f"chmod 600 {wf}"))
    if repo is None:
        out.append(Result("config.repo", "Configuration", "Primo repository", WARNING, "Could not find the repository (is ~/.config/hypr linked to it?)"))
    return out


def check_theme(s):
    out = []
    repo = find_repo(s)
    state = s.home / ".local/state/hyprland-dotfiles/current"
    current = ""
    if s.exists(state):
        current = s.read(state).strip()
    if repo and current and not (repo / "themes" / current / "theme.conf").exists():
        out.append(Result("theme.current", "Theme", "Current theme", FAIL, f"'{current}' has no folder in themes/", "hypr-theme --list"))
    elif current:
        out.append(Result("theme.current", "Theme", "Current theme", PASS, current))
    else:
        out.append(Result("theme.current", "Theme", "Current theme", WARNING, "No theme has been applied yet", "hypr-theme primo-dusk"))
    if repo:
        missing = [g for g in GENERATED if not (repo / g).exists()]
        unresolved = []
        for g in GENERATED:
            p = repo / g
            if p.exists():
                try:
                    if "{{" in p.read_text(errors="replace"):
                        unresolved.append(g)
                except OSError:
                    pass
        if missing or unresolved:
            msg = ("Missing: " + ", ".join(missing) if missing else "") + ("; unresolved placeholders in: " + ", ".join(unresolved) if unresolved else "")
            out.append(Result("theme.generated", "Theme", "Generated theme files", FAIL, msg.strip("; "), f"hypr-theme {current or 'primo-dusk'}"))
        else:
            out.append(Result("theme.generated", "Theme", "Generated theme files", PASS, f"{len(GENERATED)} files present, no placeholders left"))
    fonts = s.fonts()
    lack = [n for n in ("JetBrainsMono Nerd Font", "Inter") if n not in fonts]
    out.append(Result("theme.fonts", "Theme", "Fonts", PASS if not lack else WARNING, "Inter and JetBrainsMono Nerd Font are installed" if not lack else "Missing: " + ", ".join(lack),
                      "" if not lack else "sudo pacman -S ttf-jetbrains-mono-nerd inter-font"))
    lack = [n for n, p in (("Papirus icons", "/usr/share/icons/Papirus"), ("adw-gtk3 theme", "/usr/share/themes/adw-gtk3")) if not s.exists(p)]
    out.append(Result("theme.toolkit", "Theme", "GTK theme and icons", PASS if not lack else WARNING, "adw-gtk3 and Papirus are installed" if not lack else "Missing: " + ", ".join(lack),
                      "" if not lack else "sudo pacman -S adw-gtk-theme papirus-icon-theme"))
    return out


def check_system(s):
    out = []
    free = s.disk_free("/")
    out.append(Result("system.disk", "System", "Disk space", PASS if free >= 0.10 else (WARNING if free >= 0.05 else FAIL), f"{free * 100:.0f}% of the root filesystem is free",
                      "" if free >= 0.10 else "paccache -r   (and see: sudo du -xh / --max-depth=2 | sort -h | tail)"))
    firewall = s.which("ufw")
    if firewall:
        active = s.unit_active("ufw.service")
        out.append(Result("system.firewall", "System", "Firewall (ufw)", PASS if active else WARNING, "ufw is active" if active else "ufw is installed but not active", "" if active else "sudo scripts/setup-system.sh"))
    return out


def run_all(s=None):
    s = s or System()
    results = []
    for fn in (check_session, check_services, check_features, check_configuration, check_theme, check_system):
        try:
            results.extend(fn(s))
        except Exception as exc:   # a broken check must not hide the others
            results.append(Result(f"check.{fn.__name__}", "System", fn.__name__, FAIL, f"The check crashed: {exc}"))
    return results


# ----------------------------------------------------------------------------- summaries
def summary(results):
    counts = {k: sum(1 for r in results if r.status == k) for k in (PASS, WARNING, FAIL, SKIPPED)}
    health = "UNHEALTHY" if counts[FAIL] else ("DEGRADED" if counts[WARNING] else "HEALTHY")
    return {"health": health, "counts": counts, "exit_code": 2 if counts[FAIL] else (1 if counts[WARNING] else 0)}


def feature_states(results):
    """Per feature: unavailable (a required tool is missing), stopped (its service is not running), or working, plus notes."""
    by_feature = {}
    for r in results:
        if r.feature:
            by_feature.setdefault(r.feature, []).append(r)
    out = []
    for f in FEATURES:
        rs = by_feature.get(f.id, [])
        dep = next((r for r in rs if r.id == f"dependency.{f.id}"), None)
        svc = next((r for r in rs if r.id == f"service.{f.id}"), None)
        notes = []
        if dep and dep.status in (WARNING, FAIL):
            state, notes = "unavailable", [dep.message]
        elif svc and svc.status in (WARNING, FAIL):
            state, notes = "stopped", [svc.message]
        else:
            state = "working"
            if dep and dep.status in (PASS, SKIPPED) and dep.message.startswith("Optional"):
                notes = [dep.message]
        out.append({"id": f.id, "name": f.name, "summary": f.summary, "state": state, "notes": notes, "keybind": f.keybind, "page": f.page, "core": f.core})
    return out


def to_dicts(results):
    return [asdict(r) for r in results]
