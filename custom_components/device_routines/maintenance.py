"""The four maintenance actions and the cleanup rule (PRD 10.4 and D28, TECH_SPEC 4.6).

`async_run` serves the hub button, the `device_routines.maintenance` action, the console
and the WebSocket command alike; callers pass the loaded entry's manager as the target
(decision L39). Every action is idempotent and safe at any time. With `dry_run` nothing
changes and the report lists what would; without it the report lists what changed.

- `clean_up_now`: every cleanup candidate, whatever its age (the button is for people who
  do not want to wait): the manager deletes the routine's automation, helpers and
  entities, then this module drops the device from the Store. `changed` holds device ids.
- `rebuild_index`: the manager rebuilds the Store's index from the markers and the
  registries (TECH_SPEC 6 and 7 step 4). `changed` holds automation ids.
- `reinstall_blueprint`: puts the shipped blueprint back when the installed file differs
  or is missing, through the adapter (usable at once, users reloaded), and records its
  hash. `changed` holds the blueprint path.
- `refresh_summaries`: the manager recomputes every Schedule summary. Recomputing is the
  action, so `changed` lists the devices recomputed every time it runs.

The cleanup rule (D28) lives here as well, for the manager's automatic cleanup: a device
opted out and not opted back in, or removed from Home Assistant, is a candidate from that
moment; it is due once `cleanup_after_days` have passed, and 0 means never.

Errors (quality rule `action-exceptions`). An action that cannot finish raises a
`HomeAssistantError` with the translation key `maintenance_failed`, naming the action and
what went wrong, never a bare adapter error; a refusal that is already translated (a
`ServiceValidationError`, say) passes unchanged.

Removing the integration (decision L51: the logic lives here, `async_remove_entry` calls
`async_remove_integration`) applies On removal (PRD 8.2, TECH_SPEC 4.12) after the entry
unloaded, through the adapter's two removal capabilities (decision L37): keep (the
default) takes control of every owned automation, so it keeps running as a plain
automation described as formerly managed; delete removes every owned automation with its
timer and schedule helpers. Both then remove what the integration created once nothing
uses it: the blueprint, the system user (L23), the Routines label and the Device Routines
category, the Repairs issues and the Store.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import logging
from pathlib import Path
from typing import Any, Final, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    category_registry as cr,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
    label_registry as lr,
    storage,
)

from . import compiler, ha_adapter, markers
from .const import CONF_SYSTEM_USER_ID, DOMAIN
from .sentence import load_phrases
from .settings import OnRemoval, from_options
from .store import STORAGE_KEY, STORAGE_VERSION, RoutineStore, StoreData

_LOGGER = logging.getLogger(__name__)

# The blueprint file the integration ships (TECH_SPEC 5.1).
SHIPPED_BLUEPRINT: Final = Path(__file__).parent / "blueprints" / "device_routine.yaml"


class MaintenanceAction(StrEnum):
    """The maintenance actions of PRD 10.4."""

    CLEAN_UP_NOW = "clean_up_now"
    REBUILD_INDEX = "rebuild_index"
    REINSTALL_BLUEPRINT = "reinstall_blueprint"
    REFRESH_SUMMARIES = "refresh_summaries"


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    """What an action changed, or with a dry run, what it would change."""

    action: MaintenanceAction
    changed: list[str] = field(default_factory=list)
    would_change: list[str] = field(default_factory=list)


class MaintenanceTarget(Protocol):
    """What the maintenance actions need from the manager (lane 5 implements it)."""

    @property
    def store(self) -> RoutineStore:
        """The loaded Store the manager keeps its index in."""
        ...

    async def async_delete_routine(self, device_id: str) -> None:
        """Delete what Home Assistant holds for the device's routine.

        Its owned automation (through the adapter), its timer and schedule helpers and
        its entities, and stop tracking it in memory. Leave the Store to the caller,
        which drops the device's records once this returns. Idempotent: a device with
        nothing left is no error. Raise when something could not be deleted; the caller
        keeps the device's records, so the next cleanup retries.
        """
        ...

    async def async_rebuild_index(self, *, dry_run: bool) -> list[str]:
        """Rebuild what the Store's index holds from the markers and the registries.

        TECH_SPEC 6 and 7 step 4: `owned` from the entries carrying M1 and M2,
        `opted_in` from the Routines label (never wiped because the label itself is
        missing, plan Section 4.9), `blueprint_hash` from the installed file;
        `opted_out_at` and `ai_cache` are kept. Return the sorted automation ids whose
        record was added, changed or dropped; with `dry_run`, the ids that would be, and
        change nothing.
        """
        ...

    async def async_refresh_summaries(self, *, dry_run: bool) -> list[str]:
        """Recompute every Schedule summary and routine view.

        Return the sorted device ids recomputed; with `dry_run`, the ids that would be,
        and change nothing.
        """
        ...

    async def async_blueprint_reinstalled(self) -> None:
        """React to `reinstall_blueprint` having replaced or created the installed file.

        Clear `blueprint_modified`, run the blueprint schema migration when it is due,
        publish Health. Never called on a dry run or when the file was already shipped.
        """
        ...


def shipped_blueprint_text() -> str:
    """Return the shipped blueprint's text. Blocking: run it in the executor."""
    return SHIPPED_BLUEPRINT.read_text(encoding="utf-8")


def blueprint_hash(text: str) -> str:
    """Return the hash the Store keeps for a blueprint text (`blueprint_hash`)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# The cleanup rule of D28
# --------------------------------------------------------------------------------------


def cleanup_candidates(data: StoreData) -> dict[str, datetime]:
    """Map every cleanup candidate to the moment it became one.

    A device opted out and not opted back in, or removed from Home Assistant; for one
    that is both, the earlier moment counts.
    """
    since = {
        device_id: moment
        for device_id, moment in data.opted_out_at.items()
        if device_id not in data.opted_in
    }
    for device_id, moment in data.removed_devices_at.items():
        since[device_id] = min(moment, since.get(device_id, moment))
    return since


def due_for_cleanup(data: StoreData, now: datetime, cleanup_after_days: int) -> list[str]:
    """Return the sorted device ids whose cleanup period has passed; none for 0 (never)."""
    if cleanup_after_days <= 0:
        return []
    period = timedelta(days=cleanup_after_days)
    return sorted(
        device_id
        for device_id, moment in cleanup_candidates(data).items()
        if now - moment >= period
    )


def next_cleanup_at(data: StoreData, cleanup_after_days: int) -> datetime | None:
    """Return when the next candidate is due, so the manager can wake up then."""
    candidates = cleanup_candidates(data)
    if cleanup_after_days <= 0 or not candidates:
        return None
    return min(candidates.values()) + timedelta(days=cleanup_after_days)


async def async_clean_up(target: MaintenanceTarget, device_ids: list[str]) -> list[str]:
    """Delete the routines of these devices and drop them from the Store.

    Returns the device ids cleaned up. One that fails keeps its records and is retried
    by the next cleanup; the others go on.
    """
    data = target.store.data
    cleaned: list[str] = []
    for device_id in device_ids:
        try:
            await target.async_delete_routine(device_id)
        except Exception:  # one failure must not stop the others
            _LOGGER.warning("Could not clean up the routine of %s", device_id, exc_info=True)
            continue
        for automation_id, record in list(data.owned.items()):
            if record.device_id == device_id:
                del data.owned[automation_id]
                data.suspended.pop(automation_id, None)
        data.own_helpers.pop(device_id, None)
        data.opted_out_at.pop(device_id, None)
        data.removed_devices_at.pop(device_id, None)
        data.opted_in.discard(device_id)
        cleaned.append(device_id)
    if cleaned:
        await target.store.async_save()
    return cleaned


# --------------------------------------------------------------------------------------
# The actions
# --------------------------------------------------------------------------------------


async def _async_clean_up_now(target: MaintenanceTarget, dry_run: bool) -> list[str]:
    candidates = sorted(cleanup_candidates(target.store.data))
    if dry_run:
        return candidates
    return await async_clean_up(target, candidates)


async def _async_reinstall_blueprint(
    hass: HomeAssistant, target: MaintenanceTarget, dry_run: bool
) -> list[str]:
    shipped = await hass.async_add_executor_job(shipped_blueprint_text)
    installed = await hass.async_add_executor_job(ha_adapter.installed_blueprint_text, hass)
    if installed == shipped:
        return []
    if not dry_run:
        await ha_adapter.async_install_blueprint(hass, shipped)
        target.store.data.blueprint_hash = blueprint_hash(shipped)
        await target.store.async_save()
        await target.async_blueprint_reinstalled()
    return [markers.BLUEPRINT_PATH]


async def async_run(
    hass: HomeAssistant,
    target: MaintenanceTarget,
    action: MaintenanceAction | str,
    dry_run: bool,
) -> MaintenanceReport:
    """Run one maintenance action; raise `ValueError` for a name that is not one.

    A failure raises the translated `maintenance_failed` (see the module docstring).
    """
    action = MaintenanceAction(action)
    runs: dict[MaintenanceAction, Callable[[], Awaitable[list[str]]]] = {
        MaintenanceAction.CLEAN_UP_NOW: lambda: _async_clean_up_now(target, dry_run),
        MaintenanceAction.REBUILD_INDEX: lambda: target.async_rebuild_index(dry_run=dry_run),
        MaintenanceAction.REINSTALL_BLUEPRINT: lambda: _async_reinstall_blueprint(
            hass, target, dry_run
        ),
        MaintenanceAction.REFRESH_SUMMARIES: lambda: target.async_refresh_summaries(
            dry_run=dry_run
        ),
    }
    try:
        changes = await runs[action]()
    except HomeAssistantError as err:
        if err.translation_key is not None:
            raise
        raise _failed(action, err) from err
    except (ha_adapter.AdapterError, OSError) as err:
        raise _failed(action, err) from err
    _LOGGER.debug("Maintenance %s (dry run %s): %s", action, dry_run, changes)
    if dry_run:
        return MaintenanceReport(action=action, would_change=changes)
    return MaintenanceReport(action=action, changed=changes)


def _failed(action: MaintenanceAction, err: Exception) -> HomeAssistantError:
    """Return the translated error of an action that could not finish."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="maintenance_failed",
        translation_placeholders={"action": str(action), "error": str(err)},
    )


# --------------------------------------------------------------------------------------
# Removing the integration: On removal, keep or delete (Build A lane 10, decision L51)
# --------------------------------------------------------------------------------------

# The device page entities the blueprint reads go with the entry. A kept automation names
# the unused sentinels instead, so it never reads or writes the entities a later
# installation registers for the same device.
_RELEASED_INPUTS: Final[Mapping[str, str]] = {
    "override_entity": compiler.UNUSED_SWITCH,
    "paused_until_entity": compiler.UNUSED_DATETIME,
}


async def async_remove_integration(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply On removal, then remove what the integration created (module docstring).

    The entry is no longer loaded: the Store is read here, ownership is read from the
    markers in `automations.yaml`, and every write goes through the adapter. A step that
    fails is logged and the later steps still run, because Home Assistant removes the
    entry whatever happens here.
    """
    data = await _async_load_store(hass)
    user_id: str | None = entry.data.get(CONF_SYSTEM_USER_ID)
    try:
        entries = await ha_adapter.async_read_automations(hass)
        owned = [item for item in entries if markers.is_owned(item)]
        if from_options(entry.options).on_removal is OnRemoval.DELETE:
            user_id = await _async_delete_routines(hass, owned, data, user_id)
        else:
            await _async_release_routines(hass, owned)
        await ha_adapter.async_remove_blueprint(hass)
    except ha_adapter.AdapterError:
        _LOGGER.warning(
            "Could not read the automations file; the routine automations and the "
            "blueprint were left as they are",
            exc_info=True,
        )
    if user_id is not None:
        try:
            await ha_adapter.async_remove_system_user(hass, user_id)
        except ha_adapter.AdapterError:
            _LOGGER.warning("The stored system user was left alone", exc_info=True)
    _remove_unused_label_and_category(hass)
    registry = ir.async_get(hass)
    for issue_id in [issue_id for domain, issue_id in registry.issues if domain == DOMAIN]:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    await storage.Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY).async_remove()


async def _async_load_store(hass: HomeAssistant) -> StoreData:
    """Read the Store as the unloaded entry left it; an unreadable one reads as empty."""
    try:
        return await RoutineStore(hass).async_load()
    except HomeAssistantError:
        _LOGGER.warning("Could not read the Device Routines storage file", exc_info=True)
        return StoreData()


async def _async_release_routines(hass: HomeAssistant, owned: list[Mapping[str, Any]]) -> None:
    """Keep: write the form Take control makes of every owned automation (Stage 0 V8).

    Each entry is read again right before its release, so the write guard covers it;
    one that changed since the scan (no longer owned) is refused by the adapter and
    stays as the person left it.
    """
    phrases = await hass.async_add_executor_job(load_phrases, hass.config.language)
    for item in owned:
        automation_id = item["id"]
        try:
            current = await ha_adapter.async_read_automation(hass, automation_id)
            guard = ha_adapter.file_hash(hass)
            config = _standalone(current or {})
            plain = await ha_adapter.async_take_control_config(hass, config)
            name = _device_name(hass, _inputs(config).get("device_id"))
            plain["description"] = markers.presentation(name, phrases, formerly=True).description
            await ha_adapter.async_release_automation(hass, automation_id, plain, guard)
        except ha_adapter.AdapterError:
            _LOGGER.warning("Could not take control of %s; it was left as it is", automation_id)


async def _async_delete_routines(
    hass: HomeAssistant,
    owned: list[Mapping[str, Any]],
    data: StoreData,
    user_id: str | None,
) -> str | None:
    """Delete: remove every owned automation and its helpers; return the system user used.

    The helpers are the timer and the schedule the entry's inputs or the Store's last
    valid inputs name, and those the Store remembers creating for the device's routine
    (a weekly schedule kept after Days changed back), each only while it carries the
    Routines label, so a helper a person linked to a routine themselves is never deleted.
    """
    label_id = _label_id(hass)
    registry = er.async_get(hass)
    for item in owned:
        automation_id = item["id"]
        record = data.owned.get(automation_id)
        device_id = _inputs(item).get("device_id")
        helpers = (
            _helpers(_inputs(item))
            | _helpers(record.last_valid_inputs if record else None)
            | set(data.own_helpers.get(device_id, ()) if isinstance(device_id, str) else ())
        )
        try:
            await ha_adapter.async_delete_automation(hass, automation_id)
        except ha_adapter.AdapterError:
            _LOGGER.warning("Could not delete %s; it was left as it is", automation_id)
            continue
        for entity_id in sorted(helpers):
            helper = registry.async_get(entity_id)
            if helper is None or label_id not in helper.labels:
                continue
            try:
                user_id = await ha_adapter.async_ensure_system_user(hass, user_id)
                await ha_adapter.async_delete_helper(hass, user_id, entity_id)
            except ha_adapter.AdapterError:
                _LOGGER.warning("Could not delete %s", entity_id, exc_info=True)
    return user_id


def _inputs(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the blueprint inputs of an entry, or nothing when it has none."""
    block = config.get("use_blueprint")
    inputs = block.get("input") if isinstance(block, Mapping) else None
    return inputs if isinstance(inputs, Mapping) else {}


def _standalone(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return an owned entry with the inputs that name the entry's own entities unused."""
    if not markers.is_owned(config):
        return config
    block = config["use_blueprint"]
    return {**config, "use_blueprint": {**block, "input": {**_inputs(config), **_RELEASED_INPUTS}}}


def _helpers(inputs: Mapping[str, Any] | None) -> set[str]:
    """Return the timer and schedule helpers blueprint inputs name, sentinels left out."""
    if inputs is None or not compiler.is_valid_shape(inputs):
        return set()
    refs = compiler.refs_of(inputs)
    return {refs.timer_entity, refs.schedule_entity} - {
        compiler.UNUSED_TIMER,
        compiler.UNUSED_SCHEDULE,
    }


def _device_name(hass: HomeAssistant, device_id: Any) -> str:
    """Return the name a device shows, or the id itself when it is gone."""
    device = dr.async_get(hass).async_get(device_id) if isinstance(device_id, str) else None
    return (device.name_by_user or device.name or device.id) if device else str(device_id)


def _label_id(hass: HomeAssistant) -> str | None:
    """Return the Routines label's id, found by id or by name as the manager finds it."""
    registry = lr.async_get(hass)
    label = registry.async_get_label(markers.LABEL_ID) or registry.async_get_label_by_name(
        markers.LABEL_NAME
    )
    return label.label_id if label else None


def _remove_unused_label_and_category(hass: HomeAssistant) -> None:
    """Delete the Routines label and the Device Routines category once nothing carries them.

    A device still labelled, a kept automation or helper, or anything a person tagged
    with them keeps them; this entry's own entities never carry either.
    """
    label_id = _label_id(hass)
    if label_id is not None and not (
        dr.async_entries_for_label(dr.async_get(hass), label_id)
        or er.async_entries_for_label(er.async_get(hass), label_id)
        or ar.async_entries_for_label(ar.async_get(hass), label_id)
    ):
        lr.async_get(hass).async_delete(label_id)
    categories = cr.async_get(hass)
    category = next(
        (
            item
            for item in categories.async_list_categories(scope="automation")
            if item.name.casefold() == markers.CATEGORY_NAME.casefold()
        ),
        None,
    )
    if category is not None and not er.async_entries_for_category(
        er.async_get(hass), "automation", category.category_id
    ):
        categories.async_delete(scope="automation", category_id=category.category_id)
