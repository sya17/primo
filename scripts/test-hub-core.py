#!/usr/bin/env python3
"""Checks for the time hub core: reminder parsing (English and Indonesian), alarms, work hours, pomodoro, storage."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
from datetime import datetime
import hub_core as c
now = datetime(2026, 10, 4, 22, 30)   # a Sunday
def p(text): r = c.parse_reminder(text, now); return r["title"], (r["due"].strftime("%a %d %H:%M") if r["due"] else None), r["repeat"], r["tag"]
cases = {
 "call the bank tomorrow 14:00 #work": ("call the bank", "Mon 05 14:00", None, "work"),
 "besok jam 9 rapat tim": ("rapat tim", "Mon 05 09:00", None, None),
 "remind me to drink water in 30m": ("drink water", "Sun 04 23:00", None, None),
 "dalam 2 jam kirim laporan": ("kirim laporan", "Mon 05 00:30", None, None),
 "standup every weekday 9:30": ("standup", "Mon 05 09:30", "weekdays", None),
 "pay rent fri 3pm": ("pay rent", "Fri 09 15:00", None, None),
 "ulang tahun setiap hari 08.00": ("ulang tahun", "Mon 05 08:00", "daily", None),
 "buy milk": ("buy milk", None, None, None),
 "review PR at 22:00": ("review PR", "Mon 05 22:00", None, None),
 "email client today 23:15": ("email client", "Sun 04 23:15", None, None),
 "meeting senin 10:00": ("meeting", "Mon 05 10:00", None, None),
 "weekly report every week": ("report", "Mon 05 09:00", "weekly", None),
}
bad = 0
for text, want in cases.items():
    got = p(text)
    if got != want: bad += 1; print("FAIL", repr(text), "\n  got ", got, "\n  want", want)
a = {"time": "07:30", "days": [0, 1, 2, 3, 4], "on": True}
assert c.next_alarm(a, now) == datetime(2026, 10, 5, 7, 30)                  # Sunday night -> Monday
assert c.next_alarm({"time": "23:00", "days": [], "on": True}, now) == datetime(2026, 10, 4, 23, 0)
assert c.next_alarm({"time": "07:30", "days": [], "on": False}, now) is None
w = {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"}
assert not c.work_state(w, now)["working"] and c.work_state(w, now)["next"] == datetime(2026, 10, 5, 9, 0)
ws = c.work_state(w, datetime(2026, 10, 5, 13, 0)); assert ws["working"] and ws["left"] == 240 and abs(ws["progress"] - 0.5) < 1e-9
cfg = {"focus": 25, "short": 5, "long": 15, "cycles": 4}
assert c.next_phase("focus", 0, cfg) == ("short", 5, 1) and c.next_phase("focus", 3, cfg) == ("long", 15, 0) and c.next_phase("short", 1, cfg) == ("focus", 25, 1)
assert c.advance(datetime(2026, 1, 31, 9), "monthly") == datetime(2026, 2, 28, 9) and c.advance(datetime(2026, 10, 9, 9), "weekdays") == datetime(2026, 10, 12, 9)
assert c.fmt_clock(65) == "01:05" and c.fmt_clock(3725) == "1:02:05"
assert c.human_due(datetime(2026, 10, 5, 9), now) == "Tomorrow 09:00"
import tempfile, os
d = tempfile.mkdtemp(); s = c.Store(os.path.join(d, "h.json")); s["reminders"].append({"id": "1"}); s.save(); assert c.Store(os.path.join(d, "h.json"))["reminders"] == [{"id": "1"}] and c.Store(os.path.join(d, "h.json"))["work"]["start"] == "09:00"
print("FAILURES:", bad)
sys.exit(1 if bad else 0)
