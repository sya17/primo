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

## Logs

Each resident service calls `config_core.setup_logging("<name>")` once and logs through Python's `logging` (`primo.<name>`):
`LEVEL name: message` on stderr, and the same lines with a time in `~/.local/state/hyprland-dotfiles/log/<name>.log` (at most two files
of 256 KiB). The file is there because the desktop discards the stderr of the programs it starts today. Uncaught errors in GTK callbacks
and worker threads are logged with their traceback; a failure that repeats (a broken launcher source, an unreadable settings file) is
logged once. `PRIMO_DEBUG=1` adds debug lines. When the services become systemd user units (0.7.0), stderr goes to the journal
(`journalctl --user -u <unit>`) and the files can go.

## Launcher sources and the health model

`launcher_core.py` holds the launcher's logic without GTK: a registry of providers (calculator, applications, windows, actions, workspaces,
themes, clipboard, files, web) that each answer a query with results, and the command words that route a query to one of them. A provider
that raises is skipped (and logged once).
The file search runs `find` off the GTK thread through `launcher_core.FileSearch`: one child at a time and one waiting query, a newer
query or closing the window stops the running child (by its own handle, never by name), hidden folders and `node_modules` are pruned
before they are entered, and a result is shown only if it belongs to the text still in the box. `doctor_core.py` holds the feature registry (what each feature needs, which process or service shows it runs) and
the checks behind `primo doctor` and Settings > Health; both read the system through one small `System` class that tests replace with
sample data.

## Configuration

**Formats.** Settings you change in Settings (modes, workflow, activity) are JSON. New files meant to be written by hand (mode and project
definitions, in later releases) will be TOML: comments are allowed and Primo only reads them, never rewrites them. `theme.conf` and the
one-line state files (`current`, `wallpaper`, …) stay plain text because bash reads them. There is no YAML.

**Folders.** `config_core.py` finds them for every tool and follows the XDG variables (an empty or relative value is ignored):

| Folder | Default | Holds |
| --- | --- | --- |
| config | `~/.config/primo/` | `modes.json`, `workflow.json` (private: mode 0600), `activity.json`, TOML definitions |
| data | `~/.local/share/primo/` | `hub.json`: reminders, alarms, timers and the focus log |
| state | `~/.local/state/hyprland-dotfiles/` | what the desktop is doing now: theme, wallpaper, the running mode, caches |

`primo config path` lists them, `primo config show` prints the settings in effect and where each value comes from (calendar links and
snippet texts hidden), `primo config validate` checks every file. `primo doctor` and Settings > Health run the same check.

**The loader.** Tools read with `config_core.read_json` (forgiving: defaults for a broken or missing file) and save with `write_json`
or `atomic_write`; checks use `config_core.load` (strict: a `ConfigError` with the file, line and column, never the content).
A file that does not parse is copied to `<name>.bad-<time>` before anything is saved over it, and a warning goes to stderr. Saves go
through a temporary file that replaces the old one, so a crash or a full disk leaves the previous file whole. A file that cannot be read,
or that a newer Primo wrote (a `version` above the one the code knows), is never overwritten.

**Adding a file.** Put it in the right folder, add it to `config_core.FILES` (name, folder, path, list or table) so that `primo config`
and the Health check know it, read it with `read_json` (or `load` for a TOML definition) and save it with `write_json`. Give a new file
`version = 1` and keep accepting files without it. Tests set the `XDG_*` variables to temporary folders.

**Moving a file.** A move runs once, in the one process that owns the file, keeps the old file as `<name>.bak-primo`, is harmless when it
runs again, and leaves the old place in use when it cannot finish; nothing is deleted. `hub_core.migrate` (the hub data, from the
state folder to the data folder in 0.3.0) is the example. The old place stays readable for at least one release.

## Checks

`scripts/check.sh` syntax-checks scripts, Python and Lua, runs ShellCheck, renders every theme into a temporary directory, validates the
generated TOML, JSON and SVG, and runs the tests of the hub, modes, workflow helpers, config files, launcher, health checks and activity monitor. `scripts/check-docs.py` checks
that every link and image in the Markdown files exists. CI runs both in an Arch container, and checks that the commit messages follow
Conventional Commits (`scripts/check-commits.py`); see [RELEASING.md](RELEASING.md) for versions and releases.
`scripts/perf-baseline.py` (opt-in, read-only, not run in CI) measures the resident services, the Activity collector and the launcher
for before/after comparisons on one machine.
