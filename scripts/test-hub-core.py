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
from datetime import date
ts = lambda y, m, d, h, mi: datetime(y, m, d, h, mi).timestamp()
log = [{"start": ts(2026, 10, 2, 9, 0), "end": ts(2026, 10, 2, 10, 30), "min": 90, "label": "API", "cat": "Work"},
       {"start": ts(2026, 10, 2, 13, 0), "end": ts(2026, 10, 2, 13, 25), "min": 25, "label": "Read, \"papers\"", "cat": "Research"},
       {"start": ts(2026, 10, 5, 9, 0), "end": ts(2026, 10, 5, 9, 25), "min": 25, "label": "API", "cat": "Work"}]
r = c.report(log, date(2026, 10, 1), date(2026, 10, 7))
assert r["total"] == 140 and r["by_cat"] == {"Work": 115.0, "Research": 25.0} and r["by_label"]["API"] == 115.0
assert c.report(log, date(2026, 10, 5), date(2026, 10, 5))["total"] == 25
assert c.range_for("week", date(2026, 10, 7)) == (date(2026, 10, 5), date(2026, 10, 11)) and c.range_for("month", date(2026, 10, 7))[1] == date(2026, 10, 31)
assert c.fmt_minutes(125) == "2h 05m" and c.fmt_minutes(7) == "7m"
assert '"Read, ""papers"""' in c.csv_text(log, date(2026, 10, 1), date(2026, 10, 7))     # commas and quotes in a label stay one column
data = {"work": {"days": [0, 1, 2, 3, 4]}, "log": log, "reminders": [
    {"title": "Send invoice", "done": True, "done_at": datetime(2026, 10, 2, 16, 0).isoformat()},
    {"title": "Review PR", "done": False, "due": datetime(2026, 10, 5, 14, 0).isoformat()}]}
note = c.standup_text(data, datetime(2026, 10, 5, 8, 30))                      # Monday: "yesterday" is Friday
assert "## Friday (last work day)" in note and "- Done: Send invoice" in note and "- API: 1h 30m" in note and "- [ ] 14:00 Review PR" in note
assert c.previous_work_day({"days": [0, 1, 2, 3, 4]}, date(2026, 10, 6)) == date(2026, 10, 5)

import tempfile, os
d = tempfile.mkdtemp(); s = c.Store(os.path.join(d, "h.json")); s["reminders"].append({"id": "1"}); s.save(); assert c.Store(os.path.join(d, "h.json"))["reminders"] == [{"id": "1"}] and c.Store(os.path.join(d, "h.json"))["work"]["start"] == "09:00"
# ---- hub data moves from the state folder to the data folder, once, keeping a backup; nothing is ever deleted
import contextlib, errno, io, json, time as _t
from pathlib import Path

def place():
    root = Path(tempfile.mkdtemp())
    return root / "state" / "hub.json", root / "data" / "primo" / "hub.json"

def quiet_migrate(old, new):
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        used, notice = c.migrate(new, old)
    return used, notice, err.getvalue()

def aside(path): return sorted(path.parent.glob(path.name + ".bak-primo*"))

old, new = place()                                               # fresh install: nothing to move, nothing created
assert quiet_migrate(old, new) == (new, None, "") and not new.exists() and not old.parent.exists()

old, new = place()                                               # the normal move
old.parent.mkdir(parents=True); old.write_text('{"reminders": [{"id": "r1"}]}'); old.chmod(0o640)
used, notice, _ = quiet_migrate(old, new)
assert used == new and notice is None and new.read_text() == '{"reminders": [{"id": "r1"}]}' and oct(new.stat().st_mode & 0o777) == "0o640"
assert not old.exists() and [b.read_text() for b in aside(old)] == ['{"reminders": [{"id": "r1"}]}']
assert quiet_migrate(old, new) == (new, None, "") and len(aside(old)) == 1 and new.read_text() == '{"reminders": [{"id": "r1"}]}'   # twice: nothing changes

old, new = place()                                               # an earlier move stopped after the copy: finish it
old.parent.mkdir(parents=True); new.parent.mkdir(parents=True)
old.write_text('{"a": 1}'); new.write_text('{"a": 1}')
assert quiet_migrate(old, new)[:2] == (new, None) and not old.exists() and len(aside(old)) == 1

for later in ("old", "new"):                                     # both differ: the new place wins whichever was saved later, the other is kept
    old, new = place()                                           # (an older Primo run again after the move starts a fresh file in the old place)
    old.parent.mkdir(parents=True); new.parent.mkdir(parents=True)
    old.write_text('{"reminders": []}'); new.write_text('{"reminders": [{"id": "real"}]}')
    os.utime(new if later == "old" else old, (_t.time() - 60, _t.time() - 60))
    used, notice, _ = quiet_migrate(old, new)
    assert used == new and new.read_text() == '{"reminders": [{"id": "real"}]}' and [b.read_text() for b in aside(old)] == ['{"reminders": []}']
    assert notice and str(aside(old)[0]) in notice, notice

old, new = place()                                               # a broken file in the new place does not win over good data
old.parent.mkdir(parents=True); new.parent.mkdir(parents=True)
old.write_text('{"a": "good"}'); new.write_text('{"a": ')
used, notice, _ = quiet_migrate(old, new)
assert used == new and new.read_text() == '{"a": "good"}' and [b.read_text() for b in aside(new)] == ['{"a": '] and notice and not old.exists()

old, new = place()                                               # the copy fails (full disk): keep using the old place, change nothing
old.parent.mkdir(parents=True); old.write_text('{"a": 1}')
real_write = c.cc.atomic_write
def full(*a, **k): raise OSError(errno.ENOSPC, "No space left on device")
c.cc.atomic_write = full
try:
    used, notice, warning = quiet_migrate(old, new)
finally:
    c.cc.atomic_write = real_write
assert used == old and old.read_text() == '{"a": 1}' and not new.exists() and "No space" in warning and not aside(old)

old, new = place()                                               # one file under two names (a symlinked folder): it stays where it is
old.parent.mkdir(parents=True); old.write_text('{"a": 1}')
new.parent.parent.mkdir(parents=True); new.parent.symlink_to(old.parent)
assert quiet_migrate(old, new)[:2] == (new, None) and old.read_text() == '{"a": 1}' and not aside(old)

if os.geteuid() != 0:                                            # the new place cannot be read: keep using the old one, touch nothing
    old, new = place()
    old.parent.mkdir(parents=True); new.parent.mkdir(parents=True)
    old.write_text('{"a": "old"}'); new.write_text('{"a": "new"}'); new.chmod(0)
    used, notice, warning = quiet_migrate(old, new)
    new.chmod(0o600)
    assert used == old and old.read_text() == '{"a": "old"}' and new.read_text() == '{"a": "new"}' and not aside(old) and warning

# the store moves the data on first use, and reads and saves the new place
root = Path(tempfile.mkdtemp())
saved_env = {k: os.environ.get(k) for k in ("XDG_STATE_HOME", "XDG_DATA_HOME")}
os.environ["XDG_STATE_HOME"], os.environ["XDG_DATA_HOME"] = str(root / "state"), str(root / "data")
try:
    legacy = root / "state" / "hyprland-dotfiles" / "hub" / "hub.json"
    legacy.parent.mkdir(parents=True); legacy.write_text('{"reminders": [{"id": "kept"}]}')
    st = c.Store()
    assert st.path == root / "data" / "primo" / "hub.json" and st["reminders"] == [{"id": "kept"}] and not legacy.exists() and st.notice is None
    st["reminders"].append({"id": "new"}); st.save()
    assert json.loads(st.path.read_text())["reminders"][-1] == {"id": "new"} and c.Store()["reminders"][-1] == {"id": "new"}
finally:
    for k, v in saved_env.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

print("FAILURES:", bad)
sys.exit(1 if bad else 0)
