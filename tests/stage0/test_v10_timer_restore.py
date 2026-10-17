"""Stage 0 V10, A5b: a restored timer that expired while Home Assistant was down.

The routine's `timer_done` trigger must see the finish of a timer whose end passed during
a restart. The timer component finishes such a timer while it is being added, which is
during startup, and automations arm their triggers only in a startup job after that.
These tests record which triggers see the finish and what the timer looks like afterwards.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import CoreState, Event, HomeAssistant, State
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)

TIMER = "timer.stage0_probe"


def restored_active_timer(finishes_in: timedelta) -> State:
    """The state a running timer leaves in the restore cache at shutdown."""
    finishes_at = dt_util.utcnow().replace(microsecond=0) + finishes_in
    return State(
        TIMER,
        "active",
        {
            "duration": "0:10:00",
            "remaining": "0:10:00",
            "finishes_at": finishes_at.isoformat(),
            "last_transition": "started",
            "restore": True,
        },
    )


def automation(trigger: dict[str, Any], marker: str) -> dict[str, Any]:
    return {
        "id": f"stage0_{marker}",
        "triggers": [trigger],
        "actions": [{"action": "test.record", "data": {"marker": marker}}],
    }


class Probe:
    """What the probe records: the core's events and the automation runs."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.calls: list[Any] = []

    @property
    def markers(self) -> list[str]:
        return [call.data["marker"] for call in self.calls]


async def start_with_restored_timer(hass: HomeAssistant, finishes_in: timedelta) -> Probe:
    """Set the timer and three listening automations up as a cold start does."""
    hass.set_state(CoreState.not_running)
    mock_restore_cache(hass, [restored_active_timer(finishes_in)])
    probe = Probe()
    probe.calls = async_mock_service(hass, "test", "record")
    hass.bus.async_listen("timer.finished", probe.events.append)

    assert await async_setup_component(
        hass, "timer", {"timer": {"stage0_probe": {"duration": "00:10:00", "restore": True}}}
    )
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                automation(
                    {
                        "trigger": "event",
                        "event_type": "timer.finished",
                        "event_data": {"entity_id": TIMER},
                    },
                    "event",
                ),
                automation(
                    {"trigger": "timer.finished", "target": {"entity_id": TIMER}}, "purpose"
                ),
                automation({"trigger": "homeassistant", "event": "start"}, "start"),
            ]
        },
    )
    await hass.async_block_till_done()
    await hass.async_start()
    await hass.async_block_till_done()
    return probe


async def test_an_expired_timer_finishes_before_any_trigger_is_armed(hass: HomeAssistant) -> None:
    probe = await start_with_restored_timer(hass, timedelta(minutes=-5))

    state = hass.states.get(TIMER)

    # The core fires timer.finished once, while the entity is added during startup.
    assert len(probe.events) == 1
    assert probe.events[0].data["entity_id"] == TIMER
    # Neither the event trigger nor the purpose specific trigger is armed yet: only the
    # start trigger runs. A5b as written does not hold for an automation.
    assert probe.markers == ["start"]
    # What the start branch can see: the timer is idle and remembers that it finished.
    assert state is not None
    assert state.state == "idle"
    assert state.attributes["last_transition"] == "finished"


async def test_a_timer_with_time_left_resumes_and_fires_later(
    hass: HomeAssistant, freezer: Any
) -> None:
    probe = await start_with_restored_timer(hass, timedelta(minutes=2))

    state = hass.states.get(TIMER)
    assert state is not None
    assert state.state == "active"
    assert probe.markers == ["start"]

    freezer.tick(timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # A finish after startup reaches both armed triggers.
    assert len(probe.events) == 1
    assert sorted(probe.markers) == ["event", "purpose", "start"]
