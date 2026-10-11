#!/usr/bin/env python3
"""Overview: every workspace and its windows in one screen (SUPER+O).

Click a window to focus it, drag a window onto another workspace to move it, click an empty workspace
(or press its number) to go there, Esc closes. Runs as a small background service so it opens instantly.

    overview.py --daemon         start the service (autostart does this)
    overview.sh toggle           what the keybind calls
"""
import os
import sys
import time
import warnings

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

import config_core as cc  # noqa: E402
import overview_core as oc  # noqa: E402
import settings_jobs as sj  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

APP_ID = oc.OWN_CLASS
USER_CSS = os.path.expanduser("~/.config/gtk-4.0/gtk.css")
COLUMNS = 3

CSS = """
window.primo-overview, window.primo-overview.background { background: transparent; box-shadow: none; }
.ov-card { background-color: @window_bg_color; border: 1px solid alpha(@accent_bg_color, 0.55); }
.ov-title { font-size: 15px; font-weight: 700; margin: 14px 18px 2px 18px; }
.ov-hint { opacity: 0.55; font-size: 11px; margin: 4px 18px 14px 18px; }
.ov-notice { font-size: 11px; margin: 0 18px 10px 18px; color: @warning_color; }
.ov-group { font-weight: 700; font-size: 12px; opacity: 0.7; margin: 10px 18px 0 18px; }
.ov-search { margin: 4px 18px 6px 18px; }
.ov-keep { margin: 0 18px 10px 18px; font-size: 11px; }
.win-tile.selected { background-color: alpha(@accent_bg_color, 0.35); outline: 2px solid @accent_bg_color; outline-offset: -2px; }
.win-where { font-size: 10px; opacity: 0.55; }
.ov-loading { opacity: 0.55; font-size: 13px; margin: 60px; }
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


def icon_name_for(display, win):
    theme = Gtk.IconTheme.get_for_display(display)
    cls = win["class"]
    for cand in (cls, cls.lower(), cls.split(".")[-1], cls.split(".")[-1].lower(),
                 win.get("initialClass", "").lower()):
        if cand and theme.has_icon(cand):
            return cand
    return "application-x-executable"


class OverviewWindow(Adw.ApplicationWindow):
    """Opens at once with the last desktop it knew (or a loading note); Hyprland is read and told things by workers, never by this thread."""

    def __init__(self, app, last=None):
        super().__init__(application=app, default_width=1160, default_height=700, title="Overview")
        self.add_css_class("primo-overview")
        self.set_decorated(False)
        self.set_resizable(False)
        self.app = app
        self.view = oc.View(last)
        self.timer = None
        self.problem = ""                                # what the last action could not do, until the next one
        self.prefs = oc.load_preferences()
        self.query, self.matches, self.sel = "", [], 0
        self.selected_at = None                          # when the last selection was sent: its focus loss must not close a kept-open overview
        post = lambda fn, *args: GLib.idle_add(lambda: (fn(*args), False)[1])
        self.jobs = sj.JobOwner(post, workers=2, pending_limit=4)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["ov-card", "primo-card"], hexpand=True)
        card.append(Gtk.Label(label="Workspaces", xalign=0, css_classes=["ov-title"]))
        self.entry = Gtk.SearchEntry(placeholder_text="Search windows by title, app or workspace", css_classes=["ov-search"])
        self.entry.connect("search-changed", self.on_search)
        card.append(self.entry)
        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=10, margin_end=10)
        scroller = Gtk.ScrolledWindow(propagate_natural_height=True, max_content_height=560, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.grid)
        card.append(scroller)
        notice = Gtk.Box(spacing=8)
        self.notice = Gtk.Label(xalign=0, hexpand=True, wrap=True, css_classes=["ov-notice"])
        self.retry = Gtk.Button(label="Try again", valign=Gtk.Align.CENTER, margin_end=18)
        self.retry.connect("clicked", lambda *_: self.refresh())
        notice.append(self.notice)
        notice.append(self.retry)
        self.notice_row = notice
        notice.set_visible(False)
        card.append(notice)
        self.keep = Gtk.CheckButton(label="Close after choosing", active=self.prefs["close_after_select"], css_classes=["ov-keep"])
        self.keep.connect("toggled", self.on_keep_toggled)
        card.append(self.keep)
        card.append(Gtk.Label(label="Type to search · click a window to focus · drag it onto a workspace to move it · Alt+1–9 jump · Esc close",
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
        self.connect("close-request", self.on_close_request)
        self.set_focus(self.entry)
        self.render()
        self.refresh()
        self.timer = GLib.timeout_add_seconds(oc.REFRESH_SECONDS, self.tick)

    # ---- reading the desktop (workers)
    def refresh(self):
        """One read at a time, the newest request waits; a read in flight is not started again."""
        self.jobs.submit("overview/snapshot", lambda cancel: oc.snapshot(sj.Budget(cancel)), self.on_snapshot)

    def tick(self):
        self.refresh()
        return True

    def on_snapshot(self, result):
        if self.view.apply(result):
            self.render()
        self.show_notice()

    def show_notice(self):
        text = (f"Showing the last view. {self.view.error}." if self.view.error and self.view.snapshot else
                f"Could not read the desktop: {self.view.error}." if self.view.error else self.problem)
        self.notice.set_label(text)
        self.notice_row.set_visible(bool(text))

    def on_close_request(self, *_):
        if self.timer is not None:
            GLib.source_remove(self.timer)           # nothing refreshes while the overview is hidden
            self.timer = None
        self.jobs.invalidate_prefix("overview/")
        self.jobs.close()                            # a read still running is stopped, its child with it, and nothing it finds is shown
        self.app.last = self.view.snapshot
        return False

    @staticmethod
    def inside(widget, x, y):
        a = widget.get_allocation()
        return a.x <= x <= a.x + a.width and a.y <= y <= a.y + a.height

    # ---- content
    def clear(self):
        child = self.grid.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.grid.remove(child)
            child = nxt

    def render(self):
        snap = self.view.snapshot
        self.clear()
        if snap is None:
            self.grid.append(Gtk.Label(label="Loading workspaces…" if self.view.state == "loading" else "Nothing to show yet", css_classes=["ov-loading"]))
            return
        display = Gdk.Display.get_default()
        if self.query:
            self.render_matches(snap, display)
        else:
            self.render_groups(snap, display)

    def render_groups(self, snap, display):
        spaces = {w["id"]: w for w in snap.workspaces}
        groups = oc.group_workspaces(snap)
        for g in groups:
            if len(groups) > 1:
                self.grid.append(Gtk.Label(label=g["label"] or "Workspaces", xalign=0, css_classes=["ov-group"]))
            grid = Gtk.Grid(column_homogeneous=True)
            for i, w in enumerate(g["workspaces"]):
                grid.attach(self.make_card(w["id"], w["windows"], spaces.get(w["id"], {}).get("tiledLayout", ""), w["id"] == snap.active_workspace,
                                           snap.active_window, display, w["label"]), i % COLUMNS, i // COLUMNS, 1, 1)
            self.grid.append(grid)

    def render_matches(self, snap, display):
        previous = self.matches[self.sel]["address"] if self.matches and self.sel < len(self.matches) else None
        self.matches = oc.filter_clients(snap, self.query)
        self.sel = next((i for i, c in enumerate(self.matches) if c["address"] == previous), 0)
        if not self.matches:
            self.grid.append(Gtk.Label(label=f"No window matches “{self.query[:60]}”", css_classes=["ov-loading"]))
            return
        names = {w["id"]: w.get("name") or str(w["id"]) for w in snap.workspaces}
        for i, c in enumerate(self.matches):
            ws = c["workspace"]["id"]
            tile = self.make_tile(c, c["address"] == snap.active_window, display, f"Workspace {ws}" if names.get(ws, str(ws)) == str(ws) else names[ws])
            if i == self.sel:
                tile.add_css_class("selected")
            self.grid.append(tile)

    def make_card(self, ws_id, wins, layout, current, active_win, display, label):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["ws-card"])
        if current:
            card.add_css_class("current")
        head = Gtk.Box(spacing=8)
        head.append(Gtk.Label(label=label, xalign=0, css_classes=["ws-name"]))
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

    def make_tile(self, w, focused, display, where=""):
        tile = Gtk.Box(spacing=10, css_classes=["win-tile"] + (["focused"] if focused else []))
        icon = Gtk.Image.new_from_icon_name(icon_name_for(display, w))
        icon.set_pixel_size(32)
        tile.append(icon)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        name = w["class"].split(".")[-1].replace("-", " ").title()
        col.append(Gtk.Label(label=name, xalign=0, ellipsize=3, css_classes=["win-name"]))
        col.append(Gtk.Label(label=w.get("title") or "", xalign=0, ellipsize=3, max_width_chars=34, css_classes=["win-title"]))
        tile.append(col)
        if where:
            tile.append(Gtk.Label(label=where, valign=Gtk.Align.CENTER, css_classes=["win-where"]))

        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("released", lambda g, *_a, a=w["address"]: (g.set_state(Gtk.EventSequenceState.CLAIMED), self.focus_window(a)))
        tile.add_controller(click)

        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect("prepare", lambda *_a, a=w["address"]: Gdk.ContentProvider.new_for_value(a))
        tile.add_controller(drag)
        return tile

    # ---- actions: checked against a fresh read, then sent, all on a worker; a target that vanished says so and the view refreshes
    def act(self, work, close_when_done):
        self.problem = ""
        if close_when_done:
            self.selected_at = time.monotonic()           # a selection: the focus it moves away from here is expected
        self.jobs.submit("overview/act", lambda cancel: work(sj.Budget(cancel)), lambda out: self.on_acted(out, close_when_done))

    def on_acted(self, outcome, close_when_done):
        done = isinstance(outcome, oc.Outcome) and outcome.ok
        if done and close_when_done and self.prefs["close_after_select"]:
            self.close()
            return
        if not done:
            self.selected_at = None
            self.problem = f"Could not do that: {outcome.reason if isinstance(outcome, oc.Outcome) else outcome}."
            self.show_notice()
        self.refresh()

    def focus_window(self, address):
        self.act(lambda run: oc.focus_window(address, run), True)

    def go_workspace(self, n):
        self.act(lambda run: oc.go_workspace(n, run), True)

    def move_window(self, address, ws):
        self.act(lambda run: oc.move_window(address, ws, run), False)
        return True

    def on_search(self, entry):
        self.query = entry.get_text().strip()
        self.sel = 0
        self.render()

    def on_keep_toggled(self, button):
        self.prefs["close_after_select"] = button.get_active()
        data = dict(self.prefs)
        self.jobs.submit("overview/prefs", lambda cancel: oc.save_preferences(data), self.on_saved)

    def on_saved(self, result):
        if isinstance(result, Exception):
            self.problem = f"Could not save the setting: {result}."
            self.show_notice()

    def on_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if self.query and keyval in (Gdk.KEY_Down, Gdk.KEY_Up) and self.matches:
            self.sel = (self.sel + (1 if keyval == Gdk.KEY_Down else -1)) % len(self.matches)
            self.render()
            return True
        if self.query and keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.matches:
            self.focus_window(self.matches[self.sel]["address"])
            return True
        if Gdk.KEY_1 <= keyval <= Gdk.KEY_9 and state & Gdk.ModifierType.ALT_MASK:     # a plain digit is text for the search
            self.go_workspace(keyval - Gdk.KEY_0)
            return True
        return False

    def on_active_changed(self, *_):
        if not self.is_active():
            GLib.timeout_add(150, self.close_if_left)

    def close_if_left(self):
        if not self.is_active() and oc.closes_on_focus_loss(self.prefs["close_after_select"], self.selected_at, time.monotonic()):
            self.close()
        return False


class Service(Adw.Application):
    def __init__(self, daemon):
        super().__init__(application_id=APP_ID)
        self.daemon = daemon
        self.window = None
        self.last = None                  # the last valid desktop, so the next opening has something to show at once
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
        self.window = OverviewWindow(self, self.last)
        self.window.present()


if __name__ == "__main__":
    cc.setup_logging("overview")
    sys.exit(Service("--daemon" in sys.argv).run([sys.argv[0]]))
