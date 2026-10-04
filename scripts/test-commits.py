#!/usr/bin/env python3
"""Checks for the commit message linter: what it accepts, what it refuses, and ranges in a throwaway repository."""
import importlib.util
import os
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("cc", os.path.join(here, "check-commits.py"))
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

ok = ["feat: add the primo command", "fix(bar): clip the VPN icon", "feat(config)!: move reminders to XDG_DATA_HOME", "docs: explain the release steps",
      "chore(release): 0.2.0 [skip ci]", "perf(activity): sample less often\n\nOnly while the window is open.",
      "fix(install): keep the backup\n\nThe old folder is moved, not deleted.\n\nBREAKING CHANGE: --theme is now required.\nRefs #12", "ci: pin the checkout action\n"]
bad = ["Tidy .gitignore: sections", "feat add a thing", "Feat: capital type", "wip: half done", "feat: ends with a full stop.", "feat(Bar): capital scope",
       "feat: " + "x" * 80, "", "fix: first\nsecond line is not empty", 'Revert "feat: add the primo command"',
       "fix: body ok\n\nSome text.\n\nSigned-off-by: someone", "fix: body ok\n\nSome text.\n\nTested: on my laptop", "feat:no space", "feat: "]
for m in ok:
    assert not cc.check_message(m), (m, cc.check_message(m))
for m in bad:
    assert cc.check_message(m), m
assert "Revert" in cc.check_message('Revert "x"')[0] and "revert:" in cc.check_message('Revert "x"')[0]      # the hint says what to write instead

# ranges: only the commits in the range are judged; merges are skipped; a bad range is a usage error, not a pass
work = tempfile.mkdtemp()
def git(*a): return subprocess.run(["git", "-C", work, "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], capture_output=True, text=True, check=True).stdout
git("init", "-q", "-b", "main")
for msg in ("chore: root", "Old style message", "feat: first", "fix: second"):
    git("commit", "-q", "--allow-empty", "-m", msg)
os.chdir(work)
assert cc.main(["HEAD"]) == 0 and cc.main(["HEAD~2..HEAD"]) == 0, "feat and fix pass"
assert cc.main(["HEAD~3..HEAD"]) == 1, "the old message is inside this range"
assert cc.main(["nonexistent..HEAD"]) == 2
assert cc.main(["--title", "feat(cli): add the primo command"]) == 0 and cc.main(["--title", "Add the primo command"]) == 1
assert cc.main(["--bogus"]) == 2 and cc.main(["a", "b"]) == 2
msgfile = os.path.join(work, "MSG")
open(msgfile, "w").write("fix: from a file\n\n# a comment line the editor adds\n")
assert cc.main(["--message", msgfile]) == 0
open(msgfile, "w").write("whatever\n")
assert cc.main(["--message", msgfile]) == 1
print("commit message checks passed")
