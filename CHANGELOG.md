# Changelog

## [0.2.0](https://github.com/[secure]/primo/compare/v0.1.0...v0.2.0) (2026-10-07)

### Added

* **launcher:** hide actions whose tool is not installed ([3d1e3fb](https://github.com/[secure]/primo/commit/3d1e3fb38d91785bfa7f182ea6c2ae203e3fe1f9))
* **settings:** add configurable idle times with Never option ([7054a0e](https://github.com/[secure]/primo/commit/7054a0ed9914812f13dbf5b81cb8734e291ed44d))

### Fixed

* **config:** keep a copy of a broken settings file before saving over it ([4c45b11](https://github.com/[secure]/primo/commit/4c45b118c39722c528b032505cb76aea1c52adf3))
* **wallpaper:** recover stopped video playback ([43ddc33](https://github.com/[secure]/primo/commit/43ddc33e1e03a71098afe4e167f310674f7631b4))

## Unreleased

- `primo` command (`status`, `doctor`, `features`, all with `--json`) and Settings > Health: every feature and check, whether it
  works on this machine, and the command that fixes what does not. Read-only.
- Launcher: sources are separate providers. New: open windows, `ws 4` (workspace), `theme dusk`, `win name`, `clip text`
  (clipboard history, only when asked for).

## 0.1.0

First public release.

- Hyprland (Lua) configuration split into modules; spring-based animations; per-workspace layouts.
- One palette drives Hyprland, Waybar, Kitty, Wofi, swaync/dunst, swayosd, hyprlock, SDDM, GTK 3/4,
  Qt/KDE, Firefox, VS Code, starship, btop, fastfetch and satty (`scripts/theme-switch`).
- Themes: Primo Dusk / Dawn (signature pair), Catppuccin Mocha / Latte, Nord. Dark/light switch.
- Apps written for this setup: Primo Settings (appearance, wallpaper, displays), Spotlight-style
  launcher, Alt+Tab switcher, clipboard history, themed confirm dialog.
- Activity (`SUPER+SHIFT+Esc`): apps and background programs with CPU, memory, GPU, disk and connections, grouped
  by process tree (a command-line tool's helper servers show up under it, set per machine); badges for microphone, camera and screen
  sharing; quit / force quit / freeze with confirmation (the session itself is protected); user and system services
  and timers; Waybar tooltip with the three busiest apps; optional warning about an app that keeps the CPU busy on battery.
- Time hub (click the bar clock, `SUPER+CTRL+H`): a dropdown with Calendar (month view, plans per day), Reminders (type
  natural text in English or Indonesian, repeats, snooze), Clock (world clocks, alarms, stopwatch, timers), Focus
  (pomodoro, work hours, end-of-day and break reminders, do-not-disturb while focusing) and Notes (Markdown files in
  `~/Notes`, a list beside the editor, autosaved). The dropdown is wide and low, floats over your windows instead of pushing
  them, closes when you switch workspace, and the pin button keeps it open and shows it on every workspace. A background service keeps timers, alarms and reminders running while
  the window is closed; a running timer or focus session shows next to the bar clock.
- Modes (`SUPER+CTRL+W`): your own recipes (apps on workspaces, VPN, power mode, do-not-disturb, a focus session); ending
  one puts the settings back. Work, Research, Writing and Relax to start from. Not tied to one project.
- Time report: focus sessions say what you work on; a Report tab (today, week, month; by category, day, label), CSV and
  Markdown export, and a daily standup note built from what you finished and what is due.
- Activity > Dev: who holds a port, build tools and runtimes with their folder, Docker containers (start, stop, logs).
- Settings > Workflow: calendar links (ICS) with reminders before meetings, which workspace an app opens on, snippets
  (type the name in the launcher to copy), automatic history of `~/Notes`. A pull-request indicator in the bar (`gh`).
- VPN: Settings page (connect, disconnect, import a .ovpn, remove) over NetworkManager, a shield in the bar while connected.
- Wallpaper slideshow from a folder; live wallpapers (GIF through awww, video through mpvpaper, paused on battery).
- Screenshots with annotation, screen recording with a bar timer, night light, OSD, power menu.
- Primo logo everywhere the system showed one: the bar button (was the Arch glyph), fastfetch (was the Arch logo), the
  boot splash and the Settings icon; a small mark at the bottom of the lock and login screens. Drawn in the theme's
  colours (`templates/logo/`).
- Lock and login screens: their own background (blurred windows, the desktop wallpaper, or a picture, GIF or video)
  in Settings > Wallpaper; the lock screen says how many wrong passwords were typed and how long the faillock wait is.
- Tooling: `install.sh`, `check.sh` (+ CI), `setup-shell.sh`, VS Code theme generator.
