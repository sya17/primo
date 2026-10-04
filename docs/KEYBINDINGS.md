# Keybindings

`SUPER` is the Windows key. Everything is in `config/hypr/modules/keybinds.lua`.

## Windows and workspaces

| Keys | Action |
| --- | --- |
| `SUPER+Q` / `SUPER+Return` | Terminal |
| `SUPER+C` | Close window. Asks first if a terminal still has a program running |
| `SUPER+SHIFT+C` | Close immediately, no confirmation |
| `SUPER+F` / `SUPER+V` | Fullscreen / toggle floating |
| `SUPER+P` / `SUPER+J` | Pseudotile / toggle split |
| `SUPER+TAB` | Next layout for this workspace (dwindle, master, scrolling, monocle) |
| `SUPER+1…0` / `SUPER+SHIFT+1…0` | Go to / move the window to a workspace |
| `SUPER+O` | Overview: every workspace and its windows. Click to focus, drag to move |
| `ALT+TAB` | Window switcher: hold Alt, tap Tab to move, release Alt to switch (a quick tap goes to the previous window) |
| `` SUPER+` `` | Drop-down terminal (floating, on a hidden workspace) |
| `SUPER+S` / `SUPER+ALT+S` | Toggle the scratchpad / move the window to it |

## Apps and tools

| Keys | Action |
| --- | --- |
| `SUPER+R` / `SUPER+Space` | Launcher: apps, calculator, actions, files, snippets, web search |
| `SUPER+,` | Settings. `SUPER+D` opens Displays, `SUPER+W` opens Wallpaper |
| `SUPER+E` | File manager: Nautilus as a floating, Finder-like window (Space = Quick Look) |
| `SUPER+SHIFT+E` | Dolphin for heavy lifting (split view, bulk rename) |
| `SUPER+CTRL+H` | Time hub: calendar, reminders, clock, focus, report, notes. Also: click the clock in the bar |
| `SUPER+CTRL+N` / `SUPER+CTRL+T` | New note / reminders |
| `SUPER+CTRL+W` | Modes: set the machine up for work, research, writing… and put it back |
| `SUPER+SHIFT+Esc` | Activity: what runs in the background and what it costs |
| `SUPER+SHIFT+V` | Clipboard history: search, Enter copies, Delete removes, images get thumbnails |
| `SUPER+CTRL+P` | Pick a colour from the screen (hex copied) |
| `SUPER+CTRL+E` / `O` / `K` / `B` | VS Code / Obsidian / KeePassXC / btop |

## Theme, screen and session

| Keys | Action |
| --- | --- |
| `SUPER+T` | Theme menu |
| `SUPER+SHIFT+T` | Toggle dark / light |
| `SUPER+N` | Toggle night light |
| `SUPER+SHIFT+S`, `Print` | Screenshot an area to the clipboard and `~/Pictures/Screenshots` (the notification offers Annotate and Show in folder) |
| `SUPER+SHIFT+A` | Screenshot an area, then annotate it |
| `SHIFT+Print` | Screenshot the whole screen |
| `SUPER+SHIFT+R` / `SUPER+CTRL+R` | Record an area / the whole screen with audio. Press again to stop (a red timer shows in the bar) |
| `SUPER+L` | Lock screen (hypridle also locks after 5 minutes) |
| `SUPER+X` | Power menu: lock, suspend, log out, restart, shut down |
| `SUPER+M` | Log out (asks first) |
