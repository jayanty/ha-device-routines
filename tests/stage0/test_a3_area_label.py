"""Stage 0, A3 paths deferred from V2: automations that target a device through its area,
its floor or a label.

V2 closed the entity and device paths live; the instance has no automation targeting an
area or a label. These probes run the automation component's reference helpers against
the pinned core with synthetic registries: a living room fan whose device sits in the
living room on the ground floor and carries a label.

Recorded results (core 2026.10.1): each helper finds the automation by the id it names,
in actions and in triggers alike, and never expands it. An area, floor or label target
is invisible to `automations_with_entity` and `automations_with_device`, so discovery has
to ask each helper with the ids the device resolves to.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.automation import (
    areas_in_automation,
    automations_with_area,
    automations_with_device,
    automations_with_entity,
    automations_with_floor,
    automations_with_label,
    floors_in_automation,
    labels_in_automation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

FAN = "fan.living_room_fan"


def turn_on(target: dict[str, Any], marker: str) -> dict[str, Any]:
    return {
        "id": f"stage0_{marker}",
        "alias": f"stage0 {marker}",
        "triggers": [{"trigger": "event", "event_type": "stage0_probe"}],
        "actions": [{"action": "fan.turn_on", "target": target}],
    }


async def test_area_floor_and_label_targets(hass: HomeAssistant) -> None:
    floor = fr.async_get(hass).async_create("Ground floor")
    area = ar.async_get(hass).async_create("Living room", floor_id=floor.floor_id)
    label = lr.async_get(hass).async_create("Evening")
    entry = MockConfigEntry(domain="stage0")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("stage0", "fan")}, name="Living room fan"
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id, labels={label.label_id})
    er.async_get(hass).async_get_or_create(
        "fan", "stage0", "fan", device_id=device.id, suggested_object_id="living_room_fan"
    )

    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                turn_on({"area_id": area.id}, "area"),
                turn_on({"floor_id": floor.floor_id}, "floor"),
                turn_on({"label_id": label.label_id}, "label"),
                turn_on({"device_id": device.id}, "device"),
                turn_on({"entity_id": FAN}, "entity"),
                {
                    "id": "stage0_reads_area",
                    "alias": "stage0 reads area",
                    "triggers": [{"trigger": "state", "entity_id": FAN}],
                    "conditions": [],
                    "actions": [{"action": "light.turn_on", "target": {"area_id": area.id}}],
                },
            ]
        },
    )
    await hass.async_block_till_done()

    assert automations_with_area(hass, area.id) == [
        "automation.stage0_area",
        "automation.stage0_reads_area",
    ]
    assert automations_with_floor(hass, floor.floor_id) == ["automation.stage0_floor"]
    assert automations_with_label(hass, label.label_id) == ["automation.stage0_label"]
    assert automations_with_device(hass, device.id) == ["automation.stage0_device"]
    # The entity helper sees only literal entity references, not area, floor or label.
    assert automations_with_entity(hass, FAN) == [
        "automation.stage0_entity",
        "automation.stage0_reads_area",
    ]

    # The reverse helpers name the ids as written.
    assert areas_in_automation(hass, "automation.stage0_area") == [area.id]
    assert floors_in_automation(hass, "automation.stage0_floor") == [floor.floor_id]
    assert labels_in_automation(hass, "automation.stage0_label") == [label.label_id]
    # An area target on another domain's action still lists the area: the summary has to
    # check the action's domain against the device's entities.
    assert areas_in_automation(hass, "automation.stage0_reads_area") == [area.id]
