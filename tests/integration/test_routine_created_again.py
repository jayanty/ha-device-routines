"""Live finding F7: a routine created again for a device that had one starts turned on.

The core restores an automation's last on or off by entity id, and a routine's automation
created again for a device whose routine was cleaned up (or deleted in the editor) takes
the id and the entity id of the old one, so without the manager it would start as the
old one ended: off, when a person had turned it off. A new routine has no on or off a
person chose, so the manager sets it: on, or off while the manager itself holds the
routine off (the device opted out, the target missing). A person's own disable of a
routine that exists still sticks through every edit.

The home is the synthetic one of `conftest.py` (a living room fan on the sandbox switch);
Monday 2026-10-19 at 4:00 PM in Los Angeles. Every name is generic.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.core import HomeAssistant
import pytest

from custom_components.device_routines import ha_adapter, maintenance, markers
from custom_components.device_routines.maintenance import MaintenanceAction
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import Status
from tests.integration.conftest import (
    AUTOMATION,
    FAN,
    Clock,
    Home,
    file_entries,
    file_entry,
    flush,
    give_routine,
    inputs_of,
    save_entry,
    state_of,
    write_entries,
)
from tests.integration.test_conversion_offers import EVENING, FAN_EVENING, add_automations, settle
from tests.integration.test_reconcile import bring_the_fan_back, remove_the_fan
from tests.integration.test_sync_back import delete_in_the_editor

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


@pytest.fixture
def at_four(clock: Clock) -> Clock:
    """Monday 16:00, an hour before the fan's evening starts."""
    clock.set(clock.at(0, "16:00"))
    return clock


def routine_switch(manager: RoutineManager, device_id: str) -> str:
    entity_id = manager.entity_id_for(device_id, "routine")
    assert entity_id is not None
    return entity_id


async def turn_the_routine_off(
    hass: HomeAssistant, manager: RoutineManager, device_id: str
) -> None:
    """A person turns the device page's Routine switch off."""
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": routine_switch(manager, device_id)}, blocking=True
    )
    await hass.async_block_till_done()
    assert state_of(hass, AUTOMATION) == "off"


async def run_then_turn_off(
    hass: HomeAssistant, manager: RoutineManager, home: Home, freezer: Any
) -> str:
    """The fan gets a routine, on and active, then a person turns the routine off."""
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23)
    )
    view = manager.get(home.fan)
    assert view is not None
    assert (view.status, state_of(hass, AUTOMATION)) == (Status.ACTIVE, "on")
    await turn_the_routine_off(hass, manager, home.fan)
    return automation_id


async def clean_up_while_off(
    hass: HomeAssistant, manager: RoutineManager, home: Home, freezer: Any, _client: Any
) -> None:
    """Routine off, opt out, Clean up now: the automation and its helpers are gone."""
    automation_id = await run_then_turn_off(hass, manager, home, freezer)
    await manager.async_opt_out(home.fan)
    report = await maintenance.async_run(hass, manager, MaintenanceAction.CLEAN_UP_NOW, False)
    await hass.async_block_till_done()
    assert report.changed == [home.fan]
    assert file_entry(hass, automation_id) is None
    assert state_of(hass, AUTOMATION) is None
    assert manager.get(home.fan) is None


async def delete_while_off(
    hass: HomeAssistant, manager: RoutineManager, home: Home, freezer: Any, client: Any
) -> None:
    """Routine off, then deleted in the automation editor: the routine is cleared (PRD 8.2)."""
    automation_id = await run_then_turn_off(hass, manager, home, freezer)
    await delete_in_the_editor(hass, client, automation_id)
    assert automation_id not in manager.store.data.owned
    assert state_of(hass, AUTOMATION) is None


async def never_had_one(*_args: Any) -> None:
    """The fan never had a routine."""


HISTORIES = [
    pytest.param(clean_up_while_off, id="cleaned_up_while_off"),
    pytest.param(delete_while_off, id="deleted_while_off"),
]


async def assert_running(
    hass: HomeAssistant, manager: RoutineManager, home: Home, freezer: Any
) -> None:
    """The fan's routine is on, active, and its Routine switch and Schedule say so."""
    await settle(hass, freezer)
    assert state_of(hass, AUTOMATION) == "on"
    assert state_of(hass, routine_switch(manager, home.fan)) == "on"
    view = manager.get(home.fan)
    assert view is not None
    assert view.automation_entity_id == AUTOMATION
    assert (view.enabled, view.status) == (True, Status.ACTIVE)
    assert view.sentence == "On at 5:00 PM"
    assert manager.store.data.suspended == {}


# --------------------------------------------------------------------------------------
# A routine created again starts on (F7)
# --------------------------------------------------------------------------------------


async def test_a_conversion_after_a_cleanup_while_off_starts_the_routine_on(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """Live validation B: converting must never leave the device without its schedule."""
    await clean_up_while_off(hass, manager, home, freezer, None)
    await add_automations(hass, freezer, FAN_EVENING)

    view = await manager.async_convert_automation(EVENING)

    # Written under the same automation id and entity id as the routine cleaned up.
    assert view.automation_id == markers.automation_id(home.fan)
    assert (view.enabled, view.status) == (True, Status.ACTIVE)
    await assert_running(hass, manager, home, freezer)
    assert state_of(hass, EVENING) == "off"
    # At 5:00 PM the routine turns the fan on: the device kept its schedule.
    await at_four.to(at_four.at(0, "17:00:30"))
    assert state_of(hass, FAN) == "on"


@pytest.mark.parametrize("history", HISTORIES)
async def test_an_opt_in_and_a_setting_after_the_old_routine_ended_off_start_it_on(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_client: Any,
    history: Any,
) -> None:
    await history(hass, manager, home, freezer, hass_client)

    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))

    await assert_running(hass, manager, home, freezer)
    await at_four.to(at_four.at(0, "17:00:30"))
    assert state_of(hass, FAN) == "on"


# --------------------------------------------------------------------------------------
# What a new routine does not override
# --------------------------------------------------------------------------------------


async def test_a_routine_a_person_turned_off_stays_off_through_every_edit(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """L44: a person's disable sticks; an edit is not a new routine."""
    automation_id = await run_then_turn_off(hass, manager, home, freezer)

    # On the device page, a change that also creates the routine's timer.
    await manager.async_update(home.fan, {"off_time": time(22), "turn_off_after_min": 30})
    await flush(hass, freezer)
    assert inputs_of(hass, automation_id)["off_time"] == "22:00:00"
    # In the blueprint form.
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["on_time"] = "16:30:00"
    await save_entry(hass, entry)

    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.on_time == time(16, 30)
    assert (view.enabled, view.status) == (False, Status.OFF)
    assert state_of(hass, AUTOMATION) == "off"
    assert state_of(hass, routine_switch(manager, home.fan)) == "off"
    await at_four.to(at_four.at(0, "17:00:30"))
    assert state_of(hass, FAN) == "off"


async def test_an_entry_written_again_for_a_routine_that_exists_keeps_a_persons_off(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """The file lost the entry (saved by someone else, not reloaded): not a new routine."""
    automation_id = await run_then_turn_off(hass, manager, home, freezer)
    write_entries(hass, [item for item in file_entries(hass) if item.get("id") != automation_id])

    await manager.async_update(home.fan, {"off_time": time(22)})
    await flush(hass, freezer)

    assert inputs_of(hass, automation_id)["off_time"] == "22:00:00"
    assert state_of(hass, AUTOMATION) == "off"
    view = manager.get(home.fan)
    assert view is not None
    assert (view.enabled, view.status) == (False, Status.OFF)


@pytest.mark.parametrize(
    "history",
    [
        pytest.param(never_had_one, id="never_had_one"),
        pytest.param(clean_up_while_off, id="cleaned_up_while_off"),
    ],
)
async def test_a_new_routine_whose_target_is_missing_starts_off_until_the_target_returns(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_client: Any,
    history: Any,
) -> None:
    """A routine the manager holds off is not turned on, and comes back with its target."""
    await history(hass, manager, home, freezer, hass_client)
    await manager.async_opt_in(home.fan)
    result = await manager.async_update(home.fan, {"on_time": time(17), "off_time": time(23)})
    assert result.problem is None
    # The target goes before the debounced first write lands.
    remove_the_fan(hass)
    await hass.async_block_till_done()

    await flush(hass, freezer)

    automation_id = markers.automation_id(home.fan)
    assert file_entry(hass, automation_id) is not None
    assert state_of(hass, AUTOMATION) == "off"
    assert manager.store.data.suspended == {automation_id: "missing_target"}
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.MISSING_TARGET

    bring_the_fan_back(hass)
    await hass.async_block_till_done()

    await assert_running(hass, manager, home, freezer)


async def test_a_routine_opted_out_while_its_first_write_runs_starts_off(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opting out turns a routine off; one whose automation did not exist yet too."""
    await manager.async_opt_in(home.fan)
    result = await manager.async_update(home.fan, {"on_time": time(17), "off_time": time(23)})
    assert result.problem is None
    real = ha_adapter.async_write_automation

    async def opt_out_then_write(*args: Any) -> ha_adapter.WriteResult:
        await manager.async_opt_out(home.fan)
        return await real(*args)

    monkeypatch.setattr(ha_adapter, "async_write_automation", opt_out_then_write)
    await flush(hass, freezer)

    assert file_entry(hass, markers.automation_id(home.fan)) is not None
    assert state_of(hass, AUTOMATION) == "off"
    view = manager.get(home.fan)
    assert view is not None
    assert (view.opted_in, view.status) == (False, Status.OFF)
    assert manager.store.data.suspended == {}

    # Opting in again turns it on, as for any routine that was opted out.
    monkeypatch.setattr(ha_adapter, "async_write_automation", real)
    await manager.async_opt_in(home.fan)
    await assert_running(hass, manager, home, freezer)
