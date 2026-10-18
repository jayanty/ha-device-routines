"""Device Routines: schedules, run timers and a schedule summary on every device page.

Phase 1: a zero field config entry, the hub device with its Health sensor, diagnostics and
the SummaryCoordinator that puts a Schedule sensor on every device an automation acts on.
The routine controls and the managed automations arrive phase by phase
(docs/IMPLEMENTATION_PLAN.md). Everything the entry
owns hangs on `entry.runtime_data`; nothing is kept in `hass.data`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import ha_adapter, health
from .const import DOMAIN, PLATFORMS
from .ha_adapter import AdapterReport
from .health import HealthReport
from .sentence import load_phrases
from .settings import GlobalSettings, from_options
from .summary import SummaryCoordinator

__all__ = [
    "CONFIG_SCHEMA",
    "DOMAIN",
    "DeviceRoutinesConfigEntry",
    "DeviceRoutinesRuntimeData",
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
    health: HealthReport
    settings: GlobalSettings
    adapter: AdapterReport
    summary: SummaryCoordinator


type DeviceRoutinesConfigEntry = ConfigEntry[DeviceRoutinesRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Nothing happens until a config entry exists."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DeviceRoutinesConfigEntry) -> bool:
    """Build the runtime data and set up the platforms."""
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version or "0.0.0")
    report = await health.async_collect(hass, version)
    settings = from_options(entry.options)
    phrases = await hass.async_add_executor_job(load_phrases, hass.config.language)
    summary = SummaryCoordinator(hass, entry.entry_id, settings, phrases)
    entry.runtime_data = DeviceRoutinesRuntimeData(
        version=version,
        health=report,
        settings=settings,
        adapter=ha_adapter.check(hass),
        summary=summary,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await summary.async_start()
    entry.async_on_unload(summary.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DeviceRoutinesConfigEntry) -> bool:
    """Take the platforms down."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
