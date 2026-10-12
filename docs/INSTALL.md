# Install

Primo is made for **Arch Linux with Hyprland 0.55 or newer** (the Lua configuration). It is developed and tested on Arch with
Hyprland 0.56 on a single laptop (AMD graphics, one internal screen); see [what is tested](../README.md#what-is-tested).

## 1. Packages

This is the full set the repo was built with. Remove what you do not use; the helper scripts leave an app alone when it is not installed.

```bash
sudo pacman -S hyprland hyprpaper hyprlock hypridle cliphist waybar wofi dunst kitty grim slurp wl-clipboard libnotify \
               brightnessctl playerctl swayosd hyprsunset swaync starship eza bat fzf btop zoxide fastfetch satty wf-recorder \
               power-profiles-daemon bluez bluez-utils blueman reflector pacman-contrib ufw timeshift keepassxc \
               telegram-desktop qbittorrent baobab noto-fonts-cjk awww hyprpicker jq pavucontrol network-manager-applet networkmanager libpulse \
               polkit-kde-agent ttf-jetbrains-mono-nerd inter-font capitaine-cursors noto-fonts-emoji adw-gtk-theme \
               papirus-icon-theme breeze plasma-integration kde-cli-tools \
               nautilus sushi file-roller gvfs gvfs-smb gvfs-mtp ffmpegthumbnailer loupe papers libheif webp-pixbuf-loader
```

Primo's own tools (Settings, launcher, time hub, activity, modes) are Python with GTK 4 and libadwaita: `python-gobject` and
`libadwaita` come with Nautilus.

Some controls depend on one program each and are hidden (or say what is missing) when it is not installed, in Settings, the notification
panel and the launcher alike; `primo features` and Settings > Health list them:

| Control | Needs | Optional |
| --- | --- | --- |
| Network page, `network` in the launcher | `nmcli` (`networkmanager`) | `nm-connection-editor` and `nm-applet` (`network-manager-applet`): company or school sign-in, password prompts |
| Audio page, microphone mute, `audio` in the launcher | `pactl` (`libpulse`, served by PipeWire or PulseAudio) | `pavucontrol`: the full mixer |
| Screenshots and `capture` | `grim`, `slurp` (the copy to the clipboard uses `wl-copy` from `wl-clipboard`) | `satty` (annotate), `wf-recorder` (recording) |

## 2. Try it first

```bash
git clone https://github.com/sya17/primo.git && cd primo
./scripts/install.sh --dry-run --theme primo-dusk      # prints what it would do, changes nothing
```

## 3. Install

```bash
./scripts/install.sh --theme primo-dusk                # or primo-dawn, catppuccin-mocha, catppuccin-latte, nord
```

What it does, and nothing else:

- Links `config/<app>` to `~/.config/<app>` for hypr, waybar, wofi, dunst, kitty, swayosd, swaync and fontconfig.
  A directory that was already there is **moved** to `<app>.bak-<timestamp>`, not deleted.
- Links `hypr-theme` into `~/.local/bin` and renders the chosen theme. Generated files (`theme.lua`, `style.css`, `hyprpaper.conf`…) land
  in the linked folders and are git-ignored; the GTK, Qt, Firefox and VS Code files go to `~/.config` and `~/.local/share`.
- Writes a `primo-settings.desktop` launcher entry, applies the app settings (`scripts/configure-apps.sh`) and, if `code` is installed,
  adds the VS Code themes.

Log out and in once after the first install (Qt apps read `QT_QPA_PLATFORMTHEME=kde` from the session).

## Put it back

Delete the links in `~/.config` and move your `<app>.bak-<timestamp>` folders back. Files the theme tools changed outside the links are
backed up once as `*.bak-primo` the first time they are touched. Each optional script below has its own `--uninstall` or `--remove`.

## Before you update

Primo updates by `git pull` in its folder; nothing updates it for you. Three read-only helpers make that safer:

```bash
primo snapshot                  # copy your Primo settings aside (add --dry-run to see what it takes; --include-sensitive adds calendar links and snippets)
primo update check              # is the checkout ready for a pull? (--remote also asks GitHub what the latest release is)
git pull                        # you run this
primo doctor                    # afterwards: anything broken? `primo doctor --repair ID` shows what Primo can fix
```

If settings go wrong afterwards, `primo restore ID` previews what a snapshot would change and `primo restore ID --apply` puts it back, with a journal you can undo.
A snapshot covers your Primo settings only: not the repository, your packages or the rest of your home folder.

## Optional: run the services under systemd

By default Hyprland starts the resident services (launcher, switcher, overview, activity, time hub) at login and nothing restarts one that
crashes until you use its shortcut. With systemd user units a crashed service comes back (at most three starts a minute), and Doctor shows how each one is doing.

```bash
./scripts/install.sh --services --dry-run     # prints what it would link and enable
./scripts/install.sh --services               # links the units, enables them for the next login
./scripts/install.sh --remove-services        # disables them and removes the links
```

- It links `config/systemd/user/primo-*.service` into `~/.config/systemd/user` and a D-Bus activation file per service into `~/.local/share/dbus-1/services`.
  A file or drop-in of yours with the same name is left alone and reported. It never starts or stops a running service; the units take over at the next login.
- While a unit is enabled, the Hyprland autostart and the shortcut wrappers do not start that service themselves; without a unit they start it as before.
  A machine without a systemd user manager keeps working exactly as it did.
- After `git pull` the units are the updated files (they are links), but systemd reads them again only after `systemctl --user daemon-reload`.
- Where to look: `systemctl --user status primo-launcher.service`, `journalctl --user -u primo-launcher.service`, `primo doctor --category services`,
  and the service's own log in `~/.local/state/hyprland-dotfiles/log/<service>.log`.
- A service that finds no display or session bus exits with status 69 and is not restarted; fix the session, then use its shortcut or `systemctl --user start`.
- The time hub keeps reminders, alarms and timers in its data file, so a restart loses none of them; see "Resident services" in `docs/ARCHITECTURE.md`.

## Optional extras

| What | Command | Notes |
| --- | --- | --- |
| Per-machine settings | `~/.config/hypr/local.lua` | Git-ignored, loaded last. For monitors and devices. |
| Shell | `scripts/setup-shell.sh` | Prompt, fzf, zoxide, eza and bat aliases, btop theme. Adds one block to `~/.bashrc`; `--remove` undoes it. |
| Laptop and system | `sudo scripts/setup-system.sh` | Shows the plan; `--apply` enables Bluetooth, power profiles, fast mirrors, cache cleaning and a firewall. Every edited file is backed up. |
| Login screen | `sudo scripts/install-sddm-theme.sh` | Preview first with `sddm-greeter --test-mode --theme /usr/share/sddm/themes/primo`. `--uninstall` undoes it. |
| Boot splash | `sudo scripts/install-boot-splash.sh` | Shows the plan; `--apply` changes the initramfs. Keep a recovery USB at hand: this part cannot be verified from inside a session. |
| Lock and Caps Lock indicator | `sudo scripts/enable-lock-osd.sh` | Adds an on-screen indicator. |
| Firefox styling | `scripts/firefox-theme.sh off\|on` | Compare with stock Firefox. |
| VS Code profiles | [docs/vscode-profiles/README.md](vscode-profiles/README.md) | Eight import files (Spring Boot, Flutter, Nuxt, Next.js, Python, Rust, Go, General) with the Primo look. |
| Wallpapers that move | `yay -S mpvpaper` | GIFs work with `awww`; videos need `mpvpaper`. |
