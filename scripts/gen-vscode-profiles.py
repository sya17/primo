#!/usr/bin/env python3
"""Generate local VS Code import files without reading account or project data."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "vscode-profiles"

# Copy appearance only; credentials, AI settings and workspace state are excluded.
source = Path.home() / ".config/Code/User/settings.json"
appearance = {
    "workbench.colorTheme": "Primo Dusk",
    "window.autoDetectColorScheme": True,
    "workbench.preferredDarkColorTheme": "Primo Dusk",
    "workbench.preferredLightColorTheme": "Primo Dawn",
    "editor.fontFamily": "'JetBrainsMono Nerd Font', 'JetBrains Mono', monospace",
    "editor.fontLigatures": True,
    "terminal.integrated.fontFamily": "'JetBrainsMono Nerd Font'",
    "workbench.iconTheme": "material-icon-theme",
    "window.menuBarVisibility": "toggle",
}
if source.exists():
    try:
        current = json.loads(source.read_text())
        for key in appearance:
            if key in current:
                appearance[key] = current[key]
    except json.JSONDecodeError:
        print("Settings use JSONC; using Primo appearance defaults.")

COMMON = {
    **appearance,
    "telemetry.telemetryLevel": "off",
    "redhat.telemetry.enabled": False,
    "chat.disableAIFeatures": True,
    "workbench.enableExperiments": False,
    "extensions.ignoreRecommendations": True,
    "git.autofetch": False,
    "workbench.startupEditor": "none",
    "editor.formatOnSave": True,
    "files.autoSave": "off",
}
VISUAL = ["primo.primo-themes", "enkia.tokyo-night", "pkief.material-icon-theme"]
WEB = ["dbaeumer.vscode-eslint", "esbenp.prettier-vscode"]
WEB_SETTINGS = {
    "editor.defaultFormatter": "esbenp.prettier-vscode",
    "prettier.requireConfig": True,
    "editor.codeActionsOnSave": {"source.fixAll.eslint": "explicit"},
}
PROFILES = {
    "general": ("General", [], {"editor.formatOnSave": False}),
    "spring-boot": ("Spring Boot", [
        "redhat.java", "vscjava.vscode-java-debug", "vscjava.vscode-java-test",
        "vscjava.vscode-maven", "vscjava.vscode-gradle",
        "vmware.vscode-spring-boot", "vscjava.vscode-spring-boot-dashboard",
        "vscjava.vscode-spring-initializr",
    ], {"[java]": {"editor.defaultFormatter": "redhat.java"}}),
    "flutter": ("Flutter", ["Dart-Code.dart-code", "Dart-Code.flutter"], {
        "[dart]": {"editor.defaultFormatter": "Dart-Code.dart-code", "editor.tabSize": 2},
    }),
    "nuxt": ("Nuxt", WEB + ["Vue.volar", "Nuxtr.nuxtr-vscode", "nuxt.mdc"], {
        **WEB_SETTINGS, "[vue]": {"editor.defaultFormatter": "esbenp.prettier-vscode"},
    }),
    "next": ("Next.js", WEB, WEB_SETTINGS),
    "python": ("Python", [
        "ms-python.python", "ms-python.vscode-pylance", "ms-python.debugpy",
        "charliermarsh.ruff",
    ], {"[python]": {"editor.defaultFormatter": "charliermarsh.ruff"},
        "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python"}),
    "rust": ("Rust", ["rust-lang.rust-analyzer", "vadimcn.vscode-lldb"], {
        "[rust]": {"editor.defaultFormatter": "rust-lang.rust-analyzer"},
    }),
    "go": ("Go", ["golang.Go"], {
        "[go]": {"editor.defaultFormatter": "golang.Go"},
    }),
}

OUT.mkdir(parents=True, exist_ok=True)
for slug, (name, extensions, settings) in PROFILES.items():
    ids = VISUAL + extensions
    profile = {
        "name": name,
        "settings": json.dumps({"settings": json.dumps({**COMMON, **settings}, indent=2)}),
        "extensions": json.dumps([
            {"identifier": {"id": ext}, "preRelease": False, "disabled": False}
            for ext in ids
        ]),
    }
    (OUT / f"{slug}.code-profile").write_text(json.dumps(profile, indent=2) + "\n")
    print(f"Created {name}: {len(extensions)} language extensions")
