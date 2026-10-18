"""Device Routines: schedules, run timers and a schedule summary on every device page.

A zero field config entry, the hub device with its Health sensor, diagnostics, the
SummaryCoordinator that puts a Schedule sensor on every device an automation acts on, and
the RoutineManager (Build A lane 5) that turns device settings into managed automations
and keeps them healthy. Everything the entry owns hangs on `entry.runtime_data`; nothing
is kept in `hass.data`.

Setup order: the Store loads, the manager starts (it reconciles at once in a running
instance, or after the started event while Home Assistant boots), the platforms come up
on the reconciled state, and the summary starts last, so its first index already sees
the routines.

Removing the entry applies On removal (PRD 8.2, TECH_SPEC 4.12, Build A lane 10) in
`async_remove_entry`, after the entry unloaded, through the adapter's two removal
capabilities (decision L37): keep (the default) takes control of every owned automation,
so it keeps running as a plain automation described as formerly managed; delete removes
every owned automation with its timer and schedule helpers. Both then remove what the
integration created once nothing uses it: the blueprint, the system user (L23), the
Routines label and the Device Routines category, the Repairs issues and the Store.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    category_registry as cr,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
    label_registry as lr,
    storage,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import compiler, ha_adapter, health, markers, repairs, websocket_api
from .attribution import Attributor
from .const import CONF_SYSTEM_USER_ID, DOMAIN, PLATFORMS
from .ha_adapter import AdapterReport
from .health import HealthMonitor
from .manager import RoutineManager
from .migration import async_migrate_entry
from .sentence import load_phrases
from .services import async_setup_services
from .settings import GlobalSettings, OnRemoval, from_options
from .store import STORAGE_KEY, STORAGE_VERSION, RoutineStore, StoreData
from .summary import SummaryCoordinator

__all__ = [
    "CONFIG_SCHEMA",
    "DOMAIN",
    "DeviceRoutinesConfigEntry",
    "DeviceRoutinesRuntimeData",
    "async_migrate_entry",
    "async_remove_entry",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
]

_LOGGER = logging.getLogger(__name__)

# Set up through the UI only: YAML under this domain is a mistake, not a configuration.
CONFIG_SCHEMA: Final = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(frozen=True, slots=True)
class DeviceRoutinesRuntimeData:
    """What the loaded entry owns."""

    version: str
    health: HealthMonitor
    settings: GlobalSettings
    adapter: AdapterReport
    summary: SummaryCoordinator
    store: RoutineStore
    manager: RoutineManager


type DeviceRoutinesConfigEntry = ConfigEntry[DeviceRoutinesRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions (quality rule `action-setup`); the rest waits for an entry."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DeviceRoutinesConfigEntry) -> bool:
    """Build the runtime data, start the manager and set up the platforms."""
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version or "0.0.0")
    settings = from_options(entry.options)
    phrases = await hass.async_add_executor_job(load_phrases, hass.config.language)
    store = RoutineStore(hass)
    await store.async_load()
    summary = SummaryCoordinator(hass, entry.entry_id, settings, phrases)
    adapter = ha_adapter.check(hass)
    repairs.async_sync_adapter_issue(hass, adapter)
    manager = RoutineManager(hass, entry, store, summary, Attributor)
    # Health follows the manager from before its first reconcile (Build A lane 15).
    monitor = await health.async_start_monitor(hass, version, manager)
    entry.async_on_unload(monitor.async_stop)
    entry.runtime_data = DeviceRoutinesRuntimeData(
        version=version,
        health=monitor,
        settings=settings,
        adapter=adapter,
        summary=summary,
        store=store,
        manager=manager,
    )
    websocket_api.async_register(hass)
    await manager.async_start()
    entry.async_on_unload(manager.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await summary.async_start()
    entry.async_on_unload(summary.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DeviceRoutinesConfigEntry) -> bool:
    """Take the platforms down; the manager and the summary stop on unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# --------------------------------------------------------------------------------------
# Removal: On removal, keep or delete (Build A lane 10)
# --------------------------------------------------------------------------------------

# The device page entities the blueprint reads go with the entry. A kept automation names
# the unused sentinels instead, so it never reads or writes the entities a later
# installation registers for the same device.
_RELEASED_INPUTS: Final[Mapping[str, str]] = {
    "override_entity": compiler.UNUSED_SWITCH,
    "paused_until_entity": compiler.UNUSED_DATETIME,
}


async def async_remove_entry(hass: HomeAssistant, entry: DeviceRoutinesConfigEntry) -> None:
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
    valid inputs name, each only while it carries the Routines label, so a helper a
    person linked to a routine themselves is never deleted.
    """
    label_id = _label_id(hass)
    registry = er.async_get(hass)
    for item in owned:
        automation_id = item["id"]
        record = data.owned.get(automation_id)
        helpers = _helpers(_inputs(item)) | _helpers(record.last_valid_inputs if record else None)
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
