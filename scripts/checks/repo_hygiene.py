"""Guards the repository against things that should never be committed.

Runs on every pull request. Scans tracked files only, so anything ignored by
git is out of reach by definition.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# This file and the workflow that calls it necessarily contain the patterns
# they search for, and conventions.md documents the banned vocabulary.
SELF_EXCLUDED = {
    "scripts/checks/repo_hygiene.py",
    "scripts/checks/commit_authors.py",
    ".github/workflows/checks.yml",
    "docs/conventions.md",
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
    ".woff", ".woff2", ".ttf", ".otf", ".zip", ".gz",
}

FORBIDDEN_PATHS = [
    (re.compile(r"^CLAUDE\.md$"), "agent instructions must stay out of the repository"),
    (re.compile(r"^\.claude/"), "agent configuration must stay out of the repository"),
    (re.compile(r"^\.env$"), "environment files must never be committed"),
    (re.compile(r"^\.env\.(?!example$)"), "only .env.example may be committed"),
]

TOOLING_MENTIONS = [
    (re.compile(r"\bclaude\b", re.I), "assistant name"),
    (re.compile(r"\banthropic\b", re.I), "vendor name"),
    (re.compile(r"\bchatgpt\b", re.I), "assistant name"),
    (re.compile(r"\bcopilot\b", re.I), "assistant name"),
    (re.compile(r"co-authored-by", re.I), "attribution trailer"),
    (
        re.compile(
            r"generated (?:by|with|using)\s+(?:the\s+)?"
            r"(?:an?\s+)?(?:ai|assistant|llm|model|claude|chatgpt|copilot|gpt)",
            re.I,
        ),
        "attribution phrase",
    ),
    (re.compile(r"\bas an ai\b", re.I), "assistant phrasing"),
    (re.compile(r"\bai[- ]generated\b", re.I), "attribution phrase"),
]

SECRET_PATTERNS = [
    (re.compile(r"postgres(?:ql)?://[^:\s]+:[^@\s]+@"), "database URL with a password"),
    (re.compile(r"redis://[^:\s]+:[^@\s]+@"), "Redis URL with a password"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "API key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"\bvercel_blob_rw_[A-Za-z0-9_]{20,}"), "Blob token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (
        re.compile(r"""(?:secret|password|passwd|token|api_?key)\s*[=:]\s*["'][^"'\s]{12,}["']""", re.I),
        "hard-coded credential",
    ),
]

# Words that make prose read as machine-written rather than considered.
TIRED_WORDS = re.compile(
    r"\b(?:comprehensive|robust|seamless(?:ly)?|leverage[sd]?|streamline[sd]?|"
    r"delve|furthermore|moreover|cutting-edge|state-of-the-art|elevate[sd]?|"
    r"empower(?:s|ed)?|unlock(?:s|ed)?|myriad|plethora|testament to|"
    r"in today's .{0,20}landscape)\b",
    re.I,
)

PROSE_SUFFIXES = {".md", ".mdx"}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def read(path: str) -> str | None:
    p = Path(path)
    if p.suffix.lower() in BINARY_SUFFIXES:
        return None
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    files = tracked_files()

    for path in files:
        for pattern, reason in FORBIDDEN_PATHS:
            if pattern.search(path):
                failures.append(f"{path}: {reason}")

    for path in files:
        if path in SELF_EXCLUDED:
            continue
        content = read(path)
        if content is None:
            continue

        for line_no, line in enumerate(content.splitlines(), start=1):
            for pattern, reason in TOOLING_MENTIONS:
                match = pattern.search(line)
                if match:
                    failures.append(
                        f"{path}:{line_no}: {reason} -- {match.group(0)!r}"
                    )
            for pattern, reason in SECRET_PATTERNS:
                if pattern.search(line):
                    failures.append(f"{path}:{line_no}: looks like a {reason}")

            if Path(path).suffix.lower() in PROSE_SUFFIXES:
                match = TIRED_WORDS.search(line)
                if match:
                    warnings.append(f"{path}:{line_no}: {match.group(0)!r}")

    for warning in warnings:
        print(f"warning  {warning}")
    if warnings:
        print(f"\n{len(warnings)} tired word(s) found. Not fatal, but worth rewriting.\n")

    if failures:
        print("Repository hygiene check failed:\n")
        for failure in failures:
            print(f"  {failure}")
        print()
        return 1

    print(f"Repository hygiene check passed across {len(files)} tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
