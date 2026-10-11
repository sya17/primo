#!/usr/bin/env python3
"""The launcher window with the shared interface policy: one set of style providers however often it opens, a usable window without the
generated stylesheet, the preferences and the toolkit's animation setting on the root classes, and nothing delivered to a closed window.
Needs GTK and a display (skipped without one). Windows are built but never shown; sample facts, temporary XDG folders, this process's own
Gtk.Settings only."""
import gc
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import threading
import weakref
from pathlib import Path

if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (window checks)")
    sys.exit(0)
work = Path(tempfile.mkdtemp(prefix="primo launcher window "))
for var, sub in (("XDG_CONFIG_HOME", "config"), ("XDG_STATE_HOME", "state"), ("XDG_DATA_HOME", "data"), ("XDG_CACHE_HOME", "cache")):
    os.environ[var] = str(work / sub)
os.environ["PRIMO_SHOT_MODE"] = "1"                                  # sample facts: no hyprctl, no clipboard
here = Path(__file__).resolve().parent.parent / "config" / "hypr" / "scripts"
sys.path.insert(0, str(here))
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
if not Gtk.init_check():
    print("skip: no display (window checks)")
    sys.exit(0)
import ui_core
import ui_style

loader = importlib.machinery.SourceFileLoader("launcher_app", str(here / "launcher.py"))
spec = importlib.util.spec_from_loader("launcher_app", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
assert mod.USER_CSS == work / "config" / "gtk-4.0" / "gtk.css", "the generated stylesheet is looked up through config_core"

# ---- the providers are made once, however often the launcher opens
added = []
real_add = Gtk.StyleContext.add_provider_for_display
Gtk.StyleContext.add_provider_for_display = staticmethod(lambda *a: (added.append(a[2]), real_add(*a))[1])
try:
    service = mod.Service(False)
    for _ in range(12):
        service.load_css()
    assert len(added) == 3, ("a fallback, the generated sheet and the layout rules, once", len(added))
    assert sorted(added) == sorted([Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2])
finally:
    Gtk.StyleContext.add_provider_for_display = real_add
styles = service.styles
assert styles.user.to_string().strip() == "", "no generated stylesheet: nothing loaded, and nothing raised"
mod.USER_CSS.parent.mkdir(parents=True)
mod.USER_CSS.write_text("window.primo-launcher .primo-popup { border-radius: 15px; }\n")
service.load_css()
assert "15px" in styles.user.to_string()
mod.USER_CSS.unlink()
service.load_css()
assert styles.user.to_string().strip() == "", "a removed stylesheet is dropped on the next open"
assert "primo-popup" in styles.fallback.to_string() and "@" not in "".join(c for c in styles.fallback.to_string() if c == "#"), "the fallback uses named colours, no palette"

# ---- windows: root classes from the preferences and the toolkit setting
app = Adw.Application(application_id="dev.primo.LauncherWindowTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
app.register(None)
app.facts, app.apps, app.asked = mod.SampleFacts(), [], 0.0
prefs = work / "config" / "primo" / "ui.json"
classes = lambda w: set(w.get_css_classes())
settings = Gtk.Settings.get_default()
original = settings.get_property("gtk-enable-animations")
try:
    settings.set_property("gtk-enable-animations", True)
    win = mod.LauncherWindow(app)
    assert "primo-launcher" in classes(win) and not ({"primo-reduce-motion", "primo-opaque"} & classes(win)), "defaults: nothing reduced"
    assert prefs.exists() is False, "opening the launcher never creates the preferences file"
    win.on_close()
    prefs.parent.mkdir(parents=True)
    prefs.write_text(json.dumps({"version": 1, "reduce_motion": True, "reduce_transparency": True}))
    win = mod.LauncherWindow(app)
    assert {"primo-reduce-motion", "primo-opaque"} <= classes(win), classes(win)
    win.on_close()
    prefs.write_text(json.dumps({"version": 1, "reduce_motion": False, "reduce_transparency": False}))
    settings.set_property("gtk-enable-animations", False)
    win = mod.LauncherWindow(app)
    assert "primo-reduce-motion" in classes(win) and "primo-opaque" not in classes(win), "the system setting wins over the preference"
    win.on_close()
    prefs.write_text("{ broken")
    win = mod.LauncherWindow(app)
    assert classes(win) >= {"primo-reduce-motion"} and prefs.read_text() == "{ broken", "a broken preferences file never stops the launcher"
    win.on_close()
    settings.set_property("gtk-enable-animations", True)

    # ---- the role classes are on the widgets, the old local values are gone
    win = mod.LauncherWindow(app)
    assert "primo-control" in classes(win.entry) and "primo-title" in classes(win.entry)
    win.rebuild("2+2")                                               # the search entry delays its signal; rebuild is what it calls
    row = win.listbox.get_row_at_index(0)
    assert row is not None and "primo-control" in classes(row)
    for needle in ("border-radius", "font-size: 17px", "font-size: 14px", "font-size: 11px", "@window_bg_color", "alpha("):
        assert needle not in mod.CSS, f"the launcher's own CSS must not define shared values: {needle}"
    win.on_close()

    # ---- ten rapid open/close reversals: no handler, no thread, no window left behind
    refs = []
    threads_before = threading.active_count()
    for _ in range(10):
        w = mod.LauncherWindow(app)
        w.rebuild("fire")
        w.on_close()
        w.destroy()                                                  # what GTK does after a close request that is not stopped
        assert w.policy.handler is None and w.alive is False
        refs.append(weakref.ref(w))
        del w
    # A closed launcher window is freed: its handlers are disconnected on close (a closure on a child widget that calls back into the window
    # would otherwise keep every window ever opened in memory, a resident service growing with each opening).
    for _ in range(50):
        GLib.MainContext.default().iteration(False)
    gc.collect()
    assert all(r() is None for r in refs), ("closed launcher windows are released", sum(r() is not None for r in refs))
    assert len({threading.get_ident() for _ in refs}) == 1 and threading.active_count() <= threads_before + 1, "no worker thread outlives its window"

    # ---- a closed window receives nothing, and typing and Esc work in an open one
    old = mod.LauncherWindow(app)
    old.rebuild("a")
    old.on_close()
    before = list(old.items)
    old.apply_file_hits(["/home/sample/late-result.txt"], "a")
    old.apply_facts({"clients"})
    assert old.items == before and old.file_hits == [], "stale results do not reach a closed window"
    new = mod.LauncherWindow(app)
    new.rebuild("2+2")
    assert [i.title for i in new.items][0] == "= 4", [i.title for i in new.items]
    closed = []
    new.close = lambda: closed.append(1)
    assert new.on_key(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0)) is True and closed
    new.on_close()
finally:
    settings.set_property("gtk-enable-animations", original)
print("launcher window checks passed")
