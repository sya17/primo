#!/usr/bin/env python3
"""Check the Markdown docs: every relative link, image and #anchor must point at something that exists.

Usage: scripts/check-docs.py        exits 1 and lists the broken ones (CI runs it)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "CHANGELOG.md", ROOT / "SECURITY.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"""\]\(([^)\s]+)\)|(?:src|srcset|href)="([^"]+)\"""")


def slug(heading):
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces to dashes."""
    text = re.sub(r"[`*_]|<[^>]+>", "", heading).strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", text))


def anchors(path):
    out = set()
    fence = False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"#{1,6}\s+(.*)", line)
        if m:
            out.add(slug(m.group(1)))
    return out


def main():
    bad = []
    for f in FILES:
        if not f.exists():
            continue
        text = f.read_text()
        for m in LINK.finditer(text):
            target = (m.group(1) or m.group(2)).strip()
            if re.match(r"(https?:|mailto:|data:)", target):
                continue
            path, _, frag = target.partition("#")
            dest = f if not path else (f.parent / path).resolve()
            if path and not dest.exists():
                bad.append(f"{f.relative_to(ROOT)}: missing file {target}")
            elif frag and dest.suffix == ".md" and slug(frag) not in anchors(dest):
                bad.append(f"{f.relative_to(ROOT)}: no heading for #{frag} in {dest.name}")
    for line in bad:
        print("  BROKEN ", line)
    print("docs links ok" if not bad else f"{len(bad)} broken link(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
