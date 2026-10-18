"""Behavior matrix: sun relative bounds (FR-R10, decision L60), rows B47 and B48.

A bound at sunrise or sunset runs through a sun trigger carrying its side's scheduled id
and is tested in `expected_on` and the one shot late start with the `sun` condition, one
half per side with the weekday sets. The instants come from the core's astral helper for
the test instance's location (`sun_instant`), so a test follows the real sun: the times
move by a minute or so a day in late October. Monday 2026-10-19 is day 0.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from typing import Any

from homeassistant.core import Event, HomeAssistant, State
from homeassistant.util import dt as dt_util
import pytest

from tests.blueprint.conftest import (
    AUTOMATION_ID,
    DEVICE_ID,
    OVERRIDE,
    PAUSED,
    SWITCH,
    Clock,
    Home,
    SandboxDateTime,
    SandboxSwitch,
    inputs,
    skipped,
    sun_instant,
    sun_offset,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]
ColdStart = Callable[..., Awaitable[Home]]
SECOND = timedelta(seconds=1)
WEEKDAYS_ONLY = ["mon", "tue", "wed", "thu", "fri"]


def switch_changes(hass: HomeAssistant) -> list[str]:
    """Record every state the sandbox switch takes from now on."""
    changes: list[str] = []

    def remember(event: Event) -> None:
        if event.data["entity_id"] == SWITCH and event.data["new_state"] is not None:
            old = event.data["old_state"]
            if old is None or old.state != event.data["new_state"].state:
                changes.append(event.data["new_state"].state)

    hass.bus.async_listen("state_changed", remember)
    return changes


def sun_window(**extra: Any) -> dict[str, Any]:
    """On 30 minutes after sunrise, off 30 minutes before sunset, every day."""
    return inputs(
        on_kind="sunrise",
        on_sun_offset=sun_offset(30),
        off_kind="sunset",
        off_sun_offset=sun_offset(-30),
        **extra,
    )


def night_window(**extra: Any) -> dict[str, Any]:
    """On at sunset, off at sunrise, on weekdays: a window crossing midnight."""
    return inputs(on_kind="sunset", off_kind="sunrise", days_start=WEEKDAYS_ONLY, **extra)


# --------------------------------------------------------------------------------------
# B47: a window between two sun bounds
# --------------------------------------------------------------------------------------


async def test_b47_sun_window_on_and_off(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    routine = sun_window()
    assert not routine["crosses_midnight"]
    assert (routine["on_time_enabled"], routine["off_time_enabled"]) == (False, False)
    clock.set(clock.at(0, "04:00"))
    await routine_automation(routine)
    changes = switch_changes(hass)

    for day in range(3):
        on_at = sun_instant(hass, "sunrise", day, timedelta(minutes=30))
        off_at = sun_instant(hass, "sunset", day, timedelta(minutes=-30))
        await clock.to(on_at - SECOND)
        assert sandbox_switch.state_now == "off", day
        await clock.to(on_at + SECOND)
        assert sandbox_switch.state_now == "on", day
        await clock.to(off_at - SECOND)
        assert sandbox_switch.state_now == "on", day
        await clock.to(off_at + SECOND)
        assert sandbox_switch.state_now == "off", day

    # The instants follow the real sun, not a fixed time: they moved between the days.
    assert sun_instant(hass, "sunrise", 2).time() != sun_instant(hass, "sunrise", 0).time()
    assert changes == ["on", "off"] * 3


@pytest.mark.parametrize(
    ("event", "minutes", "restored", "expected"),
    [
        ("sunrise", 40, "off", "on"),  # ten minutes into the window
        ("sunset", -40, "off", "on"),  # ten minutes before it ends
        ("sunrise", 20, "on", "off"),  # ten minutes before it starts
        ("sunset", -20, "on", "off"),  # ten minutes after it ended
    ],
    ids=["after_the_start", "before_the_end", "before_the_start", "after_the_end"],
)
async def test_b47_catch_up_on_start_follows_the_sun_window(
    hass: HomeAssistant,
    clock: Clock,
    cold_start: ColdStart,
    event: str,
    minutes: int,
    restored: str,
    expected: str,
) -> None:
    clock.set(sun_instant(hass, event, 1, timedelta(minutes=minutes)))

    home = await cold_start([State(SWITCH, restored)], routine=sun_window())

    assert home.switch.state_now == expected
    await clock.advance(minutes=1)
    assert home.switch.state_now == expected


# --------------------------------------------------------------------------------------
# B48: sunset to sunrise, across midnight, and a one shot sun start
# --------------------------------------------------------------------------------------


async def test_b48_sunset_to_sunrise_across_midnight(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    # Nominal sunset 18:00 is later than nominal sunrise 06:00: the window crosses midnight
    # and belongs to the day it starts on (L60).
    routine = night_window()
    assert routine["crosses_midnight"]
    assert routine["days_end"] == ["tue", "wed", "thu", "fri", "sat"]
    clock.set(clock.at(4, "12:00"))  # Friday
    await routine_automation(routine)

    friday_sunset = sun_instant(hass, "sunset", 4)
    await clock.to(friday_sunset - SECOND)
    assert sandbox_switch.state_now == "off"
    await clock.to(friday_sunset + SECOND)
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(5, "02:00"))
    assert sandbox_switch.state_now == "on"
    saturday_sunrise = sun_instant(hass, "sunrise", 5)
    await clock.to(saturday_sunrise - SECOND)
    assert sandbox_switch.state_now == "on"
    await clock.to(saturday_sunrise + SECOND)  # Saturday's sunrise ends Friday's window
    assert sandbox_switch.state_now == "off"
    await clock.to(sun_instant(hass, "sunset", 5) + SECOND)  # Saturday is not a start day
    assert sandbox_switch.state_now == "off"

    # Nor does Sunday's sunrise end anything: a device turned on by hand stays on.
    await clock.to(clock.at(5, "22:00"))
    sandbox_switch.device_change(on=True)
    await clock.to(sun_instant(hass, "sunrise", 6) + SECOND)
    assert sandbox_switch.state_now == "on"
    sandbox_switch.device_change(on=False)
    await clock.to(sun_instant(hass, "sunset", 6) + SECOND)  # nor is Sunday a start day
    assert sandbox_switch.state_now == "off"
    await clock.to(sun_instant(hass, "sunset", 7) + SECOND)  # Monday is
    assert sandbox_switch.state_now == "on"


@pytest.mark.parametrize(
    ("day", "restored", "expected"),
    [(5, "off", "on"), (6, "off", "off"), (6, "on", "off")],
    ids=["saturday_inside_fridays_window", "sunday_no_window", "sunday_turns_off"],
)
async def test_b48_catch_up_across_midnight_follows_the_start_day(
    hass: HomeAssistant,
    clock: Clock,
    cold_start: ColdStart,
    day: int,
    restored: str,
    expected: str,
) -> None:
    # 02:00 on Saturday is inside Friday's window; 02:00 on Sunday is inside no window,
    # because Saturday is not a start day.
    clock.set(clock.at(day, "02:00"))

    home = await cold_start([State(SWITCH, restored)], routine=night_window())

    assert home.switch.state_now == expected


@pytest.mark.parametrize(
    ("minutes", "late_by", "expected"),
    [(30, 10, "on"), (30, 20, "off"), (-30, 10, "on"), (-30, 20, "off")],
    ids=["after_inside", "after_outside", "before_inside", "before_outside"],
)
async def test_b48_one_shot_sun_start_late_window(
    hass: HomeAssistant,
    clock: Clock,
    cold_start: ColdStart,
    minutes: int,
    late_by: int,
    expected: str,
) -> None:
    # A sun start with no end: a start missed by up to the late start window (15 minutes)
    # still runs after a restart, one missed by more waits for the next day.
    routine = inputs(on_kind="sunrise", on_sun_offset=sun_offset(minutes))
    assert routine["late_sun_offset"] == sun_offset(minutes + 15)
    start = sun_instant(hass, "sunrise", 0, timedelta(minutes=minutes))
    clock.set(start + timedelta(minutes=late_by))

    home = await cold_start([State(SWITCH, "off")], routine=routine)

    assert home.switch.state_now == expected
    if expected == "on":
        return
    tomorrow = sun_instant(hass, "sunrise", 1, timedelta(minutes=minutes))
    await clock.to(tomorrow - SECOND)
    assert home.switch.state_now == "off"
    await clock.to(tomorrow + SECOND)
    assert home.switch.state_now == "on"


async def test_b48_a_zero_late_start_window_means_no_late_sun_start(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart
) -> None:
    routine = inputs(on_kind="sunset", late_start_window_min=0)
    assert routine["late_sun_offset"] == routine["on_sun_offset"] == "00:00:00"
    clock.set(sun_instant(hass, "sunset", 0, timedelta(minutes=1)))

    home = await cold_start([State(SWITCH, "off")], routine=routine)

    assert home.switch.state_now == "off"


# --------------------------------------------------------------------------------------
# Skip next on a sun start (FR-R11 with FR-R10)
# --------------------------------------------------------------------------------------


async def test_skip_next_on_a_sun_start_fires_the_skipped_event(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    skipped_events: list[Event],
) -> None:
    # On 15 minutes after sunset, off at 23:00: at 15:00 Skip next skips tonight's start and
    # its paired end (D18), until a minute after the end.
    clock.set(clock.at(0, "15:00"))
    await routine_automation(
        inputs(
            on_kind="sunset",
            on_sun_offset=sun_offset(15),
            off_time="23:00:00",
            override_entity=OVERRIDE,
            paused_until_entity=PAUSED,
        )
    )
    paused_until.set(clock.at(0, "23:01"))
    await hass.async_block_till_done()

    start = sun_instant(hass, "sunset", 0, timedelta(minutes=15))
    await clock.to(start + SECOND)
    assert sandbox_switch.state_now == "off"
    assert skipped(skipped_events) == [("scheduled_on", "on")]
    first = skipped_events[0].data
    assert (first["device_id"], first["automation_id"]) == (DEVICE_ID, AUTOMATION_ID)
    scheduled_at = dt_util.parse_datetime(first["scheduled_at"])
    assert scheduled_at is not None
    assert abs(scheduled_at - start) < 2 * SECOND

    await clock.to(clock.at(0, "23:00:01"))
    assert skipped(skipped_events) == [("scheduled_on", "on"), ("scheduled_off", "off")]
    await clock.to(clock.at(0, "23:01"))
    paused_until.set(None)  # the integration ends the skip at the stored time
    await hass.async_block_till_done()
    assert sandbox_switch.state_now == "off"
    await clock.to(sun_instant(hass, "sunset", 1, timedelta(minutes=15)) + SECOND)
    assert sandbox_switch.state_now == "on"
