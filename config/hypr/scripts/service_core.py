"""What a resident service checks before it starts: a session bus to own its name on, and a display to draw on.

Without a bus the process would run and nobody could reach it; without a display GTK used to end with status 0 and no message, which a
supervisor reads as "finished on purpose". Either case now logs one line and exits with 69 (EX_UNAVAILABLE), which the systemd unit
treats as "do not retry" (RestartPreventExitStatus=69) and which shows up as `failed` instead of looking healthy."""
import sys

EX_UNAVAILABLE = 69


def missing_session():
    """Why this process cannot work in this session, or None when it can."""
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gio, GLib, Gtk
    try:
        Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as e:
        return f"no session bus ({e.message})"
    Gtk.init_check()   # in GTK 4 this reports success without a display; the default display is what tells
    if Gdk.Display.get_default() is None:
        return "no display"
    return None


def require_session(log):
    """Exit with 69 and one logged line when `missing_session` says so."""
    why = missing_session()
    if why:
        log.error("cannot start: %s", why)
        sys.exit(EX_UNAVAILABLE)
