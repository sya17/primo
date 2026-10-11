#!/usr/bin/env python3
"""Primo Launcher: a Spotlight-style search box.

One field for everything: applications (ranked by how often you open them), a calculator, open windows,
system actions (lock, sleep, dark mode, ...), files under your home folder and web search. Type a command
word and a space to ask one source only:

    ws 4          go to workspace 4 (just "ws" lists them)
    theme dusk    switch theme
    win firefox   find an open window
    clip token    search your clipboard history (never shown unless you ask for it)

    launcher.py --daemon         start the resident service (autostart does this)
    launcher.sh toggle           what the keybinds call (talks to the service over D-Bus)

Up/Down move, Enter opens, Esc closes. Calculator results are copied with Enter. The sources live in launcher_core.py.
"""
import logging
import os
import sys
import time
import warnings
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_core as cc  # noqa: E402
import service_core as sv  # noqa: E402
import ui_style  # noqa: E402
from launcher_core import KIND_LABEL, Context, Facts, FactsWorker, FileSearch, SampleFacts, bump_history, calculate, collect, load_history, wants_file_search  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

APP_ID = "dev.primo.Launcher"
log = logging.getLogger("primo.launcher")
USER_CSS = cc.config_home() / "gtk-4.0" / "gtk.css"

CSS = """
window.primo-launcher, window.primo-launcher.background { background: transparent; box-shadow: none; }
.ln-entry { margin: 16px 16px 8px 16px; min-height: 44px; }
.ln-row { padding: 8px 12px; margin: 1px 10px; }
.ln-sub { opacity: 0.6; }
.ln-kind { letter-spacing: 1px; margin: 10px 20px 2px 20px; }
.ln-calc { font-size: 22px; font-weight: 300; }
.ln-hint { margin: 6px 16px 10px 16px; }
"""


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
        self.alive = True
        self.used = set()
        self.search = FileSearch(lambda text, hits: GLib.idle_add(self.apply_file_hits, hits, text))
        # Windows, clipboard and the like are read by a worker; typing only ever uses what is cached.
        self.facts_worker = FactsWorker(app.facts, lambda values: GLib.idle_add(self.apply_facts, set(values)))
        self.policy = ui_style.PolicyBinding(self)       # reads the preferences now; follows the toolkit's animation setting until closed
        self.handlers = []                              # signal handlers that call back into this window: all disconnected on close (see on_close)
        self.on(self, "close-request", self.on_close)
        self.on(self, "map", lambda *_: log.debug("shown %.1f ms after it was asked for", (time.monotonic() - app.asked) * 1000))

        # The window is fixed-size and transparent; the visible card sits at its top and grows
        # downwards, so the search box never jumps while results appear (Hyprland keeps a floating
        # window's centre fixed when it resizes).
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["ln-card", "primo-card", "primo-popup"], valign=Gtk.Align.START)
        self.entry = Gtk.SearchEntry(placeholder_text="Search apps, files, math, actions…", css_classes=["ln-entry", "primo-control", "primo-title"])
        self.on(self.entry, "search-changed", self.on_changed)
        self.on(self.entry, "activate", lambda *_: self.activate_selected())
        root.append(self.entry)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, activate_on_single_click=True)
        self.listbox.set_header_func(self.header_func)
        self.on(self.listbox, "row-activated", lambda _lb, row: self.run_item(row.item))
        self.scroller = Gtk.ScrolledWindow(child=self.listbox, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                           propagate_natural_height=True, max_content_height=430)
        root.append(self.scroller)
        root.append(Gtk.Label(label="↵ Open     ↑↓ Move     Esc Close     ws  theme  win  clip", xalign=0, css_classes=["ln-hint", "primo-caption", "primo-muted"]))
        outer = Gtk.Box()
        outer.append(root)
        outer.set_hexpand(True)
        root.set_hexpand(True)
        click = Gtk.GestureClick()
        self.on(click, "pressed", lambda _g, _n, x, y: self.close() if not self.card_contains(root, x, y) else None)
        outer.add_controller(click)
        self.set_content(outer)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self.on(keys, "key-pressed", self.on_key)
        self.add_controller(keys)
        self.on(self, "notify::is-active", self.on_active_changed)
        self.rebuild("")
        if not isinstance(app.facts, SampleFacts):
            self.facts_worker.request(("clients", "snippets", "modes"))   # what the first keystroke will want
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
        if wants_file_search(text):
            GLib.timeout_add(260, self.start_file_search, text.strip(), token)
        else:
            self.search.cancel()        # shorter query, a calculation or a command word: obsolete file work stops

    def start_file_search(self, text, token):
        if token == self.query_token and self.alive:   # the user stopped typing for a moment
            self.search.search(text)
        return False

    def apply_file_hits(self, hits, text):
        if self.alive and text == self.entry.get_text().strip():   # never for an older query or a closed window
            self.file_hits = hits
            self.rebuild(self.entry.get_text(), keep_selection=True)
        return False

    def on(self, obj, signal, callback):
        """connect() that remembers the handler. A callback that refers to this window, connected on a widget the window owns, makes a cycle the
        garbage collector cannot see through (the widget's closure holds the window), so a closed window would stay in memory for good."""
        self.handlers.append((obj, obj.connect(signal, callback)))

    def on_close(self, *_):
        self.alive = False
        self.policy.close()
        for obj, handler in self.handlers:
            obj.disconnect(handler)
        self.handlers.clear()
        self.listbox.set_header_func(None)
        self.search.cancel()
        self.facts_worker.cancel()
        self.app.facts.forget("clipboard")          # previews of what you copied do not stay in memory after the window closes
        return False

    def collect(self, text):
        ctx = Context(apps=self.app.apps, file_hits=self.file_hits, history=load_history(), facts=self.app.facts, launch_app=self.launch_app)
        items = collect(text, ctx)
        self.used = self.app.facts.take_used()     # what this list depends on
        wanted = self.app.facts.take_wanted()      # what the providers used and the cache did not have fresh
        if wanted and self.alive:
            self.facts_worker.request(wanted)
        return items

    def apply_facts(self, changed):
        if self.alive and (changed & self.used):    # not for a window that closed meanwhile, nor for facts the list does not show
            self.rebuild(self.entry.get_text(), keep_selection=True)
        return False

    def rebuild(self, text, keep_selection=False):
        previous = None
        if keep_selection and self.listbox.get_selected_row():
            chosen = self.listbox.get_selected_row().item
            previous = (chosen.kind, chosen.title)
        child = self.listbox.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt
        self.items = self.collect(text)
        first = kept = None
        for it in self.items:
            row = self.make_row(it)
            self.listbox.append(row)
            first = first or row
            if kept is None and previous == (it.kind, it.title):
                kept = row                         # the first row that is the same kind and title: "Settings" the app, not the action
        if first:
            self.listbox.select_row(kept or first)
        self.scroller.set_visible(bool(self.items))

    def make_row(self, it):
        row = Gtk.ListBoxRow(css_classes=["ln-row", "primo-control"])
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
                             css_classes=["ln-calc"] if it.big else ["ln-title", "primo-body"]))
        if it.subtitle:
            col.append(Gtk.Label(label=it.subtitle, xalign=0, ellipsize=3, css_classes=["ln-sub", "primo-caption"]))
        box.append(col)
        row.set_child(box)
        return row

    def header_func(self, row, before):
        if before is None or before.item.kind != row.item.kind:
            row.set_header(Gtk.Label(label=KIND_LABEL[row.item.kind], xalign=0, css_classes=["ln-kind", "primo-caption", "primo-muted"]))
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
        self.styles = None
        self.asked = 0.0
        self.apps = []
        self.facts = SampleFacts() if os.environ.get("PRIMO_SHOT_MODE") else Facts()
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
        if self.styles is None:                  # the providers are made once; each opening only re-reads the generated stylesheet
            self.styles = ui_style.Styles(CSS)
        self.styles.reload_user(USER_CSS)

    def toggle(self):
        if self.window is not None and self.window.get_visible():
            self.window.close()
            return
        self.asked = time.monotonic()
        self.load_css()
        self.window = LauncherWindow(self)
        self.window.present()


def main():
    sv.require_session(cc.setup_logging("launcher"))
    return Service("--daemon" in sys.argv).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
