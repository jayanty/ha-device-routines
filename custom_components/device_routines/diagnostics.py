"""Diagnostics: what a bug report needs, with nothing that identifies a home.

Entity ids, device and area names and automation aliases are redacted before anything is
written, keeping domains, shapes and counts (PRD 10.3). The summary is reported as shapes
only: per device a sequence number instead of its id or name, and per item its kind,
source, flags and whether it has a next run, never its alias, sentence or automation.
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
    summaries = list(runtime.summary.summaries.values())
    items = [item for summary in summaries for item in summary.items]
    return {
        "integration": {
            "entry_id": entry.entry_id,
            "version": runtime.version,
            "options": async_redact_data(dict(entry.options), TO_REDACT),
            "settings": runtime.settings.to_options(),
            "adapter": {"failed": list(runtime.adapter.failed), **runtime.adapter.details},
            "health": asdict(runtime.health),
        },
        "summary": {
            "devices": len(summaries),
            "items": len(items),
            "source_none": sum(item.source == "none" for item in items),
            "custom_logic": sum(item.custom_logic for item in items),
            "disabled": sum(not item.enabled for item in items),
            "per_device": [
                {
                    "device": index,
                    "has_state": summary.state is not None,
                    "conflicts": [conflict.reason_key for conflict in summary.conflicts],
                    "items": [
                        {
                            "kind": item.kind,
                            "source": item.source,
                            "enabled": item.enabled,
                            "custom_logic": item.custom_logic,
                            "timed": item.next_run is not None,
                        }
                        for item in summary.items
                    ],
                }
                for index, summary in enumerate(summaries)
            ],
        },
    }
