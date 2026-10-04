#!/usr/bin/env python3
"""Primo Settings: Appearance, Wallpaper and Displays in one libadwaita window.

Usage: primo-settings.py [--page appearance|wallpaper|displays|more]

Everything here drives the same tools you can run by hand:
  themes     -> scripts/theme-switch  (hypr-theme)
  wallpaper  -> scripts/theme-switch --wallpaper PATH | reset
  displays   -> hyprctl eval 'hl.monitor{...}', persisted in ~/.config/hypr/displays.lua
"""
import json
import os
import warnings
import re
import shutil
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Graphene, Gsk, Gtk  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning)  # Gdk.Texture.new_for_pixbuf is fine for thumbnails
REPO = Path(__file__).resolve().parents[3]
THEME_SWITCH = REPO / "scripts" / "theme-switch"
THEMES_DIR = REPO / "themes"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "hyprland-dotfiles"
HYPR_DIR = Path.home() / ".config" / "hypr"
DISPLAYS_LUA = HYPR_DIR / "displays.lua"
USER_CSS = Path.home() / ".config" / "gtk-4.0" / "gtk.css"

PAGES = [
    ("appearance", "Appearance", "preferences-desktop-theme-symbolic"),
    ("wallpaper", "Wallpaper", "preferences-desktop-wallpaper-symbolic"),
    ("displays", "Displays", "preferences-desktop-display-symbolic"),
    ("power", "Power", "battery-symbolic"),
    ("bluetooth", "Bluetooth", "bluetooth-symbolic"),
    ("more", "More", "preferences-other-symbolic"),
]

APP_CSS = """
.wp-preview { border-radius: 14px; }
.wp-thumb { padding: 6px; border-radius: 12px; }
.wp-thumb.active { outline: 2px solid @accent_bg_color; outline-offset: -2px; }
.theme-card { padding: 10px; border-radius: 14px; }
.theme-card.active { outline: 2px solid @accent_bg_color; outline-offset: -2px; }
.theme-name { font-weight: 700; }
.dim { opacity: 0.65; }
"""


# --------------------------------------------------------------------------- helpers
def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def spawn(*cmd):
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def read_conf(path):
    data = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = re.split(r"\s#", v)[0].strip()
    return data


def current_theme():
    try:
        return (STATE_DIR / "current").read_text().strip()
    except OSError:
        return ""


def themes():
    out = []
    for conf in sorted(THEMES_DIR.glob("*/theme.conf")):
        d = read_conf(conf)
        d["_id"] = conf.parent.name
        out.append(d)
    return out


def rgb(hexstr):
    return tuple(int(hexstr[i:i + 2], 16) / 255 for i in (0, 2, 4))


VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}


def load_still(path, w, h):
    """A pixbuf for a picture, GIF or video (first frame via ffmpegthumbnailer); None if it cannot be read."""
    path = str(path)
    try:
        if Path(path).suffix.lower() in VIDEO_EXTS:
            out = Path(GLib.get_user_cache_dir()) / "primo-video-thumb.png"
            r = subprocess.run(["ffmpegthumbnailer", "-i", path, "-o", str(out), "-s", "0", "-q", "6"],
                               capture_output=True, timeout=15)
            if r.returncode != 0:
                return None
            path = str(out)
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, True)
    except (GLib.Error, OSError, subprocess.SubprocessError):
        return None


class Swatch(Gtk.Widget):
    """Mini window preview painted with the theme's colours (GTK snapshot, no cairo needed)."""
    __gtype_name__ = "PrimoSwatch"

    def __init__(self, colors):
        super().__init__()
        self.colors = colors
        self.set_size_request(148, 88)

    def _rect(self, snap, x, y, w, h, radius, hexcolor, alpha=1.0):
        rgba = Gdk.RGBA()
        rgba.parse("#" + hexcolor)
        rgba.alpha = alpha
        box = Graphene.Rect().init(x, y, w, h)
        rounded = Gsk.RoundedRect()
        rounded.init_from_rect(box, radius)
        snap.push_rounded_clip(rounded)
        snap.append_color(rgba, box)
        snap.pop()

    def do_snapshot(self, snap):
        c, w, h = self.colors, self.get_width(), self.get_height()
        self._rect(snap, 0, 0, w, h, 10, c["base"])
        self._rect(snap, 0, 0, w, 14, 10, c["mantle"])
        self._rect(snap, 8, 22, 36, h - 30, 6, c["surface0"])
        self._rect(snap, 12, 28, 28, 7, 3.5, c["accent"])
        for i, width in enumerate((70, 52, 62)):
            self._rect(snap, 54, 28 + i * 13, width, 6, 3, c["text"], 0.55)
        self._rect(snap, w - 40, h - 22, 30, 12, 6, c["accent2"])


def hypr_eval(lua):
    return sh("hyprctl", "eval", lua)


# --------------------------------------------------------------------------- application
class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app, page):
        super().__init__(application=app, default_width=980, default_height=660, title="Settings")
        self.add_css_class("primo-settings")
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)

        self.split = Adw.NavigationSplitView()
        self.toasts.set_child(self.split)

        # Sidebar
        self.sidebar_list = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.sidebar_list.connect("row-selected", self.on_row_selected)
        for pid, title, icon in PAGES:
            row = Gtk.ListBoxRow()
            row.page_id = pid
            box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=6, margin_end=6)
            box.append(Gtk.Image.new_from_icon_name(icon))
            box.append(Gtk.Label(label=title, xalign=0))
            row.set_child(box)
            self.sidebar_list.append(row)
        side_view = Adw.ToolbarView()
        side_view.add_top_bar(Adw.HeaderBar(show_end_title_buttons=False))
        side_view.set_content(Gtk.ScrolledWindow(child=self.sidebar_list, vexpand=True))
        self.split.set_sidebar(Adw.NavigationPage(title="Settings", child=side_view))

        # Content
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=180)
        self.builders = {
            "appearance": self.build_appearance,
            "wallpaper": self.build_wallpaper,
            "displays": self.build_displays,
            "power": self.build_power,
            "bluetooth": self.build_bluetooth,
            "more": self.build_more,
        }
        self.built = set()
        self.content_page = Adw.NavigationPage(title="Appearance")
        content_view = Adw.ToolbarView()
        content_view.add_top_bar(Adw.HeaderBar())
        content_view.set_content(self.stack)
        self.content_page.set_child(content_view)
        self.split.set_content(self.content_page)
        self.split.set_min_sidebar_width(210)
        self.split.set_max_sidebar_width(230)

        self.user_css = None
        self.load_user_css()
        self.select_page(page)

    # ---- css that follows the theme live
    def load_user_css(self):
        display = Gdk.Display.get_default()
        if self.user_css is None:
            self.user_css = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(display, self.user_css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            app_css = Gtk.CssProvider()
            app_css.load_from_string(APP_CSS)
            Gtk.StyleContext.add_provider_for_display(display, app_css, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        if USER_CSS.exists():
            self.user_css.load_from_path(str(USER_CSS))

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=2))

    # ---- navigation
    def select_page(self, pid):
        for i, (page_id, _t, _i) in enumerate(PAGES):
            if page_id == pid:
                self.sidebar_list.select_row(self.sidebar_list.get_row_at_index(i))
                return
        self.sidebar_list.select_row(self.sidebar_list.get_row_at_index(0))

    def on_row_selected(self, _lb, row):
        if row is None:
            return
        pid = row.page_id
        if pid not in self.built:
            self.stack.add_named(self.builders[pid](), pid)
            self.built.add(pid)
        self.stack.set_visible_child_name(pid)
        self.content_page.set_title(dict((p, t) for p, t, _ in PAGES)[pid])
        self.split.set_show_content(True)

    # ======================================================================= Appearance
    def build_appearance(self):
        page = Adw.PreferencesPage()

        mode_group = Adw.PreferencesGroup(title="Mode")
        row = Adw.ActionRow(title="Appearance", subtitle="Dark or light. Applies to the desktop and its apps.")
        self.dark_btn = Gtk.ToggleButton(label="Dark")
        self.light_btn = Gtk.ToggleButton(label="Light", group=self.dark_btn)
        box = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        box.append(self.dark_btn)
        box.append(self.light_btn)
        row.add_suffix(box)
        mode_group.add(row)
        page.add(mode_group)

        group = Adw.PreferencesGroup(title="Theme", description="Palette, fonts and shape for bar, windows and apps.")
        self.theme_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                      min_children_per_line=2, max_children_per_line=4,
                                      column_spacing=12, row_spacing=12)
        self.theme_buttons = {}
        for t in themes():
            self.theme_flow.append(self.make_theme_card(t))
        group.add(self.theme_flow)
        page.add(group)

        self.mode_handlers = (self.dark_btn.connect("toggled", self.on_mode_toggled),
                              self.light_btn.connect("toggled", self.on_mode_toggled))
        self.refresh_theme_state()
        return page

    def make_theme_card(self, t):
        colors = {k: t.get(k, "000000") for k in ("base", "mantle", "surface0", "text", "accent", "accent2")}
        area = Swatch(colors)
        title = Gtk.Label(label=t.get("name", t["_id"]), xalign=0, css_classes=["theme-name"])
        sub = Gtk.Label(label=("Dark" if t.get("mode") == "dark" else "Light"), xalign=0, css_classes=["dim", "caption"])
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner.append(area)
        inner.append(title)
        inner.append(sub)
        btn = Gtk.Button(child=inner, css_classes=["card", "theme-card"])
        btn.connect("clicked", lambda _b, tid=t["_id"], nm=t.get("name", t["_id"]): self.apply_theme(tid, nm))
        btn.theme_mode = t.get("mode", "dark")
        self.theme_buttons[t["_id"]] = btn
        return btn

    def refresh_theme_state(self):
        cur = current_theme()
        cur_mode = next((t.get("mode") for t in themes() if t["_id"] == cur), "dark")
        for tid, btn in self.theme_buttons.items():
            (btn.add_css_class if tid == cur else btn.remove_css_class)("active")
        for h, b in zip(self.mode_handlers, (self.dark_btn, self.light_btn)):
            b.handler_block(h)
        self.dark_btn.set_active(cur_mode == "dark")
        self.light_btn.set_active(cur_mode == "light")
        for h, b in zip(self.mode_handlers, (self.dark_btn, self.light_btn)):
            b.handler_unblock(h)

    def on_mode_toggled(self, btn):
        if not btn.get_active():
            return
        self.run_theme_switch(["dark" if btn is self.dark_btn else "light"], "Switching…")

    def apply_theme(self, tid, name):
        self.run_theme_switch([tid], f"{name} applied")

    def run_theme_switch(self, args, done_text):
        self.toast("Applying…")
        proc = Gio.Subprocess.new([str(THEME_SWITCH)] + args,
                                  Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)

        def finished(p, res):
            try:
                p.wait_finish(res)
            except GLib.Error:
                pass
            self.load_user_css()
            self.refresh_theme_state()
            if "wallpaper" in self.built:
                self.refresh_wallpaper_state()
            self.toast(done_text if p.get_successful() else "Could not apply the theme")

        proc.wait_async(None, finished)

    # ======================================================================= Wallpaper
    def build_wallpaper(self):
        page = Adw.PreferencesPage()

        cur_group = Adw.PreferencesGroup(title="Current wallpaper")
        self.wp_preview = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, height_request=230,
                                      css_classes=["wp-preview"], overflow=Gtk.Overflow.HIDDEN)
        cur_group.add(self.wp_preview)
        page.add(cur_group)

        actions = Adw.PreferencesGroup()
        choose = Adw.ActionRow(title="Choose a picture…", subtitle="A picture, a GIF or a video", activatable=True)
        choose.add_prefix(Gtk.Image.new_from_icon_name("document-open-symbolic"))
        choose.connect("activated", self.on_choose_file)
        self.wp_reset = Adw.ActionRow(title="Use the theme's wallpaper", activatable=True)
        self.wp_reset.add_prefix(Gtk.Image.new_from_icon_name("edit-undo-symbolic"))
        self.wp_reset.connect("activated", lambda *_: self.set_wallpaper("reset"))
        actions.add(choose)
        actions.add(self.wp_reset)
        page.add(actions)

        if sh("sh", "-c", "command -v awww").returncode == 0:
            transitions = [("Grow from the cursor", "grow"), ("Fade", "fade"), ("Wave", "wave"),
                           ("Wipe", "wipe"), ("None", "none")]
            tgroup = Adw.PreferencesGroup(title="Transition", description="How the new wallpaper appears")
            trow = Adw.ComboRow(title="Animation", model=Gtk.StringList.new([n for n, _ in transitions]))
            try:
                current = (STATE_DIR / "wallpaper-transition").read_text().strip()
            except OSError:
                current = "grow"
            trow.set_selected(next((i for i, (_n, v) in enumerate(transitions) if v == current), 0))

            def on_transition(row, _p):
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                (STATE_DIR / "wallpaper-transition").write_text(transitions[row.get_selected()][1])
                self.toast("Applies to the next wallpaper change")

            trow.connect("notify::selected", on_transition)
            tgroup.add(trow)
            page.add(tgroup)

        page.add(self.build_slideshow())
        if shutil.which("mpvpaper"):
            page.add(self.build_video_options())

        self.wp_group = Adw.PreferencesGroup(title="Pictures", description="Theme art and images from ~/Pictures")
        self.wp_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                   min_children_per_line=2, max_children_per_line=4,
                                   column_spacing=12, row_spacing=12)
        self.wp_buttons = {}
        self.wp_group.add(self.wp_flow)
        page.add(self.wp_group)

        self.wp_queue = list(self.find_wallpapers())
        GLib.idle_add(self.load_next_thumb)
        self.refresh_wallpaper_state()
        return page

    def build_video_options(self):
        group = Adw.PreferencesGroup(title="Video wallpaper", description="Videos are paused while windows cover the screen")
        keep = STATE_DIR / "video-keep-on-battery"
        row = Adw.SwitchRow(title="Pause on battery", subtitle="A moving wallpaper drains the battery", active=not keep.exists())

        def on_toggle(r, _p):
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            if r.get_active():
                keep.unlink(missing_ok=True)
            else:
                keep.write_text("")

        row.connect("notify::active", on_toggle)
        group.add(row)
        return group

    def build_slideshow(self):
        group = Adw.PreferencesGroup(title="Slideshow", description="Change the wallpaper by itself, using a folder of pictures")

        def read(name, default=""):
            try:
                return (STATE_DIR / name).read_text().strip() or default
            except OSError:
                return default

        folder = Adw.ActionRow(title="Folder", subtitle=read("slideshow-dir", "Not chosen yet"), activatable=True)
        folder.add_prefix(Gtk.Image.new_from_icon_name("folder-symbolic"))
        on = Adw.SwitchRow(title="Rotate automatically", active=(STATE_DIR / "slideshow-on").exists())
        steps = [("Every minute", 1), ("Every 5 minutes", 5), ("Every 15 minutes", 15), ("Every 30 minutes", 30),
                 ("Every hour", 60), ("Every 3 hours", 180)]
        every = Adw.ComboRow(title="Interval", model=Gtk.StringList.new([n for n, _ in steps]))
        every.set_selected(next((i for i, (_n, m) in enumerate(steps) if str(m) == read("slideshow-interval", "30")), 3))
        now = Adw.ActionRow(title="Next wallpaper now", activatable=True)
        now.add_prefix(Gtk.Image.new_from_icon_name("media-skip-forward-symbolic"))

        def save(name, value):
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            (STATE_DIR / name).write_text(value)

        def sync():
            ready = (STATE_DIR / "slideshow-dir").exists()
            every.set_sensitive(ready)
            now.set_sensitive(ready)
            on.set_sensitive(ready)

        def on_toggle(row, _p):
            if row.get_active():
                save("slideshow-on", "")
            else:
                (STATE_DIR / "slideshow-on").unlink(missing_ok=True)

        def on_folder(*_):
            def done(d, res):
                try:
                    f = d.select_folder_finish(res)
                except GLib.Error:
                    return
                if f:
                    save("slideshow-dir", f.get_path())
                    folder.set_subtitle(f.get_path())
                    sync()
                    on.set_active(True)

            Gtk.FileDialog(title="Choose a folder of wallpapers").select_folder(self, None, done)

        def on_now(*_):
            Gio.Subprocess.new([str(HYPR_DIR / "scripts" / "wallpaper-rotate.sh"), "next"],
                               Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
            GLib.timeout_add(1500, lambda: (self.refresh_wallpaper_state(), False)[1])

        folder.connect("activated", on_folder)
        on.connect("notify::active", on_toggle)
        every.connect("notify::selected", lambda r, _p: save("slideshow-interval", str(steps[r.get_selected()][1])))
        now.connect("activated", on_now)
        for row in (folder, on, every, now):
            group.add(row)
        sync()
        return group

    @staticmethod
    def find_wallpapers():
        seen = set()
        exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"} | (VIDEO_EXTS if shutil.which("mpvpaper") else set())
        dirs = [Path.home() / "Pictures" / "Wallpapers", Path.home() / "Pictures"]
        for t in themes():
            p = THEMES_DIR / t["_id"] / "wallpaper.png"
            if p.exists():
                seen.add(p)
                yield p, t.get("name", t["_id"])
        for d in dirs:
            if d.is_dir():
                for p in sorted(d.iterdir()):
                    if p.is_file() and p.suffix.lower() in exts and p not in seen:
                        seen.add(p)
                        yield p, p.stem

    def load_next_thumb(self):
        if not self.wp_queue:
            return False
        path, label = self.wp_queue.pop(0)
        pix = load_still(path, 420, 250)
        if pix is None:
            return True
        pic = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pix))
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(190, 110)
        pic.set_overflow(Gtk.Overflow.HIDDEN)
        cap = Gtk.Label(label=label, xalign=0, ellipsize=3, css_classes=["caption", "dim"])
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.append(pic)
        inner.append(cap)
        btn = Gtk.Button(child=inner, css_classes=["flat", "wp-thumb"], tooltip_text=str(path))
        btn.connect("clicked", lambda _b, p=path: self.set_wallpaper(str(p)))
        self.wp_buttons[str(path)] = btn
        self.wp_flow.append(btn)
        self.mark_active_wallpaper()
        return True

    def current_wallpaper(self):
        try:
            return (STATE_DIR / "wallpaper-current").read_text().strip()
        except OSError:
            pass
        try:
            for line in (HYPR_DIR / "hyprpaper.conf").read_text().splitlines():
                m = re.match(r"\s*path\s*=\s*(.+)", line)
                if m:
                    return m.group(1).strip()
        except OSError:
            pass
        return ""

    def refresh_wallpaper_state(self):
        path = self.current_wallpaper()
        if path and Path(path).exists():
            pix = load_still(path, 900, 520)
            if pix is not None:
                self.wp_preview.set_paintable(Gdk.Texture.new_for_pixbuf(pix))
        self.wp_reset.set_visible((STATE_DIR / "wallpaper").exists())
        self.mark_active_wallpaper()

    def mark_active_wallpaper(self):
        cur = self.current_wallpaper()
        for p, btn in self.wp_buttons.items():
            (btn.add_css_class if p == cur else btn.remove_css_class)("active")

    def set_wallpaper(self, path):
        self.toast("Applying…")
        proc = Gio.Subprocess.new([str(THEME_SWITCH), "--wallpaper", path],
                                  Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)

        def finished(p, res):
            try:
                p.wait_finish(res)
            except GLib.Error:
                pass
            self.refresh_wallpaper_state()
            self.toast("Wallpaper updated" if p.get_successful() else "Could not set the wallpaper")

        proc.wait_async(None, finished)

    def on_choose_file(self, *_):
        dialog = Gtk.FileDialog(title="Choose a wallpaper")  # videos need mpvpaper
        flt = Gtk.FileFilter(name="Images")
        flt.add_mime_type("image/png")
        flt.add_mime_type("image/jpeg")
        flt.add_mime_type("image/webp")
        flt.add_mime_type("image/gif")
        for m in ("video/mp4", "video/webm", "video/x-matroska", "video/quicktime"):
            flt.add_mime_type(m)
        flt.set_name("Pictures, GIFs and videos")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(flt)
        dialog.set_filters(store)
        dialog.set_default_filter(flt)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            if f:
                self.set_wallpaper(f.get_path())

        dialog.open(self, None, done)

    # ======================================================================= Displays
    def build_displays(self):
        self.disp_page = Adw.PreferencesPage()
        self.disp_groups = []
        self.disp_apply_group = None
        self.load_monitors()
        return self.disp_page

    def load_monitors(self):
        for g in self.disp_groups:
            self.disp_page.remove(g)
        if self.disp_apply_group is not None:
            self.disp_page.remove(self.disp_apply_group)
        self.disp_groups = []
        raw = json.loads(sh("hyprctl", "monitors", "all", "-j").stdout or "[]")
        self.monitors = []
        for m in raw:
            modes = {}
            for s in m["availableModes"]:
                res, rate = s.rstrip("Hz").split("@")
                modes.setdefault(res, []).append(rate)
            self.monitors.append({
                "name": m["name"], "desc": m.get("description", ""),
                "modes": modes, "res": f'{m["width"]}x{m["height"]}',
                "rate": f'{m["refreshRate"]:.2f}', "scale": float(m["scale"]),
                "transform": int(m["transform"]), "x": m["x"], "y": m["y"],
                "disabled": bool(m["disabled"]), "w": m["width"], "h": m["height"],
            })
        self.rows = {}
        for i, mon in enumerate(self.monitors):
            g = self.make_monitor_group(i, mon)
            self.disp_page.add(g)
            self.disp_groups.append(g)

        bar = Adw.PreferencesGroup()
        box = Gtk.Box(spacing=10, halign=Gtk.Align.END, margin_top=4)
        reset = Gtk.Button(label="Restore defaults")
        reset.connect("clicked", self.on_restore_displays)
        apply_btn = Gtk.Button(label="Apply", css_classes=["suggested-action", "pill"])
        apply_btn.connect("clicked", self.on_apply_displays)
        box.append(reset)
        box.append(apply_btn)
        bar.add(box)
        self.disp_apply_group = bar
        self.disp_page.add(bar)

    SCALES = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
    ROTATIONS = [("Normal", 0), ("90°", 1), ("180°", 2), ("270°", 3)]

    def make_monitor_group(self, idx, mon):
        g = Adw.PreferencesGroup(title=mon["name"], description=mon["desc"])
        rows = {}

        if len(self.monitors) > 1:
            sw = Adw.SwitchRow(title="Enabled", active=not mon["disabled"])
            g.add(sw)
            rows["enabled"] = sw

        res_list = sorted(mon["modes"], key=lambda r: -int(r.split("x")[0]) * int(r.split("x")[1]))
        res_row = Adw.ComboRow(title="Resolution", model=Gtk.StringList.new([r.replace("x", " × ") for r in res_list]))
        res_row.set_selected(res_list.index(mon["res"]) if mon["res"] in res_list else 0)
        g.add(res_row)
        rows["res"], rows["res_list"] = res_row, res_list

        rate_row = Adw.ComboRow(title="Refresh rate")
        g.add(rate_row)
        rows["rate"] = rate_row

        def fill_rates(*_):
            res = res_list[res_row.get_selected()]
            rates = sorted(set(mon["modes"][res]), key=lambda r: -float(r))
            rows["rate_list"] = rates
            rate_row.set_model(Gtk.StringList.new([f"{float(r):.0f} Hz" for r in rates]))
            want = mon["rate"] if res == mon["res"] else rates[0]
            best = min(range(len(rates)), key=lambda i: abs(float(rates[i]) - float(want)))
            rate_row.set_selected(best)

        res_row.connect("notify::selected", fill_rates)
        fill_rates()

        scale_row = Adw.ComboRow(title="Scale", model=Gtk.StringList.new([f"{round(s * 100)}%" for s in self.SCALES]))
        scale_row.set_selected(min(range(len(self.SCALES)), key=lambda i: abs(self.SCALES[i] - mon["scale"])))
        g.add(scale_row)
        rows["scale"] = scale_row

        rot_row = Adw.ComboRow(title="Rotation", model=Gtk.StringList.new([n for n, _ in self.ROTATIONS]))
        rot_row.set_selected(next((i for i, (_n, v) in enumerate(self.ROTATIONS) if v == mon["transform"]), 0))
        g.add(rot_row)
        rows["rot"] = rot_row

        if idx > 0:
            primary = self.monitors[0]["name"]
            opts = [f"Right of {primary}", f"Left of {primary}", f"Above {primary}", f"Below {primary}", f"Mirror {primary}"]
            pos_row = Adw.ComboRow(title="Position", model=Gtk.StringList.new(opts))
            p0 = self.monitors[0]
            if mon["x"] < 0:
                guess = 1
            elif mon["y"] < 0:
                guess = 2
            elif mon["y"] >= p0["y"] + p0["h"] and mon["x"] < p0["x"] + p0["w"]:
                guess = 3
            else:
                guess = 0
            pos_row.set_selected(guess)
            g.add(pos_row)
            rows["pos"] = pos_row

        self.rows[idx] = rows
        return g

    def collect_specs(self):
        """Specs for every monitor from the current UI state."""
        specs = []
        prim = self.monitors[0]
        for i, mon in enumerate(self.monitors):
            r = self.rows[i]
            if "enabled" in r and not r["enabled"].get_active():
                specs.append({"output": mon["name"], "disabled": True})
                continue
            res = r["res_list"][r["res"].get_selected()]
            rate = r["rate_list"][r["rate"].get_selected()]
            scale = self.SCALES[r["scale"].get_selected()]
            transform = self.ROTATIONS[r["rot"].get_selected()][1]
            spec = {"output": mon["name"], "mode": f"{res}@{rate}", "scale": scale, "transform": transform,
                    "position": "0x0", "_res": res}
            specs.append(spec)

        # Positions: the first monitor is the anchor at 0x0; the others sit next to it.
        def logical(spec):
            w, h = map(int, spec["_res"].split("x"))
            if spec["transform"] in (1, 3):
                w, h = h, w
            return w / spec["scale"], h / spec["scale"]

        anchor = specs[0]
        if "_res" in anchor:
            aw, ah = logical(anchor)
            for i, spec in enumerate(specs[1:], start=1):
                if "_res" not in spec:
                    continue
                w, h = logical(spec)
                choice = self.rows[i]["pos"].get_selected()
                if choice == 0:
                    spec["position"] = f"{round(aw)}x0"
                elif choice == 1:
                    spec["position"] = f"{-round(w)}x0"
                elif choice == 2:
                    spec["position"] = f"0x{-round(h)}"
                elif choice == 3:
                    spec["position"] = f"0x{round(ah)}"
                else:
                    spec["mirror"] = anchor["output"]
        return specs

    @staticmethod
    def spec_to_lua(spec):
        parts = [f'output = "{spec["output"]}"']
        if spec.get("disabled"):
            parts.append("disabled = true")
        elif spec.get("mirror"):
            parts.append(f'mirror = "{spec["mirror"]}"')
        else:
            parts += [f'mode = "{spec["mode"]}"', f'position = "{spec["position"]}"',
                      f'scale = {spec["scale"]}', f'transform = {spec["transform"]}']
        return "hl.monitor({ " + ", ".join(parts) + " })"

    def current_specs(self):
        """What is running right now, to be able to revert."""
        out = []
        for m in self.monitors:
            if m["disabled"]:
                out.append({"output": m["name"], "disabled": True})
            else:
                out.append({"output": m["name"], "mode": f'{m["res"]}@{m["rate"]}', "scale": m["scale"],
                            "transform": m["transform"], "position": f'{m["x"]}x{m["y"]}'})
        return out

    def apply_specs(self, specs):
        for s in specs:
            hypr_eval(self.spec_to_lua(s))

    def on_apply_displays(self, *_):
        previous = self.current_specs()
        specs = self.collect_specs()
        self.apply_specs(specs)

        dialog = Adw.AlertDialog(heading="Keep these display settings?")
        dialog.add_response("revert", "Revert")
        dialog.add_response("keep", "Keep")
        dialog.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("revert")
        dialog.set_close_response("revert")
        state = {"left": 10, "timer": 0, "answered": False}

        def tick():
            state["left"] -= 1
            if state["left"] <= 0:
                state["timer"] = 0
                dialog.force_close()
                return False
            dialog.set_body(f"Reverting in {state['left']} seconds if you do nothing.")
            return True

        dialog.set_body(f"Reverting in {state['left']} seconds if you do nothing.")
        state["timer"] = GLib.timeout_add_seconds(1, tick)

        def answered(d, res):
            state["answered"] = True
            if state["timer"]:
                GLib.source_remove(state["timer"])
            try:
                choice = d.choose_finish(res)
            except GLib.Error:
                choice = "revert"
            if choice == "keep":
                self.persist_displays(specs)
                self.toast("Display settings saved")
            else:
                self.apply_specs(previous)
                self.toast("Reverted")
            GLib.timeout_add(900, lambda: (self.load_monitors(), False)[1])

        dialog.choose(self, None, answered)

    def persist_displays(self, specs):
        lines = ["-- GENERATED by Primo Settings (Displays). Delete this file to restore the defaults."]
        lines += [self.spec_to_lua(s) for s in specs]
        DISPLAYS_LUA.write_text("\n".join(lines) + "\n")

    def on_restore_displays(self, *_):
        if DISPLAYS_LUA.exists():
            DISPLAYS_LUA.unlink()
        sh("hyprctl", "reload")
        self.toast("Defaults restored")
        GLib.timeout_add(1200, lambda: (self.load_monitors(), False)[1])


    # ======================================================================= Power
    PROFILES = [("power-saver", "Power Saver"), ("balanced", "Balanced"), ("performance", "Performance")]

    @staticmethod
    def battery_dir():
        for d in sorted(Path("/sys/class/power_supply").glob("BAT*")):
            return d
        return None

    @staticmethod
    def read_num(path):
        try:
            return float(Path(path).read_text().strip())
        except (OSError, ValueError):
            return None

    def build_power(self):
        page = Adw.PreferencesPage()

        mode = Adw.PreferencesGroup(title="Power mode",
                                    description="Power Saver stretches the battery, Performance trades it for speed.")
        if sh("sh", "-c", "command -v powerprofilesctl").returncode != 0:
            row = Adw.ActionRow(title="power-profiles-daemon is not installed",
                                subtitle="sudo pacman -S power-profiles-daemon, then sudo scripts/setup-system.sh --apply")
            mode.add(row)
        else:
            listing = sh("powerprofilesctl", "list").stdout
            available = [n for n, _l in self.PROFILES if re.search(rf"^\s*\*?\s*{n}:", listing, re.M)] or ["balanced"]
            current = sh("powerprofilesctl", "get").stdout.strip() or "balanced"
            row = Adw.ActionRow(title="Mode", subtitle="Applies to the whole system")
            group = Adw.ToggleGroup(valign=Gtk.Align.CENTER)
            for name, label in self.PROFILES:
                if name in available:
                    group.add(Adw.Toggle(name=name, label=label))
            group.set_active_name(current)
            group.connect("notify::active-name", lambda g, _p: self.set_profile(g.get_active_name()))
            row.add_suffix(group)
            mode.add(row)
        page.add(mode)

        bat = self.battery_dir()
        battery = Adw.PreferencesGroup(title="Battery")
        if bat is None:
            battery.add(Adw.ActionRow(title="No battery detected"))
        else:
            self.bat_row = Adw.ActionRow(title="Charge")
            self.bat_level = Gtk.LevelBar(min_value=0, max_value=100, value=0, valign=Gtk.Align.CENTER, width_request=170)
            self.bat_pct = Gtk.Label(label="", css_classes=["title-3"], width_chars=5)
            self.bat_row.add_suffix(self.bat_level)
            self.bat_row.add_suffix(self.bat_pct)
            battery.add(self.bat_row)
            self.bat_health = Adw.ActionRow(title="Battery health")
            battery.add(self.bat_health)
            self.update_battery()
            GLib.timeout_add_seconds(5, self.update_battery)
        page.add(battery)

        warn = Adw.PreferencesGroup(title="Low battery",
                                    description="Warnings appear at 20%, 10% and 4% (it suspends at 4% unless you plug in).")
        saver = Adw.SwitchRow(title="Switch to Power Saver at 20%", subtitle="Back to your previous mode when you plug in")
        try:
            saver.set_active((STATE_DIR / "battery-autosaver").read_text().strip() != "off")
        except OSError:
            saver.set_active(True)

        def on_saver(row, _p):
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            (STATE_DIR / "battery-autosaver").write_text("on" if row.get_active() else "off")

        saver.connect("notify::active", on_saver)
        warn.add(saver)
        page.add(warn)
        return page

    def set_profile(self, name):
        if name:
            sh("powerprofilesctl", "set", name)
            sh("pkill", "-RTMIN+12", "waybar")
            self.toast(dict(self.PROFILES).get(name, name))

    def update_battery(self):
        bat = self.battery_dir()
        if bat is None or not self.bat_row.get_mapped() and getattr(self, "_bat_seen", False):
            return bat is not None
        self._bat_seen = True
        cap = self.read_num(bat / "capacity") or 0
        try:
            status = (bat / "status").read_text().strip()
        except OSError:
            status = "Unknown"
        now = self.read_num(bat / "energy_now") or self.read_num(bat / "charge_now")
        full = self.read_num(bat / "energy_full") or self.read_num(bat / "charge_full")
        design = self.read_num(bat / "energy_full_design") or self.read_num(bat / "charge_full_design")
        rate = self.read_num(bat / "power_now") or self.read_num(bat / "current_now")
        left = ""
        if rate and rate > 0 and now is not None and full is not None:
            hours = (now / rate) if status == "Discharging" else ((full - now) / rate if status == "Charging" else 0)
            if hours > 0:
                left = f" · about {int(hours)} h {int((hours % 1) * 60):02d} min {'left' if status == 'Discharging' else 'to full'}"
        self.bat_row.set_subtitle(status + left)
        self.bat_level.set_value(cap)
        self.bat_pct.set_label(f"{int(cap)}%")
        if full and design:
            self.bat_health.set_subtitle(f"{full / design * 100:.0f}% of its original capacity")
        else:
            self.bat_health.set_subtitle("Not reported by this battery")
        return True

    # ======================================================================= Bluetooth
    def build_bluetooth(self):
        page = Adw.PreferencesPage()
        if sh("sh", "-c", "command -v bluetoothctl").returncode != 0:
            group = Adw.PreferencesGroup()
            group.add(Adw.ActionRow(title="Bluetooth is not installed",
                                    subtitle="sudo pacman -S bluez bluez-utils blueman, then sudo scripts/setup-system.sh --apply"))
            page.add(group)
            return page

        top = Adw.PreferencesGroup()
        self.bt_switch = Adw.SwitchRow(title="Bluetooth", subtitle="Checking…")
        self.bt_switch_handler = self.bt_switch.connect("notify::active", self.on_bt_power)
        top.add(self.bt_switch)
        page.add(top)

        self.bt_devices = Adw.PreferencesGroup(title="Devices")
        page.add(self.bt_devices)

        pair = Adw.PreferencesGroup()
        row = Adw.ActionRow(title="Pair a new device…", subtitle="Opens the Bluetooth manager", activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        row.connect("activated", lambda *_: spawn("blueman-manager"))
        pair.add(row)
        page.add(pair)
        self.bt_rows = []
        self.refresh_bluetooth()
        return page

    def refresh_bluetooth(self):
        def work():
            show = sh("bluetoothctl", "show").stdout
            powered = "Powered: yes" in show
            has_adapter = bool(show.strip()) and "No default controller" not in show
            devices = []
            if has_adapter:
                for line in sh("bluetoothctl", "devices", "Paired").stdout.splitlines():
                    parts = line.split(" ", 2)
                    if len(parts) == 3 and parts[0] == "Device":
                        info = sh("bluetoothctl", "info", parts[1]).stdout
                        devices.append((parts[1], parts[2], "Connected: yes" in info))
            GLib.idle_add(self.apply_bluetooth, has_adapter, powered, devices)

        import threading
        threading.Thread(target=work, daemon=True).start()

    def apply_bluetooth(self, has_adapter, powered, devices):
        self.bt_switch.handler_block(self.bt_switch_handler)
        self.bt_switch.set_sensitive(has_adapter)
        self.bt_switch.set_active(powered)
        self.bt_switch.set_subtitle("On" if powered else ("Off" if has_adapter else "No Bluetooth adapter found"))
        self.bt_switch.handler_unblock(self.bt_switch_handler)
        for r in self.bt_rows:
            self.bt_devices.remove(r)
        self.bt_rows = []
        for mac, name, connected in devices:
            row = Adw.ActionRow(title=name, subtitle="Connected" if connected else "Not connected")
            row.add_prefix(Gtk.Image.new_from_icon_name("bluetooth-symbolic"))
            toggle = Gtk.Button(label="Disconnect" if connected else "Connect", valign=Gtk.Align.CENTER)
            toggle.connect("clicked", lambda _b, m=mac, c=connected: self.bt_action("disconnect" if c else "connect", m))
            forget = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Forget this device",
                                css_classes=["flat"])
            forget.connect("clicked", lambda _b, m=mac: self.bt_action("remove", m))
            row.add_suffix(toggle)
            row.add_suffix(forget)
            self.bt_devices.add(row)
            self.bt_rows.append(row)
        if not devices:
            row = Adw.ActionRow(title="No paired devices" if has_adapter else "No adapter")
            self.bt_devices.add(row)
            self.bt_rows.append(row)
        return False

    def on_bt_power(self, row, _p):
        sh("bluetoothctl", "power", "on" if row.get_active() else "off")
        GLib.timeout_add(600, lambda: (self.refresh_bluetooth(), False)[1])

    def bt_action(self, action, mac):
        self.toast("Working…")

        def work():
            sh("bluetoothctl", action, mac)
            GLib.idle_add(self.refresh_bluetooth)

        import threading
        threading.Thread(target=work, daemon=True).start()

    # ======================================================================= More
    def build_more(self):
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="System", description="Open the dedicated tool.")
        for title, sub, icon, cmd in [
            ("Sound", "Volume, input and output devices", "audio-volume-high-symbolic", ["pavucontrol"]),
            ("Network", "Wi-Fi and connections", "network-wireless-symbolic", ["nm-connection-editor"]),
            ("Bluetooth", "Devices and pairing", "bluetooth-symbolic", ["blueman-manager"]),
            ("Notifications", "Open the notification center", "preferences-system-notifications-symbolic",
             ["swaync-client", "-t", "-sw"]),
            ("Backups", "System snapshots with Timeshift", "document-save-symbolic", ["timeshift-launcher"]),
            ("Disk usage", "See what takes up space", "drive-harddisk-symbolic", ["baobab"]),
            ("Passwords", "KeePassXC vault", "dialog-password-symbolic", ["keepassxc"]),
        ]:
            if sh("sh", "-c", f"command -v {cmd[0]}").returncode != 0:
                continue
            row = Adw.ActionRow(title=title, subtitle=sub, activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda _r, c=cmd: spawn(*c))
            group.add(row)
        page.add(group)

        about = Adw.PreferencesGroup(title="Shortcuts")
        for title, keys in [("Settings", "Super + ,"), ("Displays", "Super + D"), ("Wallpaper", "Super + W"),
                            ("Theme menu", "Super + T"), ("Dark / light", "Super + Shift + T")]:
            row = Adw.ActionRow(title=title)
            row.add_suffix(Gtk.Label(label=keys, css_classes=["dim"]))
            about.add(row)
        page.add(about)
        return page


class App(Adw.Application):
    def __init__(self, page):
        super().__init__(application_id="dev.primo.Settings", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.page = page

    def do_activate(self):
        win = SettingsWindow(self, self.page)
        win.present()


def main():
    page = "appearance"
    if "--page" in sys.argv:
        i = sys.argv.index("--page")
        if i + 1 < len(sys.argv):
            page = sys.argv[i + 1]
    return App(page).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
