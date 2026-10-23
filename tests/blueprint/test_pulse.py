"""Behavior matrix: Pulse (B37, B38).

FR-R8: at a time, the opposite state for N minutes, then back, only if the device has been
steady for the minimum. The pulse waits with a `delay` on purpose (TECH_SPEC 5.5), so the
clock settles by yielding while the run sits in it: `async_block_till_done` would wait for
the delay and hang. B38 restarts in the middle of a pulse and lets catch up repair it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from homeassistant.core import Event, HomeAssistant, State
import pytest

from tests.blueprint.conftest import (
    HARNESS_START,
    OVERRIDE,
    PAUSED,
    SWITCH,
    Clock,
    Home,
    SandboxDateTime,
    SandboxSwitch,
    inputs,
    skipped,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]
ColdStart = Callable[..., Awaitable[Home]]


@pytest.mark.parametrize(
    ("start_on", "during", "after"),
    [(True, "off", "on"), (False, "on", "off")],
    ids=["on_device", "off_device"],
)
async def test_b37_pulse(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    start_on: bool,
    during: str,
    after: str,
) -> None:
    # FR-R8: fan on since 06:00; at 08:00 it is off for 3 minutes, then on.
    clock.set(clock.at(0, "06:00"))
    sandbox_switch.device_change(on=start_on)
    await routine_automation(inputs(pulse_at="08:00:00"))
    before = "on" if start_on else "off"

    await clock.to(clock.at(0, "07:59"))
    assert sandbox_switch.state_now == before
    await clock.to(clock.at(0, "08:00:01"), settle="yield")
    assert sandbox_switch.state_now == during
    await clock.to(clock.at(0, "08:02:58"), settle="yield")
    assert sandbox_switch.state_now == during
    await clock.to(clock.at(0, "08:03:02"), settle="yield")
    await hass.async_block_till_done()
    assert sandbox_switch.state_now == after


async def test_a_fixture_entity_is_created_at_the_harness_start(
    hass: HomeAssistant, sandbox_switch: SandboxSwitch
) -> None:
    """The off device of B37 has been off since its creation, which must not be today.

    A fixture entity created at the real date would carry a `last_changed` after the test
    week once that date passes it, and the pulse's steady check would refuse.
    """
    state = hass.states.get(SWITCH)
    assert state is not None
    assert state.state == "off"
    assert state.last_changed == HARNESS_START


async def test_b37_no_pulse_unless_steady(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    clock.set(clock.at(0, "06:00"))
    sandbox_switch.device_change(on=True)
    await routine_automation(inputs(pulse_at="08:00:00"))

    await clock.to(clock.at(0, "07:58"))
    sandbox_switch.device_change(on=False)
    sandbox_switch.device_change(on=True)  # changed two minutes before the pulse
    await clock.to(clock.at(0, "08:00:01"), settle="yield")
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "08:04"))
    assert sandbox_switch.state_now == "on"


async def test_a_pulse_while_paused_is_reported(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
) -> None:
    clock.set(clock.at(0, "06:00"))
    sandbox_switch.device_change(on=True)
    await routine_automation(
        inputs(pulse_at="08:00:00", paused_until_entity=PAUSED, override_entity=OVERRIDE)
    )
    paused_until.set(clock.at(0, "09:00"))

    await clock.to(clock.at(0, "08:00:01"))

    assert sandbox_switch.state_now == "on"
    assert skipped(skipped_events) == [("pulse", "pulse")]


async def test_b38_pulse_interrupted_by_a_restart_is_repaired_by_catch_up(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart
) -> None:
    # The 08:00 pulse turned the device off, and Home Assistant went down at 08:01 with
    # the run in its delay: the run is gone. Catch up at the start restores the window.
    clock.set(clock.at(0, "08:02"))

    home = await cold_start(
        [State(SWITCH, "off")],
        routine=inputs(on_time="06:00:00", off_time="22:00:00", pulse_at="08:00:00"),
    )

    assert home.switch.state_now == "on"
    await clock.to(clock.at(0, "21:59"))
    assert home.switch.state_now == "on"
    await clock.to(clock.at(0, "22:00:01"))
    assert home.switch.state_now == "off"
