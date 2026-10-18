"""Device Routines: schedules, run timers and a schedule summary on every device page.

A zero field config entry, the hub device with its Health sensor, diagnostics, the
SummaryCoordinator that puts a Schedule sensor on every device an automation acts on, and
the RoutineManager (Build A lane 5) that turns device settings into managed automations
and keeps them healthy. Everything the entry owns hangs on `entry.runtime_data`; nothing
is kept in `hass.data`.

Setup order: the Store loads, the manager starts (it reconciles at once in a running
instance, or after the started event while Home Assistant boots), the platforms come up
on the reconciled state, and the summary starts last, so its first index already sees
the routines. Removing the entry (On removal, keep or delete) arrives with Build A lane
10, which adds the two adapter capabilities it needs (decision L37).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import ha_adapter, health, repairs, websocket_api
from .attribution import Attributor
from .const import DOMAIN, PLATFORMS
from .ha_adapter import AdapterReport
from .health import HealthMonitor
from .manager import RoutineManager
from .migration import async_migrate_entry
from .sentence import load_phrases
from .services import async_setup_services
from .settings import GlobalSettings, from_options
from .store import RoutineStore
from .summary import SummaryCoordinator

__all__ = [
    "CONFIG_SCHEMA",
    "DOMAIN",
    "DeviceRoutinesConfigEntry",
    "DeviceRoutinesRuntimeData",
    "async_migrate_entry",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
]

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
