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
cd "$work/repo" || exit 1

export HOME="$work/home" XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/data" XDG_STATE_HOME="$work/state"
export PYTHONPYCACHEPREFIX="$work/pyc"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME"
# Anything that would reach the running desktop goes to a log instead; the last check fails if it is not empty.
mkdir -p "$work/bin"; export LIVE_LOG="$work/live-calls"; : > "$LIVE_LOG"
for c in hyprctl pkill gsettings dunstctl swaync-client swayosd-server setsid notify-send; do
    printf '#!/bin/sh\necho "%s $*" >> "$LIVE_LOG"\n' "$c" > "$work/bin/$c"; chmod +x "$work/bin/$c"
done
export PATH="$work/bin:$PATH" PRIMO_NO_RELOAD=1 PRIMO_LOGIN_DIR="$work/login"

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
python3 scripts/test-idle.py && pass "idle settings and Never" || fail "idle settings"
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

echo "activity"
mkdir -p "$XDG_CONFIG_HOME/primo"
echo '{"lift": {"devtool": "Dev Tool"}, "helpers": ["lang-server"], "helpers_label": "Servers"}' > "$XDG_CONFIG_HOME/primo/activity.json"
python3 - <<'PY' && pass "Activity groups apps, lifts a tool's helper servers under it, protects the session" || fail "Activity collector"
import sys
sys.path.insert(0, "config/hypr/scripts")
import activity_collect as ac
P = lambda pid, ppid, comm, cmd=(): ac.Proc(pid, ppid, comm, "S", ac.ME, pid, 0, 1 << 20, list(cmd), pss=1 << 20)
procs = {p.pid: p for p in (
    P(10, 1, "Hyprland"), P(11, 10, "kitty"), P(12, 11, "zsh"),
    P(13, 12, "devtool"), P(14, 13, "uv", ["uv", "tool", "uvx", "lang-server", "start"]), P(15, 14, "python", ["python", "lang-server"]),
    P(16, 10, "waybar"))}
s = ac.Sampler()
groups = {g.name: g for g in ac.group_apps(procs, s, {11: [{"class": "kitty", "title": "t", "address": "0x1", "workspace": 1}]})}
assert "Dev Tool" in groups and "Servers: lang-server" in groups["Dev Tool"].doing, (groups.keys(), groups.get("Dev Tool"))
assert 15 in groups["Dev Tool"].pids and 15 not in groups["kitty"].pids
assert groups["kitty"].kind == "app" and groups["waybar"].kind == "bg"
assert ac.signal_group(ac.Group(key="x", name="Hyprland", kind="bg", leaders=[10], protected=True), 0) == 0
rows = ac.parse_listening('tcp LISTEN 0 100 127.0.0.1:8080 0.0.0.0:* users:(("java",pid=42,fd=9))\ntcp LISTEN 0 1 *:5432 *:*\ntcp ESTAB 0 0 1.1.1.1:5 2.2.2.2:6 users:(("x",pid=3,fd=1))')
assert [(r["port"], r["pid"]) for r in rows] == [(8080, 42), (5432, 0)], rows
dev = {p.pid: p for p in (P(1, 0, "java"), P(2, 1, "mvn"), P(3, 0, "python3", ["python3", "hub.py"]), P(4, 0, "python3", ["python3", "-m", "http.server"]),
                          P(5, 0, "node", ["node", "srv.js"]))}
names = sorted(p.comm + str(p.pid) for p in ac.dev_processes(dev, port_pids={5}))
assert names == ["java1", "node5", "python34"], names     # a plain script is not a dev process; one on a port or a dev server is; a tool under another tool is shown once
assert ac.parse_containers('{"ID":"a","Names":"db","Image":"pg","Status":"Up","State":"running","Ports":""}\nnoise')[0]["name"] == "db"
PY

echo "time hub"
python3 scripts/test-hub-core.py >"$work/hub.out" 2>&1 && pass "reminder parsing, alarms, work hours, pomodoro, storage" || { fail "time hub core"; head -8 "$work/hub.out"; }

if python3 scripts/test-hub-service.py >"$work/hubsvc.out" 2>&1; then
    if grep -q '^skip' "$work/hubsvc.out"; then skip "time hub service (needs a display)"; else pass "time hub: reminders, alarms, timers, focus, work day, notes"; fi
else fail "time hub service"; tail -8 "$work/hubsvc.out"; fi

echo "modes"
python3 scripts/test-modes.py >"$work/modes.out" 2>&1 && pass "modes: start sets things up, end puts them back" || { fail "modes"; tail -6 "$work/modes.out"; }

echo "workflow"
python3 scripts/test-workflow.py >"$work/wf.out" 2>&1 && pass "calendar feeds, app workspace rules, snippets, notes backup" || { fail "workflow helpers"; tail -6 "$work/wf.out"; }

echo "launcher and health"
python3 scripts/test-launcher.py >"$work/launcher.out" 2>&1 && pass "launcher sources: calculator, windows, workspaces, themes, clipboard only on request" || { fail "launcher"; tail -6 "$work/launcher.out"; }
python3 scripts/test-doctor.py >"$work/doctor.out" 2>&1 && pass "health checks and the primo command" || { fail "doctor"; tail -6 "$work/doctor.out"; }

echo "commit messages"
python3 scripts/test-commits.py >"$work/commits.out" 2>&1 && pass "commit message format (Conventional Commits) is enforced" || { fail "commit message linter"; tail -6 "$work/commits.out"; }
python3 - <<'PY' && pass "release config is valid JSON and keeps breaking changes below 1.0.0" || fail "release config"
import json
c = json.load(open(".releaserc.json"))
rules = dict(c["plugins"])["@semantic-release/commit-analyzer"]["releaseRules"]
assert {"breaking": True, "release": "minor"} in rules and c["tagFormat"] == "v${version}" and c["branches"] == ["main"]
PY

echo "live wallpaper"
: > "$work/live.mp4"; scripts/theme-switch --wallpaper "$work/live.mp4" >/dev/null
scripts/theme-switch --no-reload primo-dusk >/dev/null 2>&1
[[ "$(cat "$XDG_STATE_HOME/hyprland-dotfiles/wallpaper-current")" == "$work/live.mp4" ]] \
    && ! grep -q live.mp4 "$XDG_CONFIG_HOME/hypr/hyprpaper.conf" 2>/dev/null \
    && pass "a video is the live wallpaper, static consumers keep a still" || fail "video wallpaper handling"
scripts/theme-switch --wallpaper reset >/dev/null

echo "video wallpaper recovery"
video_test="$work/video-recovery"; mkdir -p "$video_test/bin" "$video_test/state/hyprland-dotfiles" "$video_test/run"
printf 'video' > "$video_test/live.mp4"; printf '%s\n' "$video_test/live.mp4" > "$video_test/state/hyprland-dotfiles/wallpaper-current"
printf '#!/bin/sh\nexit 0\n' > "$video_test/bin/pkill"; chmod +x "$video_test/bin/pkill"
printf '#!/bin/sh\nexit 1\n' > "$video_test/bin/pgrep"
printf '#!/bin/sh\nexit 1\n' > "$video_test/bin/sleep"
printf '%s\n' '#!/bin/sh' 'printf "%s\\n" "$*" >> "$VIDEO_TEST_LOG"' 'exit 0' > "$video_test/bin/setsid"
printf '#!/bin/sh\nexit 0\n' > "$video_test/bin/mpvpaper"
chmod +x "$video_test/bin/pgrep" "$video_test/bin/sleep" "$video_test/bin/setsid" "$video_test/bin/mpvpaper"
PATH="$video_test/bin:$PATH" XDG_RUNTIME_DIR="$video_test/run" XDG_STATE_HOME="$video_test/state" VIDEO_TEST_LOG="$video_test/started" \
    config/hypr/scripts/wallpaper-rotate.sh guard >/dev/null 2>&1
grep -q 'mpvpaper' "$video_test/started" && pass "a stopped video wallpaper is restarted" || fail "video wallpaper recovery"

echo "lock and login screens"
cp themes/primo-dawn/wallpaper.png "$work/pic.png"; printf 'GIF89a' > "$work/anim.gif"
scripts/theme-switch --lock-wallpaper "$work/pic.png" >/dev/null; scripts/theme-switch --login-wallpaper "$work/anim.gif" >/dev/null
grep -qx "\$lock_bg = $work/pic.png" config/hypr/hyprlock-theme.conf && grep -qx '$lock_blur = 0' config/hypr/hyprlock-theme.conf \
    && grep -qx 'background=background.gif' sddm/primo/theme.conf && [[ -f sddm/primo/background.gif && ! -e sddm/primo/background.png ]] \
    && pass "a picture on the lock screen, a GIF on the login screen" || fail "lock / login wallpaper"
scripts/theme-switch --lock-wallpaper blur >/dev/null; scripts/theme-switch --login-wallpaper desktop >/dev/null
grep -qx '$lock_bg = screenshot' config/hypr/hyprlock-theme.conf && [[ -f sddm/primo/background.png && ! -e sddm/primo/background.gif ]] \
    && pass "back to the blurred screen and the desktop wallpaper" || fail "lock / login reset"
fl() { printf 'u:\nWhen Type Source Valid\n'; for t in "$@"; do echo "2026-01-01 $t TTY V"; done; }
now="$(date -d '2026-01-01 10:05:00' +%s)"; ls_() { FAILLOCK_CONF=/dev/null NOW="$now" config/hypr/scripts/lock-status.sh -; }
[[ "$(fl 10:04:00 | ls_)" == "1 wrong password. 2 tries left before a 10 min lock." \
   && "$(fl 10:03:00 10:04:00 10:04:30 | ls_)" == "Locked after 3 wrong passwords. Try again in 10 min." && -z "$(fl 09:00:00 | ls_)" ]] \
    && pass "wrong-password line on the lock screen" || fail "lock-status.sh"

echo "generated files are valid"
python3 - <<PY && pass "TOML / JSON / SVG outputs" || fail "TOML / JSON / SVG outputs"
import json, re, tomllib, pathlib, os
cfg = pathlib.Path(os.environ["XDG_CONFIG_HOME"])
tomllib.loads((cfg / "starship.toml").read_text())
tomllib.loads((cfg / "satty" / "config.toml").read_text())
strip = lambda s: re.sub(r"^\s*//.*\n", "", s, flags=re.M)
json.loads(strip(pathlib.Path("config/waybar/config.jsonc").read_text()))
json.loads(pathlib.Path("config/swaync/config.json").read_text())
json.loads(strip((cfg / "fastfetch" / "config.jsonc").read_text()))
import xml.etree.ElementTree as ET
ET.parse("config/hypr/logo.svg"); ET.parse("sddm/primo/logo.svg")
ET.parse(pathlib.Path(os.environ["XDG_DATA_HOME"]) / "icons/hicolor/scalable/apps/primo.svg")
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

echo "launcher window"
if python3 -c 'import gi; gi.require_version("Gtk","4.0")' 2>/dev/null; then
    python3 - <<'PY' && pass "the launcher window module loads and uses the launcher sources" || fail "launcher window module"
import importlib.util
spec = importlib.util.spec_from_file_location("l", "config/hypr/scripts/launcher.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
assert m.calculate("12*(3+4)") == "84" and callable(m.collect) and m.KIND_LABEL["window"] == "WINDOWS"
PY
else skip "python-gobject not installed"; fi

echo "isolation"
[[ ! -s "$LIVE_LOG" ]] && pass "the checks never reached the running desktop" \
    || { fail "the checks tried to change the running desktop:"; sort -u "$LIVE_LOG" | head -5 | sed 's/^/        /'; }

echo
(( fails == 0 )) && echo "All checks passed." || { echo "$fails check(s) failed."; exit 1; }
