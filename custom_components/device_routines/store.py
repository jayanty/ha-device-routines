"""The integration's own storage: `.storage/device_routines`, schema 1.2 (TECH_SPEC 6).

A routine lives in its automation's blueprint inputs; the Store holds only indexes and
caches. Everything except `opted_out_at`, `ai_cache`, `suspended` and `own_helpers` can be
rebuilt from the markers and the registries (the `rebuild_index` maintenance action), so
losing the file costs at most a delayed cleanup, some AI calls, a routine the manager
turned off staying off, and a helper no routine names any more left to a person. It holds
no secret.

Serialized shape (`StoreData.to_dict`), every value plain JSON:

- `owned`: automation id to `{device_id, target_entity, last_hash, last_valid_inputs,
  previous_inputs, schema, alias_history}`; inputs are the blueprint input mappings,
  `alias_history` a list of the aliases the routine was generated with.
- `opted_in`: a sorted list of device ids.
- `opted_out_at`, `removed_devices_at`: device id to an ISO 8601 timestamp.
- `blueprint_hash`: the sha256 of the installed blueprint text, or null.
- `blueprint_schema`: the blueprint input schema the routines were last migrated to, or
  null before the first record.
- `ai_cache`: config hash to `{text, created}`, `created` an ISO 8601 timestamp.
- `suspended` (1.2): automation id to why the manager turned that automation off,
  `invalid` or `missing_target`, so it turns it back on when that ends, across restarts
  too (L44). A routine a person turned off is never in it.
- `own_helpers` (1.2): device id to the sorted entity ids of the timer and schedule
  helpers the manager created for that device's routine. A helper stays when the routine
  stops naming it (Days back from Weekly schedule keeps the blocks, FR-R2), so it is
  found again after a rename and a restart, and deleted with the routine (L53).

Versions. `migrate_store` has the shape of the core `Store` migrate function. Version 0
is the PRD 10.2 layout, before TECH_SPEC 6 added the per record schema, previous inputs
and alias history, the removal timestamps and the blueprint schema. Minor version 2 adds
`suspended` and `own_helpers`; the migration reads the helpers a routine's inputs name
under the routine prefix. A version newer than this code (a downgrade) is refused with
`StoreVersionError`, never read with keys dropped; the file stays on disk as it was.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .compiler import BLUEPRINT_SCHEMA_VERSION
from .const import DOMAIN

STORAGE_KEY: Final = DOMAIN
STORAGE_VERSION: Final = 1
STORAGE_MINOR_VERSION: Final = 2
# Seconds a delayed save waits, so a burst of changes is one write.
SAVE_DELAY: Final = 1.0

# Version 0 predates the blueprint schema record; schema 1 is the first one ever shipped.
_VERSION_0_BLUEPRINT_SCHEMA: Final = 1
# The inputs naming a routine's helpers, and the object id prefix its own helpers carry
# (M8: `timer.routine_<slug>`, `schedule.routine_<slug>`).
_HELPER_INPUTS: Final = ("timer_entity", "schedule_entity")
_OWN_HELPER_PREFIX: Final = "routine_"


class StoreVersionError(HomeAssistantError):
    """The stored data has a version this code cannot read."""

    def __init__(self, version: int, minor_version: int) -> None:
        placeholders = {
            "version": f"{version}.{minor_version}",
            "supported": f"{STORAGE_VERSION}.{STORAGE_MINOR_VERSION}",
        }
        super().__init__(
            f"{STORAGE_KEY} storage version {placeholders['version']} is not supported "
            f"(this version reads {placeholders['supported']})",
            translation_domain=DOMAIN,
            translation_key="store_version_unsupported",
            translation_placeholders=placeholders,
        )


@dataclass(frozen=True, slots=True)
class OwnedRecord:
    """What the integration remembers about one owned automation, keyed by its id.

    `last_hash` is the hash of the config the manager last wrote, so it can tell its own
    writes from foreign ones; `last_valid_inputs` the inputs a restore goes back to;
    `previous_inputs` the inputs before the last blueprint schema migration (a one click
    restore, PRD 3.1); `schema` the blueprint input schema the inputs follow;
    `alias_history` every alias the routine was generated with, so a rename follows only
    while the alias is still a generated one.
    """

    device_id: str
    target_entity: str
    last_hash: str | None = None
    last_valid_inputs: Mapping[str, Any] | None = None
    previous_inputs: Mapping[str, Any] | None = None
    schema: int = BLUEPRINT_SCHEMA_VERSION
    alias_history: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AiCacheEntry:
    """One AI written summary line, keyed by the config hash it describes."""

    text: str
    created: datetime


@dataclass(slots=True)
class StoreData:
    """Everything the Store holds; the manager and maintenance change it in place."""

    owned: dict[str, OwnedRecord] = field(default_factory=dict)
    opted_in: set[str] = field(default_factory=set)
    opted_out_at: dict[str, datetime] = field(default_factory=dict)
    removed_devices_at: dict[str, datetime] = field(default_factory=dict)
    blueprint_hash: str | None = None
    blueprint_schema: int | None = None
    ai_cache: dict[str, AiCacheEntry] = field(default_factory=dict)
    suspended: dict[str, str] = field(default_factory=dict)
    own_helpers: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the serialized shape of the module docstring."""
        return {
            "owned": {key: _record_to_dict(record) for key, record in self.owned.items()},
            "opted_in": sorted(self.opted_in),
            "opted_out_at": _times_to_dict(self.opted_out_at),
            "removed_devices_at": _times_to_dict(self.removed_devices_at),
            "blueprint_hash": self.blueprint_hash,
            "blueprint_schema": self.blueprint_schema,
            "ai_cache": {
                key: {"text": entry.text, "created": entry.created.isoformat()}
                for key, entry in self.ai_cache.items()
            },
            "suspended": dict(self.suspended),
            "own_helpers": {key: sorted(value) for key, value in self.own_helpers.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StoreData:
        """Read the serialized shape back; a missing key takes its default."""
        return cls(
            owned={key: _record_from_dict(item) for key, item in data.get("owned", {}).items()},
            opted_in=set(data.get("opted_in", ())),
            opted_out_at=_times_from_dict(data.get("opted_out_at", {})),
            removed_devices_at=_times_from_dict(data.get("removed_devices_at", {})),
            blueprint_hash=data.get("blueprint_hash"),
            blueprint_schema=data.get("blueprint_schema"),
            ai_cache={
                key: AiCacheEntry(
                    text=item["text"], created=datetime.fromisoformat(item["created"])
                )
                for key, item in data.get("ai_cache", {}).items()
            },
            suspended=dict(data.get("suspended", {})),
            own_helpers={key: list(value) for key, value in data.get("own_helpers", {}).items()},
        )


def _plain(value: Any) -> Any:
    """Copy inputs into plain dicts and lists, as JSON wants them."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value


def _inputs(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return None if value is None else _plain(value)


def _record_to_dict(record: OwnedRecord) -> dict[str, Any]:
    return {
        "device_id": record.device_id,
        "target_entity": record.target_entity,
        "last_hash": record.last_hash,
        "last_valid_inputs": _inputs(record.last_valid_inputs),
        "previous_inputs": _inputs(record.previous_inputs),
        "schema": record.schema,
        "alias_history": list(record.alias_history),
    }


def _record_from_dict(item: Mapping[str, Any]) -> OwnedRecord:
    return OwnedRecord(
        device_id=item["device_id"],
        target_entity=item["target_entity"],
        last_hash=item.get("last_hash"),
        last_valid_inputs=_inputs(item.get("last_valid_inputs")),
        previous_inputs=_inputs(item.get("previous_inputs")),
        schema=item.get("schema", BLUEPRINT_SCHEMA_VERSION),
        alias_history=tuple(item.get("alias_history", ())),
    )


def _times_to_dict(times: Mapping[str, datetime]) -> dict[str, str]:
    return {key: moment.isoformat() for key, moment in times.items()}


def _times_from_dict(times: Mapping[str, str]) -> dict[str, datetime]:
    return {key: datetime.fromisoformat(moment) for key, moment in times.items()}


# --------------------------------------------------------------------------------------
# Migration
# --------------------------------------------------------------------------------------


def _from_version_0(data: dict[str, Any]) -> dict[str, Any]:
    """Version 0 to 1: add the fields TECH_SPEC 6 added to the PRD 10.2 layout."""
    owned = {
        key: {
            **item,
            "previous_inputs": None,
            "schema": _VERSION_0_BLUEPRINT_SCHEMA,
            "alias_history": [],
        }
        for key, item in data.get("owned", {}).items()
    }
    return {
        **data,
        "owned": owned,
        "removed_devices_at": {},
        "blueprint_schema": _VERSION_0_BLUEPRINT_SCHEMA,
    }


def own_helpers_named(inputs: Mapping[str, Any] | None) -> set[str]:
    """Return the routine's own helpers blueprint inputs name (M8: the routine prefix).

    What the migration to 1.2 and `rebuild_index` can know of `own_helpers`: a helper the
    routine no longer names is known only to the Store that remembered it.
    """
    found: set[str] = set()
    for key in _HELPER_INPUTS:
        helper = (inputs or {}).get(key)
        if isinstance(helper, str) and helper.partition(".")[2].startswith(_OWN_HELPER_PREFIX):
            found.add(helper)
    return found


def _from_minor_1(data: dict[str, Any]) -> dict[str, Any]:
    """1.1 to 1.2: add `suspended` (empty) and `own_helpers` (read from the inputs).

    Before 1.2 the manager kept why it turned a routine off in memory only, so nothing is
    known; a routine's own helpers are the timer and schedule its inputs name under the
    routine prefix (M8).
    """
    own: dict[str, set[str]] = {}
    for item in data.get("owned", {}).values():
        if found := own_helpers_named(item.get("last_valid_inputs")):
            own.setdefault(item["device_id"], set()).update(found)
    helpers = {device_id: sorted(found) for device_id, found in own.items()}
    return {**data, "suspended": {}, "own_helpers": helpers}


# Each entry turns data of major version N into version N + 1.
_MIGRATIONS: Final[Mapping[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    0: _from_version_0,
}
# Each entry turns data of minor version N of the current major version into N + 1.
_MINOR_MIGRATIONS: Final[Mapping[int, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    1: _from_minor_1,
}


def migrate_store(version: int, minor_version: int, data: Mapping[str, Any]) -> dict[str, Any]:
    """Bring stored data of any earlier version to the current one.

    Major steps first; data that took one lands on minor version 1 of the current major
    version, and the minor steps follow. Raises `StoreVersionError` for a version newer
    than this code reads (a downgrade) and for a version no migration path starts from;
    the input is never mutated.
    """
    if (version, minor_version) > (STORAGE_VERSION, STORAGE_MINOR_VERSION):
        raise StoreVersionError(version, minor_version)
    migrated = dict(data)
    for step in range(version, STORAGE_VERSION):
        if step not in _MIGRATIONS:
            raise StoreVersionError(version, minor_version)
        migrated = _MIGRATIONS[step](migrated)
    first = minor_version if version == STORAGE_VERSION else 1
    for step in range(first, STORAGE_MINOR_VERSION):
        if step not in _MINOR_MIGRATIONS:
            raise StoreVersionError(version, minor_version)
        migrated = _MINOR_MIGRATIONS[step](migrated)
    return migrated


class _VersionedStore(Store[dict[str, Any]]):
    """The core Store with `migrate_store` as its migrate function."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        return migrate_store(old_major_version, old_minor_version, old_data)


class RoutineStore:
    """The loaded Store: `data` is read and changed in place, then saved.

    `data` starts empty, so it is usable before `async_load`; `async_load` replaces it.
    `async_flush` writes a delayed save that is still waiting, which the manager does on
    unload: an entry reloaded inside the delay would otherwise lose it (L53).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = _VersionedStore(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY,
            minor_version=STORAGE_MINOR_VERSION,
            atomic_writes=True,
        )
        self.data = StoreData()
        self._pending = False

    async def async_load(self) -> StoreData:
        """Load (and migrate) the stored data; raise `StoreVersionError` for a newer one."""
        stored = await self._store.async_load()
        self.data = StoreData() if stored is None else StoreData.from_dict(stored)
        return self.data

    async def async_save(self) -> None:
        """Write `data` now; a delayed save still waiting is replaced by this one."""
        self._pending = False
        await self._store.async_save(self.data.to_dict())

    @callback
    def async_delay_save(self, delay: float = SAVE_DELAY) -> None:
        """Write `data` as it is after `delay` seconds, so a burst of changes is one write."""
        self._pending = True
        self._store.async_delay_save(self._serialized, delay)

    async def async_flush(self) -> None:
        """Write now when a delayed save is still waiting; otherwise do nothing."""
        if self._pending:
            await self.async_save()

    def _serialized(self) -> dict[str, Any]:
        self._pending = False
        return self.data.to_dict()
