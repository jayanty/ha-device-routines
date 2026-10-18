"""Behavior matrix: Only when conditions (FR-R9), row B49.

The `extra_conditions` input holds native conditions that gate the scheduled start, the
catch up that turns the device on and every other path to the on action (TECH_SPEC 5.4
`extra_ok`). A start they block was not due at all, so it is no skip: the branch does not
run, nothing is called and no `device_routines_action_skipped` event fires, even while a
pause would have reported it. The next day the conditions pass, the start runs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant
import pytest

from tests.blueprint.conftest import (
    OVERRIDE,
    PAUSED,
    Clock,
    SandboxDateTime,
    SandboxSwitch,
    inputs,
    skipped,
    sun_instant,
    sun_offset,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]
GUEST_MODE = "input_boolean.guest_mode"
ONLY_WHEN_NO_GUESTS = [{"condition": "state", "entity_id": GUEST_MODE, "state": "off"}]
SECOND = timedelta(seconds=1)


def start_of(hass: HomeAssistant, clock: Clock, kind: str, day: int) -> datetime:
    """Return when the routine's start runs on a day: 17:00, or 15 minutes before sunset."""
    if kind == "time":
        return clock.at(day, "17:00")
    return sun_instant(hass, "sunset", day, timedelta(minutes=-15))


@pytest.mark.parametrize("kind", ["time", "sunset"])
async def test_b49_only_when_blocks_a_scheduled_action_and_fires_nothing(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
    kind: str,
) -> None:
    start = {"on_time": "17:00:00"} if kind == "time" else {"on_kind": "sunset"}
    if kind == "sunset":
        start["on_sun_offset"] = sun_offset(-15)
    clock.set(clock.at(0, "12:00"))
    hass.states.async_set(GUEST_MODE, "on")
    await routine_automation(
        inputs(
            **start,
            off_time="23:00:00",
            override_entity=OVERRIDE,
            paused_until_entity=PAUSED,
            extra_conditions=ONLY_WHEN_NO_GUESTS,
        )
    )

    # Day 0: the condition fails. No action and no event.
    await clock.to(start_of(hass, clock, kind, 0) + SECOND)
    assert sandbox_switch.state_now == "off"
    assert skipped(skipped_events) == []
    # The scheduled end is not gated: a device turned on by hand still turns off.
    sandbox_switch.device_change(on=True)
    await clock.to(clock.at(0, "23:00:01"))
    assert sandbox_switch.state_now == "off"
    assert skipped(skipped_events) == []

    # Day 1, paused over the whole window: the blocked start is not reported as skipped,
    # while the end, which the conditions do not gate, is.
    paused_until.set(clock.at(1, "23:01"))
    await clock.to(start_of(hass, clock, kind, 1) + SECOND)
    assert skipped(skipped_events) == []
    await clock.to(clock.at(1, "23:00:01"))
    assert skipped(skipped_events) == [("scheduled_off", "off")]
    await clock.to(clock.at(1, "23:01"))
    paused_until.set(None)  # the integration ends the pause at the stored time
    await hass.async_block_till_done()

    # Day 2, a pause that ends inside the window: its catch up (D20) is gated too.
    paused_until.set(start_of(hass, clock, kind, 2) + timedelta(minutes=30))
    await clock.to(start_of(hass, clock, kind, 2) + timedelta(minutes=30))
    paused_until.set(None)
    await hass.async_block_till_done()
    assert sandbox_switch.state_now == "off"
    assert skipped(skipped_events) == [("scheduled_off", "off")]

    # Day 3: the condition passes, and the start runs.
    hass.states.async_set(GUEST_MODE, "off")
    await clock.to(start_of(hass, clock, kind, 3) - SECOND)
    assert sandbox_switch.state_now == "off"
    await clock.to(start_of(hass, clock, kind, 3) + SECOND)
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(3, "23:00:01"))
    assert sandbox_switch.state_now == "off"
    assert skipped(skipped_events) == [("scheduled_off", "off")]
