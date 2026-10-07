#!/usr/bin/env python3
"""Checks for the launcher's sources: calculator, matching, command words, privacy of the clipboard source, and a failing source.

No GTK and no live system: Facts is replaced by sample data and nothing is launched.
"""
import os
import sys
import tempfile

work = tempfile.mkdtemp()
os.environ["XDG_STATE_HOME"] = os.path.join(work, "state")
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

# a failing source is skipped, the rest still answer
class Broken(lc.Provider):
    id, label, order, limit = "broken", "BROKEN", 1, 3
    def query(self, q, ctx, args): raise RuntimeError("boom")
assert titles("fire", providers=[Broken()] + lc.PROVIDERS)[0] == "Firefox"

# empty query: only apps you opened before (history), nothing else
assert lc.collect("", ctx) == []
ctx.history = {"firefox.desktop": 3}
assert titles("") == ["Firefox"]

# history is stored and read back
lc.bump_history("a.desktop"); lc.bump_history("a.desktop")
assert lc.load_history()["a.desktop"] == 2
print("launcher checks passed")
