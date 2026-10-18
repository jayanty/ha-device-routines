"""Build A lane 3: the adapter's write, blueprint, helper, label, category and restore
state capabilities, proven in the harness (TECH_SPEC 4.2, plan Section 4.3 lane 3).

Every name is generic and every value synthetic. The blueprint here is a small stand in
for the shipped one, which lane 2 writes in parallel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import automation as automation_component, websocket_api
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.components.blueprint import models as blueprint_models
from homeassistant.components.websocket_api import messages
from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    category_registry as cr,
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
    restore_state,
)
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util, yaml as ha_yaml
from homeassistant.util.yaml import dump, parse_yaml
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.device_routines import ha_adapter, markers

DEVICE_ID = "synthetic-living-room-fan"
ROUTINE_ID = markers.automation_id(DEVICE_ID)
ROUTINE = "automation.routine_living_room_fan"
LONG_RUN = "automation.long_run"
LOOKALIKE_ID = "living_room_fan_schedule"

BLUEPRINT_TEXT = """\
# A synthetic stand in for the shipped routine blueprint; the installed file keeps this.
blueprint:
  name: Synthetic routine
  description: Fires an event when its trigger event arrives.
  domain: automation
  input:
    event_type:
      name: Event type
      default: synthetic_routine
    minutes:
      name: Minutes
      default: 1
    days:
      name: Days
      default: []
triggers:
  - trigger: event
    event_type: !input event_type
actions:
  - event: synthetic_routine_ran
    event_data:
      minutes: !input minutes
      days: !input days
"""

HAND_MAINTAINED = """\
# Hand maintained automations, with comments and an anchor.
- id: long_run
  alias: Long run
  triggers:
    - trigger: event
      event_type: long_run_start
  actions:
    - delay:
        minutes: 10
- alias: Hallway light at dusk   # no id: the editor would add one, the adapter does not
  description: |
    Two lines
    of text.
  triggers: &evening
    - trigger: time
      at: "19:30:00"
  actions:
    - action: light.turn_on
      target:
        entity_id: light.hallway
      data:
        brightness_pct: 40
- actions:
    - action: switch.turn_off
      target: {entity_id: switch.coffee_maker}
  triggers: *evening
  id: coffee_maker_off
  alias: Coffée maker off
  mode: single
"""


def owned(minutes: int = 1, *, routine_id: str = ROUTINE_ID) -> dict[str, Any]:
    """A routine config carrying M1 and M2."""
    return {
        "id": routine_id,
        "alias": "Routine: Living room fan",
        "description": "Managed by Device Routines.",
        "use_blueprint": {
            "path": markers.BLUEPRINT_PATH,
            "input": {
                "event_type": "living_room_fan_probe",
                "minutes": minutes,
                "days": ["mon", "tue"],
            },
        },
    }


def hand_written(entry_id: str, alias: str = "Coffee maker on") -> dict[str, Any]:
    return {
        "id": entry_id,
        "alias": alias,
        "triggers": [{"trigger": "event", "event_type": f"{entry_id}_event"}],
        "actions": [{"action": "switch.turn_on", "target": {"entity_id": "switch.coffee_maker"}}],
    }


def long_run() -> dict[str, Any]:
    return {
        "id": "long_run",
        "alias": "Long run",
        "triggers": [{"trigger": "event", "event_type": "long_run_start"}],
        "actions": [{"delay": {"minutes": 10}}],
    }


def entries(path: Path) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = parse_yaml(path.read_text(encoding="utf-8"))  # type: ignore[assignment]
    return loaded


def entry(path: Path, entry_id: str) -> dict[str, Any]:
    return next(item for item in entries(path) if item.get("id") == entry_id)


def append_entry(path: Path, new: dict[str, Any]) -> None:
    """Another writer (the automation editor, a person) saving the file."""
    path.write_text(dump([*entries(path), new]), encoding="utf-8")


def replace_entry(path: Path, new: dict[str, Any]) -> None:
    current = [item for item in entries(path) if item.get("id") != new["id"]]
    path.write_text(dump([*current, new]), encoding="utf-8")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw(path: Path) -> bytes:
    return path.read_bytes()


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def put(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def remove(path: Path) -> None:
    path.unlink()


async def settle() -> None:
    """Let callbacks run without waiting for the in flight delay, as block_till_done would."""
    for _ in range(10):
        await asyncio.sleep(0)


def in_flight(hass: HomeAssistant) -> int:
    state = hass.states.get(LONG_RUN)
    assert state is not None
    current: int = state.attributes["current"]
    return current


async def reload_one(hass: HomeAssistant, entry_id: str) -> None:
    await hass.services.async_call("automation", "reload", {"id": entry_id}, blocking=True)
    await settle()


def record(hass: HomeAssistant, event_type: str) -> list[Event]:
    events: list[Event] = []
    hass.bus.async_listen(event_type, events.append)
    return events


@pytest.fixture
def config_dir(hass: HomeAssistant, tmp_path: Path) -> Path:
    """A scratch configuration directory holding one hand written automation."""
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text(
        "automation: !include automations.yaml\n", encoding="utf-8"
    )
    (tmp_path / AUTOMATION_CONFIG_PATH).write_text(dump([long_run()]), encoding="utf-8")
    return tmp_path


@pytest.fixture
async def automations(hass: HomeAssistant, config_dir: Path) -> Path:
    """The file loaded, the synthetic blueprint installed and one unowned run in flight."""
    assert await async_setup_component(
        hass, "automation", {"automation": entries(config_dir / AUTOMATION_CONFIG_PATH)}
    )
    await hass.async_block_till_done()
    await ha_adapter.async_install_blueprint(hass, BLUEPRINT_TEXT)
    hass.bus.async_fire("long_run_start")
    await settle()
    assert in_flight(hass) == 1
    return config_dir / AUTOMATION_CONFIG_PATH


@pytest.fixture
async def system_user(hass: HomeAssistant) -> str:
    """The timer and schedule components (one YAML timer included) and the system user."""
    assert await async_setup_component(
        hass, "timer", {"timer": {"hallway_light": {"duration": "00:05:00"}}}
    )
    assert await async_setup_component(hass, "schedule", {})
    return await ha_adapter.async_ensure_system_user(hass, None)


# --------------------------------------------------------------------------------------
# Writing automations
# --------------------------------------------------------------------------------------


async def test_write_creates_updates_and_deletes_an_entry_with_a_run_in_flight_elsewhere(
    hass: HomeAssistant, automations: Path
) -> None:
    long_run_changed = hass.states.get(LONG_RUN).last_changed  # type: ignore[union-attr]
    assert await ha_adapter.async_read_automation(hass, ROUTINE_ID) is None
    guard = ha_adapter.file_hash(hass)
    assert guard == sha256_of(automations)

    created = await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(1), guard)

    assert created.created is True
    assert created.hash == sha256_of(automations) == ha_adapter.file_hash(hass)
    state = hass.states.get(ROUTINE)
    assert state is not None
    assert state.state == "on"
    assert in_flight(hass) == 1

    assert await ha_adapter.async_read_automation(hass, ROUTINE_ID) == owned(1)
    updated = await ha_adapter.async_write_automation(
        hass, ROUTINE_ID, owned(2), ha_adapter.file_hash(hass)
    )

    assert updated.created is False
    assert updated.hash == sha256_of(automations)
    stored = await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    assert stored is not None
    assert stored["use_blueprint"]["input"]["minutes"] == 2
    assert in_flight(hass) == 1
    ran = record(hass, "synthetic_routine_ran")
    hass.bus.async_fire("living_room_fan_probe")
    await settle()
    assert [event.data["minutes"] for event in ran] == [2]

    assert await ha_adapter.async_delete_automation(hass, ROUTINE_ID) is True
    await settle()

    assert hass.states.get(ROUTINE) is None
    assert await ha_adapter.async_read_automation(hass, ROUTINE_ID) is None
    assert in_flight(hass) == 1
    assert hass.states.get(LONG_RUN).last_changed == long_run_changed  # type: ignore[union-attr]


async def test_write_refuses_an_unowned_config(hass: HomeAssistant, automations: Path) -> None:
    lookalike = hand_written(LOOKALIKE_ID, alias="Routine: Living room fan")
    lookalike["description"] = owned()["description"]
    append_entry(automations, lookalike)
    await reload_one(hass, LOOKALIKE_ID)
    label = ha_adapter.ensure_label(hass, "routines", "Routines", "mdi:calendar-clock")
    category = ha_adapter.ensure_category(
        hass, "automation", "Device Routines", "mdi:calendar-clock"
    )
    ha_adapter.async_update_registry_entity(
        hass, ROUTINE, labels={label}, categories={"automation": category}
    )
    before = raw(automations)
    m1_without_m2 = {**lookalike, "id": ROUTINE_ID}
    m2_without_m1 = {**owned(), "id": LOOKALIKE_ID}

    for config in (lookalike, m1_without_m2, m2_without_m1):
        with pytest.raises(ha_adapter.NotOwnedError):
            await ha_adapter.async_write_automation(hass, config["id"], config, None)
    # An owned config aimed at another id would overwrite whatever lives there.
    with pytest.raises(ha_adapter.NotOwnedError):
        await ha_adapter.async_write_automation(hass, LOOKALIKE_ID, owned(), None)

    assert raw(automations) == before
    assert hass.states.get(ROUTINE) is not None


async def test_write_and_delete_refuse_a_detached_entry(
    hass: HomeAssistant, automations: Path
) -> None:
    """Take control keeps M1 and drops M2: the entry is the person's from then on."""
    detached = hand_written(ROUTINE_ID, alias="Routine: Living room fan")
    append_entry(automations, detached)
    before = raw(automations)

    with pytest.raises(ha_adapter.NotOwnedError):
        await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(), None)
    with pytest.raises(ha_adapter.NotOwnedError):
        await ha_adapter.async_delete_automation(hass, ROUTINE_ID)
    with pytest.raises(ha_adapter.NotOwnedError):
        await ha_adapter.async_delete_automation(hass, LOOKALIKE_ID)

    assert raw(automations) == before


async def test_write_keeps_the_other_entries_semantically(
    hass: HomeAssistant, automations: Path
) -> None:
    put(automations, HAND_MAINTAINED)
    others = entries(automations)

    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(1), None)
    await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), ha_adapter.file_hash(hass))

    after = entries(automations)
    kept = [item for item in after if item.get("id") != ROUTINE_ID]
    # Values and key order of every other entry, nested ones included.
    assert json.dumps(kept) == json.dumps(others)
    assert "id" not in kept[1]
    # The written entry follows the editor's key order.
    assert list(entry(automations, ROUTINE_ID)) == ["id", "alias", "description", "use_blueprint"]
    # Comments go, exactly as the core automation editor drops them (a known limitation).
    assert "Hand maintained" not in text_of(automations)


async def test_write_retries_once_then_raises_write_conflict(
    hass: HomeAssistant, automations: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ha_adapter._read_file
    pending: list[dict[str, Any]] = []

    def read_then_someone_saves(file_path: str) -> tuple[list[Any], str]:
        result = original(file_path)
        if pending:
            append_entry(automations, pending.pop(0))
        return result

    monkeypatch.setattr(ha_adapter, "_read_file", read_then_someone_saves)

    # One move under the write: re read and retried; the other writer's entry survives.
    pending.append(hand_written("coffee_maker_on"))
    result = await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(1), None)

    assert [item["id"] for item in entries(automations)] == [
        "long_run",
        "coffee_maker_on",
        ROUTINE_ID,
    ]
    assert result.hash == sha256_of(automations)

    # Two moves: WriteConflictError, nothing of ours written, the other writer's kept.
    pending.extend([hand_written("kettle_on"), hand_written("kettle_off")])
    with pytest.raises(ha_adapter.WriteConflictError):
        await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), None)

    assert {"kettle_on", "kettle_off"} <= {item["id"] for item in entries(automations)}
    assert entry(automations, ROUTINE_ID)["use_blueprint"]["input"]["minutes"] == 1


async def test_a_guard_from_an_older_read_writes_when_only_other_entries_moved(
    hass: HomeAssistant, automations: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(1), None)
    await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    guard = ha_adapter.file_hash(hass)
    append_entry(automations, hand_written("coffee_maker_on"))

    result = await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), guard)

    assert result.created is False
    assert entry(automations, ROUTINE_ID)["use_blueprint"]["input"]["minutes"] == 2
    assert "coffee_maker_on" in {item["id"] for item in entries(automations)}

    # The stale guard was the one move allowed: a second one under the write conflicts.
    await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    guard = ha_adapter.file_hash(hass)
    append_entry(automations, hand_written("kettle_on"))
    original = ha_adapter._read_file

    def read_then_someone_saves(file_path: str) -> tuple[list[Any], str]:
        result = original(file_path)
        append_entry(automations, hand_written("kettle_off"))
        return result

    monkeypatch.setattr(ha_adapter, "_read_file", read_then_someone_saves)
    with pytest.raises(ha_adapter.WriteConflictError):
        await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(3), guard)
    assert entry(automations, ROUTINE_ID)["use_blueprint"]["input"]["minutes"] == 2


async def test_a_change_to_the_target_after_the_read_is_never_overwritten(
    hass: HomeAssistant, automations: Path
) -> None:
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(1), None)
    await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    guard = ha_adapter.file_hash(hass)
    # Someone saves the blueprint form of the routine itself after the caller's read.
    replace_entry(automations, owned(5))

    with pytest.raises(ha_adapter.WriteConflictError):
        await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), guard)
    assert entry(automations, ROUTINE_ID)["use_blueprint"]["input"]["minutes"] == 5

    # A guard the adapter never handed out cannot be verified, so it is refused too.
    with pytest.raises(ha_adapter.WriteConflictError):
        await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), "0" * 64)
    assert entry(automations, ROUTINE_ID)["use_blueprint"]["input"]["minutes"] == 5


async def test_a_guard_older_than_the_remembered_reads_is_refused(
    hass: HomeAssistant, automations: Path
) -> None:
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(1), None)
    await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    oldest = ha_adapter.file_hash(hass)
    for index in range(20):
        append_entry(automations, hand_written(f"lamp_{index}"))
        await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    recent = ha_adapter.file_hash(hass)
    append_entry(automations, hand_written("lamp_last"))

    with pytest.raises(ha_adapter.WriteConflictError):
        await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), oldest)
    result = await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), recent)

    assert result.created is False
    assert entry(automations, ROUTINE_ID)["use_blueprint"]["input"]["minutes"] == 2


async def test_a_missing_empty_or_malformed_file(hass: HomeAssistant, config_dir: Path) -> None:
    path = config_dir / AUTOMATION_CONFIG_PATH
    assert ha_adapter.file_hash(hass) == ""
    assert await async_setup_component(hass, "automation", {})
    await ha_adapter.async_install_blueprint(hass, BLUEPRINT_TEXT)

    remove(path)
    assert await ha_adapter.async_read_automation(hass, ROUTINE_ID) is None
    assert ha_adapter.file_hash(hass) == hashlib.sha256(b"").hexdigest()
    result = await ha_adapter.async_write_automation(
        hass, ROUTINE_ID, owned(), ha_adapter.file_hash(hass)
    )
    assert result.created is True
    assert [item["id"] for item in entries(path)] == [ROUTINE_ID]

    put(path, "")
    assert await ha_adapter.async_read_automation(hass, ROUTINE_ID) is None

    put(path, "not_a: list\n")
    with pytest.raises(ha_adapter.AdapterError):
        await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    with pytest.raises(ha_adapter.AdapterError):
        await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(), None)
    assert text_of(path) == "not_a: list\n"


async def test_read_automations_returns_every_mapping_and_guards_a_write(
    hass: HomeAssistant, config_dir: Path
) -> None:
    """One read of the whole file (Build A lane 5): every mapping in file order, guarded."""
    path = config_dir / AUTOMATION_CONFIG_PATH
    assert await async_setup_component(hass, "automation", {})
    await ha_adapter.async_install_blueprint(hass, BLUEPRINT_TEXT)
    put(path, dump([long_run(), "not an entry", owned()]))

    read = await ha_adapter.async_read_automations(hass)
    guard = ha_adapter.file_hash(hass)

    assert [item["id"] for item in read] == ["long_run", ROUTINE_ID]
    assert guard == sha256_of(path)
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), guard)
    stored = await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    assert stored is not None
    assert stored["use_blueprint"]["input"]["minutes"] == 2

    remove(path)
    assert await ha_adapter.async_read_automations(hass) == []


async def test_delete_removes_the_registry_entry(hass: HomeAssistant, automations: Path) -> None:
    registry = er.async_get(hass)
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(), None)
    assert registry.async_get_entity_id("automation", "automation", ROUTINE_ID) == ROUTINE

    assert await ha_adapter.async_delete_automation(hass, ROUTINE_ID) is True
    await settle()

    assert registry.async_get_entity_id("automation", "automation", ROUTINE_ID) is None
    assert hass.states.get(ROUTINE) is None
    assert ROUTINE_ID not in {item["id"] for item in entries(automations)}
    # Nothing left to delete.
    assert await ha_adapter.async_delete_automation(hass, ROUTINE_ID) is False

    # An entry removed from the file by hand and reloaded leaves a restored, unavailable
    # entity; a delete clears that leftover too.
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(), None)
    put(automations, dump([long_run()]))
    await reload_one(hass, ROUTINE_ID)
    assert hass.states.get(ROUTINE).state == "unavailable"  # type: ignore[union-attr]

    assert await ha_adapter.async_delete_automation(hass, ROUTINE_ID) is False
    await settle()

    assert registry.async_get_entity_id("automation", "automation", ROUTINE_ID) is None
    assert hass.states.get(ROUTINE) is None
    assert in_flight(hass) == 1


async def test_delete_leaves_an_automation_defined_outside_the_file_alone(
    hass: HomeAssistant, config_dir: Path
) -> None:
    elsewhere = {**hand_written(ROUTINE_ID), "alias": "Routine: Living room fan"}
    assert await async_setup_component(hass, "automation", {"automation": [elsewhere]})
    await hass.async_block_till_done()

    assert await ha_adapter.async_delete_automation(hass, ROUTINE_ID) is False

    assert er.async_get(hass).async_get_entity_id("automation", "automation", ROUTINE_ID)
    assert hass.states.get(ROUTINE) is not None


# --------------------------------------------------------------------------------------
# Removal: take control, the release write, the blueprint and the system user (lane 10)
# --------------------------------------------------------------------------------------

FORMERLY = "Formerly managed by Device Routines."
PACKAGE_CONFIGURATION = (
    "automation: !include automations.yaml\nautomation package: !include package.yaml\n"
)


async def released_form(hass: HomeAssistant) -> dict[str, Any]:
    """Read the routine and render it the way removal with On removal keep does."""
    stored = await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    assert stored is not None
    plain = await ha_adapter.async_take_control_config(hass, stored)
    return {**plain, "description": FORMERLY}


async def reload_all(hass: HomeAssistant) -> None:
    await hass.services.async_call("automation", "reload", {}, blocking=True)
    await settle()


async def test_take_control_renders_the_config_the_core_runs_for_the_entry(
    hass: HomeAssistant, automations: Path
) -> None:
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, {**owned(4), "mode": "queued"}, None)
    stored = await ha_adapter.async_read_automation(hass, ROUTINE_ID)
    assert stored is not None

    plain = await ha_adapter.async_take_control_config(hass, stored)

    assert plain == ha_adapter.automation_config(hass, ROUTINE)
    assert "use_blueprint" not in plain
    assert plain["id"] == ROUTINE_ID
    assert plain["alias"] == "Routine: Living room fan"
    assert plain["description"] == "Managed by Device Routines."
    # The entry's own keys win over the blueprint's, as the core runs it.
    assert plain["mode"] == "queued"
    assert plain["triggers"] == [{"trigger": "event", "event_type": "living_room_fan_probe"}]
    assert plain["actions"][0]["event_data"] == {"minutes": 4, "days": ["mon", "tue"]}
    assert ha_adapter.is_detached(plain)


async def test_take_control_refuses_an_unowned_config_and_reports_a_missing_blueprint(
    hass: HomeAssistant, automations: Path
) -> None:
    for config in (hand_written(LOOKALIKE_ID), hand_written(ROUTINE_ID)):
        with pytest.raises(ha_adapter.NotOwnedError):
            await ha_adapter.async_take_control_config(hass, config)

    remove(automations.parent / "blueprints" / "automation" / markers.BLUEPRINT_PATH)
    await async_get_blueprints(hass).async_reset_cache()
    with pytest.raises(ha_adapter.AdapterError):
        await ha_adapter.async_take_control_config(hass, owned())


async def test_release_turns_an_owned_entry_into_a_plain_one_that_keeps_running(
    hass: HomeAssistant, automations: Path
) -> None:
    registry = er.async_get(hass)
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), None)
    unique_before = registry.async_get(ROUTINE).unique_id  # type: ignore[union-attr]
    released = await released_form(hass)
    guard = ha_adapter.file_hash(hass)

    result = await ha_adapter.async_release_automation(hass, ROUTINE_ID, released, guard)
    await settle()

    assert result.created is False
    assert result.hash == sha256_of(automations) == ha_adapter.file_hash(hass)
    stored = entry(automations, ROUTINE_ID)
    assert stored == released
    assert next(iter(stored)) == "id"
    assert ha_adapter.is_detached(stored)
    # Same entity, same unique id: Take control keeps the id (Stage 0 V8).
    assert registry.async_get(ROUTINE).unique_id == unique_before  # type: ignore[union-attr]
    assert ha_adapter.automation_blueprint(hass, ROUTINE) is None
    state = hass.states.get(ROUTINE)
    assert state is not None
    assert state.state == "on"
    assert state.attributes["friendly_name"] == "Routine: Living room fan"
    ran = record(hass, "synthetic_routine_ran")
    hass.bus.async_fire("living_room_fan_probe")
    await settle()
    assert [event.data["minutes"] for event in ran] == [2]
    assert in_flight(hass) == 1


async def test_release_refuses_every_target_and_config_that_is_not_an_owned_routine(
    hass: HomeAssistant, automations: Path
) -> None:
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), None)
    released = await released_form(hass)
    detached_id = markers.automation_id("synthetic-desk-lamp")
    missing_id = markers.automation_id("synthetic-nowhere")
    append_entry(automations, hand_written(LOOKALIKE_ID, alias="Routine: Living room fan"))
    append_entry(automations, {**hand_written(detached_id), "alias": "Routine: Desk lamp"})
    before = raw(automations)

    refused: list[tuple[str, dict[str, Any]]] = [
        # The config: another id, no M1, or still a blueprint automation (M2, or elsewhere).
        (ROUTINE_ID, {**released, "id": detached_id}),
        (LOOKALIKE_ID, {**released, "id": LOOKALIKE_ID}),
        (ROUTINE_ID, {**released, "use_blueprint": owned()["use_blueprint"]}),
        (ROUTINE_ID, {**released, "use_blueprint": {"path": "other/blueprint.yaml"}}),
        # The target: missing from the file, or detached (M1 without M2).
        (missing_id, {**released, "id": missing_id}),
        (detached_id, {**released, "id": detached_id}),
    ]
    for automation_id, config in refused:
        with pytest.raises(ha_adapter.NotOwnedError):
            await ha_adapter.async_release_automation(hass, automation_id, config)

    assert raw(automations) == before
    assert ha_adapter.automation_blueprint(hass, ROUTINE) is not None


async def test_release_keeps_the_write_guard(hass: HomeAssistant, automations: Path) -> None:
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), None)
    released = await released_form(hass)
    guard = ha_adapter.file_hash(hass)
    # Someone saves the blueprint form of the routine after the read: never overwritten.
    replace_entry(automations, owned(7))

    with pytest.raises(ha_adapter.WriteConflictError):
        await ha_adapter.async_release_automation(hass, ROUTINE_ID, released, guard)
    assert entry(automations, ROUTINE_ID)["use_blueprint"]["input"]["minutes"] == 7

    # Only other entries moved since the read: the release goes ahead.
    released = await released_form(hass)
    guard = ha_adapter.file_hash(hass)
    append_entry(automations, hand_written("coffee_maker_on"))
    await ha_adapter.async_release_automation(hass, ROUTINE_ID, released, guard)

    assert entry(automations, ROUTINE_ID) == released
    assert "coffee_maker_on" in {item["id"] for item in entries(automations)}


async def test_the_blueprint_is_removed_only_once_nothing_uses_it(
    hass: HomeAssistant, automations: Path
) -> None:
    installed = automations.parent / "blueprints" / "automation" / markers.BLUEPRINT_PATH
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), None)
    copy = {**owned(3), "id": "living_room_fan_copy", "alias": "Living room fan copy"}
    append_entry(automations, copy)
    await reload_one(hass, copy["id"])

    # A routine uses it.
    assert await ha_adapter.async_remove_blueprint(hass) is False
    await ha_adapter.async_release_automation(hass, ROUTINE_ID, await released_form(hass))
    await settle()
    # A person's copy of a routine (no M1) still uses it.
    assert await ha_adapter.async_remove_blueprint(hass) is False

    put(automations, dump([item for item in entries(automations) if item["id"] != copy["id"]]))
    # A loaded automation the file does not hold (a YAML package) still uses it.
    package = {**owned(4), "id": "package_routine_copy", "alias": "Package copy"}
    put(automations.parent / "configuration.yaml", PACKAGE_CONFIGURATION)
    put(automations.parent / "package.yaml", dump([package]))
    await reload_all(hass)
    assert await ha_adapter.async_remove_blueprint(hass) is False
    assert installed.is_file()

    put(automations.parent / "package.yaml", "[]\n")
    await reload_all(hass)
    assert await ha_adapter.async_remove_blueprint(hass) is True

    assert not installed.exists()
    assert await hass.async_add_executor_job(ha_adapter.installed_blueprint_text, hass) is None
    with pytest.raises(HomeAssistantError):
        await async_get_blueprints(hass).async_get_blueprint(markers.BLUEPRINT_PATH)
    assert await ha_adapter.async_remove_blueprint(hass) is False
    # The released routine keeps running without the blueprint, through a full reload.
    await reload_all(hass)
    ran = record(hass, "synthetic_routine_ran")
    hass.bus.async_fire("living_room_fan_probe")
    await settle()
    assert [event.data["minutes"] for event in ran] == [2]


async def test_the_file_decides_when_a_loaded_automation_still_names_the_blueprint(
    hass: HomeAssistant, automations: Path
) -> None:
    """Stage 0 V8: a taken over automation may still count as a user of the blueprint."""
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(2), None)
    released = await released_form(hass)
    # The file holds the plain form; the loaded automation is still the blueprint one.
    put(automations, dump([long_run(), released]))
    assert ha_adapter.automation_blueprint(hass, ROUTINE) is not None

    assert await ha_adapter.async_remove_blueprint(hass) is True


async def test_a_yaml_automation_without_an_id_on_the_blueprint_keeps_it(
    hass: HomeAssistant, config_dir: Path
) -> None:
    unnamed = {key: value for key, value in owned().items() if key != "id"}
    assert await async_setup_component(hass, "automation", {})
    await ha_adapter.async_install_blueprint(hass, BLUEPRINT_TEXT)
    put(config_dir / "configuration.yaml", PACKAGE_CONFIGURATION)
    put(config_dir / "package.yaml", dump([unnamed]))
    await reload_all(hass)
    assert ha_adapter.automation_references(hass)

    assert await ha_adapter.async_remove_blueprint(hass) is False


async def test_the_system_user_is_removed_and_nobody_else_ever_is(hass: HomeAssistant) -> None:
    user_id = await ha_adapter.async_ensure_system_user(hass, None)

    assert await ha_adapter.async_remove_system_user(hass, user_id) is True
    assert await hass.auth.async_get_user(user_id) is None
    assert await ha_adapter.async_remove_system_user(hass, user_id) is False

    person = await hass.auth.async_create_user("Pat")
    other = await hass.auth.async_create_system_user("Another integration")
    for refused in (person.id, other.id):
        with pytest.raises(ha_adapter.AdapterError):
            await ha_adapter.async_remove_system_user(hass, refused)
        assert await hass.auth.async_get_user(refused) is not None


# --------------------------------------------------------------------------------------
# The blueprint
# --------------------------------------------------------------------------------------


async def test_install_blueprint_is_usable_at_once_and_hash_matches(
    hass: HomeAssistant, config_dir: Path
) -> None:
    def installed() -> str | None:
        return ha_adapter.installed_blueprint_text(hass)

    assert await hass.async_add_executor_job(installed) is None
    assert await async_setup_component(hass, "automation", {})

    assert await ha_adapter.async_install_blueprint(hass, BLUEPRINT_TEXT) is False

    text = await hass.async_add_executor_job(installed)
    assert text == BLUEPRINT_TEXT
    assert (
        hashlib.sha256(text.encode()).digest() == hashlib.sha256(BLUEPRINT_TEXT.encode()).digest()
    )
    blueprint = await async_get_blueprints(hass).async_get_blueprint(markers.BLUEPRINT_PATH)
    assert set(blueprint.inputs) == {"event_type", "minutes", "days"}
    # Usable at once: a routine built on it loads and runs, no restart.
    await ha_adapter.async_write_automation(hass, ROUTINE_ID, owned(3), None)
    ran = record(hass, "synthetic_routine_ran")
    hass.bus.async_fire("living_room_fan_probe")
    await hass.async_block_till_done()
    assert [event.data["minutes"] for event in ran] == [3]

    # Installing again overrides the file, keeps the text exact and the routine running.
    upgraded = BLUEPRINT_TEXT.replace("Synthetic routine", "Synthetic routine, upgraded")
    assert await ha_adapter.async_install_blueprint(hass, upgraded) is True
    await hass.async_block_till_done()
    assert await hass.async_add_executor_job(installed) == upgraded
    hass.bus.async_fire("living_room_fan_probe")
    await hass.async_block_till_done()
    assert [event.data["minutes"] for event in ran] == [3, 3]


async def test_install_blueprint_refuses_a_text_that_is_not_an_automation_blueprint(
    hass: HomeAssistant, config_dir: Path
) -> None:
    assert await async_setup_component(hass, "automation", {})

    with pytest.raises(ha_adapter.AdapterError):
        await ha_adapter.async_install_blueprint(hass, "- just\n- a list\n")
    with pytest.raises(HomeAssistantError):
        await ha_adapter.async_install_blueprint(
            hass, BLUEPRINT_TEXT.replace("domain: automation", "domain: script")
        )

    assert await hass.async_add_executor_job(ha_adapter.installed_blueprint_text, hass) is None


# --------------------------------------------------------------------------------------
# The system user and the helpers
# --------------------------------------------------------------------------------------


async def test_system_user_is_created_once_and_is_an_administrator(hass: HomeAssistant) -> None:
    user_id = await ha_adapter.async_ensure_system_user(hass, None)

    user = await hass.auth.async_get_user(user_id)
    assert user is not None
    assert user.system_generated
    assert user.is_admin
    assert user.is_active
    assert user.name == "Device Routines"
    assert await ha_adapter.async_ensure_system_user(hass, user_id) == user_id
    named = [item for item in await hass.auth.async_get_users() if item.name == "Device Routines"]
    assert len(named) == 1

    # A stored id that names no user, or names a person, gets a new system user.
    replaced = await ha_adapter.async_ensure_system_user(hass, "no-such-user")
    person = await hass.auth.async_create_user("Pat")
    instead_of_person = await ha_adapter.async_ensure_system_user(hass, person.id)

    assert len({user_id, replaced, instead_of_person, person.id}) == 4
    for new_id in (replaced, instead_of_person):
        new = await hass.auth.async_get_user(new_id)
        assert new is not None
        assert new.system_generated
        assert new.is_admin


async def test_create_update_delete_timer_and_schedule_with_chosen_id_and_label(
    hass: HomeAssistant, system_user: str
) -> None:
    label = ha_adapter.ensure_label(hass, "routines", "Routines", "mdi:calendar-clock")
    registry = er.async_get(hass)

    timer = await ha_adapter.async_create_helper(
        hass,
        system_user,
        "timer",
        "Routine living room fan",
        entity_id="timer.routine_living_room_fan_run",
        labels={label},
        duration="00:30:00",
        restore=True,
    )

    assert timer == "timer.routine_living_room_fan_run"
    timer_entry = registry.async_get(timer)
    assert timer_entry is not None
    assert timer_entry.labels == {label}
    state = hass.states.get(timer)
    assert state is not None
    assert state.attributes["duration"] == "0:30:00"
    assert state.attributes["restore"] is True

    await ha_adapter.async_update_helper(hass, system_user, timer, duration="00:45:00")

    state = hass.states.get(timer)
    assert state is not None
    assert state.attributes["duration"] == "0:45:00"
    assert state.attributes["restore"] is True
    assert state.attributes["friendly_name"] == "Routine living room fan"
    assert registry.async_get(timer).labels == {label}  # type: ignore[union-attr]

    await ha_adapter.async_delete_helper(hass, system_user, timer)

    assert hass.states.get(timer) is None
    assert registry.async_get(timer) is None

    schedule = await ha_adapter.async_create_helper(
        hass,
        system_user,
        "schedule",
        "Routine living room fan",
        entity_id="schedule.routine_living_room_fan_window",
        labels={label},
        monday=[{"from": "17:00:00", "to": "24:00:00"}],
        tuesday=[{"from": "00:00:00", "to": "09:00:00"}],
    )

    assert schedule == "schedule.routine_living_room_fan_window"
    assert registry.async_get(schedule).labels == {label}  # type: ignore[union-attr]
    await ha_adapter.async_update_helper(hass, system_user, schedule, icon="mdi:fan")
    state = hass.states.get(schedule)
    assert state is not None
    assert state.attributes["icon"] == "mdi:fan"
    items = await ha_adapter._async_command(hass, system_user, {"type": "schedule/list"})
    assert items[0]["monday"] == [{"from": "17:00:00", "to": "24:00:00"}]

    await ha_adapter.async_delete_helper(hass, system_user, schedule)

    assert hass.states.get(schedule) is None
    # With no registry options, the generated entity id comes back as is.
    plain = await ha_adapter.async_create_helper(hass, system_user, "timer", "Robot vacuum run")
    assert plain == "timer.robot_vacuum_run"


async def test_a_helper_does_not_keep_a_device_on_this_core(
    hass: HomeAssistant, system_user: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Canary for a spec finding: timer and schedule entities have no config entry.

    Core 2026.10 clears the device of such an entity whenever it is added again (an
    entity id change, a restart) and logs a deprecation that breaks in 2027.8, so the
    adapter does not attach helpers to devices; the label and the entity id tie them to
    their routine. A core that keeps the device fails this test and reopens the choice.
    """
    config_entry = MockConfigEntry(domain="test")
    config_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={("test", "living_room_fan")},
        name="Living room fan",
    )
    timer = await ha_adapter.async_create_helper(hass, system_user, "timer", "Living room fan")
    registry = er.async_get(hass)

    ha_adapter.async_update_registry_entity(hass, timer, device_id=device.id)
    assert registry.async_get(timer).device_id == device.id  # type: ignore[union-attr]
    renamed = ha_adapter.async_update_registry_entity(
        hass, timer, new_entity_id="timer.routine_living_room_fan_run"
    )
    await hass.async_block_till_done()

    assert registry.async_get(renamed).device_id is None  # type: ignore[union-attr]
    assert "attach a device to an entity without a config entry" in caplog.text


async def test_a_non_admin_system_user_is_refused(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "timer", {})
    user = await hass.auth.async_create_system_user("Device Routines")

    with pytest.raises(ha_adapter.HelperError) as refused:
        await ha_adapter.async_create_helper(hass, user.id, "timer", "Routine living room fan")

    assert refused.value.code == "unauthorized"
    assert hass.states.async_entity_ids("timer") == []
    with pytest.raises(ha_adapter.HelperError) as unknown:
        await ha_adapter.async_create_helper(hass, "no-such-user", "timer", "Routine fan")
    assert unknown.value.code == "unknown_user"


async def test_helper_errors_carry_the_command_code(
    hass: HomeAssistant, system_user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def code_of(call: Callable[[], Any]) -> str:
        with pytest.raises(ha_adapter.HelperError) as raised:
            await call()
        return raised.value.code

    assert (
        await code_of(lambda: ha_adapter.async_update_helper(hass, system_user, "timer.gone"))
        == "not_found"
    )
    assert (
        await code_of(
            lambda: ha_adapter.async_delete_helper(hass, system_user, "switch.living_room_fan")
        )
        == "not_a_helper"
    )
    # A YAML timer has a registry entry but no storage item the commands can change.
    assert (
        await code_of(
            lambda: ha_adapter.async_update_helper(hass, system_user, "timer.hallway_light")
        )
        == "not_found"
    )
    # The core answers a delete of a missing item twice (an error, then a result); the
    # first answer is the one that counts.
    assert (
        await code_of(
            lambda: ha_adapter.async_delete_helper(hass, system_user, "timer.hallway_light")
        )
        == "not_found"
    )
    assert (
        await code_of(
            lambda: ha_adapter.async_create_helper(
                hass, system_user, "timer", "Fan", duration="not a duration"
            )
        )
        == "invalid_format"
    )
    assert (
        await code_of(lambda: ha_adapter._async_command(hass, system_user, {"type": "no/such"}))
        == "unknown_command"
    )

    # A command that never answers times out.
    websocket_api.async_register_command(
        hass, "device_routines_test/silent", _silent, messages.MINIMAL_MESSAGE_SCHEMA
    )
    monkeypatch.setattr(ha_adapter, "_COMMAND_TIMEOUT", 0.01)
    assert (
        await code_of(
            lambda: ha_adapter._async_command(
                hass, system_user, {"type": "device_routines_test/silent"}
            )
        )
        == "timeout"
    )


def _silent(hass: HomeAssistant, connection: Any, msg: dict[str, Any]) -> None:
    """A WebSocket command handler that never answers."""


async def test_a_taken_entity_id_removes_the_new_helper_again(
    hass: HomeAssistant, system_user: str
) -> None:
    taken = await ha_adapter.async_create_helper(hass, system_user, "timer", "Living room fan")

    with pytest.raises(ValueError, match="already registered"):
        await ha_adapter.async_create_helper(
            hass, system_user, "timer", "Routine living room fan", entity_id=taken
        )

    assert sorted(hass.states.async_entity_ids("timer")) == [
        "timer.hallway_light",
        "timer.living_room_fan",
    ]


async def test_a_created_helper_without_a_registry_entry_is_reported(
    hass: HomeAssistant, system_user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(er.EntityRegistry, "async_get_entity_id", lambda *_: None)

    with pytest.raises(ha_adapter.HelperError) as missing:
        await ha_adapter.async_create_helper(hass, system_user, "timer", "Living room fan")

    assert missing.value.code == "not_found"


# --------------------------------------------------------------------------------------
# Restore state, labels, categories and the small readers
# --------------------------------------------------------------------------------------


async def test_missed_timer_finishes_reads_restore_state(hass: HomeAssistant) -> None:
    now = dt_util.utcnow()
    mock_restore_cache(
        hass,
        [
            State(
                "timer.ran_out", "active", {"finishes_at": (now - timedelta(minutes=5)).isoformat()}
            ),
            State(
                "timer.time_left",
                "active",
                {"finishes_at": (now + timedelta(minutes=5)).isoformat()},
            ),
            State("timer.paused", "paused", {"remaining": "0:04:00"}),
            State("timer.idle", "idle", {}),
            State("timer.no_end", "active", {}),
        ],
    )

    missed = ha_adapter.missed_timer_finishes(
        hass,
        [
            "timer.time_left",
            "timer.ran_out",
            "timer.paused",
            "timer.idle",
            "timer.no_end",
            "timer.never_seen",
        ],
    )

    assert missed == ["timer.ran_out"]


async def test_ensure_label_and_category_are_idempotent(hass: HomeAssistant) -> None:
    labels = lr.async_get(hass)
    label = ha_adapter.ensure_label(hass, "routines", "Routines", "mdi:calendar-clock")

    assert label == "routines"
    assert ha_adapter.ensure_label(hass, "routines", "Routines", "mdi:calendar-clock") == label
    assert len(list(labels.async_list_labels())) == 1
    labels.async_update(label, icon="mdi:fan")
    assert ha_adapter.ensure_label(hass, "routines", "Routines", "mdi:calendar-clock") == label
    assert labels.async_get_label(label).icon == "mdi:calendar-clock"  # type: ignore[union-attr]
    # A label with that name under another id is reused, not duplicated.
    existing = labels.async_create("Device schedules").label_id
    assert ha_adapter.ensure_label(hass, "schedules", "Device schedules", "mdi:clock") == existing

    categories = cr.async_get(hass)
    category = ha_adapter.ensure_category(
        hass, "automation", "Device Routines", "mdi:calendar-clock"
    )

    assert (
        ha_adapter.ensure_category(hass, "automation", "device routines", "mdi:calendar-clock")
        == category
    )
    assert len(list(categories.async_list_categories(scope="automation"))) == 1
    categories.async_update(scope="automation", category_id=category, icon="mdi:fan")
    assert (
        ha_adapter.ensure_category(hass, "automation", "Device Routines", "mdi:calendar-clock")
        == category
    )
    found = categories.async_get_category(scope="automation", category_id=category)
    assert found is not None
    assert found.icon == "mdi:calendar-clock"
    other = ha_adapter.ensure_category(hass, "script", "Device Routines", "mdi:calendar-clock")
    assert other != category


def test_is_detached() -> None:
    taken_control = {key: value for key, value in owned().items() if key != "use_blueprint"}
    other_blueprint = {**owned(), "use_blueprint": {"path": "someone/else.yaml", "input": {}}}

    assert ha_adapter.is_detached(owned()) is False
    assert ha_adapter.is_detached({**taken_control, "triggers": []}) is True
    assert ha_adapter.is_detached(other_blueprint) is True
    assert ha_adapter.is_detached(hand_written(LOOKALIKE_ID)) is False


async def test_automation_state_reads_the_state_machine(hass: HomeAssistant) -> None:
    hass.states.async_set(ROUTINE, "off")

    state = ha_adapter.automation_state(hass, ROUTINE)

    assert state is not None
    assert state.state == "off"
    assert ha_adapter.automation_state(hass, "automation.none") is None


# --------------------------------------------------------------------------------------
# The capability check (finding F5)
# --------------------------------------------------------------------------------------


def adapter_records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [
        item
        for item in caplog.records
        if item.name == ha_adapter.__name__ and item.levelno == level
    ]


async def test_check_reports_each_capability_and_logs_once(
    hass: HomeAssistant, system_user: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=ha_adapter.__name__)
    assert await async_setup_component(hass, "automation", {})

    report = ha_adapter.check(hass)

    assert report.ok
    assert report.failed == ()
    assert adapter_records(caplog, logging.WARNING) == []
    with pytest.MonkeyPatch.context() as patch:
        patch.delattr(automation_component, "labels_in_automation")
        for _ in range(3):
            report = ha_adapter.check(hass)

    assert report.failed == (ha_adapter.CAPABILITY_READ,)
    assert not report.works(ha_adapter.CAPABILITY_READ)
    assert report.works(ha_adapter.CAPABILITY_WRITE)
    assert "labels_in_automation" in report.details[ha_adapter.CAPABILITY_READ]
    warnings = adapter_records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert ha_adapter.CAPABILITY_READ in warnings[0].getMessage()

    for _ in range(3):
        report = ha_adapter.check(hass)

    assert report.ok
    infos = adapter_records(caplog, logging.INFO)
    assert len(infos) == 1
    assert ha_adapter.CAPABILITY_READ in infos[0].getMessage()


def _drop_reload(hass: HomeAssistant, patch: pytest.MonkeyPatch) -> None:
    hass.services.async_remove("automation", "reload")


def _drop_yaml_dump(hass: HomeAssistant, patch: pytest.MonkeyPatch) -> None:
    patch.delattr(ha_yaml, "dump")


def _drop_add_blueprint(hass: HomeAssistant, patch: pytest.MonkeyPatch) -> None:
    patch.delattr(blueprint_models.DomainBlueprints, "async_add_blueprint")


def _drop_timer_update(hass: HomeAssistant, patch: pytest.MonkeyPatch) -> None:
    patch.delitem(hass.data[websocket_api.DOMAIN], "timer/update")


def _drop_restore_helper(hass: HomeAssistant, patch: pytest.MonkeyPatch) -> None:
    patch.delattr(restore_state, "async_get")


def _break_restore_data(hass: HomeAssistant, patch: pytest.MonkeyPatch) -> None:
    patch.setattr(restore_state, "async_get", lambda _hass: object())


@pytest.mark.parametrize(
    ("capability", "breaks", "detail"),
    [
        (ha_adapter.CAPABILITY_WRITE, _drop_reload, "automation.reload"),
        (ha_adapter.CAPABILITY_WRITE, _drop_yaml_dump, "dump"),
        (ha_adapter.CAPABILITY_BLUEPRINT, _drop_add_blueprint, "async_add_blueprint"),
        (ha_adapter.CAPABILITY_HELPERS, _drop_timer_update, "timer/update"),
        (ha_adapter.CAPABILITY_RESTORE, _drop_restore_helper, "async_get"),
        (ha_adapter.CAPABILITY_RESTORE, _break_restore_data, "last_states"),
    ],
)
async def test_each_capability_reports_what_it_misses(
    hass: HomeAssistant,
    system_user: str,
    capability: str,
    breaks: Callable[[HomeAssistant, pytest.MonkeyPatch], None],
    detail: str,
) -> None:
    assert await async_setup_component(hass, "automation", {})
    assert ha_adapter.check(hass).ok

    with pytest.MonkeyPatch.context() as patch:
        breaks(hass, patch)
        report = ha_adapter.check(hass)

    assert report.failed == (capability,)
    assert detail in report.details[capability]


async def test_an_unresolvable_registry_id_reference_is_dropped(hass: HomeAssistant) -> None:
    plug = er.async_get(hass).async_get_or_create("switch", "test", "living_room_fan")

    resolved = ha_adapter._resolved(hass, [plug.id, "no-such-registry-entry"])

    assert resolved == frozenset({plug.entity_id})
