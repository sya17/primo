#!/usr/bin/env python3
"""Primo Settings: Appearance, Wallpaper and Displays in one libadwaita window.

Usage: primo-settings.py [--page appearance|wallpaper|displays|power|bluetooth|modes|workflow|health|vpn|more]

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
import idle_core

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
    ("modes", "Modes", "emblem-system-symbolic"),
    ("workflow", "Workflow", "view-list-symbolic"),
    ("health", "Health", "emblem-default-symbolic"),
    ("vpn", "VPN", "network-vpn-symbolic"),
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


def nm_fields(line):
    """Split one line of `nmcli -t` output (':' separated, '\\:' is a literal colon)."""
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r"(?<!\\):", line)]


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
            "modes": self.build_modes,
            "workflow": self.build_workflow,
            "health": self.build_health,
            "vpn": self.build_vpn,
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

        page.add(self.build_lock_login())

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
        if Path(path).suffix.lower() in VIDEO_EXTS and not shutil.which("mpvpaper"):
            self.toast("Video wallpapers need mpvpaper: yay -S mpvpaper")
            return
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

    def build_lock_login(self):
        group = Adw.PreferencesGroup(title="Lock and login screens",
                                     description="Behind the clock. GIFs move at login; videos show one frame")
        lock = [("Desktop wallpaper", "desktop"), ("Blurred windows", "blur"), ("A picture of its own…", "file")]
        login = [("Desktop wallpaper", "desktop"), ("A picture of its own…", "file")]
        group.add(self.screen_bg_row("Lock screen", "lock-wallpaper", lock))
        group.add(self.screen_bg_row("Login screen", "login-wallpaper", login))
        return group

    def screen_bg_row(self, title, state, options):
        keys = [k for _n, k in options]
        try:
            cur = (STATE_DIR / state).read_text().strip()
        except OSError:
            cur = ""
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([n for n, _k in options]))
        if cur.startswith("/"):
            row.set_selected(keys.index("file"))
            row.set_subtitle(Path(cur).name)
        else:
            row.set_selected(keys.index(cur) if cur in keys else keys.index("desktop"))
        row.last, row.quiet = row.get_selected(), False

        def apply(value):
            proc = Gio.Subprocess.new([str(THEME_SWITCH), f"--{state}", value],
                                      Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)

            def finished(p, res):
                try:
                    p.wait_finish(res)
                except GLib.Error:
                    pass
                if not p.get_successful():
                    self.toast(f"Could not change the {title.lower()}")
                    select(row.last)
                    return
                row.last = row.get_selected()
                row.set_subtitle(Path(value).name if value.startswith("/") else "")
                if state == "lock-wallpaper":
                    self.toast("Shown the next time the screen locks")
                else:
                    self.install_login_theme()

            proc.wait_async(None, finished)

        def on_selected(r, _p):
            if r.quiet:
                return
            key = keys[r.get_selected()]
            if key != "file":
                apply(key)
                return

            self.pick_media(f"Choose a picture for the {title.lower()}", apply, lambda: select(r.last))

        def select(i):
            row.quiet = True
            row.set_selected(i)
            row.quiet = False

        def choose(*_):
            def chosen(path):
                select(keys.index("file"))
                apply(path)
            self.pick_media(f"Choose a picture for the {title.lower()}", chosen)

        pick = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                          tooltip_text="Choose a picture")
        pick.update_property([Gtk.AccessibleProperty.LABEL], [f"Choose a picture for the {title.lower()}"])
        pick.connect("clicked", choose)
        row.add_suffix(pick)
        row.connect("notify::selected", on_selected)
        return row

    def install_login_theme(self):
        """theme-switch has already updated /var/lib/primo-login when install-sddm-theme.sh set it up once.
        No pkexec here on purpose: the script lives in a folder you own, so anything running as you could change it
        before an admin password prompt runs it as root."""
        if os.access("/var/lib/primo-login", os.W_OK):
            self.toast("Login screen updated")
        else:
            self.toast("Saved. To show it at login, run once in a terminal: sudo scripts/install-sddm-theme.sh")

    def on_choose_file(self, *_):
        self.pick_media("Choose a wallpaper", self.set_wallpaper)   # videos need mpvpaper

    def pick_media(self, title, on_path, on_cancel=None):
        dialog = Gtk.FileDialog(title=title)
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
                f = None
            if f:
                on_path(f.get_path())
            elif on_cancel:
                on_cancel()

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

        idle = Adw.PreferencesGroup(title="When idle", description="Times since your last activity. Fullscreen apps can keep the desktop awake.")
        self.idle_rows = {}
        try:
            values = idle_core.load()
        except (OSError, ValueError, TypeError) as error:
            idle.add(Adw.ActionRow(title="Cannot read idle settings", subtitle=str(error)))
        else:
            for key, title in (("dim", "Dim screen"), ("lock", "Lock screen"),
                               ("screen", "Turn off screen"), ("sleep", "Sleep")):
                choices = sorted({0, 60, 120, 150, 300, 330, 600, 900, 1800, 3600, 7200, values[key]})
                labels = ["Never" if n == 0 else
                          f"{n // 60} min {n % 60} sec" if n % 60 else f"{n // 60} min" for n in choices]
                row = Adw.ComboRow(title=title, model=Gtk.StringList.new(labels))
                row.set_selected(choices.index(values[key]))
                self.idle_rows[key] = (row, choices)
                idle.add(row)
            apply_row = Adw.ActionRow(title="Apply idle settings", subtitle="Never disables only the selected automatic action.")
            button = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
            button.connect("clicked", self.apply_idle)
            button.set_sensitive(shutil.which("hypridle") is not None)
            if shutil.which("hypridle") is None:
                apply_row.set_subtitle("Install hypridle to apply idle settings.")
            apply_row.add_suffix(button)
            idle.add(apply_row)
        page.add(idle)

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

        busy = Adw.PreferencesGroup(title="Busy apps", description="Only checked while on battery, every 30 seconds")
        alert = Adw.SwitchRow(title="Warn about an app that keeps the CPU busy",
                              subtitle="After 5 minutes above 50% CPU. Open Activity (Super+Shift+Esc) to quit or freeze it",
                              active=(STATE_DIR / "activity-alert").exists())

        def on_alert(row, _p):
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            if row.get_active():
                (STATE_DIR / "activity-alert").write_text("")
            else:
                (STATE_DIR / "activity-alert").unlink(missing_ok=True)

        alert.connect("notify::active", on_alert)
        busy.add(alert)
        page.add(busy)
        return page

    def apply_idle(self, _button):
        values = {key: choices[row.get_selected()] for key, (row, choices) in self.idle_rows.items()}
        try:
            idle_core.save(values)
            result = sh(sys.executable, str(Path(idle_core.__file__)), "--restart")
            if result.returncode:
                self.toast(result.stderr.strip() or "Saved, but the idle service could not start")
            else:
                self.toast("Idle settings applied")
        except (OSError, ValueError, TypeError) as error:
            self.toast(f"Cannot save idle settings: {error}")

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

    # ======================================================================= Modes
    def build_modes(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import modes_core
        self.mc = modes_core
        page = Adw.PreferencesPage()
        self.modes_group = Adw.PreferencesGroup(
            title="Modes", description="One action sets up apps, VPN, power and do-not-disturb for what you are about to do, "
                                       "and puts them back when you end it. Start one with Super+Ctrl+W or from the launcher.")
        page.add(self.modes_group)
        add = Adw.PreferencesGroup()
        row = Adw.ActionRow(title="New mode…", subtitle="Research, a client, a course, gaming: whatever you do", activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        row.connect("activated", lambda *_: self.edit_mode(None))
        add.add(row)
        page.add(add)
        self.mode_rows = []
        self.refresh_modes()
        return page

    def refresh_modes(self):
        for r in self.mode_rows:
            self.modes_group.remove(r)
        self.mode_rows = []
        running = self.mc.current()
        for m in self.mc.load_modes():
            bits = [f"{len(m.get('apps', []))} app{'s' if len(m.get('apps', [])) != 1 else ''}"]
            if m.get("vpn"):
                bits.append("VPN " + m["vpn"])
            if m.get("power"):
                bits.append(self.mc.POWER[m["power"]])
            if m.get("dnd"):
                bits.append("do not disturb")
            if m.get("focus"):
                bits.append("focus session")
            row = Adw.ActionRow(title=GLib.markup_escape_text(m["name"] + ("  · running" if running and running["id"] == m["id"] else "")),
                                subtitle=" · ".join(bits))
            row.add_prefix(Gtk.Image.new_from_icon_name((m.get("icon") or "emblem-system") + "-symbolic"))
            start = Gtk.Button(label="Start", valign=Gtk.Align.CENTER, css_classes=["pill"])
            start.connect("clicked", lambda _b, i=m["id"]: spawn(str(Path(__file__).resolve().parent / "mode.sh"), "start", i))
            edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Edit")
            edit.connect("clicked", lambda _b, mm=m: self.edit_mode(mm))
            row.add_suffix(start)
            row.add_suffix(edit)
            self.modes_group.add(row)
            self.mode_rows.append(row)

    def edit_mode(self, mode):
        mc = self.mc
        new = mode is None
        mode = dict(mode or {"id": "", "name": "", "icon": "emblem-system", "ask_dir": False, "vpn": "", "power": "", "dnd": False,
                              "focus": False, "category": "Work", "apps": []})
        dialog = Adw.Dialog(title="New mode" if new else mode["name"], content_width=520, content_height=620)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        save = Gtk.Button(label="Save", css_classes=["suggested-action"])
        header.pack_start(cancel)
        header.pack_end(save)
        view.add_top_bar(header)
        page = Adw.PreferencesPage()
        main = Adw.PreferencesGroup()
        name = Adw.EntryRow(title="Name", text=mode["name"])
        main.add(name)
        ask = Adw.SwitchRow(title="Ask for a folder when it starts", subtitle="Use {dir} in a command, e.g. code {dir}", active=mode["ask_dir"])
        main.add(ask)
        page.add(main)
        sys_group = Adw.PreferencesGroup(title="Settings it changes", description="Put back when you end the mode")
        vpns = ["None"] + [f[0] for f in map(nm_fields, sh("nmcli", "-t", "-f", "NAME,TYPE", "connection", "show").stdout.splitlines())
                           if len(f) > 1 and f[1] in ("vpn", "wireguard")]
        vpn = Adw.ComboRow(title="VPN", model=Gtk.StringList.new(vpns))
        vpn.set_selected(vpns.index(mode["vpn"]) if mode["vpn"] in vpns else 0)
        powers = list(mc.POWER)
        power = Adw.ComboRow(title="Power mode", model=Gtk.StringList.new([mc.POWER[p] for p in powers]))
        power.set_selected(powers.index(mode["power"]) if mode["power"] in powers else 0)
        dnd = Adw.SwitchRow(title="Do not disturb", active=mode["dnd"])
        focus = Adw.SwitchRow(title="Start a focus session", subtitle="Counted in the time report", active=mode["focus"])
        cats = Adw.ComboRow(title="Counts as", model=Gtk.StringList.new(mc.CATEGORIES))
        cats.set_selected(mc.CATEGORIES.index(mode["category"]) if mode["category"] in mc.CATEGORIES else 0)
        for w in (vpn, power, dnd, focus, cats):
            sys_group.add(w)
        page.add(sys_group)
        apps_group = Adw.PreferencesGroup(title="Apps it opens", description="One per line: workspace | command | window class (so it is not opened twice)")
        text = Gtk.TextView(wrap_mode=Gtk.WrapMode.NONE, monospace=True, top_margin=8, bottom_margin=8, left_margin=10, right_margin=10,
                            css_classes=["card"])
        text.get_buffer().set_text(mc.apps_to_text(mode["apps"]))
        apps_group.add(Gtk.ScrolledWindow(child=text, min_content_height=120, max_content_height=180))
        page.add(apps_group)
        if not new:
            gone = Adw.PreferencesGroup()
            drop = Gtk.Button(label="Delete this mode", css_classes=["destructive-action", "pill"], halign=Gtk.Align.CENTER)
            gone.add(drop)
            page.add(gone)

            def delete(*_):
                mc.save_modes([m for m in mc.load_modes() if m["id"] != mode["id"]])
                dialog.close()
                self.refresh_modes()

            drop.connect("clicked", delete)

        def do_save(*_):
            modes = mc.load_modes()
            buf = text.get_buffer()
            mode.update(name=name.get_text().strip() or "Mode", ask_dir=ask.get_active(), vpn="" if vpn.get_selected() == 0 else vpns[vpn.get_selected()],
                        power=powers[power.get_selected()], dnd=dnd.get_active(), focus=focus.get_active(),
                        category=mc.CATEGORIES[cats.get_selected()],
                        apps=mc.text_to_apps(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)))
            if new:
                mode["id"] = mc.slug(mode["name"], {m["id"] for m in modes})
                modes.append(mode)
            else:
                modes = [mode if m["id"] == mode["id"] else m for m in modes]
            mc.save_modes(modes)
            dialog.close()
            self.refresh_modes()

        save.connect("clicked", do_save)
        cancel.connect("clicked", lambda *_: dialog.close())
        view.set_content(page)
        dialog.set_child(view)
        dialog.present(self)

    # ======================================================================= Workflow
    def build_workflow(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import workflow_core
        self.wf = workflow_core
        self.wfc = workflow_core.load()
        page = Adw.PreferencesPage()

        self.cal_group = Adw.PreferencesGroup(title="Calendars", description="Meetings from Google Calendar, Outlook or any .ics link appear in the "
                                              "Calendar and remind you before they start. Read only: nothing is sent back.")
        page.add(self.cal_group)
        self.apps_group = Adw.PreferencesGroup(title="Apps on workspaces", description="An app always opens on the workspace you choose")
        page.add(self.apps_group)
        self.snip_group = Adw.PreferencesGroup(title="Snippets", description="Text you reuse. Type its name in the launcher and it is copied")
        page.add(self.snip_group)
        backup = Adw.PreferencesGroup(title="Notes backup", description="Keeps a history of ~/Notes (a local git repository), every 30 minutes")
        self.bk_on = Adw.SwitchRow(title="Back up notes automatically", active=self.wfc["backup"]["on"])
        self.bk_push = Adw.SwitchRow(title="Also push to the remote", subtitle="Only if you added one: git remote add origin … in ~/Notes",
                                     active=self.wfc["backup"]["push"])
        self.bk_now = Adw.ActionRow(title="Back up now", subtitle="", activatable=True)
        self.bk_now.add_prefix(Gtk.Image.new_from_icon_name("document-save-symbolic"))

        def on_bk(*_):
            self.wfc["backup"] = {"on": self.bk_on.get_active(), "push": self.bk_push.get_active()}
            self.wf_save()

        def on_now(*_):
            def work():
                notes = Path(os.environ.get("PRIMO_NOTES_DIR", Path.home() / "Notes"))
                res = workflow_core.backup_notes(notes, push=self.bk_push.get_active())
                GLib.idle_add(self.bk_now.set_subtitle, res)

            import threading
            self.bk_now.set_subtitle("Working…")
            threading.Thread(target=work, daemon=True).start()

        self.bk_on.connect("notify::active", on_bk)
        self.bk_push.connect("notify::active", on_bk)
        self.bk_now.connect("activated", on_now)
        for r in (self.bk_on, self.bk_push, self.bk_now):
            backup.add(r)
        page.add(backup)
        self.wf_rows = {"cal": [], "apps": [], "snip": []}
        self.refresh_workflow()
        return page

    def wf_save(self, rules=False):
        self.wf.save(self.wfc)
        if rules:
            self.wf.write_rules(self.wfc["app_rules"])
            sh("hyprctl", "reload")
        sh("gdbus", "call", "--session", "--dest", "dev.primo.Hub", "--object-path", "/dev/primo/Hub", "--method",
           "org.gtk.Actions.Activate", "workflow-reload", "[]", "{}")

    def refresh_workflow(self):
        for key, group in (("cal", self.cal_group), ("apps", self.apps_group), ("snip", self.snip_group)):
            for r in self.wf_rows[key]:
                group.remove(r)
            self.wf_rows[key] = []

        def add(key, group, row):
            group.add(row)
            self.wf_rows[key].append(row)

        for i, feed in enumerate(self.wfc["ics"]):
            host = re.sub(r"^\w+://([^/]+).*", r"\1", feed["url"])
            row = Adw.ActionRow(title=GLib.markup_escape_text(feed.get("name") or host), subtitle=GLib.markup_escape_text(host + " · the full link is kept private"))
            row.add_prefix(Gtk.Image.new_from_icon_name("x-office-calendar-symbolic"))
            drop = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Remove")
            drop.connect("clicked", lambda _b, n=i: self.wf_remove("ics", n))
            row.add_suffix(drop)
            add("cal", self.cal_group, row)
        row = Adw.ActionRow(title="Add a calendar link…", subtitle="In Google Calendar: Settings > your calendar > Secret address in iCal format", activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        row.connect("activated", lambda *_: self.wf_add_feed())
        add("cal", self.cal_group, row)
        leads = [5, 10, 15, 30, 60]
        lead = Adw.ComboRow(title="Remind me before a meeting", model=Gtk.StringList.new([f"{m} minutes" for m in leads]))
        lead.set_selected(leads.index(self.wfc["ics_alert"]) if self.wfc["ics_alert"] in leads else 1)
        lead.connect("notify::selected", lambda r, _p: (self.wfc.update(ics_alert=leads[r.get_selected()]), self.wf_save()))
        add("cal", self.cal_group, lead)

        for i, rule in enumerate(self.wfc["app_rules"]):
            row = Adw.ActionRow(title=GLib.markup_escape_text(rule["class"]), subtitle=f"Workspace {rule['ws']}" + ("" if rule.get("silent", True) else " · switches to it"))
            drop = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Remove")
            drop.connect("clicked", lambda _b, n=i: self.wf_remove("app_rules", n))
            row.add_suffix(drop)
            add("apps", self.apps_group, row)
        row = Adw.ActionRow(title="Add an app…", subtitle="Pick one that is open now, or type its window class", activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        row.connect("activated", lambda *_: self.wf_add_rule())
        add("apps", self.apps_group, row)

        for i, sn in enumerate(self.wfc["snippets"]):
            preview = sn["text"].replace("\n", " ")[:70]
            row = Adw.ActionRow(title=GLib.markup_escape_text(sn["name"]), subtitle=GLib.markup_escape_text(preview))
            edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Edit")
            edit.connect("clicked", lambda _b, n=i: self.wf_edit_snippet(n))
            drop = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Remove")
            drop.connect("clicked", lambda _b, n=i: self.wf_remove("snippets", n))
            row.add_suffix(edit)
            row.add_suffix(drop)
            add("snip", self.snip_group, row)
        row = Adw.ActionRow(title="New snippet…", subtitle="A command, an SQL query, a reply, an address", activatable=True)
        row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        row.connect("activated", lambda *_: self.wf_edit_snippet(None))
        add("snip", self.snip_group, row)

    def wf_remove(self, key, index):
        del self.wfc[key][index]
        self.wf_save(rules=(key == "app_rules"))
        self.refresh_workflow()

    def wf_dialog(self, title, content, on_save, ok="Add"):
        dialog = Adw.AlertDialog(heading=title)
        dialog.set_extra_child(content)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", ok)
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: on_save() if r == "ok" else None)
        dialog.present(self)

    def wf_add_feed(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        name = Gtk.Entry(placeholder_text="Name, e.g. Work")
        url = Gtk.Entry(placeholder_text="https://… .ics link", width_chars=44)
        box.append(name)
        box.append(url)

        def save():
            link = url.get_text().strip()
            if not link:
                return
            self.toast("Checking the link…")

            def work():
                err = self.wf.fetch_feed(link)
                GLib.idle_add(done, err)

            def done(err):
                if err:
                    self.toast(err)
                else:
                    self.wfc["ics"].append({"name": name.get_text().strip() or "Calendar", "url": link})
                    self.wf_save()
                    self.refresh_workflow()
                    self.toast("Calendar added")
                return False

            import threading
            threading.Thread(target=work, daemon=True).start()

        self.wf_dialog("Add a calendar", box, save)

    def wf_add_rule(self):
        import json as _json
        classes = sorted({c["class"] for c in _json.loads(sh("hyprctl", "clients", "-j").stdout or "[]")
                          if c.get("class") and not c["class"].startswith("dev.primo")})
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pick = Gtk.DropDown.new_from_strings(["Type it below"] + classes)
        entry = Gtk.Entry(placeholder_text="Window class, e.g. discord")
        ws = Gtk.SpinButton.new_with_range(1, 10, 1)
        ws.set_value(3)
        silent = Gtk.CheckButton(label="Open it without switching to that workspace", active=True)
        pick.connect("notify::selected", lambda d, _p: entry.set_text(classes[d.get_selected() - 1]) if d.get_selected() > 0 else None)
        wsrow = Gtk.Box(spacing=10)
        wsrow.append(Gtk.Label(label="Workspace", xalign=0, hexpand=True))
        wsrow.append(ws)
        for w in (pick, entry, wsrow, silent):
            box.append(w)

        def save():
            cls = entry.get_text().strip()
            if cls:
                self.wfc["app_rules"] = [r for r in self.wfc["app_rules"] if r["class"] != cls] + [{"class": cls, "ws": int(ws.get_value()), "silent": silent.get_active()}]
                self.wf_save(rules=True)
                self.refresh_workflow()
                self.toast("Saved: new windows of that app open there")

        self.wf_dialog("App on a workspace", box, save)

    def wf_edit_snippet(self, index):
        sn = dict(self.wfc["snippets"][index]) if index is not None else {"name": "", "text": "", "tags": ""}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        name = Gtk.Entry(placeholder_text="Name, e.g. curl health check", text=sn["name"])
        tags = Gtk.Entry(placeholder_text="Tags (optional), e.g. sql db", text=sn.get("tags", ""))
        text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=True, top_margin=6, bottom_margin=6, left_margin=8, right_margin=8, css_classes=["card"])
        text.get_buffer().set_text(sn["text"])
        scroll = Gtk.ScrolledWindow(child=text, min_content_height=140, min_content_width=420)
        for w in (name, tags, scroll):
            box.append(w)

        def save():
            buf = text.get_buffer()
            body = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            if not name.get_text().strip() or not body.strip():
                return
            entry = {"name": name.get_text().strip(), "text": body, "tags": tags.get_text().strip()}
            if index is None:
                self.wfc["snippets"].append(entry)
            else:
                self.wfc["snippets"][index] = entry
            self.wf_save()
            self.refresh_workflow()

        self.wf_dialog("Snippet", box, save, ok="Save")

    # ======================================================================= Health
    HEALTH_ICON = {"pass": "emblem-ok-symbolic", "warning": "dialog-warning-symbolic", "fail": "dialog-error-symbolic", "skipped": "view-more-horizontal-symbolic"}
    HEALTH_CSS = {"pass": "success", "warning": "warning", "fail": "error", "skipped": "dim-label"}
    FEATURE_LABEL = {"working": ("Working", "success"), "stopped": ("Stopped", "warning"), "unavailable": ("Unavailable", "error")}

    def build_health(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import doctor_core
        self.dc = doctor_core
        page = Adw.PreferencesPage()

        top = Adw.PreferencesGroup()
        self.health_row = Adw.ActionRow(title="Checking…", subtitle="Reading the state of the desktop")
        self.health_icon = Gtk.Image(icon_name="content-loading-symbolic", pixel_size=32)
        self.health_row.add_prefix(self.health_icon)
        self.health_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER, spinning=True)
        self.health_again = Gtk.Button(label="Check again", valign=Gtk.Align.CENTER, css_classes=["pill"])
        self.health_again.connect("clicked", lambda *_: self.refresh_health())
        self.health_row.add_suffix(self.health_spinner)
        self.health_row.add_suffix(self.health_again)
        top.add(self.health_row)
        page.add(top)

        self.health_problems = Adw.PreferencesGroup(title="Needs attention", description="Each fix is a command to run yourself. Primo changes nothing from here.", visible=False)
        page.add(self.health_problems)
        self.health_features = Adw.PreferencesGroup(title="Features", description="What Primo offers and whether it works on this machine")
        page.add(self.health_features)
        self.health_checks = Adw.PreferencesGroup(title="All checks", description="The same checks as the terminal command: primo doctor")
        page.add(self.health_checks)
        self.health_rows = {"problems": [], "features": [], "checks": []}
        self.refresh_health()
        return page

    def refresh_health(self):
        import threading
        self.health_spinner.set_visible(True)
        self.health_spinner.start()
        self.health_again.set_sensitive(False)

        def work():
            results = self.dc.run_all()
            GLib.idle_add(self.apply_health, results)

        threading.Thread(target=work, daemon=True).start()

    def health_check_row(self, r, with_title=True):
        row = Adw.ActionRow(title=GLib.markup_escape_text(r.title), subtitle=GLib.markup_escape_text(r.message))
        icon = Gtk.Image(icon_name=self.HEALTH_ICON[r.status], css_classes=[self.HEALTH_CSS[r.status]])
        row.add_prefix(icon)
        if r.fix:
            copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Copy the suggested command: " + r.fix)
            copy.connect("clicked", lambda _b, cmd=r.fix: (spawn("wl-copy", "--", cmd), self.toast("Command copied")))
            row.add_suffix(copy)
        return row

    def apply_health(self, results):
        import time
        for key, group in (("problems", self.health_problems), ("features", self.health_features), ("checks", self.health_checks)):
            for r in self.health_rows[key]:
                group.remove(r)
            self.health_rows[key] = []
        self.health_spinner.stop()
        self.health_spinner.set_visible(False)
        self.health_again.set_sensitive(True)

        sm = self.dc.summary(results)
        c = sm["counts"]
        icon, css, title = {"HEALTHY": ("emblem-ok-symbolic", "success", "Everything works"),
                            "DEGRADED": ("dialog-warning-symbolic", "warning", "Needs attention"),
                            "UNHEALTHY": ("dialog-error-symbolic", "error", "Something is broken")}[sm["health"]]
        self.health_icon.set_from_icon_name(icon)
        for k in ("success", "warning", "error"):
            self.health_icon.remove_css_class(k)
        self.health_icon.add_css_class(css)
        self.health_row.set_title(title)
        bits = [f"{c['pass']} checks passed"]
        if c["warning"]:
            bits.append(f"{c['warning']} warning{'s' if c['warning'] != 1 else ''}")
        if c["fail"]:
            bits.append(f"{c['fail']} failure{'s' if c['fail'] != 1 else ''}")
        if c["skipped"]:
            bits.append(f"{c['skipped']} skipped")
        self.health_row.set_subtitle(" · ".join(bits) + f" · checked {time.strftime('%H:%M')}")

        problems = [r for r in results if r.status in ("fail", "warning")]
        problems.sort(key=lambda r: (r.status != "fail", r.category))
        self.health_problems.set_visible(bool(problems))
        for r in problems:
            row = self.health_check_row(r)
            self.health_problems.add(row)
            self.health_rows["problems"].append(row)

        for f in self.dc.feature_states(results):
            label, css = self.FEATURE_LABEL[f["state"]]
            sub = f["summary"] + (("\n" + " · ".join(f["notes"])) if f["notes"] else "")
            row = Adw.ActionRow(title=GLib.markup_escape_text(f["name"]), subtitle=GLib.markup_escape_text(sub), subtitle_lines=3)
            if f["keybind"]:
                row.add_suffix(Gtk.Label(label=f["keybind"], css_classes=["dim-label", "caption"], valign=Gtk.Align.CENTER))
            row.add_suffix(Gtk.Label(label=label, css_classes=[css, "heading"], valign=Gtk.Align.CENTER, width_chars=11, xalign=1))
            if f["page"]:
                row.set_activatable(True)
                row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                row.connect("activated", lambda _r, pid=f["page"]: self.select_page(pid))
            self.health_features.add(row)
            self.health_rows["features"].append(row)

        for cat in self.dc.CATEGORIES:
            rows = [r for r in results if r.category == cat]
            if not rows:
                continue
            bad = [r for r in rows if r.status in ("fail", "warning")]
            exp = Adw.ExpanderRow(title=cat, subtitle=f"{sum(1 for r in rows if r.status == 'pass')} ok" + (f" · {len(bad)} to look at" if bad else ""), expanded=bool(bad))
            exp.add_prefix(Gtk.Image(icon_name=self.HEALTH_ICON["fail" if any(r.status == "fail" for r in bad) else "warning" if bad else "pass"],
                                     css_classes=[self.HEALTH_CSS["fail" if any(r.status == "fail" for r in bad) else "warning" if bad else "pass"]]))
            for r in rows:
                exp.add_row(self.health_check_row(r))
            self.health_checks.add(exp)
            self.health_rows["checks"].append(exp)
        return False

    # ======================================================================= VPN
    VPN_TYPES = {"vpn": "OpenVPN", "wireguard": "WireGuard"}

    def build_vpn(self):
        page = Adw.PreferencesPage()
        if sh("sh", "-c", "command -v nmcli").returncode != 0:
            group = Adw.PreferencesGroup()
            group.add(Adw.ActionRow(title="NetworkManager is not installed", subtitle="sudo pacman -S networkmanager"))
            page.add(group)
            return page

        if sh("pacman", "-Q", "networkmanager-openvpn").returncode != 0:
            need = Adw.PreferencesGroup(title="OpenVPN is not installed")
            cmd = "sudo pacman -S openvpn networkmanager-openvpn && sudo systemctl restart NetworkManager"
            row = Adw.ActionRow(title="Install it first", subtitle=cmd)
            copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Copy the command")
            copy.connect("clicked", lambda *_: (spawn("wl-copy", cmd), self.toast("Command copied")))
            row.add_suffix(copy)
            need.add(row)
            page.add(need)

        self.vpn_status = Adw.ActionRow(title="Status", subtitle="Checking…")
        top = Adw.PreferencesGroup()
        top.add(self.vpn_status)
        page.add(top)

        self.vpn_group = Adw.PreferencesGroup(title="Connections",
                                              description="Passwords are asked by the network applet when needed")
        page.add(self.vpn_group)

        more = Adw.PreferencesGroup()
        imp = Adw.ActionRow(title="Import a .ovpn file…", subtitle="An OpenVPN profile from your provider or company", activatable=True)
        imp.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        imp.connect("activated", self.on_vpn_import)
        edit = Adw.ActionRow(title="Edit connections…", subtitle="Opens the network connection editor", activatable=True)
        edit.add_prefix(Gtk.Image.new_from_icon_name("document-edit-symbolic"))
        edit.connect("activated", lambda *_: spawn("nm-connection-editor"))
        more.add(imp)
        more.add(edit)
        page.add(more)
        self.vpn_rows = []
        self.vpn_busy = False
        self.refresh_vpn()
        GLib.timeout_add_seconds(4, self.vpn_tick)
        return page

    def vpn_tick(self):
        if not self.vpn_group.get_mapped() and getattr(self, "_vpn_seen", False):
            return True
        self._vpn_seen = True
        if not self.vpn_busy:
            self.refresh_vpn()
        return True

    def refresh_vpn(self):
        def work():
            active = {f[0] for f in map(nm_fields, sh("nmcli", "-t", "-f", "UUID", "connection", "show", "--active").stdout.splitlines())}
            conns = []
            for line in sh("nmcli", "-t", "-f", "NAME,UUID,TYPE", "connection", "show").stdout.splitlines():
                name, uuid, kind = (nm_fields(line) + ["", "", ""])[:3]
                if kind in self.VPN_TYPES:
                    conns.append((name, uuid, self.VPN_TYPES[kind], uuid in active))
            GLib.idle_add(self.apply_vpn, sorted(conns, key=lambda c: (not c[3], c[0].lower())))

        import threading
        threading.Thread(target=work, daemon=True).start()

    def apply_vpn(self, conns):
        for r in self.vpn_rows:
            self.vpn_group.remove(r)
        self.vpn_rows = []
        on = [c[0] for c in conns if c[3]]
        self.vpn_status.set_subtitle(("Connected: " + ", ".join(on)) if on else "Not connected")
        for name, uuid, kind, active in conns:
            row = Adw.ActionRow(title=GLib.markup_escape_text(name), subtitle=kind + (" · connected" if active else ""))
            row.add_prefix(Gtk.Image.new_from_icon_name("network-vpn-symbolic" if active else "network-vpn-disconnected-symbolic"))
            switch = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
            switch.connect("state-set", lambda sw, state, u=uuid, n=name: self.on_vpn_toggle(sw, state, u, n))
            drop = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Remove this connection")
            drop.connect("clicked", lambda _b, u=uuid, n=name: self.on_vpn_remove(u, n))
            row.add_suffix(switch)
            row.add_suffix(drop)
            self.vpn_group.add(row)
            self.vpn_rows.append(row)
        if not conns:
            row = Adw.ActionRow(title="No VPN connections yet", subtitle="Import a .ovpn file below")
            self.vpn_group.add(row)
            self.vpn_rows.append(row)
        return False

    def on_vpn_toggle(self, switch, state, uuid, name):
        if self.vpn_busy:
            return True
        self.vpn_busy = True
        self.toast(("Connecting to " if state else "Disconnecting from ") + name + "…")

        def work():
            r = sh("nmcli", "--wait", "60", "connection", "up" if state else "down", "uuid", uuid)
            msg = ""
            if r.returncode != 0:
                msg = (r.stderr.strip().splitlines() or ["failed"])[-1].removeprefix("Error: ")
            GLib.idle_add(self.vpn_done, msg or ("Connected to " + name if state else "Disconnected"))

        import threading
        threading.Thread(target=work, daemon=True).start()
        return False

    def vpn_done(self, msg):
        self.vpn_busy = False
        sh("pkill", "-RTMIN+13", "waybar")
        self.toast(msg)
        self.refresh_vpn()
        return False

    def on_vpn_remove(self, uuid, name):
        dialog = Adw.AlertDialog(heading=f"Remove {name}?", body="The connection and its saved settings are deleted. Your VPN provider is not affected.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def answered(_d, response):
            if response == "remove":
                sh("nmcli", "connection", "delete", "uuid", uuid)
                self.toast("Removed " + name)
                self.refresh_vpn()

        dialog.connect("response", answered)
        dialog.present(self)

    def on_vpn_import(self, *_):
        dialog = Gtk.FileDialog(title="Choose an OpenVPN profile")
        flt = Gtk.FileFilter(name="OpenVPN profiles (.ovpn)")
        flt.add_pattern("*.ovpn")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(flt)
        dialog.set_filters(store)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            if not f:
                return
            r = sh("nmcli", "connection", "import", "type", "openvpn", "file", f.get_path())
            if r.returncode == 0:
                self.toast("Imported " + Path(f.get_path()).stem)
            else:
                self.toast((r.stderr.strip().splitlines() or ["Could not import"])[-1].removeprefix("Error: "))
            self.refresh_vpn()

        dialog.open(self, None, done)

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
