#!/usr/bin/env bash
# Volume / brightness with on-screen feedback.
# Usage: osd.sh volume-up|volume-down|volume-mute|mic-mute|brightness-up|brightness-down
# Uses swayosd when installed (pill OSD), otherwise a single replaceable dunst notification.
set -uo pipefail

osd_dunst() { # label value icon
    notify-send -h string:x-dunst-stack-tag:osd -h string:x-canonical-private-synchronous:osd -h "int:value:$2" -t 1200 -i "$3" "$1" "$2%"
}
volume() { wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{printf "%d", $2*100}'; }
muted()  { wpctl get-volume @DEFAULT_AUDIO_SINK@ | grep -q MUTED; }
brightness() { brightnessctl -m | awk -F, '{gsub("%","",$4); print $4}'; }

if command -v swayosd-client >/dev/null && pgrep -x swayosd-server >/dev/null; then
    case "$1" in
        volume-up)       swayosd-client --output-volume raise --max-volume 100 ;;
        volume-down)     swayosd-client --output-volume lower ;;
        volume-mute)     swayosd-client --output-volume mute-toggle ;;
        mic-mute)        swayosd-client --input-volume mute-toggle ;;
        brightness-up)   swayosd-client --brightness raise ;;
        brightness-down) swayosd-client --brightness lower ;;
    esac
    exit 0
fi

case "$1" in
    volume-up)       wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+; osd_dunst "Volume" "$(volume)" audio-volume-high ;;
    volume-down)     wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-;      osd_dunst "Volume" "$(volume)" audio-volume-low ;;
    volume-mute)     wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle
                     if muted; then osd_dunst "Muted" 0 audio-volume-muted; else osd_dunst "Volume" "$(volume)" audio-volume-high; fi ;;
    mic-mute)        wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle
                     if wpctl get-volume @DEFAULT_AUDIO_SOURCE@ | grep -q MUTED; then osd_dunst "Microphone off" 0 microphone-sensitivity-muted
                     else osd_dunst "Microphone on" 100 microphone-sensitivity-high; fi ;;
    brightness-up)   brightnessctl -e4 -n2 set 5%+ >/dev/null; osd_dunst "Brightness" "$(brightness)" display-brightness ;;
    brightness-down) brightnessctl -e4 -n2 set 5%- >/dev/null; osd_dunst "Brightness" "$(brightness)" display-brightness ;;
    *) echo "usage: ${0##*/} volume-up|volume-down|volume-mute|mic-mute|brightness-up|brightness-down" >&2; exit 2 ;;
esac
