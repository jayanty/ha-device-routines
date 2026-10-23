"""Config entry and blueprint input schema migrations (TECH_SPEC 4.11, PRD 3.1).

Config entry. `VERSION` 1 throughout; the minor version is the options version of
`settings.OPTIONS_VERSION`, so Home Assistant calls `async_migrate_entry` for every entry
whose options are older, and the options move through `settings.migrate`. A newer minor
version (a downgrade within version 1) loads as it is: `settings.from_options` reads what
it knows and drops the rest.

Blueprint input schema. When the blueprint the integration ships has a newer input schema
than an owned automation's record, `async_migrate_blueprint_schema` makes sure the shipped
blueprint is installed, then for every such automation decompiles its inputs with the
rules of its old schema (`DECOMPILERS`), has the manager compile and write them with the
current compiler (one reload each), keeps the old inputs in `previous_inputs` for a one
click restore and records the new schema. One failure does not stop the others; the
manager raises `automation_load_failed` for the ids it returns. The manager's side is the
`SchemaMigrationTarget` protocol, so this module needs no manager.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import logging
from typing import Any, Final, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import compiler, ha_adapter, markers, settings
from .models import CompileError, RoutineSettings
from .store import RoutineStore

_LOGGER = logging.getLogger(__name__)

# The config entry's major version; there has never been another (config_flow.VERSION).
ENTRY_VERSION: Final = 1

type Decompiler = Callable[[Mapping[str, Any]], RoutineSettings]

# The 29 inputs of blueprint input schema 1 (TECH_SPEC 5.2), as `v0.3.0` shipped them.
SCHEMA_1_KEYS: Final = frozenset(
    {
        "target_entity",
        "on_action",
        "off_action",
        "inactive_state",
        "device_id",
        "on_time_enabled",
        "on_time",
        "off_time_enabled",
        "off_time",
        "days_start",
        "days_end",
        "crosses_midnight",
        "schedule_enabled",
        "schedule_entity",
        "timer_entity",
        "turn_off_after_min",
        "turn_back_on_after_min",
        "catch_up",
        "late_start_window_min",
        "late_window_end",
        "respect_manual",
        "override_entity",
        "paused_until_entity",
        "pulse_enabled",
        "pulse_at",
        "pulse_minutes",
        "pulse_min_steady_min",
        "docked_guard",
        "extra_conditions",
    }
)


def decompile_schema_1(inputs: Mapping[str, Any]) -> RoutineSettings:
    """Read schema 1 inputs: refuse any later key, read the rest as the compiler does.

    Every schema 2 input defaults to schema 1 behavior, so `compiler.decompile` reads
    schema 1 exactly as schema 1 did (decision L60); `tests/fixtures/schema1/inputs.json`
    pins it, and a compiler that reads schema 1 differently freezes a copy here instead.
    """
    if not isinstance(inputs, Mapping) or not set(inputs) <= SCHEMA_1_KEYS:
        raise CompileError("invalid_inputs")
    return compiler.decompile(inputs)


# The 38 inputs of blueprint input schema 2, as `v1.0.0` shipped them: schema 1's and the
# nine of sun bounds (decision L60).
SCHEMA_2_KEYS: Final = SCHEMA_1_KEYS | frozenset(
    {
        "on_kind",
        "on_sun_offset",
        "off_kind",
        "off_sun_offset",
        "on_at_sunrise",
        "on_at_sunset",
        "off_at_sunrise",
        "off_at_sunset",
        "late_sun_offset",
    }
)


def decompile_schema_2(inputs: Mapping[str, Any]) -> RoutineSettings:
    """Read schema 2 inputs: refuse any later key, read the rest as the compiler does.

    The one input schema 3 adds, `timer_enabled`, is derived and never read (decision L83),
    so `compiler.decompile` reads schema 2 exactly as schema 2 did.
    """
    if not isinstance(inputs, Mapping) or not set(inputs) <= SCHEMA_2_KEYS:
        raise CompileError("invalid_inputs")
    return compiler.decompile(inputs)


# The rules of every older blueprint input schema, by schema number. The current schema
# reads with `compiler.decompile`; a schema change freezes the old rules here.
DECOMPILERS: Final[dict[int, Decompiler]] = {1: decompile_schema_1, 2: decompile_schema_2}


class SchemaMigrationTarget(Protocol):
    """What the blueprint schema migration needs from the manager (lane 5 implements it)."""

    async def async_ensure_blueprint(self) -> bool:
        """Install the shipped blueprint when it is missing or a previously shipped one.

        The TECH_SPEC 7 step 2 rule. Return True when the installed file is now the
        shipped one; False when it was edited by hand, which stays untouched until the
        `blueprint_modified` Repairs fix restores it (nothing is migrated meanwhile).
        """
        ...

    async def async_write_settings(self, automation_id: str, settings: RoutineSettings) -> None:
        """Compile the settings for the routine's device and write them now.

        The current compiler with the device's domain profile and helper references, the
        write algorithm of TECH_SPEC 4.1 (the adapter write with the file hash guard and
        one reload of that id), no debounce; `owned[automation_id]` then holds the new
        `last_hash`, `last_valid_inputs` and `schema`, and keeps its other fields. Raise
        on any failure (a compile problem, an adapter error); nothing is half written.
        """
        ...


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate the entry's options to the current options version."""
    if entry.version != ENTRY_VERSION:
        return False
    if entry.minor_version >= settings.OPTIONS_VERSION:
        return True
    options = settings.migrate(entry.options, entry.minor_version)
    hass.config_entries.async_update_entry(
        entry, options=options, minor_version=settings.OPTIONS_VERSION
    )
    return True


def decompile_inputs(inputs: Mapping[str, Any], schema: int) -> RoutineSettings:
    """Read blueprint inputs with the rules of the schema they were written under.

    Raises `CompileError` (`invalid_inputs`) for inputs those rules cannot read and for a
    schema whose rules are not known.
    """
    if schema == compiler.BLUEPRINT_SCHEMA_VERSION:
        return compiler.decompile(inputs)
    decompiler = DECOMPILERS.get(schema)
    if decompiler is None:
        raise CompileError("invalid_inputs")
    return decompiler(inputs)


async def async_migrate_blueprint_schema(
    hass: HomeAssistant, manager: SchemaMigrationTarget, store: RoutineStore
) -> list[str]:
    """Rewrite every owned automation of an older schema; return the ids that failed.

    Idempotent: an automation already on the current schema is not touched, and a failed
    one keeps its old schema and inputs, so the next run (every start) retries only what
    failed. An automation that is gone from the file or detached (taken control of) is
    left to the manager's reconcile and is not reported. A newer recorded schema (a
    downgrade) is left as it is.
    """
    current = compiler.BLUEPRINT_SCHEMA_VERSION
    data = store.data
    due = sorted(key for key, record in data.owned.items() if record.schema < current)
    recorded = data.blueprint_schema
    if not due and recorded is not None and recorded >= current:
        return []
    if not await manager.async_ensure_blueprint():
        _LOGGER.warning(
            "The installed routine blueprint is not the shipped one; routines stay on their "
            "blueprint schema until it is restored"
        )
        return []
    failed: list[str] = []
    for automation_id in due:
        try:
            await _async_migrate_one(hass, manager, store, automation_id)
        except Exception:  # one failure must not stop the others
            _LOGGER.warning(
                "Could not migrate %s to blueprint schema %s", automation_id, current, exc_info=True
            )
            failed.append(automation_id)
    if recorded is None or recorded < current:
        data.blueprint_schema = current
    await store.async_save()
    return failed


async def _async_migrate_one(
    hass: HomeAssistant, manager: SchemaMigrationTarget, store: RoutineStore, automation_id: str
) -> None:
    """Rewrite one automation from its old schema, or leave it alone when it is not ours."""
    record = store.data.owned[automation_id]
    config = await ha_adapter.async_read_automation(hass, automation_id)
    if config is None or not markers.is_owned(config):
        return
    inputs = config["use_blueprint"].get("input", {})
    if not isinstance(inputs, Mapping):
        raise CompileError("invalid_inputs")
    previous = dict(inputs)
    await manager.async_write_settings(automation_id, decompile_inputs(previous, record.schema))
    written = store.data.owned.get(automation_id, record)
    store.data.owned[automation_id] = replace(
        written, previous_inputs=previous, schema=compiler.BLUEPRINT_SCHEMA_VERSION
    )
