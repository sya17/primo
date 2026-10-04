#!/usr/bin/env python3
"""Checks for workflow helpers: ICS parsing and recurrence, app workspace rules, snippets storage, notes backup."""
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta

work = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = os.path.join(work, "config")
os.environ["XDG_STATE_HOME"] = os.path.join(work, "state")
os.environ["PRIMO_HYPR_DIR"] = os.path.join(work, "hypr")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import workflow_core as wf

ICS = "\r\n".join([
    "BEGIN:VCALENDAR",
    "BEGIN:VEVENT", "UID:a", "DTSTART:20261005T090000", "DTEND:20261005T093000", "SUMMARY:Standup\\, daily",
    "RRULE:FREQ=DAILY;COUNT=3", "EXDATE:20261006T090000", "LOCATION:Room 1", "END:VEVENT",
    "BEGIN:VEVENT", "UID:b", "DTSTART;VALUE=DATE:20261009", "SUMMARY:Holiday", "END:VEVENT",
    "BEGIN:VEVENT", "UID:c", "DTSTART:20261005T140000", "DURATION:PT1H", "SUMMARY:Folded line that is lo", " ng and continues", "END:VEVENT",
    "BEGIN:VEVENT", "UID:d", "DTSTART:20261006T100000", "DTEND:20261006T110000", "SUMMARY:Weekly sync", "RRULE:FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261020T000000", "END:VEVENT",
    "BEGIN:VEVENT", "UID:e", "DTSTART:20261007T100000", "DTEND:20261007T110000", "SUMMARY:Cancelled", "STATUS:CANCELLED", "END:VEVENT",
    "BEGIN:VEVENT", "UID:f", "DTSTART:20261031T080000", "DTEND:20261031T090000", "SUMMARY:Monthly", "RRULE:FREQ=MONTHLY", "END:VEVENT",
    "END:VCALENDAR", ""])
ev = wf.parse_ics(ICS)
occ = wf.occurrences(ev, date(2026, 10, 5), date(2026, 10, 12))
got = [(o["start"].strftime("%a %d %H:%M"), o["title"]) for o in occ]
assert ("Mon 05 09:00", "Standup, daily") in got and ("Tue 06 09:00", "Standup, daily") not in got, got       # EXDATE skipped, \, unescaped
assert ("Wed 07 09:00", "Standup, daily") in got and len([g for g in got if g[1] == "Standup, daily"]) == 2, got  # COUNT=3 minus the excluded one
assert any(o["allday"] and o["title"] == "Holiday" for o in occ)
folded = [o for o in occ if o["uid"] == "c"][0]
assert folded["end"] == datetime(2026, 10, 5, 15, 0) and folded["title"] == "Folded line that is long and continues", folded
assert [g[0] for g in got if g[1] == "Weekly sync"] == ["Tue 06 10:00", "Thu 08 10:00"], got   # Tuesdays and Thursdays inside the window
assert not any(g[1] == "Cancelled" for g in got)
assert [o["start"] for o in wf.occurrences(ev, date(2026, 10, 31), date(2027, 1, 31)) if o["title"] == "Monthly"] == [datetime(2026, 10, 31, 8), datetime(2026, 12, 31, 8), datetime(2027, 1, 31, 8)]   # no 31st in November
utc = wf.parse_ics("BEGIN:VEVENT\nUID:z\nDTSTART:20261005T020000Z\nDTEND:20261005T030000Z\nSUMMARY:UTC\nEND:VEVENT")[0]
assert utc["start"] == datetime(2026, 10, 5, 2, 0, tzinfo=__import__("datetime").timezone.utc).astimezone().replace(tzinfo=None)
assert wf.fetch_feed("ftp://x/y.ics").startswith("The link must start") and wf.fetch_feed("file:///etc/passwd").startswith("The link must start")

# settings are private and survive a round trip
cfg = wf.load(); cfg["ics"].append({"name": "Work", "url": "https://example.invalid/secret.ics"}); cfg["snippets"].append({"name": "sig", "text": "Thanks,\nSya", "tags": "mail"}); wf.save(cfg)
assert oct(wf.CONFIG.stat().st_mode & 0o777) == "0o600" and wf.load()["snippets"][0]["text"] == "Thanks,\nSya" and wf.load()["backup"]["on"] is False

# app rules: exact class, escaped for Lua, junk skipped
lua = wf.rules_lua([{"class": "com.microsoft.VSCode", "ws": 2}, {"class": "discord", "ws": "9", "silent": False}, {"class": "", "ws": 1}, {"class": 'a"b', "ws": "x"}])
assert 'match = { class = "^com\\\\.microsoft\\\\.VSCode$" }, workspace = "2 silent"' in lua, lua
assert 'workspace = "9" }' in lua and lua.count("hl.window_rule") == 2
wf.write_rules([{"class": "bruno", "ws": 3}]); assert "app-ws-0" in (wf.HYPR_DIR / "apprules.lua").read_text()

# notes backup: local history, no push unless asked and a remote exists
notes = os.path.join(work, "Notes"); os.makedirs(notes)
assert wf.backup_notes(notes) == "unchanged"
open(os.path.join(notes, "a.md"), "w").write("hello")
assert wf.backup_notes(notes) == "saved" and wf.backup_notes(notes) == "unchanged"
open(os.path.join(notes, "a.md"), "w").write("hello again")
assert wf.backup_notes(notes, push=True) == "saved", "no remote: nothing to push"
log = subprocess.run(["git", "log", "--oneline"], cwd=notes, capture_output=True, text=True).stdout.splitlines()
assert len(log) == 2 and "Notes snapshot" in log[0], log
print("workflow checks passed")
