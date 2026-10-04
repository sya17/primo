# How it fits together

One theme file drives everything. `scripts/theme-switch <theme>` reads `themes/<theme>/theme.conf`
(palette, fonts, shape), fills the `{{placeholders}}` in `templates/`, writes the results where each
app expects them, then reloads whatever is running.

```text
themes/<name>/theme.conf ──► templates/<app>/*.tpl ──► generated files ──► reload
        palette, fonts,                                  repo: config/<app>/…   (git-ignored)
        shape, mode                                      ~/.config, ~/.local/…  (GTK, Qt, Firefox, …)
```

## Layout

| Path | What |
| --- | --- |
| `config/` | Hand-written configs, symlinked into `~/.config` by `scripts/install.sh` (hypr, waybar, wofi, dunst, kitty, swaync, swayosd, fontconfig). |
| `config/hypr/modules/` | Hyprland Lua config, one concern per file (`keybinds`, `rules`, `animations`, …). |
| `config/hypr/scripts/` | Runtime tools: launcher, Alt+Tab switcher, clipboard, settings, confirm dialog, screenshot, recorder, … |
| `templates/` | One folder per themed app. Placeholders: `{{base}}`, `{{accent_rgb}}`, `{{rounding}}`, … |
| `themes/` | `theme.conf` + `wallpaper.png` per theme. |
| `scripts/` | Tooling: `install.sh`, `theme-switch`, `check.sh`, `setup-shell.sh`, `gen-*`. |
| `sddm/primo/` | Login-screen theme (core QtQuick only, so the Qt5 greeter loads it). |

## Placeholders

`theme-switch` exposes every key of `theme.conf`, plus derived values:
`<colour>_rgb` (`r, g, b`), `<colour>_sgr` (`r;g;b`), `view`, `menu_radius`, `cursor_theme`,
`gtk_theme`, `icon_theme`, `wallpaper_path`. A template that uses an unknown placeholder makes
`theme-switch` fail before anything is written.

## Add a theme

Copy a folder in `themes/`, edit `theme.conf` (keep `mode=dark|light`), then
`scripts/gen-wallpaper.py <name>` for its wallpaper and `hypr-theme <name>`.

## Add a themed app

1. Write `templates/<app>/<file>.tpl` using the placeholders.
2. Add a `render` (repo-local) or `render_external` (outside the repo, backs up foreign files) line in
   `scripts/theme-switch`, and a reload line at the bottom if the app can reload live.
3. Git-ignore the generated file.

## Resident services

The launcher (`launcher.py`) and Alt+Tab switcher (`switcher.py`) run as small background services so
they open instantly. Their `.sh` wrappers start them if needed and talk to them over D-Bus
(`org.gtk.Actions.Activate`). Both close themselves safely (focus loss / idle timeout).

## Checks

`scripts/check.sh` syntax-checks scripts, Python and Lua, renders every theme into a temporary
directory and validates the generated TOML/JSON. CI runs it in an Arch container.
