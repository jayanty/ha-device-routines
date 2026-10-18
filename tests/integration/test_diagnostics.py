"""Diagnostics: what a bug report needs, with nothing that names a home (TECH_SPEC 4.9).

The Store is reported as counts, owned automations as shapes with every id, name, alias
and entity redacted, and any value that looks like a token, an address or a 32 character
id is redacted wherever it appears. Each routine test serializes the whole report and
looks for every id and name of the synthetic home in it. Values that would trip the
repository's own privacy check (an email address, a private address) are built at run
time, never written out.
"""

from __future__ import annotations

from datetime import time
import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.loader import async_get_integration
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
    get_diagnostics_for_device,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.device_routines import compiler, repairs
from custom_components.device_routines.const import DOMAIN, HUB_IDENTIFIER
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.store import OwnedRecord
from tests.integration.conftest import (
    ALIAS,
    AUTOMATION,
    FAN,
    LAMP,
    OVERRIDE,
    PAUSED,
    TIMER,
    Home,
    give_routine,
)

REDACTED = "**REDACTED**"

# The manager's routines leave their own timers behind (pause ends, cleanup).
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


def secrets_of(home: Home, manager: RoutineManager) -> list[str]:
    """Every id and name of the synthetic home a report must never carry."""
    names = ["Living room fan", "Desk lamp", "Living room", "Ground floor", ALIAS]
    entities = [FAN, LAMP, TIMER, OVERRIDE, PAUSED, AUTOMATION]
    ids = [home.fan, home.lamp, home.area, home.floor, *manager.store.data.owned]
    return [*names, *entities, *ids]


def assert_names_nothing(report: Any, secrets: list[str]) -> None:
    text = json.dumps(report)
    assert [secret for secret in secrets if secret in text] == []


# --------------------------------------------------------------------------------------
# Config entry diagnostics
# --------------------------------------------------------------------------------------


async def test_diagnostics_report_the_integration_and_its_health(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, init_integration: MockConfigEntry
) -> None:
    integration = await async_get_integration(hass, DOMAIN)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert set(diagnostics) == {"integration", "store", "routines", "summary"}
    assert diagnostics["summary"]["devices"] == 0
    assert diagnostics["routines"] == []
    section = diagnostics["integration"]
    assert section["settings"]["schedule_scope"] == "all"
    assert section["adapter"] == {"failed": []}
    assert section["version"] == integration.version
    assert section["entry_id"] == init_integration.entry_id
    assert section["options"] == {}
    assert section["health"]["state"] == "ok"
    assert section["health"]["channel"] == "unknown"
    assert section["health"]["blueprint_status"] == "ok"
    assert section["health"]["issues"] == []


async def test_diagnostics_redact_secret_shaped_options_and_the_ai_task_entity(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={"token": "secret", "schedule_scope": "all", "ai_task_entity": "ai_task.local"},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, mock_config_entry)

    assert diagnostics["integration"]["options"] == {
        "token": REDACTED,
        "schedule_scope": "all",
        "ai_task_entity": REDACTED,
    }
    assert diagnostics["integration"]["settings"]["ai_task_entity"] == REDACTED


async def test_anything_matching_the_privacy_patterns_is_redacted(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, init_integration: MockConfigEntry
) -> None:
    email = "someone" + "@" + "example.com"
    octets = (192, 168, 1, 20)
    address = ".".join(str(octet) for octet in octets)
    mac = ":".join(["a4"] * 6)
    hex_id = "ab" * 16
    token = "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12
    host = "homebox" + ".local"
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            "schedule_scope": "all",
            "note": f"mail {email}",
            "list": [address, mac, {"inner": hex_id}],
            "nested": {"token_like": token, "host": host, "plain": "kept"},
        },
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert diagnostics["integration"]["options"] == {
        "schedule_scope": "all",
        "note": REDACTED,
        "list": [REDACTED, REDACTED, {"inner": REDACTED}],
        "nested": {"token_like": REDACTED, "host": REDACTED, "plain": "kept"},
    }


async def test_the_store_is_reported_as_counts(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    freezer: Any,
) -> None:
    fan = await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))
    await give_routine(hass, manager, home.lamp, freezer, turn_off_after_min=30)
    await manager.async_opt_out(home.lamp)
    # A per routine issue names its automation; the report keeps the catalog id only.
    repairs.async_sync_issue(hass, repairs.CONFLICT, present=True, subject=fan)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, routines)

    assert diagnostics["integration"]["health"]["issues"] == [repairs.CONFLICT]

    assert diagnostics["store"] == {
        "owned": 2,
        "opted_in": 1,
        "opted_out": 1,
        "removed_devices": 0,
        "ai_cache": 0,
        "blueprint_hash": manager.store.data.blueprint_hash,
        "blueprint_schema": compiler.BLUEPRINT_SCHEMA_VERSION,
    }
    assert_names_nothing(diagnostics, secrets_of(home, manager))


async def test_owned_records_are_shapes_with_ids_names_and_aliases_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    freezer: Any,
) -> None:
    automation_id = await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_time=time(17),
        off_time=time(9),
        turn_off_after_min=30,
        extra_conditions=[{"condition": "state", "entity_id": LAMP, "state": "off"}],
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, routines)

    record = manager.store.data.owned[automation_id]
    view = manager.get(home.fan)
    assert view is not None
    (routine,) = diagnostics["routines"]
    assert routine["routine"] == 0
    assert routine["automation_id"] == REDACTED
    assert routine["device_id"] == REDACTED
    assert routine["target_domain"] == "switch"
    assert routine["schema"] == compiler.BLUEPRINT_SCHEMA_VERSION
    assert routine["last_hash"] == record.last_hash
    assert routine["aliases"] == 1
    assert routine["has_previous_inputs"] is False
    shape = routine["inputs"]
    assert list(shape) == list(compiler.INPUT_KEYS)
    for key in (
        "target_entity",
        "device_id",
        "timer_entity",
        "override_entity",
        "paused_until_entity",
    ):
        assert shape[key] == REDACTED, key
    assert shape["schedule_entity"] == "unused"
    assert shape["extra_conditions"] == 1
    assert shape["on_action"] == "switch.turn_on"
    assert shape["on_time"] == "17:00:00"
    assert shape["off_time"] == "09:00:00"
    assert shape["crosses_midnight"] is True
    assert shape["turn_off_after_min"] == 30
    assert routine["runtime"] == {
        "status": "active",
        "enabled": True,
        "paused": False,
        "skipping": False,
        "has_next_action": True,
        "override": False,
        "last_change_source": None,
        "has_sentence": True,
        "items": len(view.items),
        "conflicts": 0,
    }
    assert_names_nothing(diagnostics, secrets_of(home, manager))


async def test_a_record_without_valid_inputs_or_a_device_still_reads(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    freezer: Any,
) -> None:
    """Index entries whose inputs a rebuild could not read, or whose device is gone."""
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    owned = manager.store.data.owned
    owned[automation_id] = OwnedRecord(
        device_id="no-such-device",
        target_entity=FAN,
        last_valid_inputs={
            "target_entity": FAN,
            "on_action": "script.call_someone",
            "extra_conditions": "not a list",
            "surprise": "value",
        },
        previous_inputs={"anything": 1},
    )
    owned["device_routines_000000000001"] = OwnedRecord(
        device_id="another-missing-device", target_entity=LAMP
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, routines)

    first, second = diagnostics["routines"]
    assert first["inputs"] == {
        "target_entity": REDACTED,
        "on_action": REDACTED,
        "extra_conditions": REDACTED,
        "surprise": REDACTED,
    }
    assert first["has_previous_inputs"] is True
    assert first["runtime"] is None
    assert second["inputs"] is None
    assert second["target_domain"] == "light"


# --------------------------------------------------------------------------------------
# Device diagnostics
# --------------------------------------------------------------------------------------


def linked_record(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> dr.DeviceEntry:
    """This integration's linked record of a sandbox device (decision L25)."""
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("sandbox", key)}
    )


async def test_device_diagnostics_report_that_devices_routine_and_schedule(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    freezer: Any,
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))

    diagnostics = await get_diagnostics_for_device(
        hass, hass_client, routines, linked_record(hass, routines, "fan")
    )

    assert diagnostics["opted_in"] is True
    assert diagnostics["routine"]["target_domain"] == "switch"
    assert diagnostics["routine"]["runtime"]["status"] == "active"
    assert diagnostics["schedule"]["has_state"] is True
    timed_routine_line = {
        "kind": "routine",
        "source": "parser",
        "enabled": True,
        "custom_logic": False,
        "timed": True,
    }
    summary = routines.runtime_data.summary.summaries[home.fan]
    assert diagnostics["schedule"]["items"] == [timed_routine_line] * len(summary.items)
    assert_names_nothing(diagnostics, secrets_of(home, manager))


async def test_device_diagnostics_of_a_device_without_a_routine(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
) -> None:
    await manager.async_opt_in(home.lamp)

    opted_in = await get_diagnostics_for_device(
        hass, hass_client, routines, linked_record(hass, routines, "lamp")
    )
    unknown = await get_diagnostics_for_device(
        hass, hass_client, routines, linked_record(hass, routines, "nothing_like_it")
    )

    assert opted_in == {"opted_in": True, "routine": None, "schedule": None}
    assert unknown == {"opted_in": False, "routine": None, "schedule": None}


async def test_device_diagnostics_find_a_device_known_by_its_connections(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
) -> None:
    connection = (dr.CONNECTION_NETWORK_MAC, "02:00:00:00:00:01")
    registry = dr.async_get(hass)
    plug = registry.async_get_or_create(
        config_entry_id=home.source.entry_id, connections={connection}, name="Wall plug"
    )
    er.async_get(hass).async_get_or_create(
        "switch",
        "sandbox",
        "wall_plug",
        device_id=plug.id,
        suggested_object_id="wall_plug",
        config_entry=home.source,
    )
    hass.states.async_set("switch.wall_plug", "off")
    await manager.async_opt_in(plug.id)
    linked = registry.async_get_or_create(
        config_entry_id=routines.entry_id, connections={connection}
    )

    diagnostics = await get_diagnostics_for_device(hass, hass_client, routines, linked)

    assert plug.id not in json.dumps(diagnostics)
    assert diagnostics == {"opted_in": True, "routine": None, "schedule": None}


async def test_device_diagnostics_of_the_hub_report_the_integration(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, init_integration: MockConfigEntry
) -> None:
    hub = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, HUB_IDENTIFIER), init_integration.entry_id
    )
    assert hub is not None

    diagnostics = await get_diagnostics_for_device(hass, hass_client, init_integration, hub)

    assert set(diagnostics) == {"integration", "store"}
    assert diagnostics["integration"]["health"]["state"] == "ok"
    assert diagnostics["store"]["owned"] == 0
