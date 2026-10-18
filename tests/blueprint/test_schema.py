"""The shape of the shipped blueprint: TECH_SPEC 5.1 to 5.5 with the Stage 0 results applied.

These tests read the file itself. The behavior of each rule is proven by the matrix tests
next to this file; here only the structure the spec and decisions L20, L22, L24, L60 and
the A6 note pin is checked. The file is blueprint input schema 2 (plan Section 6.2.1): the
29 inputs of schema 1 plus the nine of sun bounds, each new one defaulting to schema 1
behavior. Its last section, collapsed, holds the inputs Device Routines sets itself that
have a default; the four without one stay in Target, marked (owner decision O3, L74).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from homeassistant.components.automation.config import (
    AUTOMATION_BLUEPRINT_SCHEMA,
    async_validate_config_item,
)
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import Input, parse_yaml
import pytest

from tests.blueprint.conftest import (
    AUTOMATION_ID,
    BLUEPRINT_SCHEMA_VERSION,
    BLUEPRINT_SOURCE,
    EVENT_ACTION_SKIPPED,
    EVENT_TIMER_CAUGHT_UP,
    INPUT_KEYS,
    SCHEDULE,
    SCHEMA_1_INPUT_KEYS,
    SCHEMA_2_NEW_KEYS,
    SET_BY_DEVICE_ROUTINES,
    SET_IN_MANAGED_SECTION,
    SET_IN_TARGET,
    TIMER,
    UNUSED_DATETIME,
    UNUSED_SCHEDULE,
    UNUSED_SWITCH,
    UNUSED_TIMER,
    inputs,
    owned_automation,
    schema_1_inputs,
    sun_offset,
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
# The four sun flags of plan Section 6.2.1, which the compiler derives from the kinds.
SUN_FLAGS = {
    Input("on_at_sunrise"),
    Input("on_at_sunset"),
    Input("off_at_sunrise"),
    Input("off_at_sunset"),
}
# What each new input holds when a routine does not give it: schema 1 behavior.
SCHEMA_2_DEFAULTS = {
    "on_kind": "time",
    "on_sun_offset": "00:00:00",
    "off_kind": "time",
    "off_sun_offset": "00:00:00",
    "on_at_sunrise": False,
    "on_at_sunset": False,
    "off_at_sunrise": False,
    "off_at_sunset": False,
    "late_sun_offset": "00:15:00",
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


def section_of(blueprint: Mapping[str, Any], key: str) -> str:
    """Return the section an input sits in."""
    return next(name for name, section in sections(blueprint).items() if key in section["input"])


def walk(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Yield every node of the YAML tree with the keys and indexes leading to it."""
    yield path, node
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from walk(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, (*path, str(index)))


def node_at(root: Any, path: tuple[str, ...]) -> Any:
    """Return the node a path from `walk` leads to."""
    node = root
    for step in path:
        node = node[int(step)] if isinstance(node, list) else node[step]
    return node


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


def sun_nodes(root: Any) -> Iterator[tuple[tuple[str, ...], Mapping[str, Any]]]:
    """Yield every sun trigger and sun condition with its path."""
    for path, value in walk(root):
        if isinstance(value, Mapping) and "sun" in (value.get("trigger"), value.get("condition")):
            yield path, value


def switches_of(root: Any, path: tuple[str, ...]) -> list[Any]:
    """Return the `enabled` values of a node and of every node above it."""
    return [
        node["enabled"]
        for depth in range(len(path) + 1)
        if isinstance(node := node_at(root, path[:depth]), Mapping) and "enabled" in node
    ]


async def test_loads_through_the_automation_blueprint_schema(
    hass: HomeAssistant, blueprint: dict[str, Any], installed_blueprint: Path
) -> None:
    loaded = Blueprint(blueprint, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)

    assert loaded.name == "Device routine (managed by Device Routines)"
    # An automation built from the default inputs, one using every helper, sun bounds with
    # offsets both ways and the inputs a schema 1 compiler wrote all validate.
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
        inputs(
            on_kind="sunset",
            on_sun_offset=sun_offset(-180),
            off_kind="sunrise",
            off_sun_offset=sun_offset(180),
        ),
        inputs(on_kind="sunrise", on_sun_offset=sun_offset(30), off_time="23:00:00"),
        inputs(on_kind="sunset", on_sun_offset=sun_offset(-45), late_start_window_min=0),
        schema_1_inputs(on_time="17:00:00", off_time="09:00:00"),
    ):
        validated = await async_validate_config_item(
            hass, AUTOMATION_ID, owned_automation(routine_inputs)
        )
        assert validated is not None
        assert validated.validation_status == "ok", validated.validation_error


def test_every_input_of_the_contract_exists_once_in_order(blueprint: dict[str, Any]) -> None:
    keys = [key for key, _ in flat_inputs(blueprint)]

    assert tuple(keys) == INPUT_KEYS
    assert len(keys) == len(set(keys)) == 38
    assert list(inputs()) == list(INPUT_KEYS)
    # Schema 2 is schema 1 with nine inputs added; none went away. The form's sections
    # moved some (owner decision O3), which is layout only: inputs are stored flat.
    assert set(SCHEMA_1_INPUT_KEYS) <= set(keys)
    assert tuple(SCHEMA_2_DEFAULTS) == SCHEMA_2_NEW_KEYS
    assert {key: section_of(blueprint, key) for key in SCHEMA_2_NEW_KEYS} == {
        **dict.fromkeys(SCHEMA_2_NEW_KEYS, "managed"),
        **dict.fromkeys(("on_kind", "on_sun_offset", "off_kind", "off_sun_offset"), "schedule"),
    }


def test_the_sections_follow_the_spec(blueprint: dict[str, Any]) -> None:
    found = sections(blueprint)

    assert list(found) == ["target", "schedule", "timers", "behavior", "advanced", "managed"]
    assert [found[key].get("collapsed", False) for key in found] == [
        False,
        False,
        True,
        True,
        True,
        True,
    ]
    for key, section in found.items():
        assert section.get("name"), key
        assert section.get("description"), key


def test_the_inputs_device_routines_sets_are_marked_or_folded_away(
    blueprint: dict[str, Any],
) -> None:
    """Owner decision O3 and decision L74: the form shows first what a person may change.

    Every input Device Routines sets itself, which `decompile` never reads, is apart from
    what a person edits: the four without a default sit in Target under the device, each
    description starting "Set by Device Routines:", and the rest fill the last section,
    collapsed. The sections between hold only inputs a person may edit. The contract tests
    prove the split against `decompile` itself.
    """
    (first, target), *middle, (last, managed) = sections(blueprint).items()
    edited = [key for _, section in middle for key in section["input"]]

    assert first == "target"
    assert tuple(target["input"]) == ("target_entity", *SET_IN_TARGET)
    assert target["description"].startswith("Only the device is chosen here.")
    for key in SET_IN_TARGET:
        assert target["input"][key]["description"].startswith("Set by Device Routines: "), key
    assert last == "managed"
    assert managed["name"] == "Set by Device Routines (do not edit)"
    assert "Device Routines writes these itself" in managed["description"]
    assert "an edit here is undone or ignored" in managed["description"]
    assert managed["collapsed"] is True
    assert tuple(managed["input"]) == SET_IN_MANAGED_SECTION
    assert not set(edited) & set(SET_BY_DEVICE_ROUTINES)
    assert ("target_entity", *SET_IN_TARGET, *edited, *SET_IN_MANAGED_SECTION) == INPUT_KEYS


def test_every_collapsed_section_holds_only_inputs_with_a_default(
    blueprint: dict[str, Any],
) -> None:
    """A section declared collapsed can collapse in the core's form.

    The automation editor renders a blueprint section expanded, without a collapse control,
    while any of its inputs has no default (`_renderSection` in the frontend's
    `blueprint-generic-editor.ts`: `expanded = !section.collapsed || anyRequired`,
    `noCollapse = anyRequired`). So the inputs without a default stay in Target, which the
    form shows open anyway (decision L74).
    """
    found = sections(blueprint)
    required = {key for key, definition in flat_inputs(blueprint) if "default" not in definition}

    assert required == {"target_entity", *SET_IN_TARGET}
    assert set(found["target"]["input"]) == required
    for name, section in found.items():
        if section.get("collapsed", False):
            assert not required & set(section["input"]), name


def test_every_input_has_a_name_a_description_and_a_selector(blueprint: dict[str, Any]) -> None:
    for key, definition in flat_inputs(blueprint):
        assert definition.get("name"), key
        assert definition.get("description"), key
        assert isinstance(definition.get("selector"), Mapping), key


def test_the_new_inputs_have_the_selectors_of_the_contract(blueprint: dict[str, Any]) -> None:
    selectors = {key: definition["selector"] for key, definition in flat_inputs(blueprint)}
    kinds = [{"value": "time", "label": "Time"}, {"value": "sunrise", "label": "Sunrise"}]
    kinds.append({"value": "sunset", "label": "Sunset"})

    assert selectors["on_kind"] == selectors["off_kind"] == {"select": {"options": kinds}}
    for key in ("on_sun_offset", "off_sun_offset", "late_sun_offset"):
        assert selectors[key] == {"text": {}}, key
    for key in ("on_at_sunrise", "on_at_sunset", "off_at_sunrise", "off_at_sunset"):
        assert selectors[key] == {"boolean": {}}, key


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


def test_every_new_input_defaults_to_schema_1_behavior(blueprint: dict[str, Any]) -> None:
    defaults = {key: definition.get("default") for key, definition in flat_inputs(blueprint)}
    loaded = Blueprint(blueprint, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)
    routine = schema_1_inputs(on_time="06:30:00", off_time="17:30:00", pulse_at="12:00:00")

    assert {key: defaults[key] for key in SCHEMA_2_NEW_KEYS} == SCHEMA_2_DEFAULTS
    # Every sun trigger and sun condition is switched by a sun flag, and a schema 1 routine
    # (inputs without the nine keys) leaves all of them off, so it runs as on schema 1.
    raw = list(sun_nodes(blueprint))
    assert [node["event"] for _, node in raw if "trigger" in node] == ["sunrise", "sunset"] * 2
    assert [node for _, node in raw if "condition" in node]
    for path, _ in raw:
        assert SUN_FLAGS & set(switches_of(blueprint, path)), path
    substituted = BlueprintInputs(loaded, owned_automation(routine)).async_substitute()
    rendered = list(sun_nodes(substituted))
    assert [path for path, _ in rendered] == [path for path, _ in raw]
    for path, _ in rendered:
        assert False in switches_of(substituted, path), path


def test_header_names_schema_2() -> None:
    header = BLUEPRINT_SOURCE.read_text(encoding="utf-8").splitlines()[:3]

    assert header[0] == f"# Device Routines blueprint, schema {BLUEPRINT_SCHEMA_VERSION}."
    assert header[0] == "# Device Routines blueprint, schema 2."
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


def test_sun_triggers_carry_the_scheduled_ids(blueprint: dict[str, Any]) -> None:
    sun = [trigger for trigger in triggers(blueprint) if trigger["trigger"] == "sun"]

    # L60: the ids of the time triggers, so every branch, the start and end day checks,
    # pause, skip and the skipped action event treat a sun bound like a time.
    assert [
        (trigger["id"], trigger["event"], trigger["offset"], trigger["enabled"]) for trigger in sun
    ] == [
        ("scheduled_on", "sunrise", Input("on_sun_offset"), Input("on_at_sunrise")),
        ("scheduled_on", "sunset", Input("on_sun_offset"), Input("on_at_sunset")),
        ("scheduled_off", "sunrise", Input("off_sun_offset"), Input("off_at_sunrise")),
        ("scheduled_off", "sunset", Input("off_sun_offset"), Input("off_at_sunset")),
    ]
    # Each side's triggers sit together: its time trigger, then its two sun triggers.
    order = [(trigger["id"], trigger["trigger"]) for trigger in triggers(blueprint)][:6]
    assert order == [
        ("scheduled_on", "time"),
        ("scheduled_on", "sun"),
        ("scheduled_on", "sun"),
        ("scheduled_off", "time"),
        ("scheduled_off", "sun"),
        ("scheduled_off", "sun"),
    ]


def test_no_sun_sun_state_condition(blueprint: dict[str, Any]) -> None:
    # L60: sun.sun carries neither the offsets nor the weekday sets of a window.
    text = BLUEPRINT_SOURCE.read_text(encoding="utf-8")
    kinds = {cond["condition"] for cond in conditions_of(blueprint["actions"])}
    kinds |= {trigger["trigger"] for trigger in triggers(blueprint)}
    sun_conditions = [
        (path, cond)
        for path, cond in sun_nodes(blueprint["actions"])
        if cond.get("condition") == "sun"
    ]

    assert "sun.sun" not in text
    assert not {kind for kind in kinds if kind.startswith("sun.")}
    assert sun_conditions
    for path, cond in sun_conditions:
        # One event per condition, so never `after: sunset, before: sunrise`, which the
        # core reads as an or; the offset of each half is the side's input.
        events = {cond.get("after"), cond.get("before")} - {None}
        assert len(events) == 1, path
        for half in ("after", "before"):
            if half in cond:
                assert isinstance(cond[f"{half}_offset"], Input), path
        # Each half is tested on its day set: a weekday condition sits beside it.
        siblings = node_at(blueprint["actions"], path[:-1])
        weekdays = [
            sibling["weekday"]
            for sibling in siblings
            if sibling.get("condition") == "time" and "weekday" in sibling
        ]
        assert weekdays in ([Input("days_start")], [Input("days_end")]), path


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
