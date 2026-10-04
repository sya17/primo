# Contributing

Primo is a personal desktop, so it stays small and opinionated. Bug reports, fixes and new themes are welcome; for a bigger feature,
open an issue first so we can agree on the shape before you write it.

## Run the checks

```bash
scripts/check.sh          # syntax, ShellCheck, theme rendering, tests. Works on a copy of the repo and never touches your desktop
scripts/check-docs.py     # every link and image in the Markdown files must exist
```

CI runs both on every push and pull request. `shellcheck` gives more findings than the script reports at first: run it on the files you touched.

## A new theme

Copy a folder in `themes/`, edit `theme.conf` (keep `mode=dark` or `mode=light`), then `scripts/gen-wallpaper.py <name>` and
`hypr-theme <name>`. [docs/THEMING.md](docs/THEMING.md) lists every key. Check the text colour against the background: body text needs a
contrast of at least 4.5:1.

## A themed app

Add `templates/<app>/<file>.tpl` and one `render` line in `scripts/theme-switch`; the steps are in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#add-a-themed-app).

## Rules for changes

- Scripts that change the system (anything with `sudo`) show a plan first, back up every file they edit, and have an undo.
- Never close or kill a window you did not start yourself, and test with temporary copies, not your own config.
- Python and shell stay in the standard library or what the setup already installs. No new dependency for a few lines of code.
- Screenshots come from `scripts/take-screenshots.sh` (it draws sample data). Never post your own windows, tabs, files or faces.
- Say what you tested and what you could not.
