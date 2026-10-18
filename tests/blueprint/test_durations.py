"""Behavior matrix: Turn off after, Turn back on after and their exclusion (B09 to B18).

Rows B09 to B18 of TECH_SPEC 11.2. The countdown is a restored timer helper (PRD 9.2), so
each test asserts the device and the timer at every step; B11 and B17 start Home
Assistant over a restore cache, with time left and with a timer that ran out while Home
Assistant was down (the integration's caught up event, decision L20).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.core import Context, HomeAssistant, State
import pytest

from tests.blueprint.conftest import (
    DEVICE_ID,
    EVENT_TIMER_CAUGHT_UP,
    SWITCH,
    TIMER,
    Clock,
    Home,
    SandboxSwitch,
    inputs,
    restored_timer,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]
ColdStart = Callable[..., Awaitable[Home]]


def timer_state(hass: HomeAssistant) -> str | None:
    state = hass.states.get(TIMER)
    return None if state is None else state.state


async def turn(hass: HomeAssistant, switch: SandboxSwitch, on: bool, by: str) -> None:
    """Change the device by hand: at the wall, or from the app with a person's context."""
    if by == "wall":
        switch.device_change(on=on)
    else:
        person = await hass.auth.async_create_user("Someone at home", group_ids=[GROUP_ID_ADMIN])
        await hass.services.async_call(
            "switch",
            "turn_on" if on else "turn_off",
            {"entity_id": SWITCH},
            blocking=True,
            context=Context(user_id=person.id),
        )
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# B09 to B13: Turn off after
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("by", ["wall", "app"])
async def test_b09_turn_off_after_a_manual_on(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
    by: str,
) -> None:
    clock.set(clock.at(0, "10:00"))
    await routine_automation(inputs(timer_entity=TIMER, turn_off_after_min=30))

    await turn(hass, sandbox_switch, on=True, by=by)
    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "10:29:58"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "10:30:01"))
    assert sandbox_switch.state_now == "off"
    assert timer_state(hass) == "idle"


async def test_b10_turn_off_after_is_cancelled_by_a_manual_off(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
) -> None:
    clock.set(clock.at(0, "10:00"))
    await routine_automation(inputs(timer_entity=TIMER, turn_off_after_min=30))

    await turn(hass, sandbox_switch, on=True, by="wall")
    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "10:10"))
    await turn(hass, sandbox_switch, on=False, by="wall")
    assert timer_state(hass) == "idle"
    await clock.to(clock.at(0, "10:30:01"))
    assert sandbox_switch.state_now == "off"

    # Turning it on again starts a new countdown.
    await clock.to(clock.at(0, "10:40"))
    await turn(hass, sandbox_switch, on=True, by="wall")
    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "11:09:58"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "11:10:01"))
    assert sandbox_switch.state_now == "off"


@pytest.mark.parametrize(
    ("finishes_at", "caught_up"),
    [("10:30", False), ("10:15", True)],
    ids=["time_left", "ran_out_while_down"],
)
async def test_b11_turn_off_after_survives_a_restart(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart, finishes_at: str, caught_up: bool
) -> None:
    # FR-R3: on at 10:00, Home Assistant restarted at 10:20, the device turns off at 10:30.
    clock.set(clock.at(0, "10:20"))
    home = await cold_start(
        [State(SWITCH, "on"), restored_timer(clock.at(0, finishes_at), 30)],
        routine=inputs(timer_entity=TIMER, turn_off_after_min=30),
    )
    assert home.switch.state_now == "on"

    if caught_up:
        # The timer finished while it was added, before any trigger was armed (V10): the
        # integration reads the restore state and fires the caught up event (L20).
        assert timer_state(hass) == "idle"
        hass.bus.async_fire(EVENT_TIMER_CAUGHT_UP, {"device_id": DEVICE_ID})
        await hass.async_block_till_done()
        assert home.switch.state_now == "off"
        return

    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "10:29:58"))
    assert home.switch.state_now == "on"
    await clock.to(clock.at(0, "10:30:01"))
    assert home.switch.state_now == "off"
    assert timer_state(hass) == "idle"


async def test_b12_turn_off_after_is_not_applied_inside_an_explicit_window(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
) -> None:
    clock.set(clock.at(0, "16:40"))
    await routine_automation(
        inputs(on_time="17:00:00", off_time="23:00:00", timer_entity=TIMER, turn_off_after_min=30)
    )

    # A manual on before the window starts a countdown that would end inside it.
    await turn(hass, sandbox_switch, on=True, by="wall")
    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "17:10:01"))
    assert sandbox_switch.state_now == "on"  # the window keeps it on
    assert timer_state(hass) == "idle"

    # Off and on by hand inside the window: no countdown.
    await clock.to(clock.at(0, "18:00"))
    await turn(hass, sandbox_switch, on=False, by="wall")
    await turn(hass, sandbox_switch, on=True, by="wall")
    assert timer_state(hass) == "idle"
    await clock.to(clock.at(0, "22:59"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "23:00:01"))
    assert sandbox_switch.state_now == "off"

    # On by hand after the window: the countdown applies again.
    await clock.to(clock.at(0, "23:30"))
    await turn(hass, sandbox_switch, on=True, by="wall")
    assert timer_state(hass) == "active"
    await clock.to(clock.at(1, "00:00:01"))
    assert sandbox_switch.state_now == "off"


@pytest.mark.parametrize("already_on", [False, True])
async def test_b13_turn_off_after_applies_after_an_on_without_an_off(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
    already_on: bool,
) -> None:
    # "On at 7:00 for 30 minutes", also when the device was already on at 7:00 (no state
    # change, so only the scheduled start can start the countdown).
    clock.set(clock.at(0, "06:30"))
    if already_on:
        sandbox_switch.device_change(on=True)
    await routine_automation(inputs(on_time="07:00:00", timer_entity=TIMER, turn_off_after_min=30))
    assert timer_state(hass) == "idle"

    await clock.to(clock.at(0, "07:00:01"))
    assert sandbox_switch.state_now == "on"
    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "07:29:58"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "07:30:01"))
    assert sandbox_switch.state_now == "off"


# --------------------------------------------------------------------------------------
# B14 to B17: Turn back on after
# --------------------------------------------------------------------------------------


async def test_b14_turn_back_on_after_a_device_originated_off(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
) -> None:
    # FR-R4: a device that turns itself off at 14:00 is back on at 14:10.
    clock.set(clock.at(0, "13:00"))
    sandbox_switch.device_change(on=True)
    await routine_automation(inputs(timer_entity=TIMER, turn_back_on_after_min=10))

    await clock.to(clock.at(0, "14:00"))
    sandbox_switch.device_change(on=False)
    await hass.async_block_till_done()
    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "14:09:58"))
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(0, "14:10:01"))
    assert sandbox_switch.state_now == "on"
    assert timer_state(hass) == "idle"


async def test_b15_turn_back_on_after_never_during_a_scheduled_off(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
) -> None:
    clock.set(clock.at(0, "16:30"))
    await routine_automation(
        inputs(
            on_time="17:00:00", off_time="23:00:00", timer_entity=TIMER, turn_back_on_after_min=10
        )
    )

    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "on"
    # Inside the window an off is undone.
    await clock.to(clock.at(0, "18:00"))
    sandbox_switch.device_change(on=False)
    await hass.async_block_till_done()
    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "18:10:01"))
    assert sandbox_switch.state_now == "on"
    # The scheduled off stays off.
    await clock.to(clock.at(0, "23:00:01"))
    assert sandbox_switch.state_now == "off"
    assert timer_state(hass) == "idle"
    await clock.to(clock.at(0, "23:30"))
    assert sandbox_switch.state_now == "off"
    # And so does an off outside the window.
    sandbox_switch.device_change(on=True)
    sandbox_switch.device_change(on=False)
    await hass.async_block_till_done()
    assert timer_state(hass) == "idle"


async def test_b16_turn_back_on_after_is_cancelled_by_an_on(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
) -> None:
    clock.set(clock.at(0, "13:00"))
    sandbox_switch.device_change(on=True)
    await routine_automation(inputs(timer_entity=TIMER, turn_back_on_after_min=10))

    await clock.to(clock.at(0, "14:00"))
    sandbox_switch.device_change(on=False)
    await hass.async_block_till_done()
    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "14:05"))
    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    assert timer_state(hass) == "idle"
    await clock.to(clock.at(0, "14:10:01"))
    assert sandbox_switch.state_now == "on"
    assert timer_state(hass) == "idle"


@pytest.mark.parametrize(
    ("finishes_at", "caught_up"),
    [("14:10", False), ("14:03", True)],
    ids=["time_left", "ran_out_while_down"],
)
async def test_b17_turn_back_on_after_survives_a_restart(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart, finishes_at: str, caught_up: bool
) -> None:
    clock.set(clock.at(0, "14:05"))
    home = await cold_start(
        [State(SWITCH, "off"), restored_timer(clock.at(0, finishes_at), 10)],
        routine=inputs(timer_entity=TIMER, turn_back_on_after_min=10),
    )
    assert home.switch.state_now == "off"

    if caught_up:
        assert timer_state(hass) == "idle"
        hass.bus.async_fire(EVENT_TIMER_CAUGHT_UP, {"device_id": DEVICE_ID})
        await hass.async_block_till_done()
        assert home.switch.state_now == "on"
        return

    assert timer_state(hass) == "active"
    await clock.to(clock.at(0, "14:09:58"))
    assert home.switch.state_now == "off"
    await clock.to(clock.at(0, "14:10:01"))
    assert home.switch.state_now == "on"


async def test_the_caught_up_event_of_another_device_is_ignored(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart
) -> None:
    clock.set(clock.at(0, "14:05"))
    home = await cold_start(
        [State(SWITCH, "off"), restored_timer(clock.at(0, "14:03"), 10)],
        routine=inputs(timer_entity=TIMER, turn_back_on_after_min=10),
    )

    hass.bus.async_fire(EVENT_TIMER_CAUGHT_UP, {"device_id": "another_device"})
    await hass.async_block_till_done()

    assert home.switch.state_now == "off"


# --------------------------------------------------------------------------------------
# B18: D27, never both durations
# --------------------------------------------------------------------------------------


async def test_b18_both_durations_are_rejected(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
) -> None:
    # D27: the compiler refuses both; a hand edit that sets both starts no countdown at all.
    clock.set(clock.at(0, "10:00"))
    await routine_automation(
        inputs(timer_entity=TIMER, turn_off_after_min=30, turn_back_on_after_min=10)
    )

    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    assert timer_state(hass) == "idle"
    await clock.to(clock.at(0, "10:31"))
    assert sandbox_switch.state_now == "on"
    sandbox_switch.device_change(on=False)
    await hass.async_block_till_done()
    assert timer_state(hass) == "idle"
    await clock.to(clock.at(0, "10:42"))
    assert sandbox_switch.state_now == "off"
