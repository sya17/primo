#!/usr/bin/env python3
"""Cross-pilot checks for the 0.5 interface foundation: the launcher and Settings under the reduced-effect preferences, the system animation
setting, rapid open/close with late callbacks, empty/error/long content, and the entry points that open Settings from the launcher.

    scripts/test-ui-foundation.py                  deterministic checks; needs no display for the stylesheet part, builds windows (never shown) with one
    scripts/test-ui-foundation.py --visual [--cycles 100]
                                                   opt-in: really opens and closes both pilots (the launcher 100 times, Settings 100 times, ten of each
                                                   as rapid reversals) on a private D-Bus session and prints what happened, with frame timings from
                                                   the windows' own frame clock. SHOWS WINDOWS on your screen. Writes nothing; prints JSON.

Fake tools and temporary HOME/XDG folders only; nothing here reaches the running desktop's services, themes or settings."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "config" / "hypr" / "scripts"
parser = argparse.ArgumentParser()
parser.add_argument("--visual", action="store_true")
parser.add_argument("--cycles", type=int, default=100)
parser.add_argument("--visual-child", help=argparse.SUPPRESS)
args = parser.parse_args()


def make_sandbox():
    """Temporary HOME/XDG, stubs for every tool a pilot may call, and the repository's theme rendered into it. Returns (work, env)."""
    work = Path(tempfile.mkdtemp(prefix="primo ui foundation "))
    repo = work / "repo"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    stubs = work / "bin"
    stubs.mkdir()
    for tool, code in (("pkill", 0), ("gsettings", 0), ("dunstctl", 0), ("swaync-client", 0), ("swayosd-server", 0), ("setsid", 0), ("notify-send", 0),
                       ("kwriteconfig6", 0), ("hyprctl", 1), ("nmcli", 1), ("pactl", 1), ("bluetoothctl", 1), ("powerprofilesctl", 1), ("pacman", 1), ("gdbus", 1),
                       ("cliphist", 1), ("wl-copy", 1), ("nmtui", 1)):          # the first group absorbs what theme-switch calls; the rest fail like a missing service
        (stubs / tool).write_text(f'#!/bin/sh\necho "Error: stub $0" >&2\nexit {code}\n')
        (stubs / tool).chmod(0o755)
    env = dict(os.environ, HOME=str(work / "home"), XDG_CONFIG_HOME=str(work / "config"), XDG_DATA_HOME=str(work / "data"), XDG_STATE_HOME=str(work / "state"),
               XDG_CACHE_HOME=str(work / "cache"), PRIMO_NO_RELOAD="1", PRIMO_LOGIN_DIR=str(work / "login"), PRIMO_SHOT_MODE="1", NO_AT_BRIDGE="1", GTK_A11Y="none")
    for sub in ("home", "config", "data", "state", "cache"):
        (work / sub).mkdir()
    (work / "home" / "Pictures" / "Wallpapers").mkdir(parents=True)
    env["PATH"] = f"{stubs}:{os.environ['PATH']}"
    env["REPO"] = str(repo)
    return work, env


def render_theme(env, theme):
    done = subprocess.run([str(Path(env["REPO"]) / "scripts" / "theme-switch"), "--no-reload", theme], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-300:]
    return (Path(env["XDG_CONFIG_HOME"]) / "gtk-4.0" / "gtk.css").read_text()


# ====================================================================================== the opt-in visual run (a child on a private session)
CHILD = r'''
import gc, importlib.machinery, importlib.util, json, os, sys, threading, time
from pathlib import Path
here = Path(os.environ["REPO"]) / "config" / "hypr" / "scripts"
sys.path.insert(0, str(here))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk
Gtk.init_check(); Adw.init()
cycles = int(sys.argv[1]); out = {}
ctx = GLib.MainContext.default()
def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        ctx.iteration(False); time.sleep(0.002)
def pss():
    import re
    return int(re.search(r"Pss:\s+(\d+) kB", open("/proc/self/smaps_rollup").read()).group(1))
def spread(v):
    v = sorted(v)
    return {"count": len(v)} if not v else {"count": len(v), "median": round(v[len(v)//2], 3), "p95": round(v[min(len(v)-1, int(len(v)*0.95))], 3), "max": round(v[-1], 3)}
class Frames:
    """Intervals between one window's own frames (the first two after it opens are counted apart) and whether the compositor reported when each
    frame was presented (GdkFrameTimings). A gap is never measured across two windows."""
    def __init__(self): self.gaps, self.opening, self.reported, self.presented, self.seen = [], [], 0, 0, set()
    def watch(self, win):
        state = {"last": None, "n": 0}
        def tick(widget, clock):
            now = clock.get_frame_time(); state["n"] += 1
            if state["last"] is not None:
                (self.opening if state["n"] <= 3 else self.gaps).append((now - state["last"]) / 1000)
            state["last"] = now
            counter = clock.get_frame_counter()
            for f in range(max(0, counter - 8), counter - 3):
                t = clock.get_timings(f)
                if t is None or (id(win), f) in self.seen: continue
                self.seen.add((id(win), f)); self.reported += 1; self.presented += bool(t.get_presentation_time())
            return GLib.SOURCE_CONTINUE
        win.add_tick_callback(tick)
def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(here / file))
    spec = importlib.util.spec_from_loader(name, loader); mod = importlib.util.module_from_spec(spec); loader.exec_module(mod); return mod

# ---- launcher: the real service, toggled the way the keybind does
lm = load("launcher_app", "launcher.py")
service = lm.Service(False)
service.register(None)
errors, shown, frames = [], 0, Frames()
threads0 = threading.active_count()
pss_start = None
def launcher_open(type_text=True):
    global shown
    service.toggle()
    w = service.window
    if w is None or not w.get_visible(): errors.append("the launcher did not open"); return None
    shown += 1; frames.watch(w)
    return w
def launcher_close():
    w = service.window
    if w is not None and w.get_visible(): service.toggle()
for i in range(cycles):
    if i == 5: gc.collect(); pss_start = pss()
    w = launcher_open()
    if w is None: continue
    pump(0.08)
    w.entry.set_text("fire" if i % 2 else "ws ")           # typing during the open
    pump(0.17)
    launcher_close(); pump(0.06)
rapid = 0
for i in range(10):                                         # ten rapid reversals: open, close, open again before anything settled
    w = launcher_open(); pump(0.02); launcher_close(); pump(0.01); rapid += 1
w = launcher_open(); pump(0.2); launcher_close(); pump(0.3)
if len([x for x in service.get_windows() if x.get_visible()]): errors.append("a launcher window is still visible after the last close")
gc.collect(); pss_end = pss(); pump(10); gc.collect(); pss_settled = pss()
out["launcher"] = {"cycles": cycles, "rapid_reversals": rapid, "opened": shown, "errors": errors, "frame_interval_ms": spread(frames.gaps), "opening_frame_interval_ms": spread(frames.opening), "frames_reported": frames.reported,
                   "with_presentation_time": frames.presented, "pss_kib": {"after_5_cycles": pss_start, "after_all": pss_end, "after_10s": pss_settled}, "extra_threads": threading.active_count() - threads0}
for w in list(service.get_windows()):
    w.destroy()

# ---- Settings: windows built and shown the way the application does, with quick page changes while their tools fail
sm = load("primo_settings", "primo-settings.py")
app = Adw.Application(application_id="dev.primo.SettingsFoundation", flags=Gio.ApplicationFlags.NON_UNIQUE); app.register(None)
errors, shown, frames = [], 0, Frames()
pages = [p for p, _t, _i in sm.PAGES]
threads0 = threading.active_count(); pss_start = None
def settings_cycle(i, gap):
    global shown
    w = sm.SettingsWindow(app, pages[i % len(pages)]); w.present(); frames.watch(w)
    pump(gap)
    if not w.get_visible(): errors.append(f"settings window {i} is not visible")
    else: shown += 1
    for k in range(1, 4):
        w.select_page(pages[(i + k) % len(pages)]); pump(0.02)
    if w.stack.get_visible_child_name() != pages[(i + 3) % len(pages)]: errors.append(f"settings {i}: the last requested page is not the one shown")
    w.close(); pump(gap / 2)
    if w.get_visible(): errors.append(f"settings window {i} stayed open after close")
for i in range(cycles):
    if i == 5: gc.collect(); pss_start = pss()
    settings_cycle(i, 0.25)
rapid = 0
for i in range(10):
    settings_cycle(i, 0.03); rapid += 1
gc.collect(); pss_end = pss(); pump(10); gc.collect(); pss_settled = pss()
out["settings"] = {"cycles": cycles, "rapid_reversals": rapid, "opened": shown, "errors": errors, "frame_interval_ms": spread(frames.gaps), "opening_frame_interval_ms": spread(frames.opening), "frames_reported": frames.reported,
                   "with_presentation_time": frames.presented, "pss_kib": {"after_5_cycles": pss_start, "after_all": pss_end, "after_10s": pss_settled}, "extra_threads": threading.active_count() - threads0}
open(os.environ["VISUAL_RESULT"], "w").write(json.dumps(out))
'''

if args.visual:
    work, env = make_sandbox()
    css = {}
    result = {"cycles": args.cycles, "themes": {}}
    sys.path.insert(0, str(ROOT / "scripts"))
    for theme in ("primo-dusk", "primo-dawn"):
        render_theme(env, theme)
        target = work / f"result-{theme}.json"           # the services a private bus starts print to its output, so the result goes through a file
        done = subprocess.run(["dbus-run-session", "--", sys.executable, "-c", CHILD, str(args.cycles)], env=dict(env, VISUAL_RESULT=str(target)),
                              capture_output=True, text=True, timeout=120 + args.cycles * 6)
        result["themes"][theme] = json.loads(target.read_text()) if target.exists() else {"error": "the visual run produced no result", "stderr": done.stderr[-600:]}
    print(json.dumps(result, indent=1))
    failed = [t for t, r in result["themes"].items() if "error" in r or r["launcher"]["errors"] or r["settings"]["errors"]]
    sys.exit(1 if failed else 0)

# ====================================================================================== deterministic checks
work, env = make_sandbox()
for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    assert env[key].startswith(str(work)), "the checks must stay in their own folder"
    os.environ[key] = env[key]
os.environ["PATH"], os.environ["PRIMO_SHOT_MODE"], os.environ["REPO"] = env["PATH"], "1", env["REPO"]
sys.path.insert(0, str(HERE))

# ---- the reduced-effect rules only remove effects; selection, focus, active and error stay defined and are never conditional on motion
for theme in ("primo-dusk", "primo-dawn"):
    css = render_theme(env, theme)
    section = css[css.index("/* ---- Primo shared UI roles"):]
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", section, flags=re.S))
    for selector, body in rules:
        declared = {d.split(":")[0].strip() for d in body.split(";") if ":" in d}
        if "primo-reduce-motion" in selector:
            assert declared <= {"transition", "animation"}, (theme, selector, declared)
        if "primo-opaque" in selector:
            assert declared <= {"background-color"}, (theme, selector, declared)
    plain = " ".join(sel for sel, _b in rules if "primo-reduce-motion" not in sel and "primo-opaque" not in sel)
    for state in (".primo-selected", ".primo-control:selected", ".primo-control:focus-visible", ".primo-active", ".primo-error", ".primo-disabled"):
        assert state in plain, (theme, state, "a state must be defined for every mode, not only when effects are on")
print("reduced-effect stylesheet checks passed")

if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (window checks)")
    sys.exit(0)
import importlib.machinery
import importlib.util
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
if not Gtk.init_check():
    print("skip: no display (window checks)")
    sys.exit(0)
Adw.init()
import ui_core
import ui_style


def load(name, file):
    loader = importlib.machinery.SourceFileLoader(name, str(HERE / file))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


lm = load("launcher_app", "launcher.py")
sm = load("primo_settings", "primo-settings.py")
sm.THEME_SWITCH = work / "bin" / "nmtui"                             # never the real theme-switch
app = Adw.Application(application_id="dev.primo.UiFoundation", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
app.facts, app.apps, app.asked = lm.SampleFacts(), [], 0.0
ctx = GLib.MainContext.default()
settings = Gtk.Settings.get_default()
animations_before = settings.get_property("gtk-enable-animations")
prefs_file = ui_core.preferences_path()


def pump(seconds, until=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not (until and until()):
        ctx.iteration(False)
        time.sleep(0.002)


def write_prefs(motion, transparency):
    prefs_file.parent.mkdir(parents=True, exist_ok=True)
    prefs_file.write_text(json.dumps({"version": 1, "reduce_motion": motion, "reduce_transparency": transparency}))


def classes(w):
    return set(w.get_css_classes())


try:
    # ---- the matrix: the two preferences and the system setting, in both pilots
    for system in (True, False):
        for motion in (False, True):
            for transparency in (False, True):
                settings.set_property("gtk-enable-animations", system)
                write_prefs(motion, transparency)
                animate = system and not motion
                launcher = lm.LauncherWindow(app)
                settings_win = sm.SettingsWindow(app, "appearance")
                for win in (launcher, settings_win):
                    got = classes(win)
                    assert ("primo-reduce-motion" in got) == (not animate) and ("primo-opaque" in got) == transparency, (system, motion, transparency, got)
                assert settings_win.stack.get_transition_duration() == (180 if animate else 0), (system, motion, transparency)
                assert settings_win.stack.get_transition_type() == (Gtk.StackTransitionType.CROSSFADE if animate else Gtk.StackTransitionType.NONE)
                launcher.on_close()
                settings_win.on_close_request()
    print("the preference matrix holds in both pilots (8 combinations)")

    # ---- entry points: every Settings page the launcher can ask for opens that page
    settings.set_property("gtk-enable-animations", True)
    write_prefs(False, False)
    import launcher_core as lc
    asked = []
    real_spawn, real_shell = lc.spawn, lc.shell
    lc.spawn = lambda *cmd: asked.append(list(cmd))
    lc.shell = lambda cmd: asked.append(["sh", "-c", cmd])
    try:
        facts_all = type("All", (lc.SampleFacts,), {"has": lambda self, b: True})()
        for entry in lc.ACTIONS:
            entry[4]()
        for word in ("audio ", "network ", "vpn ", "display ", "power ", "doctor ", "capture "):
            for item in lc.collect(word, lc.Context(facts=facts_all)):
                item.run()
    finally:
        lc.spawn, lc.shell = real_spawn, real_shell
    wanted = set()
    for cmd in asked:
        text = " ".join(cmd)
        m = re.search(r"primo-settings\.py(?:\s+|\s*'?)--page\s+([a-z]+)", text) or re.search(r"--page\s+([a-z]+)", text)
        if "primo-settings.py" in text:
            wanted.add(m.group(1) if m else "appearance")
    assert {"audio", "network", "vpn", "displays", "power", "health", "wallpaper", "appearance"} <= wanted, wanted
    known = {p for p, _t, _i in sm.PAGES}
    assert wanted <= known, ("the launcher asks for a page Settings does not have", wanted - known)
    for page in sorted(wanted):
        w = sm.SettingsWindow(app, page)
        assert w.current_page == page, (page, w.current_page)
        w.on_close_request()
    print(f"the launcher opens {len(wanted)} Settings pages by name")

    # ---- content fixtures: empty, long, a failing provider; Settings pages whose tools all fail
    win = lm.LauncherWindow(app)
    win.rebuild("")
    assert win.items == [] and not win.scroller.get_visible() or win.items == [], "an empty query is an empty list, not an error"
    win.rebuild("x" * 400)
    assert win.items and all(len(i.title) < 700 for i in win.items)
    real_providers = lc.PROVIDERS[:]
    class Boom(lc.Provider):
        id, label, order = "boom", "BOOM", 1
        def query(self, q, ctx, args): raise RuntimeError("a provider failed")
    lc.PROVIDERS.insert(0, Boom())
    lc.KIND_LABEL["boom"] = "BOOM"
    try:
        win.rebuild("2+2")
        assert [i.title for i in win.items][:1] == ["= 4"], "one failing provider does not take the others down"
    finally:
        lc.PROVIDERS[:] = real_providers
    win.on_close()
    sw = sm.SettingsWindow(app, "audio")
    pump(3, until=lambda: not any(k.startswith("audio/") for k in sw.incomplete))
    tree = []
    def walk(widget):
        child = widget.get_first_child()
        while child:
            tree.append(child)
            walk(child)
            child = child.get_next_sibling()
    walk(sw.stack)
    assert any(isinstance(w, Gtk.Button) and w.get_label() == "Try again" for w in tree), "a failed read shows its reason with a way to retry"
    sw.on_close_request()
    print("empty, long and failing content is handled")

    # ---- repeated open/close with late callbacks: nothing reaches a closed window; threads and handlers are released
    cycles = 20
    threads0 = threading.active_count()
    late = []
    for i in range(cycles):
        old = lm.LauncherWindow(app)
        old.rebuild("fire")
        GLib.timeout_add(30, lambda w=old: (w.apply_file_hits(["/home/sample/late.txt"], "fire"), w.apply_facts({"clients"}), late.append(w), False)[3])
        old.on_close()
        new = lm.LauncherWindow(app)
        new.rebuild("2+2")
        before = list(new.items)
        pump(0.06)
        assert new.items == before and new.file_hits == [], (i, "a late result reached the new window")
        assert old.items == old.items and old.file_hits == [] and old.policy.handler is None
        new.on_close()
        w = sm.SettingsWindow(app, ["audio", "network", "health", "wallpaper"][i % 4])
        w.select_page("power")
        w.select_page("displays")
        w.on_close_request()
        assert w.jobs.closed and w.thumbs.closed and w.policy.handler is None and w.current_page == "displays"
    pump(1.0)
    assert len(late) == cycles, "the delayed callbacks really ran"
    assert threading.active_count() <= threads0 + 2, ("a worker outlived its window", threads0, threading.active_count())
    print(f"{cycles} open/close cycles with late callbacks leave nothing behind")
    print("the 100-cycle visual run is opt-in: scripts/test-ui-foundation.py --visual")
finally:
    settings.set_property("gtk-enable-animations", animations_before)
print("ui foundation checks passed")
