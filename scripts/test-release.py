#!/usr/bin/env python3
"""Checks that the release route stays the reviewed one: manual, main only, behind a green ci, tags never moved, no hand-typed version.

Reads the workflow, the release rules and the docs; starts nothing and needs no network."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
release = (ROOT / ".github/workflows/release.yml").read_text()
ci = (ROOT / ".github/workflows/ci.yml").read_text()
rules = json.loads((ROOT / ".releaserc.json").read_text())

# manual only, main only, dry run by default, one release at a time, nothing queued behind another
assert re.search(r"^on:\n  workflow_dispatch:", release, re.M) and "push:" not in release.split("jobs:")[0] and "pull_request" not in release.split("jobs:")[0]
assert "if: github.ref == 'refs/heads/main'" in release, "a release can only start from main"
assert re.search(r"dry_run:[\s\S]*?default: true", release), "the default is a dry run"
assert "cancel-in-progress: false" in release and "group: release" in release
# behind a green ci, with the checkout allowed to see every tag and no credentials left in the clone
assert "ci must have passed for this commit" in release and "gh run list --workflow ci.yml" in release and "No passing ci run" in release
assert "fetch-depth: 0" in release and "persist-credentials: false" in release
# the only write permission is on the release job, and only the reviewed tools run
assert release.count("contents: write") == 1 and "contents: read" in release.split("jobs:")[0]
assert "npm ci --ignore-scripts" in release and "--no-install semantic-release" in release
assert "contents: write" not in ci and "contents: read" in ci, "ci cannot write"
# the version comes from commits only: no input, no hand-set number, no forced tag, no tag deletion or move anywhere in the repository's automation
assert "version:" not in release.split("jobs:")[0].split("inputs:")[1], "there is no input that sets a version"
for path in list((ROOT / ".github").rglob("*.yml")) + list((ROOT / "scripts").glob("*.sh")):
    text = path.read_text()
    for banned in ("git tag -d", "git tag -f", "push --force", "push -f", "--force-with-lease", "git push origin :refs/tags", "git push --delete"):
        assert banned not in text, (path.name, banned)
assert rules["branches"] == ["main"] and rules["tagFormat"] == "v${version}", "one branch, tags are vX.Y.Z, no prerelease channel"
assert not any(isinstance(b, dict) and b.get("prerelease") for b in rules["branches"]) and "channel" not in json.dumps(rules["branches"])
# the bump rules: breaking and feat raise the minor below 1.0, fix perf revert the patch; test, docs, chore, ci, style, refactor, build do not release
analyzer = next(p for p in rules["plugins"] if isinstance(p, list) and p[0].endswith("commit-analyzer"))[1]["releaseRules"]
got = {(r.get("type") or "breaking"): r["release"] for r in analyzer}
assert got == {"breaking": "minor", "feat": "minor", "fix": "patch", "perf": "patch", "revert": "patch"}, got
# the changelog commit is skipped by ci and is the only thing semantic-release commits
git_plugin = next(p for p in rules["plugins"] if isinstance(p, list) and p[0].endswith("/git"))[1]
assert git_plugin["assets"] == ["CHANGELOG.md"] and "[skip ci]" in git_plugin["message"]
# the docs say what the workflow does, and how 1.0.0 would be reached
doc = (ROOT / "docs/RELEASING.md").read_text()
assert "Going to 1.0.0" in doc and "dry run" in doc and "never moved or deleted" in doc and "no pre-release channel" in doc
print("ok: release route")
