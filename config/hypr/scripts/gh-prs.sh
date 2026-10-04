#!/usr/bin/env bash
# Waybar: pull requests waiting for your review on GitHub. Hidden when there are none, or when gh is not logged in.
# Needs `gh auth login` once. Read only: it only asks GitHub for the list.
# Usage: gh-prs.sh status | open
set -uo pipefail
cache="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dotfiles/gh-prs.json"
hidden='{"text":"","class":"idle","tooltip":""}'

case "${1:-status}" in
    open) exec xdg-open "https://github.com/pulls/review-requested" ;;
    status)
        command -v gh >/dev/null && gh auth status >/dev/null 2>&1 || { echo "$hidden"; exit 0; }
        json="$(timeout 20 gh api -X GET search/issues -f q='is:pr is:open review-requested:@me archived:false' -f per_page=8 2>/dev/null)" || {
            [[ -f "$cache" ]] && cat "$cache" || echo "$hidden"; exit 0; }
        n="$(jq -r '.total_count // 0' <<<"$json")"
        if [[ "$n" == 0 ]]; then out="$hidden"
        else
            # Repository names and PR titles are written by other people and Waybar tooltips render markup: escape them.
            out="$(jq -c --arg n "$n" 'def esc: gsub("&"; "&amp;") | gsub("<"; "&lt;") | gsub(">"; "&gt;");
                {text: ("\($n)"), class: "waiting",
                tooltip: ("Waiting for your review (" + $n + ")\n" + ([.items[] | "\(.repository_url | split("/") | .[-1]) #\(.number)  \(.title)" | esc] | join("\n")))}' <<<"$json")"
        fi
        mkdir -p "$(dirname "$cache")"; echo "$out" | tee "$cache" ;;
esac
