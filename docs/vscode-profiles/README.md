# VS Code profiles for Primo

Eight ready-to-import profiles: General, Spring Boot, Flutter, Nuxt, Next.js, Python, Rust and Go. Each one has the Primo look (theme, fonts,
icons) plus only the extensions that language needs, so the editor stays quiet in projects that do not use them. The profiles hold no
account, credential or workspace data.

The look is copied from your current VS Code appearance settings when the files are generated (nine appearance keys, nothing else), and falls
back to Primo Dusk and Primo Dawn.

## Set up

All commands run from the repository folder.

1. Close every VS Code window, then apply the privacy preferences once:

   ```bash
   python3 scripts/setup-vscode-profile-privacy.py
   ```

   It turns off telemetry (VS Code and Red Hat), experiments, the built-in chat features, extension recommendations and Git auto-fetch. These
   settings apply to the whole application, and a profile import does not always apply them. Your old `settings.json` is backed up first. The
   script reads plain JSON: if your `settings.json` has comments or trailing commas it stops without changing anything, and you can set the
   six preferences listed in the script through VS Code's Settings instead.

2. In VS Code choose **File > Preferences > Profiles > Import Profile**, pick a `.code-profile` file from this folder and click
   **Create** (or **Import**). Repeat for the profiles you want.

3. The Primo theme is built locally and is not on the Marketplace. Build it once, then install it into each imported profile:

   ```bash
   python3 scripts/gen-vscode-theme.py
   code --profile "Spring Boot" --install-extension vscode/primo-themes-*.vsix
   ```

   Use the profile's name in place of "Spring Boot" (Flutter, Nuxt, Next.js, Python, Rust, Go or General). Tokyo Night and Material Icon Theme
   come from the Marketplace when the profile is imported.

4. Open a project folder and choose **Profiles: Switch Profile** from the command palette (`Ctrl+Shift+P`). VS Code remembers the profile for
   that folder. From a terminal:

   ```bash
   code --profile "Spring Boot" ~/path/to/backend
   code --profile "Nuxt" ~/path/to/frontend
   ```

## What is in each profile

| Profile | Extensions on top of the look |
| --- | --- |
| General | None. Plain editing, format on save off. |
| Spring Boot | Java, debugger, test runner, Maven, Gradle, Spring Boot tools, dashboard and Initializr. |
| Flutter | Dart and Flutter. |
| Nuxt | Vue Official, Nuxtr, MDC, ESLint, Prettier. |
| Next.js | ESLint, Prettier. JavaScript, TypeScript and debugging come with VS Code. |
| Python | Python, Pylance, debugpy, Ruff. The interpreter is the project's own `.venv`. |
| Rust | rust-analyzer, CodeLLDB. |
| Go | The official Go extension. |

Prettier only formats a project that has its own Prettier configuration (`prettier.requireConfig`), and no project's formatting settings are
changed. The Next.js profile relies on VS Code's built-in React and TypeScript support; the framework's own plugin follows the project's
configuration.

## Privacy and network use

Importing extensions contacts the Marketplace, and language servers and dependencies may download things when you open a project. The
preferences above are not a network block, and the telemetry of third-party extensions has to be checked separately. Leave Settings Sync off
if you do not want your settings uploaded. A profile does not move or delete the extensions in your Default profile.

## Runtimes

Profiles do not install SDKs or runtimes. Use `mise` for Java, Node and Go, the Flutter SDK for Flutter, `uv` for Python and `rustup` for Rust.
For Python, run `uv sync` in a project that already uses uv, or `uv venv` to create the `.venv`. A Java project follows its Maven or Gradle
configuration, so do not hard-code a global JDK location.

## Regenerate

If your Default appearance changes, write the files again:

```bash
python3 scripts/gen-vscode-profiles.py
```

A theme change made by the Hyprland scripts only touches the Default profile; a language profile with its own appearance settings does not
follow it automatically.
