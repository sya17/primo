# Changelog

## [0.4.0](https://github.com/sya17/primo/compare/v0.3.0...v0.4.0) (2026-10-11)

### Added

* **audio:** choose audio devices and mute the microphone in Settings ([1cd12c9](https://github.com/sya17/primo/commit/1cd12c97d1dc54414dd2a178725048806806047c))
* **control-center:** panel buttons follow the installed tools ([3322416](https://github.com/sya17/primo/commit/332241664e388db28b1b13090710aa2cb933df76))
* **launcher:** system namespaces for audio, network, capture and more ([5a25d7e](https://github.com/sya17/primo/commit/5a25d7e79f77a7ca7ff04c6dc071f05f74774f0d))
* **network:** connect and disconnect from the Network page ([f29d903](https://github.com/sya17/primo/commit/f29d903afb974736fecddcc7c52f6a221a0827d1))
* **network:** list Wi-Fi networks and saved connections in Settings ([4faac2b](https://github.com/sya17/primo/commit/4faac2b5436b3f623efe0112f07ac5b841f4e6e8))
* **overview:** search windows and group workspaces by monitor ([e68aa19](https://github.com/sya17/primo/commit/e68aa19153970ba6064c3eea86a2ab95019af493))

### Fixed

* **doctor:** stop the Health checks when the page is left ([fc209ce](https://github.com/sya17/primo/commit/fc209cedf370879c4cca4bd6496f3341a9d97a4e))
* **network:** stop an action when the network cannot be read ([06ca88a](https://github.com/sya17/primo/commit/06ca88a05ebe99b8666b3611c15ce3f67df1a70a))
* **perf:** restore the file search queries of the helper ([f0427e2](https://github.com/sya17/primo/commit/f0427e28e2321c34850bcdf2ec675d3d21c7579f))
* **proc:** stop the helpers of a bounded command with it ([2b1ccab](https://github.com/sya17/primo/commit/2b1ccab96412afde69aab41449c85908a97bbad9))
* **settings:** put displays back on close and stop losing queued changes ([6b1441b](https://github.com/sya17/primo/commit/6b1441b01ce5724fdd3698c3e2cb93ae2853505c))

### Faster

* **clipboard:** read, copy, delete and preview in the background ([1df32c4](https://github.com/sya17/primo/commit/1df32c44175b8457a983688718acd229ac6c2a2e))
* **launcher:** typing never waits for hyprctl, cliphist or the history ([4098a9d](https://github.com/sya17/primo/commit/4098a9dfe0a7401b4bfa7adbe3f21d366bbf4d9e))
* **overview:** read and act on Hyprland from workers ([03c9281](https://github.com/sya17/primo/commit/03c92818c127080d30ab9f429761de6e3eac73c9))
* **settings:** apply changes in the background, one at a time per item ([ea7dc1f](https://github.com/sya17/primo/commit/ea7dc1fdec2f99019a9c47ec4dcfe17c6d8a01d5))
* **settings:** make wallpaper previews in an owned child under limits ([b73cc52](https://github.com/sya17/primo/commit/b73cc52d67cb07c3b313c259ad425d9a02f27ad3))
* **settings:** read tools in the background so pages open at once ([871fe6f](https://github.com/sya17/primo/commit/871fe6f12519601389b8de1150371ae6ee6b2263))

## [0.3.0](https://github.com/sya17/primo/compare/v0.2.0...v0.3.0) (2026-10-09)

### Added

* **cli:** add primo config to list, show and validate settings files ([55d4513](https://github.com/sya17/primo/commit/55d451374c6238289e4ec71e96581aa32eb062d3))
* **config:** one loader with file and line errors, TOML for new files ([ac5ecce](https://github.com/sya17/primo/commit/ac5ecce5bf155d5aee914d2e4d36997eebd0c8ec))
* **doctor:** check settings files through the loader with file and line ([05cd5eb](https://github.com/sya17/primo/commit/05cd5ebe151d22dac0096d47c4428ef6334cef0f))
* **hub:** keep reminders in the data folder, moved once with a backup ([c3ff62d](https://github.com/sya17/primo/commit/c3ff62d3fc1138c42e8429fe1bf5b44bf96b9dea))

### Fixed

* **doctor:** night light and colour picker need their tool to work ([e555ac4](https://github.com/sya17/primo/commit/e555ac49cd33259dbe1770a75771da9cced578c9))

### Faster

* **activity:** collect on a worker so the window never waits ([16f7287](https://github.com/sya17/primo/commit/16f7287a79e94007e48a9c033c6568f8a6b811df))
* **launcher:** one file search at a time, pruned and stopped when stale ([84da5b2](https://github.com/sya17/primo/commit/84da5b2e5cfde0b5b34b947b204cbd0ceed1dca2))

## [0.2.0](https://github.com/sya17/primo/compare/v0.1.0...v0.2.0) (2026-10-07)

### Added

* **launcher:** hide actions whose tool is not installed ([3d1e3fb](https://github.com/sya17/primo/commit/3d1e3fb38d91785bfa7f182ea6c2ae203e3fe1f9))
* **settings:** add configurable idle times with Never option ([7054a0e](https://github.com/sya17/primo/commit/7054a0ed9914812f13dbf5b81cb8734e291ed44d))

### Fixed

* **config:** keep a copy of a broken settings file before saving over it ([4c45b11](https://github.com/sya17/primo/commit/4c45b118c39722c528b032505cb76aea1c52adf3))
* **wallpaper:** recover stopped video playback ([43ddc33](https://github.com/sya17/primo/commit/43ddc33e1e03a71098afe4e167f310674f7631b4))

### Also in this release

* `primo` command (`status`, `doctor`, `features`, all with `--json`) and Settings > Health: every feature and check, whether it
  works on this machine, and the command that fixes what does not. Read-only.
* Launcher: sources are separate providers. New: open windows, `ws 4` (workspace), `theme dusk`, `win name`, `clip text`
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
