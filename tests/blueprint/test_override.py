"""Behavior matrix: Manual override (B23 to B26).

The integration's attributor turns the Manual override switch on after a manual change
(lane 4); the blueprint only reads it, clears it at every scheduled time, and runs catch
up when a person clears it (PRD 9.3). Here the tests turn the stand in switch on exactly
where the attributor would, then prove what the blueprint does with it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from homeassistant.core import HomeAssistant, State

from tests.blueprint.conftest import (
    OVERRIDE,
    PAUSED,
    SWITCH,
    Clock,
    Home,
    SandboxSwitch,
    inputs,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]
ColdStart = Callable[..., Awaitable[Home]]


def window(**extra: Any) -> dict[str, Any]:
    return inputs(
        on_time="17:00:00",
        off_time="09:00:00",
        override_entity=OVERRIDE,
        paused_until_entity=PAUSED,
        **extra,
    )


async def reconnect(clock: Clock, switch: SandboxSwitch) -> None:
    """Drop the device off the network for a minute and let the 10 second debounce pass."""
    switch.set_available(False)
    await clock.advance(minutes=1)
    switch.set_available(True)
    await clock.advance(seconds=11)


async def test_b23_manual_change_sets_override_and_suppresses_catch_up(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart
) -> None:
    # FR-R6: on by hand at noon inside an off window, restarted at 12:30: it stays on.
    clock.set(clock.at(0, "12:30"))
    home = await cold_start([State(SWITCH, "on"), State(OVERRIDE, "on")], routine=window())

    assert home.switch.state_now == "on"
    assert home.override.state_now == "on"
    # A reconnect is suppressed the same way.
    await reconnect(clock, home.switch)
    assert home.switch.state_now == "on"
    # At 17:00 the routine takes over again (B24).
    await clock.to(clock.at(0, "17:00:01"))
    assert home.override.state_now == "off"
    assert home.switch.state_now == "on"


async def test_b24_a_scheduled_time_clears_override(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: Any,
) -> None:
    clock.set(clock.at(0, "12:00"))
    await routine_automation(window())

    sandbox_switch.device_change(on=True)
    override_switch.device_change(on=True)  # what the attributor does
    await clock.to(clock.at(0, "17:00:01"))
    assert override_switch.state_now == "off"
    assert sandbox_switch.state_now == "on"

    # An off by hand inside the window, override on; the scheduled end clears it too.
    await clock.to(clock.at(0, "22:00"))
    sandbox_switch.device_change(on=False)
    override_switch.device_change(on=True)
    await clock.to(clock.at(1, "09:00:01"))
    assert override_switch.state_now == "off"
    assert sandbox_switch.state_now == "off"


async def test_b25_a_person_clears_override_and_catch_up_runs(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: Any,
) -> None:
    clock.set(clock.at(0, "12:00"))
    await routine_automation(window())
    sandbox_switch.device_change(on=True)
    override_switch.device_change(on=True)
    await reconnect(clock, sandbox_switch)
    assert sandbox_switch.state_now == "on"  # held by the override

    await clock.to(clock.at(0, "12:30"))
    await hass.services.async_call("switch", "turn_off", {"entity_id": OVERRIDE}, blocking=True)
    await hass.async_block_till_done()

    assert sandbox_switch.state_now == "off"  # outside the window: catch up turned it off


async def test_b26_respect_manual_off_sets_no_override(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: Any,
) -> None:
    clock.set(clock.at(0, "12:00"))
    await routine_automation(window(respect_manual=False))

    # A manual change: with Respect manual changes off nothing sets the override (the
    # attributor skips it, the blueprint never sets it), so catch up reverts the change.
    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    assert override_switch.state_now == "off"
    await reconnect(clock, sandbox_switch)
    assert sandbox_switch.state_now == "off"
