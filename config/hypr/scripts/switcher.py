#!/usr/bin/env python3
"""Window switcher (Alt+Tab) in the Primo style.

Hold Alt and tap Tab to move through your windows (most recent first); release Alt to switch.
A quick tap goes straight to the previous window. Shift+Tab goes backwards, Esc cancels.

It runs as a tiny background service so the switcher appears instantly:
    switcher.py --daemon            start the service (autostart does this)
    switcher.sh next | prev         what the keybinds call (talks to the service over D-Bus)
"""
import json
import os
import subprocess
import sys
import warnings

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

import config_core as cc  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

APP_ID = "dev.primo.Switcher"
USER_CSS = os.path.expanduser("~/.config/gtk-4.0/gtk.css")

CSS = """
window.primo-switcher { background-color: @window_bg_color; }
.sw-tile { padding: 12px 14px 8px 14px; border-radius: 14px; margin: 6px; }
.sw-tile.selected { background-color: alpha(@accent_bg_color, 0.32); outline: 2px solid @accent_bg_color; outline-offset: -2px; }
.sw-name { font-size: 12px; }
.sw-title { font-weight: 700; font-size: 14px; margin: 2px 16px 14px 16px; }
.sw-ws { opacity: 0.55; font-size: 10px; }
"""


def hypr(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True)


def windows():
    raw = json.loads(hypr("clients", "-j").stdout or "[]")
    wins = [c for c in raw if c.get("mapped") and not c.get("hidden") and c["class"] != APP_ID and c["class"]]
    wins.sort(key=lambda c: c["focusHistoryID"])
    return wins


def icon_name_for(display, win):
    theme = Gtk.IconTheme.get_for_display(display)
    cls = win["class"]
    for cand in (cls, cls.lower(), cls.split(".")[-1], cls.split(".")[-1].lower(),
                 win.get("initialClass", "").lower(), win.get("initialClass", "").split(".")[-1].lower()):
        if cand and theme.has_icon(cand):
            return cand
    return "application-x-executable"


class SwitcherWindow(Adw.ApplicationWindow):
    def __init__(self, app, wins, backwards):
        super().__init__(application=app, title="Switcher")
        self.add_css_class("primo-switcher")
        self.set_decorated(False)
        self.set_resizable(False)
        self.wins = wins
        self.tiles = []
        self.committed = False
        n = len(wins)
        self.index = (n - 1 if backwards else (1 if n > 1 else 0))

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, halign=Gtk.Align.CENTER,
                           margin_top=14, margin_start=14, margin_end=14)
        display = Gdk.Display.get_default()
        row = None
        for i, w in enumerate(wins):
            if i % 7 == 0:  # up to seven tiles per row, each row centred
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2, halign=Gtk.Align.CENTER)
                rows_box.append(row)
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["sw-tile"])
            icon = Gtk.Image.new_from_icon_name(icon_name_for(display, w))
            icon.set_pixel_size(64)
            tile.append(icon)
            name = w["class"].split(".")[-1].replace("-", " ").title()
            tile.append(Gtk.Label(label=name, css_classes=["sw-name"], ellipsize=3, max_width_chars=11))
            ws = w["workspace"]["name"]
            tile.append(Gtk.Label(label=("Workspace " + ws) if not ws.startswith("special") else "Scratchpad",
                                  css_classes=["sw-ws"]))
            click = Gtk.GestureClick()
            click.connect("released", lambda *_a, k=i: self.choose(k))
            tile.add_controller(click)
            self.tiles.append(tile)
            row.append(tile)
        outer.append(rows_box)
        self.title = Gtk.Label(css_classes=["sw-title"], ellipsize=3, max_width_chars=60)
        outer.append(self.title)
        self.set_content(outer)
        self.refresh()

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key_pressed)
        keys.connect("key-released", self.on_key_released)
        self.add_controller(keys)

    IDLE_SECONDS = 4

    def bump_idle(self):
        """Close without switching after a few quiet seconds, so it can never get stuck open."""
        if getattr(self, "idle_id", 0):
            GLib.source_remove(self.idle_id)
        self.idle_id = GLib.timeout_add_seconds(self.IDLE_SECONDS, self.on_idle)

    def on_idle(self):
        self.idle_id = 0
        if not self.committed:
            self.committed = True
            self.close()
        return False

    def refresh(self):
        self.bump_idle()
        for i, t in enumerate(self.tiles):
            (t.add_css_class if i == self.index else t.remove_css_class)("selected")
        self.title.set_label(self.wins[self.index]["title"] or self.wins[self.index]["class"])

    def step(self, delta):
        if self.wins:
            self.index = (self.index + delta) % len(self.wins)
            self.refresh()

    def choose(self, i):
        self.index = i
        self.commit()

    def commit(self):
        if self.committed:
            return
        self.committed = True
        if self.wins:
            addr = self.wins[self.index]["address"]
            hypr("dispatch", f'hl.dsp.focus({{ window = "address:{addr}" }})')
        self.close()

    def alt_held(self):
        seat = Gdk.Display.get_default().get_default_seat()
        kb = seat.get_keyboard() if seat else None
        return bool(kb and (kb.get_modifier_state() & Gdk.ModifierType.ALT_MASK))

    def on_key_pressed(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            self.committed = True
            self.close()
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.commit()
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Down, Gdk.KEY_Tab):
            self.step(1)
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            self.step(-1)
        else:
            return False
        return True

    def on_key_released(self, _c, keyval, _code, _state):
        if keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R):
            self.commit()


class Service(Adw.Application):
    def __init__(self, daemon):
        super().__init__(application_id=APP_ID)
        self.daemon = daemon
        self.window = None
        self.css = None
        for name, handler in (("next", lambda *_: self.trigger(False)), ("prev", lambda *_: self.trigger(True)),
                              ("cancel", lambda *_: self.cancel()), ("quit", lambda *_: self.quit())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", handler)
            self.add_action(act)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.hold()  # stay resident: the switcher then appears instantly

    def do_activate(self):
        if self.daemon:  # first activation of the background service: stay hidden
            self.daemon = False
            return
        self.trigger(False)

    def load_css(self):
        display = Gdk.Display.get_default()
        if self.css is None:
            self.css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(display, self.css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            own = Gtk.CssProvider()
            own.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(display, own, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        if os.path.exists(USER_CSS):
            self.css.load_from_path(USER_CSS)  # pick up the current theme every time

    def trigger(self, backwards):
        if self.window is not None and self.window.get_visible():
            self.window.step(-1 if backwards else 1)
            return
        wins = windows()
        if len(wins) < 2:
            return
        self.load_css()
        self.window = SwitcherWindow(self, wins, backwards)
        self.window.present()
        # A quick tap (Alt already released by the time we are on screen) switches immediately.
        GLib.timeout_add(140, self.check_quick_tap)

    def cancel(self):
        if self.window is not None and self.window.get_visible():
            self.window.committed = True
            self.window.close()

    def check_quick_tap(self):
        w = self.window
        if os.environ.get("PRIMO_SWITCHER_KEEP"):  # debugging aid: keep it open until cancelled
            return False
        if w is not None and w.get_visible() and not w.alt_held():
            w.commit()
        return False


def main():
    cc.setup_logging("switcher")
    daemon = "--daemon" in sys.argv
    return Service(daemon).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
