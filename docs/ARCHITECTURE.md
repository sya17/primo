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

The launcher (`launcher.py`), Alt+Tab switcher (`switcher.py`), overview (`overview.py`), time hub (`hub.py`) and activity monitor
(`activity.py`) run as small background services so they open instantly. Their `.sh` wrappers start them if needed and talk to them over
D-Bus (`org.gtk.Actions.Activate`). The windows close themselves safely (focus loss, or an idle timeout). The hub also keeps timers, alarms
and reminders running while its window is closed; the activity monitor only measures while its window is open.

## Launcher sources and the health model

`launcher_core.py` holds the launcher's logic without GTK: a registry of providers (calculator, applications, windows, actions, workspaces,
themes, clipboard, files, web) that each answer a query with results, and the command words that route a query to one of them. A provider
that raises is skipped. `doctor_core.py` holds the feature registry (what each feature needs, which process or service shows it runs) and
the checks behind `primo doctor` and Settings > Health; both read the system through one small `System` class that tests replace with
sample data.

## Checks

`scripts/check.sh` syntax-checks scripts, Python and Lua, runs ShellCheck, renders every theme into a temporary directory, validates the
generated TOML, JSON and SVG, and runs the tests of the hub, modes, workflow helpers, launcher, health checks and activity monitor. `scripts/check-docs.py` checks
that every link and image in the Markdown files exists. CI runs both in an Arch container, and checks that the commit messages follow
Conventional Commits (`scripts/check-commits.py`); see [RELEASING.md](RELEASING.md) for versions and releases.
