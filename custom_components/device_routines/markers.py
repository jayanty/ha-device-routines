"""The markers that make an automation a managed routine (TECH_SPEC 3.4, PRD Section 8).

Ownership needs both M1 (the automation id derived from the device id) and M2 (the
blueprint path). An alias, the `Routines` label or the category alone never count, so a
lookalike automation is never written. Seeded before Build A wave A1 with the functions
the adapter's write guard needs (decision L34); lane 1 added the presentation markers M3
to M8, the alias history rule, the config hash and the slugs.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Final
import unicodedata

AUTOMATION_ID_PREFIX: Final = "device_routines_"
BLUEPRINT_PATH: Final = "device_routines/device_routine.yaml"

LABEL_ID: Final = "routines"
LABEL_NAME: Final = "Routines"
CATEGORY_NAME: Final = "Device Routines"
ICON: Final = "mdi:calendar-clock"
# Marks a hand written automation a routine replaced (FR-M1, Build B).
REPLACED_LABEL_ID: Final = "replaced_by_routine"

ENTITY_ID_PREFIX: Final = "automation.routine_"
# The English alias template; the phrase table's `routine_alias` is the same text.
DEFAULT_ALIAS_TEMPLATE: Final = "Routine: {device}"

# Characters of the helper slug suffix taken from the automation id's hash.
_SUFFIX_LENGTH: Final = 6

_AUTOMATION_ID: Final = re.compile(r"device_routines_[0-9a-f]{12}")

# Latin letters with no Unicode decomposition, spelled the way Home Assistant's slugify
# spells them; every other non ASCII letter loses its accent through NFKD or is dropped.
_TRANSLITERATIONS: Final[Mapping[str, str]] = {
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "ø": "o",
    "Ø": "O",
    "œ": "oe",
    "Œ": "OE",
    "đ": "d",
    "Đ": "D",
    "ł": "l",
    "Ł": "L",
    "þ": "th",
    "Þ": "TH",
    "ð": "d",
    "Ð": "D",
}
_THOUSANDS: Final = re.compile(r"(?<=\d),(?=\d)")
_NOT_SLUG: Final = re.compile(r"[^a-z0-9]+")


def automation_id(device_id: str) -> str:
    """Return the routine automation id of a device (M1), stable across renames."""
    digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()
    return AUTOMATION_ID_PREFIX + digest[:12]


def has_routine_id(config: Mapping[str, Any]) -> bool:
    """Tell whether a config carries M1, whatever else it holds."""
    identifier = config.get("id")
    return isinstance(identifier, str) and _AUTOMATION_ID.fullmatch(identifier) is not None


def is_owned(config: Mapping[str, Any]) -> bool:
    """Tell whether a config carries both M1 and M2, the only proof of ownership."""
    if not has_routine_id(config):
        return False
    blueprint = config.get("use_blueprint")
    return isinstance(blueprint, Mapping) and blueprint.get("path") == BLUEPRINT_PATH


# --------------------------------------------------------------------------------------
# Presentation (M3 to M8): set on create, respected afterwards
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Presentation:
    """The alias (M3), description (M4) and icon (M7) a routine automation is created with."""

    alias: str
    description: str
    icon: str


def presentation(
    device_name: str, phrases: Mapping[str, str], *, formerly: bool = False
) -> Presentation:
    """Return the presentation of a device's routine from the phrase table.

    With `formerly`, the description is the one an automation keeps after the integration
    is removed with On removal set to keep (PRD 8.2).
    """
    description_key = "formerly_managed" if formerly else "routine_description"
    return Presentation(
        alias=phrases["routine_alias"].format(device=device_name),
        description=phrases[description_key].format(device=device_name),
        icon=ICON,
    )


def alias_is_generated(
    alias: str, names: Iterable[str], template: str = DEFAULT_ALIAS_TEMPLATE
) -> bool:
    """Tell whether an alias is still the generated one for the device's names.

    `names` holds the current device name and every earlier one the Store recorded, so
    the alias follows a rename while it is generated, and a person's own alias sticks.
    """
    return any(alias == template.format(device=name) for name in names)


def config_hash(config: Mapping[str, Any]) -> str:
    """Return the sha256 of an automation entry without its `id`, as canonical JSON."""
    entry = {key: value for key, value in config.items() if key != "id"}
    text = json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Entity ids and helper slugs (M8, PRD 9.2)
# --------------------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Return a slug the way Home Assistant writes one, for Latin script names.

    Accents go, a few Latin letters are spelled out, everything else that is not a
    letter or digit becomes one underscore. Names in other scripts have no slug here and
    read as `unknown`, which `helper_slug` then makes unique.
    """
    text = "".join(_TRANSLITERATIONS.get(character, character) for character in text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = _THOUSANDS.sub("", text.lower())
    return _NOT_SLUG.sub("_", text).strip("_") or "unknown"


def entity_id_for(device_name: str) -> str:
    """Return the entity id a routine automation is created with (M8)."""
    return ENTITY_ID_PREFIX + slugify(device_name)


def helper_slug(device_name: str, device_id: str, taken: Collection[str]) -> str:
    """Return the slug a device's helpers are named with (`timer.routine_<slug>`).

    `taken` holds the slugs other devices' helpers already use. Two devices with the same
    name get distinct slugs: the second gets the first six hex characters of its
    automation id's hash appended, which never changes for that device.
    """
    slug = slugify(device_name)
    if slug not in taken:
        return slug
    digest = automation_id(device_id).removeprefix(AUTOMATION_ID_PREFIX)
    return f"{slug}_{digest[:_SUFFIX_LENGTH]}"
