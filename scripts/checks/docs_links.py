"""Verifies that relative links between markdown files actually resolve.

Catches the usual rot: a file renamed without updating the documents that
point at it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#", "tel:")


def markdown_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def main() -> int:
    broken: list[str] = []
    checked = 0

    for path in markdown_files():
        source = Path(path)
        text = source.read_text(encoding="utf-8")

        for line_no, line in enumerate(text.splitlines(), start=1):
            for target in LINK.findall(line):
                if target.startswith(SKIP_PREFIXES):
                    continue

                cleaned = target.split("#", 1)[0]
                if not cleaned:
                    continue

                checked += 1
                resolved = (source.parent / cleaned).resolve()
                if not resolved.exists():
                    broken.append(f"{path}:{line_no}: {target} does not resolve")

    if broken:
        print("Broken links:\n")
        for item in broken:
            print(f"  {item}")
        print()
        return 1

    print(f"All {checked} relative link(s) resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
