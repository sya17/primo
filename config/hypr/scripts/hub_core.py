"""Time hub core: storage, reminder parsing and the maths for alarms, work hours and the pomodoro cycle.

Standard library only, no GTK, so it can be tested on its own (scripts/check.sh does).
State lives in <state>/hub/hub.json (one file, written atomically); notes are plain Markdown files in ~/Notes,
so Obsidian or any editor can open the folder.
"""
import calendar
import json
import os
import re
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import config_core as cc

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprland-dotfiles" / "hub"
NOTES_DIR = Path(os.environ.get("PRIMO_NOTES_DIR", Path.home() / "Notes"))

DEFAULTS = {
    "reminders": [],
    "alarms": [],
    "timers": [],
    "world": [],
    "work": {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00", "end_on": True, "end_notice": 10,
             "break_on": False, "break_every": 50, "dnd_focus": True},
    "pomodoro": {"focus": 25, "short": 5, "long": 15, "cycles": 4},
    "session": {"phase": "idle", "end": 0.0, "cycle": 0, "left": None, "label": "", "category": "", "seg": None, "worked": 0.0},
    "stopwatch": {"running": False, "start": 0.0, "elapsed": 0.0, "laps": []},
    "focus": {"label": "", "category": "Work"},
    "log": [],
    "last_tab": "calendar",
    "fired": {},
}


def merged(defaults, data):
    out = {}
    for k, v in defaults.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            out[k] = merged(v, data[k])
        else:
            out[k] = data.get(k, json.loads(json.dumps(v)))
    return out


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else STATE_DIR / "hub.json"
        self.data = merged(DEFAULTS, cc.read_json(self.path, dict, {}))

    def save(self):
        cc.write_json(self.path, self.data)

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value


def new_id():
    return uuid.uuid4().hex[:8]


# ----------------------------------------------------------------------------- reminder text
WEEKDAYS = {"mon": 0, "monday": 0, "senin": 0, "tue": 1, "tues": 1, "tuesday": 1, "selasa": 1, "wed": 2, "wednesday": 2,
            "rabu": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "kamis": 3, "fri": 4, "friday": 4, "jumat": 4,
            "sat": 5, "saturday": 5, "sabtu": 5, "sun": 6, "sunday": 6, "minggu": 6}
REPEATS = [
    (r"\b(?:every ?day|daily|setiap hari|tiap hari|harian)\b", "daily"),
    (r"\b(?:every weekday|weekdays|setiap hari kerja|hari kerja)\b", "weekdays"),
    (r"\b(?:every week|weekly|setiap minggu|tiap minggu|mingguan)\b", "weekly"),
    (r"\b(?:every month|monthly|setiap bulan|tiap bulan|bulanan)\b", "monthly"),
]
UNITS = {"m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1, "menit": 1, "h": 60, "hr": 60, "hrs": 60, "hour": 60,
         "hours": 60, "jam": 60, "d": 1440, "day": 1440, "days": 1440, "hari": 1440}


class _Text:
    """A string plus its lowercase twin, so a matched span can be cut out of both."""

    def __init__(self, text):
        self.s, self.low = " " + text.strip() + " ", " " + text.strip().lower() + " "

    def take(self, pattern):
        m = re.search(pattern, self.low)
        if m:
            self.s = self.s[:m.start()] + " " + self.s[m.end():]
            self.low = self.low[:m.start()] + " " + self.low[m.end():]
        return m


def parse_reminder(text, now=None):
    """'call the bank tomorrow 14:00 #work' -> {'title','due','repeat','tag'}. English and Indonesian words."""
    now = now or datetime.now()
    t = _Text(text)
    repeat = None
    for pattern, kind in REPEATS:
        if t.take(pattern):
            repeat = kind
            while t.take(pattern):   # "weekly report every week": cut every spelling
                pass
            break
    tag = None
    m = re.search(r"(?:^|\s)[#@](\w+)", t.s)
    if m:
        tag = m.group(1).lower()
        t.s = t.s[:m.start()] + " " + t.s[m.end():]
        t.low = t.s.lower()

    due, day, hm = None, None, None
    m = t.take(r"\b(?:in|dalam)\s+(\d+)\s*(m|mins?|minutes?|menit|h|hrs?|hours?|jam|d|days?|hari)\b")
    if m:
        due = now + timedelta(minutes=int(m.group(1)) * UNITS[m.group(2)])
    else:
        if t.take(r"\b(?:tomorrow|besok)\b"):
            day = now.date() + timedelta(days=1)
        elif t.take(r"\b(?:today|hari ini)\b"):
            day = now.date()
        elif t.take(r"\b(?:tonight|malam ini)\b"):
            day, hm = now.date(), (20, 0)
        else:
            m = t.take(r"\b(?:on |pada |hari )?(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b")
            if m:
                ahead = (WEEKDAYS[m.group(1)] - now.weekday()) % 7 or 7
                day = now.date() + timedelta(days=ahead)
        m = (t.take(r"\b(?:at |jam |pukul |@)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b")
             or t.take(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b")
             or t.take(r"\b(\d{1,2})()\s*(am|pm)\b"))
        if m:
            h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
            if ap == "pm" and h < 12:
                h += 12
            if ap == "am" and h == 12:
                h = 0
            if h < 24 and mi < 60:
                hm = (h, mi)
        if day or hm or repeat:
            hm = hm or (9, 0)
            when = datetime.combine(day or now.date(), datetime.min.time()).replace(hour=hm[0], minute=hm[1])
            if not day and when <= now:
                when += timedelta(days=1)
            due = when
    title = re.sub(r"\s+", " ", t.s).strip(" ,.-")
    title = re.sub(r"^(?:to|untuk|ingatkan|remind me to|remind me)\s+", "", title, flags=re.I).strip() or text.strip()
    return {"title": title, "due": due, "repeat": repeat, "tag": tag}


def advance(due, repeat):
    """The next due time of a repeating reminder."""
    if repeat == "daily":
        return due + timedelta(days=1)
    if repeat == "weekly":
        return due + timedelta(days=7)
    if repeat == "weekdays":
        nxt = due + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        return nxt
    if repeat == "monthly":
        y, m = (due.year + (due.month // 12), due.month % 12 + 1)
        return due.replace(year=y, month=m, day=min(due.day, calendar.monthrange(y, m)[1]))
    return None


def human_due(due, now=None):
    now = now or datetime.now()
    if due is None:
        return "No date"
    d = due.date() - now.date()
    clock = due.strftime("%H:%M")
    if d.days == 0:
        return f"Today {clock}"
    if d.days == 1:
        return f"Tomorrow {clock}"
    if d.days == -1:
        return f"Yesterday {clock}"
    if 0 < d.days < 7:
        return f"{due.strftime('%a')} {clock}"
    return f"{due.strftime('%a %d %b')} {clock}"


# ----------------------------------------------------------------------------- alarms
def next_alarm(alarm, now=None):
    """Next time the alarm rings (datetime), or None when it is off."""
    if not alarm.get("on", True):
        return None
    now = now or datetime.now()
    h, m = (int(x) for x in alarm["time"].split(":"))
    days = alarm.get("days") or []
    for ahead in range(0, 8):
        cand = (now + timedelta(days=ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
        if cand > now and (not days or cand.weekday() in days):
            return cand
    return None


# ----------------------------------------------------------------------------- work hours
def parse_hm(text):
    h, m = (int(x) for x in text.split(":"))
    return h * 60 + m


def work_state(cfg, now=None):
    """{'working': bool, 'progress': 0..1, 'left': minutes to the end, 'next': datetime of the next start}."""
    now = now or datetime.now()
    start, end = parse_hm(cfg["start"]), parse_hm(cfg["end"])
    mins = now.hour * 60 + now.minute
    working = now.weekday() in cfg["days"] and start <= mins < end
    nxt = None
    for ahead in range(0, 8):
        day = now + timedelta(days=ahead)
        cand = day.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
        if day.weekday() in cfg["days"] and cand > now:
            nxt = cand
            break
    span = max(end - start, 1)
    return {"working": working, "progress": (mins - start) / span if working else 0.0,
            "left": end - mins if working else 0, "next": nxt}


# ----------------------------------------------------------------------------- pomodoro
def next_phase(phase, cycle, cfg):
    """(next phase, minutes, cycle) after `phase` ends. A long break comes after every `cycles` focus blocks."""
    if phase == "focus":
        cycle += 1
        if cycle >= cfg["cycles"]:
            return "long", cfg["long"], 0
        return "short", cfg["short"], cycle
    return "focus", cfg["focus"], cycle


def fmt_clock(seconds):
    seconds = max(0, int(seconds + 0.999))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ----------------------------------------------------------------------------- notes
def list_notes(keep=None):
    """Notes, newest first. Empty files are left out (a note you opened and never typed in), except `keep`."""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    notes = []
    for p in NOTES_DIR.glob("*.md"):
        try:
            text = p.read_text()
        except OSError:
            continue
        if not text.strip() and p != keep:
            continue
        lines = [ln.strip().lstrip("#").strip() for ln in text.splitlines() if ln.strip()]
        notes.append({"path": p, "title": lines[0] if lines else "New note", "preview": lines[1] if len(lines) > 1 else "",
                      "mtime": p.stat().st_mtime})
    return sorted(notes, key=lambda n: -n["mtime"])


def new_note_path():
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_DIR / f"{datetime.now():%Y-%m-%d-%H%M%S}.md"


# ----------------------------------------------------------------------------- time report
CATEGORIES = ["Work", "Research", "Learning", "Personal", "Other"]


def fmt_minutes(m):
    m = int(round(m))
    h, mi = divmod(m, 60)
    return f"{h}h {mi:02d}m" if h else f"{mi}m"


def report(log, since, until):
    """Totals (minutes) of the focus log between two dates, inclusive: by category, label and day."""
    out = {"total": 0.0, "by_cat": {}, "by_label": {}, "by_day": {}}
    for e in log:
        d = datetime.fromtimestamp(e["start"]).date()
        if since <= d <= until:
            out["total"] += e["min"]
            cat, lab = e.get("cat") or "Other", e.get("label") or "(no label)"
            out["by_cat"][cat] = out["by_cat"].get(cat, 0.0) + e["min"]
            out["by_label"][lab] = out["by_label"].get(lab, 0.0) + e["min"]
            out["by_day"][d] = out["by_day"].get(d, 0.0) + e["min"]
    return out


def range_for(name, today):
    if name == "today":
        return today, today
    if name == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])


def csv_text(log, since, until):
    lines = ["date,start,end,minutes,category,label"]
    for e in sorted(log, key=lambda e: e["start"]):
        s = datetime.fromtimestamp(e["start"])
        if since <= s.date() <= until:
            label = '"' + (e.get("label") or "").replace('"', '""') + '"'
            lines.append(f"{s:%Y-%m-%d},{s:%H:%M},{datetime.fromtimestamp(e['end']):%H:%M},{e['min']:.0f},{e.get('cat', '')},{label}")
    return "\n".join(lines) + "\n"


def markdown_summary(log, since, until):
    r = report(log, since, until)
    lines = [f"# Time {since:%d %b} to {until:%d %b %Y}: {fmt_minutes(r['total'])}", ""]
    lines += [f"- {c}: {fmt_minutes(m)}" for c, m in sorted(r["by_cat"].items(), key=lambda x: -x[1])]
    lines += ["", "## By label"] + [f"- {l}: {fmt_minutes(m)}" for l, m in sorted(r["by_label"].items(), key=lambda x: -x[1])]
    return "\n".join(lines) + "\n"


def previous_work_day(cfg, today):
    """The last day you were meant to work before `today` (Friday for a Monday)."""
    for back in range(1, 8):
        d = today - timedelta(days=back)
        if d.weekday() in cfg["days"]:
            return d
    return today - timedelta(days=1)


def standup_text(data, now):
    """A daily note: what was done on the last work day, what is on today."""
    today = now.date()
    prev = previous_work_day(data["work"], today)
    lines = [f"# Daily note {today:%Y-%m-%d} ({today:%A})", "", f"## {prev:%A} " + ("(yesterday)" if prev == today - timedelta(days=1) else "(last work day)")]
    done = [r for r in data["reminders"] if r.get("done") and r.get("done_at") and datetime.fromisoformat(r["done_at"]).date() == prev]
    lines += [f"- Done: {r['title']}" for r in done] or ["- (nothing marked done)"]
    rep = report(data["log"], prev, prev)
    if rep["total"]:
        lines += ["", f"Focus time: {fmt_minutes(rep['total'])}"] + [f"- {l}: {fmt_minutes(m)}" for l, m in sorted(rep["by_label"].items(), key=lambda x: -x[1])]
    lines += ["", "## Today"]
    todo = sorted((r for r in data["reminders"] if not r.get("done") and r.get("due") and datetime.fromisoformat(r["due"]).date() <= today),
                  key=lambda r: r["due"])
    lines += [f"- [ ] {datetime.fromisoformat(r['due']):%H:%M} {r['title']}" for r in todo] or ["- [ ] "]
    lines += ["", "## Blockers", "- ", "", "## Notes", ""]
    return "\n".join(lines)
