"""Turn raw captures into fixtures with deterministic fake ids and names (TECH_SPEC 8).

Run as `python -m tools.anonymize --output tests/fixtures/automations local/captures/automations`.
Every denylisted token is replaced by a generic stand in of the same kind: an entity id
keeps its domain (`switch.example_switch_1`), a device becomes `Device 1`, an area
`Area 1`, a registry id another 32 character id, a MAC address a locally administered one.
Times, domains, structure and automation shapes are untouched, which is what makes the
result usable as a golden corpus.

The mapping is kept in `local/anonymize_map.json` so the same token always becomes the
same stand in, across files and across runs. The output is checked before it is written:
if any denylisted token survives, nothing is reported as done.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, Any

from tools.privacy_check import SYNTHETIC_MAC_PREFIX, Denylist, compile_denylist, load_lines

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

DEFAULT_DENYLIST = Path("local/denylist.txt")
DEFAULT_MAP = Path("local/anonymize_map.json")

EXIT_OK = 0
EXIT_SURVIVORS = 1
EXIT_CONFIGURATION = 2

ENTITY_ID = re.compile(r"\A[a-z_]+\.[a-z0-9_]+\Z")
HEX_ID = re.compile(r"\A[0-9a-f]{32}\Z")
MAC = re.compile(r"\A(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\Z")

# How each category of token is replaced; `{n}` is a counter within the category.
FORMATS: dict[str, str] = {
    "area": "Area {n}",
    "floor": "Floor {n}",
    "label": "Label {n}",
    "person": "Person {n}",
    "device": "Device {n}",
    "host": "example-host-{n}",
    "serial": "serial-{n}",
    "mac": SYNTHETIC_MAC_PREFIX + "{n:02x}",
    "name": "Example name {n}",
}
ENTITY_FORMAT = "{domain}.example_{domain}_{n}"


def normalize(token: str) -> str:
    """Return the form two spellings of one token share: lowercase words, space separated."""
    return " ".join(word for word in re.split(r"[^A-Za-z0-9]+", token.lower()) if word)


def categorize(registries: Mapping[str, Any]) -> dict[str, str]:
    """Map each registry name to its kind, so the replacement says what the token was.

    Earlier kinds win when the same name appears twice: an area named like a device is
    still an area, and a device's name beats the entity names derived from it.
    """
    categories: dict[str, str] = {}

    def take(records: Iterable[Mapping[str, Any]], category: str, *fields: str) -> None:
        for record in records:
            for name in fields:
                value = record.get(name)
                if isinstance(value, str) and value.strip():
                    categories.setdefault(normalize(value), category)

    take(registries.get("areas", []), "area", "id", "name")
    take(registries.get("floors", []), "floor", "floor_id", "name")
    take(registries.get("labels", []), "label", "label_id", "name")
    take(registries.get("persons", []), "person", "name")
    take(registries.get("devices", []), "device", "name", "name_by_user")
    take(registries.get("devices", []), "serial", "serial_number")
    for device in registries.get("devices", []):
        for pair in device.get("identifiers", []) or []:
            if isinstance(pair, list | tuple) and len(pair) == 2 and isinstance(pair[1], str):  # noqa: PLR2004
                categories.setdefault(normalize(pair[1]), "serial")
    take(registries.get("entities", []), "name", "name", "original_name")
    for host in registries.get("hosts", []) or []:
        if isinstance(host, str):
            categories.setdefault(normalize(host), "host")
    return categories


def _shaped(matched: str, replacement: str) -> str:
    """Spell the replacement the way the matched text was spelled."""
    if " " in matched:
        return replacement
    if "-" in matched and "_" not in matched:
        return replacement.lower().replace(" ", "-")
    if "_" in matched or matched == matched.lower():
        return replacement.lower().replace(" ", "_")
    return replacement


@dataclass
class Anonymizer:
    """Replace denylisted tokens with stable, generic stand ins."""

    tokens: Sequence[str]
    mapping: dict[str, str]
    categories: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unique: dict[str, str] = {}
        for token in sorted(set(self.tokens), key=lambda t: (-len(t), t)):
            unique.setdefault(normalize(token), token)
        self._denylist: Denylist = compile_denylist(unique.values())
        self._by_key = {normalize(token): token for token in self.mapping}

    def _category(self, token: str) -> str:
        if ENTITY_ID.match(token):
            return "entity"
        if HEX_ID.match(token):
            return "id"
        if MAC.match(token):
            return "mac"
        return self.categories.get(normalize(token), "name")

    def _next_number(self, template: str) -> int:
        shape = (
            re.escape(template).replace(r"\{n\}", r"(\d+)").replace(r"\{n:02x\}", r"([0-9a-f]{2})")
        )
        pattern = re.compile(rf"\A{shape}\Z")
        taken = [match for value in self.mapping.values() if (match := pattern.match(value))]
        return len(taken) + 1

    def replacement(self, token: str) -> str:
        """Return the stand in for a token, allocating one the first time it is seen."""
        known = self._by_key.get(normalize(token))
        if known is not None:
            return self.mapping[known]
        category = self._category(token)
        if category == "entity":
            domain = token.split(".", 1)[0]
            template = ENTITY_FORMAT.replace("{domain}", domain)
            value = template.format(n=self._next_number(template))
        elif category == "id":
            value = hashlib.sha256(f"anonymize:{token}".encode()).hexdigest()[:32]
        else:
            template = FORMATS[category]
            value = template.format(n=self._next_number(template))
        self.mapping[token] = value
        self._by_key[normalize(token)] = token
        return value

    def _substitute(self, token: str) -> Callable[[re.Match[str]], str]:
        """Return the replacement function for one token, spelled like each match."""

        def substitute(match: re.Match[str]) -> str:
            return _shaped(match.group(0), self.replacement(token))

        return substitute

    def _anonymize_line(self, line: str) -> str:
        for token, pattern in self._denylist.candidates(line):
            line = pattern.sub(self._substitute(token), line)
        return line

    def anonymize(self, text: str) -> str:
        """Return `text` with every denylisted token replaced, longest tokens first."""
        return "\n".join(self._anonymize_line(line) for line in text.split("\n"))

    def surviving(self, text: str) -> list[str]:
        """Return the denylisted tokens that still match `text`, longest first."""
        found = {
            token for line in text.split("\n") for token, _match in self._denylist.search(line)
        }
        return sorted(found, key=lambda token: (-len(token), token))


def load_map(path: Path) -> dict[str, str]:
    """Return the saved mapping, or an empty one."""
    try:
        loaded: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return {}
    return {str(key): str(value) for key, value in loaded.items()}


def save_map(path: Path, mapping: Mapping[str, str]) -> None:
    """Write the mapping, sorted so a diff of it is readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(mapping.items())), indent=2) + "\n", encoding="utf-8")


def _input_files(inputs: Iterable[Path]) -> list[tuple[Path, Path]]:
    """Pair every input file with its output relative path."""
    pairs: list[tuple[Path, Path]] = []
    for given in inputs:
        if given.is_dir():
            pairs.extend(
                (path, path.relative_to(given))
                for path in sorted(given.rglob("*"))
                if path.is_file()
            )
        elif given.is_file():
            pairs.append((given, Path(given.name)))
    return pairs


def main(argv: Sequence[str] | None = None) -> int:
    """Anonymize files or directories into the output directory and save the mapping."""
    parser = argparse.ArgumentParser(description="Anonymize raw captures into fixtures.")
    parser.add_argument("--denylist", type=Path, default=DEFAULT_DENYLIST)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--registries", type=Path, help="registries capture, for categories")
    parser.add_argument("--output", type=Path, required=True, help="directory to write into")
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args(argv)

    if not args.denylist.is_file():
        print(f"the denylist {args.denylist} does not exist; run tools/make_denylist.py first")
        return EXIT_CONFIGURATION
    categories: dict[str, str] = {}
    if args.registries is not None:
        categories = categorize(json.loads(args.registries.read_text(encoding="utf-8")))
    anonymizer = Anonymizer(load_lines(args.denylist), load_map(args.map), categories)

    survivors = 0
    written = 0
    for source, relative in _input_files(args.inputs):
        try:
            text = source.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        result = anonymizer.anonymize(text)
        left = anonymizer.surviving(result)
        if left:
            survivors += len(left)
            print(f"{relative}: {len(left)} denylisted tokens survived; not written")
            continue
        destination = args.output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(result, encoding="utf-8")
        written += 1
    save_map(args.map, anonymizer.mapping)
    print(f"anonymized {written} files into {args.output}; mapping saved to {args.map}")
    return EXIT_SURVIVORS if survivors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
