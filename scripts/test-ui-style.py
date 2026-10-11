#!/usr/bin/env python3
"""Checks for ui_style, the GTK adapter of the interface policy. The policy arithmetic needs no display; the window checks do (skipped
without one) and never show a window. Only this process's own Gtk.Settings object is changed: no global setting is written."""
import gc
import os
import sys
import weakref
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "config" / "hypr" / "scripts"))
import ui_core as ui

# ---- the transition length follows the policy (no display needed)
assert ui.transition_ms(ui.UiPolicy(animate=True, opaque=False)) == 180 and ui.transition_ms(ui.UiPolicy(animate=False, opaque=True)) == 0
print("ui style policy checks passed")

if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
    print("skip: no display (window checks)")
    sys.exit(0)
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
if not Gtk.init_check():
    print("skip: no display (window checks)")
    sys.exit(0)
import ui_style as style

assert style.page_transition_ms(ui.UiPolicy(True, False)) == 180 and style.page_transition_ms(ui.UiPolicy(False, False)) == 0
Adw.init()
win = Gtk.Window()
classes = lambda w: set(w.get_css_classes())

# classes follow the policy, both ways
style.apply_policy(win, ui.UiPolicy(animate=False, opaque=True))
assert {"primo-reduce-motion", "primo-opaque"} <= classes(win)
style.apply_policy(win, ui.UiPolicy(animate=True, opaque=False))
assert not ({"primo-reduce-motion", "primo-opaque"} & classes(win))
style.apply_policy(win, ui.UiPolicy(animate=False, opaque=False))
assert "primo-reduce-motion" in classes(win) and "primo-opaque" not in classes(win), "the two classes are independent"

# the toolkit setting wins, and the binding follows it
settings = Gtk.Settings.get_default()
original = settings.get_property("gtk-enable-animations")
try:
    prefs = {"value": ui.UiPreferences()}
    settings.set_property("gtk-enable-animations", True)
    win = Gtk.Window()
    binding = style.PolicyBinding(win, load=lambda: prefs["value"])
    assert binding.policy == ui.UiPolicy(True, False) and "primo-reduce-motion" not in classes(win)
    settings.set_property("gtk-enable-animations", False)                    # the system turns animation off while the window is open
    assert binding.policy.animate is False and "primo-reduce-motion" in classes(win), "an open window follows the system"
    settings.set_property("gtk-enable-animations", True)
    prefs["value"] = ui.UiPreferences(reduce_motion=True, reduce_transparency=True)
    assert binding.refresh().animate is False and {"primo-reduce-motion", "primo-opaque"} <= classes(win)
    assert style.system_animations() is True
    settings.set_property("gtk-enable-animations", False)
    assert binding.refresh(ui.UiPreferences()).animate is False, "the app preference cannot switch animation on again"

    # after close() the window is no longer touched, and a closed window is not kept alive by the setting
    binding.close()
    before = classes(win)
    settings.set_property("gtk-enable-animations", True)
    assert classes(win) == before, "a closed binding ignores the system setting"
    binding.close()                                                           # closing twice is harmless
    ref = weakref.ref(win)
    del win, binding
    gc.collect()
    assert ref() is None, "the binding must not keep the window alive"

    # repeated open and close leaves no handler behind
    for _ in range(25):
        w = Gtk.Window()
        b = style.PolicyBinding(w, load=lambda: ui.UiPreferences())
        b.close()
        assert b.handler is None
    # a stack gets a crossfade, or no transition at all; the binding tells its owner when the policy changes
    stack = Gtk.Stack()
    style.set_page_transition(stack, ui.UiPolicy(True, False))
    assert stack.get_transition_type() == Gtk.StackTransitionType.CROSSFADE and stack.get_transition_duration() == 180
    style.set_page_transition(stack, ui.UiPolicy(False, False))
    assert stack.get_transition_type() == Gtk.StackTransitionType.NONE and stack.get_transition_duration() == 0
    seen = []
    settings.set_property("gtk-enable-animations", True)
    w = Gtk.Window()
    b = style.PolicyBinding(w, load=lambda: ui.UiPreferences(), on_change=seen.append)
    assert seen == [ui.UiPolicy(True, False)], "the owner hears the first policy at once"
    settings.set_property("gtk-enable-animations", False)
    assert seen[-1] == ui.UiPolicy(False, False) and len(seen) == 2
    b.close()
    settings.set_property("gtk-enable-animations", True)
    assert len(seen) == 2, "a closed binding tells nobody"
    # a setting that cannot be read means the quiet fallback
    assert style.system_animations(display=object()) is False
finally:
    settings.set_property("gtk-enable-animations", original)
print("ui style window checks passed")
