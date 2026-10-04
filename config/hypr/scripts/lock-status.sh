#!/usr/bin/env bash
# Lock screen line about wrong passwords, from pam_faillock (a hyprlock label runs this every second).
# Prints nothing while there are no recent failures. faillock counts every wrong password for this user
# (lock screen, sudo, login), and locks the account for unlock_time after `deny` of them in fail_interval.
#
# Usage: lock-status.sh        read `faillock --user $USER`
#        lock-status.sh -      read faillock output from stdin (tests)
set -uo pipefail

conf="${FAILLOCK_CONF:-/etc/security/faillock.conf}"
get() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\([0-9]*\).*/\1/p" "$conf" 2>/dev/null | tail -n1; }
deny="$(get deny)";           deny="${deny:-3}"
unlock="$(get unlock_time)";  unlock="${unlock:-600}"
window="$(get fail_interval)"; window="${window:-900}"
now="${NOW:-$(date +%s)}"

if [[ "${1:-}" == - ]]; then out="$(cat)"; else out="$(faillock --user "$USER" 2>/dev/null)"; fi

n=0 last=0
while read -r d t; do
    s="$(date -d "$d $t" +%s 2>/dev/null)" || continue
    (( now - s <= window )) || continue
    n=$((n + 1)); (( s > last )) && last=$s
done < <(awk '$1 ~ /^[0-9]{4}-/ && $NF == "V" {print $1, $2}' <<<"$out")

(( n > 0 )) || exit 0
plural() { (( $1 == 1 )) && echo "$1 $2" || echo "$1 $2s"; }
if (( n >= deny )); then
    if (( unlock == 0 )); then echo "Locked after $(plural "$n" "wrong password"). An administrator has to unlock it (faillock --reset)."; exit 0; fi
    left=$((last + unlock - now))
    if (( left > 0 )); then
        (( left >= 60 )) && wait="$(( (left + 59) / 60 )) min" || wait="${left} s"
        echo "Locked after $(plural "$n" "wrong password"). Try again in $wait."
        exit 0
    fi
    exit 0   # the lock has expired; the next password is checked normally
fi
left=$((deny - n)); (( left == 1 )) && tries="1 try" || tries="$left tries"
echo "$(plural "$n" "wrong password"). $tries left before a $(( unlock / 60 )) min lock."
