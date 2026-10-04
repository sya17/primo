#!/usr/bin/env python3
"""Modes: start one with `modes.py start work`, stop with `modes.py end`.

    modes.py start ID [FOLDER]   set the machine up (asks for a folder when the mode wants one and none is given)
    modes.py end                 put back power, do-not-disturb, VPN and the focus session
    modes.py status              what is running, one line
    modes.py list                the modes you have
    modes.py menu                choose a mode to start (or end the running one)
"""
import subprocess
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modes_core as mc  # noqa: E402


def cli():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "menu"
    if cmd == "list":
        for m in mc.load_modes():
            print(f"{m['id']:12} {m['name']}")
        return 0
    if cmd == "status":
        st = mc.current()
        print(f"{st['name']} · {mc.elapsed(st) // 60} min" if st else "No mode running")
        return 0
    if cmd == "end":
        return 0 if mc.end() else 1
    if cmd == "start" and len(sys.argv) > 2:
        mode = mc.get_mode(sys.argv[2])
        if not mode:
            print("no such mode:", sys.argv[2], file=sys.stderr)
            return 2
        directory = sys.argv[3] if len(sys.argv) > 3 else None
        if mode.get("ask_dir") and not directory:
            return gui("pick", mode)
        mc.start(mode, directory)
        return 0
    return gui("menu")


def gui(kind, mode=None):
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    user_css = Path.home() / ".config" / "gtk-4.0" / "gtk.css"

    class App(Adw.Application):
        def __init__(self):
            super().__init__(application_id="dev.primo.Modes", flags=Gio.ApplicationFlags.NON_UNIQUE)

        def do_activate(self):
            if user_css.exists():
                css = Gtk.CssProvider()
                css.load_from_path(str(user_css))
                Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            win = Adw.Window(application=self, title="Modes", default_width=440, default_height=520)
            win.add_css_class("primo-modes")
            view = Adw.ToolbarView()
            view.add_top_bar(Adw.HeaderBar())
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=6, margin_bottom=16, margin_start=16, margin_end=16)
            lst = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
            scroll = Gtk.ScrolledWindow(child=lst, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)

            def row(title, sub, icon, fn):
                r = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(sub), activatable=True)
                r.add_prefix(Gtk.Image.new_from_icon_name(icon))
                r.connect("activated", lambda *_: (fn(), win.close()))
                lst.append(r)

            if kind == "pick":
                box.append(Gtk.Label(label=f"Start {mode['name']}: which folder?", xalign=0, css_classes=["title-4"]))
                for d in mc.project_dirs():
                    row(Path(d).name, d.replace(str(Path.home()), "~"), "folder-symbolic", lambda d=d: mc.start(mode, d))
                row("Without a folder", "Start the mode as it is", "go-next-symbolic", lambda: mc.start(mode, None))

                def other(*_):
                    dlg = Gtk.FileDialog(title="Choose a folder")

                    def done(d, res):
                        try:
                            f = d.select_folder_finish(res)
                        except GLib.Error:
                            return
                        if f:
                            mc.start(mode, f.get_path())
                            win.close()

                    dlg.select_folder(win, None, done)

                btn = Gtk.Button(label="Another folder…", css_classes=["flat"], halign=Gtk.Align.START)
                btn.connect("clicked", other)
                box.append(scroll)
                box.append(btn)
            else:
                st = mc.current()
                box.append(Gtk.Label(label="Modes", xalign=0, css_classes=["title-4"]))
                if st:
                    row(f"End {st['name']}", f"Running for {mc.elapsed(st) // 60} min. Puts settings back; apps stay open.", "process-stop-symbolic", mc.end)
                for m in mc.load_modes():
                    sub = ", ".join(a["cmd"].split()[0] for a in m.get("apps", [])[:3]) or "Settings only"
                    if m.get("ask_dir"):
                        row(m["name"], sub + " · asks for a folder", "go-next-symbolic",
                            lambda m=m: subprocess.Popen([sys.executable, __file__, "start", m["id"]]))
                    else:
                        row(m["name"], sub, "go-next-symbolic", lambda m=m: mc.start(m, None))
                box.append(scroll)
            view.set_content(box)
            win.set_content(view)
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", lambda _c, kv, *_a: (win.close(), True)[1] if kv == 65307 else False)
            win.add_controller(keys)
            win.present()

    return App().run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(cli())
