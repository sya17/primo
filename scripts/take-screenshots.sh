#!/usr/bin/env bash
# Take the README screenshots without showing any of your own windows or data. RUN IT YOURSELF, when you are not working.
#
# It shows an empty special workspace ("shots") over your screen, puts the theme's own wallpaper behind it, opens a few
# Primo windows filled with SAMPLE data, and captures them. Your windows are hidden underneath, your notifications are not
# touched (do-not-disturb is switched on meanwhile), and your theme is put back at the end. Your wallpaper choice is not changed:
# the backdrop shows the theme's own wallpaper from the repo.
# It takes about a minute per theme and covers your screen while it runs.
#
# Do not open windows while it runs: they would land on that workspace. They are moved back to your workspace, never
# closed, but it is better not to. The script only ever closes windows it opened itself, and only on its own workspace.
#
# Usage: scripts/take-screenshots.sh --yes [theme ...]      default: primo-dusk primo-dawn
#        (--yes confirms that you know your screen is covered)
# Needs: grim, ffmpeg (WebP), a running Hyprland session. Writes docs/screenshots/<dusk|dawn>-<name>.webp
set -uo pipefail

root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
scripts="$root/config/hypr/scripts"
out="$root/docs/screenshots"
state="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles"
if [[ "${1:-}" != --yes ]]; then
    echo "This covers your screen for about a minute per theme, hides your windows meanwhile and switches the theme."
    echo "Do not open windows while it runs. Start it again with --yes when the computer is yours: $0 --yes [theme ...]"
    exit 1
fi
shift
themes=("$@"); (( ${#themes[@]} )) || themes=(primo-dusk primo-dawn)
ALLOWED="dev.primo.Backdrop dev.primo.Settings dev.primo.Hub dev.primo.Launcher primo-shot-term"

for c in grim ffmpeg hyprctl python3 kitty fastfetch eza; do command -v "$c" >/dev/null || { echo "$c is required"; exit 1; }; done
[[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || { echo "Run this inside your Hyprland session."; exit 1; }
lockdir="${XDG_RUNTIME_DIR:-/tmp}/primo-screenshots.lock.d"   # a directory, not flock: windows we start must not inherit a lock file
mkdir "$lockdir" 2>/dev/null || { echo "Already running (remove $lockdir if it is not)."; exit 1; }
tmp="$(mktemp -d)"
mkdir -p "$out"

# ---------------------------------------------------------------------------- remember everything, restore it on exit
# If an earlier run was cut short (logout, crash), put its theme back first, from the file it left behind.
recover="$state/screenshots-restore"
if [[ -f "$recover" ]]; then
    "$root/scripts/theme-switch" "$(cat "$recover")" >/dev/null 2>&1 && echo "Restored the theme from an earlier interrupted run."
fi
orig_theme="$(cat "$state/current" 2>/dev/null || echo primo-dusk)"
mkdir -p "$state"; echo "$orig_theme" > "$recover"
dnd_was="$(swaync-client -D 2>/dev/null || echo false)"
orig_ws="$(hyprctl activeworkspace -j | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
daemons=()                                   # resident services we stop and later start again
for d in launcher hub activity; do pgrep -f "^python3 .*scripts/$d\.py" >/dev/null && daemons+=("$d"); done

special_shown() { hyprctl monitors -j | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)[0]["specialWorkspace"]["name"] == "special:shots" else 1)'; }
hide_special() { special_shown && hyprctl dispatch 'hl.dsp.workspace.toggle_special("shots")' >/dev/null; sleep 0.5; }
show_special() { special_shown || hyprctl dispatch 'hl.dsp.workspace.toggle_special("shots")' >/dev/null; sleep 0.8; }

cleanup() {
    close_class dev.primo.Backdrop; close_class primo-shot-term; close_class dev.primo.Settings
    pkill -f "^python3 .*scripts/(launcher|hub)\.py" 2>/dev/null
    sleep 0.8
    hide_special
    "$root/scripts/theme-switch" "$orig_theme" >/dev/null 2>&1       # your wallpaper choice is never touched: only the theme is switched
    rm -f "$recover"
    [[ "$dnd_was" == true ]] || swaync-client -df >/dev/null 2>&1
    for d in "${daemons[@]}"; do
        hyprctl dispatch "hl.dsp.exec_cmd(\"python3 ~/.config/hypr/scripts/$d.py --daemon\")" >/dev/null 2>&1
    done
    hyprctl reload >/dev/null 2>&1               # drops the temporary window rules
    rm -rf "$tmp" "$lockdir"
    echo "Restored: theme $orig_theme, your windows and services."
}
trap cleanup EXIT

# ---------------------------------------------------------------------------- helpers
clients() { hyprctl clients -j; }
# Everything below looks only at windows on OUR workspace, so your own windows are never touched.
mine() { clients | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    if c['workspace']['name'] == 'special:shots' and c['class'] == '$1':
        print(c['$2'])" | head -1; }
wait_class() { for _ in $(seq 1 60); do [[ -n "$(mine "$1" pid)" ]] && return 0; sleep 0.25; done; return 1; }
close_class() { local p; p="$(mine "$1" pid)"; [[ -n "$p" ]] && kill "$p" 2>/dev/null; sleep 0.7; }
rule() { hyprctl eval "hl.window_rule({ name = \"$1\", match = { class = \"$2\" }, $3 })" >/dev/null; }

# Before every picture: only our windows may be on the screenshot workspace, and the backdrop must cover the screen.
guard() {
    special_shown || { echo "the screenshot workspace is not showing: stopping"; exit 1; }
    local addr
    for addr in $(clients | python3 -c "
import json, sys
allowed = set('$ALLOWED'.split())
print(' '.join(c['address'] for c in json.load(sys.stdin) if c['workspace']['name'] == 'special:shots' and c['class'] not in allowed))"); do
        echo "  a window of yours opened here; moving it back to workspace $orig_ws"
        hyprctl dispatch "hl.dsp.window.move({ workspace = $orig_ws, window = \"address:$addr\" })" >/dev/null
        sleep 0.4
    done
    clients | python3 -c "
import json, sys
bd = [c for c in json.load(sys.stdin) if c['class'] == 'dev.primo.Backdrop']
ok = bd and bd[0]['at'] == [0, 0] and bd[0]['size'][0] >= 1900 and bd[0]['size'][1] >= 1070 and bd[0]['workspace']['name'] == 'special:shots'
if not ok:
    print('the backdrop does not cover the screen'); sys.exit(1)
" || { echo "stopping."; exit 1; }
}

# shot NAME [CLASS]: capture the whole screen (no class) or the box of that window plus a margin; saved as WebP
shot() {
    local name="$1" cls="${2:-}" crop="" png="$tmp/$1.png"
    guard
    grim "$png"
    if [[ -n "$cls" ]]; then
        crop="$(clients | python3 -c "
import json, sys
c = next(c for c in json.load(sys.stdin) if c['class'] == '$cls' and c['workspace']['name'] == 'special:shots')
m = 28
x, y, w, h = c['at'][0], c['at'][1], c['size'][0], c['size'][1]
x0, y0 = max(0, x - m), max(0, y - m)
print(f'{min(1920 - x0, w + 2 * m)}:{min(1080 - y0, h + 2 * m)}:{x0}:{y0}')")"
        ffmpeg -loglevel error -y -i "$png" -vf "crop=$crop" -c:v libwebp -quality 90 "$out/$tag-$name.webp"
    else
        ffmpeg -loglevel error -y -i "$png" -c:v libwebp -quality 90 "$out/$tag-$name.webp"
    fi
    printf '  %s-%s.webp  %s KB\n' "$tag" "$name" "$(( $(stat -c %s "$out/$tag-$name.webp") / 1024 ))"
}

# ---------------------------------------------------------------------------- sample data (never your own)
sample="$tmp/sample"; mkdir -p "$sample/state" "$sample/notes"
SCRIPTS="$scripts" python3 - "$sample" <<'PY'
import os, sys, time
from datetime import datetime, timedelta
d = sys.argv[1]
os.environ["XDG_STATE_HOME"] = d + "/state"; os.environ["PRIMO_WORKFLOW_CONFIG"] = d + "/workflow.json"
sys.path.insert(0, os.environ["SCRIPTS"])
import hub_core as hc, workflow_core as wf
now = datetime.now()
st = hc.Store()
for txt in ["Review pull requests #work", "Send the weekly report tomorrow 16:00 #work", "Renew the domain on friday 10:00",
            "Stand-up every weekday 9:30 #work", "Call the dentist next monday 11:00", "Water the plants"]:
    r = hc.parse_reminder(txt)
    st["reminders"].append({"id": hc.new_id(), "title": r["title"], "due": r["due"].isoformat(timespec="minutes") if r["due"] else None,
                            "repeat": r["repeat"], "tag": r["tag"], "done": False, "fired": False})
st["reminders"].append({"id": hc.new_id(), "title": "Book the flights", "due": (now - timedelta(hours=26)).isoformat(timespec="minutes"),
                        "repeat": None, "tag": None, "done": True, "fired": True})
st["alarms"] = [{"id": "a1", "time": "07:30", "days": [0, 1, 2, 3, 4], "label": "Wake up", "on": True}]
st["world"] = ["Asia/Tokyo", "Europe/London", "America/New_York"]
log = []
for back, (m, lab, cat) in enumerate([(95, "Project work", "Work"), (50, "Reading", "Learning"), (125, "Project work", "Work"),
                                      (45, "Writing", "Personal"), (75, "Planning", "Work"), (60, "Reading", "Learning"), (40, "Inbox", "Other")]):
    s = (now - timedelta(days=back)).replace(hour=9, minute=0).timestamp()
    log.append({"start": s, "end": s + m * 60, "min": m, "label": lab, "cat": cat})
    if back in (0, 2, 3):
        log.append({"start": s + 4000, "end": s + 5500, "min": 25, "label": "Writing", "cat": "Personal"})
st["log"] = log
st["session"] = {"phase": "focus", "end": time.time() + 3600, "cycle": 1, "left": None, "label": "Write the README", "category": "Work", "seg": time.time(), "worked": 0.0}
st["focus"] = {"label": "Write the README", "category": "Work"}
st.save()
def stamp(t): return t.strftime("%Y%m%dT%H%M%S")
ics = "BEGIN:VCALENDAR\r\n"
for i, (h, title, loc) in enumerate([(1, "Sprint planning", "Room 4"), (4, "1:1 with the team lead", ""), (27, "Design review", "Video call")]):
    t = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=h)
    ics += f"BEGIN:VEVENT\r\nUID:m{i}\r\nDTSTART:{stamp(t)}\r\nDTEND:{stamp(t + timedelta(hours=1))}\r\nSUMMARY:{title}\r\nLOCATION:{loc}\r\nEND:VEVENT\r\n"
t0 = now.replace(hour=9, minute=30, second=0, microsecond=0) - timedelta(days=3)
ics += f"BEGIN:VEVENT\r\nUID:std\r\nDTSTART:{stamp(t0)}\r\nDTEND:{stamp(t0 + timedelta(minutes=15))}\r\nSUMMARY:Daily stand-up\r\nRRULE:FREQ=DAILY\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
url = "https://calendar.example.invalid/sample.ics"
wf.STATE.mkdir(parents=True, exist_ok=True); wf.feed_path(url).write_text(ics)
cfg = wf.load(); cfg["ics"] = [{"name": "Work", "url": url}]; wf.save(cfg)
open(d + "/notes/Meeting notes.md", "w").write("Meeting notes\nAgenda, decisions and next steps.\n")
PY

# ---------------------------------------------------------------------------- run
swaync-client -dn >/dev/null 2>&1                       # no pop-ups from your real notifications while we capture
pkill -f "^python3 .*scripts/(launcher|hub|activity)\.py" 2>/dev/null; sleep 1

for t in "${themes[@]}"; do
    echo "== $t"
    tag="${t#primo-}"; tag="${tag#catppuccin-}"
    if [[ "$(cat "$state/current" 2>/dev/null)" != "$t" ]]; then "$root/scripts/theme-switch" "$t" >/dev/null || continue; sleep 2; fi
    sleep 2.5
    # a theme switch reloads Hyprland, which forgets temporary rules: add them again
    rule shot-backdrop '^dev\\.primo\\.Backdrop$' 'float = true, size = "1920 1080", move = "0 0", no_anim = true, border_size = 0, rounding = 0, no_shadow = true, no_blur = true'
    rule shot-term '^primo-shot-term$' 'float = true, size = "1120 640", move = "monitor_w*0.5-560 monitor_h*0.5-300", no_anim = true'

    show_special
    setsid -f python3 "$root/scripts/shot-backdrop.py" "$root/themes/$t/wallpaper.png" >/dev/null 2>&1
    wait_class dev.primo.Backdrop || { echo "backdrop did not open"; exit 1; }; sleep 1.2

    # desktop: the bar, the wallpaper and a terminal
    setsid -f kitty --class primo-shot-term --directory "$root" bash -ic 'clear; fastfetch; eza -l --icons=always themes | head -6; exec bash -i' >/dev/null 2>&1
    wait_class primo-shot-term && { sleep 3.5; shot desktop; }
    close_class primo-shot-term

    # settings
    setsid -f python3 "$scripts/primo-settings.py" --page appearance >/dev/null 2>&1
    wait_class dev.primo.Settings && { sleep 2.5; shot settings dev.primo.Settings; }
    close_class dev.primo.Settings

    # health: a sample machine where everything works (the real page would show the services this script stopped)
    PRIMO_SHOT_MODE=1 setsid -f python3 "$scripts/primo-settings.py" --page health >/dev/null 2>&1
    wait_class dev.primo.Settings && { sleep 3; shot health dev.primo.Settings; }
    close_class dev.primo.Settings

    # launcher with a query already typed
    PRIMO_LAUNCHER_QUERY="fire" setsid -f python3 "$scripts/launcher.py" --daemon >/dev/null 2>&1; sleep 2.5
    "$scripts/launcher.sh" toggle; wait_class dev.primo.Launcher && { sleep 1.8; shot launcher dev.primo.Launcher; }
    "$scripts/launcher.sh" toggle; sleep 0.8; pkill -f "^python3 .*scripts/launcher\.py"; sleep 0.8

    # launcher command word, with invented windows and workspaces (your own window titles are never shown)
    PRIMO_SHOT_MODE=1 PRIMO_LAUNCHER_QUERY="ws " setsid -f python3 "$scripts/launcher.py" --daemon >/dev/null 2>&1; sleep 2.5
    "$scripts/launcher.sh" toggle; wait_class dev.primo.Launcher && { sleep 1.8; shot launcher-ws dev.primo.Launcher; }
    "$scripts/launcher.sh" toggle; sleep 0.8; pkill -f "^python3 .*scripts/launcher\.py"; sleep 0.8

    # the time hub, with sample data
    PRIMO_SHOT_MODE=1 PRIMO_HUB_KEEP=1 PRIMO_HUB_MUTE=1 XDG_STATE_HOME="$sample/state" PRIMO_WORKFLOW_CONFIG="$sample/workflow.json" PRIMO_NOTES_DIR="$sample/notes" \
        setsid -f python3 "$scripts/hub.py" --daemon >/dev/null 2>&1; sleep 2.5
    for tab in calendar reminders clock focus report notes; do
        XDG_STATE_HOME="$sample/state" "$scripts/hub.sh" "$tab"; wait_class dev.primo.Hub && { sleep 2; shot "hub-$tab" dev.primo.Hub; }
    done
    pkill -f "^python3 .*scripts/hub\.py"; sleep 1

    close_class dev.primo.Backdrop
    hide_special
done
echo "Done. Screenshots are in $out"
