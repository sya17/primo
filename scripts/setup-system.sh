#!/usr/bin/env bash
# One-time system setup for a laptop: Bluetooth, power profiles, fast mirrors, cache cleaning, firewall.
#
# Usage: sudo scripts/setup-system.sh           show the plan, change NOTHING (default)
#        sudo scripts/setup-system.sh --apply   do it
#
# Every step is skipped when its package is not installed, and each config file it edits is backed up
# first as <file>.bak-primo. Safe to run again.
#   sudo pacman -S power-profiles-daemon bluez bluez-utils blueman reflector pacman-contrib ufw
set -euo pipefail

apply=0
case "${1:-}" in
    "") ;;
    --apply) apply=1 ;;
    *) echo "usage: $0 [--apply]" >&2; exit 2 ;;
esac
(( ! apply || EUID == 0 )) || { echo "Run with sudo."; exit 1; }
(( apply )) && echo "Applying." || echo "Plan only: nothing will be changed. Run with --apply."

have() { pacman -Q "$1" >/dev/null 2>&1; }
step() { if (( apply )); then echo "  $*"; else echo "  would: $*"; fi; }
run() { (( apply )) && "$@" || true; }
backup() { [[ -f "$1" && ! -f "$1.bak-primo" ]] && cp -a "$1" "$1.bak-primo" || true; }

echo "== Bluetooth"
if have bluez; then
    step "enable bluetooth.service and power the adapter on at boot (AutoEnable=true)"
    if (( apply )); then
        backup /etc/bluetooth/main.conf
        if grep -qE '^\s*#?\s*AutoEnable' /etc/bluetooth/main.conf; then
            sed -i -E 's/^\s*#?\s*AutoEnable\s*=.*/AutoEnable=true/' /etc/bluetooth/main.conf
        else
            printf '\n[Policy]\nAutoEnable=true\n' >> /etc/bluetooth/main.conf
        fi
        systemctl enable --now bluetooth.service
    fi
else echo "  skip: bluez not installed"; fi

echo "== Power profiles"
if have power-profiles-daemon; then
    step "enable power-profiles-daemon.service (Power Saver / Balanced / Performance)"
    run systemctl enable --now power-profiles-daemon.service
    have tlp && echo "  WARNING: tlp is installed too; they conflict. Remove one."
else echo "  skip: power-profiles-daemon not installed"; fi

echo "== Mirrors"
if have reflector; then
    step "write /etc/xdg/reflector/reflector.conf (https, Indonesia/Singapore/Japan, 20 fastest) and enable reflector.timer"
    if (( apply )); then
        mkdir -p /etc/xdg/reflector
        backup /etc/xdg/reflector/reflector.conf
        cat > /etc/xdg/reflector/reflector.conf <<'CONF'
--save /etc/pacman.d/mirrorlist
--protocol https
--country Indonesia,Singapore,Japan
--latest 20
--sort rate
CONF
        systemctl enable --now reflector.timer
        step "rank mirrors now (backup: /etc/pacman.d/mirrorlist.bak-primo)"
        backup /etc/pacman.d/mirrorlist
        reflector @/etc/xdg/reflector/reflector.conf || echo "  reflector failed; your old mirrorlist is untouched"
    fi
else echo "  skip: reflector not installed"; fi

echo "== Package cache"
if have pacman-contrib; then
    step "enable paccache.timer (keeps the 3 latest versions of each package)"
    run systemctl enable --now paccache.timer
else echo "  skip: pacman-contrib not installed"; fi

echo "== Firewall"
if have ufw; then
    step "ufw: deny incoming, allow outgoing, enable at boot"
    step "note: Docker publishes ports outside ufw's rules; bind containers to 127.0.0.1 if that matters"
    if (( apply )); then
        ufw default deny incoming
        ufw default allow outgoing
        ufw --force enable
        systemctl enable ufw.service
    fi
else echo "  skip: ufw not installed"; fi

echo
if (( apply )); then echo "Done. Check: systemctl status bluetooth power-profiles-daemon ufw"; else echo "Nothing was changed."; fi
