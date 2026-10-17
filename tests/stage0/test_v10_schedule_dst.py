"""Stage 0 V10, A6 and A7: schedule blocks that meet at midnight, and time triggers on DST days.

A6: a weekly schedule with one block ending at midnight and the next starting at midnight
must not blip off and on, or a routine's `block_off` and `block_on` triggers would cycle
the device. A7: what the core time trigger does with a wall clock time that is skipped or
repeated on a daylight saving day, on the 2026 United States and European dates.

Recorded results (core 2026.10.2): A6 holds, the state stays on and only the attribute
`next_event` changes at midnight. A7: a skipped time does not run that night at all, and a
repeated time runs twice, once per offset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import Event, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

SCHEDULE = "schedule.stage0_probe"

# The probes stop in the middle of a schedule and a daily trigger, so the next fire is
# still scheduled when the test ends; that is the point, not a leak.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


def record(marker: str) -> dict[str, Any]:
    return {"action": "test.record", "data": {"marker": marker}}


async def step_minutes(hass: HomeAssistant, freezer: Any, minutes: int) -> None:
    """Advance the clock one minute at a time, letting every timer fire."""
    for _ in range(minutes):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# A6: adjacent blocks at midnight
# --------------------------------------------------------------------------------------


async def test_blocks_meeting_at_midnight_stay_on(hass: HomeAssistant, freezer: Any) -> None:
    await hass.config.async_set_time_zone("America/Los_Angeles")
    tz = ZoneInfo("America/Los_Angeles")
    # Monday 2026-10-19, 23:55 local.
    freezer.move_to(datetime(2026, 10, 19, 23, 55, tzinfo=tz))
    calls = async_mock_service(hass, "test", "record")
    changes: list[Event] = []

    assert await async_setup_component(
        hass,
        "schedule",
        {
            "schedule": {
                "stage0_probe": {
                    "name": "stage0 probe",
                    "monday": [{"from": "22:00:00", "to": "24:00:00"}],
                    "tuesday": [{"from": "00:00:00", "to": "02:00:00"}],
                }
            }
        },
    )
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "id": "stage0_on",
                    "triggers": [{"trigger": "state", "entity_id": SCHEDULE, "to": "on"}],
                    "actions": [record("state_on")],
                },
                {
                    "id": "stage0_off",
                    "triggers": [{"trigger": "state", "entity_id": SCHEDULE, "to": "off"}],
                    "actions": [record("state_off")],
                },
                {
                    "id": "stage0_started",
                    "triggers": [
                        {"trigger": "schedule.block_started", "target": {"entity_id": SCHEDULE}}
                    ],
                    "actions": [record("block_started")],
                },
                {
                    "id": "stage0_ended",
                    "triggers": [
                        {"trigger": "schedule.block_ended", "target": {"entity_id": SCHEDULE}}
                    ],
                    "actions": [record("block_ended")],
                },
            ]
        },
    )
    await hass.async_block_till_done()
    hass.bus.async_listen(
        "state_changed",
        lambda event: changes.append(event) if event.data["entity_id"] == SCHEDULE else None,
    )
    assert hass.states.get(SCHEDULE).state == "on"  # type: ignore[union-attr]

    # Across midnight: 23:55 to 00:10.
    await step_minutes(hass, freezer, 15)

    states = [event.data["new_state"].state for event in changes]
    markers = [call.data["marker"] for call in calls]
    # One attribute only change at midnight (next_event moves to 02:00); the state never
    # leaves on, so state triggers to on and to off stay silent.
    assert states == ["on"]
    assert "state_on" not in markers
    assert "state_off" not in markers
    assert "block_ended" not in markers
    # The purpose specific block started trigger fires for back to back blocks by design.
    assert markers == ["block_started"]

    # And the block really ends at 02:00.
    await step_minutes(hass, freezer, 115)
    assert hass.states.get(SCHEDULE).state == "off"  # type: ignore[union-attr]
    assert sorted(call.data["marker"] for call in calls) == [
        "block_ended",
        "block_started",
        "state_off",
    ]


# --------------------------------------------------------------------------------------
# A7: time triggers on daylight saving days
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DstCase:
    """One daylight saving night: where, from when, which trigger time, what happens."""

    label: str
    zone: str
    start: datetime
    at: str
    hours: int = 6

    @property
    def skipped(self) -> bool:
        return self.label.endswith("skipped")


LOS_ANGELES = ZoneInfo("America/Los_Angeles")
BERLIN = ZoneInfo("Europe/Berlin")
DST_CASES = [
    DstCase(
        "us_spring_skipped",
        "America/Los_Angeles",
        datetime(2026, 3, 7, 23, tzinfo=LOS_ANGELES),
        "02:30:00",
    ),
    DstCase(
        "us_fall_repeated",
        "America/Los_Angeles",
        datetime(2026, 10, 31, 23, tzinfo=LOS_ANGELES),
        "01:30:00",
    ),
    DstCase(
        "eu_spring_skipped", "Europe/Berlin", datetime(2026, 3, 28, 23, tzinfo=BERLIN), "02:30:00"
    ),
    DstCase(
        "eu_fall_repeated", "Europe/Berlin", datetime(2026, 10, 24, 23, tzinfo=BERLIN), "02:30:00"
    ),
]


async def runs_of_time_trigger(hass: HomeAssistant, freezer: Any, case: DstCase) -> list[datetime]:
    await hass.config.async_set_time_zone(case.zone)
    freezer.move_to(case.start)
    runs: list[datetime] = []

    async def remember(call: Any) -> None:
        runs.append(dt_util.utcnow())

    hass.services.async_register("test", "record", remember)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "id": "stage0_time",
                "triggers": [{"trigger": "time", "at": case.at}],
                "actions": [record("time")],
            }
        },
    )
    await hass.async_block_till_done()
    await step_minutes(hass, freezer, case.hours * 60)
    return runs


@pytest.mark.parametrize("case", DST_CASES, ids=[case.label for case in DST_CASES])
async def test_time_trigger_on_dst_days(hass: HomeAssistant, freezer: Any, case: DstCase) -> None:
    runs = await runs_of_time_trigger(hass, freezer, case)
    local = [run.astimezone(ZoneInfo(case.zone)) for run in runs]

    if case.skipped:
        # The wall clock time does not exist that night: the trigger does not run at all.
        assert local == []
    else:
        # The wall clock time exists twice: the trigger runs at both occurrences, first
        # with the daylight saving offset, then an hour later with the standard offset.
        assert len(local) == 2
        assert local[0].dst() != timedelta(0)
        assert local[1].dst() == timedelta(0)
        assert runs[1] - runs[0] == timedelta(hours=1)
