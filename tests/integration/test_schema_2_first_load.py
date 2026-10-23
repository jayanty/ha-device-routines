"""Build B lane 19: the first start on a newer blueprint input schema (TECH_SPEC 4.11, PRD 3.1).

An instance updated from v0.3.0 has the schema 1 blueprint installed (the file as
v0.3.0-beta.1 ships it, `tests/fixtures/blueprint/device_routine_schema_1.yaml`), owned
automations whose inputs a schema 1 compiler wrote (`tests/fixtures/schema1/inputs.json`,
the identity inputs set to the synthetic home's devices) and a Store on schema 1. Setting
the entry up installs the shipped blueprint and migrates every routine through
`migration.async_migrate_blueprint_schema`, the machinery of Build A's task A2.2 used for
real here: the inputs move to the current schema with the previous ones kept, and no
device changes state on the way. A rewrite that fails is `automation_load_failed`, and
that issue's fix migrates the automation again (the L48 carry over). An instance updated
from v1.0.0 has the schema 2 file and routines instead, and moves to schema 3 the same way
(live finding F8, decision L83). Every id and name is synthetic.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, Final

from homeassistant.components.repairs import RepairsFlowManager, repairs_flow_manager
from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.core import Event, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import dump
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_routines import compiler, ha_adapter, maintenance, markers, migration
from custom_components.device_routines.config_flow import DeviceRoutinesConfigFlow
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import Status
from custom_components.device_routines.sentence import load_phrases
from custom_components.device_routines.store import STORAGE_KEY, OwnedRecord, StoreData
from tests.blueprint.conftest import SCHEMA_1_BLUEPRINT, SCHEMA_2_BLUEPRINT
from tests.integration.conftest import (
    FAN,
    GARAGE,
    LAMP,
    Clock,
    Home,
    file_entry,
    inputs_of,
    issue_of,
    state_of,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

FIXTURE: Final = Path(__file__).parents[1] / "fixtures" / "schema1" / "inputs.json"
CASES: Final[Mapping[str, Mapping[str, Any]]] = {
    case["name"]: case["inputs"]
    for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
}
HEALTH: Final = "sensor.device_routines_health"
PHRASES: Final = load_phrases("en")


def schema_1_entry(case: str, device_id: str, target: str, name: str) -> dict[str, Any]:
    """An owned automation as v0.3.0 wrote it: a recorded case, on one of the home's devices.

    The identity inputs (the target, the device, the Manual override and Paused until) are
    the home's, as the manager names them; every other input is the recorded one.
    """
    slug = markers.slugify(name)
    inputs = {
        **CASES[case],
        "target_entity": target,
        "device_id": device_id,
        "override_entity": f"switch.{slug}_manual_override",
        "paused_until_entity": f"datetime.{slug}_paused_until",
    }
    shown = markers.presentation(name, PHRASES)
    return {
        "id": markers.automation_id(device_id),
        "alias": shown.alias,
        "description": shown.description,
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": inputs},
    }


def schema_1_store(
    entries: list[dict[str, Any]], blueprint: str, schema: int = 1
) -> dict[str, Any]:
    """The Store v0.3.0 left: every record on schema 1, its blueprint and its schema.

    With `schema` 2, the Store v1.0.0 left.
    """
    data = StoreData(
        owned={
            entry["id"]: OwnedRecord(
                device_id=entry["use_blueprint"]["input"]["device_id"],
                target_entity=entry["use_blueprint"]["input"]["target_entity"],
                last_hash=markers.config_hash(entry),
                last_valid_inputs=entry["use_blueprint"]["input"],
                schema=schema,
                alias_history=(entry["alias"],),
            )
            for entry in entries
        },
        opted_in={entry["use_blueprint"]["input"]["device_id"] for entry in entries},
        blueprint_hash=maintenance.blueprint_hash(blueprint),
        blueprint_schema=schema,
    )
    return {"version": 1, "minor_version": 2, "key": STORAGE_KEY, "data": data.to_dict()}


def current_of(old: Mapping[str, Any]) -> dict[str, Any]:
    """The current inputs of the same settings: the old ones, plus the new at their defaults.

    The late sun offset is the on offset (0 for a time) plus the late start window, and
    `timer_enabled` is on exactly when the routine has a timer (decision L83).
    """
    window = old["late_start_window_min"]
    added = {key: compiler.INPUT_DEFAULTS[key] for key in compiler.INPUT_KEYS if key not in old}
    added["late_sun_offset"] = f"{window // 60:02d}:{window % 60:02d}:00"
    added["timer_enabled"] = old["timer_entity"] != compiler.UNUSED_TIMER
    return {**old, **added}


def schema_2_of(old: Mapping[str, Any]) -> dict[str, Any]:
    """The schema 2 inputs of the same settings, as the schema 1 to 2 migration wrote them."""
    return {key: value for key, value in current_of(old).items() if key in migration.SCHEMA_2_KEYS}


def watch(hass: HomeAssistant, entity_ids: tuple[str, ...]) -> list[tuple[str, str]]:
    """Record every state change of the routines' targets from now on."""
    changes: list[tuple[str, str]] = []

    def remember(event: Event) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if event.data["entity_id"] in entity_ids and (
            old is None or new is None or old.state != new.state
        ):
            changes.append((event.data["entity_id"], new.state if new else "removed"))

    hass.bus.async_listen("state_changed", remember)
    return changes


async def on_schema_1(
    hass: HomeAssistant, home: Home, hass_storage: dict[str, Any], schema: int = 1
) -> list[dict[str, Any]]:
    """Put the instance where v0.3.0 left it; return the owned entries.

    The fan's routine is a weekday window from 09:00 to 17:30, the desk lamp's a weekend
    night and the garage door's an off time every day. The automation component comes
    first, because installing a blueprint over an existing file reloads its automations
    through the core (L64); the schema 1 file goes in as the adapter installs a file,
    with its exact text, as v0.3.0 installed it. With `schema` 2, where v1.0.0 left it: the
    schema 2 file and the same routines with the inputs the schema 1 to 2 migration wrote.
    """
    assert await async_setup_component(hass, "automation", {})
    source = SCHEMA_1_BLUEPRINT if schema == 1 else SCHEMA_2_BLUEPRINT
    blueprint = source.read_text(encoding="utf-8")
    await ha_adapter.async_install_blueprint(hass, blueprint)
    entries = [
        schema_1_entry("switch: same day window on weekdays", home.fan, FAN, "Living room fan"),
        schema_1_entry("light: night window at the weekend", home.lamp, LAMP, "Desk lamp"),
        schema_1_entry("cover garage: off time every day", home.garage, GARAGE, "Garage door"),
    ]
    if schema == 2:
        for entry in entries:
            entry["use_blueprint"]["input"] = schema_2_of(entry["use_blueprint"]["input"])
    (Path(hass.config.config_dir) / AUTOMATION_CONFIG_PATH).write_text(
        dump(entries), encoding="utf-8"
    )
    await hass.services.async_call("automation", "reload", blocking=True)
    await hass.async_block_till_done()
    keys = migration.SCHEMA_1_KEYS if schema == 1 else migration.SCHEMA_2_KEYS
    for entry in entries:
        assert set(entry["use_blueprint"]["input"]) == keys
        entity_id = f"automation.{markers.slugify(entry['alias'])}"
        assert state_of(hass, entity_id) == "on", entity_id
    hass_storage[STORAGE_KEY] = schema_1_store(entries, blueprint, schema)
    return entries


async def set_up(hass: HomeAssistant) -> MockConfigEntry:
    """Set the integration up, as the first start after the update does."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_TITLE,
        unique_id=DOMAIN,
        minor_version=DeviceRoutinesConfigFlow.MINOR_VERSION,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def installed_text(hass: HomeAssistant) -> str:
    path = Path(hass.config.config_dir) / "blueprints" / "automation" / markers.BLUEPRINT_PATH
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("schema", [1, 2])
async def test_first_load_migrates_every_routine_of_an_older_schema(
    hass: HomeAssistant, home: Home, hass_storage: dict[str, Any], clock: Clock, schema: int
) -> None:
    clock.set(clock.at(0, "08:00"))  # Monday
    entries = await on_schema_1(hass, home, hass_storage, schema)
    await clock.to(clock.at(0, "09:00:01"))
    assert home.switch.state_now == "on"  # the fan's window runs on the old schema
    changes = watch(hass, (FAN, LAMP, GARAGE))
    states = {entity_id: state_of(hass, entity_id) for entity_id in (FAN, LAMP, GARAGE)}

    routines = await set_up(hass)

    manager: RoutineManager = routines.runtime_data.manager
    data = manager.store.data
    # The shipped blueprint is installed, and recorded as installed.
    current = compiler.BLUEPRINT_SCHEMA_VERSION
    shipped = maintenance.shipped_blueprint_text()
    assert installed_text(hass) == shipped
    assert data.blueprint_hash == maintenance.blueprint_hash(shipped)
    assert data.blueprint_schema == current == 3
    # Every owned automation is on the current schema, with the inputs it had kept for a
    # restore; none has a countdown, so none runs a step that names the timer (F8).
    for entry in entries:
        automation_id, old = entry["id"], entry["use_blueprint"]["input"]
        written = inputs_of(hass, automation_id)
        assert list(written) == list(compiler.INPUT_KEYS), automation_id
        assert written == current_of(old), automation_id
        assert written["timer_enabled"] is False, automation_id
        record = data.owned[automation_id]
        assert (record.schema, record.previous_inputs) == (current, old)
        assert record.last_valid_inputs == written
        assert record.last_hash == markers.config_hash(file_entry(hass, automation_id) or {})
        assert issue_of(hass, "automation_load_failed", automation_id) is None
        view = manager.get(record.device_id)
        assert view is not None
        assert view.status is Status.ACTIVE
        assert view.settings == migration.decompile_inputs(old, schema)
    # No device changed state on the way, and the fan's window goes on as it was.
    assert changes == []
    assert {entity_id: state_of(hass, entity_id) for entity_id in states} == states
    health = hass.states.get(HEALTH)
    assert health is not None
    assert health.attributes["blueprint_schema"] == current
    assert health.attributes["owned_count"] == health.attributes["loaded_count"] == 3
    await clock.to(clock.at(0, "17:30:01"))
    assert home.switch.state_now == "off"
    assert changes == [(FAN, "off")]


async def test_a_failed_migration_is_automation_load_failed_and_its_fix_retries(
    hass: HomeAssistant,
    home: Home,
    hass_storage: dict[str, Any],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock.set(clock.at(0, "12:00"))
    entries = await on_schema_1(hass, home, hass_storage)
    lamp = markers.automation_id(home.lamp)
    old = next(entry for entry in entries if entry["id"] == lamp)["use_blueprint"]["input"]
    failing = [True]
    write = ha_adapter.async_write_automation

    async def flaky(hass: HomeAssistant, automation_id: str, config: Any, guard: Any) -> Any:
        if failing[0] and automation_id == lamp:
            raise ha_adapter.AdapterError("synthetic write failure")
        return await write(hass, automation_id, config, guard)

    monkeypatch.setattr(ha_adapter, "async_write_automation", flaky)

    routines = await set_up(hass)

    manager: RoutineManager = routines.runtime_data.manager
    # The lamp's rewrite failed: its automation keeps running on its schema 1 inputs.
    assert issue_of(hass, "automation_load_failed", lamp) is not None
    view = manager.get(home.lamp)
    assert view is not None
    assert view.status is Status.INVALID
    assert inputs_of(hass, lamp) == old
    record = manager.store.data.owned[lamp]
    assert (record.schema, record.previous_inputs) == (1, None)
    assert state_of(hass, "automation.routine_desk_lamp") == "on"
    # The others migrated, and the next starts would retry only the lamp's.
    others = [entry["id"] for entry in entries if entry["id"] != lamp]
    current = compiler.BLUEPRINT_SCHEMA_VERSION
    assert all(manager.store.data.owned[key].schema == current for key in others)
    assert manager.store.data.blueprint_schema == current
    failing[0] = False
    assert await async_setup_component(hass, "repairs", {})
    fixer = repairs_flow_manager(hass)
    assert fixer is not None

    # While the blueprint is edited by hand nothing migrates: the fix does not take.
    path = Path(hass.config.config_dir) / "blueprints" / "automation" / markers.BLUEPRINT_PATH
    shipped = path.read_text(encoding="utf-8")
    path.write_text(shipped + "# edited by hand\n", encoding="utf-8")
    result = await fix(fixer, f"automation_load_failed_{lamp}")
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "not_fixed")
    assert issue_of(hass, "blueprint_modified") is not None
    assert inputs_of(hass, lamp) == old

    # With the shipped file back, the fix migrates the lamp's automation again.
    path.write_text(shipped, encoding="utf-8")
    result = await fix(fixer, f"automation_load_failed_{lamp}")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert issue_of(hass, "automation_load_failed", lamp) is None
    assert issue_of(hass, "blueprint_modified") is None
    assert inputs_of(hass, lamp) == current_of(old)
    record = manager.store.data.owned[lamp]
    assert (record.schema, record.previous_inputs) == (current, old)
    view = manager.get(home.lamp)
    assert view is not None
    assert view.status is Status.ACTIVE


async def fix(fixer: RepairsFlowManager, registry_id: str) -> Any:
    """Open the fix flow of an issue and confirm its one step, as the dashboard does."""
    result = await fixer.async_init(DOMAIN, context={"issue_id": registry_id})
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "confirm")
    return await fixer.async_configure(result["flow_id"], {})
