#!/usr/bin/env python3
"""Clipboard history picker (cliphist) in the Primo style.

Type to filter, Up/Down to move, Enter to copy the entry, Delete to remove it, Esc to close.
Images show a thumbnail. Needs: cliphist, wl-clipboard, python-gobject, libadwaita.
"""
import re
import subprocess
import sys
import warnings

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

MAX_ENTRIES = 120
MAX_THUMBS = 14
IMAGE_RE = re.compile(r"^\[\[ binary data .*(png|jpe?g|webp|gif|bmp).* \]\]$")

CSS = """
window.primo-clip { background-color: @window_bg_color; }
.clip-search { margin: 14px 14px 8px 14px; }
.clip-row { padding: 9px 12px; border-radius: 10px; margin: 1px 8px; }
.clip-row:selected { background-color: alpha(@accent_bg_color, 0.3); }
.clip-kind { opacity: 0.6; min-width: 22px; }
.clip-text { font-size: 13px; }
.clip-thumb { border-radius: 8px; }
.clip-hint { opacity: 0.55; font-size: 11px; margin: 8px 14px 10px 14px; }
"""


def run(*cmd, data=None):
    return subprocess.run(cmd, input=data, capture_output=True)


def load_entries():
    out = run("cliphist", "list").stdout.decode("utf-8", "replace")
    entries = []
    for line in out.splitlines()[:MAX_ENTRIES]:
        ident, _, preview = line.partition("\t")
        if ident:
            entries.append({"line": line, "id": ident, "text": preview})
    return entries


class Picker(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, default_width=620, default_height=560, title="Clipboard")
        self.add_css_class("primo-clip")
        self.set_decorated(False)
        self.entries = load_entries()
        self.thumbs = 0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.search = Gtk.SearchEntry(placeholder_text="Search clipboard history", css_classes=["clip-search"])
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        root.append(self.search)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, activate_on_single_click=True)
        self.listbox.set_filter_func(self.filter_row)
        self.listbox.connect("row-activated", lambda _lb, row: self.copy(row.entry))
        for e in self.entries:
            self.listbox.append(self.make_row(e))
        scroller = Gtk.ScrolledWindow(vexpand=True, child=self.listbox, hscrollbar_policy=Gtk.PolicyType.NEVER)
        root.append(scroller)

        footer = Gtk.Box()
        footer.append(Gtk.Label(label="↵ Copy     ⌦ Delete     Esc Close", xalign=0, hexpand=True, css_classes=["clip-hint"]))
        wipe = Gtk.Button(label="Clear all", css_classes=["flat", "destructive-action"], margin_end=10, margin_bottom=6)
        wipe.connect("clicked", self.on_wipe)
        footer.append(wipe)
        root.append(footer)
        self.set_content(root)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)
        self.select_first()
        self.search.grab_focus()

    # ---- rows
    def make_row(self, e):
        text = e["text"]
        is_image = bool(IMAGE_RE.match(text))
        row = Gtk.ListBoxRow(css_classes=["clip-row"])
        row.entry = e
        row.is_image = is_image
        box = Gtk.Box(spacing=12)
        glyph = "" if is_image else ("" if re.match(r"^https?://", text) else "")
        box.append(Gtk.Label(label=glyph, css_classes=["clip-kind"]))
        if is_image and self.thumbs < MAX_THUMBS:
            self.thumbs += 1
            GLib.idle_add(self.load_thumb, row, box)
            label = Gtk.Label(label="Image", xalign=0, hexpand=True, css_classes=["clip-text"])
        else:
            one_line = " ".join(text.split())
            label = Gtk.Label(label=one_line, xalign=0, hexpand=True, ellipsize=3, max_width_chars=70,
                              css_classes=["clip-text"], tooltip_text=text[:600])
        box.append(label)
        row.set_child(box)
        return row

    def load_thumb(self, row, box):
        data = run("cliphist", "decode", row.entry["id"]).stdout
        try:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pix = loader.get_pixbuf().scale_simple(72, 48, GdkPixbuf.InterpType.BILINEAR)
            pic = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pix))
            pic.set_size_request(72, 48)
            pic.set_overflow(Gtk.Overflow.HIDDEN)
            pic.add_css_class("clip-thumb")
            box.append(pic)
        except (GLib.Error, AttributeError):
            pass
        return False

    def filter_row(self, row):
        q = self.search.get_text().strip().lower()
        return not q or q in row.entry["text"].lower()

    # ---- actions
    def select_first(self):
        for row in self.rows():
            if row.get_child_visible():
                self.listbox.select_row(row)
                return

    def rows(self):
        child = self.listbox.get_first_child()
        while child:
            yield child
            child = child.get_next_sibling()

    def visible_rows(self):
        return [r for r in self.rows() if self.filter_row(r)]

    def move(self, delta):
        rows = self.visible_rows()
        if not rows:
            return
        cur = self.listbox.get_selected_row()
        idx = rows.index(cur) if cur in rows else -1
        row = rows[max(0, min(len(rows) - 1, idx + delta))]
        self.listbox.select_row(row)
        row.grab_focus()
        self.search.grab_focus()

    def copy(self, entry):
        decoded = run("cliphist", "decode", entry["id"]).stdout
        subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, start_new_session=True).communicate(decoded)
        self.close()

    def delete_selected(self):
        row = self.listbox.get_selected_row()
        if row is None:
            return
        run("cliphist", "delete", data=(row.entry["line"] + "\n").encode())
        rows = self.visible_rows()
        idx = rows.index(row) if row in rows else 0
        self.listbox.remove(row)
        rows = self.visible_rows()
        if rows:
            self.listbox.select_row(rows[min(idx, len(rows) - 1)])

    def on_wipe(self, *_):
        run("cliphist", "wipe")
        self.close()

    def on_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_Tab):
            self.move(1)
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            self.move(-1)
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            row = self.listbox.get_selected_row()
            if row is not None:
                self.copy(row.entry)
        elif keyval == Gdk.KEY_Delete:
            self.delete_selected()
        else:
            return False
        return True


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="dev.primo.Clipboard", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        Picker(self).present()


if __name__ == "__main__":
    sys.exit(App().run([sys.argv[0]]))
