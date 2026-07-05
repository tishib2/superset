"""Detect test files with describe blocks."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def get_changed_files(repo_root: str) -> list[str]:
    """Return files changed between HEAD~1 and HEAD."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_root, "diff", "--name-only", "HEAD~1", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [f for f in result.stdout.splitlines() if f]
    except subprocess.CalledProcessError:
        # Initial commit: diff against empty tree
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_root,
                "diff",
                "--name-only",
                "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return [f for f in result.stdout.splitlines() if f]


def is_test_file(path: str) -> bool:
    """Return True if the file is a TypeScript test/spec file."""
    return bool(re.search(r"\.(test|spec)\.(ts|tsx)$", path))


def has_describe_block(file_path: Path) -> bool:
    """Return True if the file contains a describe( call."""
    try:
        content = file_path.read_text(encoding="utf-8")
        return "describe(" in content
    except OSError:
        return False


def detect_files(
    repo_root: str,
    targets: list[str],
    changed_files: list[str],
) -> list[str]:
    """Return changed test files that match targets and contain describe blocks."""
    matched: list[str] = []
    for changed in changed_files:
        if not is_test_file(changed):
            continue
        for target in targets:
            if target in changed:
                full_path = Path(repo_root) / changed
                if has_describe_block(full_path):
                    matched.append(changed)
                    break
    return matched
