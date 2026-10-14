"""Diagnostics: what a bug report needs, with nothing that identifies a home.

Entity ids, device and area names and automation aliases are redacted before anything is
written, keeping domains, shapes and counts (PRD 10.3). Phase 0 has only the integration's
own version, options and health to report; the Store and the summaries join in later phases
and go through the same redaction.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DeviceRoutinesConfigEntry

# Option keys whose value would be a secret in itself. None is written today; the list is
# here because options grow without this module being touched.
TO_REDACT: Final = {"token", "password", "api_key", "access_token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviceRoutinesConfigEntry
) -> dict[str, Any]:
    """Return the integration's own state."""
    runtime = entry.runtime_data
    return {
        "integration": {
            "entry_id": entry.entry_id,
            "version": runtime.version,
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "health": asdict(runtime.health),
        }
    }
