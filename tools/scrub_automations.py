"""Strip the free text out of captured automation configs before they are anonymized.

Run as `python -m tools.scrub_automations --output local/captures/automations/scrubbed
local/captures/automations`, then `tools.anonymize` over the output (TECH_SPEC 8).

The anonymizer replaces the tokens on the denylist; it cannot know that an alias, a
description, a note, a notification text, a URL or a webhook id describes a home. This
step keeps every structural key and value the summary engine reads (triggers, conditions,
actions, times, durations, modes, templates) and replaces the rest with generic stand ins:

- files become `automation_NN.json` and top level ids `automation_NN`;
- top level aliases become `Automation NN`, nested aliases `Step`, non empty descriptions
  `Description.`, notes are dropped, `stop` texts become `Stopped.`;
- `title`, `message` and `name` strings become `Title`, `Message` and `Name`;
- webhook ids, URLs and notify services become generic, consistently across files;
- 32 character registry ids under `entity_id` (device triggers, conditions and actions
  refer to entities by registry id) become synthetic ids, consistently across files.

Input is a directory holding `config/<name>.json` (the loaded entity's config, from the
`automation/config` WebSocket command) and optionally `related/<name>.json` (the
`search/related` result for the same automation). Each output file holds `config` and,
when captured, `related` limited to entities, devices, areas, floors and labels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

REGISTRY_ID = re.compile(r"\A[0-9a-f]{32}\Z")
URL = re.compile(r"[a-z][a-z0-9+.-]*://[^\s'\"{}]+", re.IGNORECASE)
NOTIFY_SERVICE = re.compile(r"\Anotify\.(?!notify\Z|send_message\Z|persistent_notification\Z)\w+\Z")
FIXED_TEXT = {
    "alias": "Step",
    "stop": "Stopped.",
    "title": "Title",
    "message": "Message",
    "name": "Name",
}
RELATED_KEYS = ("entity", "device", "area", "floor", "label")
FAKE_URL = "https://example.invalid/path"


class Scrubber:
    """Replaces free text and opaque ids, keeping one stand in per original across files."""

    def __init__(self) -> None:
        self.registry_ids: dict[str, str] = {}
        self.notify_services: dict[str, str] = {}
        self.webhooks: dict[str, str] = {}

    def _registry_id(self, value: str) -> str:
        if value not in self.registry_ids:
            self.registry_ids[value] = f"ee{len(self.registry_ids) + 1:030x}"
        return self.registry_ids[value]

    def _notify(self, value: str) -> str:
        if value not in self.notify_services:
            self.notify_services[value] = f"notify.phone_{len(self.notify_services) + 1}"
        return self.notify_services[value]

    def _webhook(self, value: str) -> str:
        if value not in self.webhooks:
            self.webhooks[value] = f"webhook_{len(self.webhooks) + 1}"
        return self.webhooks[value]

    def _entity_ids(self, value: Any) -> Any:
        if isinstance(value, str) and REGISTRY_ID.match(value):
            return self._registry_id(value)
        if isinstance(value, list):
            return [self._entity_ids(item) for item in value]
        return value

    def _string(self, value: str) -> str:
        if NOTIFY_SERVICE.match(value):
            return self._notify(value)
        return URL.sub(FAKE_URL, value)

    def _pair(self, key: str, value: Any) -> Any:
        """Scrub one mapping entry by its key."""
        if isinstance(value, str):
            if key in FIXED_TEXT:
                return FIXED_TEXT[key]
            if key == "description":
                return "Description." if value else ""
            if key == "webhook_id":
                return self._webhook(value)
        if key == "entity_id":
            return self._entity_ids(self.scrub(value))
        return self.scrub(value)

    def scrub(self, node: Any) -> Any:
        """Return a scrubbed copy of one nested config node; notes are dropped."""
        if isinstance(node, dict):
            return {key: self._pair(key, value) for key, value in node.items() if key != "note"}
        if isinstance(node, list):
            return [self.scrub(item) for item in node]
        if isinstance(node, str):
            return self._string(node)
        return node

    def automation(self, number: int, config: dict[str, Any]) -> dict[str, Any]:
        """Scrub one top level automation config and give it a generic id and alias."""
        scrubbed: dict[str, Any] = self.scrub(config)
        scrubbed["id"] = f"automation_{number:02d}"
        scrubbed["alias"] = f"Automation {number:02d}"
        return scrubbed

    def related(self, related: dict[str, Any]) -> dict[str, list[str]]:
        """Keep the reference helper results the summary uses, with ids made generic."""
        kept: dict[str, list[str]] = {}
        for key in RELATED_KEYS:
            if key in related:
                kept[key] = sorted(self._entity_ids(list(related[key])))
        return kept


def main(argv: Sequence[str] | None = None) -> int:
    """Scrub every captured config in the input directory into the output directory."""
    parser = argparse.ArgumentParser(description="Strip free text from automation captures.")
    parser.add_argument("--output", type=Path, required=True, help="directory to write into")
    parser.add_argument("input", type=Path, help="directory holding config/ and related/")
    args = parser.parse_args(argv)

    configs = sorted((args.input / "config").glob("*.json"))
    if not configs:
        print(f"no configs under {args.input / 'config'}")
        return 2
    scrubber = Scrubber()
    args.output.mkdir(parents=True, exist_ok=True)
    for number, path in enumerate(configs, start=1):
        record: dict[str, Any] = {
            "config": scrubber.automation(number, json.loads(path.read_text(encoding="utf-8")))
        }
        related_path = args.input / "related" / path.name
        if related_path.is_file():
            record["related"] = scrubber.related(
                json.loads(related_path.read_text(encoding="utf-8"))
            )
        destination = args.output / f"automation_{number:02d}.json"
        destination.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(f"scrubbed {len(configs)} automations into {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
