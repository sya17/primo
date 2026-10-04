#!/usr/bin/env python3
"""Activity: what is running in the background and what it costs (SUPER+SHIFT+Esc).

Apps and background programs with CPU, memory, GPU, disk and connections; services and timers; quit,
force quit, freeze. A resident service like the switcher, so it opens instantly; it only measures while
the window is open (plus, if you turn it on, a slow check for busy apps while on battery).

    activity.py --daemon     start the service (autostart does this)
    activity.sh toggle       what the keybind calls
    activity.py --top        print a JSON summary for the Waybar tooltip
"""
import html
import json
import os
import signal
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import activity_collect as ac  # noqa: E402

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprland-dotfiles"
APP_ID = "dev.primo.Activity"


def windows_by_pid():
    try:
        raw = json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=3).stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    out = {}
    for c in raw:
        if c.get("mapped") and c.get("class") and c["class"] != APP_ID:
            out.setdefault(c["pid"], []).append({"class": c["class"], "title": c.get("title", ""),
                                                 "address": c["address"], "workspace": c["workspace"]["id"]})
    return out


def snapshot(sampler):
    procs = sampler.sample()
    return procs, ac.group_apps(procs, sampler, windows_by_pid())


# ----------------------------------------------------------------------------- Waybar tooltip
def top_main():
    sampler = ac.Sampler(light=True)
    sampler.sample()
    time.sleep(0.4)
    _procs, groups = snapshot(sampler)
    best = sorted((g for g in groups if g.impact > 0.5 and os.getpid() not in g.pids), key=lambda g: -g.impact)[:3]
    lines = [f"{html.escape(g.name)}: {g.cpu:.0f}% CPU" for g in best] or ["All quiet"]
    lines.append(f"<i>measured {time.strftime('%H:%M:%S')}, click for details</i>")
    busy = bool(best) and best[0].impact >= 50
    print(json.dumps({"text": "", "class": "busy" if busy else "", "tooltip": "\n".join(lines)}))


if "--top" in sys.argv:
    top_main()
    sys.exit(0)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

USER_CSS = Path.home() / ".config" / "gtk-4.0" / "gtk.css"
CONFIRM = HERE / "confirm.py"

CSS = """
window.primo-activity { background-color: @window_bg_color; }
.act-head { font-size: 15px; font-weight: 700; }
.act-foot { font-size: 11px; opacity: 0.6; }
.act-small { font-size: 11px; opacity: 0.65; }
.act-bar { min-width: 84px; }
.act-bar trough { min-height: 6px; border-radius: 999px; }
.act-bar progress { min-height: 6px; border-radius: 999px; background-image: linear-gradient(to right, @accent_bg_color, @accent2_color); }
.act-num { font-size: 11px; font-feature-settings: "tnum"; min-width: 56px; }
.act-badge { padding: 3px; border-radius: 999px; background-color: alpha(@accent_bg_color, 0.22); }
.act-badge.hot { background-color: alpha(@destructive_bg_color, 0.28); }
.act-mono { font-family: monospace; font-size: 11px; }
"""

BADGES = {
    "microphone": ("audio-input-microphone-symbolic", "Using the microphone", True),
    "camera": ("camera-web-symbolic", "Using the camera", True),
    "screen": ("video-display-symbolic", "Sharing or recording the screen", True),
    "audio": ("audio-volume-high-symbolic", "Playing sound", False),
    "frozen": ("media-playback-pause-symbolic", "Frozen: not running", False),
}
PROTECTED_UNITS = ("dbus-broker", "pipewire", "wireplumber", "wayland-wm@", "xdg-", "session-", "init.scope")


def fmt_rate(n):
    return "0" if n < 1024 else ac.fmt_bytes(n) + "/s"


def ago(us, future=False):
    if not us:
        return "never"
    delta = us / 1e6 - time.time()
    delta = delta if future else -delta
    if delta < 0:
        return "now"
    for unit, size in (("d", 86400), ("h", 3600), ("min", 60)):
        if delta >= size:
            return f"{delta / size:.0f} {unit}" + ("" if future else " ago")
    return "moments" if future else "just now"


def clear(box):
    child = box.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def label(text, css=None, xalign=0.0, **kw):
    return Gtk.Label(label=text, xalign=xalign, css_classes=[css] if css else [], **kw)


class Apps:
    """Resolves a window class to a display name and an icon."""

    def __init__(self):
        self.by_key = None

    def load(self):
        self.by_key = {}
        for info in Gio.AppInfo.get_all():
            if not isinstance(info, Gio.DesktopAppInfo):
                continue
            keys = {(info.get_id() or "").lower().removesuffix(".desktop"), (info.get_startup_wm_class() or "").lower()}
            for k in keys - {""}:
                self.by_key.setdefault(k, info)

    def lookup(self, name):
        if self.by_key is None:
            self.load()
        low = name.lower()
        return self.by_key.get(low) or self.by_key.get(low.split(".")[-1])

    def label_icon(self, group):
        info = self.lookup(group.name) if group.kind == "app" else None
        if info:
            return info.get_display_name(), info.get_icon()
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for cand in (group.name.lower(), group.name.lower().split(".")[-1], group.name.lower().replace(" ", "-")):
            if theme.has_icon(cand):
                return group.name, Gio.ThemedIcon.new(cand)
        fallback = "utilities-terminal" if group.name in ac.LIFT.values() else "system-run-symbolic"
        return group.name, Gio.ThemedIcon.new(fallback)


class AppRow(Adw.ExpanderRow):
    def __init__(self, win, group):
        super().__init__()
        self.win = win
        self.key = group.key
        self.group = group
        self.sort = (0, 0, 0)
        self.child_rows = []

        self.icon = Gtk.Image(pixel_size=32)
        self.add_prefix(self.icon)
        self.badges = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        grid = Gtk.Grid(column_spacing=8, row_spacing=2, valign=Gtk.Align.CENTER)
        self.cpu_bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, css_classes=["act-bar"])
        self.mem_bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, css_classes=["act-bar"])
        self.cpu_txt = Gtk.Label(xalign=1, css_classes=["act-num"])
        self.mem_txt = Gtk.Label(xalign=1, css_classes=["act-num"])
        for r, (name, bar, txt) in enumerate((("CPU", self.cpu_bar, self.cpu_txt), ("RAM", self.mem_bar, self.mem_txt))):
            grid.attach(Gtk.Label(label=name, xalign=0, css_classes=["act-small"]), 0, r, 1, 1)
            grid.attach(bar, 1, r, 1, 1)
            grid.attach(txt, 2, r, 1, 1)
        suffix = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        suffix.append(self.badges)
        suffix.append(grid)
        self.add_suffix(suffix)

        self.detail = Gtk.Label(xalign=0, wrap=True, selectable=True, css_classes=["act-mono"], margin_top=8, margin_bottom=4,
                                margin_start=16, margin_end=16)
        self.detail_row = Gtk.ListBoxRow(activatable=False, selectable=False, child=self.detail)
        self.add_row(self.detail_row)
        self.buttons = Gtk.Box(spacing=8, margin_top=6, margin_bottom=10, margin_start=16, margin_end=16, halign=Gtk.Align.END)
        self.btn_open = Gtk.Button(label="Open window", css_classes=["flat"])
        self.btn_freeze = Gtk.Button(label="Freeze", css_classes=["flat"])
        self.btn_quit = Gtk.Button(label="Quit", css_classes=["flat"])
        self.btn_kill = Gtk.Button(label="Force quit", css_classes=["flat", "destructive-action"])
        self.locked = Gtk.Label(label="System process: it cannot be stopped from here", css_classes=["act-small"])
        for b in (self.btn_open, self.btn_freeze, self.btn_quit, self.btn_kill, self.locked):
            self.buttons.append(b)
        self.add_row(Gtk.ListBoxRow(activatable=False, selectable=False, child=self.buttons))
        self.btn_open.connect("clicked", lambda *_: win.open_window(self.key))
        self.btn_freeze.connect("clicked", lambda *_: win.freeze_toggle(self.key))
        self.btn_quit.connect("clicked", lambda *_: win.quit_app(self.key))
        self.btn_kill.connect("clicked", lambda *_: win.force_quit(self.key))
        self.shown_icon = None

    def update(self, g, total_mem, label, icon):
        self.group = g
        self.set_title(GLib.markup_escape_text(label if len(g.leaders) < 2 or g.kind == "bg" else f"{label} ×{len(g.leaders)}"))
        self.set_subtitle(g.doing)
        if self.shown_icon != label:
            self.icon.set_from_gicon(icon)
            self.shown_icon = label
        self.cpu_bar.set_fraction(min(g.cpu / 100.0, 1.0))
        self.cpu_txt.set_label(f"{g.cpu:.0f}%" + (f" +{g.gpu:.0f}% GPU" if g.gpu >= 5 else ""))
        self.mem_bar.set_fraction(min(g.mem / max(total_mem, 1), 1.0))
        self.mem_txt.set_label(ac.fmt_bytes(g.mem))
        child = self.badges.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.badges.remove(child)
            child = nxt
        for b in g.badges:
            icon_name, tip, hot = BADGES[b]
            img = Gtk.Image(icon_name=icon_name, tooltip_text=tip, css_classes=["act-badge"] + (["hot"] if hot else []))
            self.badges.append(img)
        has_window = bool(g.windows)
        self.btn_open.set_visible(has_window)
        self.btn_freeze.set_label("Resume" if g.frozen else "Freeze")
        for b in (self.btn_freeze, self.btn_quit, self.btn_kill):
            b.set_visible(not g.protected)
        self.locked.set_visible(g.protected)
        if self.get_expanded():
            self.fill_detail(g)

    def fill_detail(self, g):
        lines = [f"{len(g.pids)} process{'es' if len(g.pids) != 1 else ''}"
                 + (f" · GPU {g.gpu:.0f}%" if g.gpu else "")
                 + f" · disk read {fmt_rate(g.io_r)}, write {fmt_rate(g.io_w)}"]
        if g.conns:
            hosts = ", ".join(g.hosts[:4]) + (f" +{len(g.hosts) - 4}" if len(g.hosts) > 4 else "")
            lines.append(f"{g.conns} connection{'s' if g.conns != 1 else ''}: {hosts}")
        if g.ports:
            lines.append("listening on port " + ", ".join(g.ports[:6]))
        lines.append("")
        for depth, p in g.tree[:14]:
            lines.append(f"{'  ' * depth}{'└ ' if depth else ''}{ac.script_name(p)}  {ac.fmt_bytes(p.pss)}  {p.cpu:.0f}%")
        if len(g.tree) > 14:
            lines.append(f"… and {len(g.tree) - 14} more")
        self.detail.set_label("\n".join(lines))


class ActivityWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, default_width=800, default_height=720, title="Activity")
        self.add_css_class("primo-activity")
        self.app = app
        self.rows = {}
        self.tick_n = 0
        self.sort_by = "impact"
        self.tab = "apps"
        self.service_rows = []
        self.expand_first = False
        self.svc_data = None
        self.apps = Apps()

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        tabs = Adw.ToggleGroup()
        for name, label in (("apps", "Apps"), ("bg", "Background"), ("services", "Services"), ("dev", "Dev")):
            tabs.add(Adw.Toggle(name=name, label=label))
        tabs.set_active_name("apps")
        tabs.connect("notify::active-name", lambda g, _p: self.set_tab(g.get_active_name()))
        header.set_title_widget(tabs)
        view.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=6, margin_bottom=8, margin_start=18, margin_end=18)
        top = Gtk.Box(spacing=12)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, spacing=2)
        self.headline = Gtk.Label(label="Measuring…", xalign=0, css_classes=["act-head"], ellipsize=3)
        self.subline = Gtk.Label(label="", xalign=0, css_classes=["act-small"], ellipsize=3)
        text.append(self.headline)
        text.append(self.subline)
        top.append(text)
        self.query = ""
        self.sorter = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
        for name, label in (("impact", "Impact"), ("mem", "Memory"), ("cpu", "CPU")):
            self.sorter.add(Adw.Toggle(name=name, label=label))
        self.sorter.set_active_name("impact")
        self.sorter.connect("notify::active-name", self.on_sort)
        top.append(self.sorter)
        body.append(top)

        self.search = Gtk.SearchEntry(placeholder_text="Search apps, background programs and services", hexpand=True)
        self.search.connect("search-changed", self.on_search)
        self.search.set_key_capture_widget(self)         # just start typing
        body.append(self.search)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self.list.set_sort_func(lambda a, b: (b.sort > a.sort) - (b.sort < a.sort))
        self.empty = Gtk.Label(label="Measuring…", margin_top=60, valign=Gtk.Align.START, css_classes=["dim-label"])
        self.svc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.stack = Gtk.Stack()
        self.stack.add_named(self.list, "list")
        self.stack.add_named(self.empty, "empty")
        self.stack.set_visible_child_name("empty")
        self.stack.add_named(self.svc_box, "services")
        self.dev_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.stack.add_named(self.dev_box, "dev")
        self.dev_data = None
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.scroll.set_child(self.stack)
        body.append(self.scroll)
        self.footer = Gtk.Label(xalign=0, css_classes=["act-foot"])
        body.append(self.footer)
        view.set_content(body)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.connect("close-request", self.on_close)
        self.alive = True
        self.groups = []
        self.procs = {}
        app.sampler.sample()                      # baseline for the rates
        if os.environ.get("PRIMO_ACTIVITY_TAB"):  # debugging aid: start on another tab, with the first row open
            self.set_tab(os.environ["PRIMO_ACTIVITY_TAB"])
            tabs.set_active_name(os.environ["PRIMO_ACTIVITY_TAB"])
            self.expand_first = True
        if os.environ.get("PRIMO_ACTIVITY_QUERY"):
            self.search.set_text(os.environ["PRIMO_ACTIVITY_QUERY"])
        GLib.timeout_add(1000, self.tick)         # first real numbers after a second

    def on_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            if self.search.get_text():
                self.search.set_text("")
            else:
                self.close()
            return True
        if keyval == Gdk.KEY_f and state & Gdk.ModifierType.CONTROL_MASK:
            self.search.grab_focus()
            return True
        return False

    def on_search(self, entry):
        self.query = entry.get_text().strip().lower()
        if self.tab == "services":
            if self.svc_data:
                self.fill_services(*self.svc_data)
        elif self.tab == "dev":
            if self.dev_data:
                self.fill_dev(*self.dev_data)
        else:
            self.refresh_apps(resort=True)

    def matches(self, *texts):
        hay = " ".join(texts).lower()
        return all(word in hay for word in self.query.split())

    # ---- loop
    def on_close(self, *_):
        self.alive = False
        return False

    def tick(self):
        if not self.alive:
            return False
        self.procs, self.groups = snapshot(self.app.sampler)
        self.tick_n += 1
        if self.tab == "services":
            if self.tick_n % 3 == 0:   # three systemctl calls: no need to repeat them every 2 s
                self.refresh_services()
        elif self.tab == "dev":
            if self.tick_n % 2 == 0:
                self.refresh_dev()
        else:
            self.refresh_apps(resort=(self.tick_n % 3 == 1))
        self.refresh_footer()
        GLib.timeout_add(2000, self.tick)
        return False

    def set_tab(self, name):
        self.tab = name
        self.sorter.set_visible(name not in ("services", "dev"))
        if name == "services":
            self.stack.set_visible_child_name("services")
            self.refresh_services()
        elif name == "dev":
            self.stack.set_visible_child_name("dev")
            self.refresh_dev()
        else:
            self.stack.set_visible_child_name("list")
            for row in list(self.rows.values()):   # the other tab's rows go away; new ones are made on the next refresh
                self.list.remove(row)
            self.rows.clear()
            self.refresh_apps(resort=True)

    def on_sort(self, group, _p):
        self.sort_by = group.get_active_name()
        self.refresh_apps(resort=True)

    # ---- apps / background
    def refresh_apps(self, resort):
        if not self.groups:
            return
        total = ac.mem_info()["total"]
        kind = "app" if self.tab == "apps" else "bg"
        # An app with a window, or one of the lifted tools, is an "app"; everything else runs in the background.
        # A search looks through both.
        if self.query:
            shown = {g.key: g for g in self.groups if self.matches(g.name, g.doing, " ".join(" ".join(p.cmd) for p in g.pids_procs), " ".join(g.ports))}
        else:
            shown = {g.key: g for g in self.groups if g.kind == kind}
        for key in [k for k in self.rows if k not in shown]:
            self.list.remove(self.rows.pop(key))
        names = {}
        for key, g in shown.items():
            row = self.rows.get(key)
            if row is None:
                row = self.rows[key] = AppRow(self, g)
                self.list.append(row)
                resort = True
            label, icon = self.apps.label_icon(g)
            names[key] = label
            row.update(g, total, label, icon)
            row.sort = {"impact": (g.impact, g.mem), "mem": (g.mem, 0), "cpu": (g.cpu, g.mem)}[self.sort_by]
        if resort:
            self.list.invalidate_sort()
        if self.expand_first and self.rows:
            self.expand_first = False
            first = max(self.rows.values(), key=lambda r: r.sort)
            first.set_expanded(True)
            first.fill_detail(first.group)
        self.empty.set_label(f"No match for “{self.query}”" if self.query else "Nothing here")
        self.stack.set_visible_child_name("list" if shown else "empty")
        if self.query:
            self.headline.set_label(f"{len(shown)} match{'es' if len(shown) != 1 else ''} for “{self.query}”")
            self.subline.set_label("Apps and background programs · measured over the last 2 seconds")
        else:
            self.headline.set_label(ac.headline(list(shown.values()), names) if shown else "Nothing here")
            self.subline.set_label(f"{len(shown)} {'apps' if kind == 'app' else 'background programs'} · measured over the last 2 seconds")

    def refresh_footer(self):
        m = ac.mem_info()
        text = f"Memory {ac.fmt_bytes(m['used'])} of {ac.fmt_bytes(m['total'])}"
        if m["swap_total"]:
            text += f" · swap {ac.fmt_bytes(m['swap_used'])}"
        bat = ac.battery()
        if bat:
            status, watts = bat
            text += f" · battery {status.lower()}" + (f", drawing {watts:.1f} W" if watts and status == "Discharging" else "")
        self.footer.set_label(text)

    # ---- developer view: ports, build tools and runtimes, containers
    def refresh_dev(self):
        procs = self.procs

        def work():
            ports = ac.listening(procs)
            conts = ac.containers()
            GLib.idle_add(self.fill_dev, ports, conts)

        threading.Thread(target=work, daemon=True).start()

    def fill_dev(self, ports, conts):
        if not self.alive or self.tab != "dev":
            return
        self.dev_data = (ports, conts)
        rows, problem = conts
        keep = self.scroll.get_vadjustment().get_value()
        clear(self.dev_box)
        GLib.idle_add(lambda: (self.scroll.get_vadjustment().set_value(keep), False)[1])
        by_pid = {}
        for r in ports:
            by_pid.setdefault(r["pid"], []).append(r["port"])
        devs = ac.dev_processes(self.procs, set(by_pid))
        q = self.query
        shown_ports = [r for r in ports if not q or self.matches(str(r["port"]), r["name"], ac.cwd_of(r["pid"]) if r["pid"] else "", r["addr"])]
        shown_devs = [p for p in devs if not q or self.matches(ac.script_name(p), " ".join(p.cmd), ac.cwd_of(p.pid), " ".join(map(str, by_pid.get(p.pid, []))))]
        shown_conts = [c for c in rows if not q or self.matches(c["name"], c["image"], c["ports"], c["status"])]
        self.headline.set_label(f"{len(shown_ports)} port{'s' if len(shown_ports) != 1 else ''} listening · "
                                f"{len(shown_devs)} dev process{'es' if len(shown_devs) != 1 else ''} · {len(shown_conts)} container{'s' if len(shown_conts) != 1 else ''}")
        self.subline.set_label("Type a port number to see what uses it")

        group = Adw.PreferencesGroup(title="Listening ports", description="Who is holding a port (“address already in use”)")
        for r in shown_ports:
            proc = self.procs.get(r["pid"]) if r["pid"] else None
            cwd = ac.cwd_of(r["pid"]).replace(str(Path.home()), "~") if proc else ""
            row = Adw.ActionRow(title=GLib.markup_escape_text(f":{r['port']}  {r['name']}"),
                                subtitle=GLib.markup_escape_text(f"{r['proto']} · {'only this computer' if r['addr'] in ('127.0.0.1', '::1') else 'reachable from the network'}"
                                                                 + (f" · {cwd}" if cwd else "")))
            if proc and proc.comm not in ac.PROTECTED:
                self.proc_buttons(row, proc)
            elif not r["pid"]:
                row.add_suffix(label("another user", "act-small"))
            group.add(row)
        if shown_ports:
            self.dev_box.append(group)
        if shown_devs:
            dg = Adw.PreferencesGroup(title="Dev processes", description="Builds, runtimes and databases you started")
            for p in shown_devs:
                cwd = ac.cwd_of(p.pid).replace(str(Path.home()), "~")
                pts = by_pid.get(p.pid)
                row = Adw.ActionRow(title=GLib.markup_escape_text(ac.script_name(p) + (f"  ·  {Path(cwd).name}" if cwd and cwd != "~" else "")),
                                    subtitle=GLib.markup_escape_text((f"port {', '.join(map(str, pts))} · " if pts else "") + (" ".join(p.cmd)[:90] or p.comm)))
                row.add_suffix(label(ac.fmt_bytes(p.pss), "act-num"))
                self.proc_buttons(row, p)
                dg.add(row)
            self.dev_box.append(dg)
        cg = Adw.PreferencesGroup(title="Containers")
        if problem:
            msgs = {"permission": ("Docker is installed, but your account cannot use it",
                                   "Members of the docker group can act as root, so this is your decision: sudo usermod -aG docker $USER, then log in again"),
                    "missing": ("Docker is not installed", "sudo pacman -S docker"),
                    "stopped": ("Docker is not running", "sudo systemctl enable --now docker")}
            title, sub = msgs[problem]
            row = Adw.ActionRow(title=title, subtitle=sub)
            if problem == "permission":
                cmd = "sudo usermod -aG docker $USER"
                copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Copy the command")
                copy.connect("clicked", lambda *_: self.copy_cmd(cmd))
                row.add_suffix(copy)
            cg.add(row)
            if not q:
                self.dev_box.append(cg)
        else:
            for c in shown_conts:
                up = c["state"] == "running"
                row = Adw.ActionRow(title=GLib.markup_escape_text(c["name"]),
                                    subtitle=GLib.markup_escape_text(f"{c['image']} · {c['status']}" + (f" · {c['ports']}" if c["ports"] else "")))
                row.add_prefix(Gtk.Image(icon_name="media-playback-start-symbolic" if up else "media-playback-stop-symbolic",
                                         css_classes=["act-badge"] if up else []))
                logs = Gtk.Button(icon_name="utilities-terminal-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Follow the log in a terminal")
                logs.connect("clicked", lambda _b, cid=c["id"], n=c["name"]: subprocess.Popen(
                    ["kitty", "--title", f"docker logs {n}", "-e", "docker", "logs", "-f", "--tail", "200", cid], start_new_session=True))
                toggle = Gtk.Button(label="Stop" if up else "Start", valign=Gtk.Align.CENTER, css_classes=["flat"] + (["destructive-action"] if up else []))
                toggle.connect("clicked", lambda _b, cid=c["id"], n=c["name"], u=up: self.docker_action("stop" if u else "start", cid, n))
                restart = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Restart")
                restart.connect("clicked", lambda _b, cid=c["id"], n=c["name"]: self.docker_action("restart", cid, n))
                for w in (logs, restart, toggle):
                    row.add_suffix(w)
                cg.add(row)
            if shown_conts or not q:
                if not shown_conts:
                    cg.add(Adw.ActionRow(title="No containers", subtitle="docker run … or docker compose up"))
                self.dev_box.append(cg)
        if not (shown_ports or shown_devs or shown_conts or problem):
            self.dev_box.append(label(f"No match for “{q}”" if q else "Nothing is listening", "dim-label", xalign=0.5, margin_top=40))

    def proc_buttons(self, row, proc):
        quit_ = Gtk.Button(label="Quit", valign=Gtk.Align.CENTER, css_classes=["flat"])
        kill = Gtk.Button(label="Force quit", valign=Gtk.Align.CENTER, css_classes=["flat", "destructive-action"])
        quit_.connect("clicked", lambda *_: self.proc_action(proc, signal.SIGTERM))
        kill.connect("clicked", lambda *_: self.proc_action(proc, signal.SIGKILL))
        row.add_suffix(quit_)
        row.add_suffix(kill)

    def proc_action(self, proc, sig):
        name = ac.script_name(proc)
        forced = sig == signal.SIGKILL

        def go():
            n = ac.signal_tree(proc, self.procs, sig)
            self.toast((f"Stopped {name}" if forced else f"Asked {name} to quit") if n else "Could not reach it (already gone?)")
            GLib.timeout_add(1200, lambda: (self.refresh_dev(), False)[1])

        self.confirm(f"{'Force quit' if forced else 'Quit'} {name}?",
                     ("Ends it and everything it started, immediately. Unsaved work is lost." if forced else "It is asked to stop normally."),
                     "Force quit" if forced else "Quit", go)

    def docker_action(self, verb, cid, name):
        def go():
            r = subprocess.run(["docker", verb, cid], capture_output=True, text=True)
            msg = f"{ {'start': 'Started', 'stop': 'Stopped', 'restart': 'Restarted'}[verb] } {name}"
            GLib.idle_add(lambda: (self.toast(msg if r.returncode == 0 else (r.stderr.strip().splitlines() or ["failed"])[-1]), self.refresh_dev(), False)[2])

        if verb == "stop":
            self.confirm(f"Stop {name}?", "The container stops. Its data in volumes stays.", "Stop", lambda: threading.Thread(target=go, daemon=True).start())
        else:
            threading.Thread(target=go, daemon=True).start()

    # ---- services
    def refresh_services(self):
        def work():
            user = ac.services(True)
            system = ac.services(False)
            GLib.idle_add(self.fill_services, user, system)

        threading.Thread(target=work, daemon=True).start()

    def fill_services(self, user, system):
        if not self.alive or self.tab != "services":
            return
        keep = self.scroll.get_vadjustment().get_value()
        child = self.svc_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.svc_box.remove(child)
            child = nxt
        GLib.idle_add(lambda: (self.scroll.get_vadjustment().set_value(keep), False)[1])
        kids = ac.children_map(self.procs)

        def mem_of(pid):
            total, stack = 0, [pid]
            while stack:
                p = stack.pop()
                if p in self.procs:
                    total += self.procs[p].pss or self.procs[p].rss
                    stack.extend(kids.get(p, []))
            return total

        self.svc_data = (user, system)
        u_rows, u_timers = user
        s_rows, s_timers = system
        if self.query:
            u_rows = [r for r in u_rows if self.matches(r["unit"], r["description"])]
            s_rows = [r for r in s_rows if self.matches(r["unit"], r["description"])]
            u_timers = [t for t in u_timers if self.matches(t["unit"], t.get("activates", ""))]
            s_timers = [t for t in s_timers if self.matches(t["unit"], t.get("activates", ""))]
            self.headline.set_label(f"{len(u_rows) + len(s_rows)} services match “{self.query}”")
        else:
            self.headline.set_label(f"{len(u_rows)} user services and {len(s_rows)} system services running")
        self.subline.set_label(f"{len(u_timers) + len(s_timers)} timers scheduled")
        for title, rows, is_user in (("Your services", u_rows, True), ("System services", s_rows, False)):
            if self.query and not rows:
                continue
            group = Adw.PreferencesGroup(title=title, description="" if is_user else "Read-only here: stopping these needs administrator rights")
            for r in sorted(rows, key=lambda r: -mem_of(r["pid"]) if r["pid"] else 0):
                row = Adw.ActionRow(title=GLib.markup_escape_text(r["description"] or r["unit"]), subtitle=GLib.markup_escape_text(r["unit"]))
                mem = mem_of(r["pid"]) if r["pid"] else 0
                if mem:
                    row.add_suffix(Gtk.Label(label=ac.fmt_bytes(mem), css_classes=["act-num"]))
                locked = any(r["unit"].startswith(p) for p in PROTECTED_UNITS)
                if is_user and not locked:
                    restart = Gtk.Button(label="Restart", valign=Gtk.Align.CENTER, css_classes=["flat"])
                    stop = Gtk.Button(label="Stop", valign=Gtk.Align.CENTER, css_classes=["flat", "destructive-action"])
                    restart.connect("clicked", lambda _b, u=r["unit"]: self.unit_action(u, "restart"))
                    stop.connect("clicked", lambda _b, u=r["unit"]: self.unit_action(u, "stop"))
                    row.add_suffix(restart)
                    row.add_suffix(stop)
                elif not is_user:
                    copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                      tooltip_text="Copy: sudo systemctl restart " + r["unit"])
                    copy.connect("clicked", lambda _b, u=r["unit"]: self.copy_cmd(f"sudo systemctl restart {u}"))
                    row.add_suffix(copy)
                else:
                    row.add_suffix(Gtk.Image(icon_name="changes-prevent-symbolic", tooltip_text="Part of your session: it cannot be stopped from here"))
                group.add(row)
            self.svc_box.append(group)
        timers = Adw.PreferencesGroup(title="Timers")
        for t in sorted(u_timers + s_timers, key=lambda t: t.get("next") or 1 << 62)[:12]:
            timers.add(Adw.ActionRow(title=GLib.markup_escape_text(t.get("activates", t["unit"])),
                                     subtitle=f"next in {ago(t.get('next'), True)} · last {ago(t.get('last'))}"))
        if u_timers or s_timers:
            self.svc_box.append(timers)

    def unit_action(self, unit, verb):
        def go():
            subprocess.run(["systemctl", "--user", verb, unit], capture_output=True)
            GLib.idle_add(lambda: (self.toast(f"{'Restarted' if verb == 'restart' else 'Stopped'} {unit}"), self.refresh_services(), False)[2])

        if verb == "stop":
            self.confirm(f"Stop {unit}?", "Things that rely on it may stop working until you start it again.", "Stop it",
                         lambda: threading.Thread(target=go, daemon=True).start())
        else:
            threading.Thread(target=go, daemon=True).start()

    def copy_cmd(self, cmd):
        subprocess.Popen(["wl-copy", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.toast("Command copied")

    # ---- actions
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def confirm(self, title, text, label, then):
        proc = Gio.Subprocess.new([sys.executable, str(CONFIRM), "--title", title, "--text", text, "--confirm", label, "--danger"],
                                  Gio.SubprocessFlags.NONE)

        def done(p, res):
            try:
                p.wait_finish(res)
            except GLib.Error:
                return
            if p.get_exit_status() == 0:
                then()

        proc.wait_async(None, done)

    def group(self, key):
        return next((g for g in self.groups if g.key == key), None)

    def describe(self, g):
        n = len(g.pids)
        return f"{g.name} ({n} process{'es' if n != 1 else ''})"

    def quit_app(self, key):
        g = self.group(key)
        if not g or g.protected:
            return
        extra = " Unsaved work in it may be lost."
        if g.name in ac.LIFT.values():
            extra = " This ends the running session(s), including one you may be using right now."

        def go():
            n = ac.signal_group(g, signal.SIGTERM, only_leaders=True)
            self.toast(f"Asked {g.name} to quit" if n else "Could not reach it (already gone?)")

        self.confirm(f"Quit {g.name}?", "It is asked to close normally." + extra, "Quit", go)

    def force_quit(self, key):
        g = self.group(key)
        if not g or g.protected:
            return

        def go():
            n = ac.signal_group(g, signal.SIGKILL)
            self.toast(f"Stopped {n} process{'es' if n != 1 else ''}" if n else "Could not reach it (already gone?)")

        self.confirm(f"Force quit {g.name}?", f"Ends {self.describe(g)} immediately. Anything unsaved is lost.", "Force quit", go)

    def freeze_toggle(self, key):
        g = self.group(key)
        if not g or g.protected:
            return
        if g.frozen:
            n = ac.signal_group(g, signal.SIGCONT)
            self.toast(f"Resumed {g.name}" if n else "Could not reach it")
            return

        def go():
            n = ac.signal_group(g, signal.SIGSTOP)
            self.toast(f"Froze {g.name}" if n else "Could not reach it")

        self.confirm(f"Freeze {g.name}?", "It stops using CPU but also stops responding, and music or downloads in it pause. "
                     "Resume it from here at any time.", "Freeze", go)

    def open_window(self, key):
        g = self.group(key)
        if g and g.windows:
            subprocess.run(["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{g.windows[0]["address"]}" }})'],
                           capture_output=True)
            self.close()


class Service(Adw.Application):
    ALERT_CPU = 50.0        # % of one core
    ALERT_SAMPLES = 10      # in a row, 30 s apart = 5 minutes
    ALERT_COOLDOWN = 1800

    def __init__(self, daemon):
        super().__init__(application_id=APP_ID)
        self.daemon = daemon
        self.window = None
        self.css = None
        self.sampler = ac.Sampler()
        self.streak = {}
        self.notified = {}
        for name, fn in (("toggle", self.toggle), ("quit", self.quit)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda *_a, f=fn: f())
            self.add_action(act)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.hold()
        GLib.timeout_add_seconds(30, self.watch)

    def do_activate(self):
        if self.daemon:
            self.daemon = False
            return
        self.toggle()

    def load_css(self):
        display = Gdk.Display.get_default()
        if self.css is None:
            self.css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(display, self.css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            own = Gtk.CssProvider()
            fallback = ""
            try:
                if "accent2_color" not in USER_CSS.read_text():
                    fallback = "@define-color accent2_color @accent_bg_color;\n"   # theme not re-applied yet
            except OSError:
                fallback = "@define-color accent2_color @accent_bg_color;\n"
            own.load_from_string(fallback + CSS)
            Gtk.StyleContext.add_provider_for_display(display, own, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        if USER_CSS.exists():
            self.css.load_from_path(str(USER_CSS))

    def toggle(self):
        if self.window is not None and self.window.alive and self.window.get_visible():
            self.window.close()
            return
        self.load_css()
        self.window = ActivityWindow(self)
        self.window.present()

    # Optional: warn about an app that keeps the CPU busy while on battery (Settings > Power).
    def watch(self):
        try:
            if not (STATE_DIR / "activity-alert").exists() or (self.window is not None and self.window.alive):
                self.streak.clear()
                return True
            bat = ac.battery()
            if not bat or bat[0] != "Discharging":
                self.streak.clear()
                return True
            _procs, groups = snapshot(self.sampler)
            busy = {g.key: g for g in groups if g.cpu >= self.ALERT_CPU and not g.protected}
            self.streak = {k: self.streak.get(k, 0) + 1 for k in busy}
            now = time.time()
            for key, n in self.streak.items():
                if n >= self.ALERT_SAMPLES and now - self.notified.get(key, 0) > self.ALERT_COOLDOWN:
                    self.notified[key] = now
                    g = busy[key]
                    subprocess.Popen(["notify-send", "-a", "Activity", "-i", "utilities-system-monitor",
                                      f"{g.name} is using the battery",
                                      f"About {g.cpu:.0f}% CPU for 5 minutes. Open Activity (Super+Shift+Esc) to quit or freeze it."])
        except Exception as exc:   # a watcher must never take the service down
            print("activity watch:", exc, file=sys.stderr)
        return True


if __name__ == "__main__":
    sys.exit(Service("--daemon" in sys.argv).run([sys.argv[0]]))
