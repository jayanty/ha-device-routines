"""Build A lane 6: the config entry migration and the blueprint input schema migration
(TECH_SPEC 4.11, plan Section 4.4 lane 6).

The schema migration runs against a fake of the manager's side of the contract
(`SchemaMigrationTarget`): it compiles with the real compiler and writes through the real
adapter, so every rewrite lands in `automations.yaml` and reloads. Schema 0 is a fake:
start and stop as `HH:MM` text, a weekdays flag and an `off_after` number. The blueprint is
a synthetic stand in that declares every schema 1 input; the shipped one is lane 2's.
Every id and name is synthetic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import time
import json
from pathlib import Path
from typing import Any

from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Event, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import dump, parse_yaml
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.device_routines as integration
from custom_components.device_routines import compiler, ha_adapter, markers, migration, settings
from custom_components.device_routines.config_flow import DeviceRoutinesConfigFlow
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.domains import profile_for
from custom_components.device_routines.models import CompileError, Days, RoutineSettings
from custom_components.device_routines.store import OwnedRecord, RoutineStore

FAN_DEVICE = "synthetic-living-room-fan"
LIGHT_DEVICE = "synthetic-hallway-light"
VACUUM_DEVICE = "synthetic-robot-vacuum"
COFFEE_DEVICE = "synthetic-coffee-maker"
PUMP_DEVICE = "synthetic-garden-pump"
PORCH_DEVICE = "synthetic-porch-light"

FAN_ID = markers.automation_id(FAN_DEVICE)
LIGHT_ID = markers.automation_id(LIGHT_DEVICE)
VACUUM_ID = markers.automation_id(VACUUM_DEVICE)
COFFEE_ID = markers.automation_id(COFFEE_DEVICE)
PUMP_ID = markers.automation_id(PUMP_DEVICE)
PORCH_ID = markers.automation_id(PORCH_DEVICE)

PROBE = "synthetic_routine_probe"
RAN = "synthetic_routine_ran"

SCHEMA_0_BLUEPRINT = f"""\
blueprint:
  name: Synthetic routine, schema 0
  domain: automation
  input:
    target_entity: {{name: Target}}
    on_action: {{name: On action}}
    off_action: {{name: Off action}}
    inactive_state: {{name: Inactive state}}
    device_id: {{name: Device}}
    start: {{name: Start, default: ""}}
    stop: {{name: Stop, default: ""}}
    weekdays_only: {{name: Weekdays only, default: false}}
    off_after: {{name: Off after, default: 0}}
triggers:
  - trigger: event
    event_type: {PROBE}
    event_data:
      device_id: !input device_id
actions:
  - event: {RAN}
    event_data:
      device_id: !input device_id
      start: !input start
"""


def schema_1_blueprint() -> str:
    """A stand in declaring every schema 1 input, the required ones without a default."""
    lines = [
        "blueprint:",
        "  name: Synthetic routine, schema 1",
        "  domain: automation",
        "  input:",
    ]
    for key in compiler.INPUT_KEYS:
        lines.append(f"    {key}:")
        lines.append(f"      name: {key}")
        if key in compiler.INPUT_DEFAULTS:
            lines.append(f"      default: {json.dumps(compiler.INPUT_DEFAULTS[key])}")
    lines += [
        "triggers:",
        "  - trigger: event",
        f"    event_type: {PROBE}",
        "    event_data:",
        "      device_id: !input device_id",
        "actions:",
        f"  - event: {RAN}",
        "    event_data:",
        "      device_id: !input device_id",
        "      on_time: !input on_time",
        "      off_time: !input off_time",
        "      days_start: !input days_start",
        "      turn_off_after_min: !input turn_off_after_min",
    ]
    return "\n".join(lines) + "\n"


def schema_0_inputs(device_id: str, target: str, **old: Any) -> dict[str, Any]:
    domain = target.partition(".")[0]
    profile = profile_for(domain)
    assert profile is not None
    return {
        "target_entity": target,
        "on_action": profile.on_action or profile.off_action,
        "off_action": profile.off_action,
        "inactive_state": profile.inactive_state,
        "device_id": device_id,
        **old,
    }


def routine(automation_id: str, alias: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": automation_id,
        "alias": alias,
        "description": "Managed by Device Routines.",
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": dict(inputs)},
    }


def decompile_schema_0(inputs: Mapping[str, Any]) -> RoutineSettings:
    """The old rules: what schema 0 inputs meant."""
    if "start" not in inputs or "stop" not in inputs:
        raise CompileError("invalid_inputs")
    start, stop = inputs["start"], inputs["stop"]
    return RoutineSettings(
        target_entity=inputs["target_entity"],
        on_time=time.fromisoformat(start) if start else None,
        off_time=time.fromisoformat(stop) if stop else None,
        days=Days.WEEKDAYS if inputs.get("weekdays_only") else Days.EVERY_DAY,
        turn_off_after_min=int(inputs.get("off_after", 0)),
    )


FAN_OLD = schema_0_inputs(
    FAN_DEVICE, "fan.living_room", start="17:00", stop="23:00", weekdays_only=True, off_after=0
)
LIGHT_OLD = schema_0_inputs(
    LIGHT_DEVICE, "light.hallway", start="07:00", stop="", weekdays_only=False, off_after=30
)
# Edited by hand under schema 0 into something the old rules cannot read.
VACUUM_OLD = schema_0_inputs(VACUUM_DEVICE, "vacuum.robot", begin="10:00")
PORCH_DETACHED = {
    "id": PORCH_ID,
    "alias": "Routine: Porch light",
    "triggers": [{"trigger": "event", "event_type": "porch_light_probe"}],
    "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.porch"}}],
}

FAN_NEW = RoutineSettings(
    target_entity="fan.living_room", on_time=time(17), off_time=time(23), days=Days.WEEKDAYS
)
LIGHT_NEW = RoutineSettings(target_entity="light.hallway", on_time=time(7), turn_off_after_min=30)


def compiled(settings_: RoutineSettings, device_id: str) -> dict[str, Any]:
    profile = profile_for(settings_.target_entity.partition(".")[0])
    assert profile is not None
    return dict(compiler.compile(settings_, profile, compiler.HelperRefs(device_id)).inputs)


COFFEE_INPUTS = compiled(
    RoutineSettings(target_entity="switch.coffee_maker", on_time=time(6, 30)), COFFEE_DEVICE
)


class FakeManager:
    """The manager's side of `SchemaMigrationTarget`, as lane 5 will implement it."""

    def __init__(self, hass: HomeAssistant, routines: RoutineStore) -> None:
        self.hass = hass
        self.routines = routines
        self.blueprint_is_shipped = True
        self.refuse: set[str] = set()
        self.ensure_calls = 0
        self.writes: list[str] = []

    async def async_ensure_blueprint(self) -> bool:
        self.ensure_calls += 1
        if self.blueprint_is_shipped:
            await ha_adapter.async_install_blueprint(self.hass, schema_1_blueprint())
        return self.blueprint_is_shipped

    async def async_write_settings(self, automation_id: str, new: RoutineSettings) -> None:
        if automation_id in self.refuse:
            raise ha_adapter.WriteConflictError("synthetic conflict")
        record = self.routines.data.owned[automation_id]
        inputs = compiled(new, record.device_id)
        current = await ha_adapter.async_read_automation(self.hass, automation_id)
        assert current is not None
        guard = ha_adapter.file_hash(self.hass)
        config = {**current, "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": inputs}}
        await ha_adapter.async_write_automation(self.hass, automation_id, config, guard)
        self.routines.data.owned[automation_id] = replace(
            record,
            last_hash=markers.config_hash(config),
            last_valid_inputs=inputs,
            schema=compiler.BLUEPRINT_SCHEMA_VERSION,
        )
        self.writes.append(automation_id)


def file_entries(path: Path) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = parse_yaml(path.read_text(encoding="utf-8"))  # type: ignore[assignment]
    return loaded


def raw(path: Path) -> bytes:
    return path.read_bytes()


def write_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    """Another writer (a person, the automation editor) saving the file."""
    path.write_text(dump(entries), encoding="utf-8")


def file_entry(path: Path, automation_id: str) -> dict[str, Any]:
    return next(item for item in file_entries(path) if item.get("id") == automation_id)


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.fixture
def schema_0(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register the old rules for the fake schema 0."""
    monkeypatch.setitem(migration.DECOMPILERS, 0, decompile_schema_0)


@pytest.fixture
async def automations(hass: HomeAssistant, tmp_path: Path) -> Path:
    """Four routines on schema 0 (one unreadable, one detached), one already on schema 1."""
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text(
        "automation: !include automations.yaml\n", encoding="utf-8"
    )
    folder = tmp_path / "blueprints" / "automation" / "device_routines"
    folder.mkdir(parents=True)
    (folder / "device_routine.yaml").write_text(SCHEMA_0_BLUEPRINT, encoding="utf-8")
    entries = [
        routine(FAN_ID, "Routine: Living room fan", FAN_OLD),
        routine(LIGHT_ID, "Routine: Hallway light", LIGHT_OLD),
        routine(VACUUM_ID, "Routine: Robot vacuum", VACUUM_OLD),
        PORCH_DETACHED,
    ]
    path = tmp_path / AUTOMATION_CONFIG_PATH
    path.write_text(dump(entries), encoding="utf-8")
    assert await async_setup_component(hass, "automation", {"automation": entries})
    await hass.async_block_till_done()
    return path


def record_of(
    device_id: str, target: str, inputs: Mapping[str, Any] | None, schema: int
) -> OwnedRecord:
    return OwnedRecord(
        device_id=device_id,
        target_entity=target,
        last_hash="0" * 64,
        last_valid_inputs=inputs,
        schema=schema,
        alias_history=(f"Routine: {device_id}",),
    )


@pytest.fixture
def routines(hass: HomeAssistant, hass_storage: dict[str, Any]) -> RoutineStore:
    loaded = RoutineStore(hass)
    loaded.data.owned = {
        FAN_ID: record_of(FAN_DEVICE, "fan.living_room", FAN_OLD, 0),
        LIGHT_ID: record_of(LIGHT_DEVICE, "light.hallway", LIGHT_OLD, 0),
        VACUUM_ID: record_of(VACUUM_DEVICE, "vacuum.robot", None, 0),
        COFFEE_ID: record_of(COFFEE_DEVICE, "switch.coffee_maker", COFFEE_INPUTS, 1),
        PUMP_ID: record_of(PUMP_DEVICE, "switch.garden_pump", None, 0),
        PORCH_ID: record_of(PORCH_DEVICE, "light.porch", None, 0),
    }
    loaded.data.blueprint_schema = 0
    return loaded


def recorder(hass: HomeAssistant) -> list[Event]:
    events: list[Event] = []
    hass.bus.async_listen(RAN, events.append)
    return events


# --------------------------------------------------------------------------------------
# The config entry
# --------------------------------------------------------------------------------------


def phase_1_entry(**overrides: Any) -> MockConfigEntry:
    values: dict[str, Any] = {
        "domain": DOMAIN,
        "title": INTEGRATION_TITLE,
        "data": {},
        "options": {"schedule_scope": "routines", "time_format": "24h"},
        "unique_id": DOMAIN,
        "version": 1,
        "minor_version": 1,
    }
    return MockConfigEntry(**(values | overrides))


def test_the_entry_minor_version_is_the_options_version() -> None:
    assert DeviceRoutinesConfigFlow.VERSION == migration.ENTRY_VERSION
    assert DeviceRoutinesConfigFlow.MINOR_VERSION == settings.OPTIONS_VERSION == 2
    assert integration.async_migrate_entry is migration.async_migrate_entry


async def test_async_migrate_entry_migrates_phase_1_options(hass: HomeAssistant) -> None:
    entry = phase_1_entry()
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 1
    assert entry.minor_version == 2
    assert entry.options == {
        **settings.GlobalSettings().to_options(),
        "schedule_scope": "routines",
        "time_format": "24h",
    }
    assert entry.runtime_data.settings == settings.GlobalSettings(
        schedule_scope=settings.ScheduleScope.ROUTINES, time_format=settings.TimeFormat.H24
    )


async def test_a_current_entry_is_left_alone(hass: HomeAssistant) -> None:
    current = settings.GlobalSettings(cleanup_after_days=7).to_options()
    entry = phase_1_entry(options=current, minor_version=2)
    entry.add_to_hass(hass)

    assert await migration.async_migrate_entry(hass, entry) is True

    assert entry.options == current
    assert entry.minor_version == 2


async def test_a_newer_minor_version_loads_as_it_is(hass: HomeAssistant) -> None:
    """A downgrade within version 1: the lenient loader reads what it knows."""
    entry = phase_1_entry(options={"time_format": "12h", "future_key": 1}, minor_version=3)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == 3
    assert entry.options == {"time_format": "12h", "future_key": 1}


async def test_another_major_version_is_refused(hass: HomeAssistant) -> None:
    entry = phase_1_entry(version=2)
    entry.add_to_hass(hass)

    assert await migration.async_migrate_entry(hass, entry) is False

    assert entry.options == {"schedule_scope": "routines", "time_format": "24h"}


# --------------------------------------------------------------------------------------
# The blueprint input schema
# --------------------------------------------------------------------------------------


@pytest.mark.usefixtures("schema_0")
async def test_async_migrate_blueprint_schema_rewrites_every_owned_automation_from_schema_0(
    hass: HomeAssistant,
    automations: Path,
    routines: RoutineStore,
    hass_storage: dict[str, Any],
) -> None:
    before = {item["id"]: item for item in file_entries(automations)}
    manager = FakeManager(hass, routines)
    ran = recorder(hass)

    failed = await migration.async_migrate_blueprint_schema(hass, manager, routines)

    # The unreadable one failed, and the one after it in id order still migrated.
    assert failed == [VACUUM_ID]
    assert sorted([FAN_ID, VACUUM_ID, LIGHT_ID]) == [FAN_ID, VACUUM_ID, LIGHT_ID]
    assert manager.ensure_calls == 1
    assert manager.writes == [FAN_ID, LIGHT_ID]

    # Decompiled with the old rules, compiled with the new, written and reloaded.
    for automation_id, new, device_id, old in (
        (FAN_ID, FAN_NEW, FAN_DEVICE, FAN_OLD),
        (LIGHT_ID, LIGHT_NEW, LIGHT_DEVICE, LIGHT_OLD),
    ):
        entry = file_entry(automations, automation_id)
        assert entry["use_blueprint"]["input"] == compiled(new, device_id)
        assert entry["alias"] == before[automation_id]["alias"]
        record = routines.data.owned[automation_id]
        assert record.previous_inputs == old
        assert record.schema == compiler.BLUEPRINT_SCHEMA_VERSION
        assert record.last_valid_inputs == compiled(new, device_id)
        assert record.alias_history == (f"Routine: {device_id}",)

    hass.bus.async_fire(PROBE, {"device_id": FAN_DEVICE})
    hass.bus.async_fire(PROBE, {"device_id": LIGHT_DEVICE})
    await settle()
    assert [dict(event.data) for event in ran] == [
        {
            "device_id": FAN_DEVICE,
            "on_time": "17:00:00",
            "off_time": "23:00:00",
            "days_start": ["mon", "tue", "wed", "thu", "fri"],
            "turn_off_after_min": 0,
        },
        {
            "device_id": LIGHT_DEVICE,
            "on_time": "07:00:00",
            "off_time": "00:00:00",
            "days_start": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "turn_off_after_min": 30,
        },
    ]

    # The failed one, the detached one and the missing one are untouched.
    assert file_entry(automations, VACUUM_ID) == before[VACUUM_ID]
    assert file_entry(automations, PORCH_ID) == before[PORCH_ID]
    assert routines.data.owned[VACUUM_ID] == record_of(VACUUM_DEVICE, "vacuum.robot", None, 0)
    assert routines.data.owned[PORCH_ID] == record_of(PORCH_DEVICE, "light.porch", None, 0)
    assert routines.data.owned[PUMP_ID] == record_of(PUMP_DEVICE, "switch.garden_pump", None, 0)
    # The routine already on schema 1 is neither read nor written.
    assert routines.data.owned[COFFEE_ID].previous_inputs is None

    assert routines.data.blueprint_schema == compiler.BLUEPRINT_SCHEMA_VERSION
    saved = hass_storage["device_routines"]["data"]
    assert saved["blueprint_schema"] == compiler.BLUEPRINT_SCHEMA_VERSION
    assert saved["owned"][FAN_ID]["previous_inputs"] == FAN_OLD


@pytest.mark.usefixtures("schema_0")
async def test_schema_migration_retries_only_what_failed(
    hass: HomeAssistant, automations: Path, routines: RoutineStore
) -> None:
    manager = FakeManager(hass, routines)
    await migration.async_migrate_blueprint_schema(hass, manager, routines)
    migrated = raw(automations)

    again = await migration.async_migrate_blueprint_schema(hass, manager, routines)

    assert again == [VACUUM_ID]
    assert manager.writes == [FAN_ID, LIGHT_ID]
    assert raw(automations) == migrated
    assert routines.data.owned[FAN_ID].previous_inputs == FAN_OLD


@pytest.mark.usefixtures("schema_0")
async def test_schema_migration_contains_a_failed_write(
    hass: HomeAssistant, automations: Path, routines: RoutineStore
) -> None:
    manager = FakeManager(hass, routines)
    manager.refuse = {FAN_ID}
    before = file_entry(automations, FAN_ID)

    failed = await migration.async_migrate_blueprint_schema(hass, manager, routines)

    assert failed == [FAN_ID, VACUUM_ID]
    assert manager.writes == [LIGHT_ID]
    assert file_entry(automations, FAN_ID) == before
    assert routines.data.owned[FAN_ID].schema == 0
    assert routines.data.owned[FAN_ID].previous_inputs is None


@pytest.mark.usefixtures("schema_0")
async def test_schema_migration_waits_for_the_shipped_blueprint(
    hass: HomeAssistant, automations: Path, routines: RoutineStore
) -> None:
    """A hand edited blueprint stays (PRD 3.1): nothing is rewritten until it is restored."""
    manager = FakeManager(hass, routines)
    manager.blueprint_is_shipped = False
    before = raw(automations)

    failed = await migration.async_migrate_blueprint_schema(hass, manager, routines)

    assert failed == []
    assert manager.ensure_calls == 1
    assert manager.writes == []
    assert raw(automations) == before
    assert routines.data.blueprint_schema == 0
    assert routines.data.owned[FAN_ID].schema == 0


async def test_nothing_due_returns_at_once(hass: HomeAssistant, routines: RoutineStore) -> None:
    routines.data.owned = {
        COFFEE_ID: record_of(COFFEE_DEVICE, "switch.coffee_maker", COFFEE_INPUTS, 1)
    }
    routines.data.blueprint_schema = compiler.BLUEPRINT_SCHEMA_VERSION
    manager = FakeManager(hass, routines)

    assert await migration.async_migrate_blueprint_schema(hass, manager, routines) == []

    assert manager.ensure_calls == 0


@pytest.mark.parametrize("recorded", [None, 0])
async def test_a_store_without_routines_records_the_schema(
    hass: HomeAssistant, routines: RoutineStore, recorded: int | None
) -> None:
    """A fresh Store, or one from before the schema moved, with no routine to rewrite."""
    routines.data.owned = {}
    routines.data.blueprint_schema = recorded
    manager = FakeManager(hass, routines)
    manager.blueprint_is_shipped = False

    assert await migration.async_migrate_blueprint_schema(hass, manager, routines) == []
    assert routines.data.blueprint_schema == recorded

    manager.ensure_calls = 0

    async def shipped() -> bool:
        manager.ensure_calls += 1
        return True

    manager.async_ensure_blueprint = shipped  # type: ignore[method-assign]
    assert await migration.async_migrate_blueprint_schema(hass, manager, routines) == []
    assert manager.ensure_calls == 1
    assert routines.data.blueprint_schema == compiler.BLUEPRINT_SCHEMA_VERSION


async def test_a_newer_recorded_schema_is_kept(hass: HomeAssistant, routines: RoutineStore) -> None:
    """After a downgrade nothing moves backwards: a later schema is not this code's to undo."""
    later = compiler.BLUEPRINT_SCHEMA_VERSION + 1
    routines.data.owned = {
        COFFEE_ID: record_of(COFFEE_DEVICE, "switch.coffee_maker", COFFEE_INPUTS, later)
    }
    routines.data.blueprint_schema = later
    manager = FakeManager(hass, routines)

    assert await migration.async_migrate_blueprint_schema(hass, manager, routines) == []

    assert manager.ensure_calls == 0
    assert routines.data.blueprint_schema == later
    assert routines.data.owned[COFFEE_ID].schema == later


@pytest.mark.usefixtures("schema_0")
async def test_inputs_that_are_not_a_mapping_fail(
    hass: HomeAssistant, automations: Path, routines: RoutineStore
) -> None:
    broken = routine(FAN_ID, "Routine: Living room fan", {})
    broken["use_blueprint"]["input"] = ["not", "a", "mapping"]
    entries = [item for item in file_entries(automations) if item["id"] != FAN_ID]
    write_entries(automations, [*entries, broken])
    manager = FakeManager(hass, routines)

    failed = await migration.async_migrate_blueprint_schema(hass, manager, routines)

    assert failed == [FAN_ID, VACUUM_ID]
    assert manager.writes == [LIGHT_ID]


def test_decompile_inputs_picks_the_rules_of_the_schema(schema_0: None) -> None:
    current = compiled(FAN_NEW, FAN_DEVICE)

    assert migration.decompile_inputs(current, compiler.BLUEPRINT_SCHEMA_VERSION) == FAN_NEW
    assert migration.decompile_inputs(FAN_OLD, 0) == FAN_NEW
    with pytest.raises(CompileError) as raised:
        migration.decompile_inputs(FAN_OLD, -5)
    assert raised.value.translation_key == "invalid_inputs"
