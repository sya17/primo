#!/usr/bin/env python3
"""A plain wallpaper window used as a clean backdrop while taking screenshots (scripts/take-screenshots.sh).

Usage: shot-backdrop.py IMAGE      shows IMAGE, scaled to cover the window, with no decorations. Close it with Esc."""
import sys
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, Gtk


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.primo.Backdrop", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self, decorated=False, default_width=1920, default_height=1044, title="Backdrop")
        pic = Gtk.Picture.new_for_filename(sys.argv[1])
        pic.set_content_fit(Gtk.ContentFit.COVER)
        win.set_child(pic)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a: win.close() if kv == Gdk.KEY_Escape else None)
        win.add_controller(keys)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run([sys.argv[0]]) if len(sys.argv) > 1 else 2)
