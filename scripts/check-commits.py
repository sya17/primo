#!/usr/bin/env python3
"""Check commit messages against Conventional Commits: the format the release tool reads to pick the next version.

    check-commits.py                  the last commit
    check-commits.py A..B             every commit in a range (CI passes the range that was pushed)
    check-commits.py --message FILE   one message file (a commit-msg hook)
    check-commits.py --title TEXT     a pull request title (a squash merge turns it into the commit)

Format: type(scope)!: description. Types: feat (new minor version), fix, perf, revert (new patch version), and refactor, docs, style, test,
build, ci, chore (no release). A "!" or a "BREAKING CHANGE:" line marks an incompatible change. See docs/RELEASING.md.
Exit codes: 0 fine, 1 a message does not follow the format, 2 usage or git error.
"""
import re
import subprocess
import sys

TYPES = ("feat", "fix", "perf", "revert", "refactor", "docs", "style", "test", "build", "ci", "chore")
TRAILERS = ("BREAKING CHANGE", "BREAKING-CHANGE", "Refs", "Fixes", "Closes", "Reverts")
HEADER = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9][a-z0-9-]*)\))?(?P<bang>!)?: (?P<desc>\S.*)$")
TRAILER = re.compile(r"^(?P<token>[A-Za-z][A-Za-z -]*?)(?::\s|\s#)\S")
MAX_HEADER = 72


def check_header(header):
    problems = []
    m = HEADER.match(header)
    if not m:
        hint = ' Git\'s own "Revert …" message is not accepted: write "revert: <what>".' if header.startswith("Revert") else ""
        return [f'"{header}" is not "type(scope): description" (types: {", ".join(TYPES)}).{hint}']
    if m["type"] not in TYPES:
        problems.append(f'unknown type "{m["type"]}" (types: {", ".join(TYPES)})')
    if len(header) > MAX_HEADER:
        problems.append(f"the first line is {len(header)} characters, the limit is {MAX_HEADER}")
    if header.rstrip().endswith("."):
        problems.append("the first line must not end with a full stop")
    return problems


def check_message(message):
    """A list of problems with one commit message; empty when it is fine."""
    lines = message.strip("\n").splitlines()
    if not lines:
        return ["the message is empty"]
    problems = check_header(lines[0])
    if len(lines) > 1 and lines[1].strip():
        problems.append("the second line must be empty (the body starts on the third)")
    paragraphs = [p for p in re.split(r"\n\s*\n", message.strip("\n")) if p.strip()]
    if len(paragraphs) > 1:
        last = [ln for ln in paragraphs[-1].splitlines() if ln.strip()]
        found = [TRAILER.match(ln) for ln in last]
        if found and all(found):
            for m in found:
                if m["token"] not in TRAILERS:
                    problems.append(f'unknown footer "{m["token"]}" (allowed: {", ".join(TRAILERS)}); write other notes as a sentence in the body')
    return problems


def commits_in(rev_range):
    """(short hash, message) for each non-merge commit in a range. Raises RuntimeError when git fails."""
    cmd = ["git", "log", "--no-merges", "--format=%h%x00%B%x01", rev_range] if ".." in rev_range else ["git", "log", "-1", "--no-merges", "--format=%h%x00%B%x01", rev_range]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip() or "git log failed")
    return [tuple(chunk.strip("\n").split("\0", 1)) for chunk in out.stdout.split("\x01") if chunk.strip()]


def main(argv):
    try:
        if argv[:1] == ["--message"] and len(argv) == 2:
            with open(argv[1], encoding="utf-8") as f:
                text = "".join(ln for ln in f if not ln.startswith("#"))
            items = [("message", text)]
        elif argv[:1] == ["--title"] and len(argv) == 2:
            items = [("title", argv[1])]
        elif len(argv) <= 1 and not (argv and argv[0].startswith("-")):
            items = commits_in(argv[0] if argv else "HEAD")
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except (OSError, RuntimeError) as e:
        print(f"check-commits: {e}", file=sys.stderr)
        return 2
    bad = 0
    for ref, message in items:
        problems = check_message(message)
        for p in problems:
            print(f"{ref}: {p}", file=sys.stderr)
        bad += bool(problems)
    if bad:
        print(f"{bad} of {len(items)} commit message(s) do not follow Conventional Commits (docs/RELEASING.md).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
