# Security

Some scripts here run with `sudo` or `pkexec` (`setup-system.sh`, `install-sddm-theme.sh`, `install-boot-splash.sh`). Each one shows its plan
before it changes anything. Read a script before you run it as root.

The scripts live in a folder you own, so any program running as you can edit them. Before you run one with `sudo`, read it, and do not run
a copy that came from somewhere else. Primo never downloads and runs code. It reads from the network only what you set up: calendar feeds you add (read as text), the pull-request
count from GitHub through `gh`, and mirror lists when you run `setup-system.sh`.

To report a vulnerability, use [a private security advisory](https://github.com/sya17/primo/security/advisories/new) instead of a public
issue. Please include the script, what you expected and what happened.

Primo stores nothing secret on its own, with one exception: a calendar link you add under Settings > Workflow is kept in
`~/.config/primo/workflow.json`, readable only by you. Clipboard history (`cliphist`) keeps whatever you copy; see
[docs/TOOLS.md](docs/TOOLS.md#good-to-know).
