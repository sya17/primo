# Versions, branches and releases

Primo follows [Semantic Versioning](https://semver.org) and [Conventional Commits](https://www.conventionalcommits.org). The version is not
typed by hand: the commit messages decide it, a tool reads them, and a release is cut by pressing one button.

## What a version number promises

Primo is a desktop, not a library, so "the interface" is what you rely on when you update:

- the keybindings in [KEYBINDINGS.md](KEYBINDINGS.md), the `primo` and `hypr-theme` commands, their options, exit codes and `--json` output;
- the keys of `themes/<name>/theme.conf` and the files Primo reads from `~/.config/primo/`;
- the flags of `scripts/install.sh` and what it changes outside the repository.

An incompatible change to any of these is a **breaking change**. A new look, a new page or a faster window is not.

Until 1.0.0 the number is `0.MINOR.PATCH` and anything may change, but the rules below still hold: a breaking change raises the minor
version, and the changelog says so. 1.0.0 is a decision for the maintainer, taken when the configuration format and the update path are stable.

## Commit messages

```
type(scope): short description in the imperative, no full stop, 72 characters at most

Optional body: what changed and why, in plain sentences.

BREAKING CHANGE: what breaks and what to do instead.
```

| Type | Use for | Next version |
| --- | --- | --- |
| `feat` | something new you can use | minor |
| `fix` | something that was wrong | patch |
| `perf` | the same thing, faster or lighter | patch |
| `revert` | undoing an earlier commit | patch |
| `refactor`, `docs`, `style`, `test`, `build`, `ci`, `chore` | no change for the user | none |

Add `!` after the type or scope (`feat(config)!: …`), or a `BREAKING CHANGE:` line in the footer, for an incompatible change. The scope is
optional and names the part: `bar`, `launcher`, `settings`, `hub`, `activity`, `modes`, `theme`, `wallpaper`, `install`, `cli`, `doctor`, `docs`, `ci`.
The footers `Refs`, `Fixes` and `Closes` are accepted; write anything else as a sentence in the body.

The subject of a `feat` or `fix` becomes a line in the changelog, so write it for the person who updates: "fix(bar): keep the VPN icon inside
the bar", not "fix: padding".

`scripts/check-commits.py` checks the format, `scripts/check.sh` tests it, and CI runs it on every push to `main` (and on the title of a
pull request, which a squash merge turns into the commit).

## Branches

- `main` always works: CI is green and it can be released at any time. Small changes go straight to `main` after `scripts/check.sh` passes.
- Bigger work lives on a short-lived branch named `type/topic` (`feat/launcher-providers`, `fix/vpn-icon`), is rebased on `main`, and is merged
  with a squash. The history stays linear. Delete the branch after the merge.
- Several people or tools working at once should use `git worktree add ../primo-topic -b feat/topic` instead of switching branches in one
  folder.
- There are no long-lived `develop` or `release` branches and no pre-release channel. After 1.0.0, a `1.x` branch is how an old line gets a
  fix; the release tool supports it with one line in `.releaserc.json`.

## Tags and releases

A tag `vMAJOR.MINOR.PATCH` marks a release, and it is never moved or deleted. A bad release is fixed forward with the next patch release.

## The pipeline

```
push or pull request ──▶ ci: checks, docs links, commit messages
                          │
          Actions > release > Run workflow (by hand, from main)
                          ▼
   ci must be green for this commit ─▶ semantic-release reads the commits since the last tag
                          │
     dry run (default): prints the next version and the notes
     real run: the tag, the GitHub release, and one commit that adds the notes to CHANGELOG.md
```

- `ci.yml` has read-only rights. `release.yml` is the only workflow that can write, and only when someone starts it.
- The release tools are installed from `.github/release/package-lock.json` with install scripts off, so what runs is what was reviewed. To update
  them, change the versions in `.github/release/package.json`, run `npm install --package-lock-only` there, and read the diff.
- The changelog commit uses the repository owner's noreply identity, like every other commit. No bot account is involved.
- The rules for which commit raises which version, and the layout of the notes, are in `.releaserc.json`.

## Cutting a release

1. Look at what would be released: **Actions > release > Run workflow**, leave "Dry run" ticked. The log shows the next version and the notes.
   "There are no relevant changes" means no `feat`, `fix`, `perf` or `revert` commit since the last tag.
2. If the version or the notes are wrong, fix the commit history of `main` by adding commits, not by rewriting it, and run the dry run again.
3. Run again with "Dry run" cleared. Then `git fetch --tags` and check the release page.

The commits that came before this pipeline do not follow the format, so the first release is judged only by what follows it. Their notes are
written by hand under "Unreleased" in [CHANGELOG.md](../CHANGELOG.md); move them under the new version heading once.

## Repository settings (maintainer)

These are settings on GitHub, not files, so they are not applied by a commit. They keep an accident from rewriting history or a tag.

```bash
# One merge method (squash, with the pull request title as the message), and delete merged branches
gh api -X PATCH repos/sya17/primo -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=BLANK

# A release tag cannot be moved or deleted
gh api repos/sya17/primo/rulesets --input - <<'JSON'
{"name": "release tags", "target": "tag", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
 "rules": [{"type": "update"}, {"type": "deletion"}, {"type": "non_fast_forward"}]}
JSON

# main cannot be deleted, force-pushed over, or given merge commits
gh api repos/sya17/primo/rulesets --input - <<'JSON'
{"name": "main", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
 "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "required_linear_history"}]}
JSON
```

To rewrite history on purpose (rare), disable the `main` ruleset first, and enable it again afterwards.
