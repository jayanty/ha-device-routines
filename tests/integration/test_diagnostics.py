"""Config entry diagnostics: the report shape, with nothing that names a network."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.device_routines.const import DOMAIN


async def test_diagnostics_report_the_integration_and_its_health(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, init_integration: MockConfigEntry
) -> None:
    integration = await async_get_integration(hass, DOMAIN)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert set(diagnostics) == {"integration", "summary"}
    assert diagnostics["summary"]["devices"] == 0
    assert diagnostics["integration"]["settings"]["schedule_scope"] == "all"
    assert diagnostics["integration"]["adapter"] == {"failed": []}
    assert diagnostics["integration"]["version"] == integration.version
    assert diagnostics["integration"]["entry_id"] == init_integration.entry_id
    assert diagnostics["integration"]["options"] == {}
    assert diagnostics["integration"]["health"]["state"] == "ok"
    assert diagnostics["integration"]["health"]["channel"] == "unknown"


async def test_diagnostics_redact_secret_shaped_options(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, init_integration: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        init_integration, options={"token": "secret", "schedule_scope": "all"}
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert diagnostics["integration"]["options"] == {
        "token": "**REDACTED**",
        "schedule_scope": "all",
    }
