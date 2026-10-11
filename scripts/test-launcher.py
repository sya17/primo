#!/usr/bin/env python3
"""Checks for the launcher's sources: calculator, matching, command words, privacy of the clipboard source, and a failing source.

No GTK and no live system: Facts is replaced by sample data and nothing is launched.
"""
import os
import sys
import tempfile

work = tempfile.mkdtemp()
os.environ["XDG_STATE_HOME"] = os.path.join(work, "state")
os.environ["XDG_CONFIG_HOME"] = os.path.join(work, "config")      # real Facts read snippets and modes from here: never the user's own
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "hypr", "scripts"))
import launcher_core as lc


class App:
    def __init__(self, name, ident, generic="", keywords=()):
        self.name, self.ident, self.generic, self.keywords = name, ident, generic, list(keywords)

    def get_display_name(self): return self.name
    def get_generic_name(self): return self.generic
    def get_description(self): return ""
    def get_icon(self): return None
    def get_id(self): return self.ident
    def get_keywords(self): return self.keywords


class FakeFacts:
    missing = ()          # tools that are not installed

    def has(self, binary):
        return binary not in self.missing

    def clients(self):
        return [{"address": "0xabc1", "class": "firefox", "title": "Sample page", "workspace": {"id": 2, "name": "2"}},
                {"address": "0xabc2", "class": "kitty", "title": "build", "workspace": {"id": 1, "name": "1"}},
                {"address": "0xabc3", "class": "dev.primo.Launcher", "title": "Launcher", "workspace": {"id": 1, "name": "1"}},
                {"address": "0xabc4; rm -rf", "class": "evil", "title": "bad address", "workspace": {"id": 1, "name": "1"}}]

    def workspaces(self):
        return [{"id": 1, "windows": 2, "lastwindowtitle": "build"}, {"id": 2, "windows": 1, "lastwindowtitle": "Sample page"}, {"id": 5, "windows": 0}]

    def themes(self):
        return [{"id": "primo-dusk", "name": "Primo Dusk", "mode": "dark"}, {"id": "primo-dawn", "name": "Primo Dawn", "mode": "light"},
                {"id": "bad id;", "name": "Bad", "mode": "dark"}]

    def clipboard(self):
        return [{"id": "7", "preview": "sample-secret-token-123"}, {"id": "6", "preview": "[[ binary data 12 KiB png 10x10 ]]"}, {"id": "x1", "preview": "bad id row"}]

    def snippets(self):
        return [{"name": "Sample greeting", "text": "Hello there", "tags": "mail"}]

    def modes(self):
        return [{"id": "work", "name": "Work", "icon": "emblem-system"}]


facts = FakeFacts()
ctx = lc.Context(apps=[App("Firefox", "firefox.desktop", "Web Browser", ["internet"]), App("Visual Studio Code", "code.desktop"), App("Kitty", "kitty.desktop")],
                 facts=facts, launch_app=lambda i: None)


def titles(q, **kw):
    return [i.title for i in lc.collect(q, ctx, **kw)]


def kinds(q):
    return [i.kind for i in lc.collect(q, ctx)]


# calculator
assert lc.calculate("12*(3+4)") == "84" and lc.calculate("15% of 80") == "12" and lc.calculate("sqrt(16)") == "4"
assert lc.calculate("2^10") == "1024" and lc.calculate("10/4") == "2.5" and lc.calculate("1/0") is None
assert lc.calculate("firefox") is None and lc.calculate("2**99999") is None and lc.calculate("__import__('os')") is None
assert lc.collect("1+1", ctx)[0].kind == "calc" and "web" not in kinds("1+1")        # math is not also a web search

# matching
assert lc.fuzzy("fire", "Firefox") == 90 and lc.fuzzy("vsc", "Visual Studio Code") == 60 and lc.fuzzy("xyz", "Firefox") == 0

# plain queries find apps, windows and the web fallback; the launcher's own window never lists itself
assert titles("fire")[0] == "Firefox" and "web" in kinds("fire")
assert "Sample page" in titles("sample") and "Launcher" not in titles("launcher")
assert "window" not in kinds("bad") and "window" not in kinds("evil")             # an address that is not plain hex is never used
assert "Start Work mode" in titles("work") and "Sample greeting" in titles("greeting")

# command words
assert titles("ws 5") == ["Go to workspace 5"] and kinds("ws 2") == ["workspace"]
assert titles("ws ") == ["Go to workspace 1", "Go to workspace 2", "Go to workspace 5"] and "Go to workspace 1" in titles("ws")
assert titles("theme dusk") == ["Switch to Primo Dusk"] and titles("theme light") == ["Switch to Primo Dawn"]
assert "Switch to Bad" not in titles("theme ")                                          # an id that is not a plain name is never run
assert titles("win kitty") == ["build"] and set(kinds("win ")) == {"window"}
assert "Go to workspace 5" not in titles("ws 7") and titles("ws 150") == []              # out-of-range numbers do not match

# clipboard: only when asked for
assert "clipboard" not in kinds("sample-secret") and "clipboard" not in kinds("token")
assert "clipboard" not in kinds("clip") and "clipboard" not in kinds("secret")
assert titles("clip secret") == ["sample-secret-token-123"] and titles("cb ") == ["sample-secret-token-123", "Image: 12 KiB png 10x10"]
assert "bad id row" not in titles("clip ") and set(kinds("clip ")) == {"clipboard"}      # a non-numeric id is never passed to the shell

# actions whose tool is not installed are not listed; actions that need nothing always are
import doctor_core as dc
assert "Toggle night light" in titles("night") and "Pick a colour" in titles("colour") and "Clipboard history" in titles("history")
facts.missing = {"hyprsunset", "hyprpicker"}
assert "Toggle night light" not in titles("night") and "Pick a colour" not in titles("colour")             # a tool named by the action
assert "Clipboard history" in titles("history") and "Health" in titles("health")
facts.missing = {"cliphist"}
assert "Clipboard history" not in titles("history") and "Toggle night light" in titles("night")  # a feature's requirements, from the doctor registry
assert "Take screenshot" in titles("screenshot") and "Health" in titles("health")
facts.missing = {"grim"}
assert "Take screenshot" not in titles("screenshot")
facts.missing = ()
assert set(lc.NEEDS) <= {a[0] for a in lc.ACTIONS}, "a rule for an action that does not exist"
assert all(dc.FEATURES_BY_ID[n].requires for n in lc.NEEDS.values() if n in dc.FEATURES_BY_ID), "a feature with no requirements would hide nothing"

# looking for a tool is cached: typing never runs `which` again for the same name
asked = []
real_which = lc.shutil.which
lc.shutil.which = lambda b: asked.append(b) or (None if b == "nothing-here" else "/usr/bin/" + b)
try:
    live = lc.Facts()
    assert [live.has("tool"), live.has("tool"), live.has("nothing-here"), live.has("nothing-here")] == [True, True, False, False] and asked == ["tool", "nothing-here"], asked
finally:
    lc.shutil.which = real_which

# the sample machine for documentation screenshots: invented windows, nothing of the user's own
sf = lc.SampleFacts()
sample_ctx = lc.Context(facts=sf)
assert [i.title for i in lc.collect("ws ", sample_ctx)] == ["Go to workspace 1", "Go to workspace 2", "Go to workspace 3"]
assert lc.collect("win ", sample_ctx) and {i.kind for i in lc.collect("win ", sample_ctx)} == {"window"}
assert sf.snippets() == [] and sf.modes() == [] and sf.clipboard() == []

# ---- file search: pruned before traversal, literal names, one child at a time, newest query only, bounded
import subprocess, threading, time
from pathlib import Path
tree = Path(tempfile.mkdtemp())
for rel in ["notes/report.txt", "notes/a*b [x].txt", "node_modules/pkg/report.js", ".cache/report.bin", "code/.git/report.pack", "deep/1/2/3/4/5/6/report.md"]:
    (tree / rel).parent.mkdir(parents=True, exist_ok=True)
    (tree / rel).write_text("x")
(tree / "node_modules" / "locked").mkdir()
(tree / "node_modules" / "locked").chmod(0)                     # if find went inside, it would complain about this folder
def find(q):
    r = subprocess.run(lc.find_command(tree, q), capture_output=True, text=True)
    return sorted(Path(line).relative_to(tree).as_posix() for line in r.stdout.splitlines()), r.stderr
hits, err = find("report")
assert hits == ["notes/report.txt"] and err == "", (hits, err)     # hidden folders and node_modules pruned, depth bounded
assert find("b [x")[0] == ["notes/a*b [x].txt"] and find("*")[0] == ["notes/a*b [x].txt"] and find("?")[0] == []   # glob characters are literal
assert find("-delete")[0] == [] and (tree / "notes/report.txt").exists()                                         # a query is never an option
(tree / "node_modules" / "locked").chmod(0o700)

delivered, children, alive_max = [], [], [0]
def slow_child(text):                                            # stands in for find: prints after a while, or many lines at once
    code = "import sys,time; time.sleep(float(sys.argv[1])); [print(f'/x/{sys.argv[2]}-{i}', flush=True) for i in range(int(sys.argv[3]))]; time.sleep(float(sys.argv[4]))"
    delay, count, tail = {"slow": ("0.6", "1", "0"), "many": ("0", "50", "5"), "hang": ("9", "1", "0")}.get(text.split()[0], ("0.05", "1", "0"))
    return [sys.executable, "-c", code, delay, text.replace(" ", "_"), count, tail]
class Spy(lc.FileSearch):
    def _start(self, cmd):
        proc = super()._start(cmd)
        children.append(proc)
        alive_max[0] = max(alive_max[0], sum(1 for c in children if c.poll() is None))
        return proc
def wait_idle(fs, limit=8.0):
    end = time.time() + limit
    while fs.busy and time.time() < end:
        time.sleep(0.02)
    assert not fs.busy, "the search worker did not finish"

fs = Spy(lambda q, hits: delivered.append((q, hits)), command=slow_child, limit=6, timeout=1.0)
fs.search("slow one")
time.sleep(0.15)
fs.search("slow two")                                            # supersedes: the running child is stopped, only the newest result arrives
fs.search("quick three")
wait_idle(fs)
assert delivered == [("quick three", ["/x/quick_three-0"])], delivered
assert alive_max[0] == 1 and all(c.returncode is not None for c in children), "one child at a time, every child reaped"
assert len(children) == 2 and children[0].returncode < 0, "the superseded child was stopped; the middle query never started"

delivered.clear(); children.clear()
fs.search("many lines")                                          # stops reading (and the child) once enough results are in
wait_idle(fs)
assert delivered == [("many lines", [f"/x/many_lines-{i}" for i in range(6)])] and children[0].returncode < 0, delivered

delivered.clear(); children.clear()
fs.search("hang forever")                                        # a child that takes too long is stopped; nothing stale is shown
wait_idle(fs)
assert delivered == [("hang forever", [])] and children[0].returncode < 0, delivered

delivered.clear(); children.clear()
fs.search("slow again")
time.sleep(0.15)
fs.cancel()                                                      # window closed or the query no longer searches files
wait_idle(fs)
assert delivered == [] and children[0].returncode < 0, delivered
assert "pkill" not in Path(lc.__file__).read_text() and "killall" not in Path(lc.__file__).read_text()

# a failing source is skipped, the rest still answer
class Broken(lc.Provider):
    id, label, order, limit = "broken", "BROKEN", 1, 3
    def query(self, q, ctx, args): raise RuntimeError("boom")
import logging
records = []
catch = logging.Handler(); catch.emit = records.append
logging.getLogger("primo.launcher").addHandler(catch)
assert titles("fire", providers=[Broken()] + lc.PROVIDERS)[0] == "Firefox"
assert titles("firef", providers=[Broken()] + lc.PROVIDERS)[0] == "Firefox"
assert [r.getMessage() for r in records] == ["source broken failed: RuntimeError: boom"], "a failing source is logged once, not on every keystroke"

# empty query: only apps you opened before (history), nothing else
assert lc.collect("", ctx) == []
ctx.history = {"firefox.desktop": 3}
assert titles("") == ["Firefox"]

# history is stored and read back
lc.bump_history("a.desktop"); lc.bump_history("a.desktop")
assert lc.load_history()["a.desktop"] == 2

# ---- the typing path never waits for a tool: cached facts answer, a worker refreshes what a query used, and only that
import json
import threading
import time
import proc_core as pc

gate, cancelled_runs, running, most = threading.Event(), [], [0], [0]
CLIENTS = json.dumps([{"address": "0xa1", "class": "firefox", "title": "Sample page", "mapped": True, "workspace": {"id": 2, "name": "2"}}])


def fake_run(cmd, cancel):
    running[0] += 1
    most[0] = max(most[0], running[0])
    try:
        if cmd[0] == "hyprctl":
            end = time.monotonic() + 5
            while not gate.is_set() and not cancel.is_set() and time.monotonic() < end:
                time.sleep(0.01)
            if cancel.is_set():
                cancelled_runs.append(cmd[:2])
                return pc.Run(reason="cancelled")
            return pc.Run(code=0, out=CLIENTS if cmd[1] == "clients" else "[]")
        if cmd[0] == "cliphist":
            return pc.Run(code=0, out="7\tsample-secret\n")
        return pc.Run(reason="missing")
    finally:
        running[0] -= 1


facts = lc.Facts(run=fake_run)
cold = lc.Context(apps=ctx.apps, facts=facts, launch_app=lambda i: None)
t0 = time.monotonic()
got = [i.title for i in lc.collect("fire", cold)]
assert time.monotonic() - t0 < 0.3 and got[0] == "Firefox" and "Sample page" not in got, (got, time.monotonic() - t0)   # blocked hyprctl, instant answer
assert facts.take_wanted() == ("clients", "modes", "snippets") and facts.take_wanted() == (), "it says what it still needs, once"
assert facts.state("clients") is None and facts.peek("clients") is None

# the worker: one refresh at a time, one latest pending request (the keys of the waiting requests are merged), results only while it is alive
delivered = []
worker = lc.FactsWorker(facts, delivered.append)
worker.request(("clients",))
time.sleep(0.1)
worker.request(("snippets",))
worker.request(("modes",))
worker.request(("clients", "modes"))
assert most[0] == 1 and worker.pending == {"snippets", "modes", "clients"}, (most, worker.pending)
gate.set()
end = time.monotonic() + 5
while worker.busy and time.monotonic() < end:
    time.sleep(0.01)
assert not worker.busy and len(delivered) == 2 and most[0] == 1, (len(delivered), most)          # not one run per request
assert "clients" in delivered[0] and set(delivered[1]) <= {"snippets", "modes", "clients"}
assert "Sample page" in [i.title for i in lc.collect("fire", cold)], "the refreshed windows are in the next answer"
assert facts.state("clients") == "ok" and facts.take_wanted() == ()                                  # fresh now: nothing more is asked

# a new query asks only for what its providers used; the clipboard only inside its own namespace
facts2 = lc.Facts(run=fake_run)
cold2 = lc.Context(apps=ctx.apps, facts=facts2, launch_app=lambda i: None)
lc.collect("fire", cold2)
assert "clipboard" not in facts2.take_wanted()
lc.collect("clip sample", cold2)
assert facts2.take_wanted() == ("clipboard",)
lc.collect("ws ", cold2)
assert facts2.take_wanted() == ("workspaces",), "a namespace asks for its own facts only"

# unavailable is not empty: a tool that times out keeps the last good value and says so; an empty answer is a good answer
unreliable = {"fail": False}
def flaky_run(cmd, cancel):
    return pc.Run(reason="timeout") if unreliable["fail"] else pc.Run(code=0, out=CLIENTS)
f3 = lc.Facts(run=flaky_run)
f3.refresh(("clients",), threading.Event())
assert f3.state("clients") == "ok" and f3.clients()[0]["class"] == "firefox"
unreliable["fail"] = True
f3._cache["clients"] = (0.0, f3._cache["clients"][1])           # expired
f3.refresh(("clients",), threading.Event())
assert f3.state("clients") == "unavailable" and f3.clients()[0]["class"] == "firefox", "the last good windows stay on screen"
f3.take_wanted()
assert f3.clients() and f3.take_wanted() == (), "a failure counts as an answer for its lifetime: no retry loop"
empty = lc.Facts(run=lambda cmd, cancel: pc.Run(code=0, out="[]"))
empty.refresh(("clients",), threading.Event())
assert empty.state("clients") == "ok" and empty.clients() == []

# closing the window: nothing is delivered afterwards, and the command in flight is stopped
gate.clear()
cancelled_runs.clear()
late = []
w2 = lc.FactsWorker(lc.Facts(run=fake_run), late.append)
w2.request(("clients",))
time.sleep(0.15)
w2.cancel()
end = time.monotonic() + 5
while w2.busy and time.monotonic() < end:
    time.sleep(0.01)
assert not w2.busy and late == [] and cancelled_runs, (late, cancelled_runs)
w3 = lc.FactsWorker(lc.Facts(run=fake_run), late.append)        # the next window starts clean
gate.set()
w3.request(("clients",))
end = time.monotonic() + 5
while (w3.busy or not late) and time.monotonic() < end:
    time.sleep(0.01)
assert len(late) == 1

# a refresh that finishes after the window closed (a tool that ignores the stop) is dropped too
gate2, after_close = threading.Event(), []
def stubborn(cmd, cancel):
    gate2.wait(5)
    return pc.Run(code=0, out=CLIENTS)
w4 = lc.FactsWorker(lc.Facts(run=stubborn), after_close.append)
w4.request(("clients",))
time.sleep(0.1)
w4.cancel()
gate2.set()
end = time.monotonic() + 5
while w4.busy and time.monotonic() < end:
    time.sleep(0.01)
assert not w4.busy and after_close == [], after_close

# a reader that raises something unexpected is "unavailable", and the worker stays usable for the next request
def bad_run(cmd, cancel):
    return pc.Run(code=0, out='{"not": "a list"}')
f5 = lc.Facts(run=bad_run)
survived = []
w5 = lc.FactsWorker(f5, survived.append)
w5.request(("clients",))
end = time.monotonic() + 3
while w5.busy and time.monotonic() < end:
    time.sleep(0.01)
assert not w5.busy and f5.state("clients") == "unavailable" and f5.clients() == [], (w5.busy, f5.state("clients"))
f5._run = lambda cmd, cancel: pc.Run(code=0, out=CLIENTS)
f5._cache["clients"] = (0.0, [])
w5.request(("clients",))
end = time.monotonic() + 3
while (w5.busy or not survived) and time.monotonic() < end:
    time.sleep(0.01)
assert survived and f5.state("clients") == "ok" and f5.clients()[0]["class"] == "firefox", "the second request worked"

# only what changed is delivered, and the keys a list used are known
f6 = lc.Facts(run=lambda cmd, cancel: pc.Run(code=0, out=CLIENTS))
assert set(f6.refresh(("clients", "modes"), threading.Event())) == {"clients", "modes"}
f6._cache["clients"] = (0.0, f6._cache["clients"][1])
assert f6.refresh(("clients",), threading.Event()) == {}, "the same answer again is not news"
lc.collect("fire", lc.Context(apps=ctx.apps, facts=f6, launch_app=lambda i: None))
assert {"clients", "snippets", "modes"} <= f6.take_used() and f6.take_used() == set()
f6.forget("clients")
assert f6.peek("clients") is None and f6.state("clients") is None

# a provider that fails does not take the healthy results with it (here: every tool is missing)
dead = lc.Context(apps=ctx.apps, facts=lc.Facts(run=lambda cmd, cancel: pc.Run(reason="missing")), launch_app=lambda i: None)
assert [i.title for i in lc.collect("fire", dead)][0] == "Firefox"

# history: read once, re-read only when the file changed (by us or by someone else)
reads_before = lc.history_reads
lc.bump_history("b.desktop")
assert lc.load_history()["b.desktop"] == 1 and lc.load_history()["b.desktop"] == 1
assert lc.history_reads - reads_before <= 1, "keystrokes do not re-read an unchanged file"
lc.HISTORY.write_text(json.dumps({"c.desktop": 9}))
os.utime(lc.HISTORY, ns=(1, 1))
assert lc.load_history() == {"c.desktop": 9}

# ---- system namespaces: audio network vpn capture display power doctor (explicit prefix only, fixed argv, nothing runs while typing)
SYSTEM = ("audio", "network", "vpn", "capture", "display", "power", "doctor")
SETTINGS = str(lc.SCRIPTS / "primo-settings.py")
spawned = []
real_spawn, real_shell = lc.spawn, lc.shell
lc.spawn = lambda *cmd: spawned.append(cmd)
lc.shell = lambda cmd: spawned.append(("sh", "-c", cmd))


class QuietFacts(FakeFacts):
    """Only tool lookups are allowed: a namespace never reads windows, the clipboard or anything else to answer."""
    def __init__(self):
        self.asked = []
    def has(self, binary):
        self.asked.append(binary)
        return binary not in self.missing
    def clipboard(self): raise AssertionError("clipboard read for a system namespace")
    def clients(self): raise AssertionError("windows read for a system namespace")


def system(q, missing=()):
    qf = QuietFacts()
    qf.missing = set(missing)
    c = lc.Context(apps=ctx.apps, facts=qf, launch_app=lambda i: None, file_hits=["/home/sample/audio-notes.txt"])
    got = lc.collect(q, c)
    assert not spawned, ("typing started something", q, spawned)
    return got


def argv_of(item):
    spawned.clear()
    item.run()
    out = spawned[:]
    spawned.clear()
    return out


# every word routes to its own provider, only with a space after it
for word in SYSTEM:
    provider, args = lc.route(word + " ")
    assert provider is not None and provider.commands[0] == word and args == "", word
    assert lc.route(word)[0] is None, "a bare word is a normal search, so it does not duplicate the actions"
    assert {i.kind for i in system(word + " ")} == {word}, (word, "other sources must not answer an explicit namespace (no file hits, no apps)")
assert lc.route("health ")[0] is lc.route("doctor ")[0], "health is the same namespace as doctor"
assert len({lc.route(w + " ")[0].id for w in SYSTEM}) == 7

# the table: each namespace, its results, and the exact argv they run
expected = {
    "audio": [("Open Audio settings", [("python3", SETTINGS, "--page", "audio")]),
              ("Open the sound mixer", [("pavucontrol",)]),
              ("Mute or unmute the microphone", [("pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle")])],
    "network": [("Open Network settings", [("python3", SETTINGS, "--page", "network")]),
                ("Open the advanced connection editor", [("nm-connection-editor",)])],
    "vpn": [("Open VPN settings", [("python3", SETTINGS, "--page", "vpn")])],
    "display": [("Open Displays settings", [("python3", SETTINGS, "--page", "displays")]),
                ("Toggle night light", [(str(lc.SCRIPTS / "nightlight.sh"), "toggle")])],
    "power": [("Open Power settings", [("python3", SETTINGS, "--page", "power")]),
              ("Open the session menu", [(str(lc.SCRIPTS / "power-menu.sh"),)]),
              ("Log out", [(str(lc.SCRIPTS / "power-menu.sh"), "logout")])],
    "doctor": [("Open Health", [("python3", SETTINGS, "--page", "health")])],
    "capture": [("Screenshot an area", [(str(lc.SCRIPTS / "screenshot.sh"), "area")]),
                ("Screenshot the whole screen", [(str(lc.SCRIPTS / "screenshot.sh"), "full")]),
                ("Screenshot an area and annotate it", [(str(lc.SCRIPTS / "screenshot.sh"), "edit")]),
                ("Record an area", [(str(lc.SCRIPTS / "record.sh"), "toggle", "area")]),
                ("Record the whole screen", [(str(lc.SCRIPTS / "record.sh"), "toggle", "full")])],
}
assert set(expected) == set(SYSTEM)
for word, rows in expected.items():
    got = system(word + " ")
    assert [(i.title, argv_of(i)) for i in got] == rows, (word, [i.title for i in got])
    assert all(i.run is not None and i.subtitle for i in got)

# a word after the command filters inside the namespace
assert [i.title for i in system("audio mic")] == ["Mute or unmute the microphone"]
assert [i.title for i in system("capture record")] == ["Record an area", "Record the whole screen"]
assert [i.title for i in system("health ")] == ["Open Health"]
assert [i.title for i in system("display night")] == ["Toggle night light"]

# labels: opening something says Open, changing a setting says what it changes
for word in SYSTEM:
    for i in system(word + " "):
        assert i.title.split()[0] in ("Open", "Mute", "Toggle", "Log", "Screenshot", "Record"), i.title
assert all(i.title.startswith("Open") for i in system("audio ") if "settings" in i.title.lower() or "mixer" in i.title.lower())

# per-action requirements, from the doctor registry and program names: unavailable actions are not shown
assert [i.title for i in system("audio ", missing={"pavucontrol"})] == ["Open Audio settings", "Mute or unmute the microphone"]
assert [i.title for i in system("network ", missing={"nm-connection-editor"})] == ["Open Network settings"]
assert [i.title for i in system("capture ", missing={"satty"})] == [t for t, _ in expected["capture"] if "annotate" not in t]
assert [i.title for i in system("capture ", missing={"wf-recorder"})][-1] == "Screenshot an area and annotate it"
assert "Open the session menu" not in [i.title for i in system("power ", missing={"wofi"})]
assert "Open Power settings" not in [i.title for i in system("power ", missing={"powerprofilesctl"})]
assert "Log out" in [i.title for i in system("power ", missing={"powerprofilesctl"})]

# an empty namespace says why instead of falling to files or apps; the note changes nothing
for word, tools in (("audio", {"pactl"}), ("network", {"nmcli", "nm-connection-editor"}), ("vpn", {"nmcli"}), ("capture", {"grim", "slurp", "wf-recorder"})):
    got = system(word + " ", missing=tools)
    assert [i.kind for i in got] == [word] * len(got), (word, "no file or app falls through")
    if word != "audio":
        assert len(got) == 1 and "not available" in got[0].title.lower(), (word, [i.title for i in got])
all_gone = system("vpn ", missing={"nmcli"})
assert len(all_gone) == 1 and "nmcli" in all_gone[0].subtitle and "Health" in all_gone[0].subtitle and "not available" in all_gone[0].title.lower(), (all_gone[0].title, all_gone[0].subtitle)
assert argv_of(all_gone[0]) == [], "the explanation does nothing when chosen"
nothing_matches = system("power zzz-nothing")
assert len(nothing_matches) == 1 and "zzz-nothing" in nothing_matches[0].title and argv_of(nothing_matches[0]) == []
assert system("doctor ") and system("doctor ")[0].title == "Open Health", "doctor needs nothing, so it is never empty"

# querying never reads anything but tool names, whatever the namespace and whatever is typed
for word in SYSTEM:
    qf = QuietFacts()
    lc.collect(word + " ", lc.Context(apps=ctx.apps, facts=qf, launch_app=lambda i: None))
    assert not spawned
    assert set(qf.asked) <= {"grim", "slurp", "wl-copy", "satty", "wf-recorder", "pactl", "pavucontrol", "nmcli", "nm-connection-editor", "hyprsunset", "wofi", "powerprofilesctl"}, qf.asked

# the typed text is data: it never reaches an argv or a shell
for hostile in ("; touch /tmp/pwned", "$(touch /tmp/pwned)", "`touch /tmp/pwned`", "'; rm -rf ~ #", "--page ../../etc", "\n&& reboot", "audio\0x"):
    for word in SYSTEM:
        for i in system(f"{word} {hostile}"):
            ran = argv_of(i)
            assert all(hostile not in part and "touch" not in part for cmd in ran for part in cmd), (word, hostile, ran)
            assert not any(cmd[0] == "sh" for cmd in ran), (word, hostile, ran)
assert not Path("/tmp/pwned").exists()

# nothing here can reach restart or poweroff directly
every = [argv for w in SYSTEM for i in system(w + " ") for argv in argv_of(i)]
flat = [part for cmd in every for part in cmd]
assert not any(w in flat for w in ("reboot", "poweroff", "shutdown", "systemctl", "hyprshutdown")), flat
assert str(lc.SCRIPTS / "power-menu.sh") in flat and not any(c[:2] == (str(lc.SCRIPTS / "power-menu.sh"), "reboot") for c in every)

# the clipboard stays opt-in: no system word and no plain search shows it
assert "clipboard" not in {i.kind for w in SYSTEM for i in system(w + " ")} and "clipboard" not in kinds("audio") and "clipboard" not in kinds("sample")
assert "clipboard" in kinds("clip ")

# rapid switching: only the newest word answers, and file search is only for text that is not a command word
for first, second in zip(SYSTEM, SYSTEM[1:] + SYSTEM[:1]):
    a, b = {i.kind for i in system(first + " ")}, {i.kind for i in system(second + " ")}
    assert a == {first} and b == {second}
assert not lc.wants_file_search("audio ") and not lc.wants_file_search("capture area") and not lc.wants_file_search("2+2")
assert lc.wants_file_search("audio") and lc.wants_file_search("report") and not lc.wants_file_search("ab")

# the same entries through the real Facts, with only fake tools on PATH
bin_real = Path(tempfile.mkdtemp())
for tool in ("pactl", "grim", "slurp", "wl-copy"):
    (bin_real / tool).write_text("#!/bin/sh\n")
    (bin_real / tool).chmod(0o755)
saved_path = os.environ["PATH"]
os.environ["PATH"] = str(bin_real)
try:
    live_titles = [i.title for i in lc.collect("audio ", lc.Context(apps=[], facts=lc.Facts(), launch_app=lambda i: None))]
    assert live_titles == ["Open Audio settings", "Mute or unmute the microphone"], live_titles          # pavucontrol is not there
    live_capture = [i.title for i in lc.collect("capture ", lc.Context(apps=[], facts=lc.Facts(), launch_app=lambda i: None))]
    assert live_capture == ["Screenshot an area", "Screenshot the whole screen"], live_capture
finally:
    os.environ["PATH"] = saved_path
lc.spawn, lc.shell = real_spawn, real_shell

print("launcher checks passed")
