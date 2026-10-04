#!/usr/bin/env python3
"""Primo Launcher: a Spotlight-style search box.

One field for everything: applications (ranked by how often you open them), a calculator,
system actions (lock, sleep, dark mode, ...), files under your home folder and web search.

    launcher.py --daemon         start the resident service (autostart does this)
    launcher.sh toggle           what the keybinds call (talks to the service over D-Bus)

Up/Down move, Enter opens, Esc closes. Calculator results are copied with Enter.
"""
import ast
import json
import math
import operator
import os
import re
import subprocess
import sys
import threading
import warnings
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

APP_ID = "dev.primo.Launcher"
SCRIPTS = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprland-dotfiles"
HISTORY = STATE_DIR / "launcher-history.json"
USER_CSS = Path.home() / ".config" / "gtk-4.0" / "gtk.css"
MAX_RESULTS = 9

CSS = """
window.primo-launcher, window.primo-launcher.background { background: transparent; box-shadow: none; }
.ln-card { background-color: @window_bg_color; border: 1px solid alpha(@accent_bg_color, 0.55); }
.ln-entry { margin: 16px 16px 8px 16px; font-size: 17px; min-height: 44px; border-radius: 12px; }
.ln-row { padding: 8px 12px; border-radius: 12px; margin: 1px 10px; }
.ln-row:selected { background-color: alpha(@accent_bg_color, 0.30); }
.ln-row:selected label { color: @window_fg_color; }
.ln-title { font-size: 14px; }
.ln-sub { font-size: 11px; opacity: 0.6; }
.ln-kind { font-size: 10px; opacity: 0.5; letter-spacing: 1px; margin: 10px 20px 2px 20px; }
.ln-calc { font-size: 22px; font-weight: 300; }
.ln-hint { opacity: 0.5; font-size: 11px; margin: 6px 16px 10px 16px; }
"""

KIND_LABEL = {"calc": "CALCULATOR", "app": "APPLICATIONS", "action": "ACTIONS", "file": "FILES", "web": "WEB"}
KIND_ORDER = ["calc", "app", "action", "file", "web"]


# --------------------------------------------------------------------------- calculator
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log10,
          "ln": math.log, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil}
_NAMES = {"pi": math.pi, "e": math.e}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _NAMES:
        return _NAMES[node.id]
    raise ValueError("unsupported")


def calculate(query):
    """Return a formatted result for math-looking input, otherwise None."""
    q = query.strip().lstrip("=").strip()
    if not q or not re.search(r"[\d)]", q) or not re.search(r"[-+*/%^(]|\b(sqrt|sin|cos|tan|log|ln|abs|round|floor|ceil)\b", q):
        return None
    q = q.replace("^", "**").replace("×", "*").replace("÷", "/").replace(",", ".")
    q = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*(?:of)\s*(\d+(?:\.\d+)?)", r"(\1/100*\2)", q)
    try:
        value = _eval(ast.parse(q, mode="eval"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        text = f"{value:.10g}"
    else:
        text = str(value)
    return text


# --------------------------------------------------------------------------- data
def load_history():
    try:
        return json.loads(HISTORY.read_text())
    except (OSError, ValueError):
        return {}


def bump_history(key):
    data = load_history()
    data[key] = data.get(key, 0) + 1
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(data))


def fuzzy(query, text):
    """0 = no match, higher is better. Substrings and word-initial acronyms only."""
    q, t = query.lower(), text.lower()
    if not q:
        return 1
    if t == q:
        return 100
    if t.startswith(q):
        return 90
    if re.search(r"\b" + re.escape(q), t):
        return 75
    if q in t:
        return 55
    # Acronym of the word starts ("vsc" -> Visual Studio Code); scattered letters do not count.
    initials = "".join(w[0] for w in re.split(r"[\s\-_.]+", t) if w)
    if len(q) >= 2 and initials.startswith(q):
        return 60
    return 0


def spawn(*cmd):
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def shell(cmd):
    spawn("sh", "-c", cmd)


ACTIONS = [
    ("Lock screen", "Lock the session", "system-lock-screen", "lock screen", lambda: shell("pidof hyprlock || hyprlock")),
    ("Sleep", "Suspend the computer", "weather-clear-night", "sleep suspend", lambda: shell("systemctl suspend")),
    ("Log out", "Asks for confirmation", "system-log-out", "log out logout exit", lambda: spawn(str(SCRIPTS / "power-menu.sh"), "logout")),
    ("Restart", "Open the power menu", "system-reboot", "restart reboot", lambda: spawn(str(SCRIPTS / "power-menu.sh"))),
    ("Shut down", "Open the power menu", "system-shutdown", "shut down poweroff shutdown", lambda: spawn(str(SCRIPTS / "power-menu.sh"))),
    ("Dark mode", "Switch to the dark theme", "weather-clear-night", "dark mode theme", lambda: shell("hypr-theme dark")),
    ("Light mode", "Switch to the light theme", "weather-clear", "light mode theme", lambda: shell("hypr-theme light")),
    ("Toggle night light", "Warm the screen colours", "preferences-system-brightness", "night light", lambda: spawn(str(SCRIPTS / "nightlight.sh"), "toggle")),
    ("Settings", "Appearance, wallpaper, displays", "preferences-system", "settings preferences", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py")),
    ("Wallpaper", "Choose a wallpaper", "preferences-desktop-wallpaper", "wallpaper background", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py --page wallpaper")),
    ("Displays", "Resolution, scale, arrangement", "preferences-desktop-display", "display monitor resolution", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py --page displays")),
    ("VPN", "Connect, disconnect, import a .ovpn profile", "network-vpn", "vpn openvpn connect tunnel", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py --page vpn")),
    ("Clipboard history", "Search what you copied", "edit-paste", "clipboard history paste", lambda: shell(f"python3 {SCRIPTS}/clipboard.py")),
    ("Activity", "What is running and what it costs", "utilities-system-monitor", "activity monitor processes background task manager cpu memory", lambda: spawn(str(SCRIPTS / "activity.sh"), "toggle")),
    ("Pick a colour", "Copy any colour from the screen", "color-select", "color colour picker eyedropper", lambda: spawn(str(SCRIPTS / "colorpicker.sh"))),
    ("Take screenshot", "Select an area", "applets-screenshooter", "screenshot capture", lambda: spawn(str(SCRIPTS / "screenshot.sh"), "area")),
]


class Item:
    def __init__(self, kind, title, subtitle="", icon=None, gicon=None, run=None, score=0, big=False):
        self.kind, self.title, self.subtitle, self.icon, self.gicon = kind, title, subtitle, icon, gicon
        self.run, self.score, self.big = run, score, big


class LauncherWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, default_width=660, default_height=600, title="Launcher")
        self.add_css_class("primo-launcher")
        self.set_decorated(False)
        self.set_resizable(False)
        self.app = app
        self.items = []
        self.file_hits = []
        self.query_token = 0

        # The window is fixed-size and transparent; the visible card sits at its top and grows
        # downwards, so the search box never jumps while results appear (Hyprland keeps a floating
        # window's centre fixed when it resizes).
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["ln-card", "primo-card"], valign=Gtk.Align.START)
        self.entry = Gtk.SearchEntry(placeholder_text="Search apps, files, math, actions…", css_classes=["ln-entry"])
        self.entry.connect("search-changed", self.on_changed)
        self.entry.connect("activate", lambda *_: self.activate_selected())
        root.append(self.entry)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, activate_on_single_click=True)
        self.listbox.set_header_func(self.header_func)
        self.listbox.connect("row-activated", lambda _lb, row: self.run_item(row.item))
        self.scroller = Gtk.ScrolledWindow(child=self.listbox, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                           propagate_natural_height=True, max_content_height=430)
        root.append(self.scroller)
        root.append(Gtk.Label(label="↵ Open     ↑↓ Move     Esc Close", xalign=0, css_classes=["ln-hint"]))
        outer = Gtk.Box()
        outer.append(root)
        outer.set_hexpand(True)
        root.set_hexpand(True)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _g, _n, x, y: self.close() if not self.card_contains(root, x, y) else None)
        outer.add_controller(click)
        self.set_content(outer)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.connect("notify::is-active", self.on_active_changed)
        self.rebuild("")
        self.entry.grab_focus()
        preset = os.environ.get("PRIMO_LAUNCHER_QUERY")  # used to take documentation screenshots
        if preset:
            self.entry.set_text(preset)

    @staticmethod
    def card_contains(card, x, y):
        a = card.get_allocation()
        return a.x <= x <= a.x + a.width and a.y <= y <= a.y + a.height

    # ---- search
    def on_changed(self, entry):
        text = entry.get_text()
        self.rebuild(text)
        self.query_token += 1
        token = self.query_token
        self.file_hits = []
        if len(text.strip()) >= 3 and not calculate(text):
            GLib.timeout_add(260, self.start_file_search, text.strip(), token)

    def start_file_search(self, text, token):
        if token != self.query_token:
            return False

        def work():
            hits = []
            try:
                out = subprocess.run(
                    ["find", str(Path.home()), "-maxdepth", "5", "-iname", f"*{text}*",
                     "-not", "-path", "*/.*", "-not", "-path", "*/node_modules/*", "-not", "-path", "*/.cache/*"],
                    capture_output=True, text=True, timeout=2.5).stdout.splitlines()
                hits = out[:6]
            except (subprocess.TimeoutExpired, OSError):
                pass
            GLib.idle_add(self.apply_file_hits, hits, token)

        threading.Thread(target=work, daemon=True).start()
        return False

    def apply_file_hits(self, hits, token):
        if token == self.query_token:
            self.file_hits = hits
            self.rebuild(self.entry.get_text(), keep_selection=True)
        return False

    def collect(self, text):
        q = text.strip()
        items = []
        result = calculate(q)
        if result is not None:
            items.append(Item("calc", f"= {result}", "Press Enter to copy", icon="accessories-calculator",
                              run=lambda r=result: subprocess.run(["wl-copy", r]), score=1000, big=True))
        history = load_history()
        for info in self.app.apps:
            name = info.get_display_name() or ""
            best = max(fuzzy(q, name), fuzzy(q, info.get_generic_name() or "") - 10,
                       fuzzy(q, " ".join(getattr(info, "get_keywords", lambda: [])() or [])) - 25)
            if q and best <= 0:
                continue
            boost = min(history.get(info.get_id() or name, 0), 20)
            score = (best + boost) if q else boost
            if not q and boost == 0:
                continue
            items.append(Item("app", name, info.get_description() or "", gicon=info.get_icon(),
                              run=lambda i=info: self.launch_app(i), score=score))
        for title, sub, icon, keywords, fn in ACTIONS:
            best = max(fuzzy(q, title), fuzzy(q, keywords) - 15)
            if q and best > 0:
                items.append(Item("action", title, sub, icon=icon, run=fn, score=best - 5))
        for path in self.file_hits:
            p = Path(path)
            items.append(Item("file", p.name, str(p.parent).replace(str(Path.home()), "~"),
                              icon="folder" if p.is_dir() else "text-x-generic",
                              run=lambda x=path: spawn("xdg-open", x), score=20))
        if len(q) >= 2 and result is None:
            items.append(Item("web", f"Search the web for “{q}”", "DuckDuckGo", icon="web-browser",
                              run=lambda s=q: spawn("xdg-open", "https://duckduckgo.com/?q=" + GLib.Uri.escape_string(s, None, False)),
                              score=1))
        items.sort(key=lambda i: (KIND_ORDER.index(i.kind), -i.score))
        limited, counts = [], {}
        for it in items:
            counts[it.kind] = counts.get(it.kind, 0) + 1
            if counts[it.kind] <= (6 if it.kind == "app" else 4):
                limited.append(it)
        return limited[:MAX_RESULTS + 3]

    def rebuild(self, text, keep_selection=False):
        previous = None
        if keep_selection and self.listbox.get_selected_row():
            previous = self.listbox.get_selected_row().item.title
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt
        self.items = self.collect(text)
        selected = None
        for it in self.items:
            row = self.make_row(it)
            self.listbox.append(row)
            if selected is None or (previous and it.title == previous):
                selected = row if selected is None or it.title == previous else selected
        if selected:
            self.listbox.select_row(selected)
        self.scroller.set_visible(bool(self.items))

    def make_row(self, it):
        row = Gtk.ListBoxRow(css_classes=["ln-row"])
        row.item = it
        box = Gtk.Box(spacing=14)
        img = Gtk.Image(pixel_size=32)
        if it.gicon is not None:
            img.set_from_gicon(it.gicon)
        else:
            img.set_from_icon_name(it.icon or "application-x-executable")
        box.append(img)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        col.append(Gtk.Label(label=it.title, xalign=0, ellipsize=3,
                             css_classes=["ln-calc" if it.big else "ln-title"]))
        if it.subtitle:
            col.append(Gtk.Label(label=it.subtitle, xalign=0, ellipsize=3, css_classes=["ln-sub"]))
        box.append(col)
        row.set_child(box)
        return row

    def header_func(self, row, before):
        if before is None or before.item.kind != row.item.kind:
            row.set_header(Gtk.Label(label=KIND_LABEL[row.item.kind], xalign=0, css_classes=["ln-kind"]))
        else:
            row.set_header(None)

    # ---- actions
    def launch_app(self, info):
        ctx = Gdk.Display.get_default().get_app_launch_context()
        try:
            info.launch([], ctx)
        except GLib.Error:
            pass
        bump_history(info.get_id() or info.get_display_name())

    def run_item(self, it):
        self.close()
        GLib.idle_add(lambda: (it.run(), False)[1])

    def activate_selected(self):
        row = self.listbox.get_selected_row()
        if row is not None:
            self.run_item(row.item)

    def move(self, delta):
        rows = []
        child = self.listbox.get_first_child()
        while child:
            rows.append(child)
            child = child.get_next_sibling()
        if not rows:
            return
        cur = self.listbox.get_selected_row()
        idx = rows.index(cur) if cur in rows else -1
        row = rows[max(0, min(len(rows) - 1, idx + delta))]
        self.listbox.select_row(row)
        row.grab_focus()
        self.entry.grab_focus()
        self.entry.set_position(-1)

    def on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_Tab):
            self.move(1)
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            self.move(-1)
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.activate_selected()
        else:
            return False
        return True

    def on_active_changed(self, *_):
        if not self.is_active():  # clicked elsewhere: behave like Spotlight and go away
            GLib.timeout_add(120, lambda: (self.close() if not self.is_active() else None, False)[1])


class Service(Adw.Application):
    def __init__(self, daemon):
        super().__init__(application_id=APP_ID)
        self.daemon = daemon
        self.window = None
        self.css = None
        self.apps = []
        act = Gio.SimpleAction.new("toggle", None)
        act.connect("activate", lambda *_: self.toggle())
        self.add_action(act)
        quit_act = Gio.SimpleAction.new("quit", None)
        quit_act.connect("activate", lambda *_: self.quit())
        self.add_action(quit_act)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.hold()
        self.reload_apps()
        self.monitor = Gio.AppInfoMonitor.get()
        self.monitor.connect("changed", lambda *_: self.reload_apps())

    def reload_apps(self):
        self.apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]

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
            own.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(display, own, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        if USER_CSS.exists():
            self.css.load_from_path(str(USER_CSS))

    def toggle(self):
        if self.window is not None and self.window.get_visible():
            self.window.close()
            return
        self.load_css()
        self.window = LauncherWindow(self)
        self.window.present()


def main():
    return Service("--daemon" in sys.argv).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
