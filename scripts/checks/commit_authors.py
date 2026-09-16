"""Checks that every commit on a branch is authored by the repository owner
and carries no attribution trailers.

Contributor history is hard to correct after the fact, so this runs before
anything merges rather than after.
"""

from __future__ import annotations

import os
import subprocess
import sys

EXPECTED_NAME = "Yash Seth"
# Both forms of the same private address. The second is what GitHub uses for
# anything committed through the web interface once email privacy is on.
ALLOWED_EMAILS = {
    "yashseth2710@users.noreply.github.com",
    "133786228+yashseth2710@users.noreply.github.com",
}

BANNED_TRAILERS = ("co-authored-by", "generated with", "signed-off-by: claude")
SEPARATOR = "\x1e"


def commit_range() -> str:
    base = os.environ.get("BASE_SHA")
    head = os.environ.get("HEAD_SHA")
    if base and head:
        return f"{base}..{head}"
    return "HEAD~1..HEAD"


def main() -> int:
    rng = commit_range()
    fmt = f"%H{SEPARATOR}%an{SEPARATOR}%ae{SEPARATOR}%cn{SEPARATOR}%ce{SEPARATOR}%B"

    result = subprocess.run(
        ["git", "log", rng, f"--format={fmt}%x00"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Could not read commit range {rng}:\n{result.stderr}")
        return 1

    failures: list[str] = []
    count = 0

    for record in result.stdout.split("\x00"):
        record = record.strip()
        if not record:
            continue

        parts = record.split(SEPARATOR)
        if len(parts) < 6:
            continue

        sha, author_name, author_email, committer_name, committer_email, body = parts[:6]
        short = sha[:8]
        count += 1

        if author_name != EXPECTED_NAME:
            failures.append(f"{short}: author is {author_name!r}, expected {EXPECTED_NAME!r}")
        if author_email.lower() not in ALLOWED_EMAILS:
            failures.append(f"{short}: author email {author_email!r} is not recognised")
        if committer_name != EXPECTED_NAME:
            failures.append(
                f"{short}: committer is {committer_name!r}, expected {EXPECTED_NAME!r}"
            )
        if committer_email.lower() not in ALLOWED_EMAILS:
            failures.append(f"{short}: committer email {committer_email!r} is not recognised")

        lowered = body.lower()
        for trailer in BANNED_TRAILERS:
            if trailer in lowered:
                failures.append(f"{short}: message contains {trailer!r}")

    if failures:
        print("Commit authorship check failed:\n")
        for failure in failures:
            print(f"  {failure}")
        print()
        return 1

    print(f"All {count} commit(s) in {rng} are authored correctly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
