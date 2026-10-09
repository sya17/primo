#!/usr/bin/env python3
"""Clipboard history picker (cliphist) in the Primo style.

Type to filter, Up/Down to move, Enter to copy the entry, Delete to remove it, Esc to close. Images show a small preview.
Needs: cliphist, wl-clipboard, python-gobject, libadwaita. The history is read, copied and previewed by background workers
(clipboard_core, settings_jobs, thumbnail_core), so the window answers keys while they run.
"""
import re
import sys
import warnings
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clipboard_core as cp  # noqa: E402
import settings_jobs as sj  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)

CSS = """
window.primo-clip { background-color: @window_bg_color; }
.clip-search { margin: 14px 14px 8px 14px; }
.clip-row { padding: 9px 12px; border-radius: 10px; margin: 1px 8px; }
.clip-row:selected { background-color: alpha(@accent_bg_color, 0.3); }
.clip-kind { opacity: 0.6; min-width: 22px; }
.clip-text { font-size: 13px; }
.clip-thumb { border-radius: 8px; }
.clip-status { opacity: 0.7; margin: 6px 16px; }
.clip-hint { opacity: 0.55; font-size: 11px; margin: 8px 14px 10px 14px; }
"""


class Picker(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, default_width=620, default_height=560, title="Clipboard")
        self.add_css_class("primo-clip")
        self.set_decorated(False)
        self.entries_by_id = {}
        self.thumbs = 0
        post = lambda fn, *args: GLib.idle_add(lambda: (fn(*args), False)[1])
        self.jobs = sj.JobOwner(post, workers=2, pending_limit=16)       # the history and the previews: stopped when the window closes
        self.ops = sj.Operations(post, app.hold, app.release)            # copy, delete, clear: finish even if the window closes meanwhile
        self.busy = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.search = Gtk.SearchEntry(placeholder_text="Search clipboard history", css_classes=["clip-search"])
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        root.append(self.search)

        status_row = Gtk.Box(spacing=8)
        self.status = Gtk.Label(label="Loading the history…", xalign=0, hexpand=True, wrap=True, css_classes=["clip-status"])
        self.retry = Gtk.Button(label="Try again", valign=Gtk.Align.CENTER, margin_end=14, visible=False)
        self.retry.connect("clicked", lambda *_: self.load_history())
        status_row.append(self.status)
        status_row.append(self.retry)
        root.append(status_row)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, activate_on_single_click=True)
        self.listbox.set_filter_func(self.filter_row)
        self.listbox.connect("row-activated", lambda _lb, row: self.copy(row.entry))
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
        self.connect("close-request", self.on_close_request)
        self.search.grab_focus()
        self.load_history()

    # ---- the history
    def set_status(self, text, retry=False):
        self.status.set_label(text)
        self.status.set_visible(bool(text))
        self.retry.set_visible(retry)

    def load_history(self):
        self.set_status("Loading the history…")
        self.jobs.submit("clip/list", lambda cancel: cp.list_entries(cancel=cancel), self.on_entries)

    def on_entries(self, entries):
        if isinstance(entries, Exception):
            self.set_status(f"Could not read the history: {entries}", retry=True)
            return
        if entries.state == "missing":
            self.set_status("cliphist is not installed. Install it with: sudo pacman -S cliphist wl-clipboard")
            return
        if entries.state != "ok":
            self.set_status("The history took too long to read." if entries.state == "timeout" else "Could not read the history.", retry=True)
            return
        for row in list(self.rows()):
            self.listbox.remove(row)
        self.entries_by_id = {}
        for e in entries:
            self.entries_by_id[e["id"]] = e
            self.listbox.append(self.make_row(e))
        if not entries:
            self.set_status("Nothing copied yet. Copy something and it appears here.")
        else:
            self.set_status(f"Showing the newest {cp.MAX_ENTRIES} entries." if entries.truncated else "")
        self.select_first()

    # ---- rows
    def make_row(self, e):
        text = e["text"]
        image = cp.is_image(text)
        row = Gtk.ListBoxRow(css_classes=["clip-row"])
        row.entry = e
        row.is_image = image
        box = Gtk.Box(spacing=12)
        glyph = "" if image else ("" if re.match(r"^https?://", text) else "")
        box.append(Gtk.Label(label=glyph, css_classes=["clip-kind"]))
        if image:
            label = Gtk.Label(label="Image", xalign=0, hexpand=True, css_classes=["clip-text"])
            if self.thumbs < cp.MAX_THUMBS:
                self.thumbs += 1
                entry_id = e["id"]
                self.jobs.submit(f"clip/thumb:{entry_id}", lambda cancel, i=entry_id: cp.preview(i, cancel),
                                 lambda result, r=row, i=entry_id, b=box, lb=label: self.apply_thumb(r, i, result, b, lb))
        else:
            one_line = " ".join(text.split())
            label = Gtk.Label(label=one_line, xalign=0, hexpand=True, ellipsize=3, max_width_chars=70,
                              css_classes=["clip-text"], tooltip_text=text[:600])
        box.append(label)
        row.set_child(box)
        return row

    def apply_thumb(self, row, entry_id, result, box=None, label=None):
        """A preview arrived. A row that was deleted, replaced by a reload or belongs to another entry ignores it."""
        if row.get_parent() is None or getattr(row, "entry", {}).get("id") != entry_id:
            return
        box = box or row.get_child()
        if isinstance(result, Exception) or result.status == "cancelled":
            return
        if result.status != "ok":
            if label is not None:
                label.set_tooltip_text(f"No preview: {result.reason}")
            return
        pic = Gtk.Picture.new_for_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(result.png)))
        pic.set_size_request(*cp.tc.CLIPBOARD_OUTPUT)
        pic.set_overflow(Gtk.Overflow.HIDDEN)
        pic.add_css_class("clip-thumb")
        box.append(pic)

    def filter_row(self, row):
        q = self.search.get_text().strip().lower()
        return not q or q in row.entry["text"].lower()

    # ---- actions
    def select_first(self):
        for row in self.rows():
            if row.get_child_visible() or self.filter_row(row):
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
        """Copy in the background; the picker closes only when it worked."""
        if self.busy:
            return
        self.busy = True
        self.set_status("Copying…")

        def done(outcome):
            self.busy = False
            if isinstance(outcome, Exception) or not outcome:
                self.set_status("Could not copy: " + (outcome.reason if not isinstance(outcome, Exception) else str(outcome)))
            else:
                self.close()

        if not self.ops.run("clip/copy", lambda budget: cp.copy_entry(entry["id"], cancel=budget.cancel), done, deadline=cp.COPY_DEADLINE):
            self.busy = False

    def delete_selected(self):
        row = self.listbox.get_selected_row()
        if row is None or self.busy:
            return
        self.busy = True
        line = row.entry["line"]

        def done(outcome):
            self.busy = False
            if isinstance(outcome, Exception) or not outcome:
                self.set_status("Could not delete: " + (outcome.reason if not isinstance(outcome, Exception) else str(outcome)))
                return
            if row.get_parent() is None:
                return
            rows = self.visible_rows()
            idx = rows.index(row) if row in rows else 0
            self.entries_by_id.pop(row.entry["id"], None)
            self.listbox.remove(row)
            rows = self.visible_rows()
            if rows:
                self.listbox.select_row(rows[min(idx, len(rows) - 1)])
            self.set_status("")

        if not self.ops.run("clip/delete", lambda budget: cp.delete_entry(line, run=budget), done):
            self.busy = False

    def on_wipe(self, *_):
        dialog = Adw.AlertDialog(heading="Clear the clipboard history?", body="Every entry is deleted. This cannot be undone.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("wipe", "Clear all")
        dialog.set_response_appearance("wipe", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: self.wipe_answered(response))
        dialog.present(self)

    def wipe_answered(self, response):
        if response != "wipe" or self.busy:
            return                                          # Cancel: nothing runs
        self.busy = True
        self.set_status("Clearing…")

        def done(outcome):
            self.busy = False
            if isinstance(outcome, Exception) or not outcome:
                self.set_status("Could not clear the history: " + (outcome.reason if not isinstance(outcome, Exception) else str(outcome)))
            else:
                self.close()

        if not self.ops.run("clip/wipe", lambda budget: cp.wipe(run=budget), done):
            self.busy = False

    def on_close_request(self, *_):
        self.jobs.close()                                   # previews and the history stop, their children with them
        self.ops.close()                                    # a change already started finishes; nothing is shown for it
        return False

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
