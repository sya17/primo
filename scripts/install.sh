#!/usr/bin/env bash
# Symlink the configs into ~/.config, install the theme-switch helper and apply a theme.
#
# Usage: install.sh [--dry-run] [--theme NAME]
#        install.sh --services [--dry-run]         enable Primo's systemd user units (they take over at the next login)
#        install.sh --remove-services [--dry-run]  disable them again; the autostart fallback takes over
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
bin_dir="$HOME/.local/bin"
stamp="$(date +%Y%m%d-%H%M%S)"
apps=(hypr waybar wofi dunst kitty swayosd swaync fontconfig)
theme="catppuccin-mocha"
dry=0
services=""
units=(primo-overview.service primo-launcher.service primo-switcher.service primo-activity.service primo-hub.service)   # the resident services that have a unit
declare -A unit_bus=([primo-overview.service]=dev.primo.Overview.service [primo-launcher.service]=dev.primo.Launcher.service
                    [primo-switcher.service]=dev.primo.Switcher.service [primo-activity.service]=dev.primo.Activity.service [primo-hub.service]=dev.primo.Hub.service)   # each unit and its D-Bus activation file

while (( $# )); do
    case "$1" in
        --dry-run) dry=1 ;;
        --theme)   theme="${2:?--theme needs a name}"; shift ;;
        --services) services=install ;;
        --remove-services) services=remove ;;
        -h|--help) sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

run() { if (( dry )); then echo "[dry-run] $*"; else "$@"; fi; }

# ---- systemd user units: link only what is ours, never replace a user's own file or drop-in ----
if [[ -n "$services" ]]; then
    if ! command -v systemctl >/dev/null || ! systemctl --user show-environment >/dev/null 2>&1; then
        echo "note: no systemd user manager here; the services keep starting from the Hyprland autostart"
        exit 0
    fi
    changed=0
    link_ours() {   # link_ours SRC DST
        if [[ -L "$2" && "$(readlink -f "$2")" == "$1" ]]; then echo "ok: $2 already linked"
        elif [[ -e "$2" || -L "$2" ]]; then echo "skip: $2 exists and is not Primo's; left alone"; return 1
        else run mkdir -p "$(dirname "$2")"; run ln -s "$1" "$2"; echo "link: $2 -> $1"; changed=1; fi
    }
    unlink_ours() { # unlink_ours SRC DST
        if [[ -L "$2" && "$(readlink -f "$2")" == "$1" ]]; then run rm "$2"; echo "removed: $2"; changed=1
        elif [[ -e "$2" || -L "$2" ]]; then echo "skip: $2 is not Primo's; left alone"; fi
    }
    unit_dir="$config_home/systemd/user"
    bus_dir="${XDG_DATA_HOME:-$HOME/.local/share}/dbus-1/services"
    for unit in "${units[@]}"; do
        if [[ "$services" == install ]]; then
            link_ours "$root/config/systemd/user/$unit" "$unit_dir/$unit" || continue
            link_ours "$root/config/systemd/dbus-1/services/${unit_bus[$unit]}" "$bus_dir/${unit_bus[$unit]}" || true
            run systemctl --user enable "$unit" >/dev/null 2>&1 || echo "note: could not enable $unit"
        else
            run systemctl --user disable "$unit" >/dev/null 2>&1 || true
            unlink_ours "$root/config/systemd/dbus-1/services/${unit_bus[$unit]}" "$bus_dir/${unit_bus[$unit]}"
            unlink_ours "$root/config/systemd/user/$unit" "$unit_dir/$unit"
        fi
    done
    (( changed )) && run systemctl --user daemon-reload
    [[ "$services" == install ]] && echo "Enabled for the next login; services that are running keep running until then."
    exit 0
fi

# ---- dependencies ----
required=(Hyprland hyprpaper hyprlock hypridle cliphist wl-paste waybar wofi dunst kitty grim slurp wl-copy notify-send)
optional=(awww hyprpicker power-profiles-daemon bluetoothctl blueman-manager starship eza bat fzf btop zoxide fastfetch satty wf-recorder nautilus kwriteconfig6 swayosd-server hyprsunset brightnessctl playerctl wpctl nm-applet pavucontrol dolphin nwg-displays nwg-look)
missing=(); for c in "${required[@]}"; do command -v "$c" >/dev/null || missing+=("$c"); done
if (( ${#missing[@]} )); then
    echo "Missing required commands: ${missing[*]}"
    echo "Arch: sudo pacman -S hyprland hyprpaper hyprlock hypridle cliphist waybar wofi dunst kitty grim slurp wl-clipboard libnotify"
    exit 1
fi
for c in "${optional[@]}"; do command -v "$c" >/dev/null || echo "note: optional '$c' not found"; done
fonts="$(fc-list : family)"   # capture first: grep -q + pipefail would misreport
grep -qi "nerd font\|symbols nerd" <<<"$fonts" || echo "note: no Nerd Font found; bar icons will not render (pacman -S ttf-jetbrains-mono-nerd)"
grep -qi "^inter" <<<"$fonts" || echo "note: font 'Inter' not found (pacman -S inter-font); falling back to Adwaita Sans"

[[ -d /usr/share/themes/adw-gtk3 ]] || echo "note: adw-gtk3 not found (pacman -S adw-gtk-theme); GTK apps fall back to Adwaita"
[[ -d /usr/share/icons/Papirus ]] || echo "note: Papirus icons not found (pacman -S papirus-icon-theme); using breeze icons"
python3 -c "import gi; gi.require_version('Adw', '1')" 2>/dev/null || echo "note: Primo Settings needs python-gobject and libadwaita (pacman -S python-gobject libadwaita)"
pacman -Q plasma-integration breeze >/dev/null 2>&1 || echo "note: Qt apps (Dolphin) need plasma-integration + breeze to follow the theme"

# ---- generate theme first so the symlinked dirs are complete ----
if (( dry )); then
    echo "[dry-run] $root/scripts/theme-switch --no-reload $theme"
else
    "$root/scripts/theme-switch" --no-reload "$theme"
fi

# ---- link configs, backing up anything that is not already ours ----
for app in "${apps[@]}"; do
    src="$root/config/$app"
    dst="$config_home/$app"
    if [[ -L "$dst" && "$(readlink -f "$dst")" == "$src" ]]; then
        echo "ok: $dst already linked"
        continue
    fi
    if [[ -e "$dst" || -L "$dst" ]]; then
        echo "backup: $dst -> $dst.bak-$stamp"
        run mv "$dst" "$dst.bak-$stamp"
    fi
    run mkdir -p "$config_home"
    run ln -s "$src" "$dst"
    echo "link: $dst -> $src"
done

# Launcher entry so "Settings" shows up in wofi / app menus
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
run mkdir -p "$app_dir"
if (( ! dry )); then
    printf '[Desktop Entry]\nType=Application\nName=Settings\nComment=Appearance, wallpaper and displays\nExec=python3 %s/.config/hypr/scripts/primo-settings.py\nIcon=primo\nCategories=Settings;\nTerminal=false\n' "$HOME" > "$app_dir/primo-settings.desktop"
    echo "link: $app_dir/primo-settings.desktop"
fi

run mkdir -p "$bin_dir"
run ln -sf "$root/scripts/theme-switch" "$bin_dir/hypr-theme"
echo "link: $bin_dir/hypr-theme"
run ln -sf "$root/scripts/primo" "$bin_dir/primo"
echo "link: $bin_dir/primo"
case ":$PATH:" in *":$bin_dir:"*) ;; *) echo "note: add $bin_dir to PATH to use 'hypr-theme' and 'primo'" ;; esac

"$root/scripts/configure-apps.sh" >/dev/null 2>&1 || true   # file manager prefs, defaults (safe to re-run)
command -v code >/dev/null && python3 "$root/scripts/gen-vscode-theme.py" --install >/dev/null 2>&1 && echo "VS Code: Primo themes installed" || true
echo "Done. Log in to Hyprland, or run 'hyprctl reload' inside a session."
