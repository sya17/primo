#!/usr/bin/env python3
"""Run from the desktop terminal to apply application-wide privacy preferences."""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
path = config_home / "Code/User/settings.json"
settings = json.loads(path.read_text()) if path.exists() else {}
changes = {
    "telemetry.telemetryLevel": "off",
    "redhat.telemetry.enabled": False,
    "chat.disableAIFeatures": True,
    "workbench.enableExperiments": False,
    "extensions.ignoreRecommendations": True,
    "git.autofetch": False,
}
if any(settings.get(k) != v for k, v in changes.items()):
    if path.exists():
        backup = path.with_name("settings.json.backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        shutil.copy2(path, backup)
        print(f"Backup: {backup}")
    settings.update(changes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=4) + "\n")
print("Privacy preferences applied. Disable Settings Sync in VS Code if it is enabled.")
