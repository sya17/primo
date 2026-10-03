#!/usr/bin/env bash
# Symlink the configs into ~/.config, install the theme-switch helper and apply a theme.
#
# Usage: install.sh [--dry-run] [--theme NAME]
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
bin_dir="$HOME/.local/bin"
stamp="$(date +%Y%m%d-%H%M%S)"
apps=(hypr waybar wofi dunst kitty swayosd fontconfig)
theme="catppuccin-mocha"
dry=0

while (( $# )); do
    case "$1" in
        --dry-run) dry=1 ;;
        --theme)   theme="${2:?--theme needs a name}"; shift ;;
        -h|--help) sed -n '2,4p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

run() { if (( dry )); then echo "[dry-run] $*"; else "$@"; fi; }

# ---- dependencies ----
required=(Hyprland hyprpaper hyprlock hypridle cliphist wl-paste waybar wofi dunst kitty grim slurp wl-copy notify-send)
optional=(nautilus kwriteconfig6 swayosd-server hyprsunset brightnessctl playerctl wpctl nm-applet pavucontrol dolphin nwg-displays nwg-look)
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

run mkdir -p "$bin_dir"
run ln -sf "$root/scripts/theme-switch" "$bin_dir/hypr-theme"
echo "link: $bin_dir/hypr-theme"
case ":$PATH:" in *":$bin_dir:"*) ;; *) echo "note: add $bin_dir to PATH to use 'hypr-theme'" ;; esac

"$root/scripts/configure-apps.sh" >/dev/null 2>&1 || true   # file manager prefs, defaults (safe to re-run)
echo "Done. Log in to Hyprland, or run 'hyprctl reload' inside a session."
