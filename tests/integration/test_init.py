"""Setup and unload of the config entry, and the hub device it creates."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_routines.const import DOMAIN, HUB_IDENTIFIER, INTEGRATION_TITLE

HEALTH = "sensor.device_routines_health"


async def test_setup_loads_and_unload_unloads(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    assert init_integration.state is ConfigEntryState.LOADED
    health = hass.states.get(HEALTH)
    assert health is not None
    assert health.state == "ok"

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    assert entry_state(hass, init_integration.entry_id) is ConfigEntryState.NOT_LOADED
    unavailable = hass.states.get(HEALTH)
    assert unavailable is not None
    assert unavailable.state == STATE_UNAVAILABLE


def entry_state(hass: HomeAssistant, entry_id: str) -> ConfigEntryState:
    """Read the state afresh, so a type checker cannot narrow it across the unload."""
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry is not None
    return entry.state


async def test_the_hub_device_is_a_service_device(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, HUB_IDENTIFIER), init_integration.entry_id
    )

    assert device is not None
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.name == INTEGRATION_TITLE
    assert device.sw_version == integration.version
    assert device.manufacturer == INTEGRATION_TITLE


async def test_yaml_configuration_raises_a_repair_issue(hass: HomeAssistant) -> None:
    """The domain is UI only: a YAML block under it is reported, not configured."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {"anything": 1}})
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue("homeassistant", f"config_entry_only_{DOMAIN}")

    assert issue is not None
    assert issue.issue_domain == DOMAIN
