"""Fail on the em dash character anywhere in the repository (TECH_SPEC Section 8).

The rule is absolute: code, comments, docs, UI strings and commit messages use a hyphen or
a colon instead. Run with file paths (the pre commit hook passes the staged text files) or
with no arguments to scan every file git tracks.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

EM_DASH = chr(0x2014)  # never the character itself: this file is checked too


@dataclass(frozen=True)
class Finding:
    """One em dash, located by file, 1-based line and 1-based column."""

    path: Path
    line: int
    column: int


def _read_text(path: Path) -> str | None:
    """Return the file's text, or None for a missing or binary file."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_files(paths: Iterable[Path]) -> list[Finding]:
    """Return every em dash in the given files, in file, line and column order."""
    findings: list[Finding] = []
    for path in paths:
        text = _read_text(Path(path))
        if text is None:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            findings.extend(
                Finding(path=Path(path), line=line_number, column=column + 1)
                for column, character in enumerate(line)
                if character == EM_DASH
            )
    return findings


def _git_ls_files(root: Path) -> list[str]:
    """Return the paths git tracks under `root`, relative to it."""
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True, text=True
    )
    return [name for name in completed.stdout.split("\0") if name]


def tracked_files(root: Path) -> list[Path]:
    """Return every tracked file under `root` as an absolute path."""
    return [root / name for name in _git_ls_files(root)]


def main(argv: Sequence[str] | None = None) -> int:
    """Scan the given files, or every tracked file, and report each em dash."""
    parser = argparse.ArgumentParser(description="Refuse the em dash character.")
    parser.add_argument("paths", nargs="*", type=Path, help="files to scan (default: git tracked)")
    args = parser.parse_args(argv)
    paths = args.paths or tracked_files(Path.cwd())
    findings = scan_files(paths)
    for finding in findings:
        print(f"{finding.path}:{finding.line}:{finding.column}: em dash (U+2014) is not allowed")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
