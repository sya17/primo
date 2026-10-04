# Theming

One theme file drives everything. `scripts/theme-switch` reads `themes/<name>/theme.conf` and renders a template for every app, then
reloads whatever is running.

```bash
hypr-theme --list        # name and mode (dark or light)
hypr-theme dark          # the theme last used in dark mode; light and toggle work the same way
hypr-theme toggle        # SUPER+SHIFT+T
hypr-theme nord          # any theme by name
hypr-theme --current
```

Bundled: **Primo Dusk** (dark) and **Primo Dawn** (light), the signature pair: compact and crisp, periwinkle with a coral spark.
Also Catppuccin Mocha, Catppuccin Latte and Nord. `dark` and `light` apply the last theme you used in that mode, and the GTK
`color-scheme` is switched too.

## Make your own

Copy `themes/catppuccin-mocha` to `themes/<name>` and edit `theme.conf` (set `mode=dark` or `mode=light`). Shape lives in the theme too:
`rounding`, `gaps_*`, `bar_radius` (999 = pill) and `input_rounding`. `wallpaper_style=lines` adds flowing contour lines to the generated
wallpaper; set `wallpaper=` to a file in the theme folder, otherwise `~/Pictures/wallpaper.jpg` is used. The bundled wallpapers are
generated from each palette (`scripts/gen-wallpaper.py <theme> [WIDTHxHEIGHT]`, styles `gradient` and `lines`) and are MIT-licensed.

To theme another app, add a template under `templates/` and one `render` line in `scripts/theme-switch`.

The Primo mark follows the theme: the bar button, the lock and login screens, the Settings icon (`primo`), fastfetch and the boot splash
draw it in `logo` (accent on dark themes, text colour on light ones) and `logo_accent` (accent2). A theme may set both.

## GTK and Qt apps

- **GTK 3 and 4** (pavucontrol, nwg-look, file pickers…): `adw-gtk3` with named colours in `~/.config/gtk-{3,4}.0/gtk.css`, plus
  `settings.ini` and `gsettings` (theme, icons, font).
- **Qt and KDE** (Dolphin…): a KDE colour scheme (`Primo.colors`) merged into `kdeglobals`, the Breeze style and Papirus icons. Needs
  `plasma-integration` and `QT_QPA_PLATFORMTHEME=kde` (set in `modules/env.lua`; log in again after the first install).
- **KeePassXC** is still a Qt 5 app, so it follows dark and light through its own setting instead of the palette.

These files live in `~/.config` and `~/.local/share`, not in the repo. A file that `theme-switch` did not write is backed up once as
`*.bak-primo`. Do not change the theme with `nwg-look`: pick it with `SUPER+T`, or it is overwritten on the next switch.

## Terminal

`starship`, `fzf`, `btop` and `fastfetch` take their colours from the active theme and change with it. `scripts/setup-shell.sh` adds one
block to `~/.bashrc` (and `--remove` takes it out); nothing else in the file is touched and a one-time backup is kept.

## Editors

`python3 scripts/gen-vscode-theme.py --install` turns every theme into a **VS Code** colour theme (Primo Dusk, Primo Dawn, Catppuccin,
Nord) and, when you have no `settings.json` yet, writes a starter one that follows the desktop's dark and light mode
(`window.autoDetectColorScheme`). `install.sh` runs it when `code` is installed.

## Firefox

`theme-switch` writes `userChrome.css` and `userContent.css` into the profile your Firefox uses (read from `installs.ini`; set
`FIREFOX_PROFILE=/path` to pick another) and enables `toolkit.legacyUserProfileCustomizations.stylesheets` in `user.js`. **Restart Firefox**
after switching themes: it reads these files at startup. Toolbar, tabs, address bar, menus and the new-tab page follow the palette and the
theme's corner radius. `scripts/firefox-theme.sh off|on` switches the styling off and on.

## Login screen and boot splash

`sudo scripts/install-sddm-theme.sh` copies the Primo login theme with the active palette and wallpaper (re-run it after switching themes if
the login screen should follow). The cursor (white on dark themes, black on light) and fonts (Inter, JetBrainsMono Nerd Font, Noto Color Emoji)
are set system-wide by `theme-switch` and `config/fontconfig`.

The optional boot splash (Plymouth) is a gradient ring with pulsing dots drawn from the palette. See [INSTALL.md](INSTALL.md#optional-extras).
Every file the installer touches is backed up first, the fallback boot entry is left alone, and a failed `mkinitcpio` restores your config.
