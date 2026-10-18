"""Behavior matrix: pause, skip, resume and the routine switch (B27 to B36).

Paused until is one stored value per device (PRD 5.5). The integration computes skip
targets, sets the value, cancels a skipped countdown and, at the stored end, resumes by
setting the value to now (decision L22: the blueprint has no pause end trigger). Here the
tests do exactly those writes on the stand in entity and prove what the blueprint does:
not_paused blocks every scheduled and countdown action and reports each skip, a pause
pauses and resumes the countdown, and the end of a pause catches up (D20).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant
from homeassistant.util import dt as dt_util
import pytest

from tests.blueprint.conftest import (
    AUTOMATION,
    AUTOMATION_ID,
    DEVICE_ID,
    EVENT_TIMER_CAUGHT_UP,
    OVERRIDE,
    PAUSED,
    TIMER,
    Clock,
    SandboxDateTime,
    SandboxSwitch,
    inputs,
    skipped,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]


def timer(hass: HomeAssistant) -> tuple[str | None, str | None]:
    state = hass.states.get(TIMER)
    if state is None:
        return None, None
    return state.state, state.attributes.get("remaining")


def routine(**extra: Any) -> dict[str, Any]:
    return inputs(paused_until_entity=PAUSED, override_entity=OVERRIDE, **extra)


async def resume(hass: HomeAssistant, paused: SandboxDateTime) -> None:
    """What the integration does at the stored end: it clears the value (TECH_SPEC 5.5).

    Setting the value to now at the stored second would write the same state, which is
    no state change at all, so the routine would never hear that the pause ended.
    """
    paused.set(None)
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# B27 to B30: pause and resume
# --------------------------------------------------------------------------------------


async def test_b27_pause_blocks_scheduled_actions_and_fires_the_event(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
) -> None:
    clock.set(clock.at(0, "15:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="09:00:00"))
    paused_until.set(clock.at(1, "10:00"))
    await hass.async_block_till_done()

    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "off"
    sandbox_switch.device_change(on=True)  # a person may still use it
    await clock.to(clock.at(1, "09:00:01"))
    assert sandbox_switch.state_now == "on"

    assert skipped(skipped_events) == [("scheduled_on", "on"), ("scheduled_off", "off")]
    first = skipped_events[0].data
    assert first["device_id"] == DEVICE_ID
    assert first["automation_id"] == AUTOMATION_ID
    assert dt_util.parse_datetime(first["scheduled_at"]) is not None
    assert abs(
        dt_util.parse_datetime(first["scheduled_at"]) - clock.at(0, "17:00")  # type: ignore[operator]
    ) < timedelta(seconds=2)


async def test_b27_pause_blocks_countdown_actions_and_fires_the_event(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    routine_timer: str,
    skipped_events: list[Event],
) -> None:
    clock.set(clock.at(0, "10:00"))
    await routine_automation(routine(timer_entity=TIMER, turn_off_after_min=30))
    paused_until.set(clock.at(0, "12:00"))
    await hass.async_block_till_done()

    # No countdown starts while paused.
    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    assert timer(hass)[0] == "idle"
    # A countdown that finishes while paused does not act and is reported.
    hass.bus.async_fire(EVENT_TIMER_CAUGHT_UP, {"device_id": DEVICE_ID})
    await hass.async_block_till_done()
    assert sandbox_switch.state_now == "on"
    assert skipped(skipped_events) == [("timer_done", "off")]


async def test_b28_pause_pauses_and_resumes_a_running_countdown_with_the_time_left(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    routine_timer: str,
) -> None:
    clock.set(clock.at(0, "10:00"))
    await routine_automation(routine(timer_entity=TIMER, turn_off_after_min=30))
    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    assert timer(hass)[0] == "active"

    await clock.to(clock.at(0, "10:10"))
    paused_until.set(clock.at(0, "10:40"))
    await hass.async_block_till_done()
    assert timer(hass) == ("paused", "0:20:00")
    await clock.to(clock.at(0, "10:39"))
    assert sandbox_switch.state_now == "on"

    await clock.to(clock.at(0, "10:40"))
    await resume(hass, paused_until)
    assert timer(hass)[0] == "active"
    await clock.to(clock.at(0, "10:59:58"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "11:00:01"))
    assert sandbox_switch.state_now == "off"


async def test_b29_pause_end_catches_up(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
) -> None:
    clock.set(clock.at(0, "16:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="23:00:00"))
    paused_until.set(clock.at(0, "18:00"))
    await hass.async_block_till_done()

    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "off"
    assert skipped(skipped_events) == [("scheduled_on", "on")]

    # D20: at the stored end, inside the window, the device takes the window's state.
    await clock.to(clock.at(0, "18:00"))
    await resume(hass, paused_until)
    assert sandbox_switch.state_now == "on"


@pytest.mark.parametrize("how", ["now", "cleared"])
async def test_b30_resume_ends_the_pause_and_catches_up(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    how: str,
) -> None:
    clock.set(clock.at(0, "16:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="23:00:00"))
    paused_until.set(clock.at(1, "08:00"))
    await clock.to(clock.at(0, "17:30"))
    assert sandbox_switch.state_now == "off"

    # Resume before the stored end: the value becomes now (PRD 9.5), or is cleared.
    paused_until.set(dt_util.utcnow() if how == "now" else None)
    await hass.async_block_till_done()

    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "23:00:01"))
    assert sandbox_switch.state_now == "off"


async def test_setting_paused_until_to_its_own_stored_instant_is_not_heard(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
) -> None:
    # A note for the manager (lane 5): at the stored end, "set the value to now" writes
    # the state the entity already has, so no trigger fires and D20 never runs. Clearing
    # the value (TECH_SPEC 5.5) is what ends a pause at its stored time.
    clock.set(clock.at(0, "16:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="23:00:00"))
    paused_until.set(clock.at(0, "18:00"))
    await clock.to(clock.at(0, "18:00"))

    paused_until.set(dt_util.utcnow())
    await hass.async_block_till_done()

    assert sandbox_switch.state_now == "off"


async def test_a_resume_while_a_manual_override_holds_does_not_catch_up(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
) -> None:
    clock.set(clock.at(0, "16:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="23:00:00"))
    override_switch.device_change(on=True)
    paused_until.set(clock.at(0, "18:00"))
    await clock.to(clock.at(0, "18:00"))

    await resume(hass, paused_until)

    assert sandbox_switch.state_now == "off"


async def test_catch_up_off_leaves_the_pause_end_alone(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
) -> None:
    clock.set(clock.at(0, "16:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="23:00:00", catch_up=False))
    paused_until.set(clock.at(0, "18:00"))
    await clock.to(clock.at(0, "18:00"))

    await resume(hass, paused_until)

    assert sandbox_switch.state_now == "off"


# --------------------------------------------------------------------------------------
# B31 to B34: skip next
# --------------------------------------------------------------------------------------


async def test_b31_skip_next_on_a_window_start_skips_both_ends(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
) -> None:
    # FR-R11 and D18: at 15:00 with a 17:00 to 09:00 window, Skip next leaves it off tonight.
    clock.set(clock.at(0, "15:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="09:00:00"))
    paused_until.set(clock.at(1, "09:01"))  # one minute after the paired end

    await clock.to(clock.at(1, "09:01"))
    assert sandbox_switch.state_now == "off"
    assert skipped(skipped_events) == [("scheduled_on", "on"), ("scheduled_off", "off")]
    await resume(hass, paused_until)
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(1, "17:00:01"))
    assert sandbox_switch.state_now == "on"


@pytest.mark.parametrize("override_set", [True, False])
async def test_b32_skip_next_on_a_window_end(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
    override_set: bool,
) -> None:
    # D19: at 20:00 inside a 17:00 to 09:00 window, Skip next skips the 09:00 off alone.
    clock.set(clock.at(0, "16:30"))
    await routine_automation(routine(on_time="17:00:00", off_time="09:00:00"))
    await clock.to(clock.at(0, "20:00"))
    assert sandbox_switch.state_now == "on"
    paused_until.set(clock.at(1, "09:01"))
    if override_set:
        override_switch.device_change(on=True)

    await clock.to(clock.at(1, "09:00:01"))
    assert sandbox_switch.state_now == "on"
    assert skipped(skipped_events) == [("scheduled_off", "off")]
    await clock.to(clock.at(1, "09:01"))
    await resume(hass, paused_until)

    if not override_set:
        # D20: the end of the skip catches up like a restart, so the skipped off applies
        # one minute late. Holding the device "as is until the following action" needs
        # the Manual override (FR-R6), which the next scheduled time clears.
        assert sandbox_switch.state_now == "off"
        return
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(1, "17:00:01"))
    assert override_switch.state_now == "off"
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(2, "09:00:01"))
    assert sandbox_switch.state_now == "off"


async def test_b33_skip_next_on_a_running_countdown(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    routine_timer: str,
) -> None:
    clock.set(clock.at(0, "10:00"))
    await routine_automation(routine(timer_entity=TIMER, turn_off_after_min=30))
    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    assert timer(hass)[0] == "active"

    # The integration cancels the countdown and skips until a minute after its end.
    await clock.to(clock.at(0, "10:10"))
    await hass.services.async_call("timer", "cancel", {"entity_id": TIMER}, blocking=True)
    paused_until.set(clock.at(0, "10:31"))
    await hass.async_block_till_done()
    assert timer(hass)[0] == "idle"

    await clock.to(clock.at(0, "10:31"))
    assert sandbox_switch.state_now == "on"
    await resume(hass, paused_until)
    await clock.to(clock.at(0, "11:30"))
    assert sandbox_switch.state_now == "on"
    assert timer(hass)[0] == "idle"


async def test_b34_pressing_skip_next_twice_extends_the_skip(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
) -> None:
    clock.set(clock.at(0, "15:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="09:00:00"))
    paused_until.set(clock.at(1, "09:01"))
    await hass.async_block_till_done()
    await clock.advance(minutes=1)
    paused_until.set(clock.at(2, "09:01"))  # the following start and its paired end

    await clock.to(clock.at(2, "09:01"))
    assert sandbox_switch.state_now == "off"
    assert skipped(skipped_events) == [
        ("scheduled_on", "on"),
        ("scheduled_off", "off"),
        ("scheduled_on", "on"),
        ("scheduled_off", "off"),
    ]
    await resume(hass, paused_until)
    await clock.to(clock.at(2, "17:00:01"))
    assert sandbox_switch.state_now == "on"


# --------------------------------------------------------------------------------------
# B35, B36: manual changes while paused, the routine switch
# --------------------------------------------------------------------------------------


async def test_b35_manual_change_while_paused_sets_no_override(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    routine_timer: str,
) -> None:
    clock.set(clock.at(0, "11:00"))
    await routine_automation(
        routine(on_time="17:00:00", off_time="23:00:00", timer_entity=TIMER, turn_off_after_min=30)
    )
    paused_until.set(clock.at(0, "14:00"))

    # D21: the change is allowed, starts no countdown and sets no override.
    await clock.to(clock.at(0, "12:00"))
    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    assert override_switch.state_now == "off"
    assert timer(hass)[0] == "idle"
    await clock.to(clock.at(0, "13:59"))
    assert sandbox_switch.state_now == "on"

    # With no override, the end of the pause catches up (D20).
    await clock.to(clock.at(0, "14:00"))
    await resume(hass, paused_until)
    assert sandbox_switch.state_now == "off"


async def test_b36_routine_off_runs_nothing_and_keeps_the_pause(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
) -> None:
    clock.set(clock.at(0, "15:00"))
    await routine_automation(routine(on_time="17:00:00", off_time="23:00:00"))
    paused_until.set(clock.at(1, "10:00"))
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": AUTOMATION}, blocking=True
    )

    await clock.to(clock.at(0, "17:00:01"))
    assert skipped(skipped_events) == []  # nothing runs, not even the skip report
    sandbox_switch.device_change(on=True)

    # Back on before the pause ends: the stored value applies again.
    await clock.to(clock.at(0, "18:00"))
    await hass.services.async_call(
        "automation", "turn_on", {"entity_id": AUTOMATION}, blocking=True
    )
    paused = hass.states.get(PAUSED)
    assert paused is not None
    assert dt_util.parse_datetime(paused.state) == clock.at(1, "10:00")
    await clock.to(clock.at(0, "23:00:01"))
    assert sandbox_switch.state_now == "on"
    assert skipped(skipped_events) == [("scheduled_off", "off")]

    # Without anyone resuming, the pause still ends: the next scheduled time runs.
    await clock.to(clock.at(1, "17:00:01"))
    await clock.to(clock.at(1, "23:00:01"))
    assert sandbox_switch.state_now == "off"
