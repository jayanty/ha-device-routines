"""Keep instance data out of the public repository (PRD Section 11.3, TECH_SPEC Section 8).

Three places run this check. The pre commit hook runs `--staged` on the staged content and
`--commit-msg` on the message, both against the local denylist (built from the instance's
registries by `tools/make_denylist.py`) and the generic patterns. CI runs `--ci`, where no
denylist exists, with the generic patterns only. `--files` scans given paths and exists
for tests and for checking a document by hand.

The generic patterns are the shapes instance data takes whatever the home: Home Assistant
long lived access tokens, GitHub tokens, private IPv4 addresses, MAC addresses, `.local`
host names, email addresses and the 32 character hexadecimal ids Home Assistant gives
registry entries, the last one outside the anonymized fixtures. `tools/privacy_allowlist.txt`
lists the intentional exceptions.

Findings never print the matched text in full. CI logs are public, and a hook that echoed
the private name it just refused would be undoing its own work.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DENYLIST_PATH = Path("local/denylist.txt")
ALLOWLIST_PATH = Path("tools/privacy_allowlist.txt")
PRIVATE_CONTEXT_PATH = Path("CLAUDE.local.md")
FIXTURES_PREFIX = "tests/fixtures/"
COMMIT_MESSAGE_LABEL = "commit message"

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_CONFIGURATION = 2

# The anonymizer replaces MAC addresses with locally administered ones in this range, which
# no real device carries, so the address pattern below leaves the range alone.
SYNTHETIC_MAC_PREFIX = "02:00:00:00:00:"

GENERIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "home_assistant_token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    ),
    (
        "github_token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})\b"),
    ),
    (
        "private_ipv4",
        re.compile(
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
            r"|192\.168\.\d{1,3}\.\d{1,3})\b"
        ),
    ),
    (
        "mac_address",
        re.compile(r"\b(?!02:00:00:00:00:)(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    ),
    (
        "local_hostname",
        re.compile(r"\b[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.local(?![\w.-])"),
    ),
    ("email_address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)
HEX_ID_PATTERN: tuple[str, re.Pattern[str]] = ("hex_id", re.compile(r"\b[0-9a-f]{32}\b"))
DENYLIST_KIND = "denylist"


@dataclass(frozen=True)
class Finding:
    """One match: which rule, on which 1-based line, with the text masked."""

    kind: str
    line: int
    excerpt: str


def mask(value: str) -> str:
    """Hide the middle of a matched string, keeping only its shape and edges."""
    if len(value) <= 6:  # noqa: PLR2004
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 5) + value[-2:]


def load_lines(path: Path) -> list[str]:
    """Return the non blank, non comment lines of a list file, or [] when it is missing."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def load_allowlist(path: Path) -> frozenset[str]:
    """Return the allowlist as lowercase strings."""
    return frozenset(line.lower() for line in load_lines(path))


def phrase_pattern(token: str) -> re.Pattern[str]:
    """Match a denylisted token however its words are separated or cased.

    `Top Floor Hallway` also matches `top_floor_hallway` and `top-floor-hallway`, which is
    how the same area name appears in entity ids and slugs. Word boundaries keep `Zorblax`
    from matching `zorblaxian` and an entity id from matching a longer one.
    """
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", token) if part]
    body = r"[^A-Za-z0-9]+".join(re.escape(part) for part in parts)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])", re.IGNORECASE)


def _words(text: str) -> list[str]:
    """Split text into lowercase alphanumeric words."""
    return [word for word in re.split(r"[^A-Za-z0-9]+", text.lower()) if word]


Entry = tuple[str, re.Pattern[str]]


@dataclass
class Denylist:
    """Compiled denylist tokens, filed under each token's rarest word.

    A real denylist holds thousands of entity ids, and running every pattern over every
    line would make the hook take minutes. A token can only match a line that contains
    all of its words, so each token is filed under the word fewest other tokens share,
    and a line is checked only against the tokens filed under the words it contains.
    """

    entries: list[Entry] = field(default_factory=list)
    index: dict[str, list[Entry]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def candidates(self, line: str) -> list[Entry]:
        """Return the tokens that could occur in `line`, longest first."""
        found: list[Entry] = []
        for word in set(_words(line)):
            found.extend(self.index.get(word, ()))
        return sorted(found, key=lambda entry: (-len(entry[0]), entry[0]))

    def search(self, line: str) -> Iterator[tuple[str, re.Match[str]]]:
        """Yield every (token, match) in `line`."""
        for token, pattern in self.candidates(line):
            for match in pattern.finditer(line):
                yield token, match


def compile_denylist(tokens: Iterable[str]) -> Denylist:
    """Compile every denylisted token and file it under its rarest word."""
    entries: list[Entry] = []
    seen: set[str] = set()
    for token in tokens:
        cleaned = token.strip()
        if cleaned and cleaned not in seen and _words(cleaned):
            seen.add(cleaned)
            entries.append((cleaned, phrase_pattern(cleaned)))
    frequency = Counter(word for token, _ in entries for word in set(_words(token)))
    index: defaultdict[str, list[Entry]] = defaultdict(list)
    for token, pattern in entries:
        rarest = min(set(_words(token)), key=lambda word: (frequency[word], -len(word), word))
        index[rarest].append((token, pattern))
    return Denylist(entries, dict(index))


def scan_text(
    text: str,
    *,
    denylist: Denylist,
    allowlist: frozenset[str] = frozenset(),
    hex_ids: bool = True,
) -> list[Finding]:
    """Return every denylist and generic pattern match in `text`, line by line."""
    rules: list[tuple[str, re.Pattern[str]]] = list(GENERIC_PATTERNS)
    if hex_ids:
        rules.append(HEX_ID_PATTERN)
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        matches = [(DENYLIST_KIND, match) for _token, match in denylist.search(line)]
        matches.extend((kind, match) for kind, pattern in rules for match in pattern.finditer(line))
        for kind, match in matches:
            if match.group(0).lower() in allowlist:
                continue
            findings.append(Finding(kind=kind, line=line_number, excerpt=mask(match.group(0))))
    return findings


def scan_path(
    relative: str,
    text: str,
    denylist: Denylist,
    allowlist: frozenset[str] = frozenset(),
) -> list[Finding]:
    """Scan one file's text; registry shaped ids are allowed inside the anonymized fixtures."""
    inside_fixtures = relative.replace("\\", "/").startswith(FIXTURES_PREFIX)
    return scan_text(text, denylist=denylist, allowlist=allowlist, hex_ids=not inside_fixtures)


# --------------------------------------------------------------------------------------
# Reading content
# --------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> bytes:
    """Run git in `root` and return its standard output."""
    completed = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return completed.stdout


def _decode(data: bytes) -> str | None:
    """Return text for a text blob, or None for anything binary."""
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def staged_files(root: Path) -> list[str]:
    """Return the paths staged for commit (added, copied, modified or renamed)."""
    raw = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [name for name in raw.decode("utf-8").split("\0") if name]


def staged_text(root: Path, relative: str) -> str | None:
    """Return the staged content of one path, not the working tree's, or None if binary."""
    return _decode(_git(root, "show", f":{relative}"))


def tracked_files(root: Path) -> list[str]:
    """Return every path git tracks under `root`."""
    raw = _git(root, "ls-files", "-z")
    return [name for name in raw.decode("utf-8").split("\0") if name]


def _read_text(path: Path) -> str | None:
    """Return a file's text, or None when it is missing or binary."""
    try:
        return _decode(path.read_bytes())
    except OSError:
        return None


# --------------------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------------------


def _report(label: str, findings: Iterable[Finding]) -> int:
    """Print findings in `label:line: kind: masked` form and count them."""
    count = 0
    for finding in findings:
        print(f"{label}:{finding.line}: {finding.kind}: {finding.excerpt}")
        count += 1
    return count


def run_staged(root: Path, denylist: Denylist, allowlist: frozenset[str]) -> int:
    """Check the staged content of every staged text file."""
    total = 0
    for relative in staged_files(root):
        text = staged_text(root, relative)
        if text is None:
            continue
        total += _report(relative, scan_path(relative, text, denylist, allowlist))
    return EXIT_FINDINGS if total else EXIT_CLEAN


def run_commit_message(path: Path, denylist: Denylist, allowlist: frozenset[str]) -> int:
    """Check a commit message, ignoring git's own comment lines."""
    text = _read_text(path) or ""
    kept = "\n".join("" if line.startswith("#") else line for line in text.splitlines())
    findings = scan_text(kept, denylist=denylist, allowlist=allowlist)
    return EXIT_FINDINGS if _report(COMMIT_MESSAGE_LABEL, findings) else EXIT_CLEAN


def run_ci(root: Path, allowlist: frozenset[str]) -> int:
    """Check every tracked file against the generic patterns only."""
    total = 0
    for relative in tracked_files(root):
        text = _read_text(root / relative)
        if text is None:
            continue
        total += _report(relative, scan_path(relative, text, compile_denylist([]), allowlist))
    return EXIT_FINDINGS if total else EXIT_CLEAN


def run_files(
    root: Path, paths: Iterable[Path], denylist: Denylist, allowlist: frozenset[str]
) -> int:
    """Check the given files as they are on disk."""
    total = 0
    for path in paths:
        text = _read_text(path)
        if text is None:
            continue
        try:
            relative = str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            relative = str(path)
        total += _report(relative, scan_path(relative, text, denylist, allowlist))
    return EXIT_FINDINGS if total else EXIT_CLEAN


def _load_denylist(root: Path) -> Denylist | None:
    """Return the compiled denylist, or None when this clone must have one and does not.

    A clone that carries `CLAUDE.local.md` is connected to a real instance, and committing
    from it without the denylist that instance generates would defeat the whole check.
    """
    path = root / DENYLIST_PATH
    if not path.is_file():
        if (root / PRIVATE_CONTEXT_PATH).exists():
            return None
        return compile_denylist([])
    return compile_denylist(load_lines(path))


def build_parser() -> argparse.ArgumentParser:
    """Build the command line: exactly one mode, plus the repository root."""
    parser = argparse.ArgumentParser(description="Keep instance data out of the repository.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check the staged content")
    mode.add_argument("--commit-msg", type=Path, metavar="FILE", help="check a commit message")
    mode.add_argument("--ci", action="store_true", help="generic patterns over tracked files")
    mode.add_argument("--files", nargs="+", type=Path, metavar="PATH", help="check these files")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one mode and return 0 (clean), 1 (findings) or 2 (configuration problem)."""
    args = build_parser().parse_args(argv)
    root: Path = args.root
    allowlist = load_allowlist(root / ALLOWLIST_PATH)
    if args.ci:
        return run_ci(root, allowlist)
    denylist = _load_denylist(root)
    if denylist is None:
        print(
            f"{DENYLIST_PATH} is missing but {PRIVATE_CONTEXT_PATH} exists: this clone is "
            "connected to a real instance. Capture the registries and run "
            "`python -m tools.make_denylist` before committing."
        )
        return EXIT_CONFIGURATION
    if args.staged:
        return run_staged(root, denylist, allowlist)
    if args.commit_msg is not None:
        return run_commit_message(args.commit_msg, denylist, allowlist)
    return run_files(root, args.files, denylist, allowlist)


if __name__ == "__main__":
    sys.exit(main())
