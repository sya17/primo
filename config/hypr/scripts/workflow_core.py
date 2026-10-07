"""Workflow settings and helpers shared by the hub, the launcher and Settings: calendar feeds (ICS), snippets,
which workspace an app opens on, and the snapshot backup of ~/Notes. Standard library only.

Settings live in ~/.config/primo/workflow.json (readable by you only: a private calendar link is a secret).
"""
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config_core as cc

CONFIG = Path(os.environ.get("PRIMO_WORKFLOW_CONFIG") or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "primo" / "workflow.json")
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprland-dotfiles" / "hub"
HYPR_DIR = Path(os.environ.get("PRIMO_HYPR_DIR", Path.home() / ".config" / "hypr"))

DEFAULTS = {"ics": [], "ics_alert": 10, "app_rules": [], "snippets": [], "backup": {"on": False, "push": False}}


def load():
    data = cc.read_json(CONFIG, dict, {})
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in data.items():
        if k in out:
            out[k] = {**out[k], **v} if isinstance(out[k], dict) and isinstance(v, dict) else v
    return out


def save(data):
    cc.write_json(CONFIG, data, 0o600)


# ----------------------------------------------------------------------------- ICS
def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).replace("\r\n", "\n").replace("\r", "\n")


def unescape(v):
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_when(value, params):
    """(naive local datetime, all_day) from an ICS date or date-time."""
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value, "%Y%m%d")
        return d, True
    m = re.fullmatch(r"(\d{8}T\d{6})(Z?)", value)
    if not m:
        raise ValueError(value)
    dt = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
    if m.group(2):
        return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None), False
    tzid = params.get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return dt.replace(tzinfo=ZoneInfo(tzid)).astimezone().replace(tzinfo=None), False
        except Exception:
            pass
    return dt, False


def parse_ics(text):
    """The events of an ICS file: [{uid, title, start, end, allday, location, rrule, exdates, recurrence_id}]."""
    events, cur = [], None
    for line in unfold(text).split("\n"):
        if line == "BEGIN:VEVENT":
            cur = {"exdates": [], "title": "", "location": "", "rrule": None, "uid": "", "end": None, "recurrence_id": None, "duration": None}
        elif line == "END:VEVENT" and cur is not None:
            if cur.get("start"):
                if cur["end"] is None:
                    cur["end"] = cur["start"] + (cur["duration"] or (timedelta(days=1) if cur["allday"] else timedelta(0)))
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, _, value = line.partition(":")
            name, *plist = head.split(";")
            params = dict(p.split("=", 1) for p in plist if "=" in p)
            name = name.upper()
            try:
                if name == "DTSTART":
                    cur["start"], cur["allday"] = parse_when(value, params)
                elif name == "DTEND":
                    cur["end"], _ = parse_when(value, params)
                elif name == "DURATION":
                    m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value.strip())
                    if m:
                        w, d, h, mi, s = (int(x or 0) for x in m.groups())
                        cur["duration"] = timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
                elif name == "SUMMARY":
                    cur["title"] = unescape(value)
                elif name == "LOCATION":
                    cur["location"] = unescape(value)
                elif name == "UID":
                    cur["uid"] = value.strip()
                elif name == "RRULE":
                    cur["rrule"] = dict(kv.split("=", 1) for kv in value.split(";") if "=" in kv)
                elif name == "EXDATE":
                    for v in value.split(","):
                        cur["exdates"].append(parse_when(v, params)[0])
                elif name == "RECURRENCE-ID":
                    cur["recurrence_id"] = parse_when(value, params)[0]
                elif name == "STATUS" and value.strip().upper() == "CANCELLED":
                    cur["cancelled"] = True
            except (ValueError, KeyError):
                continue
    return events


WEEKDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def expand(ev, since, until):
    """The occurrences of one event that start between two dates (inclusive), as [(start, end)]."""
    length = ev["end"] - ev["start"]
    rule = ev["rrule"]
    window = (datetime.combine(since, datetime.min.time()), datetime.combine(until, datetime.max.time()))
    if not rule:
        return [(ev["start"], ev["end"])] if ev["end"] >= window[0] and ev["start"] <= window[1] else []
    freq = rule.get("FREQ", "")
    interval = max(int(rule.get("INTERVAL", "1") or 1), 1)
    count = int(rule["COUNT"]) if rule.get("COUNT") else None
    last = None
    if rule.get("UNTIL"):
        try:
            last = parse_when(rule["UNTIL"], {})[0]
            if len(rule["UNTIL"]) == 8:
                last = last.replace(hour=23, minute=59)
        except ValueError:
            pass
    byday = [WEEKDAY[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in WEEKDAY]
    out, n = [], 0
    limit = window[1] + timedelta(days=1)
    start = ev["start"]
    k = -1
    while k < 5000:
        k += 1
        if freq == "DAILY":
            cur = start + timedelta(days=interval * k)
            cands = [cur]
        elif freq == "WEEKLY":
            cur = start + timedelta(weeks=interval * k)
            if byday:
                week = cur - timedelta(days=cur.weekday())
                cands = [(week + timedelta(days=d)).replace(hour=start.hour, minute=start.minute, second=start.second) for d in sorted(byday)]
            else:
                cands = [cur]
        elif freq in ("MONTHLY", "YEARLY"):
            months = interval * k * (12 if freq == "YEARLY" else 1)
            y, m = start.year + (start.month - 1 + months) // 12, (start.month - 1 + months) % 12 + 1
            try:
                cands = [start.replace(year=y, month=m)]      # a month without that day (the 31st) has no occurrence
            except ValueError:
                cands = []
            cur = datetime(y, m, 1, start.hour, start.minute)
        else:
            break
        if cur > limit and (not cands or min(cands) > limit):
            break
        for c in cands:
            if c < start:
                continue
            if last and c > last:
                return out
            n += 1
            if count and n > count:
                return out
            if c not in ev["exdates"] and c + length >= window[0] and c <= window[1]:
                out.append((c, c + length))
    return out


def occurrences(events, since, until):
    """Every event instance between two dates, sorted: [{title, start, end, allday, location}]."""
    overridden = {(e["uid"], e["recurrence_id"]) for e in events if e.get("recurrence_id")}
    out = []
    for ev in events:
        if ev.get("cancelled"):
            continue
        for s, e in expand(ev, since, until):
            if not ev.get("recurrence_id") and (ev["uid"], s) in overridden:
                continue
            out.append({"title": ev["title"] or "(no title)", "start": s, "end": e, "allday": ev["allday"], "location": ev["location"],
                        "uid": ev["uid"]})
    return sorted(out, key=lambda o: (o["start"], o["title"]))


def feed_path(url):
    return STATE / f"ics-{hashlib.sha1(url.encode()).hexdigest()[:12]}.ics"


def fetch_feed(url, timeout=15):
    """Download a calendar feed to the cache. Returns '' on success or a short reason."""
    url = url.strip()
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not url.startswith(("https://", "http://")):
        return "The link must start with https://"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Primo/1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(8_000_000)
    except Exception as exc:
        return f"Could not download: {getattr(exc, 'reason', exc)}"
    if b"BEGIN:VCALENDAR" not in data[:4000] and b"BEGIN:VEVENT" not in data:
        return "That link is not a calendar (.ics) feed"
    STATE.mkdir(parents=True, exist_ok=True)
    feed_path(url).write_bytes(data)
    return ""


def feed_text(url):
    try:
        return feed_path(url).read_text(errors="replace")
    except OSError:
        return ""


def load_events(cfg, since, until):
    events = []
    for feed in cfg["ics"]:
        url = feed["url"]
        if url.startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        for o in occurrences(parse_ics(feed_text(url)), since, until):
            o["calendar"] = feed.get("name", "")
            events.append(o)
    return sorted(events, key=lambda o: (o["start"], o["title"]))


# ----------------------------------------------------------------------------- app workspace rules
def lua_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def rules_lua(rules):
    """The file Hyprland loads: one window rule per app. Class names are matched exactly."""
    lines = ["-- Written by Primo Settings (Workflow > Apps on workspaces). Git-ignored: edit it there."]
    for i, r in enumerate(rules):
        if not r.get("class") or not str(r.get("ws", "")).isdigit() or int(r["ws"]) < 1:
            continue
        match = "^" + re.escape(r["class"]) + "$"
        ws = f"{int(r['ws'])}" + (" silent" if r.get("silent", True) else "")
        lines.append(f'hl.window_rule({{ name = {lua_str(f"app-ws-{i}")}, match = {{ class = {lua_str(match)} }}, workspace = {lua_str(ws)} }})')
    return "\n".join(lines) + "\n"


def write_rules(rules):
    cc.atomic_write(HYPR_DIR / "apprules.lua", rules_lua(rules))


# ----------------------------------------------------------------------------- notes backup
def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=Primo", "-c", "user.email=primo@localhost", *args], cwd=cwd, capture_output=True, text=True, timeout=60)


def backup_notes(notes_dir, push=False, now=None):
    """Commit changes in the notes folder (a local history you can go back in). Pushes only when asked and a remote exists.
    Returns a short status: 'unchanged', 'saved', 'saved, pushed', or 'error: ...'."""
    notes_dir = Path(notes_dir)
    if not notes_dir.is_dir():
        return "unchanged"
    try:
        if not (notes_dir / ".git").exists():
            git(notes_dir, "init", "-q")
        git(notes_dir, "add", "-A")
        if not git(notes_dir, "status", "--porcelain").stdout.strip():
            status = "unchanged"
        else:
            msg = f"Notes snapshot {(now or datetime.now()):%Y-%m-%d %H:%M}"
            r = git(notes_dir, "commit", "-q", "-m", msg)
            if r.returncode != 0:
                return "error: " + (r.stderr.strip().splitlines() or ["commit failed"])[-1]
            status = "saved"
        if push and git(notes_dir, "remote").stdout.strip():
            r = git(notes_dir, "push", "-q")
            if r.returncode != 0:
                return "error: " + (r.stderr.strip().splitlines() or ["push failed"])[-1]
            status += ", pushed" if status == "saved" else ""
        return status
    except (OSError, subprocess.SubprocessError) as exc:
        return f"error: {exc}"
