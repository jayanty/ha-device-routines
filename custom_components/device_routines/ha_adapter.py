"""The only module that touches Home Assistant internals (TECH_SPEC 4.2, PRD D2).

Each capability is one small function. `check` runs at setup and from every reconcile and
says which capabilities work on the running core; a failed one disables what depends on
it and raises the single `adapter_incompatible` Repairs issue, while routines keep
running. It logs a failure once at WARNING and its recovery once at INFO (finding F5).

Capabilities:

- read: the automation component's reference helpers and each entity's `raw_config`;
  for a blueprint automation also its `use_blueprint` block, which the rendered
  `raw_config` no longer holds.
- write: the config editor's path replicated (Stage 0 V6): load `automations.yaml`,
  replace or append one entry, write the file atomically, reload that id only. The
  editor's lock is not reachable, so the adapter holds its own lock and compares the file
  hash before the write. It writes only configs carrying M1 and M2, over entries carrying
  both or over nothing (PRD Section 8), whatever the caller. Like the editor, it re dumps
  the file, so comments in a hand maintained `automations.yaml` are dropped; every other
  entry keeps its values and key order.
- blueprint: `DomainBlueprints.async_add_blueprint`, usable at once (Stage 0 V5).
- helpers: the timer and schedule WebSocket commands dispatched in process for the
  integration's system administrator user (decision L23), then the entity registry.
- restore state: the restore cache read for timers that ran out during a restart (L20).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Iterable, Mapping
import contextvars
from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path
from typing import Any, Final, Literal, cast

from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.components import automation, websocket_api
from homeassistant.components.automation import (
    DATA_COMPONENT,
    config as automation_config_schema,
    helpers as automation_helpers,
)
from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.components.blueprint import models as blueprint_models
from homeassistant.components.blueprint.const import BLUEPRINT_FOLDER, CONF_USE_BLUEPRINT
from homeassistant.components.timer import ATTR_FINISHES_AT, STATUS_ACTIVE
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.http import WebSocketAdapter
from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.const import CONF_ID, CONF_PATH, SERVICE_RELOAD
from homeassistant.core import HomeAssistant, State, callback, split_entity_id
from homeassistant.helpers import (
    category_registry as cr,
    entity_registry as er,
    label_registry as lr,
    restore_state,
)
from homeassistant.helpers.typing import UNDEFINED, UndefinedType
from homeassistant.util import dt as dt_util, file as ha_file, yaml as ha_yaml
from homeassistant.util.hass_dict import HassKey
from homeassistant.util.json import json_loads

from . import markers
from .const import DOMAIN, INTEGRATION_TITLE

_LOGGER = logging.getLogger(__name__)

CAPABILITY_READ: Final = "read_automations"
CAPABILITY_WRITE: Final = "write_automations"
CAPABILITY_BLUEPRINT: Final = "install_blueprint"
CAPABILITY_HELPERS: Final = "create_helpers"
CAPABILITY_RESTORE: Final = "restore_state"

# Every reference helper discovery uses (Stage 0 V2 and A3).
_REFERENCE_HELPERS: Final = (
    "entities_in_automation",
    "devices_in_automation",
    "areas_in_automation",
    "floors_in_automation",
    "labels_in_automation",
    "automations_with_entity",
    "blueprint_in_automation",
)

# The automation component fires this after a reload; the SummaryCoordinator listens.
EVENT_AUTOMATION_RELOADED: Final = automation.EVENT_AUTOMATION_RELOADED

# The config editor writes these keys first, in this order, after the id.
_EDITOR_KEY_ORDER: Final = (
    "alias",
    "description",
    "triggers",
    "trigger",
    "conditions",
    "condition",
    "actions",
    "action",
)

# Past reads remembered, so a caller's guard can be checked against its target entry.
_SNAPSHOTS: Final = 16

_HELPER_DOMAINS: Final = ("timer", "schedule")
_HELPER_COMMANDS: Final = tuple(
    f"{domain}/{operation}"
    for domain in _HELPER_DOMAINS
    for operation in ("list", "create", "update", "delete")
)
_COMMAND_TIMEOUT: Final = 30.0


class AdapterError(Exception):
    """A capability could not do what it was asked."""


class NotOwnedError(AdapterError):
    """The config, or an entry it would replace, lacks M1 or M2: it is never written."""


class WriteConflictError(AdapterError):
    """`automations.yaml` moved twice, or the target changed after the caller's read."""


class HelperError(AdapterError):
    """A timer or schedule command failed; `code` is the WebSocket error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class AdapterReport:
    """Which capabilities work on the running core."""

    failed: tuple[str, ...] = ()
    details: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Tell whether every capability works."""
        return not self.failed

    def works(self, capability: str) -> bool:
        """Tell whether one capability works."""
        return capability not in self.failed


@dataclass(frozen=True, slots=True)
class AutomationRefs:
    """One loaded automation: its config and every id it references, resolved.

    `config` is the entity's `raw_config`, which for a blueprint automation is the
    rendered config without `use_blueprint`; `blueprint` is that block (path and inputs),
    None for a plain automation. Ownership (M1 and M2) reads both together:
    `markers.is_owned({**config, "use_blueprint": blueprint})`.
    """

    entity_id: str
    config: Mapping[str, Any]
    entities: frozenset[str]
    devices: frozenset[str]
    areas: frozenset[str]
    floors: frozenset[str]
    labels: frozenset[str]
    blueprint: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class WriteResult:
    """What a write left behind.

    `hash` is the sha256 of `automations.yaml` as written, equal to `file_hash` right
    after the call, so it guards the next write; `created` tells whether the entry was new.
    """

    hash: str
    created: bool


@dataclass(slots=True)
class _AdapterData:
    """Per instance state: the write lock, what the file looked like, what was logged."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_hash: str = ""
    snapshots: dict[str, dict[str, str]] = field(default_factory=dict)
    failing: set[str] = field(default_factory=set)

    def remember(self, digest: str, entries: list[Any]) -> None:
        """Record the file as just read or written."""
        self.last_hash = digest
        self.snapshots.pop(digest, None)
        self.snapshots[digest] = _fingerprints(entries)
        while len(self.snapshots) > _SNAPSHOTS:
            del self.snapshots[next(iter(self.snapshots))]


_DATA: HassKey[_AdapterData] = HassKey(f"{DOMAIN}_adapter")


@callback
def _data(hass: HomeAssistant) -> _AdapterData:
    if (data := hass.data.get(_DATA)) is None:
        data = hass.data[_DATA] = _AdapterData()
    return data


# --------------------------------------------------------------------------------------
# The capability check
# --------------------------------------------------------------------------------------


def _missing(owner: object, *names: str) -> list[str]:
    return [name for name in names if not callable(getattr(owner, name, None))]


def _probe_read(hass: HomeAssistant) -> list[str]:
    return _missing(automation, *_REFERENCE_HELPERS)


def _probe_write(hass: HomeAssistant) -> list[str]:
    missing = _missing(ha_file, "write_utf8_file_atomic") + _missing(ha_yaml, "parse_yaml", "dump")
    if not hass.services.has_service(AUTOMATION_DOMAIN, SERVICE_RELOAD):
        missing.append(f"{AUTOMATION_DOMAIN}.{SERVICE_RELOAD}")
    return missing


def _probe_blueprint(hass: HomeAssistant) -> list[str]:
    return _missing(automation_helpers, "async_get_blueprints") + _missing(
        blueprint_models.DomainBlueprints, "async_add_blueprint"
    )


def _probe_helpers(hass: HomeAssistant) -> list[str]:
    handlers = hass.data.get(websocket_api.DOMAIN) or {}
    return [command for command in _HELPER_COMMANDS if command not in handlers]


def _probe_restore(hass: HomeAssistant) -> list[str]:
    missing = _missing(restore_state, "async_get")
    if not missing and not isinstance(
        getattr(restore_state.async_get(hass), "last_states", None), dict
    ):
        missing.append("last_states")
    return missing


_PROBES: Final[Mapping[str, Callable[[HomeAssistant], list[str]]]] = {
    CAPABILITY_READ: _probe_read,
    CAPABILITY_WRITE: _probe_write,
    CAPABILITY_BLUEPRINT: _probe_blueprint,
    CAPABILITY_HELPERS: _probe_helpers,
    CAPABILITY_RESTORE: _probe_restore,
}


@callback
def check(hass: HomeAssistant) -> AdapterReport:
    """Return which capabilities this core offers, logging each change of state once."""
    details: dict[str, str] = {}
    for capability, probe in _PROBES.items():
        if missing := probe(hass):
            details[capability] = "missing: " + ", ".join(missing)
    failing = _data(hass).failing
    for capability in _PROBES:
        if capability in details and capability not in failing:
            failing.add(capability)
            _LOGGER.warning(
                "Capability %s does not work on this core (%s); routine editing that "
                "depends on it is disabled until it does",
                capability,
                details[capability],
            )
        elif capability not in details and capability in failing:
            failing.discard(capability)
            _LOGGER.info("Capability %s works again", capability)
    return AdapterReport(failed=tuple(details), details=details)


# --------------------------------------------------------------------------------------
# Reading loaded automations
# --------------------------------------------------------------------------------------


def automation_config(hass: HomeAssistant, entity_id: str) -> Mapping[str, Any] | None:
    """Return the config a loaded automation entity was built from, UI and YAML alike.

    None for an automation entity without one: a restored, unavailable registry entry, or
    a YAML automation ignored for a duplicate id (TECH_SPEC 4.2).
    """
    component = hass.data.get(DATA_COMPONENT)
    if component is None:
        return None
    entity = component.get_entity(entity_id)
    config = getattr(entity, "raw_config", None)
    return config if isinstance(config, Mapping) else None


def automation_blueprint(hass: HomeAssistant, entity_id: str) -> Mapping[str, Any] | None:
    """Return the `use_blueprint` block a loaded automation was built from, or None.

    Core keeps the rendered config, inputs substituted and `use_blueprint` dropped, as the
    entity's `raw_config` (`automation/config.py`), so neither M2 nor the inputs are in
    it. The block is the entity's blueprint inputs; when that attribute moves, the public
    `blueprint_in_automation` helper still names the path, and the inputs read as absent.
    """
    path = automation.blueprint_in_automation(hass, entity_id)
    if path is None:
        return None
    entity = hass.data[DATA_COMPONENT].get_entity(entity_id)
    inputs = getattr(entity, "_blueprint_inputs", None)
    block = inputs.get(CONF_USE_BLUEPRINT) if isinstance(inputs, Mapping) else None
    if isinstance(block, Mapping) and block.get(CONF_PATH) == path:
        return block
    return {CONF_PATH: path}


def _resolved(hass: HomeAssistant, references: list[str]) -> frozenset[str]:
    """Resolve registry id references to entity ids, dropping any that do not resolve."""
    registry = er.async_get(hass)
    resolved = set()
    for reference in references:
        entity_id = er.async_resolve_entity_id(registry, reference)
        if entity_id is not None:
            resolved.add(entity_id)
    return frozenset(resolved)


def automation_references(hass: HomeAssistant) -> list[AutomationRefs]:
    """Return every loaded automation with a config and the ids it references."""
    found: list[AutomationRefs] = []
    helper: Callable[[HomeAssistant, str], list[str]]
    for entity_id in sorted(hass.states.async_entity_ids("automation")):
        config = automation_config(hass, entity_id)
        if config is None:
            continue
        ids: dict[str, frozenset[str]] = {}
        for kind in ("devices", "areas", "floors", "labels"):
            helper = getattr(automation, f"{kind}_in_automation")
            ids[kind] = frozenset(helper(hass, entity_id))
        found.append(
            AutomationRefs(
                entity_id=entity_id,
                config=config,
                entities=_resolved(hass, automation.entities_in_automation(hass, entity_id)),
                blueprint=automation_blueprint(hass, entity_id),
                **ids,
            )
        )
    return found


@callback
def automation_state(hass: HomeAssistant, entity_id: str) -> State | None:
    """Return the state of an automation entity, or None when it has none."""
    return hass.states.get(entity_id)


def is_detached(config: Mapping[str, Any]) -> bool:
    """Tell whether a config carries M1 but no longer M2: a routine someone took over.

    Take control removes `use_blueprint` and keeps the id (Stage 0 V8); a config pointed
    at another blueprint is no longer owned either and counts the same way. Pass the entry
    as `automations.yaml` holds it, or `AutomationRefs.config` with its `blueprint` block
    put back: the rendered `raw_config` alone has no `use_blueprint`, so every routine
    would read as detached.
    """
    return markers.has_routine_id(config) and not markers.is_owned(config)


# --------------------------------------------------------------------------------------
# Writing automations.yaml
# --------------------------------------------------------------------------------------


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bytes(path: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return b""


def _read_file(path: str) -> tuple[list[Any], str]:
    """Load the entries of `automations.yaml` and the hash of the bytes they came from."""
    raw = _read_bytes(path)
    loaded = ha_yaml.parse_yaml(raw.decode("utf-8"))
    if not loaded:
        return [], _digest(raw)
    if not isinstance(loaded, list):
        raise AdapterError(f"{AUTOMATION_CONFIG_PATH} does not hold a list")
    return loaded, _digest(raw)


def _replace_if(path: str, read_digest: str, entries: list[Any]) -> str | None:
    """Write the entries unless the file moved since it was read; return the new hash."""
    contents = ha_yaml.dump(entries)
    if _digest(_read_bytes(path)) != read_digest:
        return None
    ha_file.write_utf8_file_atomic(path, contents)
    return _digest(contents.encode("utf-8"))


def _matches(item: Any, automation_id: str) -> bool:
    return isinstance(item, Mapping) and item.get(CONF_ID) == automation_id


def _fingerprints(entries: list[Any]) -> dict[str, str]:
    """Map each routine id in the entries to a hash of its entry, key order included."""
    grouped: dict[str, list[Any]] = {}
    for item in entries:
        if isinstance(item, Mapping) and markers.has_routine_id(item):
            grouped.setdefault(item[CONF_ID], []).append(item)
    return {key: _digest(repr(items).encode("utf-8")) for key, items in grouped.items()}


def _plain(value: Any) -> Any:
    """Copy a config into the dicts and lists the YAML dumper knows."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _editor_ordered(automation_id: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """Build the entry the config editor would write: the id, its ordered keys, the rest."""
    entry: dict[str, Any] = {CONF_ID: automation_id}
    for key in _EDITOR_KEY_ORDER:
        if key in config:
            entry[key] = _plain(config[key])
    for key, value in config.items():
        if key not in entry:
            entry[key] = _plain(value)
    return entry


def _refuse_unowned(entries: list[Any], automation_id: str) -> list[Any]:
    """Return the entries holding the id, refusing when any of them is not owned."""
    targets = [item for item in entries if _matches(item, automation_id)]
    if not all(markers.is_owned(item) for item in targets):
        raise NotOwnedError(f"the entry {automation_id} lacks M1 or M2")
    return targets


def _refuse_changed_target(
    automation_id: str, guard: dict[str, str] | None, entries: list[Any]
) -> None:
    """Refuse when the target is not what it was at the caller's guarded read."""
    if guard is None or guard.get(automation_id) != _fingerprints(entries).get(automation_id):
        raise WriteConflictError(
            f"{automation_id} changed after the caller's read, or the guard is not one "
            "the adapter handed out"
        )


async def _async_rewrite(
    hass: HomeAssistant,
    automation_id: str,
    expected_hash: str | None,
    build: Callable[[list[Any]], list[Any] | None],
) -> tuple[str, bool]:
    """Rewrite the file with what `build` makes of its entries, under the adapter's lock.

    Returns the file hash afterwards and whether anything was written. A move is the file
    differing from the caller's guard at the first read, or changing between a read and
    the write: the first move is re read and retried, the second raises
    `WriteConflictError`, so there are never more than two reads. With a guard, the
    target entry must also still be what it was at the caller's read, or nothing is
    written.
    """
    adapter = _data(hass)
    path = hass.config.path(AUTOMATION_CONFIG_PATH)
    guard = adapter.snapshots.get(expected_hash) if expected_hash is not None else None
    stale = expected_hash
    moves = 0
    async with adapter.lock:
        while True:
            entries, digest = await hass.async_add_executor_job(_read_file, path)
            adapter.remember(digest, entries)
            if stale is not None and digest != stale:
                moves += 1
            if expected_hash is not None and digest != expected_hash:
                _refuse_changed_target(automation_id, guard, entries)
            new_entries = build(entries)
            if new_entries is None:
                return digest, False
            written = await hass.async_add_executor_job(_replace_if, path, digest, new_entries)
            if written is not None:
                adapter.remember(written, new_entries)
                return written, True
            moves += 1
            if moves > 1:
                raise WriteConflictError(f"{AUTOMATION_CONFIG_PATH} moved twice")
            stale = None


@callback
def file_hash(hass: HomeAssistant) -> str:
    """Return the sha256 of `automations.yaml` as the adapter last read or wrote it.

    Taken right after `async_read_automation` (no await in between) it is the guard for
    that read, to pass as `expected_hash`. Empty before the first read or write.
    """
    return _data(hass).last_hash


async def async_read_automation(
    hass: HomeAssistant, automation_id: str
) -> Mapping[str, Any] | None:
    """Return the entry with this id from `automations.yaml`, or None."""
    adapter = _data(hass)
    async with adapter.lock:
        entries, digest = await hass.async_add_executor_job(
            _read_file, hass.config.path(AUTOMATION_CONFIG_PATH)
        )
        adapter.remember(digest, entries)
    return next((item for item in entries if _matches(item, automation_id)), None)


async def async_read_automations(hass: HomeAssistant) -> list[Mapping[str, Any]]:
    """Return every entry of `automations.yaml` that is a mapping, in file order.

    One read for callers that look at every entry (sync back, the reconcile scan, the
    index rebuild). Like `async_read_automation` it is remembered, so `file_hash` right
    after it (no await in between) guards a write based on it.
    """
    adapter = _data(hass)
    async with adapter.lock:
        entries, digest = await hass.async_add_executor_job(
            _read_file, hass.config.path(AUTOMATION_CONFIG_PATH)
        )
        adapter.remember(digest, entries)
    return [item for item in entries if isinstance(item, Mapping)]


async def async_write_automation(
    hass: HomeAssistant,
    automation_id: str,
    config: Mapping[str, Any],
    expected_hash: str | None,
) -> WriteResult:
    """Create or replace one owned entry, then reload that id only.

    Refuses with `NotOwnedError` unless the config carries M1 and M2 under this id and
    every entry it replaces does too. `expected_hash` is the `file_hash` of the caller's
    read, or None when the caller expects to create the entry or does not care what it
    holds. Raises `WriteConflictError` when the file moved twice, or when the target
    changed after the guarded read.
    """
    if config.get(CONF_ID) != automation_id or not markers.is_owned(config):
        raise NotOwnedError(f"refusing to write {automation_id}: the config lacks M1 or M2")
    created = False

    def build(entries: list[Any]) -> list[Any]:
        nonlocal created
        created = not _refuse_unowned(entries, automation_id)
        if created:
            return [*entries, _editor_ordered(automation_id, config)]
        return [
            _editor_ordered(automation_id, config) if _matches(item, automation_id) else item
            for item in entries
        ]

    digest, _ = await _async_rewrite(hass, automation_id, expected_hash, build)
    await hass.services.async_call(
        AUTOMATION_DOMAIN, SERVICE_RELOAD, {CONF_ID: automation_id}, blocking=True
    )
    return WriteResult(hash=digest, created=created)


async def async_delete_automation(hass: HomeAssistant, automation_id: str) -> bool:
    """Remove one owned entry and its entity registry entry, as the editor's delete does.

    Returns whether the file held the entry. Refuses with `NotOwnedError` an id without M1
    and an entry without M1 and M2. When the file no longer holds the entry, only a
    leftover registry entry with no loaded config is removed; an automation of that id
    defined elsewhere is left alone.
    """
    if not markers.has_routine_id({CONF_ID: automation_id}):
        raise NotOwnedError(f"refusing to delete {automation_id}: it lacks M1")

    def build(entries: list[Any]) -> list[Any] | None:
        if not _refuse_unowned(entries, automation_id):
            return None
        return [item for item in entries if not _matches(item, automation_id)]

    _, removed = await _async_rewrite(hass, automation_id, None, build)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, automation_id)
    if entity_id is not None and (removed or automation_config(hass, entity_id) is None):
        registry.async_remove(entity_id)
    return removed


# --------------------------------------------------------------------------------------
# The blueprint
# --------------------------------------------------------------------------------------


def _blueprint_path(hass: HomeAssistant) -> str:
    return hass.config.path(BLUEPRINT_FOLDER, AUTOMATION_DOMAIN, markers.BLUEPRINT_PATH)


async def async_install_blueprint(hass: HomeAssistant, text: str) -> bool:
    """Install the routine blueprint at `markers.BLUEPRINT_PATH`, usable at once.

    Goes through `DomainBlueprints.async_add_blueprint` with override allowed (the method
    `blueprint/save` calls), which validates the blueprint and reloads its users, then
    puts the exact text in the file, so the installed file hashes like the shipped one.
    Returns whether a previous file was replaced.
    """
    data = ha_yaml.parse_yaml(text)
    if not isinstance(data, dict):
        raise AdapterError("the blueprint text is not a mapping")
    blueprint = blueprint_models.Blueprint(
        data,
        expected_domain=AUTOMATION_DOMAIN,
        schema=automation_config_schema.AUTOMATION_BLUEPRINT_SCHEMA,
    )
    replaced = await automation_helpers.async_get_blueprints(hass).async_add_blueprint(
        blueprint, markers.BLUEPRINT_PATH, allow_override=True
    )
    await hass.async_add_executor_job(ha_file.write_utf8_file_atomic, _blueprint_path(hass), text)
    return bool(replaced)


def installed_blueprint_text(hass: HomeAssistant) -> str | None:
    """Return the installed blueprint file's text, or None. Blocking: run it in the executor."""
    try:
        return Path(_blueprint_path(hass)).read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None


# --------------------------------------------------------------------------------------
# The system user and the timer and schedule helpers
# --------------------------------------------------------------------------------------


async def async_ensure_system_user(hass: HomeAssistant, user_id: str | None) -> str:
    """Return the id of the integration's system administrator user, creating it if needed.

    The stored id is kept while it names a system user; None, an id that names no user
    and an id that names a person all get a new `Device Routines` system user in the
    administrators group. A system user moved out of that group stays as it is, and the
    helper commands then refuse it.
    """
    if user_id is not None:
        user = await hass.auth.async_get_user(user_id)
        if user is not None and user.system_generated:
            return user.id
    created = await hass.auth.async_create_system_user(
        INTEGRATION_TITLE, group_ids=[GROUP_ID_ADMIN]
    )
    return created.id


def _decoded(message: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    return cast("dict[str, Any]", json_loads(message))


async def _async_command(hass: HomeAssistant, user_id: str, command: dict[str, Any]) -> Any:
    """Dispatch one registered WebSocket command in process as the user; return its result."""
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise HelperError("unknown_user", "the stored system user does not exist")
    reply: asyncio.Future[dict[str, Any]] = hass.loop.create_future()

    def send(message: bytes | str | dict[str, Any]) -> None:
        if not reply.done():
            reply.set_result(_decoded(message))

    def dispatch() -> None:
        connection = ActiveConnection(
            WebSocketAdapter(_LOGGER, {"connid": DOMAIN}), hass, send, user, None, None
        )
        connection.async_handle({"id": 1, **command})

    # The connection marks itself current in the context it is built in; build it in a
    # copy, so the caller's context never carries it.
    contextvars.copy_context().run(dispatch)
    try:
        async with asyncio.timeout(_COMMAND_TIMEOUT):
            message = await reply
    except TimeoutError as err:
        raise HelperError("timeout", f"{command['type']} did not answer") from err
    if not message.get("success"):
        error = message.get("error") or {}
        raise HelperError(str(error.get("code")), str(error.get("message")))
    return message.get("result")


def _helper_item(hass: HomeAssistant, entity_id: str) -> tuple[str, str]:
    """Return the domain and the storage item id behind a helper entity."""
    domain = split_entity_id(entity_id)[0]
    if domain not in _HELPER_DOMAINS:
        raise HelperError("not_a_helper", f"{entity_id} is not a timer or a schedule")
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != domain:
        raise HelperError("not_found", f"{entity_id} has no registry entry")
    return domain, entry.unique_id


async def async_create_helper(  # noqa: PLR0913  # the contract's positionals plus registry options
    hass: HomeAssistant,
    user_id: str,
    domain: Literal["timer", "schedule"],
    name: str,
    *,
    entity_id: str | None = None,
    labels: Collection[str] | None = None,
    **fields: Any,
) -> str:
    """Create a timer or schedule helper through its WebSocket command; return its entity id.

    `fields` go to the command (`duration`, `restore`, `icon`, the weekday blocks). The
    optional `entity_id` and `labels` are then set in the entity registry; if that fails
    (an entity id already taken), the new helper is deleted again and the registry's
    `ValueError` raised. No device is attached: a helper has no config entry, and core
    2026.10 drops the device of such an entity whenever it is added again.
    """
    item = await _async_command(hass, user_id, {"type": f"{domain}/create", "name": name, **fields})
    created = er.async_get(hass).async_get_entity_id(domain, domain, item[CONF_ID])
    if created is None:
        raise HelperError("not_found", f"the new {domain} has no registry entry")
    if entity_id is None and labels is None:
        return created
    try:
        return async_update_registry_entity(
            hass,
            created,
            new_entity_id=UNDEFINED if entity_id is None else entity_id,
            labels=UNDEFINED if labels is None else labels,
        )
    except ValueError:
        await _async_command(
            hass, user_id, {"type": f"{domain}/delete", f"{domain}_id": item[CONF_ID]}
        )
        raise


async def async_update_helper(
    hass: HomeAssistant, user_id: str, entity_id: str, **fields: Any
) -> None:
    """Change some fields of a timer or schedule helper, keeping the others.

    The update commands replace the whole item, so the current item is read first and
    the given fields merged into it.
    """
    domain, item_id = _helper_item(hass, entity_id)
    items = await _async_command(hass, user_id, {"type": f"{domain}/list"})
    current = next((item for item in items if item[CONF_ID] == item_id), None)
    if current is None:
        raise HelperError("not_found", f"{entity_id} is not a {domain} the commands manage")
    merged = {key: value for key, value in current.items() if key != CONF_ID} | fields
    await _async_command(
        hass, user_id, {"type": f"{domain}/update", f"{domain}_id": item_id, **merged}
    )


async def async_delete_helper(hass: HomeAssistant, user_id: str, entity_id: str) -> None:
    """Delete a timer or schedule helper; its entity and registry entry go with it."""
    domain, item_id = _helper_item(hass, entity_id)
    await _async_command(hass, user_id, {"type": f"{domain}/delete", f"{domain}_id": item_id})


@callback
def async_update_registry_entity(  # noqa: PLR0913  # one keyword per registry field set
    hass: HomeAssistant,
    entity_id: str,
    *,
    new_entity_id: str | UndefinedType = UNDEFINED,
    labels: Collection[str] | UndefinedType = UNDEFINED,
    device_id: str | UndefinedType | None = UNDEFINED,
    area_id: str | UndefinedType | None = UNDEFINED,
    icon: str | UndefinedType | None = UNDEFINED,
    categories: Mapping[str, str] | UndefinedType = UNDEFINED,
) -> str:
    """Set registry fields of an entity and return its entity id afterwards.

    Each field left out stays as it is; `labels` and `categories` replace the whole set.
    The registry's own errors propagate: `KeyError` for an unknown entity, `ValueError`
    for an entity id already taken. A `device_id` only lasts on an entity that belongs to
    a config entry; core 2026.10 drops it from any other (a helper, an automation) the
    next time the entity is added.
    """
    entry = er.async_get(hass).async_update_entity(
        entity_id,
        new_entity_id=new_entity_id,
        labels=UNDEFINED if isinstance(labels, UndefinedType) else set(labels),
        device_id=device_id,
        area_id=area_id,
        icon=icon,
        categories=UNDEFINED if isinstance(categories, UndefinedType) else dict(categories),
    )
    return entry.entity_id


# --------------------------------------------------------------------------------------
# Labels, categories and restore state
# --------------------------------------------------------------------------------------


@callback
def ensure_label(hass: HomeAssistant, label_id: str, name: str, icon: str) -> str:
    """Return the id of the label with this id or name, creating it, with the right icon."""
    registry = lr.async_get(hass)
    label = registry.async_get_label(label_id) or registry.async_get_label_by_name(name)
    if label is None:
        return registry.async_create(name, icon=icon).label_id
    if label.icon != icon:
        registry.async_update(label.label_id, icon=icon)
    return label.label_id


@callback
def ensure_category(hass: HomeAssistant, scope: str, name: str, icon: str) -> str:
    """Return the id of the category with this name in the scope, creating it, with the icon."""
    registry = cr.async_get(hass)
    category = next(
        (
            item
            for item in registry.async_list_categories(scope=scope)
            if item.name.casefold() == name.casefold()
        ),
        None,
    )
    if category is None:
        return registry.async_create(scope=scope, name=name, icon=icon).category_id
    if category.icon != icon:
        registry.async_update(scope=scope, category_id=category.category_id, icon=icon)
    return category.category_id


@callback
def missed_timer_finishes(hass: HomeAssistant, timer_entity_ids: Iterable[str]) -> list[str]:
    """Return the timers the restore cache shows ran out while Home Assistant was down.

    A timer saved `active` with a `finishes_at` in the past was finished during startup
    before any trigger was armed (Stage 0 V10, decision L20); one paused, idle or with
    time left is not reported. Call it once, during startup.
    """
    last_states = restore_state.async_get(hass).last_states
    now = dt_util.utcnow()
    missed: list[str] = []
    for entity_id in timer_entity_ids:
        stored = last_states.get(entity_id)
        if stored is None or stored.state.state != STATUS_ACTIVE:
            continue
        finishes_at = dt_util.parse_datetime(str(stored.state.attributes.get(ATTR_FINISHES_AT)))
        if finishes_at is not None and dt_util.as_utc(finishes_at) <= now:
            missed.append(entity_id)
    return missed
