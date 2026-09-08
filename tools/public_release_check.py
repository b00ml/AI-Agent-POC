"""Fail-fast checks for files that must not enter a public release."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PATHS = (
    Path(".env"),
    Path("output"),
    Path("bank"),
    Path("data/source-docs"),
    Path("doc/homework"),
)
FORBIDDEN_SUFFIXES = (".backup", ".patch", ".tar.gz", ".zip", ".db")
SECRET_PATTERNS = {
    "qiheng-live-key": re.compile(r"qh_live_[A-Za-z0-9_-]{12,}"),
    "provider-key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "portal-password": re.compile(r"QIHENG_PORTAL_PASSWORD\s*=\s*(?!your_)[^\s#]+"),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [Path(item) for item in result.stdout.decode("utf-8").split("\0") if item]


def forbidden_path(path: Path) -> bool:
    return any(path == prefix or prefix in path.parents for prefix in FORBIDDEN_PATHS)


def main() -> int:
    failures: list[str] = []
    files = tracked_files()
    for path in files:
        if forbidden_path(path) or path.name.endswith(FORBIDDEN_SUFFIXES):
            failures.append(f"forbidden-path:{path.as_posix()}")
            continue
        full_path = ROOT / path
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                failures.append(f"secret-pattern:{name}:{path.as_posix()}")

    if failures:
        print("Public release check failed:")
        print("\n".join(sorted(set(failures))))
        return 1
    print(f"Public release check passed ({len(files)} tracked files inspected).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
