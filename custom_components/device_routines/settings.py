"""Global settings: the PRD 10.4 catalog, defaults and migration (TECH_SPEC 3.9).

The settings live in the config entry options. `from_options` is lenient, because stored
options must always load: an unknown key is dropped and an invalid value takes its
default. `validate` is strict and is what the options flow uses before it stores anything.

Options versions. Version 1 (Phase 1) stored only `schedule_scope` and `time_format`.
Version 2 holds the complete catalog: migrating from 1 adds every other key at its
default and keeps whatever was stored, so a later change of a default never moves a
setting an existing entry already had. The config entry's minor version carries the
options version (`migration.async_migrate_entry`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from typing import Any, Final

from .models import Problem

OPTIONS_VERSION: Final = 2


class ScheduleScope(StrEnum):
    """Where Schedule sensors appear (PRD FR-S8)."""

    ALL = "all"
    ROUTINES = "routines"
    NONE = "none"


class TimeFormat(StrEnum):
    """How sentences show times (PRD D32)."""

    AUTO = "auto"
    H12 = "12h"
    H24 = "24h"


class OnRemoval(StrEnum):
    """What removing the integration does to managed automations."""

    KEEP = "keep"
    DELETE = "delete"


# Countries whose clocks read 12 hour by convention; everything else resolves to 24 hour.
TWELVE_HOUR_COUNTRIES: Final[frozenset[str]] = frozenset(
    {"US", "CA", "AU", "NZ", "IN", "PH", "EG", "SA", "PK", "BD", "MY", "CO", "JO", "SV"}
)

# Integer settings and their inclusive ranges.
RANGES: Final[Mapping[str, tuple[int, int]]] = {
    "default_late_start_window_min": (0, 180),
    "cleanup_after_days": (0, 365),
    "ai_calls_per_hour": (1, 100),
}

ENUMS: Final[Mapping[str, type[StrEnum]]] = {
    "schedule_scope": ScheduleScope,
    "time_format": TimeFormat,
    "on_removal": OnRemoval,
}

BOOLEANS: Final[frozenset[str]] = frozenset(
    {
        "default_catch_up",
        "default_respect_manual",
        "assign_area",
        "offer_conversions",
        "raise_conflict_repairs",
    }
)


@dataclass(frozen=True, slots=True)
class GlobalSettings:
    """Every global setting with its default."""

    schedule_scope: ScheduleScope = ScheduleScope.ALL
    time_format: TimeFormat = TimeFormat.AUTO
    default_catch_up: bool = True
    default_respect_manual: bool = True
    default_late_start_window_min: int = 15
    cleanup_after_days: int = 30
    assign_area: bool = True
    on_removal: OnRemoval = OnRemoval.KEEP
    ai_task_entity: str | None = None
    ai_calls_per_hour: int = 20
    offer_conversions: bool = True
    raise_conflict_repairs: bool = True

    def to_options(self) -> dict[str, Any]:
        """Return the settings as plain values for the config entry options."""
        return {
            key: str(value) if isinstance(value, StrEnum) else value
            for key, value in asdict(self).items()
        }

    def resolved_time_format(self, country: str | None) -> str:
        """Return `12h` or `24h`; `auto` follows the Home Assistant country."""
        if self.time_format is not TimeFormat.AUTO:
            return self.time_format.value
        return TimeFormat.H12.value if (country or "").upper() in TWELVE_HOUR_COUNTRIES else "24h"


KEYS: Final[frozenset[str]] = frozenset(field.name for field in fields(GlobalSettings))


def _problem(key: str, value: Any) -> Problem | None:
    """Return why one value is invalid for its key, or None."""
    if key not in KEYS:
        return Problem(key, "unknown_setting")
    if key in ENUMS:
        allowed = [member.value for member in ENUMS[key]]
        if value not in allowed:
            return Problem(key, "invalid_choice", {"allowed": ", ".join(allowed)})
    elif key in BOOLEANS:
        if not isinstance(value, bool):
            return Problem(key, "invalid_boolean")
    elif key in RANGES:
        low, high = RANGES[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            return Problem(key, "out_of_range", {"min": str(low), "max": str(high)})
    elif value is not None and not (isinstance(value, str) and value.startswith("ai_task.")):
        return Problem(key, "invalid_ai_task_entity")
    return None


def validate(options: Mapping[str, Any]) -> list[Problem]:
    """Return a problem for every key or value that cannot be stored."""
    return [p for key, value in options.items() if (p := _problem(key, value)) is not None]


def _from_version_1(options: dict[str, Any]) -> dict[str, Any]:
    """Add every key version 1 never stored at its default; keep what it stored."""
    return {**GlobalSettings().to_options(), **options}


# Each entry turns options of version N into version N + 1.
MIGRATIONS: Final[Mapping[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    1: _from_version_1,
}


def migrate(options: Mapping[str, Any], version: int) -> dict[str, Any]:
    """Bring stored options up to the current version."""
    migrated = dict(options)
    for step in range(version, OPTIONS_VERSION):
        migrated = MIGRATIONS[step](migrated)
    return migrated


def from_options(options: Mapping[str, Any], version: int = OPTIONS_VERSION) -> GlobalSettings:
    """Load settings from stored options, migrating them; bad values take their default."""
    migrated = migrate(options, version)
    values: dict[str, Any] = {}
    for key, value in migrated.items():
        if key not in KEYS or _problem(key, value) is not None:
            continue
        values[key] = ENUMS[key](value) if key in ENUMS else value
    return GlobalSettings(**values)
