"""Shared fixtures: a config entry for the integration, set up the way a user's system does."""

from __future__ import annotations

import shutil

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, get_test_config_dir

from custom_components.device_routines.config_flow import DeviceRoutinesConfigFlow
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/device_routines in every test."""
    return


@pytest.fixture
def hass_config_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Give every test its own copy of the harness config directory.

    Setting the integration up installs the routine blueprint into the config directory
    (TECH_SPEC 7 step 2); the default directory lives inside the harness package and is
    shared by every test run, so each test writes into its own temporary copy instead,
    apart from `tmp_path`, which tests use for their own files.
    """
    config_dir = tmp_path_factory.mktemp("config")
    shutil.copytree(get_test_config_dir(), config_dir, symlinks=True, dirs_exist_ok=True)
    return str(config_dir)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return the single config entry the zero field flow creates."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_TITLE,
        data={},
        options={},
        unique_id=DOMAIN,
        entry_id="device-routines-test-entry",
        minor_version=DeviceRoutinesConfigFlow.MINOR_VERSION,
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set the integration up and return its loaded entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
