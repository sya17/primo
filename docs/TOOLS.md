# The tools that come with Primo

Everything here is written for this setup and styled by the active theme. Most of it is Python with GTK 4 and libadwaita, and the
windows that open often (launcher, switcher, overview, time hub, activity) run as small background services so they appear instantly.

## Settings (`SUPER+,`)

A libadwaita app with these pages:

- **Appearance**: dark and light switch, and theme cards with a live palette preview.
- **Wallpaper**: a gallery of theme art and `~/Pictures`. A picture you choose survives theme switches until you press "Use the theme's
  wallpaper". Also a slideshow from a folder (every minute to every three hours), animated transitions when `awww` is installed, GIFs
  (through `awww`), videos (through `mpvpaper`, paused on battery).
- **Displays**: resolution, refresh rate, scale, rotation and arrangement for each monitor. Changes apply live and revert by themselves
  after 10 seconds unless you press Keep. Kept settings are saved to `~/.config/hypr/displays.lua` (git-ignored). It replaces
  `nwg-displays`, which writes hyprlang files the Lua config does not read.
- **Power**: Power Saver, Balanced or Performance, charge, time left, battery health, and the low-battery behaviour.
- **Bluetooth**: paired devices with Connect, Disconnect and Forget.
- **Modes**, **Workflow**, **VPN**: described below.
- **More**: shortcuts to Sound, Network, Notifications, Timeshift, Baobab and KeePassXC (only the ones that are installed).

## Launcher (`SUPER+Space`)

One search box for everything: applications ranked by how often you open them, a calculator (`12*(3+4)`, `sqrt(16)`, `15% of 80`; Enter
copies the result), system actions (lock, sleep, dark and light, night light, settings pages, modes, calendar, reminders, notes),
your snippets, files under your home folder, and a web search fallback.

## Time hub (click the clock, or `SUPER+CTRL+H`)

A floating panel under the bar clock. It does not push your windows around and it closes when you click elsewhere; the pin keeps it open
and shows it on every workspace.

- **Calendar**: a month, the plans of the day you pick, and meetings from calendar links (see Workflow).
- **Reminders**: type them in plain words, in English or Indonesian: `call the bank tomorrow 14:00 #work`, `besok jam 9 rapat`,
  `in 30m`, `standup every weekday 9:30`. Reminders repeat, can be snoozed from the notification, and are grouped as overdue, today, later.
- **Clock**: world clocks, alarms, a stopwatch with laps, and timers that keep running with the window closed.
- **Focus**: a Pomodoro with what you are working on, work hours with an end-of-day warning and break reminders, do-not-disturb while
  you focus, and your VPN switches.
- **Report**: where your focus time went (today, week, month, by category, day and label), as CSV or a Markdown summary, and a daily
  standup note built from what you finished and what is due.
- **Notes**: plain Markdown files in `~/Notes`, saved as you type, with a list beside the editor.

A background service keeps timers, alarms and reminders running while the window is closed. Its data is
`~/.local/state/hyprland-dotfiles/hub/hub.json`.

## Modes (`SUPER+CTRL+W`)

A mode is a recipe for what you are about to do: which apps open on which workspace, a VPN, a power mode, do-not-disturb and a focus
session. Ending it puts power, do-not-disturb and the VPN back (apps stay open). Work, Research, Writing and Relax are there to start
from; make your own in Settings > Modes. A mode can ask for a project folder and pass it to its apps as `{dir}`.

## Activity (`SUPER+SHIFT+Esc`, or the pulse icon in the bar)

What is running and what it costs: apps and background programs with CPU, memory, GPU, disk and connections, grouped by process tree
(a command-line tool and its helper servers show up together). Badges appear only when something really uses the microphone, camera or screen share.
Quit, force quit or freeze with a confirmation; the session itself is protected. Tabs for services and timers, and a **Dev** tab: who
holds a port, build tools and runtimes with their folder, and Docker containers (needs your user in the `docker` group). Type to search.

## Workflow (Settings > Workflow)

- **Calendars**: paste a secret `.ics` link (Google Calendar, Outlook…). Read only. Meetings appear in the Calendar and remind you before they start.
- **Apps on workspaces**: an app always opens on the workspace you choose.
- **Snippets**: text you reuse. Type its name in the launcher and it is copied.
- **Notes backup**: an automatic local history of `~/Notes` (a git repository), pushed only if you add a remote and turn that on.
- A pull-request indicator in the bar shows reviews waiting for you (needs `gh auth login`).

## Laptop

- **Power mode** (`power-profiles-daemon`): an icon in the bar cycles Power Saver, Balanced and Performance.
- **Battery watch** warns at 20% (and switches to Power Saver until you plug in), at 10%, and suspends at 4%.
- **Bluetooth** (`bluez`, `blueman`): a bar icon with the number of connected devices.
- **VPN** (NetworkManager): Settings > VPN lists your connections with a switch each, imports `.ovpn` files, and a shield appears in the
  bar while one is connected.
- **System setup**: `sudo scripts/setup-system.sh` shows the plan; `--apply` enables Bluetooth, power profiles, fast mirrors (`reflector`),
  `paccache` and a `ufw` firewall that denies incoming connections. Each edited file is backed up.

## Notifications

`swaync` gives a control center (click the bell in the bar): history, do-not-disturb, quick toggles, volume and brightness sliders and media
controls. Right-click the bell for do-not-disturb. Without swaync, dunst is used and the bell only toggles do-not-disturb.

## Files, screenshots, recordings

- **Nautilus** opens as a floating, Finder-style window on `SUPER+E`: select a file and press Space for Quick Look (`sushi`), expand folders
  in place in list view, drag to the sidebar favourites. Images and PDFs open in Loupe and Papers. `SUPER+SHIFT+E` opens Dolphin for split
  view and bulk rename. `scripts/configure-apps.sh` applies the view settings and default apps.
- **Screenshots** land in `~/Pictures/Screenshots` and on the clipboard; the notification offers Annotate (satty, with the theme's palette)
  and Show in folder.
- **Recordings** (`wf-recorder`) land in `~/Videos/Recordings`; a red timer appears in the bar and clicking it stops the recording.

## Workspaces, layouts, window rules

Each workspace has a purpose and a layout: 1 general (dwindle), 2 code (master), 3 reading and media (scrolling), 4 focus (monocle).
`SUPER+TAB`, or a click on the bar icon, cycles the layout of the current workspace. Edit the presets in `config/hypr/modules/workspaces.lua`.

Small utility apps float centred instead of tiling: pavucontrol, nm-connection-editor, blueman, Timeshift, polkit prompts and file pickers.
Firefox Picture-in-Picture floats pinned in the bottom-right corner, and fullscreen windows inhibit idle and lock. Add more in
`config/hypr/modules/rules.lua`; find a window's class with `hyprctl clients`.

## Good to know

- Clipboard history (`cliphist`) stores everything you copy, including passwords from a password manager. Wipe it with `cliphist wipe`, or
  remove the `wl-paste … cliphist store` lines in `config/hypr/modules/autostart.lua` to turn it off.
- Validate the Hyprland config with `Hyprland --verify-config -c config/hypr/hyprland.lua`.
