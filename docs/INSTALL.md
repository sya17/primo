# Install

Primo is made for **Arch Linux with Hyprland 0.55 or newer** (the Lua configuration). It is developed and tested on Arch with
Hyprland 0.56 on a single laptop (AMD graphics, one internal screen); see [what is tested](../README.md#what-is-tested).

## 1. Packages

This is the full set the repo was built with. Remove what you do not use; the helper scripts leave an app alone when it is not installed.

```bash
sudo pacman -S hyprland hyprpaper hyprlock hypridle cliphist waybar wofi dunst kitty grim slurp wl-clipboard libnotify \
               brightnessctl playerctl swayosd hyprsunset swaync starship eza bat fzf btop zoxide fastfetch satty wf-recorder \
               power-profiles-daemon bluez bluez-utils blueman reflector pacman-contrib ufw timeshift keepassxc \
               telegram-desktop qbittorrent baobab noto-fonts-cjk awww hyprpicker jq pavucontrol network-manager-applet \
               polkit-kde-agent ttf-jetbrains-mono-nerd inter-font capitaine-cursors noto-fonts-emoji adw-gtk-theme \
               papirus-icon-theme breeze plasma-integration kde-cli-tools \
               nautilus sushi file-roller gvfs gvfs-smb gvfs-mtp ffmpegthumbnailer loupe papers libheif webp-pixbuf-loader
```

Primo's own tools (Settings, launcher, time hub, activity, modes) are Python with GTK 4 and libadwaita: `python-gobject` and
`libadwaita` come with Nautilus.

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
| Wallpapers that move | `yay -S mpvpaper` | GIFs work with `awww`; videos need `mpvpaper`. |
