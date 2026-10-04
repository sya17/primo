#!/usr/bin/env python3
"""Generate VS Code colour themes from the Primo palettes and build an installable extension.

Usage: gen-vscode-theme.py                 build vscode/primo-themes-<version>.vsix
       gen-vscode-theme.py --install       build, then `code --install-extension` it
                                           (and write a starter settings.json if you have none)

Every theme in themes/*/theme.conf becomes a VS Code colour theme (dark and light). With
`window.autoDetectColorScheme` VS Code follows the desktop's dark/light mode.
"""
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "vscode"
VERSION = "0.1.0"
PUBLISHER, NAME = "primo", "primo-themes"


def read_conf(path):
    data = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = re.split(r"\s#", v)[0].strip()
    return data


def build_theme(p):
    c = lambda k, a="": "#" + p[k] + a  # noqa: E731  colour with optional alpha suffix
    ansi = {
        "Black": "surface1", "Red": "red", "Green": "green", "Yellow": "yellow",
        "Blue": "blue", "Magenta": "magenta", "Cyan": "cyan", "White": "subtext",
    }
    terminal = {"terminal.background": c("mantle"), "terminal.foreground": c("text"),
                "terminalCursor.foreground": c("accent"), "terminal.selectionBackground": c("accent", "44")}
    for name, key in ansi.items():
        terminal[f"terminal.ansi{name}"] = c(key)
        terminal[f"terminal.ansiBright{name}"] = c("overlay") if name == "Black" else c(key)

    colors = {
        "focusBorder": c("accent", "99"), "foreground": c("text"), "descriptionForeground": c("subtext"),
        "errorForeground": c("red"), "icon.foreground": c("subtext"), "widget.shadow": c("shadow", "66"),
        "selection.background": c("accent", "55"),
        "button.background": c("accent"), "button.foreground": c("base"), "button.hoverBackground": c("accent2"),
        "button.secondaryBackground": c("surface1"), "button.secondaryForeground": c("text"),
        "badge.background": c("accent"), "badge.foreground": c("base"),
        "progressBar.background": c("accent"),
        "scrollbarSlider.background": c("overlay", "44"), "scrollbarSlider.hoverBackground": c("overlay", "77"),
        "scrollbarSlider.activeBackground": c("overlay", "99"),
        "dropdown.background": c("surface0"), "dropdown.border": c("surface1"), "dropdown.foreground": c("text"),
        "input.background": c("surface0"), "input.border": c("surface1"), "input.foreground": c("text"),
        "input.placeholderForeground": c("overlay"), "inputOption.activeBackground": c("accent", "33"),
        "inputOption.activeBorder": c("accent"),
        "list.activeSelectionBackground": c("accent", "33"), "list.activeSelectionForeground": c("text"),
        "list.inactiveSelectionBackground": c("surface1"), "list.hoverBackground": c("surface0"),
        "list.focusBackground": c("accent", "33"), "list.highlightForeground": c("accent"),
        "activityBar.background": c("crust"), "activityBar.foreground": c("text"),
        "activityBar.inactiveForeground": c("overlay"), "activityBar.border": c("crust"),
        "activityBar.activeBorder": c("accent"), "activityBarBadge.background": c("accent"),
        "activityBarBadge.foreground": c("base"),
        "sideBar.background": c("mantle"), "sideBar.foreground": c("subtext"), "sideBar.border": c("crust"),
        "sideBarTitle.foreground": c("text"), "sideBarSectionHeader.background": c("mantle"),
        "sideBarSectionHeader.foreground": c("text"),
        "editorGroupHeader.tabsBackground": c("mantle"), "editorGroup.border": c("crust"),
        "tab.activeBackground": c("base"), "tab.activeForeground": c("text"), "tab.inactiveBackground": c("mantle"),
        "tab.inactiveForeground": c("overlay"), "tab.border": c("mantle"), "tab.activeBorderTop": c("accent"),
        "tab.hoverBackground": c("surface0"), "tab.unfocusedActiveBackground": c("base"),
        "editor.background": c("base"), "editor.foreground": c("text"),
        "editorLineNumber.foreground": c("overlay"), "editorLineNumber.activeForeground": c("text"),
        "editor.lineHighlightBackground": c("surface0", "80"), "editor.selectionBackground": c("accent", "44"),
        "editor.inactiveSelectionBackground": c("accent", "22"), "editor.selectionHighlightBackground": c("accent", "22"),
        "editor.wordHighlightBackground": c("surface1"), "editor.findMatchBackground": c("yellow", "55"),
        "editor.findMatchHighlightBackground": c("yellow", "33"), "editorCursor.foreground": c("accent"),
        "editorWhitespace.foreground": c("surface1"), "editorIndentGuide.background1": c("surface0"),
        "editorIndentGuide.activeBackground1": c("overlay"), "editorBracketMatch.background": c("accent", "33"),
        "editorBracketMatch.border": c("accent"), "editorRuler.foreground": c("surface1"),
        "editorGutter.addedBackground": c("green"), "editorGutter.modifiedBackground": c("yellow"),
        "editorGutter.deletedBackground": c("red"),
        "editorError.foreground": c("red"), "editorWarning.foreground": c("yellow"),
        "editorInfo.foreground": c("accent"), "editorHint.foreground": c("cyan"),
        "editorWidget.background": c("surface0"), "editorWidget.border": c("surface1"),
        "editorSuggestWidget.background": c("surface0"), "editorSuggestWidget.selectedBackground": c("surface1"),
        "editorSuggestWidget.highlightForeground": c("accent"), "editorHoverWidget.background": c("surface0"),
        "editorHoverWidget.border": c("surface1"),
        "peekView.border": c("accent"), "peekViewEditor.background": c("mantle"),
        "peekViewResult.background": c("mantle"), "peekViewTitle.background": c("surface0"),
        "diffEditor.insertedTextBackground": c("green", "22"), "diffEditor.removedTextBackground": c("red", "22"),
        "panel.background": c("mantle"), "panel.border": c("crust"), "panelTitle.activeForeground": c("text"),
        "panelTitle.activeBorder": c("accent"), "panelTitle.inactiveForeground": c("overlay"),
        "statusBar.background": c("mantle"), "statusBar.foreground": c("subtext"), "statusBar.border": c("crust"),
        "statusBar.noFolderBackground": c("mantle"), "statusBar.debuggingBackground": c("orange"),
        "statusBar.debuggingForeground": c("base"), "statusBarItem.hoverBackground": c("surface0"),
        "statusBarItem.remoteBackground": c("accent"), "statusBarItem.remoteForeground": c("base"),
        "titleBar.activeBackground": c("crust"), "titleBar.activeForeground": c("subtext"),
        "titleBar.inactiveBackground": c("crust"), "titleBar.inactiveForeground": c("overlay"),
        "menu.background": c("surface0"), "menu.foreground": c("text"), "menu.selectionBackground": c("accent", "33"),
        "menu.separatorBackground": c("surface1"),
        "notifications.background": c("surface0"), "notifications.foreground": c("text"),
        "notificationCenterHeader.background": c("surface1"),
        "breadcrumb.foreground": c("overlay"), "breadcrumb.focusForeground": c("text"),
        "breadcrumb.activeSelectionForeground": c("accent"),
        "textLink.foreground": c("accent"), "textLink.activeForeground": c("accent2"),
        "textCodeBlock.background": c("surface0"), "textBlockQuote.background": c("surface0"),
        "gitDecoration.modifiedResourceForeground": c("yellow"), "gitDecoration.addedResourceForeground": c("green"),
        "gitDecoration.deletedResourceForeground": c("red"), "gitDecoration.untrackedResourceForeground": c("cyan"),
        "gitDecoration.ignoredResourceForeground": c("overlay"), "gitDecoration.conflictingResourceForeground": c("orange"),
        "minimapSlider.background": c("overlay", "33"),
        **terminal,
    }

    def tok(scope, color, style=""):
        rule = {"scope": scope, "settings": {"foreground": c(color)}}
        if style:
            rule["settings"]["fontStyle"] = style
        return rule

    tokens = [
        tok(["comment", "punctuation.definition.comment"], "overlay", "italic"),
        tok(["string", "string.quoted", "punctuation.definition.string"], "green"),
        tok(["string.regexp"], "cyan"),
        tok(["constant.numeric", "constant.language", "constant.character", "constant.other", "support.constant"], "orange"),
        tok(["keyword", "keyword.control", "storage", "storage.type", "storage.modifier"], "accent2"),
        tok(["keyword.operator", "keyword.operator.assignment"], "cyan"),
        tok(["entity.name.function", "support.function", "meta.function-call entity.name.function"], "accent"),
        tok(["entity.name.type", "entity.name.class", "support.class", "support.type", "entity.other.inherited-class"], "yellow"),
        tok(["entity.name.namespace", "entity.name.module"], "yellow"),
        tok(["variable", "variable.other", "meta.definition.variable"], "text"),
        tok(["variable.parameter"], "orange", "italic"),
        tok(["variable.language"], "red", "italic"),
        tok(["entity.name.tag", "meta.tag"], "red"),
        tok(["entity.other.attribute-name"], "yellow"),
        tok(["support.type.property-name", "meta.object-literal.key", "support.type.property-name.json"], "accent"),
        tok(["punctuation", "meta.brace", "meta.delimiter"], "subtext"),
        tok(["markup.heading", "entity.name.section"], "accent", "bold"),
        tok(["markup.bold"], "orange", "bold"),
        tok(["markup.italic"], "accent2", "italic"),
        tok(["markup.inline.raw", "markup.fenced_code"], "green"),
        tok(["markup.underline.link", "string.other.link"], "accent", "underline"),
        tok(["markup.quote"], "overlay", "italic"),
        tok(["invalid", "invalid.illegal"], "red"),
    ]
    return {
        "name": p["name"],
        "type": "dark" if p.get("mode") == "dark" else "light",
        "semanticHighlighting": True,
        "colors": colors,
        "tokenColors": tokens,
    }


def build():
    themes = []
    (OUT / "extension" / "themes").mkdir(parents=True, exist_ok=True)
    for conf in sorted((ROOT / "themes").glob("*/theme.conf")):
        p = read_conf(conf)
        slug = conf.parent.name
        (OUT / "extension" / "themes" / f"{slug}.json").write_text(json.dumps(build_theme(p), indent=2) + "\n")
        themes.append({"label": p["name"], "uiTheme": "vs-dark" if p.get("mode") == "dark" else "vs",
                       "path": f"./themes/{slug}.json"})
    package = {
        "name": NAME, "displayName": "Primo Themes", "description": "Colour themes generated from the Primo desktop palettes",
        "version": VERSION, "publisher": PUBLISHER, "license": "MIT",
        "engines": {"vscode": "^1.60.0"}, "categories": ["Themes"], "contributes": {"themes": themes},
    }
    (OUT / "extension" / "package.json").write_text(json.dumps(package, indent=2) + "\n")
    (OUT / "extension" / "README.md").write_text("# Primo Themes\n\nGenerated from the palettes in the Primo dotfiles.\n")

    vsix = OUT / f"{NAME}-{VERSION}.vsix"
    manifest = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="{NAME}" Version="{VERSION}" Publisher="{PUBLISHER}"/>
    <DisplayName>Primo Themes</DisplayName>
    <Description xml:space="preserve">Colour themes generated from the Primo desktop palettes</Description>
    <Categories>Themes</Categories>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
  </Assets>
</PackageManifest>
"""
    content_types = ('<?xml version="1.0" encoding="utf-8"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/Content-Types">'
                     '<Default Extension=".json" ContentType="application/json"/>'
                     '<Default Extension=".md" ContentType="text/markdown"/>'
                     '<Default Extension=".vsixmanifest" ContentType="text/xml"/></Types>')
    with zipfile.ZipFile(vsix, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("extension.vsixmanifest", manifest)
        for f in sorted((OUT / "extension").rglob("*")):
            if f.is_file():
                z.write(f, "extension/" + f.relative_to(OUT / "extension").as_posix())
    print(f"built {vsix.relative_to(ROOT)} with {len(themes)} themes")
    return vsix


def starter_settings(names):
    dark = next((n for n in names if "Dusk" in n), names[0])
    light = next((n for n in names if "Dawn" in n), names[-1])
    return {
        "workbench.colorTheme": dark,
        "window.autoDetectColorScheme": True,
        "workbench.preferredDarkColorTheme": dark,
        "workbench.preferredLightColorTheme": light,
        "editor.fontFamily": "'JetBrainsMono Nerd Font', 'JetBrains Mono', monospace",
        "editor.fontLigatures": True,
        "editor.cursorBlinking": "smooth",
        "editor.cursorSmoothCaretAnimation": "on",
        "editor.smoothScrolling": True,
        "workbench.list.smoothScrolling": True,
        "terminal.integrated.smoothScrolling": True,
        "terminal.integrated.fontFamily": "'JetBrainsMono Nerd Font'",
        "editor.bracketPairColorization.enabled": True,
        "workbench.startupEditor": "none",
        "window.menuBarVisibility": "toggle",
    }


def main():
    vsix = build()
    if "--install" not in sys.argv:
        return 0
    r = subprocess.run(["code", "--install-extension", str(vsix), "--force"], capture_output=True, text=True)
    print((r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "")
    if r.returncode != 0:
        return r.returncode
    settings = Path.home() / ".config" / "Code" / "User" / "settings.json"
    names = [json.loads(f.read_text())["name"] for f in sorted((OUT / "extension" / "themes").glob("*.json"))]
    if not settings.exists() or not settings.read_text().strip():
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(starter_settings(names), indent=4) + "\n")
        print(f"wrote a starter {settings}")
    else:
        print("settings.json already exists: pick the theme with Ctrl+K Ctrl+T (or add window.autoDetectColorScheme)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
