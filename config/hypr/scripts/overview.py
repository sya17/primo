#!/usr/bin/env python3
"""Overview: every workspace and its windows in one screen (SUPER+O).

Click a window to focus it, drag a window onto another workspace to move it, click an empty workspace
(or press its number) to go there, Esc closes. Runs as a small background service so it opens instantly.

    overview.py --daemon         start the service (autostart does this)
    overview.sh toggle           what the keybind calls
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
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

import config_core as cc  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

APP_ID = "dev.primo.Overview"
USER_CSS = os.path.expanduser("~/.config/gtk-4.0/gtk.css")
MIN_WORKSPACES = 4
COLUMNS = 3

CSS = """
window.primo-overview, window.primo-overview.background { background: transparent; box-shadow: none; }
.ov-card { background-color: @window_bg_color; border: 1px solid alpha(@accent_bg_color, 0.55); }
.ov-title { font-size: 15px; font-weight: 700; margin: 14px 18px 2px 18px; }
.ov-hint { opacity: 0.55; font-size: 11px; margin: 4px 18px 14px 18px; }
.ws-card { background-color: alpha(@card_bg_color, 0.7); border-radius: 14px; margin: 8px; padding: 10px; min-height: 150px; }
.ws-card.current { outline: 2px solid @accent_bg_color; outline-offset: -2px; }
.ws-card.drop { background-color: alpha(@accent_bg_color, 0.25); }
.ws-name { font-weight: 700; font-size: 13px; }
.ws-layout { opacity: 0.55; font-size: 11px; }
.ws-empty { opacity: 0.4; font-size: 12px; }
.win-tile { padding: 8px 10px; border-radius: 10px; }
.win-tile:hover { background-color: alpha(@accent_bg_color, 0.25); }
.win-tile.focused { background-color: alpha(@accent_bg_color, 0.35); }
.win-name { font-size: 12px; }
.win-title { font-size: 10px; opacity: 0.55; }
"""


def hypr(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True)


def snapshot():
    clients = [c for c in json.loads(hypr("clients", "-j").stdout or "[]")
               if c.get("mapped") and not c.get("hidden") and c["class"] and c["class"] != APP_ID]
    spaces = {w["id"]: w for w in json.loads(hypr("workspaces", "-j").stdout or "[]")}
    active = json.loads(hypr("activeworkspace", "-j").stdout or "{}").get("id")
    active_win = json.loads(hypr("activewindow", "-j").stdout or "{}").get("address")
    return clients, spaces, active, active_win


def icon_name_for(display, win):
    theme = Gtk.IconTheme.get_for_display(display)
    cls = win["class"]
    for cand in (cls, cls.lower(), cls.split(".")[-1], cls.split(".")[-1].lower(),
                 win.get("initialClass", "").lower()):
        if cand and theme.has_icon(cand):
            return cand
    return "application-x-executable"


class OverviewWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, default_width=1160, default_height=700, title="Overview")
        self.add_css_class("primo-overview")
        self.set_decorated(False)
        self.set_resizable(False)
        self.app = app

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["ov-card", "primo-card"], hexpand=True)
        card.append(Gtk.Label(label="Workspaces", xalign=0, css_classes=["ov-title"]))
        self.grid = Gtk.Grid(column_homogeneous=True, margin_start=10, margin_end=10)
        card.append(self.grid)
        card.append(Gtk.Label(label="Click a window to focus · drag it onto a workspace to move it · 1–9 jump · Esc close",
                              xalign=0, css_classes=["ov-hint"]))
        outer = Gtk.Box(valign=Gtk.Align.START)
        outer.append(card)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda _g, _n, x, y: self.close() if not self.inside(card, x, y) else None)
        outer.add_controller(click)
        self.set_content(outer)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.connect("notify::is-active", self.on_active_changed)
        self.populate()

    @staticmethod
    def inside(widget, x, y):
        a = widget.get_allocation()
        return a.x <= x <= a.x + a.width and a.y <= y <= a.y + a.height

    # ---- content
    def populate(self):
        clients, spaces, active, active_win = snapshot()
        used = sorted({c["workspace"]["id"] for c in clients if c["workspace"]["id"] > 0})
        ids = sorted(set(range(1, max([MIN_WORKSPACES] + used) + 1)) | ({active} if active and active > 0 else set()))
        display = Gdk.Display.get_default()
        for i, ws_id in enumerate(ids):
            wins = [c for c in clients if c["workspace"]["id"] == ws_id]
            layout = spaces.get(ws_id, {}).get("tiledLayout", "")
            self.grid.attach(self.make_card(ws_id, wins, layout, ws_id == active, active_win, display),
                             i % COLUMNS, i // COLUMNS, 1, 1)

    def make_card(self, ws_id, wins, layout, current, active_win, display):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["ws-card"])
        if current:
            card.add_css_class("current")
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label=f"Workspace {ws_id}", xalign=0, css_classes=["ws-name"]))
        head.append(Gtk.Label(label=layout, xalign=0, hexpand=True, css_classes=["ws-layout"]))
        card.append(head)
        if not wins:
            card.append(Gtk.Label(label="Empty", css_classes=["ws-empty"], vexpand=True))
        for w in wins:
            card.append(self.make_tile(w, w["address"] == active_win, display))

        click = Gtk.GestureClick()
        click.connect("released", lambda *_a, n=ws_id: self.go_workspace(n))
        card.add_controller(click)

        drop = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop.connect("enter", lambda *_a, c=card: (c.add_css_class("drop"), Gdk.DragAction.MOVE)[1])
        drop.connect("leave", lambda *_a, c=card: c.remove_css_class("drop"))
        drop.connect("drop", lambda _t, value, _x, _y, n=ws_id: self.move_window(value, n))
        card.add_controller(drop)
        return card

    def make_tile(self, w, focused, display):
        tile = Gtk.Box(spacing=10, css_classes=["win-tile"] + (["focused"] if focused else []))
        icon = Gtk.Image.new_from_icon_name(icon_name_for(display, w))
        icon.set_pixel_size(32)
        tile.append(icon)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        name = w["class"].split(".")[-1].replace("-", " ").title()
        col.append(Gtk.Label(label=name, xalign=0, ellipsize=3, css_classes=["win-name"]))
        col.append(Gtk.Label(label=w["title"] or "", xalign=0, ellipsize=3, max_width_chars=34, css_classes=["win-title"]))
        tile.append(col)

        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("released", lambda g, *_a, a=w["address"]: (g.set_state(Gtk.EventSequenceState.CLAIMED), self.focus_window(a)))
        tile.add_controller(click)

        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", lambda *_a, a=w["address"]: Gdk.ContentProvider.new_for_value(a))
        tile.add_controller(drag)
        return tile

    # ---- actions
    def focus_window(self, address):
        hypr("dispatch", f'hl.dsp.focus({{ window = "address:{address}" }})')
        self.close()

    def go_workspace(self, n):
        hypr("dispatch", f"hl.dsp.focus({{ workspace = {n} }})")
        self.close()

    def move_window(self, address, ws):
        hypr("dispatch", f'hl.dsp.window.move({{ workspace = {ws}, window = "address:{address}" }})')
        child = self.grid.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt
        GLib.timeout_add(150, lambda: (self.populate(), False)[1])
        return True

    def on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if Gdk.KEY_1 <= keyval <= Gdk.KEY_9:
            self.go_workspace(keyval - Gdk.KEY_0)
            return True
        return False

    def on_active_changed(self, *_):
        if not self.is_active():
            GLib.timeout_add(150, lambda: (self.close() if not self.is_active() else None, False)[1])


class Service(Adw.Application):
    def __init__(self, daemon):
        super().__init__(application_id=APP_ID)
        self.daemon = daemon
        self.window = None
        self.css = None
        for name, fn in (("toggle", self.toggle), ("quit", self.quit)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda *_a, f=fn: f())
            self.add_action(act)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.hold()

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
        if os.path.exists(USER_CSS):
            self.css.load_from_path(USER_CSS)

    def toggle(self):
        if self.window is not None and self.window.get_visible():
            self.window.close()
            return
        self.load_css()
        self.window = OverviewWindow(self)
        self.window.present()


if __name__ == "__main__":
    cc.setup_logging("overview")
    sys.exit(Service("--daemon" in sys.argv).run([sys.argv[0]]))
