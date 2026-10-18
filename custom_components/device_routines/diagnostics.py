"""Diagnostics: what a bug report needs, with nothing that identifies a home (TECH_SPEC 4.9).

Config entry diagnostics hold five sections:

- `integration`: the version, the options and settings (secret shaped keys and the AI
  Task entity redacted), the adapter report and the Health report, its issues reduced to
  their catalog ids so no routine's automation id shows.
- `store`: the Store as counts, plus the blueprint hash and schema.
- `routines`: one shape per owned automation, numbered instead of named: the target's
  domain, the schema, the config hash, how many aliases it was generated with, its inputs
  (entity inputs read `unused` for a sentinel and are redacted otherwise; ids redacted;
  Only when conditions counted; service names, states, times, days, flags and minutes
  kept; anything else redacted) and the routine's runtime state as flags.
- `summary`: the Schedule summaries as shapes, as in Phase 1.

Device diagnostics report one device the same way: the hub reports the integration and
the Store; a device page record (decision L25) reports that device's routine and Schedule
summary. Finally every string anywhere in the report that looks like a token, a private
address, a MAC address, a `.local` host name, an email address or a 32 character registry
id is redacted (PRD 11.3), whatever key it sits under.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import re
from typing import Any, Final

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import DeviceRoutinesConfigEntry, compiler
from .const import DOMAIN, HUB_IDENTIFIER
from .domains import PROFILES
from .models import RoutineView, Weekday
from .repairs import CATALOG
from .store import OwnedRecord, StoreData
from .summary import DeviceSummary, SummaryCoordinator

# Option and setting keys whose value is a secret or names something in the home.
TO_REDACT: Final = {"token", "password", "api_key", "access_token", "ai_task_entity"}

# Inputs that name an entity: `unused` for a sentinel, redacted otherwise.
_ENTITY_INPUTS: Final = frozenset(
    {"target_entity", "schedule_entity", "timer_entity", "override_entity", "paused_until_entity"}
)
_SENTINELS: Final = frozenset(
    {
        compiler.UNUSED_TIMER,
        compiler.UNUSED_SCHEDULE,
        compiler.UNUSED_SWITCH,
        compiler.UNUSED_DATETIME,
    }
)
# Inputs whose values are kept when they are plain: every input but the ids, the entity
# inputs and the Only when conditions (which may name anything, so they are counted).
_PLAIN_INPUTS: Final = (
    frozenset(compiler.INPUT_KEYS)
    - _ENTITY_INPUTS
    - {
        "device_id",
        "extra_conditions",
    }
)
# The words a plain input may hold: the profiles' actions and off states, and weekdays.
_KNOWN_WORDS: Final = frozenset(
    {action for profile in PROFILES.values() for action in (profile.on_action, profile.off_action)}
    | {profile.inactive_state for profile in PROFILES.values()}
    | {day.value for day in Weekday}
) - {None}
_TIME: Final = re.compile(r"^\d{2}:\d{2}(?::\d{2})?$")

# The generic privacy patterns of PRD 11.3 (the repository's own check uses the same).
_PRIVATE: Final = (
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})\b"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    re.compile(r"\b[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.local\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b[0-9a-f]{32}\b"),
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DeviceRoutinesConfigEntry
) -> dict[str, Any]:
    """Return the integration's own state."""
    runtime = entry.runtime_data
    data = runtime.manager.store.data
    return _scrubbed(
        {
            "integration": _integration(entry),
            "store": _store(data),
            "routines": [
                _routine(index, record, runtime.manager.get(record.device_id))
                for index, record in enumerate(data.owned.values())
            ],
            "summary": _summary(runtime.summary),
        }
    )


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: DeviceRoutinesConfigEntry, device: dr.DeviceEntry
) -> dict[str, Any]:
    """Return one device: the hub's integration state, or a device's routine."""
    runtime = entry.runtime_data
    data = runtime.manager.store.data
    if (DOMAIN, HUB_IDENTIFIER) in device.identifiers:
        return _scrubbed({"integration": _integration(entry), "store": _store(data)})
    device_id = _user_device_id(hass, entry, device)
    if device_id is None:
        return {"opted_in": False, "routine": None, "schedule": None}
    record = next((item for item in data.owned.values() if item.device_id == device_id), None)
    summary = runtime.summary.summaries.get(device_id)
    return _scrubbed(
        {
            "opted_in": device_id in data.opted_in,
            "routine": _routine(0, record, runtime.manager.get(device_id)) if record else None,
            "schedule": _schedule(0, summary) if summary else None,
        }
    )


def _user_device_id(
    hass: HomeAssistant, entry: DeviceRoutinesConfigEntry, device: dr.DeviceEntry
) -> str | None:
    """Return the user's device a record of this entry stands for (decision L25)."""
    for candidate in dr.async_get(hass).devices:
        if candidate.config_entry_id == entry.entry_id:
            continue
        if candidate.identifiers & device.identifiers or candidate.connections & device.connections:
            return candidate.id
    return None


def _integration(entry: DeviceRoutinesConfigEntry) -> dict[str, Any]:
    runtime = entry.runtime_data
    adapter = runtime.manager.adapter_report
    report = runtime.health.report
    return {
        "entry_id": entry.entry_id,
        "version": runtime.version,
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "settings": async_redact_data(runtime.settings.to_options(), TO_REDACT),
        "adapter": {"failed": list(adapter.failed), **adapter.details},
        "health": {**asdict(report), "issues": sorted(_issue_kind(i) for i in report.issues)},
    }


def _issue_kind(issue_id: str) -> str:
    """Return the catalog id of a registry issue id, without the routine it names."""
    return next(
        (kind for kind in CATALOG if issue_id == kind or issue_id.startswith(f"{kind}_")),
        REDACTED,
    )


def _store(data: StoreData) -> dict[str, Any]:
    return {
        "owned": len(data.owned),
        "opted_in": len(data.opted_in),
        "opted_out": len(data.opted_out_at),
        "removed_devices": len(data.removed_devices_at),
        "ai_cache": len(data.ai_cache),
        "blueprint_hash": data.blueprint_hash,
        "blueprint_schema": data.blueprint_schema,
    }


def _routine(index: int, record: OwnedRecord, view: RoutineView | None) -> dict[str, Any]:
    inputs = record.last_valid_inputs
    return {
        "routine": index,
        "automation_id": REDACTED,
        "device_id": REDACTED,
        "target_domain": record.target_entity.partition(".")[0],
        "schema": record.schema,
        "last_hash": record.last_hash,
        "aliases": len(record.alias_history),
        "has_previous_inputs": record.previous_inputs is not None,
        "inputs": None if inputs is None else {key: _input(key, v) for key, v in inputs.items()},
        "runtime": None if view is None else _runtime(view),
    }


def _input(key: str, value: Any) -> Any:
    """Return one blueprint input as a shape (see the module docstring)."""
    if key in _ENTITY_INPUTS:
        return "unused" if value in _SENTINELS else REDACTED
    if key == "extra_conditions":
        return len(value) if isinstance(value, list | tuple) else REDACTED
    if key in _PLAIN_INPUTS:
        return _plain(value)
    return REDACTED


def _plain(value: Any) -> Any:
    """Return a flag, a number, a time, a known word or a list of those; else redact."""
    if isinstance(value, bool | int):
        return value
    if isinstance(value, str) and (value in _KNOWN_WORDS or _TIME.match(value)):
        return value
    if isinstance(value, list) and all(item in _KNOWN_WORDS for item in value):
        return value
    return REDACTED


def _runtime(view: RoutineView) -> dict[str, Any]:
    source = view.last_change_source
    return {
        "status": view.status.value,
        "enabled": view.enabled,
        "paused": view.paused_until is not None,
        "skipping": view.skipped_action is not None,
        "has_next_action": view.next_action is not None,
        "override": view.override,
        "last_change_source": None if source is None else source.value,
        "has_sentence": view.sentence is not None,
        "items": len(view.items),
        "conflicts": len(view.conflicts),
    }


def _summary(coordinator: SummaryCoordinator) -> dict[str, Any]:
    summaries = list(coordinator.summaries.values())
    items = [item for summary in summaries for item in summary.items]
    return {
        "devices": len(summaries),
        "items": len(items),
        "source_none": sum(item.source == "none" for item in items),
        "custom_logic": sum(item.custom_logic for item in items),
        "disabled": sum(not item.enabled for item in items),
        "per_device": [_schedule(index, summary) for index, summary in enumerate(summaries)],
    }


def _schedule(index: int, summary: DeviceSummary) -> dict[str, Any]:
    """Return a device's Schedule summary as a shape: no alias, sentence or automation."""
    return {
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


def _scrubbed(report: dict[str, Any]) -> dict[str, Any]:
    """Return the report with `_scrub` applied to every value."""
    return {key: _scrub(value) for key, value in report.items()}


def _scrub(value: Any) -> Any:
    """Redact every string that matches a privacy pattern, at any depth."""
    if isinstance(value, str):
        return REDACTED if any(pattern.search(value) for pattern in _PRIVATE) else value
    if isinstance(value, Mapping):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value
