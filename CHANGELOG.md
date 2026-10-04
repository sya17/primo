# Changelog

## 0.1.0

First public release.

- Hyprland (Lua) configuration split into modules; spring-based animations; per-workspace layouts.
- One palette drives Hyprland, Waybar, Kitty, Wofi, swaync/dunst, swayosd, hyprlock, SDDM, GTK 3/4,
  Qt/KDE, Firefox, VS Code, starship, btop, fastfetch and satty (`scripts/theme-switch`).
- Themes: Primo Dusk / Dawn (signature pair), Catppuccin Mocha / Latte, Nord. Dark/light switch.
- Apps written for this setup: Primo Settings (appearance, wallpaper, displays), Spotlight-style
  launcher, Alt+Tab switcher, clipboard history, themed confirm dialog.
- Activity (`SUPER+SHIFT+Esc`): apps and background programs with CPU, memory, GPU, disk and connections, grouped
  by process tree (a command-line tool's helper servers show up under it); badges for microphone, camera and screen
  sharing; quit / force quit / freeze with confirmation (the session itself is protected); user and system services
  and timers; Waybar tooltip with the three busiest apps; optional warning about an app that keeps the CPU busy on battery.
- Time hub (click the bar clock, `SUPER+CTRL+H`): a dropdown with Calendar (month view, plans per day), Reminders (type
  natural text in English or Indonesian, repeats, snooze), Clock (world clocks, alarms, stopwatch, timers), Focus
  (pomodoro, work hours, end-of-day and break reminders, do-not-disturb while focusing) and Notes (Markdown files in
  `~/Notes`, autosaved, pin to keep it open). A background service keeps timers, alarms and reminders running while
  the window is closed; a running timer or focus session shows next to the bar clock.
- VPN: Settings page (connect, disconnect, import a .ovpn, remove) over NetworkManager, a shield in the bar while connected.
- Wallpaper slideshow from a folder; live wallpapers (GIF through awww, video through mpvpaper, paused on battery).
- Screenshots with annotation, screen recording with a bar timer, night light, OSD, power menu.
- Tooling: `install.sh`, `check.sh` (+ CI), `setup-shell.sh`, VS Code theme generator.
