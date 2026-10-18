"""Behavior matrix: windows, weekly schedules, one shot starts, catch up, DST and bursts.

Rows B01 to B08, B19 to B22 and B40 to B42 of TECH_SPEC 11.2. Every test drives the real
blueprint through time travel; B19, B21, B22 and B41 start Home Assistant over a restore
cache. Monday 2026-10-19 is day 0 unless a test says otherwise.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.vacuum.const import VacuumActivity
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.util import dt as dt_util
import pytest

from tests.blueprint.conftest import (
    AUTOMATION,
    SCHEDULE,
    SWITCH,
    TIMER,
    VACUUM,
    Blocks,
    Clock,
    Home,
    SandboxSwitch,
    SandboxVacuum,
    inputs,
    target_inputs,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]
ColdStart = Callable[..., Awaitable[Home]]
LOS_ANGELES = ZoneInfo("America/Los_Angeles")


def state_of(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    return None if state is None else state.state


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


# --------------------------------------------------------------------------------------
# B01 to B05: windows and days
# --------------------------------------------------------------------------------------


async def test_b01_window_on_and_off_the_same_day(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    clock.set(clock.at(0, "08:00"))
    await routine_automation(inputs(on_time="09:00:00", off_time="17:00:00"))

    await clock.to(clock.at(0, "08:59:59"))
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(0, "09:00:01"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "16:59:59"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(1, "09:00:01"))
    assert sandbox_switch.state_now == "on"


async def test_b02_window_crossing_midnight(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    clock.set(clock.at(0, "12:00"))
    await routine_automation(inputs(on_time="17:00:00", off_time="09:00:00"))

    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(1, "00:30"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(1, "08:59:59"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(1, "09:00:01"))
    assert sandbox_switch.state_now == "off"


async def test_b03_crossing_window_with_weekdays_follows_the_start_day(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    # Weekdays 17:00 to 09:00: the window belongs to the day it starts on.
    clock.set(clock.at(4, "16:00"))  # Friday
    await routine_automation(
        inputs(
            on_time="17:00:00", off_time="09:00:00", days_start=["mon", "tue", "wed", "thu", "fri"]
        )
    )

    await clock.to(clock.at(4, "17:00:01"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(5, "09:00:01"))  # Saturday morning ends Friday's window
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(5, "17:00:01"))  # Saturday is not a start day
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(6, "17:00:01"))  # nor is Sunday
    assert sandbox_switch.state_now == "off"

    # Monday 08:00 is off: Sunday is not a start day. A catch up on reconnect agrees.
    await clock.to(clock.at(7, "07:00"))
    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    sandbox_switch.set_available(False)
    await clock.to(clock.at(7, "07:30"))
    sandbox_switch.set_available(True)
    await clock.to(clock.at(7, "07:30:11"))
    assert sandbox_switch.state_now == "off"

    # Tuesday 08:00 is inside Monday's window: the same catch up turns the device on.
    await clock.to(clock.at(8, "07:00"))
    sandbox_switch.device_change(on=False)
    await hass.async_block_till_done()
    sandbox_switch.set_available(False)
    await clock.to(clock.at(8, "07:30"))
    sandbox_switch.set_available(True)
    await clock.to(clock.at(8, "07:30:11"))
    assert sandbox_switch.state_now == "on"


async def test_b04_weekends_only(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    clock.set(clock.at(4, "09:00"))  # Friday
    await routine_automation(
        inputs(on_time="10:00:00", off_time="12:00:00", days_start=["sat", "sun"])
    )

    await clock.to(clock.at(4, "10:00:01"))
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(5, "10:00:01"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(5, "12:00:01"))
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(6, "10:00:01"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(6, "12:00:01"))
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(7, "10:00:01"))  # Monday
    assert sandbox_switch.state_now == "off"


async def test_b05_some_days(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    clock.set(clock.at(0, "09:00"))
    await routine_automation(
        inputs(on_time="10:00:00", off_time="12:00:00", days_start=["mon", "wed", "fri"])
    )

    expected = {0: "on", 1: "off", 2: "on", 3: "off", 4: "on", 5: "off"}
    for day, state in expected.items():
        await clock.to(clock.at(day, "10:00:01"))
        assert sandbox_switch.state_now == state, day
        await clock.to(clock.at(day, "12:00:01"))
        assert sandbox_switch.state_now == "off", day


# --------------------------------------------------------------------------------------
# B06, B07: weekly schedule blocks
# --------------------------------------------------------------------------------------


async def test_b06_weekly_schedule_blocks(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    routine_schedule: Callable[[Blocks], Awaitable[str]],
    sandbox_switch: SandboxSwitch,
) -> None:
    clock.set(clock.at(0, "16:00"))
    await routine_schedule(
        {"monday": [("17:00:00", "22:00:00")], "tuesday": [("08:00:00", "09:00:00")]}
    )
    await routine_automation(inputs(schedule_entity=SCHEDULE))

    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "22:00:01"))
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(1, "07:59"))
    assert sandbox_switch.state_now == "off"
    await clock.to(clock.at(1, "08:00:01"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(1, "09:00:01"))
    assert sandbox_switch.state_now == "off"


async def test_b07_adjacent_blocks_at_midnight_produce_no_blip(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    routine_schedule: Callable[[Blocks], Awaitable[str]],
    sandbox_switch: SandboxSwitch,
) -> None:
    clock.set(clock.at(0, "21:00"))
    await routine_schedule(
        {"monday": [("22:00:00", "24:00:00")], "tuesday": [("00:00:00", "02:00:00")]}
    )
    await routine_automation(inputs(schedule_entity=SCHEDULE))
    changes = switch_changes(hass)

    await clock.to(clock.at(0, "22:00:01"))
    assert changes == ["on"]
    await clock.to(clock.at(0, "23:59:30"))
    await clock.to(clock.at(1, "00:00:30"))
    await clock.to(clock.at(1, "01:59"))
    # A6: the schedule stays on across midnight, so the routine never cycles the device.
    assert changes == ["on"]
    await clock.to(clock.at(1, "02:00:01"))
    assert changes == ["on", "off"]


# --------------------------------------------------------------------------------------
# B08: one shot start with the docked guard
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("docked_guard", "starts_away_from_dock"), [(True, False), (False, True)])
async def test_b08_one_shot_start_with_the_docked_guard(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_vacuum: SandboxVacuum,
    docked_guard: bool,
    starts_away_from_dock: bool,
) -> None:
    clock.set(clock.at(0, "09:00"))
    await routine_automation(
        inputs(**target_inputs("vacuum", VACUUM), on_time="09:45:00", docked_guard=docked_guard)
    )

    # Docked at 09:45: the start runs.
    await clock.to(clock.at(0, "09:45:01"))
    assert state_of(hass, VACUUM) == "cleaning"
    # A start with no end leaves the run to the vacuum.
    sandbox_vacuum.device_change(VacuumActivity.DOCKED)
    await clock.to(clock.at(0, "23:00"))
    assert state_of(hass, VACUUM) == "docked"

    # Left in the middle of the room the next morning: the guard holds the start.
    sandbox_vacuum.device_change(VacuumActivity.IDLE)
    await clock.to(clock.at(1, "09:45:01"))
    assert state_of(hass, VACUUM) == ("cleaning" if starts_away_from_dock else "idle")


# --------------------------------------------------------------------------------------
# B19 to B22: catch up
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("restart_at", "restored", "expected"),
    [("17:10", "off", "on"), ("12:00", "on", "off")],
    ids=["inside_the_window", "outside_the_window"],
)
async def test_b19_catch_up_on_start_inside_a_window(
    hass: HomeAssistant,
    clock: Clock,
    cold_start: ColdStart,
    restart_at: str,
    restored: str,
    expected: str,
) -> None:
    # FR-R5: down from 16:55 to 17:10 with a 17:00 on time; on by 17:11.
    clock.set(clock.at(0, restart_at))

    home = await cold_start(
        [State(SWITCH, restored)], routine=inputs(on_time="17:00:00", off_time="23:00:00")
    )

    assert home.switch.state_now == expected
    await clock.advance(minutes=1)
    assert home.switch.state_now == expected


async def test_b20_catch_up_on_reconnect(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    clock.set(clock.at(0, "16:50"))
    await routine_automation(inputs(on_time="17:00:00", off_time="23:00:00"))

    sandbox_switch.set_available(False)
    await clock.to(clock.at(0, "17:00:01"))
    # The scheduled on found the device unavailable and did not call it.
    assert sandbox_switch.state_now == "unavailable"
    await clock.to(clock.at(0, "17:05"))
    sandbox_switch.set_available(True)
    await clock.to(clock.at(0, "17:05:05"))
    assert sandbox_switch.state_now == "off"  # the 10 second debounce
    await clock.to(clock.at(0, "17:05:11"))
    assert sandbox_switch.state_now == "on"


async def test_b21_one_shot_late_start_inside_the_window(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart
) -> None:
    clock.set(clock.at(0, "09:50"))  # down from 09:40, the 09:45 start was missed

    await cold_start(
        [State(VACUUM, "docked")],
        routine=inputs(**target_inputs("vacuum", VACUUM), on_time="09:45:00"),
        vacuum=True,
    )

    assert state_of(hass, VACUUM) == "cleaning"


async def test_b22_one_shot_outside_the_window_waits(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart
) -> None:
    clock.set(clock.at(0, "10:05"))  # 20 minutes late, the window is 15

    await cold_start(
        [State(VACUUM, "docked")],
        routine=inputs(**target_inputs("vacuum", VACUUM), on_time="09:45:00"),
        vacuum=True,
    )

    assert state_of(hass, VACUUM) == "docked"
    await clock.to(clock.at(1, "09:44"))
    assert state_of(hass, VACUUM) == "docked"
    await clock.to(clock.at(1, "09:45:01"))
    assert state_of(hass, VACUUM) == "cleaning"


async def test_b22_a_zero_late_start_window_means_no_late_start(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart
) -> None:
    # With 0 the compiler emits late_window_end equal to on_time, and a core time condition
    # with equal after and before is always true: the branch is switched off instead.
    clock.set(clock.at(0, "09:46"))
    routine = inputs(**target_inputs("vacuum", VACUUM), on_time="09:45:00", late_start_window_min=0)
    assert routine["late_window_end"] == routine["on_time"]

    await cold_start([State(VACUUM, "docked")], routine=routine, vacuum=True)

    assert state_of(hass, VACUUM) == "docked"


# --------------------------------------------------------------------------------------
# B40, B41: daylight saving (decision L21)
# --------------------------------------------------------------------------------------


async def test_b40_dst_spring_forward_skips_a_time_in_the_missing_hour(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    clock.set(datetime(2026, 3, 7, 23, 0, tzinfo=LOS_ANGELES))
    await routine_automation(inputs(on_time="02:30:00", off_time="06:00:00"))
    changes = switch_changes(hass)

    # 02:30 does not exist on 2026-03-08: the window does not start that night (L21).
    await clock.to(datetime(2026, 3, 8, 7, 0, tzinfo=LOS_ANGELES))
    assert changes == []
    assert sandbox_switch.state_now == "off"
    # The next night runs as usual.
    await clock.to(datetime(2026, 3, 9, 2, 30, 1, tzinfo=LOS_ANGELES))
    assert sandbox_switch.state_now == "on"
    await clock.to(datetime(2026, 3, 9, 6, 0, 1, tzinfo=LOS_ANGELES))
    assert changes == ["on", "off"]


async def test_b41_dst_fall_back_runs_a_repeated_time_twice_as_a_no_op(
    hass: HomeAssistant, clock: Clock, cold_start: ColdStart
) -> None:
    # Down from 01:20 to 01:40 daylight time on 2026-11-01, missing the first 01:30.
    clock.set(datetime(2026, 11, 1, 1, 40, tzinfo=LOS_ANGELES, fold=0))
    home = await cold_start(
        [State(SWITCH, "off")], routine=inputs(on_time="01:30:00", off_time="03:00:00")
    )
    changes = switch_changes(hass)
    assert home.switch.state_now == "on"  # catch up inside the window

    # 01:30 standard time, an hour after the first 01:30: the trigger runs again, and the
    # device state guard makes it a no op.
    # (Arithmetic on a fold=1 datetime resets fold, so the step is taken in UTC.)
    second = dt_util.as_utc(datetime(2026, 11, 1, 1, 30, tzinfo=LOS_ANGELES, fold=1))
    await clock.to(second + timedelta(seconds=1))
    automation = hass.states.get(AUTOMATION)
    assert automation is not None
    last_triggered = automation.attributes["last_triggered"]
    assert dt_util.as_utc(last_triggered) >= second
    assert changes == []
    await clock.to(datetime(2026, 11, 1, 3, 0, 1, tzinfo=LOS_ANGELES))
    assert changes == ["off"]


# --------------------------------------------------------------------------------------
# B42: a queued burst
# --------------------------------------------------------------------------------------


async def test_b42_a_queued_burst_is_processed_in_order(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
) -> None:
    clock.set(clock.at(0, "10:00"))
    await routine_automation(inputs(timer_entity=TIMER, turn_off_after_min=30))
    timer_events: list[str] = []

    def remember(event: Event) -> None:
        timer_events.append(str(event.event_type).removeprefix("timer."))

    for kind in ("started", "restarted", "cancelled", "finished"):
        hass.bus.async_listen(f"timer.{kind}", remember)

    # Five changes before any run gets to go: on, off, on, off, on.
    for on in (True, False, True, False, True):
        sandbox_switch.device_change(on=on)
    await hass.async_block_till_done()

    assert timer_events == ["started", "cancelled", "started", "cancelled", "started"]
    assert state_of(hass, TIMER) == "active"
    await clock.to(clock.at(0, "10:30:01"))
    assert sandbox_switch.state_now == "off"
    assert timer_events[-1] == "finished"


async def test_only_when_conditions_gate_the_scheduled_start(
    hass: HomeAssistant, clock: Clock, routine_automation: Routine, sandbox_switch: SandboxSwitch
) -> None:
    # FR-R9 ships its editor in Build B; schema 1 already carries and applies the input.
    clock.set(clock.at(0, "16:00"))
    hass.states.async_set("input_boolean.guest_mode", "on")
    await routine_automation(
        inputs(
            on_time="17:00:00",
            off_time="23:00:00",
            extra_conditions=[
                {"condition": "state", "entity_id": "input_boolean.guest_mode", "state": "off"}
            ],
        )
    )

    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "off"
    hass.states.async_set("input_boolean.guest_mode", "off")
    await clock.to(clock.at(1, "17:00:01"))
    assert sandbox_switch.state_now == "on"
