#!/usr/bin/env bash
# Install the Primo boot splash (Plymouth): a gradient ring with pulsing dots.
#
# Usage: sudo scripts/install-boot-splash.sh              show the plan, change NOTHING (default)
#        sudo scripts/install-boot-splash.sh --apply      do it
#        sudo scripts/install-boot-splash.sh --uninstall  put everything back
#
# What --apply touches (each file is backed up first as <file>.bak-primo):
#   /etc/mkinitcpio.conf     adds the `plymouth` hook after `udev`
#   /boot/loader/entries/*.conf (systemd-boot) or /etc/default/grub (GRUB): adds `quiet splash`
#                            the *fallback* entry is left alone, so you can always boot verbosely
#   /usr/share/plymouth/themes/primo   the theme
# then rebuilds the initramfs with `mkinitcpio -P`. If that fails, your files are restored.
#
# If a boot ever misbehaves: pick the "fallback" entry in the boot menu, then run --uninstall.
# Prerequisite: `sudo pacman -S plymouth`.
set -euo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
theme_src="$root/boot/plymouth/primo"
theme_dst="/usr/share/plymouth/themes/primo"
mkconf="/etc/mkinitcpio.conf"
mode=plan
case "${1:-}" in
    "") ;;
    --apply) mode=apply ;;
    --uninstall) mode=uninstall ;;
    *) echo "usage: $0 [--apply|--uninstall]" >&2; exit 2 ;;
esac

say()  { printf '%s\n' "$*"; }
step() { if [[ $mode == plan ]]; then say "  would: $*"; else say "  $*"; fi; }
do_it() { [[ $mode == plan ]] || "$@"; }

[[ $mode == plan || $EUID -eq 0 ]] || { say "Run with sudo."; exit 1; }
command -v mkinitcpio >/dev/null || { say "mkinitcpio not found: this script is for Arch-style systems."; exit 1; }

backup() { [[ -f "$1.bak-primo" ]] || cp -a "$1" "$1.bak-primo"; }

# ---- which boot loader
loader=unknown
if   [[ -d /boot/loader/entries ]]; then loader=systemd-boot
elif [[ -f /etc/default/grub ]];     then loader=grub
elif [[ $EUID -ne 0 ]];              then loader="unknown (/boot is only readable by root)"
fi
say "Mode: $mode | boot loader: $loader"

# ================================================================== uninstall
if [[ $mode == uninstall ]]; then
    for f in /boot/loader/entries/*.conf.bak-primo /etc/default/grub.bak-primo; do
        [[ -f "$f" ]] && { cp -a "$f" "${f%.bak-primo}"; rm -f "$f"; step "restored ${f%.bak-primo}"; }
    done
    [[ -f "$mkconf.bak-primo" ]] && { cp -a "$mkconf.bak-primo" "$mkconf"; rm -f "$mkconf.bak-primo"; step "restored $mkconf"; }
    mkinitcpio -P
    [[ -f /boot/grub/grub.cfg ]] && command -v grub-mkconfig >/dev/null && grub-mkconfig -o /boot/grub/grub.cfg
    rm -rf "$theme_dst"
    say "Uninstalled. Reboot to see the normal boot messages again."
    exit 0
fi

# ================================================================== checks
command -v plymouth-set-default-theme >/dev/null || { say "Plymouth is not installed: sudo pacman -S plymouth"; exit 1; }
[[ -f "$theme_src/primo.script" ]] || { say "Theme missing. Run: python3 scripts/gen-plymouth-theme.py"; exit 1; }
[[ -r $mkconf ]] || { say "Cannot read $mkconf"; exit 1; }
hooks="$(grep -E '^HOOKS=' "$mkconf" || true)"
[[ -n "$hooks" ]] || { say "No HOOKS= line found in $mkconf: aborting without changes."; exit 1; }
[[ $hooks == *udev* || $hooks == *plymouth* ]] || { say "HOOKS has no 'udev' (systemd-style hooks?). Add 'plymouth' after 'systemd' by hand."; exit 1; }
say "HOOKS now: $hooks"

# ================================================================== plan / apply
say "Steps:"
step "copy the theme to $theme_dst and make it the default (without rebuilding yet)"
do_it mkdir -p "$theme_dst"
do_it cp -a "$theme_src"/. "$theme_dst"/
do_it plymouth-set-default-theme primo

if [[ $hooks == *plymouth* ]]; then
    step "$mkconf already has the plymouth hook (skip)"
else
    step "back up $mkconf and add 'plymouth' after 'udev' in HOOKS"
    if [[ $mode == apply ]]; then
        backup "$mkconf"
        sed -i '/^HOOKS=/ s/\budev\b/udev plymouth/' "$mkconf"
        grep -E '^HOOKS=' "$mkconf" | grep -q plymouth || { cp -a "$mkconf.bak-primo" "$mkconf"; say "Edit failed, restored."; exit 1; }
    fi
fi

case "$loader" in
    systemd-boot)
        for f in /boot/loader/entries/*.conf; do
            [[ $f == *fallback* ]] && { step "leave $f alone (fallback)"; continue; }
            if grep -qE '^options .*\bsplash\b' "$f"; then step "$f already has splash (skip)"; continue; fi
            step "back up $f and add 'quiet splash' to its options"
            if [[ $mode == apply ]]; then
                backup "$f"
                sed -i '/^options / { /\bquiet\b/! s/$/ quiet/ ; /\bsplash\b/! s/$/ splash/ }' "$f"
            fi
        done ;;
    grub)
        if grep -qE '^GRUB_CMDLINE_LINUX_DEFAULT=.*splash' /etc/default/grub; then step "GRUB already has splash (skip)"
        else
            step "back up /etc/default/grub, add 'quiet splash', run grub-mkconfig"
            if [[ $mode == apply ]]; then
                backup /etc/default/grub
                sed -i -E '/^GRUB_CMDLINE_LINUX_DEFAULT=/ { /\bquiet\b/! s/"$/ quiet"/ ; /\bsplash\b/! s/"$/ splash"/ }' /etc/default/grub
                grub-mkconfig -o /boot/grub/grub.cfg
            fi
        fi ;;
    *) step "NOTE: boot loader not recognised: add 'quiet splash' to your kernel command line yourself" ;;
esac

step "rebuild the initramfs: mkinitcpio -P"
if [[ $mode == apply ]]; then
    if ! mkinitcpio -P; then
        say "mkinitcpio FAILED: restoring $mkconf"
        [[ -f "$mkconf.bak-primo" ]] && cp -a "$mkconf.bak-primo" "$mkconf" && mkinitcpio -P || true
        exit 1
    fi
    say "Done. Reboot to see it. Undo any time: sudo $0 --uninstall"
else
    say "Nothing was changed. Run with --apply to do it."
fi
