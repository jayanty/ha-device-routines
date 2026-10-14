"""Build `local/denylist.txt` from a capture of the instance's registries (TECH_SPEC 8).

The capture, `local/captures/registries.json`, is written from read only MCP queries and
never leaves `local/`. Every token that identifies the home goes into the list: entity ids,
device ids, device, area, floor and label names and ids, person and user names, serial
numbers, identifiers, connections and host names.

What stays out is anything that identifies nothing. A single generic word such as
`Kitchen` or `Office`, or a stock phrase such as `Living Room`, names a kind of place that
every home has, and listing it would block the generic examples the documentation is
written with. Manufacturer and model are public product names and stay out too. A token
shorter than three characters would match everywhere and means nothing on its own.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

DEFAULT_CAPTURES = Path("local/captures/registries.json")
DEFAULT_OUTPUT = Path("local/denylist.txt")
MIN_LENGTH = 3

EXIT_OK = 0
EXIT_CONFIGURATION = 2

# Words that describe a kind of room, place, device or direction rather than a home,
# plus the nouns Home Assistant itself uses, which turn up as device and entity names.
_GENERIC_WORD_TEXT = """
    alarm alexa assistant automation automations backup bar birdseye bridge buttons calendars
    cameras chime cloud core counters covers dates datetimes device devices doorbell driveway
    dryer entities entrance forecast google groups hacs homeassistant humidifiers images
    integrations ipad iphone issues keypad lights locks mac macbook main nest numbers os
    package persons projector proxy refrigerator remotes repair repairs scenes scripts selects
    sensors sirens supervisor stt suite suns switches texts timers times todos tts update vacuums
    washer watch weather zones
    air attic back balcony basement bath bathroom bed bedroom blind blinds bottom bridge
    bulb button cabinet camera car ceiling chair charger closet coffee cool cooler corridor
    couch counter cover deck default den desk dimmer dining dishwasher door downstairs
    driveway dryer east energy entry entryway example family fan filter fireplace first
    floor foyer freezer fridge front garage garden gas gateway ground guest gym hall
    hallway heat heater home hot house hub humidifier humidity indoor inside island
    kettle kitchen lamp landing laundry led left level light lights little living lock
    loft lower main master microwave mirror modem motion mower mudroom new none north nursery
    occupancy office old outdoor outlet outside oven pantry patio pc phone playroom plug
    pool porch power presence printer pump purifier range refrigerator relay remote right
    roof room router scene second sensor server shade shades shed shower side sink small
    sofa south spa speaker sprinkler stairs stairway stove strip study sunroom switch table
    tablet temperature terrace test third thermostat toaster toilet top tub tv unknown
    upper upstairs utility vacuum valve wall washer watch water west window workshop yard
    zone
    """
GENERIC_WORDS: frozenset[str] = frozenset(_GENERIC_WORD_TEXT.split())

# Stock phrases made of generic words that every home has.
GENERIC_PHRASES: frozenset[str] = frozenset(
    {
        "living room",
        "dining room",
        "family room",
        "guest room",
        "master bedroom",
        "guest bedroom",
        "laundry room",
        "powder room",
        "mud room",
        "home office",
        "front door",
        "back door",
        "side door",
        "garage door",
        "front porch",
        "back porch",
        "front yard",
        "back yard",
        "hot tub",
        "ceiling fan",
        "air filter",
        "air purifier",
        "water heater",
        "first floor",
        "second floor",
        "third floor",
        "ground floor",
        "upper floor",
        "lower floor",
        "main floor",
        "top floor",
        "home assistant",
        "guest bathroom",
        "master bathroom",
        "wine cellar",
        "upper balcony",
        "back bedroom",
        "front bedroom",
        "first bedroom",
        "basement bedroom",
    }
)

# Integrations whose devices stand for software or a service, not for a thing in the home:
# their names and identifiers are public product names and slugs.
SOFTWARE_DOMAINS: frozenset[str] = frozenset(
    {
        "hassio",
        "hacs",
        "spook",
        "backup",
        "sun",
        "met",
        "google_translate",
        "co2signal",
        "device_links",
        "bermuda",
        "local_openai",
    }
)

# Entity ids the core itself creates on every install, and the prefixes of the ones that
# describe the core, the backup manager, the sun and the cloud rather than a device.
CORE_ENTITY_IDS: frozenset[str] = frozenset(
    {
        "sun.sun",
        "zone.home",
        "weather.forecast_home",
        "todo.shopping_list",
        "conversation.home_assistant",
        "stt.home_assistant_cloud",
        "tts.home_assistant_cloud",
        "tts.google_translate_en_com",
        "binary_sensor.remote_ui",
        "event.repair",
        "event.backup_automatic_backup",
        "button.homeassistant_restart",
        "button.homeassistant_reload",
        "button.ignore_all_issues",
        "button.unignore_all_issues",
    }
)
CORE_ENTITY_PREFIXES: tuple[str, ...] = (
    "sensor.sun_next_",
    "sensor.backup_",
    "update.home_assistant_",
    "switch.cloud_",
)


def _words(token: str) -> list[str]:
    """Split a token into lowercase words, however it was separated."""
    return [word for word in re.split(r"[^A-Za-z0-9]+", token.lower()) if word]


def is_generic(token: str) -> bool:
    """Report whether a token names a kind of thing rather than this home's thing."""
    words = _words(token)
    if not words:
        return True
    if len(words) == 1:
        return words[0] in GENERIC_WORDS or words[0].isdigit()
    return " ".join(words) in GENERIC_PHRASES


def _is_core_entity(entity_id: str) -> bool:
    """Report whether an entity id belongs to the core, an app or a plugin, not a device."""
    if entity_id in CORE_ENTITY_IDS or entity_id.startswith(CORE_ENTITY_PREFIXES):
        return True
    domain, _, object_id = entity_id.partition(".")
    if domain == "update" and object_id.endswith("_update"):
        return True  # apps and plugins; a device's firmware entity ends in _firmware
    return "_" not in object_id and is_generic(object_id)


def _is_software_device(device: Mapping[str, Any]) -> bool:
    """Report whether every identifier of a device points at a software integration."""
    domains = [
        pair[0]
        for pair in device.get("identifiers") or []
        if isinstance(pair, list | tuple) and pair and isinstance(pair[0], str)
    ]
    return bool(domains) and all(domain in SOFTWARE_DOMAINS for domain in domains)


def _values(pairs: object) -> Iterator[str]:
    """Yield the value half of identifier and connection pairs, skipping the domain half."""
    if not isinstance(pairs, list):
        return
    for pair in pairs:
        if isinstance(pair, list | tuple) and len(pair) == 2 and isinstance(pair[1], str):  # noqa: PLR2004
            yield pair[1]


def _fields(record: Mapping[str, Any], *names: str) -> Iterator[str]:
    """Yield the string values of the named fields of one registry record."""
    for name in names:
        value = record.get(name)
        if isinstance(value, str):
            yield value


def tokens_from_registries(data: Mapping[str, Any]) -> list[str]:
    """Return every identifying token in a registries capture, in capture order."""
    tokens: list[str] = []
    for entity in data.get("entities", []):
        entity_id = entity.get("entity_id")
        if isinstance(entity_id, str) and _is_core_entity(entity_id):
            continue
        tokens.extend(_fields(entity, "entity_id", "id", "name", "original_name", "device_id"))
    for device in data.get("devices", []):
        tokens.extend(_fields(device, "id"))
        if _is_software_device(device):
            continue
        tokens.extend(_fields(device, "name", "name_by_user", "serial_number"))
        tokens.extend(_values(device.get("identifiers")))
        tokens.extend(_values(device.get("connections")))
    for area in data.get("areas", []):
        tokens.extend(_fields(area, "id", "name"))
    for floor in data.get("floors", []):
        tokens.extend(_fields(floor, "floor_id", "name"))
    for label in data.get("labels", []):
        tokens.extend(_fields(label, "label_id", "name"))
    for person in data.get("persons", []):
        tokens.extend(_fields(person, "entity_id", "name"))
    tokens.extend(value for value in data.get("users", []) if isinstance(value, str))
    tokens.extend(value for value in data.get("hosts", []) if isinstance(value, str))
    # Tokens added by hand while reviewing the capture: a place name hiding in an entity
    # id, a family domain, a zone name. They are listed verbatim and never filtered.
    tokens.extend(value for value in data.get("extra", []) if isinstance(value, str))
    return tokens


def build_denylist(data: Mapping[str, Any], *, allow: Iterable[str] = ()) -> list[str]:
    """Return the sorted, case insensitively unique denylist for a capture."""
    allowed = {token.lower() for token in allow}
    kept: dict[str, str] = {}
    for raw in tokens_from_registries(data):
        token = raw.strip()
        if len(token) < MIN_LENGTH or is_generic(token) or token.lower() in allowed:
            continue
        kept.setdefault(token.lower(), token)
    return sorted(kept.values(), key=str.lower)


def main(argv: Sequence[str] | None = None) -> int:
    """Read the capture, write the denylist, and report only how many tokens it holds."""
    parser = argparse.ArgumentParser(description="Build the local privacy denylist.")
    parser.add_argument("--captures", type=Path, default=DEFAULT_CAPTURES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow", nargs="*", default=[], help="tokens to leave out")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.captures.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        print(f"cannot read the registries capture {args.captures}: {err}")
        return EXIT_CONFIGURATION
    tokens = build_denylist(data, allow=args.allow)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Generated by tools/make_denylist.py from the registries capture. One token per\n"
        "# line; the privacy check matches each one case insensitively with any separator.\n"
        "# This file is private and lives only under local/.\n"
    )
    args.output.write_text(header + "".join(f"{token}\n" for token in tokens), encoding="utf-8")
    print(f"wrote {len(tokens)} tokens to {args.output}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
