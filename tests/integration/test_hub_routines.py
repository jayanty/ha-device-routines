"""Build A lane 14: the hub Routines sensor (PRD 4.4).

State: the count of active routines. Attributes: every managed routine with its device,
area, summary line, next action, status and automation, so a markdown card can show all
managed automations in one place. The rows come from the manager; the sensor follows
the manager's events and every Schedule summary change, at most once a second. Every
id and name is synthetic.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.device_routines.manager import HubRoutine, RoutineManager
from custom_components.device_routines.models import Status
from custom_components.device_routines.sensor import HUB_COOLDOWN_SECONDS
from tests.integration.conftest import (
    AUTOMATION,
    Clock,
    Home,
    file_entry,
    give_routine,
    save_entry,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

HUB = "sensor.device_routines_routines"
LAMP_AUTOMATION = "automation.routine_desk_lamp"


async def settle(hass: HomeAssistant, freezer: Any) -> None:
    """Let the hub's one second cooldown run out."""
    freezer.tick(timedelta(seconds=HUB_COOLDOWN_SECONDS + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def hub(hass: HomeAssistant) -> tuple[str, list[dict[str, Any]]]:
    state = hass.states.get(HUB)
    assert state is not None
    routines: list[dict[str, Any]] = state.attributes["routines"]
    return state.state, routines


async def test_the_hub_lists_every_managed_routine(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "08:00"))
    assert hub(hass) == ("0", [])

    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))
    await manager.async_opt_in(home.lamp)  # controls, but no automation yet
    await settle(hass, freezer)

    assert hub(hass) == (
        "1",
        [
            {
                "device": "Living room fan",
                "area": "Living room",
                "summary": "5:00 PM: on, 9:00 AM: off",
                "next_action": "Off at 9:00 AM",
                "status": "active",
                "automation": AUTOMATION,
            }
        ],
    )

    await give_routine(hass, manager, home.lamp, freezer, off_time=time(23))
    await settle(hass, freezer)

    count, routines = hub(hass)
    assert count == "2"
    assert [row["device"] for row in routines] == ["Desk lamp", "Living room fan"]
    assert routines[0] == {
        "device": "Desk lamp",
        "area": "Living room",
        "summary": "11:00 PM: off",
        "next_action": "Off at 11:00 PM",
        "status": "active",
        "automation": LAMP_AUTOMATION,
    }


async def test_the_count_is_the_active_routines_and_each_row_has_its_status(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "08:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))
    await give_routine(hass, manager, home.lamp, freezer, off_time=time(23))

    await manager.async_disable(home.lamp)
    await manager.async_pause(home.fan, until=clock.at(0, "12:00"))
    await hass.async_block_till_done()
    await settle(hass, freezer)

    count, routines = hub(hass)
    assert count == "0"
    assert {row["device"]: row["status"] for row in routines} == {
        "Desk lamp": "off",
        "Living room fan": "paused",
    }
    by_device = {row["device"]: row for row in routines}
    # The next action that really runs: the pause hides the 9:00 AM off (FR-S4).
    assert by_device["Living room fan"]["next_action"] == "On at 5:00 PM"
    assert by_device["Desk lamp"]["next_action"] is None

    await manager.async_skip_next(home.fan)
    await hass.async_block_till_done()
    await settle(hass, freezer)
    assert {row["device"]: row["status"] for row in hub(hass)[1]} == {
        "Desk lamp": "off",
        "Living room fan": "skipping",
    }


async def test_the_hub_moves_on_with_the_next_action(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "08:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))
    await settle(hass, freezer)
    assert hub(hass)[1][0]["next_action"] == "Off at 9:00 AM"

    await clock.to(clock.at(0, "09:00:05"))
    await settle(hass, freezer)

    assert hub(hass)[1][0]["next_action"] == "On at 5:00 PM"


async def test_a_detached_routine_stays_listed_as_detached(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "08:00"))
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9)
    )
    entry = file_entry(hass, automation_id)
    assert entry is not None
    taken = {key: value for key, value in entry.items() if key != "use_blueprint"}
    taken["triggers"] = [{"trigger": "time", "at": "17:00:00"}]
    taken["actions"] = [{"action": "switch.turn_on", "target": {"entity_id": "switch.x"}}]

    await save_entry(hass, taken)
    await settle(hass, freezer)

    rows = manager.hub_routines()
    assert [(row.device, row.status) for row in rows] == [("Living room fan", Status.DETACHED)]
    assert hub(hass)[1][0]["status"] == "detached"
    assert hub(hass)[1][0]["automation"] == AUTOMATION


async def test_a_device_without_an_area_or_a_summary_line(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "08:00"))
    dr.async_get(hass).async_update_device(home.fan, area_id=None)
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))
    manager.summary.summaries.pop(home.fan)

    assert manager.hub_routines() == (
        HubRoutine(
            device="Living room fan",
            area=None,
            summary=None,
            next_action="Off at 9:00 AM",
            status=Status.ACTIVE,
            automation=AUTOMATION,
        ),
    )
