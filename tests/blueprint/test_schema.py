"""The shape of the shipped blueprint: TECH_SPEC 5.1 to 5.5 with the Stage 0 results applied.

These tests read the file itself. The behavior of each rule is proven by the matrix tests
next to this file; here only the structure the spec and decisions L20, L22, L24 and the
A6 note pin is checked.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from homeassistant.components.automation.config import (
    AUTOMATION_BLUEPRINT_SCHEMA,
    async_validate_config_item,
)
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import Input, parse_yaml
import pytest

from tests.blueprint.conftest import (
    AUTOMATION_ID,
    BLUEPRINT_SOURCE,
    EVENT_ACTION_SKIPPED,
    EVENT_TIMER_CAUGHT_UP,
    INPUT_KEYS,
    SCHEDULE,
    TIMER,
    UNUSED_DATETIME,
    UNUSED_SCHEDULE,
    UNUSED_SWITCH,
    UNUSED_TIMER,
    inputs,
    owned_automation,
    target_inputs,
)

NOT_PAUSED_TEMPLATE = (
    "{% set s = states(paused_entity) %}"
    "{{ s in ('unknown', 'unavailable', '') or as_datetime(s) <= now() }}"
)
TRIGGER_IDS = {
    "scheduled_on",
    "scheduled_off",
    "block_on",
    "block_off",
    "ha_start",
    "reconnect",
    "device_on",
    "device_off",
    "timer_done",
    "pause_changed",
    "override_cleared",
    "pulse",
}


@pytest.fixture(scope="module")
def blueprint() -> dict[str, Any]:
    data = parse_yaml(BLUEPRINT_SOURCE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def sections(blueprint: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = blueprint["blueprint"]["input"]
    return result


def flat_inputs(blueprint: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    return [
        (key, definition)
        for section in sections(blueprint).values()
        for key, definition in section["input"].items()
    ]


def walk(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Yield every node of the YAML tree with the keys and indexes leading to it."""
    yield path, node
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from walk(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, (*path, str(index)))


def conditions_of(node: Any) -> Iterator[Mapping[str, Any]]:
    """Yield every condition mapping anywhere under a node, nested ones included."""
    for path, value in walk(node):
        if isinstance(value, Mapping) and "condition" in value and not _is_action_step(path):
            yield value


def _is_action_step(path: tuple[str, ...]) -> bool:
    """A `condition` mapping directly in a sequence is an action step, also checked below."""
    return len(path) >= 2 and path[-2] in {"sequence", "then", "else", "actions"}


def actions_of(node: Any) -> Iterator[Mapping[str, Any]]:
    """Yield every action step under a node: the items of each action list."""
    for path, value in walk(node):
        if isinstance(value, list) and path and path[-1] in {"sequence", "then", "else", "actions"}:
            yield from (step for step in value if isinstance(step, Mapping))


def triggers(blueprint: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = blueprint["triggers"]
    return result


async def test_loads_through_the_automation_blueprint_schema(
    hass: HomeAssistant, blueprint: dict[str, Any], installed_blueprint: Path
) -> None:
    loaded = Blueprint(blueprint, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)

    assert loaded.name == "Device routine (managed by Device Routines)"
    # An automation built from the default inputs, and one using every helper, validates.
    for routine_inputs in (
        inputs(),
        inputs(
            on_time="17:00:00",
            off_time="09:00:00",
            timer_entity=TIMER,
            turn_off_after_min=30,
            pulse_at="08:00:00",
            extra_conditions=[{"condition": "state", "entity_id": "sun.sun", "state": "below"}],
        ),
        inputs(schedule_entity=SCHEDULE, timer_entity=TIMER, turn_back_on_after_min=10),
        inputs(**target_inputs("vacuum", "vacuum.robot_vacuum"), on_time="09:45:00"),
    ):
        validated = await async_validate_config_item(
            hass, AUTOMATION_ID, owned_automation(routine_inputs)
        )
        assert validated is not None
        assert validated.validation_status == "ok", validated.validation_error


def test_every_input_of_the_contract_exists_once_in_order(blueprint: dict[str, Any]) -> None:
    keys = [key for key, _ in flat_inputs(blueprint)]

    assert tuple(keys) == INPUT_KEYS
    assert len(keys) == 29
    assert list(inputs()) == list(INPUT_KEYS)


def test_the_sections_follow_the_spec(blueprint: dict[str, Any]) -> None:
    found = sections(blueprint)

    assert list(found) == ["target", "schedule", "timers", "behavior", "advanced"]
    assert [found[key].get("collapsed", False) for key in found] == [
        False,
        False,
        True,
        True,
        True,
    ]


def test_every_input_has_a_name_a_description_and_a_selector(blueprint: dict[str, Any]) -> None:
    for key, definition in flat_inputs(blueprint):
        assert definition.get("name"), key
        assert definition.get("description"), key
        assert isinstance(definition.get("selector"), Mapping), key


def test_defaults_carry_the_sentinels(blueprint: dict[str, Any]) -> None:
    defaults = {key: definition.get("default") for key, definition in flat_inputs(blueprint)}

    assert defaults["schedule_entity"] == UNUSED_SCHEDULE
    assert defaults["timer_entity"] == UNUSED_TIMER
    assert defaults["override_entity"] == UNUSED_SWITCH
    assert defaults["paused_until_entity"] == UNUSED_DATETIME
    assert defaults["extra_conditions"] == []
    # Required inputs have no default; every other default equals the mirror's.
    required = {"target_entity", "on_action", "off_action", "inactive_state", "device_id"}
    assert {key for key, value in defaults.items() if value is None} == required
    assert {key: value for key, value in defaults.items() if key not in required} == {
        key: value for key, value in inputs().items() if key not in required
    }


def test_the_header_says_schema_1_and_do_not_edit() -> None:
    header = BLUEPRINT_SOURCE.read_text(encoding="utf-8").splitlines()[:3]

    assert header[0] == "# Device Routines blueprint, schema 1."
    assert "do not edit" in header[1].lower()


def test_no_source_url(blueprint: dict[str, Any]) -> None:
    # L24: the integration installs and upgrades the file; a source_url would offer a
    # re-import from GitHub and, with Spook, an update entity.
    assert "source_url" not in blueprint["blueprint"]
    assert "source_url" not in BLUEPRINT_SOURCE.read_text(encoding="utf-8")


def test_min_version_is_2026_10_2(blueprint: dict[str, Any]) -> None:
    assert blueprint["blueprint"]["homeassistant"] == {"min_version": "2026.10.2"}


def test_every_trigger_condition_and_branch_has_an_alias(blueprint: dict[str, Any]) -> None:
    missing = [trigger for trigger in triggers(blueprint) if not trigger.get("alias")]
    missing += [cond for cond in conditions_of(blueprint["actions"]) if not cond.get("alias")]
    missing += [
        option
        for _, node in walk(blueprint["actions"])
        if isinstance(node, Mapping) and "choose" in node
        for option in node["choose"]
        if not option.get("alias")
    ]
    missing += [step for step in actions_of(blueprint) if not step.get("alias")]

    assert missing == []


def test_mode_queued_max_10(blueprint: dict[str, Any]) -> None:
    assert blueprint["mode"] == "queued"
    assert blueprint["max"] == 10


def test_trigger_ids_are_the_spec_set(blueprint: dict[str, Any]) -> None:
    ids = {trigger["id"] for trigger in triggers(blueprint)}

    # pause_ended is omitted: the time trigger refuses a datetime entity (V12, L22).
    assert ids == TRIGGER_IDS
    assert all(trigger["id"] in TRIGGER_IDS for trigger in triggers(blueprint))


def test_time_triggers_are_switched_by_their_inputs(blueprint: dict[str, Any]) -> None:
    timed = {
        trigger["id"]: trigger for trigger in triggers(blueprint) if trigger["trigger"] == "time"
    }

    assert set(timed) == {"scheduled_on", "scheduled_off", "pulse"}
    assert {key: (value["at"], value["enabled"]) for key, value in timed.items()} == {
        "scheduled_on": (Input("on_time"), Input("on_time_enabled")),
        "scheduled_off": (Input("off_time"), Input("off_time_enabled")),
        "pulse": (Input("pulse_at"), Input("pulse_enabled")),
    }


def test_no_schedule_block_started_trigger(blueprint: dict[str, Any]) -> None:
    # A6: schedule.block_started fires again at midnight between back to back blocks.
    kinds = {trigger["trigger"] for trigger in triggers(blueprint)}
    blocks = [
        trigger for trigger in triggers(blueprint) if trigger["id"] in {"block_on", "block_off"}
    ]

    assert not {kind for kind in kinds if kind.startswith("schedule.")}
    assert [(block["trigger"], block["entity_id"], block["to"]) for block in blocks] == [
        ("state", Input("schedule_entity"), "on"),
        ("state", Input("schedule_entity"), "off"),
    ]


def test_timer_done_has_the_caught_up_event_twin(blueprint: dict[str, Any]) -> None:
    done = [trigger for trigger in triggers(blueprint) if trigger["id"] == "timer_done"]

    # L20: a timer that expired while Home Assistant was down finishes before triggers are
    # armed; the integration fires the caught up event for the device instead.
    assert len(done) == 2
    finished, caught_up = done
    assert finished["trigger"] == "timer.finished"
    assert finished["target"] == {"entity_id": Input("timer_entity")}
    assert caught_up["trigger"] == "event"
    assert caught_up["event_type"] == EVENT_TIMER_CAUGHT_UP
    assert caught_up["event_data"] == {"device_id": Input("device_id")}


def test_not_paused_is_the_only_template(blueprint: dict[str, Any]) -> None:
    template_conditions = [
        cond for cond in conditions_of(blueprint["actions"]) if cond["condition"] == "template"
    ]
    jinja = [
        (path, value)
        for path, value in walk(blueprint)
        if isinstance(value, str) and ("{{" in value or "{%" in value)
    ]
    skipped_event_steps = {
        path
        for path, node in walk(blueprint)
        if isinstance(node, Mapping) and node.get("event") == EVENT_ACTION_SKIPPED
    }

    # L22: the one template condition is not_paused, wherever a branch repeats it.
    assert template_conditions
    assert {cond["value_template"] for cond in template_conditions} == {NOT_PAUSED_TEMPLATE}
    assert {cond["alias"] for cond in template_conditions} == {"Not paused"}
    # Every other Jinja string is data of the skipped action event, never logic.
    for path, value in jinja:
        if value == NOT_PAUSED_TEMPLATE:
            assert path[-1] == "value_template"
            continue
        assert path[-2] == "event_data", path
        assert path[:-2] in skipped_event_steps, path
    assert not [path for path, _ in jinja if path[0] in {"triggers", "conditions", "variables"}]
