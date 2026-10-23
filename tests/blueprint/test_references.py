"""Every entity a routine's running steps name exists (live finding F8, decision L83).

An input that names a helper holds a sentinel that never exists while its feature is off
(`compiler.UNUSED_TIMER`, `compiler.UNUSED_SCHEDULE`). The core lists every entity an
automation names among its `referenced_entities`, disabled steps included, and tools that
check those references (Spook's unknown entity references repair on the instance) leave
out what only a disabled step names: a step carrying `enabled: false` never runs. So every
step that names a sentinel must carry a flag input that is `false` whenever the sentinel
is written: `schedule_enabled` for the weekly schedule, `timer_enabled` for the countdown.

`without_disabled_steps` reads a configuration the way that repair does: a trigger,
condition or action whose `enabled` is literally `false` is left out, and nothing under a
key that holds values (service data, variables, event data) counts as a step.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from homeassistant.components.automation import DATA_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest

from tests.blueprint.conftest import (
    AUTOMATION,
    OVERRIDE,
    PAUSED,
    TIMER,
    Blocks,
    Clock,
    SandboxDateTime,
    SandboxSwitch,
    inputs,
    sun_offset,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]
Schedule = Callable[[Blocks], Awaitable[str]]

# Keys whose value holds values, never a step.
VALUE_KEYS = frozenset({"data", "data_template", "service_data", "variables", "event_data"})
HELPERS = {"override_entity": OVERRIDE, "paused_until_entity": PAUSED}

# Routines of every shape, as the mirror writes them with the routine's own helpers.
SHAPES: Mapping[str, Mapping[str, Any]] = {
    "a_window": {"on_time": "17:00:00", "off_time": "09:00:00"},
    "turn_on_only": {"on_time": "07:00:00"},
    "turn_off_after": {"timer_entity": TIMER, "turn_off_after_min": 30},
    "turn_back_on_after": {"timer_entity": TIMER, "turn_back_on_after_min": 10},
    "a_window_and_turn_off_after": {
        "on_time": "17:00:00",
        "off_time": "23:00:00",
        "timer_entity": TIMER,
        "turn_off_after_min": 30,
    },
    "a_pulse": {"pulse_at": "08:00:00"},
    "a_sun_window": {
        "on_kind": "sunset",
        "on_sun_offset": sun_offset(30),
        "off_kind": "sunrise",
    },
    "a_weekly_schedule": {},
}


def without_disabled_steps(config: Any, *, in_values: bool = False) -> Any:
    """Return a copy of a configuration without the steps whose `enabled` is `false`."""
    if isinstance(config, list):
        return [
            without_disabled_steps(item, in_values=in_values)
            for item in config
            if in_values or not (isinstance(item, Mapping) and item.get("enabled") is False)
        ]
    if isinstance(config, Mapping):
        return {
            key: without_disabled_steps(value, in_values=in_values or key in VALUE_KEYS)
            for key, value in config.items()
            if in_values
            or key in VALUE_KEYS
            or not (isinstance(value, Mapping) and value.get("enabled") is False)
        }
    return config


def strings_in(config: Any) -> set[str]:
    """Return every string a configuration holds, and its lowercased comma pieces."""
    found: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, str):
            found.add(value)
            found.update(piece.strip().lower() for piece in value.split(","))
        elif isinstance(value, Mapping):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(config)
    return found


def named_by_running_steps(hass: HomeAssistant) -> set[str]:
    """Return the entities the core lists for the routine that a running step names."""
    entity = hass.data[DATA_COMPONENT].get_entity(AUTOMATION)
    assert entity is not None
    running = strings_in(without_disabled_steps(entity.raw_config))
    return {entity_id for entity_id in entity.referenced_entities if entity_id in running}


def test_a_disabled_step_names_nothing_that_runs() -> None:
    config = {
        "triggers": [
            {"trigger": "state", "entity_id": "timer.a", "enabled": False},
            {"trigger": "state", "entity_id": "switch.b"},
        ],
        "actions": [
            {"action": "timer.cancel", "target": {"entity_id": "timer.a"}, "enabled": False},
            {"event": "x", "event_data": {"items": [{"enabled": False, "entity_id": "c.d"}]}},
            {"if": {"condition": "state", "entity_id": "e.f", "enabled": False}},
        ],
    }

    running = strings_in(without_disabled_steps(config))

    assert "timer.a" not in running
    assert {"switch.b", "c.d"} <= running
    assert "e.f" not in running


@pytest.mark.parametrize("shape", list(SHAPES))
async def test_every_entity_a_running_step_names_exists(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    routine_schedule: Schedule,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    routine_timer: str,
    shape: str,
) -> None:
    clock.set(clock.at(0, "12:00"))
    assert await async_setup_component(hass, "sun", {})
    given = dict(SHAPES[shape])
    if shape == "a_weekly_schedule":
        given["schedule_entity"] = await routine_schedule({"monday": [("17:00:00", "22:00:00")]})
    await routine_automation(inputs(**given, **HELPERS))

    named = named_by_running_steps(hass)
    missing = sorted(entity_id for entity_id in named if hass.states.get(entity_id) is None)

    assert missing == []
    assert not {name for name in named if name.endswith(".device_routines_unused")}
