#!/usr/bin/env bash
# Hook the Primo terminal setup (prompt, fzf, zoxide, eza, bat) into ~/.bashrc and set the btop theme.
# It only adds one marked block to ~/.bashrc and keeps a one-time backup; nothing else is touched.
#
# Usage: setup-shell.sh            install or refresh
#        setup-shell.sh --remove   take it out again
set -euo pipefail

rc="$HOME/.bashrc"
begin="# >>> primo shell >>>"
end="# <<< primo shell <<<"
btop_conf="${XDG_CONFIG_HOME:-$HOME/.config}/btop/btop.conf"

strip_block() { # print stdin without the marked block
    awk -v b="$begin" -v e="$end" '$0 == b {skip = 1} !skip {print} $0 == e {skip = 0}'
}

touch "$rc"
if [[ "${1:-}" == "--remove" ]]; then
    strip_block < "$rc" > "$rc.primo-tmp" && mv "$rc.primo-tmp" "$rc"
    echo "Removed the Primo block from $rc (open a new terminal)."
    exit 0
fi

[[ -f "$rc.bak-primo" ]] || { cp "$rc" "$rc.bak-primo"; echo "Backup: $rc.bak-primo"; }
{
    strip_block < "$rc"
    printf '%s\n' "$begin" \
        '[[ -r "$HOME/.config/primo/shell.sh" ]] && source "$HOME/.config/primo/shell.sh"' \
        "$end"
} > "$rc.primo-tmp" && mv "$rc.primo-tmp" "$rc"
echo "Hooked into $rc. Open a new terminal to see the prompt."

# btop: use the generated theme
mkdir -p "$(dirname "$btop_conf")"
if [[ -f "$btop_conf" ]]; then
    if grep -q '^color_theme' "$btop_conf"; then sed -i 's|^color_theme.*|color_theme = "primo"|' "$btop_conf"
    else echo 'color_theme = "primo"' >> "$btop_conf"; fi
else
    printf 'color_theme = "primo"\ntruecolor = True\nrounded_corners = True\n' > "$btop_conf"
fi
echo "btop theme set to primo."
