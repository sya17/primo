#!/usr/bin/env python3
"""Time hub: calendar, reminders, clock (world, alarm, stopwatch, timer), focus and notes. A dropdown under the bar clock.

A resident service, like the switcher: it keeps the timers, alarms and reminders running while the window is closed
and notifies you when they are due. Everything it remembers is in <state>/hub/hub.json; notes are Markdown in ~/Notes.

    hub.py --daemon        start the service (autostart does this)
    hub.sh toggle|calendar|reminders|clock|focus|notes|new-note     what the clock click and the keybinds call
"""
import os
import re
import subprocess
import sys
import threading
import time
import warnings
import zoneinfo
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hub_core as hc  # noqa: E402
import modes_core as mc  # noqa: E402
import workflow_core as wf  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

APP_ID = "dev.primo.Hub"
USER_CSS = Path.home() / ".config" / "gtk-4.0" / "gtk.css"
SOUNDS = Path("/usr/share/sounds/freedesktop/stereo")
STATUS = hc.STATE_DIR / "status.json"
TABS = [("calendar", "x-office-calendar-symbolic", "Calendar"), ("reminders", "emblem-ok-symbolic", "Reminders"),
        ("clock", "alarm-symbolic", "Clock"), ("focus", "timer-symbolic", "Focus"), ("report", "office-chart-bar-symbolic", "Report"),
        ("notes", "document-edit-symbolic", "Notes")]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

CSS = """
window.primo-hub, window.primo-hub.background { background: transparent; box-shadow: none; }
.hub-card { background-color: @window_bg_color; border-radius: 22px; border: 1px solid alpha(currentColor, 0.14);
            box-shadow: 0 8px 22px rgba(0,0,0,0.38); margin: 6px 14px 26px 14px; }
.hub-time { font-size: 38px; font-weight: 300; font-feature-settings: "tnum"; }
.hub-sep { opacity: 0.5; }
.hub-side { padding: 2px 0; }
.tagchip { padding: 3px 11px; border-radius: 999px; min-height: 0; font-size: 12px; }
.note-row { border-radius: 10px; }
.note-row.active { background-color: alpha(@accent_bg_color, 0.22); }
.hub-date { opacity: 0.65; }
.hub-h { font-size: 11px; font-weight: 700; opacity: 0.55; }
.hub-small { font-size: 11px; opacity: 0.6; }
.hub-big { font-size: 34px; font-weight: 300; font-feature-settings: "tnum"; }
.ring-text { font-size: 40px; font-weight: 300; font-feature-settings: "tnum"; }
.day { padding: 0; min-width: 0; min-height: 32px; border-radius: 999px; }
.day.other { opacity: 0.32; }
.day.today { background-color: @accent_bg_color; color: @accent_fg_color; font-weight: 700; }
.day.sel { outline: 2px solid @accent_bg_color; outline-offset: -2px; }
.day-dot { font-size: 7px; color: @accent_bg_color; }
.day.today .day-dot { color: @accent_fg_color; }
.weekday { font-size: 11px; opacity: 0.5; font-weight: 700; }
.rem-done { opacity: 0.45; }
.rem-late { color: @destructive_color; }
.chip { padding: 5px 13px; border-radius: 999px; min-height: 0; }
.hub-bar trough { min-height: 8px; border-radius: 999px; }
.hub-bar progress { min-height: 8px; border-radius: 999px; background-image: linear-gradient(to right, @accent_bg_color, @accent2_color); }
.note-title { font-weight: 700; }
.note-prev { opacity: 0.6; font-size: 12px; }
textview.note-editor { font-size: 15px; background: transparent; }
textview.note-editor text { background: transparent; }
.tzrow { padding: 10px 4px; }
.daychip { min-width: 26px; min-height: 26px; padding: 0; font-size: 11px; }
"""


# ----------------------------------------------------------------------------- small helpers
def clear(box):
    child = box.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def label(text="", css=None, xalign=0.0, **kw):
    return Gtk.Label(label=text, xalign=xalign, css_classes=[css] if css else [], **kw)


def sound(name, loop_for=0, stop=None):
    path = SOUNDS / name
    if not path.exists() or os.environ.get("PRIMO_HUB_MUTE"):   # the env var is for tests
        return

    def play():
        end = time.time() + loop_for
        while True:
            subprocess.run(["pw-play", str(path)], capture_output=True)
            if not loop_for or time.time() > end or (stop and stop.is_set()):
                return

    threading.Thread(target=play, daemon=True).start()


def notify(title, body, actions=None, on_action=None, icon="appointment-soon"):
    """A critical notification (it stays until you act on it); action buttons call on_action(name)."""
    cmd = ["notify-send", "-a", "Hub", "-u", "critical", "-i", icon]
    for name, text in (actions or []):
        cmd += ["-A", f"{name}={text}"]
    cmd += ["--", title, body]

    def run():
        try:
            out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        except OSError:
            return
        if out and on_action:
            GLib.idle_add(lambda: (on_action(out), False)[1])

    threading.Thread(target=run, daemon=True).start()


def set_dnd(on):
    if subprocess.run(["sh", "-c", "command -v swaync-client"], capture_output=True).returncode == 0:
        subprocess.run(["swaync-client", "-dn" if on else "-df"], capture_output=True)


def dnd_is_on():
    try:
        return subprocess.run(["swaync-client", "-D"], capture_output=True, text=True).stdout.strip() == "true"
    except OSError:
        return False


class Ring(Gtk.Overlay):
    """A progress ring with a big time in the middle (the focus and timer dials)."""

    def __init__(self, size=190, thick=10):
        super().__init__(halign=Gtk.Align.CENTER)
        self.fraction, self.thick = 0.0, thick
        self.area = Gtk.DrawingArea(content_width=size, content_height=size)
        self.area.set_draw_func(self.draw)
        self.set_child(self.area)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.big = label("", "ring-text", xalign=0.5)
        self.small = label("", "hub-small", xalign=0.5)
        box.append(self.big)
        box.append(self.small)
        self.add_overlay(box)

    def set(self, fraction, big, small=""):
        self.fraction = max(0.0, min(1.0, fraction))
        self.big.set_label(big)
        self.small.set_label(small)
        self.area.queue_draw()

    def draw(self, area, cr, w, h):
        import math
        import cairo
        ctx = area.get_style_context()
        fg = ctx.get_color()
        ok, a1 = ctx.lookup_color("accent_bg_color")
        ok2, a2 = ctx.lookup_color("accent2_color")
        a2 = a2 if ok2 else a1
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - self.thick
        cr.set_line_width(self.thick)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.12)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        if self.fraction > 0.002:
            grad = cairo.LinearGradient(0, 0, w, h)
            grad.add_color_stop_rgb(0, a1.red, a1.green, a1.blue)
            grad.add_color_stop_rgb(1, a2.red, a2.green, a2.blue)
            cr.set_source(grad)
            cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * self.fraction)
            cr.stroke()


def scrolled(child, height=520):
    return Gtk.ScrolledWindow(child=child, hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                              max_content_height=height)


# ----------------------------------------------------------------------------- shared reminder row
def reminder_row(app, r, now=None):
    now = now or datetime.now()
    due = datetime.fromisoformat(r["due"]) if r.get("due") else None
    row = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6)
    check = Gtk.CheckButton(active=r.get("done", False), valign=Gtk.Align.CENTER)
    check.connect("toggled", lambda b, rid=r["id"]: app.complete_reminder(rid, b.get_active()))
    col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, spacing=1)
    title = label(r["title"], "rem-done" if r.get("done") else None, wrap=True)
    sub_bits = [hc.human_due(due, now)] if due else []
    if r.get("repeat"):
        sub_bits.append("repeats " + r["repeat"])
    if r.get("tag"):
        sub_bits.append("#" + r["tag"])
    sub = label(" · ".join(sub_bits), "hub-small")
    if due and due < now and not r.get("done"):
        sub.add_css_class("rem-late")
    col.append(title)
    if sub_bits:
        col.append(sub)
    drop = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "circular"], valign=Gtk.Align.CENTER, tooltip_text="Delete")
    drop.connect("clicked", lambda *_: app.delete_reminder(r["id"]))
    row.append(check)
    row.append(col)
    row.append(drop)
    return row


def quick_add_box(app, placeholder, day=None):
    """An entry that understands 'call the bank tomorrow 14:00 #work' and shows what it understood."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    entry = Gtk.Entry(placeholder_text=placeholder, primary_icon_name="list-add-symbolic")
    hint = label("", "hub-small")
    box.append(entry)
    box.append(hint)

    def parsed():
        r = hc.parse_reminder(entry.get_text())
        if day and r["due"] is None and entry.get_text().strip():
            r["due"] = datetime.combine(day, datetime.min.time()).replace(hour=9)
        elif day and r["due"] and "today" not in entry.get_text().lower():
            pass
        return r

    def on_changed(*_):
        if not entry.get_text().strip():
            hint.set_label("")
            return
        r = parsed()
        bits = [hc.human_due(r["due"]) if r["due"] else "No date"]
        if r["repeat"]:
            bits.append("repeats " + r["repeat"])
        if r["tag"]:
            bits.append("#" + r["tag"])
        hint.set_label("→ " + " · ".join(bits))

    def on_activate(*_):
        if entry.get_text().strip():
            r = parsed()
            app.add_reminder(r["title"], r["due"], r["repeat"], r["tag"])
            entry.set_text("")

    entry.connect("changed", on_changed)
    entry.connect("activate", on_activate)
    box.entry = entry
    return box


# ----------------------------------------------------------------------------- pages
class CalendarPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.app = app
        self.today = date.today()
        self.shown = self.today.replace(day=1)
        self.sel = self.today
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=330, hexpand=False)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.append(left)
        self.append(Gtk.Separator(css_classes=["hub-sep"]))
        self.append(right)
        head = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        self.time = label("", "hub-time")
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.date = label("", "hub-date")
        self.week = label("", "hub-small")
        col.append(self.date)
        col.append(self.week)
        head.append(self.time)
        head.append(col)
        left.append(head)

        nav = Gtk.Box(spacing=4, margin_top=2)
        self.month = label("", "title-4", hexpand=True)
        prev = Gtk.Button(icon_name="go-previous-symbolic", css_classes=["flat", "circular"])
        nxt = Gtk.Button(icon_name="go-next-symbolic", css_classes=["flat", "circular"])
        today = Gtk.Button(label="Today", css_classes=["flat", "chip"])
        prev.connect("clicked", lambda *_: self.move(-1))
        nxt.connect("clicked", lambda *_: self.move(1))
        today.connect("clicked", lambda *_: self.go_today())
        for w in (self.month, today, prev, nxt):
            nav.append(w)
        left.append(nav)

        self.grid = Gtk.Grid(column_homogeneous=True, row_spacing=1, column_spacing=1)
        left.append(self.grid)
        self.day_label = label("", "title-4")
        right.append(self.day_label)
        self.events = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        ev = scrolled(self.events, 250)
        ev.set_vexpand(True)
        ev.set_propagate_natural_height(False)
        right.append(ev)
        self.adder = quick_add_box(app, "Add a reminder for this day…")
        right.append(self.adder)
        self.refresh()

    def move(self, step):
        y, m = self.shown.year, self.shown.month + step
        y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
        self.shown = date(y, m, 1)
        self.build_grid()

    def go_today(self):
        self.today = date.today()
        self.shown, self.sel = self.today.replace(day=1), self.today
        self.refresh()

    def pick(self, d):
        self.sel = d
        if (d.year, d.month) != (self.shown.year, self.shown.month):
            self.shown = d.replace(day=1)
        self.refresh()

    def build_grid(self):
        clear(self.grid)
        self.month.set_label(self.shown.strftime("%B %Y"))
        for i, name in enumerate(DAYS):
            self.grid.attach(label(name, "weekday", xalign=0.5), i, 0, 1, 1)
        busy = {datetime.fromisoformat(r["due"]).date() for r in self.app.store["reminders"] if r.get("due") and not r.get("done")}
        for o in self.app.ics_events:
            busy.add(o["start"].date())
        start = self.shown - timedelta(days=self.shown.weekday())
        for i in range(42):
            d = start + timedelta(days=i)
            btn = Gtk.Button(css_classes=["flat", "day"], halign=Gtk.Align.CENTER, width_request=36)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            col.append(label(str(d.day), xalign=0.5))
            dot = label("●", "day-dot", xalign=0.5)
            dot.set_opacity(1 if d in busy else 0)
            col.append(dot)
            btn.set_child(col)
            if d.month != self.shown.month:
                btn.add_css_class("other")
            if d == self.today:
                btn.add_css_class("today")
            if d == self.sel:
                btn.add_css_class("sel")
            btn.connect("clicked", lambda _b, dd=d: self.pick(dd))
            self.grid.attach(btn, i % 7, i // 7 + 1, 1, 1)

    def refresh(self):
        self.build_grid()
        self.day_label.set_label(self.sel.strftime("%A, %d %B"))
        clear(self.events)
        meetings = [o for o in self.app.ics_events if o["start"].date() <= self.sel <= max(o["start"].date(), (o["end"] - timedelta(seconds=1)).date())]
        for o in meetings:
            row = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6)
            row.append(Gtk.Image(icon_name="x-office-calendar-symbolic", valign=Gtk.Align.CENTER, opacity=0.7))
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, spacing=1)
            col.append(label(o["title"], wrap=True))
            when = "All day" if o["allday"] else f"{o['start']:%H:%M} to {o['end']:%H:%M}"
            col.append(label(" · ".join(x for x in (when, o["location"], o.get("calendar", "")) if x), "hub-small", wrap=True))
            row.append(col)
            self.events.append(row)
        items = sorted((r for r in self.app.store["reminders"] if r.get("due") and datetime.fromisoformat(r["due"]).date() == self.sel),
                       key=lambda r: r["due"])
        for r in items:
            self.events.append(reminder_row(self.app, r))
        if not items and not meetings:
            self.events.append(label("Nothing planned", "hub-small", margin_top=2, margin_bottom=6))
        self.adder.entry.set_placeholder_text(f"Add a reminder for {self.sel.strftime('%d %b')}…")

    def tick(self):
        now = datetime.now()
        self.time.set_label(now.strftime("%H:%M"))
        self.date.set_label(now.strftime("%A, %d %B"))
        self.week.set_label(f"{now.year} · week {now.isocalendar()[1]}")
        if now.date() != self.today:
            self.go_today()


class RemindersPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.app = app
        self.filter = None
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, width_request=290, hexpand=False)
        self.adder = quick_add_box(app, "Call the bank tomorrow 14:00 #work")
        left.append(self.adder)
        left.append(label("Try “in 30m”, “besok jam 9”, “every weekday 9:30”, or add #tag.", "hub-small", wrap=True))
        self.counts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6)
        left.append(self.counts)
        self.tags = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=6, row_spacing=6, max_children_per_line=4)
        left.append(self.tags)
        self.append(left)
        self.append(Gtk.Separator(css_classes=["hub-sep"]))
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        scroll = scrolled(self.body, 360)
        scroll.set_hexpand(True)
        scroll.set_vexpand(True)
        scroll.set_propagate_natural_height(False)
        self.append(scroll)
        self.refresh()

    def set_filter(self, tag):
        self.filter = None if tag == self.filter else tag
        self.refresh()

    def refresh(self):
        clear(self.body)
        clear(self.counts)
        now = datetime.now()
        rems = self.app.store["reminders"]
        tags = sorted({r["tag"] for r in rems if r.get("tag")})
        clear(self.tags)
        for tag in tags:
            b = Gtk.ToggleButton(label="#" + tag, active=(self.filter == tag), css_classes=["tagchip"])
            b.connect("clicked", lambda _b, t=tag: self.set_filter(t))
            self.tags.append(b)
        if self.filter and self.filter not in tags:
            self.filter = None
        if self.filter:
            rems = [r for r in rems if r.get("tag") == self.filter]
        open_ = [r for r in rems if not r.get("done")]
        sections = [("OVERDUE", [r for r in open_ if r.get("due") and datetime.fromisoformat(r["due"]) < now]),
                    ("TODAY", [r for r in open_ if r.get("due") and datetime.fromisoformat(r["due"]).date() == now.date()
                               and datetime.fromisoformat(r["due"]) >= now]),
                    ("LATER", [r for r in open_ if r.get("due") and datetime.fromisoformat(r["due"]).date() > now.date()]),
                    ("NO DATE", [r for r in open_ if not r.get("due")]),
                    ("DONE", [r for r in rems if r.get("done")][-8:])]
        shown = False
        for title, items in sections:
            if items and title != "DONE":
                row = Gtk.Box(spacing=8)
                row.append(label(title.title(), "hub-small", hexpand=True))
                row.append(label(str(len(items)), "hub-small"))
                self.counts.append(row)
            if not items:
                continue
            shown = True
            self.body.append(label(f"{title}  {len(items)}", "hub-h", margin_top=10, margin_bottom=2))
            for r in sorted(items, key=lambda r: r.get("due") or "9"):
                self.body.append(reminder_row(self.app, r, now))
        if not shown:
            self.body.append(label("Nothing here yet. Type a reminder on the left: a time, a day, or both.", "hub-small", wrap=True, margin_top=14))

    def tick(self):
        pass


class ClockPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.app = app
        self.tabs = Adw.ToggleGroup(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START, width_request=150)
        for name, text, icon in (("world", "World", "find-location-symbolic"), ("alarm", "Alarm", "alarm-symbolic"),
                                 ("watch", "Stopwatch", "stopwatch-symbolic"), ("timer", "Timer", "timer-symbolic")):
            self.tabs.add(Adw.Toggle(name=name, label=text, icon_name=icon))
        self.append(self.tabs)
        self.append(Gtk.Separator(css_classes=["hub-sep"]))
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.world = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.alarm = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.watch = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.timer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for name, w in (("world", self.world), ("alarm", self.alarm), ("watch", self.watch), ("timer", self.timer)):
            inner = scrolled(w, 360)
            inner.set_propagate_natural_height(False)
            self.stack.add_named(inner, name)
        self.stack.set_hexpand(True)
        self.append(self.stack)
        self.tabs.set_active_name(app.store["last_tab"] if app.store["last_tab"] in ("world", "alarm", "watch", "timer") else "world")
        self.tabs.connect("notify::active-name", lambda g, _p: self.switch(g.get_active_name()))
        self.build_watch()
        self.build_timer()
        self.switch(self.tabs.get_active_name())

    def switch(self, name):
        self.stack.set_visible_child_name(name)
        self.refresh()

    def refresh(self):
        self.build_world()
        self.build_alarm()
        self.refresh_timers()
        self.tick()

    # ---- world clocks
    def zone_names(self):
        return sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "posix", "right", "SystemV", "US/")))

    def build_world(self):
        clear(self.world)
        local = datetime.now().astimezone()
        zones = [("Here", local.tzinfo)] + [(z.split("/")[-1].replace("_", " "), zoneinfo.ZoneInfo(z)) for z in self.app.store["world"]]
        self.world_labels = []
        for i, (name, tz) in enumerate(zones):
            row = Gtk.Box(spacing=10, css_classes=["tzrow"])
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            col.append(label(name, "heading"))
            sub = label("", "hub-small")
            col.append(sub)
            big = label("", "hub-big", xalign=1)
            row.append(col)
            row.append(big)
            if i > 0:
                drop = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "circular"], valign=Gtk.Align.CENTER)
                drop.connect("clicked", lambda _b, z=self.app.store["world"][i - 1]: self.app.remove_zone(z))
                row.append(drop)
            self.world.append(row)
            self.world_labels.append((tz, sub, big))
        pop = Gtk.Popover()
        pbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        search = Gtk.SearchEntry(placeholder_text="City or region, e.g. Tokyo", width_request=260)
        results = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        pbox.append(search)
        pbox.append(Gtk.ScrolledWindow(child=results, min_content_height=200, max_content_height=240, hscrollbar_policy=Gtk.PolicyType.NEVER))
        pop.set_child(pbox)
        names = self.zone_names()

        def fill(*_):
            clear(results)
            q = search.get_text().strip().lower().replace(" ", "_")
            for z in [n for n in names if q in n.lower()][:40] if q else []:
                b = Gtk.Button(label=z.replace("_", " "), css_classes=["flat"], halign=Gtk.Align.START)
                b.connect("clicked", lambda _b, zz=z: (pop.popdown(), self.app.add_zone(zz)))
                results.append(b)

        search.connect("search-changed", fill)
        pop.connect("notify::visible", lambda p, _x: self.app.hold_open(p.get_visible()))
        add = Gtk.MenuButton(child=Adw.ButtonContent(label="Add a city", icon_name="list-add-symbolic"), popover=pop,
                             css_classes=["flat"], halign=Gtk.Align.CENTER, margin_top=6)
        self.world.append(add)

    # ---- alarms
    def build_alarm(self):
        clear(self.alarm)
        alarms = sorted(self.app.store["alarms"], key=lambda a: a["time"])
        for a in alarms:
            row = Gtk.Box(spacing=10, css_classes=["tzrow"])
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            col.append(label(a["time"], "hub-big"))
            days = "Once" if not a["days"] else ("Every day" if len(a["days"]) == 7 else " ".join(DAYS[d] for d in a["days"]))
            col.append(label(days + (" · " + a["label"] if a.get("label") else ""), "hub-small"))
            click = Gtk.GestureClick()
            click.connect("released", lambda *_a, al=a: self.edit_alarm(al))
            col.add_controller(click)
            sw = Gtk.Switch(active=a.get("on", True), valign=Gtk.Align.CENTER)
            sw.connect("notify::active", lambda s, _p, al=a: self.app.set_alarm_on(al["id"], s.get_active()))
            row.append(col)
            row.append(sw)
            self.alarm.append(row)
        if not alarms:
            self.alarm.append(label("No alarms. They ring even when this window is closed.", "hub-small", margin_top=12, margin_bottom=8, wrap=True))
        add = Gtk.Button(child=Adw.ButtonContent(label="New alarm", icon_name="list-add-symbolic"), css_classes=["flat"],
                         halign=Gtk.Align.CENTER, margin_top=6)
        add.connect("clicked", lambda *_: self.edit_alarm(None))
        self.alarm.append(add)

    def edit_alarm(self, alarm):
        h0, m0 = (int(x) for x in (alarm["time"] if alarm else (datetime.now() + timedelta(minutes=30)).strftime("%H:%M")).split(":"))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        times = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        minute = Gtk.SpinButton.new_with_range(0, 59, 1)
        for sp, v in ((hour, h0), (minute, m0)):
            sp.set_value(v)
            sp.set_wrap(True)
            sp.set_numeric(True)
            sp.set_orientation(Gtk.Orientation.VERTICAL)
            sp.connect("output", lambda s: (s.set_text(f"{int(s.get_value()):02d}"), True)[1])
        times.append(hour)
        times.append(label(":", "hub-big", xalign=0.5))
        times.append(minute)
        box.append(times)
        days = Gtk.Box(spacing=4, halign=Gtk.Align.CENTER)
        toggles = []
        for i, name in enumerate(DAYS):
            t = Gtk.ToggleButton(label=name[0], active=bool(alarm and i in alarm["days"]), css_classes=["circular"], tooltip_text=name)
            toggles.append(t)
            days.append(t)
        box.append(days)
        name_entry = Gtk.Entry(placeholder_text="Label (optional)", text=alarm.get("label", "") if alarm else "")
        box.append(name_entry)
        dialog = Adw.AlertDialog(heading="Alarm" if alarm else "New alarm")
        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        if alarm:
            dialog.add_response("delete", "Delete")
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def answered(_d, response):
            self.app.hold_open(False)
            if response == "save":
                self.app.save_alarm(alarm["id"] if alarm else None, f"{int(hour.get_value()):02d}:{int(minute.get_value()):02d}",
                                    [i for i, t in enumerate(toggles) if t.get_active()], name_entry.get_text().strip())
            elif response == "delete":
                self.app.delete_alarm(alarm["id"])

        dialog.connect("response", answered)
        self.app.hold_open(True)
        dialog.present(self.get_root())

    # ---- stopwatch
    def build_watch(self):
        self.watch_big = label("00:00.00", "hub-time", xalign=0.5, margin_top=14)
        self.watch.append(self.watch_big)
        row = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        self.watch_go = Gtk.Button(label="Start", css_classes=["pill", "suggested-action"])
        self.watch_lap = Gtk.Button(label="Lap", css_classes=["pill"])
        self.watch_go.connect("clicked", lambda *_: (self.app.watch_toggle(), self.refresh_watch()))
        self.watch_lap.connect("clicked", lambda *_: (self.app.watch_lap(), self.refresh_watch()))
        row.append(self.watch_lap)
        row.append(self.watch_go)
        self.watch.append(row)
        self.laps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6)
        self.watch.append(scrolled(self.laps, 200))

    def watch_text(self):
        s = self.app.store["stopwatch"]
        total = s["elapsed"] + (time.time() - s["start"] if s["running"] else 0)
        m, rest = divmod(total, 60)
        h, m = divmod(int(m), 60)
        txt = f"{int(m):02d}:{rest:05.2f}"
        return f"{h}:{txt}" if h else txt

    def refresh_watch(self):
        s = self.app.store["stopwatch"]
        self.watch_go.set_label("Stop" if s["running"] else "Start")
        self.watch_lap.set_label("Lap" if s["running"] else "Reset")
        self.watch_lap.set_sensitive(s["running"] or s["elapsed"] > 0)
        clear(self.laps)
        prev = 0.0
        for i, t in enumerate(s["laps"], 1):
            row = Gtk.Box(spacing=8)
            row.append(label(f"Lap {i}", "hub-small", hexpand=True))
            row.append(label(f"+{t - prev:.2f}s", "hub-small"))
            row.append(label(f"{int(t // 60):02d}:{t % 60:05.2f}"))
            self.laps.append(row)
            prev = t
        self.watch_big.set_label(self.watch_text())

    # ---- timers
    def build_timer(self):
        presets = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6, min_children_per_line=3,
                              column_spacing=6, row_spacing=6, homogeneous=True, margin_top=6)
        for minutes in (1, 5, 10, 15, 25, 45):
            b = Gtk.Button(label=f"{minutes} min", css_classes=["chip"])
            b.connect("clicked", lambda _b, m=minutes: self.app.add_timer(m * 60))
            presets.append(b)
        self.timer.append(presets)
        custom = Gtk.Entry(placeholder_text="Custom: 90s, 12m, 1h30, 25:00", primary_icon_name="alarm-symbolic")

        def go(*_):
            secs = parse_duration(custom.get_text())
            if secs:
                self.app.add_timer(secs)
                custom.set_text("")

        custom.connect("activate", go)
        self.timer.append(custom)
        self.timer_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=4)
        self.timer.append(self.timer_list)

    def refresh_timers(self):
        clear(self.timer_list)
        self.timer_rows = []
        for t in self.app.store["timers"]:
            row = Gtk.Box(spacing=10, css_classes=["tzrow"])
            ring = Ring(size=64, thick=6)
            ring.big.remove_css_class("ring-text")
            row.append(ring)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
            big = label("", "hub-big")
            col.append(big)
            col.append(label(f"of {hc.fmt_clock(t['total'])}", "hub-small"))
            row.append(col)
            pause = Gtk.Button(icon_name="media-playback-pause-symbolic" if t.get("left") is None else "media-playback-start-symbolic",
                               css_classes=["flat", "circular"], valign=Gtk.Align.CENTER)
            pause.connect("clicked", lambda _b, tid=t["id"]: self.app.pause_timer(tid))
            stop = Gtk.Button(icon_name="window-close-symbolic", css_classes=["flat", "circular"], valign=Gtk.Align.CENTER, tooltip_text="Cancel")
            stop.connect("clicked", lambda _b, tid=t["id"]: self.app.cancel_timer(tid))
            row.append(pause)
            row.append(stop)
            self.timer_list.append(row)
            self.timer_rows.append((t, ring, big))
        if not self.app.store["timers"]:
            self.timer_list.append(label("Pick a time. The timer keeps running when this window is closed.", "hub-small", wrap=True))

    def tick(self):
        local = datetime.now().astimezone()
        for tz, sub, big in getattr(self, "world_labels", []):
            now = datetime.now(tz)
            big.set_label(now.strftime("%H:%M"))
            diff = (now.utcoffset() - local.utcoffset()).total_seconds() / 3600
            sub.set_label(("Today" if now.date() == local.date() else ("Tomorrow" if now.date() > local.date() else "Yesterday"))
                          + (f", {diff:+g}h" if diff else ""))
        for t, ring, big in getattr(self, "timer_rows", []):
            left = t["left"] if t.get("left") is not None else max(0, t["end"] - time.time())
            big.set_label(hc.fmt_clock(left))
            ring.set(left / max(t["total"], 1), "", "")
        if self.stack.get_visible_child_name() == "watch":
            self.refresh_watch()


def parse_duration(text):
    """'90s', '12m', '1h30', '1h 30m', '25:00', '5' (minutes) -> seconds, or 0."""
    t = text.strip().lower().replace(" ", "")
    if not t:
        return 0
    m = re.fullmatch(r"(\d+):(\d{2})(?::(\d{2}))?", t)
    if m:
        a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
        return a * 3600 + b * 60 + int(c) if c else a * 60 + b
    m = re.fullmatch(r"(?:(\d+)h(?:ours?|r)?)?(?:(\d+)m(?:in(?:utes?)?)?)?(?:(\d+)s(?:ec(?:onds?)?)?)?", t)
    if m and any(m.groups()):
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
    m = re.fullmatch(r"(\d+)h(\d+)", t)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60
    return int(t) * 60 if t.isdigit() else 0


class FocusPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.app = app
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, width_request=290, valign=Gtk.Align.CENTER, hexpand=False)
        self.ring = Ring(size=200, thick=11)
        left.append(self.ring)
        row = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        self.go = Gtk.Button(css_classes=["pill", "suggested-action"])
        self.skip = Gtk.Button(label="Skip", css_classes=["pill"])
        self.reset = Gtk.Button(label="Reset", css_classes=["pill"])
        self.go.connect("clicked", lambda *_: app.focus_toggle())
        self.skip.connect("clicked", lambda *_: app.focus_skip())
        self.reset.connect("clicked", lambda *_: app.focus_reset())
        for b in (self.reset, self.go, self.skip):
            row.append(b)
        left.append(row)
        what = Gtk.Box(spacing=6, margin_top=4)
        self.what = Gtk.Entry(placeholder_text="What are you working on?", hexpand=True, primary_icon_name="document-edit-symbolic")
        self.cat = Gtk.DropDown.new_from_strings(hc.CATEGORIES)
        self.what.connect("changed", lambda *_: self.on_what())
        self.cat.connect("notify::selected", lambda *_: self.on_what())
        what.append(self.what)
        what.append(self.cat)
        left.append(what)
        self.append(left)
        self.append(Gtk.Separator(css_classes=["hub-sep"]))
        self.syncing = False
        self.sync_what()

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll = scrolled(body, 360)
        scroll.set_hexpand(True)
        scroll.set_propagate_natural_height(False)
        self.append(scroll)
        work = app.store["work"]
        pomo = app.store["pomodoro"]

        # work day
        day = Adw.PreferencesGroup(title="Work day")
        self.work_status = Adw.ActionRow(title="Right now", subtitle="")
        self.work_bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=110, css_classes=["hub-bar"])
        self.work_status.add_suffix(self.work_bar)
        day.add(self.work_status)
        days_row = Adw.ActionRow(title="Days")
        dbox = Gtk.Box(spacing=3, valign=Gtk.Align.CENTER)
        for i, name in enumerate(DAYS):
            t = Gtk.ToggleButton(label=name[0], active=i in work["days"], css_classes=["circular", "daychip"], tooltip_text=name)
            t.connect("toggled", lambda b, d=i: self.set_day(d, b.get_active()))
            dbox.append(t)
        days_row.add_suffix(dbox)
        day.add(days_row)
        for key, title in (("start", "Starts"), ("end", "Ends")):
            entry = Adw.EntryRow(title=title, text=work[key], show_apply_button=True)
            entry.connect("apply", lambda e, k=key: self.set_time(e, k))
            day.add(entry)
        end_on = Adw.SwitchRow(title="Tell me before the day ends", subtitle=f"{work['end_notice']} minutes before", active=work["end_on"])
        end_on.connect("notify::active", lambda r, _p: self.set_work("end_on", r.get_active()))
        brk = Adw.SwitchRow(title="Remind me to take a break", subtitle=f"Every {work['break_every']} minutes while working", active=work["break_on"])
        brk.connect("notify::active", lambda r, _p: self.set_work("break_on", r.get_active()))
        day.add(end_on)
        day.add(brk)
        body.append(day)

        # vpn
        self.vpn_group = Adw.PreferencesGroup(title="VPN")
        self.vpn_rows = []
        body.insert_child_after(self.vpn_group, None)
        self.vpn_busy = False
        self.refresh_vpn()

        # mode
        mg = Adw.PreferencesGroup(title="Mode", description="Sets up apps, VPN, power and do-not-disturb for what you are about to do")
        self.mode_row = Adw.ActionRow(title="None running", subtitle="")
        self.mode_btn = Gtk.Button(valign=Gtk.Align.CENTER, css_classes=["pill"])
        self.mode_btn.connect("clicked", lambda *_: self.mode_click())
        self.mode_row.add_suffix(self.mode_btn)
        mg.add(self.mode_row)
        body.insert_child_after(mg, None)

        # pomodoro settings
        pg = Adw.PreferencesGroup(title="Focus sessions")
        for key, title, lo, hi in (("focus", "Focus", 5, 120), ("short", "Short break", 1, 30), ("long", "Long break", 5, 60), ("cycles", "Sessions before a long break", 2, 8)):
            spin = Adw.SpinRow.new_with_range(lo, hi, 1)
            spin.set_title(title)
            spin.set_value(pomo[key])
            spin.connect("notify::value", lambda r, _p, k=key: self.set_pomo(k, int(r.get_value())))
            pg.add(spin)
        dnd = Adw.SwitchRow(title="Do not disturb while focusing", subtitle="Mutes notifications during focus sessions", active=work["dnd_focus"])
        dnd.connect("notify::active", lambda r, _p: self.set_work("dnd_focus", r.get_active()))
        pg.add(dnd)
        body.append(pg)
        self.tick()

    def refresh_vpn(self):
        def work():
            def nm(*a):
                try:
                    return subprocess.run(["nmcli", "-t", *a], capture_output=True, text=True, timeout=6).stdout.splitlines()
                except (OSError, subprocess.SubprocessError):
                    return []
            active = {l.split(":")[0] for l in nm("-f", "NAME,TYPE", "connection", "show", "--active") if l.split(":")[-1] in ("vpn", "wireguard")}
            names = [l.rsplit(":", 1)[0].replace("\\:", ":") for l in nm("-f", "NAME,TYPE", "connection", "show") if l.rsplit(":", 1)[-1] in ("vpn", "wireguard")]
            GLib.idle_add(self.apply_vpn, sorted(names), active)

        threading.Thread(target=work, daemon=True).start()

    def apply_vpn(self, names, active):
        for r in self.vpn_rows:
            self.vpn_group.remove(r)
        self.vpn_rows = []
        self.vpn_group.set_visible(bool(names))
        for name in names:
            row = Adw.ActionRow(title=GLib.markup_escape_text(name), subtitle="Connected" if name in active else "Off")
            sw = Gtk.Switch(active=name in active, valign=Gtk.Align.CENTER)
            sw.connect("state-set", lambda w, state, n=name: self.vpn_toggle(w, state, n))
            row.add_suffix(sw)
            self.vpn_group.add(row)
            self.vpn_rows.append(row)
        return False

    def vpn_toggle(self, sw, state, name):
        if self.vpn_busy:
            return True
        self.vpn_busy = True

        def work():
            subprocess.run(["nmcli", "--wait", "45", "connection", "up" if state else "down", "id", name], capture_output=True)
            subprocess.run(["pkill", "-RTMIN+13", "waybar"], capture_output=True)
            self.vpn_busy = False
            GLib.idle_add(self.refresh_vpn)

        threading.Thread(target=work, daemon=True).start()
        return False

    def sync_what(self):
        """Show the label of the running session (a mode may have set it), else the one for the next session."""
        s = self.app.store["session"]
        src = s if s["phase"] != "idle" and s.get("label") else self.app.store["focus"]
        self.syncing = True
        if not self.what.has_focus() and self.what.get_text() != (src.get("label") or ""):
            self.what.set_text(src.get("label") or "")
        cat = src.get("category") or "Work"
        if cat in hc.CATEGORIES:
            self.cat.set_selected(hc.CATEGORIES.index(cat))
        self.syncing = False

    def on_what(self):
        if self.syncing:
            return
        label_text, cat = self.what.get_text(), hc.CATEGORIES[self.cat.get_selected()]
        self.app.store["focus"] = {"label": label_text, "category": cat}
        s = self.app.store["session"]
        if s["phase"] != "idle":
            s["label"], s["category"] = label_text, cat
        self.app.save()

    def mode_click(self):
        script = HERE / "modes.py"
        subprocess.Popen([sys.executable, str(script), "end" if mc.current() else "menu"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)

    def set_day(self, d, on):
        days = set(self.app.store["work"]["days"])
        (days.add if on else days.discard)(d)
        self.set_work("days", sorted(days))

    def set_time(self, entry, key):
        text = entry.get_text().strip()
        if re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", text):
            self.set_work(key, f"{int(text.split(':')[0]):02d}:{text.split(':')[1]}")
            entry.remove_css_class("error")
        else:
            entry.add_css_class("error")

    def set_work(self, key, value):
        self.app.store["work"][key] = value
        self.app.save()

    def set_pomo(self, key, value):
        self.app.store["pomodoro"][key] = value
        self.app.save()

    def refresh(self):
        self.tick()

    def tick(self):
        s = self.app.store["session"]
        cfg = self.app.store["pomodoro"]
        self.sync_what()
        if s["phase"] == "idle":
            self.ring.set(0, f"{cfg['focus']:02d}:00", "Ready to focus")
            self.go.set_label("Start")
            self.skip.set_sensitive(False)
            self.reset.set_sensitive(False)
        else:
            left = s["left"] if s["left"] is not None else max(0, s["end"] - time.time())
            total = {"focus": cfg["focus"], "short": cfg["short"], "long": cfg["long"]}[s["phase"]] * 60
            names = {"focus": f"Focus · {s['cycle'] + 1} of {cfg['cycles']}", "short": "Short break", "long": "Long break"}
            self.ring.set(left / max(total, 1), hc.fmt_clock(left), names[s["phase"]] + (" · paused" if s["left"] is not None else ""))
            self.go.set_label("Resume" if s["left"] is not None else "Pause")
            self.skip.set_sensitive(True)
            self.reset.set_sensitive(True)
        st = mc.current()
        if st:
            self.mode_row.set_title(st["name"])
            self.mode_row.set_subtitle(f"Running for {mc.elapsed(st) // 60} min" + (f" · {Path(st['dir']).name}" if st["dir"] else ""))
            self.mode_btn.set_label("End")
        else:
            self.mode_row.set_title("None running")
            self.mode_row.set_subtitle("Work, research, writing, relax… your own in Settings")
            self.mode_btn.set_label("Choose…")
        w = hc.work_state(self.app.store["work"])
        if w["working"]:
            self.work_status.set_subtitle(f"Working · {w['left'] // 60}h {w['left'] % 60:02d}m left")
            self.work_bar.set_fraction(w["progress"])
        else:
            nxt = w["next"].strftime("%a %H:%M") if w["next"] else "no work days set"
            self.work_status.set_subtitle(f"Off the clock · next start {nxt}")
            self.work_bar.set_fraction(0)


class ReportPage(Gtk.Box):
    """Where the focus time went: today, this week, this month. Export it or turn it into a daily note."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.app = app
        self.range = "week"
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, width_request=280, hexpand=False)
        self.tabs = Adw.ToggleGroup(halign=Gtk.Align.START)
        for name, text in (("today", "Today"), ("week", "Week"), ("month", "Month")):
            self.tabs.add(Adw.Toggle(name=name, label=text))
        self.tabs.set_active_name("week")
        self.tabs.connect("notify::active-name", lambda g, _p: self.set_range(g.get_active_name()))
        left.append(self.tabs)
        self.total = label("", "hub-time")
        self.span = label("", "hub-small")
        left.append(self.total)
        left.append(self.span)
        self.cats = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6)
        left.append(self.cats)
        self.append(left)
        self.append(Gtk.Separator(css_classes=["hub-sep"]))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sc = scrolled(self.body, 300)
        sc.set_vexpand(True)
        sc.set_propagate_natural_height(False)
        right.append(sc)
        actions = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        for text, icon, fn in (("Copy", "edit-copy-symbolic", self.copy), ("CSV", "document-save-symbolic", self.export),
                               ("Standup", "document-edit-symbolic", lambda *_: app.standup())):
            b = Gtk.Button(child=Adw.ButtonContent(label=text, icon_name=icon), css_classes=["flat"],
                           tooltip_text={"Copy": "Copy a Markdown summary", "CSV": "Save a CSV in Documents", "Standup": "Create today's daily note"}[text])
            b.connect("clicked", lambda _b, f=fn: f())
            actions.append(b)
        right.append(actions)
        self.append(right)
        self.refresh()

    def bounds(self):
        return hc.range_for(self.range, date.today())

    def set_range(self, name):
        self.range = name
        self.refresh()

    def bar(self, name, minutes, total, parent):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head = Gtk.Box()
        head.append(label(name, hexpand=True, ellipsize=Pango.EllipsizeMode.END, max_width_chars=26))
        head.append(label(hc.fmt_minutes(minutes), "hub-small"))
        bar = Gtk.ProgressBar(fraction=minutes / max(total, 1), css_classes=["hub-bar"])
        row.append(head)
        row.append(bar)
        parent.append(row)

    def refresh(self):
        since, until = self.bounds()
        r = hc.report(self.app.store["log"], since, until)
        self.total.set_label(hc.fmt_minutes(r["total"]) if r["total"] else "0m")
        self.span.set_label(f"{since:%d %b}" + ("" if since == until else f" to {until:%d %b}") + " · focus time")
        clear(self.cats)
        clear(self.body)
        for cat, mins in sorted(r["by_cat"].items(), key=lambda x: -x[1]):
            self.bar(cat, mins, r["total"], self.cats)
        if not r["total"]:
            self.cats.append(label("No focus time yet. Start a session from the Focus tab or a mode and it is counted here.", "hub-small", wrap=True))
            return
        if self.range != "today":
            self.body.append(label("BY DAY", "hub-h"))
            peak = max(r["by_day"].values())
            d = since
            while d <= min(until, date.today()):
                self.bar(d.strftime("%a %d"), r["by_day"].get(d, 0), peak, self.body)
                d += timedelta(days=1)
        self.body.append(label("BY LABEL", "hub-h", margin_top=8))
        for lab, mins in sorted(r["by_label"].items(), key=lambda x: -x[1])[:10]:
            self.bar(lab, mins, r["total"], self.body)

    def copy(self):
        since, until = self.bounds()
        subprocess.Popen(["wl-copy", hc.markdown_summary(self.app.store["log"], since, until)])
        self.app.toast("Summary copied (Markdown)")

    def export(self):
        since, until = self.bounds()
        out = Path.home() / "Documents" / f"time-report-{since:%Y%m%d}-{until:%Y%m%d}.csv"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(hc.csv_text(self.app.store["log"], since, until))
            self.app.toast(f"Saved {out.name} in Documents")
        except OSError as exc:
            self.app.toast(f"Could not save: {exc.strerror}")

    def tick(self):
        pass


class NotesPage(Gtk.Box):
    """A list on the left, the editor on the right (like Apple Notes). Everything is saved as you type."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.app = app
        self.path = None
        self.save_id = 0
        self.loading = True

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, width_request=270, hexpand=False)
        bar = Gtk.Box(spacing=6)
        self.search = Gtk.SearchEntry(placeholder_text="Search notes", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.refresh())
        new = Gtk.Button(icon_name="list-add-symbolic", css_classes=["suggested-action", "circular"], tooltip_text="New note (Ctrl+N)")
        new.connect("clicked", lambda *_: self.new_note())
        bar.append(self.search)
        bar.append(new)
        left.append(bar)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sc = scrolled(self.list, 360)
        sc.set_vexpand(True)
        sc.set_propagate_natural_height(False)
        left.append(sc)
        self.append(left)
        self.append(Gtk.Separator(css_classes=["hub-sep"]))

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        top = Gtk.Box(spacing=6)
        self.edited = label("", "hub-small", hexpand=True)
        self.drop = Gtk.Button(icon_name="user-trash-symbolic", css_classes=["flat", "circular"], tooltip_text="Delete this note")
        self.drop.connect("clicked", lambda *_: self.delete_note())
        top.append(self.edited)
        top.append(self.drop)
        right.append(top)
        self.view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, css_classes=["note-editor"], left_margin=4, right_margin=4,
                                 top_margin=4, bottom_margin=10, vexpand=True)
        self.buf = self.view.get_buffer()
        self.buf.connect("changed", self.on_changed)
        self.title_tag = self.buf.create_tag("title", weight=700, scale=1.35)
        self.hint = label("Select a note, or press + to write a new one.", "hub-small", margin_start=8, margin_top=4, valign=Gtk.Align.START, can_target=False)
        over = Gtk.Overlay(child=Gtk.ScrolledWindow(child=self.view, hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True))
        over.add_overlay(self.hint)
        right.append(over)
        self.append(right)
        self.set_editor(False)
        self.refresh()
        first = hc.list_notes()
        if first:
            self.open_note(first[0]["path"], focus=False)
        self.loading = False

    def set_editor(self, on):
        self.view.set_sensitive(on)
        self.drop.set_sensitive(on)
        self.hint.set_visible(not on)

    def refresh(self):
        clear(self.list)
        q = self.search.get_text().strip().lower()
        shown = 0
        for n in hc.list_notes(self.path):
            if q:
                try:
                    if q not in n["path"].read_text().lower():
                        continue
                except OSError:
                    continue
            shown += 1
            btn = Gtk.Button(css_classes=["flat", "note-row"] + (["active"] if self.path and n["path"] == self.path else []))
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, halign=Gtk.Align.START, margin_top=3, margin_bottom=3)
            col.append(label(n["title"], "note-title", ellipsize=Pango.EllipsizeMode.END, max_width_chars=28))
            when = datetime.fromtimestamp(n["mtime"])
            col.append(label(f"{when:%d %b} · {n['preview']}" if n["preview"] else f"{when:%d %b}", "note-prev", ellipsize=Pango.EllipsizeMode.END,
                             max_width_chars=30))
            btn.set_child(col)
            btn.connect("clicked", lambda _b, p=n["path"]: self.open_note(p))
            self.list.append(btn)
        if not shown:
            self.list.append(label("No notes match." if q else "No notes yet. They are Markdown files in ~/Notes.", "hub-small", wrap=True, margin_top=14))

    def new_note(self):
        self.finish_current()
        path = hc.new_note_path()
        path.write_text("")
        self.open_note(path)

    def finish_current(self):
        """Save what is open; an empty note is not worth keeping."""
        if self.save_id:
            GLib.source_remove(self.save_id)
            self.flush()
        if self.path and self.path.exists() and not self.path.read_text().strip():
            self.path.unlink()
        self.path = None

    def open_note(self, path, focus=True):
        if self.path and Path(path) != self.path:
            self.finish_current()
        self.path = Path(path)
        self.loading = True
        try:
            text = self.path.read_text()
        except OSError:
            text = ""
        self.buf.set_text(text)
        self.restyle()
        self.loading = False
        self.edited.set_label("")
        self.set_editor(True)
        self.hint.set_visible(False)
        self.refresh()
        if focus:
            self.view.grab_focus()
            self.buf.place_cursor(self.buf.get_end_iter())

    def restyle(self):
        start, end = self.buf.get_bounds()
        self.buf.remove_tag(self.title_tag, start, end)
        _ok, first_end = self.buf.get_iter_at_line(0)
        if not first_end.ends_line():
            first_end.forward_to_line_end()
        self.buf.apply_tag(self.title_tag, start, first_end)

    def on_changed(self, *_):
        if self.loading or not self.path:
            return
        self.restyle()
        self.edited.set_label("Saving…")
        if self.save_id:
            GLib.source_remove(self.save_id)
        self.save_id = GLib.timeout_add(500, self.flush)

    def flush(self):
        self.save_id = 0
        if self.path:
            start, end = self.buf.get_bounds()
            self.path.write_text(self.buf.get_text(start, end, False))
            self.edited.set_label("Saved")
            self.refresh()
        return False

    def close_note(self):
        self.finish_current()
        self.buf.set_text("")
        self.set_editor(False)
        self.refresh()

    def delete_note(self):
        if not self.path:
            return
        dialog = Adw.AlertDialog(heading="Delete this note?", body="The file is removed from ~/Notes.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def answered(_d, response):
            self.app.hold_open(False)
            if response == "delete" and self.path:
                if self.save_id:
                    GLib.source_remove(self.save_id)
                    self.save_id = 0
                self.path.unlink(missing_ok=True)
                self.path = None
                self.loading = True
                self.buf.set_text("")
                self.loading = False
                self.set_editor(False)
                self.refresh()

        dialog.connect("response", answered)
        self.app.hold_open(True)
        dialog.present(self.get_root())

    def tick(self):
        pass


# ----------------------------------------------------------------------------- the dropdown
class HubWindow(Adw.ApplicationWindow):
    def __init__(self, app, tab):
        super().__init__(application=app, default_width=800, default_height=470, title="Hub")
        self.add_css_class("primo-hub")
        self.set_decorated(False)
        self.set_resizable(False)
        self.app = app
        self.pinned = bool(os.environ.get("PRIMO_HUB_KEEP"))   # debugging aid: do not close on focus loss
        self.holds = 0
        self.alive = True

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, css_classes=["hub-card", "primo-card"], valign=Gtk.Align.START,
                       hexpand=True)
        top = Gtk.Box(margin_top=12, margin_start=14, margin_end=10)
        self.picker = Adw.ToggleGroup(hexpand=True, halign=Gtk.Align.CENTER)
        for name, icon, tip in TABS:
            self.picker.add(Adw.Toggle(name=name, icon_name=icon, label=tip))
        self.pin = Gtk.ToggleButton(icon_name="view-pin-symbolic", css_classes=["flat", "circular"],
                                    tooltip_text="Pin: stay open, and follow you across workspaces")
        self.pin.connect("toggled", self.on_pin)
        top.append(self.picker)
        top.append(self.pin)
        card.append(top)
        self.title = label("")           # kept for show_tab; the tab names are on the picker itself
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=140, vhomogeneous=True,
                               height_request=372)
        self.pages = {}
        self.stack.set_margin_start(20)
        self.stack.set_margin_end(20)
        self.stack.set_margin_bottom(18)
        card.append(self.stack)
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
        self.connect("close-request", self.on_close)
        self.picker.set_active_name(tab)
        self.show_tab(tab)
        self.picker.connect("notify::active-name", lambda g, _p: self.show_tab(g.get_active_name()))

    @staticmethod
    def inside(widget, x, y):
        a = widget.get_allocation()
        return a.x <= x <= a.x + a.width and a.y <= y <= a.y + a.height

    def page(self, name):
        if name not in self.pages:
            cls = {"calendar": CalendarPage, "reminders": RemindersPage, "clock": ClockPage, "focus": FocusPage, "report": ReportPage,
                   "notes": NotesPage}[name]
            self.pages[name] = cls(self.app)
            self.stack.add_named(self.pages[name], name)
        return self.pages[name]

    def show_tab(self, name):
        page = self.page(name)
        self.stack.set_visible_child_name(name)
        self.tab = name
        self.title.set_label(dict((n, t) for n, _i, t in TABS)[name])
        self.app.store["last_tab"] = name if name != "clock" else self.app.store["last_tab"]
        page.refresh() if hasattr(page, "refresh") else None
        page.tick()

    def changed(self):
        for page in self.pages.values():
            if hasattr(page, "refresh"):
                page.refresh()

    def tick(self):
        page = self.pages.get(self.tab)
        if page:
            page.tick()

    def on_key(self, _c, keyval, _code, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if ctrl and Gdk.KEY_1 <= keyval <= Gdk.KEY_6:
            self.picker.set_active_name(TABS[keyval - Gdk.KEY_1][0])
            return True
        if ctrl and keyval == Gdk.KEY_n:
            self.picker.set_active_name("notes")
            self.page("notes").new_note()
            return True
        return False

    def hold_open(self, on):
        self.holds = max(0, self.holds + (1 if on else -1))

    def on_pin(self, button):
        """Pinned = stays open when focus moves away and is shown on every workspace (Hyprland's pin)."""
        self.pinned = button.get_active()
        addr = self.address()
        if addr:
            subprocess.run(["hyprctl", "dispatch", f'hl.dsp.window.pin({{ window = "address:{addr}", action = "{"enable" if self.pinned else "disable"}" }})'],
                           capture_output=True)

    def address(self):
        try:
            import json
            for c in json.loads(subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=3).stdout or "[]"):
                if c["class"] == APP_ID and c["title"] == "Hub":
                    return c["address"]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return None

    def on_active_changed(self, *_):
        if os.environ.get("PRIMO_HUB_DEBUG"):
            print("active:", self.is_active(), "pinned", self.pinned, "holds", self.holds, file=sys.stderr)
        if not self.is_active():
            GLib.timeout_add(250, lambda: (self.close() if self.alive and not self.is_active() and not self.pinned and not self.holds
                                           and not self.editing() else None, False)[1])

    def editing(self):
        notes = self.pages.get("notes")
        return bool(notes and self.tab == "notes" and notes.path and notes.view.has_focus())

    def on_close(self, *_):
        notes = self.pages.get("notes")
        if notes and notes.save_id:
            GLib.source_remove(notes.save_id)
            notes.flush()
        self.alive = False
        self.app.save()
        return False


# ----------------------------------------------------------------------------- the alarm that rings
class AlarmWindow(Adw.Window):
    def __init__(self, app, alarm_label, clock):
        super().__init__(application=app, title="Alarm", default_width=380, default_height=240, resizable=False)
        self.app = app
        self.stop = threading.Event()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=24, margin_bottom=24, margin_start=28, margin_end=28)
        box.append(label(clock, "hub-time", xalign=0.5))
        box.append(label(alarm_label or "Alarm", "title-3", xalign=0.5))
        row = Gtk.Box(spacing=10, homogeneous=True, margin_top=8)
        snooze = Gtk.Button(label="Snooze 10 min", css_classes=["pill"])
        stop = Gtk.Button(label="Stop", css_classes=["pill", "suggested-action"])
        snooze.connect("clicked", lambda *_: self.done(True))
        stop.connect("clicked", lambda *_: self.done(False))
        row.append(snooze)
        row.append(stop)
        box.append(row)
        self.set_content(box)
        self.connect("close-request", lambda *_: (self.stop.set(), False)[1])
        sound("alarm-clock-elapsed.oga", loop_for=90, stop=self.stop)
        GLib.timeout_add_seconds(90, lambda: (self.close() if self.get_visible() else None, False)[1])
        self.snooze_cb = None

    def done(self, snooze):
        self.stop.set()
        if snooze and self.snooze_cb:
            self.snooze_cb()
        self.close()


# ----------------------------------------------------------------------------- the service
class Service(Adw.Application):
    def __init__(self, daemon):
        super().__init__(application_id=APP_ID)
        self.daemon = daemon
        self.window = None
        self.css = None
        self.store = hc.Store()
        self.last_break = 0.0
        self.ringing = []
        self.wf = wf.load()
        self.ics_events = []
        self.last_fetch = 0.0
        self.last_backup = time.time()
        for name, fn, param in (("toggle", lambda *_: self.toggle(), None), ("open", lambda _a, p: self.show(p.get_string()), "s"),
                                ("focus-start", lambda _a, p: self.focus_start(*p.get_string().split("|", 1)), "s"),
                                ("focus-end", lambda *_: self.focus_reset(), None),
                                ("standup", lambda *_: self.standup(), None),
                                ("workflow-reload", lambda *_: self.workflow_reload(), None),
                                ("quit", lambda *_: self.quit(), None)):
            act = Gio.SimpleAction.new(name, GLib.VariantType(param) if param else None)
            act.connect("activate", fn)
            self.add_action(act)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.hold()
        self.load_events()
        self.check_due(datetime.now(), startup=True)
        GLib.timeout_add_seconds(1, self.tick)

    def do_activate(self):
        if self.daemon:
            self.daemon = False
            return
        self.show(self.store["last_tab"])

    # ---- window
    def load_css(self):
        display = Gdk.Display.get_default()
        if self.css is None:
            self.css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(display, self.css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            own = Gtk.CssProvider()
            fallback = ""
            try:
                if "accent2_color" not in USER_CSS.read_text():
                    fallback = "@define-color accent2_color @accent_bg_color;\n"
            except OSError:
                fallback = "@define-color accent2_color @accent_bg_color;\n"
            own.load_from_string(fallback + CSS)
            Gtk.StyleContext.add_provider_for_display(display, own, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        if USER_CSS.exists():
            self.css.load_from_path(str(USER_CSS))

    def visible(self):
        return self.window is not None and self.window.alive and self.window.get_visible()

    def toggle(self):
        if self.visible():
            self.window.close()
        else:
            self.show(self.store["last_tab"])

    def show(self, tab):
        new_note = tab == "new-note"
        sub = tab.split("-", 1)[1] if tab.startswith("clock-") else None      # clock-alarm, clock-timer, ...
        tab = "clock" if sub else ("notes" if new_note else (tab if tab in dict((n, 0) for n, _i, _t in TABS) else "calendar"))
        if self.visible():
            self.window.picker.set_active_name(tab)
        else:
            self.load_css()
            self.window = HubWindow(self, tab)
            self.window.present()
        if new_note:
            self.window.page("notes").new_note()
        if sub in ("world", "alarm", "watch", "timer"):
            self.window.page("clock").tabs.set_active_name(sub)

    def hold_open(self, on):
        if self.window is not None:
            self.window.hold_open(on)

    def toast(self, text):
        subprocess.Popen(["notify-send", "-a", "Hub", "-t", "3000", "-i", "emblem-ok", text])

    # ---- calendar feeds (ICS) and the notes backup
    def load_events(self):
        today = date.today()
        self.ics_events = wf.load_events(self.wf, today - timedelta(days=35), today + timedelta(days=70))
        if self.visible():
            self.window.changed()

    def workflow_reload(self):
        self.wf = wf.load()
        self.last_fetch = 0.0
        self.load_events()

    def fetch_feeds(self):
        def work():
            for feed in self.wf["ics"]:
                err = wf.fetch_feed(feed["url"])
                if err:
                    print("calendar feed", feed.get("name", ""), err, file=sys.stderr)
            GLib.idle_add(lambda: (self.load_events(), False)[1])

        threading.Thread(target=work, daemon=True).start()

    def background_jobs(self, now):
        t = time.time()
        if self.wf["ics"] and t - self.last_fetch > 1800:
            self.last_fetch = t
            self.fetch_feeds()
        if self.wf["backup"]["on"] and t - self.last_backup > 1800:
            self.last_backup = t
            threading.Thread(target=lambda: wf.backup_notes(hc.NOTES_DIR, push=self.wf["backup"]["push"]), daemon=True).start()
        for o in self.ics_events:
            lead = (o["start"] - now).total_seconds() / 60
            key = f"ics-{o['uid']}-{o['start']:%Y%m%d%H%M}"
            if not o["allday"] and 0 < lead <= self.wf["ics_alert"] and key not in self.store["fired"]:
                self.store["fired"][key] = now.timestamp()
                sound("message.oga")
                notify(f"In {max(1, round(lead))} min: {o['title']}", " · ".join(x for x in (f"{o['start']:%H:%M}", o["location"]) if x), icon="x-office-calendar")

    def standup(self):
        """Create today's daily note (once) and open it in Notes."""
        path = hc.NOTES_DIR / f"{datetime.now():%Y-%m-%d}-daily.md"
        if not path.exists():
            hc.NOTES_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(hc.standup_text(self.store.data, datetime.now()))
        self.show("notes")
        self.window.page("notes").open_note(path)

    def save(self):
        self.store.save()

    def changed(self):
        self.save()
        self.write_status()
        if self.visible():
            self.window.changed()

    # ---- data changes
    def add_reminder(self, title, due, repeat, tag):
        self.store["reminders"].append({"id": hc.new_id(), "title": title, "due": due.isoformat(timespec="minutes") if due else None,
                                        "repeat": repeat, "tag": tag, "done": False, "fired": False})
        self.changed()

    def complete_reminder(self, rid, done):
        for r in self.store["reminders"]:
            if r["id"] == rid:
                r["done"] = done
                if done:
                    r["done_at"] = datetime.now().isoformat(timespec="minutes")
                else:
                    r.pop("done_at", None)
        self.changed()

    def delete_reminder(self, rid):
        self.store["reminders"] = [r for r in self.store["reminders"] if r["id"] != rid]
        self.changed()

    def add_zone(self, zone):
        if zone not in self.store["world"]:
            self.store["world"].append(zone)
        self.changed()

    def remove_zone(self, zone):
        self.store["world"] = [z for z in self.store["world"] if z != zone]
        self.changed()

    def save_alarm(self, aid, hhmm, days, name):
        if aid:
            for a in self.store["alarms"]:
                if a["id"] == aid:
                    a.update(time=hhmm, days=days, label=name, on=True)
                    a.pop("next", None)
        else:
            self.store["alarms"].append({"id": hc.new_id(), "time": hhmm, "days": days, "label": name, "on": True})
        self.changed()

    def set_alarm_on(self, aid, on):
        for a in self.store["alarms"]:
            if a["id"] == aid:
                a["on"] = on
                a.pop("next", None)
        self.save()

    def delete_alarm(self, aid):
        self.store["alarms"] = [a for a in self.store["alarms"] if a["id"] != aid]
        self.changed()

    def add_timer(self, seconds):
        self.store["timers"].append({"id": hc.new_id(), "total": seconds, "end": time.time() + seconds, "left": None})
        self.changed()

    def pause_timer(self, tid):
        for t in self.store["timers"]:
            if t["id"] == tid:
                if t["left"] is None:
                    t["left"] = max(0, t["end"] - time.time())
                else:
                    t["end"], t["left"] = time.time() + t["left"], None
        self.changed()

    def cancel_timer(self, tid):
        self.store["timers"] = [t for t in self.store["timers"] if t["id"] != tid]
        self.changed()

    def watch_toggle(self):
        s = self.store["stopwatch"]
        now = time.time()
        if s["running"]:
            s["elapsed"] += now - s["start"]
            s["running"] = False
        else:
            s["start"], s["running"] = now, True
        self.changed()

    def watch_lap(self):
        s = self.store["stopwatch"]
        if s["running"]:
            s["laps"].append(s["elapsed"] + time.time() - s["start"])
        else:
            s.update(elapsed=0.0, laps=[], start=0.0)
        self.changed()

    def focus_toggle(self):
        s = self.store["session"]
        now = time.time()
        if s["phase"] == "idle":
            f = self.store["focus"]
            self.start_phase("focus", self.store["pomodoro"]["focus"], 0, f["label"], f["category"])
        elif s["left"] is None:
            s["left"] = max(0, s["end"] - now)
            s["worked"] = s.get("worked", 0.0) + (now - s["seg"] if s.get("seg") else 0.0)
            s["seg"] = None
        else:
            s["end"], s["left"], s["seg"] = now + s["left"], None, now
        self.changed()

    def focus_skip(self):
        s = self.store["session"]
        self.log_session()
        phase, mins, cycle = hc.next_phase(s["phase"], s["cycle"], self.store["pomodoro"])
        self.start_phase(phase, mins, cycle)
        self.changed()

    def focus_reset(self):
        self.log_session()
        self.store["session"] = {"phase": "idle", "end": 0.0, "cycle": 0, "left": None, "label": "", "category": "", "seg": None, "worked": 0.0}
        self.sync_dnd()
        self.changed()

    def log_session(self, end_ts=None):
        """Add the focus time of the session that is ending to the log (breaks and tiny sessions are not counted)."""
        s = self.store["session"]
        if s["phase"] != "focus":
            return
        end_ts = end_ts or time.time()
        total = s.get("worked", 0.0) + (end_ts - s["seg"] if s.get("seg") else 0.0)
        if total >= 60:
            self.store["log"].append({"start": end_ts - total, "end": end_ts, "min": round(total / 60, 1),
                                      "label": s.get("label", ""), "cat": s.get("category") or "Other"})
            self.store["log"] = self.store["log"][-3000:]

    def focus_start(self, label_text="", category=""):
        """Used by modes: begin a focus session labelled with what you are working on."""
        self.start_phase("focus", self.store["pomodoro"]["focus"], 0, label_text, category)
        self.changed()

    def start_phase(self, phase, minutes, cycle, label_text=None, category=None):
        old = self.store["session"]
        self.store["session"] = {"phase": phase, "end": time.time() + minutes * 60, "cycle": cycle, "left": None,
                                 "label": old.get("label", "") if label_text is None else label_text,
                                 "category": old.get("category", "") if category is None else category,
                                 "seg": time.time(), "worked": 0.0}
        self.sync_dnd()

    def sync_dnd(self):
        """Do not disturb while a focus block runs (only if it was off before, so your own setting is left alone)."""
        s, work = self.store["session"], self.store["work"]
        want = work["dnd_focus"] and s["phase"] == "focus" and s["left"] is None
        if want and not getattr(self, "dnd_ours", False) and not dnd_is_on():
            set_dnd(True)
            self.dnd_ours = True
        elif not want and getattr(self, "dnd_ours", False):
            set_dnd(False)
            self.dnd_ours = False

    # ---- the clock that drives everything
    def tick(self):
        try:
            self.check_due(datetime.now())
            if int(time.time()) % 10 == 0:
                self.background_jobs(datetime.now())
            self.write_status()
            if self.visible():
                self.window.tick()
        except Exception as exc:   # one bad entry must not stop every alarm
            print("hub tick:", exc, file=sys.stderr)
        return True

    def check_due(self, now, startup=False):
        ts = now.timestamp()
        changed = False
        for r in self.store["reminders"]:
            if r.get("done") or not r.get("due") or r.get("fired"):
                continue
            due = datetime.fromisoformat(r["due"])
            if due <= now:
                late = (now - due).total_seconds() > 300
                self.fire_reminder(r, late)
                nxt = hc.advance(due, r.get("repeat"))
                if nxt:
                    while nxt <= now:
                        nxt = hc.advance(nxt, r["repeat"])
                    r["due"], r["fired"] = nxt.isoformat(timespec="minutes"), False
                else:
                    r["fired"] = True
                changed = True
        for a in self.store["alarms"]:
            if not a.get("on", True):
                continue
            nxt = datetime.fromisoformat(a["next"]) if a.get("next") else None
            if nxt is None:
                n = hc.next_alarm(a, now)
                a["next"] = n.isoformat() if n else None
                changed = True
            elif nxt <= now:
                if (now - nxt).total_seconds() < 600:
                    self.ring_alarm(a)
                else:
                    notify("Missed alarm", f"{a['time']} {a.get('label', '')}".strip(), icon="alarm")
                if a["days"]:
                    n = hc.next_alarm(a, now)
                    a["next"] = n.isoformat() if n else None
                else:
                    a["on"], a["next"] = False, None
                changed = True
        for t in list(self.store["timers"]):
            if t["left"] is None and t["end"] <= ts:
                self.store["timers"].remove(t)
                sound("complete.oga")
                notify("Timer done", hc.fmt_clock(t["total"]) + " is up", icon="alarm")
                changed = True
        s = self.store["session"]
        if s["phase"] != "idle" and s["left"] is None and s["end"] <= ts:
            self.log_session(end_ts=min(ts, s["end"]))
            phase, mins, cycle = hc.next_phase(s["phase"], s["cycle"], self.store["pomodoro"])
            msg = {"focus": "Time to focus", "short": "Take a short break", "long": "Take a long break"}[phase]
            sound("complete.oga")
            notify(msg, f"{mins} minutes", icon="timer")
            self.start_phase(phase, mins, cycle)
            changed = True
        if not startup:
            changed |= self.check_work(now)
        if changed:
            self.changed()

    def check_work(self, now):
        w = hc.work_state(self.store["work"], now)
        fired = self.store["fired"]
        changed = False
        if w["working"]:
            cfg = self.store["work"]
            key = f"end-{now:%Y%m%d}"
            if cfg["end_on"] and 0 < w["left"] <= cfg["end_notice"] and key not in fired:
                fired[key] = now.timestamp()
                notify("The work day ends soon", f"{w['left']} minutes left. Wrap up and note what is next.", icon="appointment-soon")
                changed = True
            if cfg["break_on"]:
                if not self.last_break:
                    self.last_break = time.time()
                elif time.time() - self.last_break >= cfg["break_every"] * 60:
                    self.last_break = time.time()
                    notify("Time for a break", "Stand up, stretch, look away from the screen.", icon="timer")
        else:
            self.last_break = 0.0
        for k in [k for k in fired if k.startswith("end-") and k[4:] < f"{now - timedelta(days=3):%Y%m%d}"]:
            del fired[k]
            changed = True
        for k in [k for k, v in fired.items() if k.startswith("ics-") and v < now.timestamp() - 86400]:
            del fired[k]
            changed = True
        return changed

    def fire_reminder(self, r, late):
        sound("message.oga")
        title = ("Missed: " if late else "") + r["title"]
        notify(title, "Reminder" + (f" · #{r['tag']}" if r.get("tag") else ""),
               actions=[("done", "Done"), ("snooze", "Snooze 10 min")],
               on_action=lambda act, rid=r["id"]: self.reminder_action(rid, act))

    def reminder_action(self, rid, act):
        for r in self.store["reminders"]:
            if r["id"] == rid:
                if act == "done":
                    r["done"] = True
                elif act == "snooze":
                    r["due"], r["fired"], r["done"] = (datetime.now() + timedelta(minutes=10)).isoformat(timespec="minutes"), False, False
        self.changed()

    def ring_alarm(self, a):
        win = AlarmWindow(self, a.get("label", ""), a["time"])
        win.snooze_cb = lambda aid=a["id"]: self.snooze_alarm(aid)
        self.ringing.append(win)                      # keep a reference: a window nobody holds is destroyed
        win.connect("close-request", lambda w: (self.ringing.remove(w) if w in self.ringing else None, False)[1])
        win.present()
        notify("Alarm", f"{a['time']} {a.get('label', '')}".strip(), icon="alarm")

    def snooze_alarm(self, aid):
        for a in self.store["alarms"]:
            if a["id"] == aid:
                a["next"], a["on"] = (datetime.now() + timedelta(minutes=10)).isoformat(), True
        self.changed()

    # ---- the bit of status the bar shows
    def write_status(self):
        parts, cls = [], ""
        mode = mc.current()
        if mode:
            secs = mc.elapsed(mode)
            parts.append(f"{mode['name']} {secs // 3600}:{secs % 3600 // 60:02d}")
            cls = "mode"
        s = self.store["session"]
        if s["phase"] != "idle":
            left = s["left"] if s["left"] is not None else max(0, s["end"] - time.time())
            parts.append({"focus": "Focus", "short": "Break", "long": "Break"}[s["phase"]] + " " + hc.fmt_clock(left))
            cls = "focus"
        timers = [t for t in self.store["timers"]]
        if timers:
            t = min(timers, key=lambda t: t["left"] if t["left"] is not None else t["end"] - time.time())
            left = t["left"] if t["left"] is not None else max(0, t["end"] - time.time())
            parts.append("Timer " + hc.fmt_clock(left))
            cls = cls or "timer"
        if parts:
            data = json_dumps({"text": " · ".join(parts), "class": cls, "tooltip": "Click the clock to open"})
        else:
            data = None
        try:
            if data:
                STATUS.parent.mkdir(parents=True, exist_ok=True)
                if not STATUS.exists() or STATUS.read_text() != data:
                    STATUS.write_text(data)
            else:
                STATUS.unlink(missing_ok=True)
        except OSError:
            pass


def json_dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    sys.exit(Service("--daemon" in sys.argv).run([sys.argv[0]]))
