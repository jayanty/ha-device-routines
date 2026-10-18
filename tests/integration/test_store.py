"""Build A lane 6: the persistent Store, schema 1.2, and its migration (TECH_SPEC 6, 4.11).

Minor version 2 (plan A4.0 items 2 and 15) adds why the manager turned an automation off
(`suspended`, L44) and the helpers it created for each routine (`own_helpers`, L53).

Every id and name is synthetic. `hass_storage` stands in for `.storage`: a save lands in it
at once, a load reads from it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.device_routines import compiler, markers, store
from custom_components.device_routines.store import (
    AiCacheEntry,
    OwnedRecord,
    RoutineStore,
    StoreData,
    StoreVersionError,
    migrate_store,
)

FAN_DEVICE = "synthetic-living-room-fan"
VACUUM_DEVICE = "synthetic-robot-vacuum"
GONE_DEVICE = "synthetic-garden-pump"
FAN_ID = markers.automation_id(FAN_DEVICE)
VACUUM_ID = markers.automation_id(VACUUM_DEVICE)

OPTED_OUT = datetime(2026, 10, 1, 8, 30, tzinfo=UTC)
REMOVED = datetime(2026, 10, 2, 21, 0, 15, tzinfo=UTC)
CACHED = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

FAN_INPUTS: dict[str, Any] = {
    "target_entity": "fan.living_room",
    "on_action": "fan.turn_on",
    "off_action": "fan.turn_off",
    "inactive_state": "off",
    "device_id": FAN_DEVICE,
    "on_time_enabled": True,
    "on_time": "17:00:00",
    "days_start": ["mon", "tue", "wed", "thu", "fri"],
    "extra_conditions": [{"condition": "state", "entity_id": "input_boolean.guest_mode"}],
}


def every_key() -> StoreData:
    """Store data with every key and every record field holding a non default value."""
    return StoreData(
        owned={
            FAN_ID: OwnedRecord(
                device_id=FAN_DEVICE,
                target_entity="fan.living_room",
                last_hash="a" * 64,
                last_valid_inputs=FAN_INPUTS,
                previous_inputs={**FAN_INPUTS, "on_time": "16:00:00"},
                schema=1,
                alias_history=("Routine: Fan", "Routine: Living room fan"),
            ),
            VACUUM_ID: OwnedRecord(device_id=VACUUM_DEVICE, target_entity="vacuum.robot"),
        },
        opted_in={FAN_DEVICE, VACUUM_DEVICE},
        opted_out_at={GONE_DEVICE: OPTED_OUT},
        removed_devices_at={GONE_DEVICE: REMOVED},
        blueprint_hash="b" * 64,
        blueprint_schema=1,
        ai_cache={"c" * 64: AiCacheEntry(text="Turns the fan on at dusk", created=CACHED)},
        suspended={VACUUM_ID: "missing_target"},
        own_helpers={FAN_DEVICE: ["schedule.routine_living_room_fan", "timer.routine_fan"]},
    )


SERIALIZED: dict[str, Any] = {
    "owned": {
        FAN_ID: {
            "device_id": FAN_DEVICE,
            "target_entity": "fan.living_room",
            "last_hash": "a" * 64,
            "last_valid_inputs": FAN_INPUTS,
            "previous_inputs": {**FAN_INPUTS, "on_time": "16:00:00"},
            "schema": 1,
            "alias_history": ["Routine: Fan", "Routine: Living room fan"],
        },
        VACUUM_ID: {
            "device_id": VACUUM_DEVICE,
            "target_entity": "vacuum.robot",
            "last_hash": None,
            "last_valid_inputs": None,
            "previous_inputs": None,
            "schema": compiler.BLUEPRINT_SCHEMA_VERSION,
            "alias_history": [],
        },
    },
    "opted_in": sorted([FAN_DEVICE, VACUUM_DEVICE]),
    "opted_out_at": {GONE_DEVICE: "2026-10-01T08:30:00+00:00"},
    "removed_devices_at": {GONE_DEVICE: "2026-10-02T21:00:15+00:00"},
    "blueprint_hash": "b" * 64,
    "blueprint_schema": 1,
    "ai_cache": {
        "c" * 64: {"text": "Turns the fan on at dusk", "created": "2026-10-03T12:00:00+00:00"}
    },
    "suspended": {VACUUM_ID: "missing_target"},
    "own_helpers": {FAN_DEVICE: ["schedule.routine_living_room_fan", "timer.routine_fan"]},
}

# What a version 0 Store held: the PRD 10.2 layout, before TECH_SPEC 6 added the per
# record schema, previous inputs and alias history, the removal timestamps and the
# blueprint schema.
VERSION_0: dict[str, Any] = {
    "owned": {
        FAN_ID: {
            "device_id": FAN_DEVICE,
            "target_entity": "fan.living_room",
            "last_hash": "a" * 64,
            "last_valid_inputs": FAN_INPUTS,
        }
    },
    "opted_in": [FAN_DEVICE],
    "opted_out_at": {GONE_DEVICE: "2026-10-01T08:30:00+00:00"},
    "blueprint_hash": "b" * 64,
    "ai_cache": {},
}


def stored(
    hass_storage: dict[str, Any], data: dict[str, Any], version: int, minor: int = 1
) -> None:
    hass_storage[store.STORAGE_KEY] = {
        "version": version,
        "minor_version": minor,
        "key": store.STORAGE_KEY,
        "data": data,
    }


def test_the_contract_names() -> None:
    assert store.STORAGE_KEY == "device_routines"
    assert store.STORAGE_VERSION == 1
    assert store.STORAGE_MINOR_VERSION == 2


async def test_the_store_round_trips_every_key(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    routines = RoutineStore(hass)
    routines.data = every_key()

    await routines.async_save()

    saved = hass_storage[store.STORAGE_KEY]
    assert saved["version"] == 1
    assert saved["minor_version"] == 2
    assert saved["data"] == SERIALIZED

    reloaded = RoutineStore(hass)
    loaded = await reloaded.async_load()

    assert loaded == every_key()
    assert reloaded.data is loaded
    assert loaded.opted_out_at[GONE_DEVICE].tzinfo is not None
    assert loaded.owned[FAN_ID].alias_history == ("Routine: Fan", "Routine: Living room fan")


async def test_a_missing_store_loads_empty(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    routines = RoutineStore(hass)

    loaded = await routines.async_load()

    assert loaded == StoreData()
    assert loaded.owned == {}
    assert loaded.opted_in == set()
    assert loaded.blueprint_hash is None
    assert loaded.blueprint_schema is None
    assert store.STORAGE_KEY not in hass_storage


async def test_missing_keys_load_at_their_defaults(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A hand trimmed file still loads: everything but two keys can be rebuilt anyway."""
    stored(
        hass_storage,
        {"owned": {VACUUM_ID: {"device_id": VACUUM_DEVICE, "target_entity": "vacuum.robot"}}},
        1,
    )

    loaded = await RoutineStore(hass).async_load()

    assert loaded == StoreData(
        owned={VACUUM_ID: OwnedRecord(device_id=VACUUM_DEVICE, target_entity="vacuum.robot")}
    )


async def test_inputs_are_saved_as_plain_json(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Inputs read from YAML may hold tuples and mapping subclasses; JSON gets plain types."""

    class Node(dict[str, Any]):
        """A stand in for the YAML loader's mapping subclass."""

    routines = RoutineStore(hass)
    routines.data.owned[FAN_ID] = OwnedRecord(
        device_id=FAN_DEVICE,
        target_entity="fan.living_room",
        last_valid_inputs=Node(days_start=("mon", "tue"), extra_conditions=(Node(a=1),)),
    )

    await routines.async_save()

    inputs = hass_storage[store.STORAGE_KEY]["data"]["owned"][FAN_ID]["last_valid_inputs"]
    assert inputs == {"days_start": ["mon", "tue"], "extra_conditions": [{"a": 1}]}
    assert type(inputs) is dict
    assert type(inputs["extra_conditions"][0]) is dict


def test_migrate_store_from_a_hand_written_version_0_payload() -> None:
    migrated = migrate_store(0, 1, VERSION_0)

    assert migrated["owned"][FAN_ID] == {
        "device_id": FAN_DEVICE,
        "target_entity": "fan.living_room",
        "last_hash": "a" * 64,
        "last_valid_inputs": FAN_INPUTS,
        "previous_inputs": None,
        "schema": 1,
        "alias_history": [],
    }
    assert migrated["opted_in"] == [FAN_DEVICE]
    assert migrated["opted_out_at"] == {GONE_DEVICE: "2026-10-01T08:30:00+00:00"}
    assert migrated["removed_devices_at"] == {}
    assert migrated["blueprint_hash"] == "b" * 64
    assert migrated["blueprint_schema"] == 1
    assert migrated["ai_cache"] == {}
    assert migrated["suspended"] == {}
    assert migrated["own_helpers"] == {}
    assert "previous_inputs" not in VERSION_0["owned"][FAN_ID], "the payload is not mutated"


async def test_a_version_0_store_migrates_on_load_and_is_saved_as_version_1(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    stored(hass_storage, VERSION_0, 0)

    loaded = await RoutineStore(hass).async_load()

    assert loaded.owned[FAN_ID] == OwnedRecord(
        device_id=FAN_DEVICE,
        target_entity="fan.living_room",
        last_hash="a" * 64,
        last_valid_inputs=FAN_INPUTS,
        previous_inputs=None,
        schema=1,
        alias_history=(),
    )
    assert loaded.opted_in == {FAN_DEVICE}
    assert loaded.opted_out_at == {GONE_DEVICE: OPTED_OUT}
    assert loaded.blueprint_schema == 1
    assert hass_storage[store.STORAGE_KEY]["version"] == 1
    assert hass_storage[store.STORAGE_KEY]["minor_version"] == 2
    assert hass_storage[store.STORAGE_KEY]["data"]["removed_devices_at"] == {}


def test_migrate_store_leaves_the_current_version_alone() -> None:
    assert migrate_store(1, 2, SERIALIZED) == SERIALIZED


# What a version 1.1 Store held: the TECH_SPEC 6 layout before minor version 2. The fan's
# routine names its own timer and schedule; the lamp's names a schedule a person made.
VERSION_1_1: dict[str, Any] = {
    "owned": {
        FAN_ID: {
            "device_id": FAN_DEVICE,
            "target_entity": "fan.living_room",
            "last_valid_inputs": {
                **FAN_INPUTS,
                "timer_entity": "timer.routine_living_room_fan",
                "schedule_entity": "schedule.routine_living_room_fan",
            },
        },
        VACUUM_ID: {
            "device_id": VACUUM_DEVICE,
            "target_entity": "vacuum.robot",
            "last_valid_inputs": {
                "timer_entity": compiler.UNUSED_TIMER,
                "schedule_entity": "schedule.cleaning_hours",
            },
        },
        markers.automation_id(GONE_DEVICE): {
            "device_id": GONE_DEVICE,
            "target_entity": "switch.garden_pump",
            "last_valid_inputs": None,
        },
    },
    "opted_in": [FAN_DEVICE, VACUUM_DEVICE],
}


def test_migrate_store_from_1_1_adds_suspended_and_reads_the_own_helpers() -> None:
    """Plan A4.0 items 2 and 15: minor version 2 and its migration."""
    migrated = migrate_store(1, 1, VERSION_1_1)

    assert migrated["suspended"] == {}
    assert migrated["own_helpers"] == {
        FAN_DEVICE: ["schedule.routine_living_room_fan", "timer.routine_living_room_fan"]
    }
    assert migrated["owned"] == VERSION_1_1["owned"]
    assert "suspended" not in VERSION_1_1, "the payload is not mutated"


async def test_a_1_1_store_migrates_on_load_and_is_saved_as_1_2(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    stored(hass_storage, VERSION_1_1, 1, minor=1)

    loaded = await RoutineStore(hass).async_load()

    assert loaded.suspended == {}
    assert loaded.own_helpers == {
        FAN_DEVICE: ["schedule.routine_living_room_fan", "timer.routine_living_room_fan"]
    }
    assert hass_storage[store.STORAGE_KEY]["minor_version"] == 2
    assert hass_storage[store.STORAGE_KEY]["data"]["suspended"] == {}


def test_a_minor_version_without_a_migration_path_is_refused() -> None:
    with pytest.raises(StoreVersionError):
        migrate_store(1, 0, {})


@pytest.mark.parametrize(("version", "minor"), [(2, 1), (1, 3), (7, 0)])
def test_an_unknown_future_version_is_refused(version: int, minor: int) -> None:
    with pytest.raises(StoreVersionError) as raised:
        migrate_store(version, minor, SERIALIZED)

    assert raised.value.translation_key == "store_version_unsupported"
    assert raised.value.translation_placeholders == {
        "version": f"{version}.{minor}",
        "supported": "1.2",
    }


def test_a_version_without_a_migration_path_is_refused() -> None:
    with pytest.raises(StoreVersionError):
        migrate_store(-1, 1, {})


async def test_a_future_store_is_refused_on_load_and_left_on_disk(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    stored(hass_storage, {"owned": {}, "future_key": True}, 1, minor=3)

    with pytest.raises(StoreVersionError):
        await RoutineStore(hass).async_load()

    assert hass_storage[store.STORAGE_KEY]["minor_version"] == 3
    assert hass_storage[store.STORAGE_KEY]["data"]["future_key"] is True


async def test_a_future_major_version_is_refused_on_load(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    stored(hass_storage, {"owned": {}}, 2)

    with pytest.raises(HomeAssistantError):
        await RoutineStore(hass).async_load()

    assert hass_storage[store.STORAGE_KEY]["version"] == 2


async def test_a_delayed_save_lands_after_the_delay(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    routines = RoutineStore(hass)
    routines.data.opted_in.add(FAN_DEVICE)

    routines.async_delay_save()
    routines.data.opted_in.add(VACUUM_DEVICE)
    assert store.STORAGE_KEY not in hass_storage

    freezer.tick(timedelta(seconds=store.SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass_storage[store.STORAGE_KEY]["data"]["opted_in"] == sorted(
        [FAN_DEVICE, VACUUM_DEVICE]
    )


async def test_a_flush_writes_a_pending_delayed_save_at_once(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    """Plan A4.0 item 14: the manager flushes on unload, so a pending save is not lost."""
    routines = RoutineStore(hass)
    routines.data.opted_in.add(FAN_DEVICE)

    await routines.async_flush()
    assert store.STORAGE_KEY not in hass_storage  # nothing pending, nothing written

    routines.async_delay_save()
    await routines.async_flush()

    assert hass_storage[store.STORAGE_KEY]["data"]["opted_in"] == [FAN_DEVICE]
    del hass_storage[store.STORAGE_KEY]
    freezer.tick(timedelta(seconds=store.SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert store.STORAGE_KEY not in hass_storage  # the delayed save was the flushed one
    await routines.async_flush()
    assert store.STORAGE_KEY not in hass_storage


async def test_a_delayed_save_that_ran_leaves_nothing_to_flush(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer: FrozenDateTimeFactory
) -> None:
    routines = RoutineStore(hass)
    routines.async_delay_save()
    freezer.tick(timedelta(seconds=store.SAVE_DELAY + 1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    del hass_storage[store.STORAGE_KEY]

    await routines.async_flush()

    assert store.STORAGE_KEY not in hass_storage
