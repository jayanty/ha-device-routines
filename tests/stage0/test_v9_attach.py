"""Stage 0 V9, A10: entities of this integration on another integration's device.

The approach of ha-device-links: look the device up in the registry and copy its
identifiers and name verbatim into the entity's `DeviceInfo`. Recorded results on core
2026.10.2, which made identifiers unique per config entry and gives each device a single
config entry: `DeviceInfo` creates this integration's own device record carrying the same
identifiers, which the core reports as a linked device of the user's device; setting the
entity's `device_id` to the user's device directly is undone the next time the platform
adds the entity. Identifiers alone name the entity after the config entry, so the name is
copied too. Whether the device page shows a linked record's entities in its cards is a
frontend question checked live (cleanup item C4).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, MockEntityPlatform

from custom_components.device_routines.const import DOMAIN


class RoutineSwitch(SwitchEntity):
    """The shape of a routine's config entity."""

    _attr_has_entity_name = True
    _attr_name = "Routine"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_is_on = False

    def __init__(self, device: dr.DeviceEntry, copy_name: bool = True) -> None:
        self._attr_unique_id = f"{device.id}_routine"
        if copy_name:
            self._attr_device_info = DeviceInfo(
                identifiers=set(device.identifiers), name=device.name
            )
        else:
            self._attr_device_info = DeviceInfo(identifiers=set(device.identifiers))


async def add_routine_entity(
    hass: HomeAssistant, copy_name: bool
) -> tuple[dr.DeviceEntry, er.RegistryEntry, MockConfigEntry, MockConfigEntry, int]:
    other = MockConfigEntry(domain="matter", title="Matter")
    other.add_to_hass(hass)
    ours = MockConfigEntry(domain=DOMAIN, title="Device Routines")
    ours.add_to_hass(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("matter", "deviceid_0123456789ABCDEF-0000000000000042-MatterNodeDevice")},
        name="Living room fan",
    )
    before = len(devices.devices)
    platform = MockEntityPlatform(hass, domain="switch", platform_name=DOMAIN)
    platform.config_entry = ours

    await platform.async_add_entities([RoutineSwitch(device, copy_name)])
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{device.id}_routine")
    assert entity_id is not None
    entry = registry.async_get(entity_id)
    assert entry is not None
    return device, entry, other, ours, before


async def test_device_info_makes_our_own_record_sharing_the_identifiers(
    hass: HomeAssistant,
) -> None:
    """Core 2026.10: identifiers are unique per config entry, a device has one entry."""
    device, entry, other, ours, before = await add_routine_entity(hass, copy_name=True)
    devices = dr.async_get(hass)

    assert entry.device_id != device.id
    ours_record = devices.async_get(entry.device_id)  # type: ignore[arg-type]
    assert ours_record is not None
    assert ours_record.identifiers == device.identifiers
    assert ours_record.config_entry_id == ours.entry_id
    assert devices.async_get(device.id).config_entry_id == other.entry_id  # type: ignore[union-attr]
    assert len(devices.devices) == before + 1
    assert entry.entity_id == "switch.living_room_fan_routine"


async def test_the_registry_path_does_not_survive_a_load(hass: HomeAssistant) -> None:
    """Setting the entity's device_id to the user's device directly."""
    other = MockConfigEntry(domain="matter", title="Matter")
    other.add_to_hass(hass)
    ours = MockConfigEntry(domain=DOMAIN, title="Device Routines")
    ours.add_to_hass(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={("matter", "deviceid_0123456789ABCDEF-0000000000000042-MatterNodeDevice")},
        name="Living room fan",
    )
    registry = er.async_get(hass)
    created = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{device.id}_routine",
        config_entry=ours,
        device_id=device.id,
        entity_category=EntityCategory.CONFIG,
        has_entity_name=True,
        original_name="Routine",
        suggested_object_id="living_room_fan_routine",
    )
    assert created.device_id == device.id
    assert created.entity_id == "switch.living_room_fan_routine"

    # The other integration updates its device: the entity stays attached.
    devices.async_update_device(device.id, sw_version="2.0")
    await hass.async_block_till_done()
    assert registry.async_get(created.entity_id).device_id == device.id  # type: ignore[union-attr]

    # But the entity is added by its platform on every load, and without device_info the
    # core clears the device again: this path does not survive a restart.
    platform = MockEntityPlatform(hass, domain="switch", platform_name=DOMAIN)
    platform.config_entry = ours
    entity = RoutineSwitch(device)
    entity._attr_device_info = None
    await platform.async_add_entities([entity])
    await hass.async_block_till_done()
    assert registry.async_get(created.entity_id).device_id is None  # type: ignore[union-attr]


async def test_removing_the_device_leaves_our_entity_detached(hass: HomeAssistant) -> None:
    """The registry keeps another entry's entity and clears its device; the manager's
    device removal handling (PRD 3.1) removes it."""
    other = MockConfigEntry(domain="matter", title="Matter")
    other.add_to_hass(hass)
    ours = MockConfigEntry(domain=DOMAIN, title="Device Routines")
    ours.add_to_hass(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("matter", "node_42")}, name="Fan"
    )
    registry = er.async_get(hass)
    created = registry.async_get_or_create(
        "switch", DOMAIN, "fan_routine", config_entry=ours, device_id=device.id
    )

    devices.async_remove_device(device.id)
    await hass.async_block_till_done()

    left = registry.async_get(created.entity_id)
    assert left is not None
    assert left.device_id is None


async def test_our_record_is_a_linked_device_of_the_users_device(
    hass: HomeAssistant, hass_ws_client: Any
) -> None:
    """What the frontend asks to show related records on a device page."""
    assert await async_setup_component(hass, "config", {})
    device, entry, _, _, _ = await add_routine_entity(hass, copy_name=True)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "config/device_registry/list_linked_devices", "device_id": device.id}
    )
    response = await client.receive_json()

    assert response["success"], response
    linked = response["result"]["linked_devices"]
    assert [item["id"] if isinstance(item, dict) else item for item in linked] == [entry.device_id]


async def test_identifiers_alone_name_the_record_and_entity_after_the_config_entry(
    hass: HomeAssistant,
) -> None:
    """Why the name is copied too."""
    _, entry, _, _, _ = await add_routine_entity(hass, copy_name=False)

    record = dr.async_get(hass).async_get(entry.device_id)  # type: ignore[arg-type]
    assert record is not None
    assert record.name == "Device Routines"
    assert entry.entity_id == "switch.device_routines_routine"
