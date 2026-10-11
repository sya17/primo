"""The small GTK side of the interface policy (ui_core): root classes on a window, the toolkit's own animation setting, and a binding that
follows that setting while the window is open. Not a service and not an animation engine: it only sets classes (`primo-reduce-motion`,
`primo-opaque`) that the shared GTK4 stylesheet answers, and tells a page how long its own transition should last. It never changes a global
GTK or compositor setting and never moves a whole window."""
import weakref
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

import ui_core  # noqa: E402

ANIMATIONS = "gtk-enable-animations"


def apply_policy(window, policy):
    """Put the policy on the window as classes; the shared stylesheet turns them into solid surfaces and no transitions."""
    for name, wanted in (("primo-reduce-motion", not policy.animate), ("primo-opaque", policy.opaque)):
        (window.add_css_class if wanted else window.remove_css_class)(name)


def page_transition_ms(policy):
    return ui_core.transition_ms(policy)


def set_page_transition(stack, policy):
    """A stack's own page transition for this policy: a 180 ms crossfade, or none at all when custom motion is off."""
    ms = page_transition_ms(policy)
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE if ms else Gtk.StackTransitionType.NONE)
    stack.set_transition_duration(ms)


def _settings(display=None):
    return Gtk.Settings.get_for_display(display or Gdk.Display.get_default())


def system_animations(display=None):
    """Does the toolkit allow animation? When that cannot be read, no: the fallback is the quiet one."""
    try:
        value = _settings(display).get_property(ANIMATIONS)
    except Exception:
        return False
    return value if isinstance(value, bool) else False


class PolicyBinding:
    """Resolves the policy for one window when it opens and again when the toolkit's animation setting changes, until `close()`.
    Holds the window weakly and disconnects its one signal handler, so a closed window is never kept alive or touched."""

    def __init__(self, window, load=ui_core.load_preferences, display=None, on_change=None):
        self.window, self.load, self.display, self.on_change = weakref.ref(window), load, display, on_change
        self.policy = None
        self.prefs = None
        self.handler = None
        try:
            self.settings = _settings(display)
            self.handler = self.settings.connect(f"notify::{ANIMATIONS}", self._changed)
        except Exception:
            self.settings = None          # no setting to follow: the policy is resolved once, with the quiet fallback
        self.refresh()

    def refresh(self, prefs=None):
        window = self.window()
        if window is None:
            return None
        self.prefs = prefs or self.load()
        self.policy = ui_core.resolve_policy(self.prefs, system_animations(self.display))
        apply_policy(window, self.policy)
        if self.on_change:
            self.on_change(self.policy)
        return self.policy

    def _changed(self, *_):
        self.refresh()

    def close(self):
        if self.settings is not None and self.handler is not None:
            self.settings.disconnect(self.handler)
        self.handler = None
        self.on_change = None


# Used only when the generated stylesheet has no shared roles (never rendered, or deleted): the pilots stay readable with the toolkit's own
# named colours. The generated roles are at a higher priority and replace all of it.
FALLBACK_CSS = """
.primo-popup { background-color: @window_bg_color; color: @window_fg_color; border: 1px solid alpha(@accent_bg_color, 0.55); border-radius: 12px; }
.primo-surface { background-color: @card_bg_color; border-radius: 12px; }
.primo-control { border-radius: 9px; }
.primo-control:selected { background-color: alpha(@accent_bg_color, 0.30); }
.primo-active { outline: 2px solid @accent_bg_color; outline-offset: -2px; }
"""


class Styles:
    """The three style providers of a pilot, created once for the process: the fallback (lowest), the generated user stylesheet (the shared
    roles; re-read on each open so a theme switch shows), and the pilot's own layout rules (highest, holding no shared value)."""

    def __init__(self, layout_css, display=None):
        display = display or Gdk.Display.get_default()
        self.fallback, self.user, self.layout = Gtk.CssProvider(), Gtk.CssProvider(), Gtk.CssProvider()
        self.fallback.load_from_string(FALLBACK_CSS)
        self.layout.load_from_string(layout_css)
        for provider, priority in ((self.fallback, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION), (self.user, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1),
                                   (self.layout, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)):
            Gtk.StyleContext.add_provider_for_display(display, provider, priority)

    def reload_user(self, path):
        path = Path(path)
        if path.exists():
            self.user.load_from_path(str(path))
        else:
            self.user.load_from_string("")
