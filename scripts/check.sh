#!/usr/bin/env bash
# Static checks, used locally and by CI.
#
# Runs on a throw-away COPY of the repo with every XDG directory pointed at a temp folder, so it
# never touches your live config or the files theme-switch generated for your desktop.
#
# Usage: scripts/check.sh            run everything that can run on this machine
set -uo pipefail

src="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp -r "$src" "$work/repo" && rm -rf "$work/repo/.git"
cd "$work/repo"

export HOME="$work/home" XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/data" XDG_STATE_HOME="$work/state"
export PYTHONPYCACHEPREFIX="$work/pyc"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME"

fails=0
pass() { printf '  ok    %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
skip() { printf '  skip  %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "shell scripts"
while IFS= read -r f; do
    bash -n "$f" 2>/dev/null && pass "bash -n $f" || fail "bash -n $f"
done < <(find scripts config -type f -name '*.sh' ; echo scripts/theme-switch)
if have shellcheck; then
    shellcheck -S warning scripts/theme-switch scripts/*.sh config/hypr/scripts/*.sh >/dev/null 2>&1 \
        && pass "shellcheck" || fail "shellcheck (run it to see the findings)"
else skip "shellcheck not installed"; fi

echo "python"
while IFS= read -r f; do
    python3 -m py_compile "$f" 2>/dev/null && pass "$f" || fail "$f"
done < <(find scripts config -type f -name '*.py')

echo "themes render"
for conf in themes/*/theme.conf; do
    t="$(basename "$(dirname "$conf")")"
    if scripts/theme-switch --no-reload "$t" >/dev/null 2>"$work/err"; then
        left="$(grep -rIl '{{[a-z_0-9]*}}' config "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" sddm 2>/dev/null | head -3)"
        [[ -z "$left" ]] && pass "$t" || fail "$t: unresolved placeholders in $left"
    else fail "$t: $(head -1 "$work/err")"; fi
done

echo "generated files are valid"
python3 - <<PY && pass "TOML / JSON outputs" || fail "TOML / JSON outputs"
import json, re, tomllib, pathlib, os
cfg = pathlib.Path(os.environ["XDG_CONFIG_HOME"])
tomllib.loads((cfg / "starship.toml").read_text())
tomllib.loads((cfg / "satty" / "config.toml").read_text())
strip = lambda s: re.sub(r"^\s*//.*\n", "", s, flags=re.M)
json.loads(strip(pathlib.Path("config/waybar/config.jsonc").read_text()))
json.loads(pathlib.Path("config/swaync/config.json").read_text())
json.loads(strip((cfg / "fastfetch" / "config.jsonc").read_text()))
PY

echo "lua"
if have luac; then
    while IFS= read -r f; do
        luac -p "$f" 2>/dev/null && pass "luac -p $f" || fail "luac -p $f"
    done < <(find config/hypr -name '*.lua')
elif have lua; then
    while IFS= read -r f; do
        lua -e "assert(loadfile('$f'))" 2>/dev/null && pass "lua syntax $f" || fail "lua syntax $f"
    done < <(find config/hypr -name '*.lua')
else skip "lua not installed"; fi
if have Hyprland; then
    Hyprland --verify-config -c "$PWD/config/hypr/hyprland.lua" 2>&1 | grep -q "config ok" \
        && pass "Hyprland --verify-config" || skip "Hyprland --verify-config (needs a working Hyprland install)"
else skip "Hyprland not installed"; fi

echo "launcher logic"
if python3 -c 'import gi; gi.require_version("Gtk","4.0")' 2>/dev/null; then
    python3 - <<'PY' && pass "calculator and fuzzy matching" || fail "calculator and fuzzy matching"
import importlib.util
spec = importlib.util.spec_from_file_location("l", "config/hypr/scripts/launcher.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cases = {"2+2": "4", "12*(3+4)": "84", "sqrt(16)": "4", "2^10": "1024", "15% of 80": "12", "1/0": None,
         "firefox": None, "__import__('os')": None, "2**99999": None}
assert all(m.calculate(q) == v for q, v in cases.items())
assert m.fuzzy("fire", "Firefox") > 0 and m.fuzzy("fire", "File Roller") == 0
PY
else skip "python-gobject not installed"; fi

echo
(( fails == 0 )) && echo "All checks passed." || { echo "$fails check(s) failed."; exit 1; }
