"""Primo Command, the logic behind the launcher: a calculator, fuzzy matching, and a registry of providers that each answer a query with results.

Standard library only (no GTK), so it is tested without a display. The launcher window (launcher.py) owns the UI and the file search thread; everything
else a result can come from is a Provider here:

    CalculatorProvider  12*(3+4), sqrt(16), 15% of 80
    AppProvider         installed applications, ranked by how often you open them
    WindowProvider      open windows (also: "win firefox")
    ActionProvider      system actions, modes, snippets
    WorkspaceProvider   "ws 4" switches to workspace 4, "ws" lists them
    ThemeProvider       "theme dawn" switches theme
    ClipboardProvider   "clip foo" searches your clipboard history (only on request: it can hold secrets)
    FileProvider        file hits found by the window's background search
    WebProvider         a web search fallback

A command word ("ws", "theme", "clip", "win") followed by a space sends the query to that provider only. Add a provider by writing a class with
`id`, `label`, `order`, `limit` and `query(q, ctx, args)` and putting it in PROVIDERS. A provider that raises is skipped, never fatal.
"""
import ast
import json
import math
import operator
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import config_core as cc  # noqa: E402
import doctor_core as dc  # noqa: E402

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprland-dotfiles"
HISTORY = STATE_DIR / "launcher-history.json"
MAX_RESULTS = 9


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
        return f"{value:.10g}"
    return str(value)


# --------------------------------------------------------------------------- matching and history
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


def load_history():
    try:
        return json.loads(HISTORY.read_text())
    except (OSError, ValueError):
        return {}


def bump_history(key):
    data = load_history()
    data[key] = data.get(key, 0) + 1
    cc.atomic_write(HISTORY, json.dumps(data))


def spawn(*cmd):
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def shell(cmd):
    spawn("sh", "-c", cmd)


@dataclass
class Item:
    kind: str
    title: str
    subtitle: str = ""
    icon: str = None
    gicon: object = None
    run: object = None
    score: float = 0
    big: bool = False


# --------------------------------------------------------------------------- what providers can know (the real machine; tests pass a fake)
class Facts:
    """Windows, workspaces, themes, clipboard entries, snippets and modes. Cached for a second so typing stays cheap."""

    def __init__(self, repo=None):
        self.repo = Path(repo) if repo else SCRIPTS.parents[2]
        self._cache = {}

    def _cached(self, key, fn, ttl=1.0):
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        value = fn()
        self._cache[key] = (now, value)
        return value

    @staticmethod
    def _json(*cmd):
        try:
            return json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout or "[]")
        except (OSError, ValueError, subprocess.SubprocessError):
            return []

    def clients(self):
        return self._cached("clients", lambda: [c for c in self._json("hyprctl", "clients", "-j") if c.get("mapped") and c.get("class")])

    def workspaces(self):
        return self._cached("workspaces", lambda: sorted((w for w in self._json("hyprctl", "workspaces", "-j") if w.get("id", 0) > 0), key=lambda w: w["id"]))

    def has(self, binary):
        """Is this program on PATH? Remembered for a while, so typing never runs `which` again."""
        return self._cached(("has", binary), lambda: shutil.which(binary) is not None, ttl=30.0)

    def themes(self):
        return self._cached("themes", self._read_themes, ttl=5.0)

    def _read_themes(self):
        out = []
        for conf in sorted((self.repo / "themes").glob("*/theme.conf")):
            data = {}
            for line in conf.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    data[k.strip()] = re.split(r"\s#", v)[0].strip()
            out.append({"id": conf.parent.name, "name": data.get("name", conf.parent.name), "mode": data.get("mode", "")})
        return out

    def clipboard(self):
        def read():
            if not shutil.which("cliphist"):
                return []
            try:
                text = subprocess.run(["cliphist", "list"], capture_output=True, text=True, timeout=2).stdout
            except (OSError, subprocess.SubprocessError):
                return []
            rows = []
            for line in text.splitlines()[:300]:
                ident, _, preview = line.partition("\t")
                if ident.isdigit():
                    rows.append({"id": ident, "preview": preview})
            return rows
        return self._cached("clipboard", read, ttl=2.0)

    def snippets(self):
        def read():
            try:
                import workflow_core
                return workflow_core.load()["snippets"]
            except Exception:
                return []
        return self._cached("snippets", read, ttl=2.0)

    def modes(self):
        def read():
            try:
                import modes_core
                return modes_core.load_modes()
            except Exception:
                return []
        return self._cached("modes", read, ttl=2.0)


class SampleFacts(Facts):
    """Invented windows and workspaces for documentation screenshots (PRIMO_SHOT_MODE): the real ones show your own window titles."""

    def clients(self):
        return [{"address": "0xa1", "class": "kitty", "title": "build", "workspace": {"id": 1, "name": "1"}},
                {"address": "0xa2", "class": "firefox", "title": "Sample page", "workspace": {"id": 2, "name": "2"}},
                {"address": "0xa3", "class": "obsidian", "title": "Meeting notes", "workspace": {"id": 2, "name": "2"}},
                {"address": "0xa4", "class": "code", "title": "demo", "workspace": {"id": 3, "name": "3"}}]

    def workspaces(self):
        return [{"id": 1, "windows": 1, "lastwindowtitle": "build"}, {"id": 2, "windows": 2, "lastwindowtitle": "Meeting notes"},
                {"id": 3, "windows": 1, "lastwindowtitle": "demo"}]

    def clipboard(self):
        return []

    def snippets(self):
        return []

    def modes(self):
        return []


@dataclass
class Context:
    apps: list = None          # objects with get_display_name(), get_generic_name(), get_description(), get_icon(), get_id(), get_keywords() (Gio.AppInfo)
    file_hits: list = None
    history: dict = None
    facts: object = None
    launch_app: object = None  # called with an app object

    def __post_init__(self):
        self.apps, self.file_hits, self.history = self.apps or [], self.file_hits or [], self.history or {}


# --------------------------------------------------------------------------- providers
class Provider:
    id = ""
    label = ""
    order = 50
    limit = 4
    commands = ()

    def browse(self, q):
        """True when the query is just this provider's command word, with nothing after it."""
        return q.strip().lower() in self.commands

    def query(self, q, ctx, args):
        return []


class CalculatorProvider(Provider):
    id, label, order, limit = "calc", "CALCULATOR", 0, 1

    def query(self, q, ctx, args):
        result = calculate(q)
        if result is None:
            return []
        return [Item("calc", f"= {result}", "Press Enter to copy", icon="accessories-calculator", run=lambda r=result: subprocess.run(["wl-copy", "--", r]), score=1000, big=True)]


class AppProvider(Provider):
    id, label, order, limit = "app", "APPLICATIONS", 10, 6

    def query(self, q, ctx, args):
        out = []
        for info in ctx.apps:
            name = info.get_display_name() or ""
            best = max(fuzzy(q, name), fuzzy(q, info.get_generic_name() or "") - 10, fuzzy(q, " ".join(getattr(info, "get_keywords", lambda: [])() or [])) - 25)
            if q and best <= 0:
                continue
            boost = min(ctx.history.get(info.get_id() or name, 0), 20)
            score = (best + boost) if q else boost
            if not q and boost == 0:
                continue
            out.append(Item("app", name, info.get_description() or "", gicon=info.get_icon(), run=lambda i=info: ctx.launch_app(i) if ctx.launch_app else None, score=score))
        return out


class WindowProvider(Provider):
    id, label, order, limit, commands = "window", "WINDOWS", 15, 3, ("win", "window", "windows")
    SELF = "dev.primo.Launcher"

    def query(self, q, ctx, args):
        explicit = args is not None or self.browse(q)
        text = (args or "").strip() if explicit else q
        if not explicit and (len(text) < 2 or calculate(text) is not None):
            return []
        out = []
        for c in ctx.facts.clients():
            if c["class"] == self.SELF or not re.fullmatch(r"0x[0-9a-f]+", c.get("address", "")):
                continue
            title = c.get("title") or c["class"]
            best = max(fuzzy(text, title), fuzzy(text, c["class"])) if text else 50
            if best <= 0:
                continue
            ws = c.get("workspace", {})
            out.append(Item("window", title[:80], f"{c['class']} · workspace {ws.get('name') or ws.get('id', '?')}", icon=c["class"].lower(),
                            run=lambda a=c["address"]: spawn("hyprctl", "dispatch", f'hl.dsp.focus({{ window = "address:{a}" }})'),
                            score=best - (0 if explicit else 8)))
        return out


class ActionProvider(Provider):
    id, label, order, limit = "action", "ACTIONS", 20, 4

    def __init__(self, actions, needs=None):
        self.actions, self.needs = actions, needs or {}

    def available(self, title, facts):
        need = self.needs.get(title)
        if not need:
            return True
        feature = dc.FEATURES_BY_ID.get(need)
        return all(facts.has(b) for b in ([b for b, _pkg in feature.requires] if feature else [need]))

    def query(self, q, ctx, args):
        out = []
        for sn in ctx.facts.snippets():
            best = max(fuzzy(q, sn["name"]), fuzzy(q, f"snippet {sn.get('tags', '')}") - 15)
            if q and best > 0:
                out.append(Item("action", sn["name"], sn["text"].replace("\n", " ")[:80], icon="edit-paste", score=best - 4, run=lambda sn=sn: copy_snippet(sn)))
        for m in ctx.facts.modes():
            title = f"Start {m['name']} mode"
            best = max(fuzzy(q, title), fuzzy(q, f"mode start {m['name']} {m['id']}") - 15)
            if q and best > 0:
                out.append(Item("action", title, "Opens its apps, sets power, VPN and do-not-disturb", icon=m.get("icon") or "emblem-system", score=best - 3,
                                run=lambda i=m["id"]: spawn(str(SCRIPTS / "mode.sh"), "start", i)))
        for title, sub, icon, keywords, fn in self.actions:
            best = max(fuzzy(q, title), fuzzy(q, keywords) - 15)
            if q and best > 0 and self.available(title, ctx.facts):
                out.append(Item("action", title, sub, icon=icon, run=fn, score=best - 5))
        return out


def copy_snippet(sn):
    subprocess.Popen(["wl-copy", "--", sn["text"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    spawn("notify-send", "-a", "Snippets", "-t", "2500", "-i", "edit-copy", "--", f"Copied: {sn['name']}")


class WorkspaceProvider(Provider):
    id, label, order, limit, commands = "workspace", "WORKSPACES", 25, 5, ("ws", "workspace")

    def query(self, q, ctx, args):
        if args is None and not self.browse(q):
            return []
        text = (args or "").strip()
        spaces = {w["id"]: w for w in ctx.facts.workspaces()}
        out = []

        def item(n, score):
            w = spaces.get(n)
            sub = "Empty" if not w or not w.get("windows") else f"{w['windows']} window{'s' if w['windows'] != 1 else ''}" + (f" · {w['lastwindowtitle'][:40]}" if w.get("lastwindowtitle") else "")
            return Item("workspace", f"Go to workspace {n}", sub, icon="view-grid-symbolic", score=score,
                        run=lambda n=n: spawn("hyprctl", "dispatch", f"hl.dsp.focus({{ workspace = {n} }})"))
        if text.isdigit() and 1 <= int(text) <= 99:
            out.append(item(int(text), 100))
            return out
        for n in sorted(spaces):
            w = spaces[n]
            hay = f"{n} {w.get('name', '')} {w.get('lastwindowtitle', '')}"
            if not text or fuzzy(text, hay) > 0:
                out.append(item(n, 90 - n))
        return out


class ThemeProvider(Provider):
    id, label, order, limit, commands = "theme", "THEMES", 26, 6, ("theme", "themes")

    def query(self, q, ctx, args):
        if args is None and not self.browse(q):
            return []
        text = (args or "").strip()
        out = []
        for t in ctx.facts.themes():
            best = fuzzy(text, f"{t['name']} {t['id']} {t['mode']}") if text else 50
            if best > 0 and re.fullmatch(r"[a-z0-9-]+", t["id"]):
                out.append(Item("theme", f"Switch to {t['name']}", f"{t['mode'].capitalize()} theme", icon="preferences-desktop-theme", score=best,
                                run=lambda i=t["id"]: shell(f"hypr-theme {i}")))
        return out


class ClipboardProvider(Provider):
    """Clipboard history can hold passwords, so it is only shown when you ask for it: `clip`, `clipboard` or `cb`, then a space."""
    id, label, order, limit, commands = "clipboard", "CLIPBOARD", 28, 6, ("clip", "clipboard", "cb")

    def query(self, q, ctx, args):
        if args is None:
            return []
        text = args.strip()
        out = []
        for row in ctx.facts.clipboard():
            preview = row["preview"].strip()
            image = preview.startswith("[[ binary data")
            if not row["id"].isdigit():
                continue
            if text and (image or fuzzy(text, preview) <= 0):
                continue
            title = "Image: " + re.sub(r"^\[\[ binary data |\s*\]\]$", "", preview) if image else preview[:90]
            out.append(Item("clipboard", title, "Press Enter to copy again", icon="edit-paste", score=50 - len(out),
                            run=lambda i=row["id"]: shell(f"cliphist decode {i} | wl-copy")))
        return out


class FileProvider(Provider):
    id, label, order, limit = "file", "FILES", 30, 4

    def query(self, q, ctx, args):
        out = []
        for path in ctx.file_hits:
            p = Path(path)
            out.append(Item("file", p.name, str(p.parent).replace(str(Path.home()), "~"), icon="folder" if p.is_dir() else "text-x-generic", run=lambda x=path: spawn("xdg-open", x), score=20))
        return out


class WebProvider(Provider):
    id, label, order, limit = "web", "WEB", 40, 1

    def query(self, q, ctx, args):
        if len(q) < 2 or calculate(q) is not None:
            return []
        from urllib.parse import quote
        return [Item("web", f"Search the web for “{q}”", "DuckDuckGo", icon="web-browser", score=1, run=lambda s=q: spawn("xdg-open", "https://duckduckgo.com/?q=" + quote(s)))]


ACTIONS = [
    ("Lock screen", "Lock the session", "system-lock-screen", "lock screen", lambda: shell("pidof hyprlock || hyprlock")),
    ("Sleep", "Suspend the computer", "weather-clear-night", "sleep suspend", lambda: shell("systemctl suspend")),
    ("Log out", "Asks for confirmation", "system-log-out", "log out logout exit", lambda: spawn(str(SCRIPTS / "power-menu.sh"), "logout")),
    ("Restart", "Open the power menu", "system-reboot", "restart reboot", lambda: spawn(str(SCRIPTS / "power-menu.sh"))),
    ("Shut down", "Open the power menu", "system-shutdown", "shut down poweroff shutdown", lambda: spawn(str(SCRIPTS / "power-menu.sh"))),
    ("Dark mode", "Switch to the dark theme", "weather-clear-night", "dark mode theme", lambda: shell("hypr-theme dark")),
    ("Light mode", "Switch to the light theme", "weather-clear", "light mode theme", lambda: shell("hypr-theme light")),
    ("Toggle night light", "Warm the screen colours", "preferences-system-brightness", "night light", lambda: spawn(str(SCRIPTS / "nightlight.sh"), "toggle")),
    ("Settings", "Appearance, wallpaper, displays", "primo", "settings preferences", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py")),
    ("Wallpaper", "Choose a wallpaper", "preferences-desktop-wallpaper", "wallpaper background", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py --page wallpaper")),
    ("Displays", "Resolution, scale, arrangement", "preferences-desktop-display", "display monitor resolution", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py --page displays")),
    ("VPN", "Connect, disconnect, import a .ovpn profile", "network-vpn", "vpn openvpn connect tunnel", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py --page vpn")),
    ("Health", "Is everything installed and running? Features and checks", "emblem-default", "health doctor check status features diagnose", lambda: shell(f"python3 {SCRIPTS}/primo-settings.py --page health")),
    ("Clipboard history", "Search what you copied", "edit-paste", "clipboard history paste", lambda: shell(f"python3 {SCRIPTS}/clipboard.py")),
    ("Calendar", "Month view and your plans", "x-office-calendar", "calendar date month", lambda: spawn(str(SCRIPTS / "hub.sh"), "calendar")),
    ("Reminders", "Things to do and when", "appointment-soon", "reminders todo tasks remind", lambda: spawn(str(SCRIPTS / "hub.sh"), "reminders")),
    ("Timer", "Count down, keeps running when closed", "timer", "timer countdown", lambda: spawn(str(SCRIPTS / "hub.sh"), "clock-timer")),
    ("Alarm", "Wake up, repeat on days", "alarm", "alarm wake clock", lambda: spawn(str(SCRIPTS / "hub.sh"), "clock-alarm")),
    ("Stopwatch", "Laps", "stopwatch", "stopwatch lap", lambda: spawn(str(SCRIPTS / "hub.sh"), "clock-watch")),
    ("World clock", "Time in other cities", "preferences-system-time", "world clock timezone", lambda: spawn(str(SCRIPTS / "hub.sh"), "clock-world")),
    ("Standup note", "Today's daily note: what you did, what is next", "document-edit", "standup daily note report", lambda: spawn(str(SCRIPTS / "hub.sh"), "standup")),
    ("Time report", "Where your focus time went", "office-chart-bar", "time report hours tracking", lambda: spawn(str(SCRIPTS / "hub.sh"), "report")),
    ("Focus", "Pomodoro and work hours", "timer", "focus pomodoro work hours", lambda: spawn(str(SCRIPTS / "hub.sh"), "focus")),
    ("New note", "Write something down", "document-edit", "note notes write memo", lambda: spawn(str(SCRIPTS / "hub.sh"), "new-note")),
    ("Activity", "What is running and what it costs", "utilities-system-monitor", "activity monitor processes background task manager cpu memory", lambda: spawn(str(SCRIPTS / "activity.sh"), "toggle")),
    ("Modes", "Start work, research, writing… or end the running one", "emblem-system", "mode modes start work research session", lambda: spawn(str(SCRIPTS / "mode.sh"), "menu")),
    ("End mode", "Put power, VPN and do-not-disturb back", "process-stop", "end mode stop session", lambda: spawn(str(SCRIPTS / "mode.sh"), "end")),
    ("Pick a colour", "Copy any colour from the screen", "color-select", "color colour picker eyedropper", lambda: spawn(str(SCRIPTS / "colorpicker.sh"))),
    ("Take screenshot", "Select an area", "applets-screenshooter", "screenshot capture", lambda: spawn(str(SCRIPTS / "screenshot.sh"), "area")),
]

# Actions that do nothing without a tool and are not listed until it is installed: a feature id (its required tools come from the doctor
# registry, the same list `primo features` shows) or the name of a program.
NEEDS = {"Lock screen": "hyprlock", "Toggle night light": "hyprsunset", "Pick a colour": "hyprpicker", "VPN": "vpn", "Clipboard history": "clipboard",
         "Take screenshot": "capture", "Modes": "modes", "End mode": "modes",
         **dict.fromkeys(["Calendar", "Reminders", "Timer", "Alarm", "Stopwatch", "World clock", "Standup note", "Time report", "Focus", "New note"], "hub")}

PROVIDERS = [CalculatorProvider(), AppProvider(), WindowProvider(), ActionProvider(ACTIONS, NEEDS), WorkspaceProvider(), ThemeProvider(), ClipboardProvider(), FileProvider(), WebProvider()]
KIND_LABEL = {p.id: p.label for p in PROVIDERS}


def route(q, providers=PROVIDERS):
    """(provider, args) when the query starts with a provider's command word and a space; otherwise (None, None)."""
    first, sep, rest = q.partition(" ")
    if not sep:
        return None, None
    for p in providers:
        if first.lower() in p.commands:
            return p, rest
    return None, None


def collect(text, ctx, providers=PROVIDERS, cap=MAX_RESULTS + 3):
    """Every result for a query, ordered by provider and score, a few per provider. One provider failing never breaks the rest."""
    raw = text.lstrip()
    provider, args = route(raw, providers)
    q = raw if provider else raw.strip()
    items = []
    for p in [provider] if provider else providers:
        try:
            got = p.query(q, ctx, args.strip() if provider else None)
        except Exception:
            continue
        got.sort(key=lambda i: -i.score)
        items.extend((p.order, i) for i in got[:p.limit])
    items.sort(key=lambda t: (t[0], -t[1].score))
    return [i for _o, i in items][:cap]
