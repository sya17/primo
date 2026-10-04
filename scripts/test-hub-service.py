#!/usr/bin/env python3
"""Checks for the time hub service: what fires and when (reminders, alarms, timers, focus, work day), and the notes editor.

Needs GTK; skipped when there is no display (CI)."""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

work = tempfile.mkdtemp()
os.environ["XDG_STATE_HOME"] = os.path.join(work, "state")
os.environ["PRIMO_NOTES_DIR"] = os.path.join(work, "notes")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display")      # GTK aborts (not just fails) without one, so look before touching it
    sys.exit(0)
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
if not Gtk.init_check():
    print("skip: no display")
    sys.exit(0)
import hub
import hub_core as hc

sent, rang = [], []
hub.notify = lambda title, body, **kw: sent.append(title)
hub.sound = lambda *a, **k: None
hub.set_dnd = lambda on: None
hub.dnd_is_on = lambda: False
app = hub.Service(False)
app.store = hc.Store(os.path.join(work, "hub.json"))
app.ring_alarm = lambda a: rang.append(a["time"])
app.write_status = lambda: None
app.wf = {"ics": [], "ics_alert": 10, "backup": {"on": False, "push": False}, "app_rules": [], "snippets": []}
now = datetime(2026, 10, 5, 9, 0)           # a Monday

def due(minutes): return (now + timedelta(minutes=minutes)).isoformat(timespec="minutes")
R = app.store["reminders"]
R += [{"id": "a", "title": "due now", "due": due(-1), "repeat": None, "done": False, "fired": False},
      {"id": "b", "title": "later", "due": due(30), "repeat": None, "done": False, "fired": False},
      {"id": "c", "title": "daily", "due": due(-2), "repeat": "daily", "done": False, "fired": False},
      {"id": "d", "title": "missed", "due": due(-600), "repeat": None, "done": False, "fired": False},
      {"id": "e", "title": "done one", "due": due(-1), "repeat": None, "done": True, "fired": False}]
app.check_due(now)
assert sent.count("due now") == 1 and "later" not in sent and "done one" not in sent, sent
assert "Missed: missed" in sent, sent                        # a reminder that came due while the service was off
assert [r for r in R if r["id"] == "c"][0]["due"] == (now + timedelta(days=1, minutes=-2)).isoformat(timespec="minutes")
sent.clear(); app.check_due(now)
assert sent == [], "must not fire twice"
app.reminder_action("a", "snooze")
assert [r for r in R if r["id"] == "a"][0]["fired"] is False and not [r for r in R if r["id"] == "a"][0]["done"]

app.store["alarms"].append({"id": "x", "time": "09:05", "days": [], "label": "", "on": True})
app.check_due(now)                                           # arms it
assert not rang
app.check_due(now + timedelta(minutes=5, seconds=1))
assert rang == ["09:05"] and app.store["alarms"][0]["on"] is False   # a one-off alarm switches itself off
rang.clear(); app.store["alarms"][0].update(on=True, days=[0], next=None)
app.check_due(now + timedelta(minutes=6)); app.check_due(now + timedelta(days=7, minutes=6))
assert rang == ["09:05"], rang                               # a repeating alarm rings on its day

sent.clear()
app.store["timers"].append({"id": "t", "total": 60, "end": time.time() - 1, "left": None})
app.store["timers"].append({"id": "p", "total": 60, "end": 0, "left": 30.0})   # paused: must not fire
app.check_due(datetime.now())
assert "Timer done" in sent and [t["id"] for t in app.store["timers"]] == ["p"]

sent.clear(); app.focus_toggle()
s = app.store["session"]; assert s["phase"] == "focus" and abs(s["end"] - time.time() - 1500) < 3
s["end"] = time.time() - 1; app.check_due(datetime.now())
assert app.store["session"]["phase"] == "short" and "Take a short break" in sent
app.focus_toggle(); assert app.store["session"]["left"] is not None            # pause
app.focus_reset(); assert app.store["session"]["phase"] == "idle"

sent.clear(); app.store["work"].update(days=[0], start="09:00", end="17:00", end_notice=10)
app.check_work(datetime(2026, 10, 5, 16, 49)); assert sent == [], sent
app.check_work(datetime(2026, 10, 5, 16, 52)); app.check_work(datetime(2026, 10, 5, 16, 55))
assert sent == ["The work day ends soon"], sent              # once, not at every tick

# time tracking: pauses are not counted, short and break sessions are not logged
clock = [1_000_000.0]; real_time = time.time; time.time = lambda: clock[0]
app.store["log"].clear(); app.store["focus"] = {"label": "API work", "category": "Work"}
app.focus_toggle(); assert app.store["session"]["label"] == "API work"
clock[0] += 600; app.focus_toggle()                      # pause after 10 min
clock[0] += 300; app.focus_toggle()                      # resume 5 min later
clock[0] += 300; app.focus_skip()                        # 5 more minutes, then skip
assert len(app.store["log"]) == 1 and app.store["log"][0]["min"] == 15.0 and app.store["log"][0]["label"] == "API work", app.store["log"]
clock[0] += 400; app.focus_skip()                        # the break is not logged
assert len(app.store["log"]) == 1 and app.store["session"]["phase"] == "focus"
clock[0] += 30; app.focus_reset(); assert len(app.store["log"]) == 1            # 30 s of focus is not a session
app.focus_toggle(); s = app.store["session"]; clock[0] = s["end"] + 5
app.check_due(datetime.fromtimestamp(clock[0]))          # the block runs out by itself
assert len(app.store["log"]) == 2 and app.store["log"][1]["min"] == 25.0, app.store["log"]
app.focus_reset(); time.time = real_time
app.add_reminder("finish", None, None, None); rid = app.store["reminders"][-1]["id"]
app.complete_reminder(rid, True); assert app.store["reminders"][-1]["done_at"]
app.complete_reminder(rid, False); assert "done_at" not in app.store["reminders"][-1]

# meetings from a calendar feed: one reminder, a few minutes ahead, only once
os.environ["XDG_CONFIG_HOME"] = os.path.join(work, "config")
import workflow_core as wf
soon = datetime.now() + timedelta(minutes=7)
app.ics_events = [{"title": "Planning", "start": soon, "end": soon + timedelta(hours=1), "allday": False, "location": "Room 2", "uid": "u1"},
                  {"title": "Holiday", "start": soon, "end": soon + timedelta(days=1), "allday": True, "location": "", "uid": "u2"},
                  {"title": "Far", "start": soon + timedelta(hours=3), "end": soon + timedelta(hours=4), "allday": False, "location": "", "uid": "u3"}]
sent.clear(); app.background_jobs(datetime.now()); app.background_jobs(datetime.now())
assert [t for t in sent if "Planning" in t] == ["In 7 min: Planning"] and not any("Holiday" in t or "Far" in t for t in sent), sent

# notes: typing is saved, an empty note is not kept
page = hub.NotesPage(app)
page.new_note(); page.buf.set_text("Title line\nbody text"); page.flush()
assert page.path.read_text() == "Title line\nbody text"
kept = page.path
page.close_note()
assert [n["title"] for n in hc.list_notes()] == ["Title line"] and kept.exists()
page.new_note(); empty = page.path; page.close_note()
assert not empty.exists()
assert hub.parse_duration("1h30") == 5400 and hub.parse_duration("90s") == 90 and hub.parse_duration("25:00") == 1500 and hub.parse_duration("5") == 300
print("hub service checks passed")
