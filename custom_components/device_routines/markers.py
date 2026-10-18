"""The markers that make an automation a managed routine (TECH_SPEC 3.4, PRD Section 8).

Ownership needs both M1 (the automation id derived from the device id) and M2 (the
blueprint path). An alias, the `Routines` label or the category alone never count, so a
lookalike automation is never written. Seeded before Build A wave A1 with the functions
the adapter's write guard needs (decision L34); the presentation, alias and hash functions
of the Section 4.2 contract follow in lane 1.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Any, Final

AUTOMATION_ID_PREFIX: Final = "device_routines_"
BLUEPRINT_PATH: Final = "device_routines/device_routine.yaml"

_AUTOMATION_ID: Final = re.compile(r"device_routines_[0-9a-f]{12}")


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
