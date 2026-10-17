"""Stage 0 V13, A14: purpose specific triggers and conditions from a custom integration.

A throwaway custom integration (`tests/fixtures/stage0/custom_components/stage0_probe`)
ships `trigger.py` and `condition.py` with `async_get_triggers` and `async_get_conditions`
plus their `triggers.yaml` and `conditions.yaml`, the shape core integrations use. The
probes check that the core registers them, that their descriptions (what the editor's
pickers read) carry the target selector, and that device, area and label targets work.
The pickers themselves are frontend, checked live once Device Routines ships its own
(cleanup item C5).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant import loader
from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    condition,
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
    trigger,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "stage0"
SWITCH = "switch.living_room_fan"


@pytest.fixture
def probe_integration(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the probe on the custom_components namespace path, as a HACS install would."""
    monkeypatch.syspath_prepend(str(FIXTURES))
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)


@pytest.fixture
def targets(hass: HomeAssistant) -> dict[str, str]:
    """A fan switch on a device in an area with a label."""
    area = ar.async_get(hass).async_create("Living room")
    label = lr.async_get(hass).async_create("Evening")
    entry = MockConfigEntry(domain="matter")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("matter", "fan")}, name="Living room fan"
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    er.async_get(hass).async_get_or_create(
        "switch",
        "matter",
        "fan",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="living_room_fan",
    )
    er.async_get(hass).async_update_entity(SWITCH, labels={label.label_id})
    hass.states.async_set(SWITCH, "off")
    return {"device_id": device.id, "area_id": area.id, "label_id": label.label_id}


async def test_the_core_registers_and_describes_them(
    hass: HomeAssistant, probe_integration: None
) -> None:
    assert await async_setup_component(hass, "automation", {})
    assert await async_setup_component(hass, "stage0_probe", {})
    await hass.async_block_till_done()

    triggers = await trigger.async_get_all_descriptions(hass)
    conditions = await condition.async_get_all_descriptions(hass)
    started = triggers["stage0_probe.routine_started"]
    active = conditions["stage0_probe.routine_active"]
    assert started is not None
    assert active is not None

    assert started["target"] == {"entity": [{"domain": ["switch"]}]}
    assert "behavior" in started["fields"]
    assert active["target"] == {"entity": [{"domain": ["switch"]}]}


@pytest.mark.parametrize("kind", ["device_id", "area_id", "label_id"])
async def test_device_area_and_label_targets_fire_and_hold(
    hass: HomeAssistant, probe_integration: None, targets: dict[str, str], kind: str
) -> None:
    calls = async_mock_service(hass, "test", "record")
    target: dict[str, Any] = {kind: targets[kind]}
    config: dict[str, Any] = {
        "id": f"stage0_v13_{kind}",
        "triggers": [{"trigger": "stage0_probe.routine_started", "target": target}],
        "conditions": [{"condition": "stage0_probe.routine_active", "target": target}],
        "actions": [{"action": "test.record"}],
    }
    validated = await async_validate_config_item(hass, config["id"], config)
    assert validated is not None
    assert validated.validation_status == "ok", validated.validation_error
    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()

    hass.states.async_set(SWITCH, "on")
    await hass.async_block_till_done()

    assert len(calls) == 1
