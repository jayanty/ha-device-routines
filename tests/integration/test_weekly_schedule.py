"""Build A lane 14: the weekly schedule helper of a routine (PRD FR-R2, decision L38).

Days set to Weekly schedule creates the routine's own `schedule` helper, named after the
device, with the `Routines` label, links it into the routine and greys out the two time
entities; changing Days back keeps the helper, so its blocks are still there when Weekly
schedule comes back, and the D28 cleanup deletes it with the routine. A helper recreated
empty raises `schedule_blocks_needed` until it has blocks again. Skip next outside a
block skips the next block's start together with its end, as D18 does for a window; the
manager reads the block from the helper through the adapter's `schedule/list` dispatch.

The module also pins the defaults a new routine takes from the global settings (PRD
10.4), the late start window among them. Every id and name is synthetic.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_routines import compiler, ha_adapter, markers, repairs
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import Days, Occurrence, Status, Verb
from tests.integration.conftest import (
    OVERRIDE,
    SCHEDULE,
    Clock,
    Home,
    file_entry,
    flush,
    give_routine,
    inputs_of,
    issue_of,
    state_of,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

MONDAY_EVENING = [{"from": "17:00:00", "to": "22:00:00"}]


def helper_creations(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str | None]]:
    """Record every helper the adapter is asked to create: domain, name and entity id."""
    created: list[tuple[str, str, str | None]] = []
    real = ha_adapter.async_create_helper

    async def spy(hass: HomeAssistant, user_id: str, domain: Any, name: str, **kwargs: Any) -> str:
        created.append((domain, name, kwargs.get("entity_id")))
        return await real(hass, user_id, domain, name, **kwargs)

    monkeypatch.setattr(ha_adapter, "async_create_helper", spy)
    return created


async def system_user(hass: HomeAssistant, manager: RoutineManager) -> str:
    return await ha_adapter.async_ensure_system_user(hass, manager.entry.data.get("system_user_id"))


async def add_blocks(
    hass: HomeAssistant, manager: RoutineManager, **days: list[dict[str, str]]
) -> None:
    """A person adding blocks in the weekly editor (`schedule/update`)."""
    user = await system_user(hass, manager)
    await ha_adapter.async_update_helper(hass, user, SCHEDULE, **days)
    await hass.async_block_till_done()


async def weekly_routine(
    hass: HomeAssistant, manager: RoutineManager, home: Home, freezer: Any
) -> str:
    """Give the fan a routine that follows its own weekly schedule; return its id."""
    return await give_routine(hass, manager, home.fan, freezer, days="weekly_schedule")


# --------------------------------------------------------------------------------------
# The lifecycle
# --------------------------------------------------------------------------------------


async def test_days_set_to_weekly_schedule_creates_links_and_labels_the_helper(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = helper_creations(monkeypatch)
    await manager.async_opt_in(home.fan)

    result = await manager.async_update(home.fan, {"days": "weekly_schedule"})

    assert result.problem is None
    assert result.view is not None
    assert result.view.settings.days is Days.WEEKLY_SCHEDULE
    assert result.view.settings.schedule_entity == SCHEDULE
    assert created == [("schedule", "Living room fan routine", SCHEDULE)]
    state = hass.states.get(SCHEDULE)
    assert state is not None
    assert state.name == "Living room fan routine"
    entry = er.async_get(hass).async_get(SCHEDULE)
    assert entry is not None
    assert markers.LABEL_ID in entry.labels
    assert entry.device_id is None  # helpers carry no device (L36)
    # The two time entities are greyed out; everything else stays available.
    assert manager.unavailable_reason(home.fan, "on_time") == "weekly_schedule"
    assert manager.unavailable_reason(home.fan, "off_time") == "weekly_schedule"
    assert manager.unavailable_reason(home.fan, "days") is None
    assert manager.unavailable_reason(home.fan) is None

    await flush(hass, freezer)

    view = manager.get(home.fan)
    assert view is not None
    inputs = inputs_of(hass, view.automation_id)
    assert inputs["schedule_entity"] == SCHEDULE
    assert inputs["schedule_enabled"] is True
    # A new, empty helper is the person's to fill: no Repairs issue for it.
    assert issue_of(hass, repairs.SCHEDULE_BLOCKS_NEEDED, view.automation_id) is None


async def test_switching_a_timed_routine_to_weekly_schedule_drops_its_times(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9)
    )

    result = await manager.async_update(home.fan, {"days": "weekly_schedule"})
    await flush(hass, freezer)

    assert result.problem is None
    assert result.view is not None
    assert (result.view.settings.on_time, result.view.settings.off_time) == (None, None)
    inputs = inputs_of(hass, automation_id)
    assert inputs["schedule_entity"] == SCHEDULE
    assert inputs["on_time_enabled"] is False
    # Times named together with Weekly schedule are still refused (TECH_SPEC 3.3).
    refused = await manager.async_update(home.fan, {"days": "weekly_schedule", "on_time": "17:00"})
    assert refused.problem is not None
    assert refused.problem.translation_key == "times_with_weekly_schedule"


async def test_days_back_from_weekly_schedule_keeps_the_helper_and_links_it_again(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = helper_creations(monkeypatch)
    automation_id = await weekly_routine(hass, manager, home, freezer)
    await add_blocks(hass, manager, monday=MONDAY_EVENING)

    result = await manager.async_update(home.fan, {"days": "every_day", "on_time": "17:00"})
    await flush(hass, freezer)

    assert result.problem is None
    assert inputs_of(hass, automation_id)["schedule_entity"] == compiler.UNUSED_SCHEDULE
    assert state_of(hass, SCHEDULE) is not None  # kept: the cleanup governs it
    assert manager.unavailable_reason(home.fan, "on_time") is None

    again = await manager.async_update(home.fan, {"days": "weekly_schedule", "on_time": None})
    await flush(hass, freezer)

    assert again.problem is None
    assert inputs_of(hass, automation_id)["schedule_entity"] == SCHEDULE
    assert [domain for domain, _name, _entity in created] == ["schedule"]
    user = await system_user(hass, manager)
    blocks = await ha_adapter.async_schedule_blocks(hass, user, SCHEDULE)
    assert blocks is not None
    assert blocks["monday"] == MONDAY_EVENING  # the person's blocks survived the detour


async def test_after_a_restart_weekly_schedule_links_the_kept_helper_again(
    hass: HomeAssistant,
    home: Home,
    routines: MockConfigEntry,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The settings are read back from the inputs, which no longer name the helper."""
    created = helper_creations(monkeypatch)
    manager: RoutineManager = routines.runtime_data.manager
    automation_id = await weekly_routine(hass, manager, home, freezer)
    await manager.async_update(home.fan, {"days": "every_day", "on_time": "17:00"})
    await flush(hass, freezer)
    assert await hass.config_entries.async_reload(routines.entry_id)
    await hass.async_block_till_done()
    manager = routines.runtime_data.manager
    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.schedule_entity is None

    again = await manager.async_update(home.fan, {"days": "weekly_schedule"})
    await flush(hass, freezer)

    assert again.problem is None
    assert inputs_of(hass, automation_id)["schedule_entity"] == SCHEDULE
    assert [domain for domain, _name, _entity in created] == ["schedule"]


async def test_a_schedule_named_in_the_patch_is_linked_as_it_is(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = helper_creations(monkeypatch)
    hass.states.async_set("schedule.workweek", "off", {"friendly_name": "Workweek"})

    automation_id = await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        days="weekly_schedule",
        schedule_entity="schedule.workweek",
    )

    assert inputs_of(hass, automation_id)["schedule_entity"] == "schedule.workweek"
    assert created == []
    assert state_of(hass, SCHEDULE) is None


async def test_a_helper_that_cannot_be_created_keeps_the_patch_out(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await manager.async_opt_in(home.fan)

    async def refuse(*_args: Any, **_kwargs: Any) -> str:
        raise ha_adapter.HelperError("unauthorized", "the system user is not an admin")

    monkeypatch.setattr(ha_adapter, "async_create_helper", refuse)
    result = await manager.async_update(home.fan, {"days": "weekly_schedule"})

    assert result.problem is not None
    assert result.problem.key == "days"
    assert result.problem.translation_key == "schedule_helper_failed"
    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.days is Days.EVERY_DAY


async def test_a_recreated_empty_schedule_raises_schedule_blocks_needed_until_it_has_blocks(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await weekly_routine(hass, manager, home, freezer)
    user = await system_user(hass, manager)
    await ha_adapter.async_delete_helper(hass, user, SCHEDULE)
    await hass.async_block_till_done()
    created = helper_creations(monkeypatch)

    await manager.async_reconcile()
    await hass.async_block_till_done()

    assert created == [("schedule", "Living room fan routine", SCHEDULE)]
    assert state_of(hass, SCHEDULE) == "off"
    assert markers.LABEL_ID in er.async_get(hass).async_get(SCHEDULE).labels  # type: ignore[union-attr]
    assert issue_of(hass, repairs.SCHEDULE_BLOCKS_NEEDED, automation_id) is not None
    # Another reconcile while it is still empty keeps the issue and recreates nothing.
    await manager.async_reconcile()
    await hass.async_block_till_done()
    assert issue_of(hass, repairs.SCHEDULE_BLOCKS_NEEDED, automation_id) is not None
    assert len(created) == 1

    # A person adds a block in the weekly editor: the issue clears by itself.
    await add_blocks(hass, manager, tuesday=MONDAY_EVENING)

    assert issue_of(hass, repairs.SCHEDULE_BLOCKS_NEEDED, automation_id) is None
    # Later changes of the schedule ask nothing more.
    await add_blocks(hass, manager, wednesday=MONDAY_EVENING)
    assert issue_of(hass, repairs.SCHEDULE_BLOCKS_NEEDED, automation_id) is None


async def test_a_reconcile_clears_schedule_blocks_needed_once_the_schedule_has_blocks(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """An issue left from before a restart clears at the next reconcile."""
    automation_id = await weekly_routine(hass, manager, home, freezer)
    await add_blocks(hass, manager, monday=MONDAY_EVENING)
    repairs.async_sync_issue(
        hass,
        repairs.SCHEDULE_BLOCKS_NEEDED,
        True,
        {"device": "Living room fan", "schedule": SCHEDULE},
        subject=automation_id,
    )

    await manager.async_reconcile()
    await hass.async_block_till_done()

    assert issue_of(hass, repairs.SCHEDULE_BLOCKS_NEEDED, automation_id) is None


async def test_blocks_that_cannot_be_read_leave_the_issue_open(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await weekly_routine(hass, manager, home, freezer)
    user = await system_user(hass, manager)
    await ha_adapter.async_delete_helper(hass, user, SCHEDULE)
    await hass.async_block_till_done()
    await manager.async_reconcile()
    await hass.async_block_till_done()

    async def unreadable(*_args: Any) -> None:
        raise ha_adapter.HelperError("timeout", "schedule/list did not answer")

    monkeypatch.setattr(ha_adapter, "async_schedule_blocks", unreadable)
    await add_blocks(hass, manager, monday=MONDAY_EVENING)

    assert issue_of(hass, repairs.SCHEDULE_BLOCKS_NEEDED, automation_id) is not None


async def test_the_cleanup_deletes_the_weekly_schedule_even_after_days_changed_back(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await weekly_routine(hass, manager, home, freezer)
    await manager.async_update(home.fan, {"days": "every_day", "on_time": "17:00"})
    await flush(hass, freezer)
    assert state_of(hass, SCHEDULE) is not None

    await manager.async_delete_routine(home.fan)
    await hass.async_block_till_done()

    assert state_of(hass, SCHEDULE) is None
    assert er.async_get(hass).async_get(SCHEDULE) is None


async def test_a_routine_deleted_by_hand_takes_its_weekly_schedule_along(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await weekly_routine(hass, manager, home, freezer)
    await manager.async_update(home.fan, {"days": "every_day", "on_time": "17:00"})
    await flush(hass, freezer)

    await manager.async_handle_removed(automation_id)
    await hass.async_block_till_done()

    assert state_of(hass, SCHEDULE) is None


async def test_a_schedule_of_someone_else_is_never_deleted(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """Only the routine's own, labelled helper goes with the routine."""
    await weekly_routine(hass, manager, home, freezer)
    await manager.async_update(home.fan, {"days": "every_day", "on_time": "17:00"})
    await flush(hass, freezer)
    er.async_get(hass).async_update_entity(SCHEDULE, labels=set())

    await manager.async_delete_routine(home.fan)
    await hass.async_block_till_done()

    assert state_of(hass, SCHEDULE) is not None


async def test_a_device_rename_renames_the_weekly_schedule(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await weekly_routine(hass, manager, home, freezer)

    dr.async_get(hass).async_update_device(home.fan, name_by_user="Bedroom fan")
    await hass.async_block_till_done()

    assert hass.states.get(SCHEDULE).name == "Bedroom fan routine"  # type: ignore[union-attr]


# --------------------------------------------------------------------------------------
# Skip next outside a block (L38)
# --------------------------------------------------------------------------------------


async def test_skip_next_outside_a_block_skips_the_block_start_with_its_end(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    skipped_events: list[Event],
) -> None:
    """D18 for a weekly schedule: Monday 15:00, blocks Monday and Tuesday 17:00 to 22:00."""
    clock.set(clock.at(0, "15:00"))
    await weekly_routine(hass, manager, home, freezer)
    await add_blocks(hass, manager, monday=MONDAY_EVENING, tuesday=MONDAY_EVENING)

    result = await manager.async_skip_next(home.fan)
    await hass.async_block_till_done()

    assert result.skipped_action == Occurrence(clock.at(0, "17:00"), Verb.ON)
    assert result.paused_until == clock.at(0, "22:01")
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.SKIPPING
    assert view.override is False  # a block start is not a block end (D18)

    await clock.to(clock.at(0, "17:00:01"))
    assert home.switch.state_now == "off"
    await clock.to(clock.at(0, "22:01:01"))
    assert [event.data["trigger_id"] for event in skipped_events] == ["block_on", "block_off"]
    assert home.switch.state_now == "off"
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    await clock.to(clock.at(1, "17:00:01"))
    assert home.switch.state_now == "on"


async def test_skip_next_inside_a_block_skips_its_end_alone(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "15:00"))
    await weekly_routine(hass, manager, home, freezer)
    await add_blocks(hass, manager, monday=MONDAY_EVENING)
    await clock.to(clock.at(0, "18:00"))
    assert home.switch.state_now == "on"

    result = await manager.async_skip_next(home.fan)
    await hass.async_block_till_done()

    assert result.skipped_action == Occurrence(clock.at(0, "22:00"), Verb.OFF)
    assert result.paused_until == clock.at(0, "22:01")
    assert state_of(hass, OVERRIDE) == "on"  # D19 as for a window end (L40)


async def test_skip_next_without_readable_blocks_has_nothing_to_skip(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock.set(clock.at(0, "15:00"))
    await weekly_routine(hass, manager, home, freezer)
    await add_blocks(hass, manager, monday=MONDAY_EVENING)

    async def unreadable(*_args: Any) -> None:
        raise ha_adapter.HelperError("not_found", "no such schedule")

    monkeypatch.setattr(ha_adapter, "async_schedule_blocks", unreadable)
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_skip_next(home.fan)
    assert raised.value.translation_key == "nothing_to_skip"


async def test_skip_next_with_a_schedule_the_commands_do_not_manage(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A YAML schedule is not in `schedule/list`, so its block end is unknown."""
    clock.set(clock.at(0, "15:00"))
    await weekly_routine(hass, manager, home, freezer)
    await add_blocks(hass, manager, monday=MONDAY_EVENING)

    async def unmanaged(*_args: Any) -> None:
        return None

    monkeypatch.setattr(ha_adapter, "async_schedule_blocks", unmanaged)
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_skip_next(home.fan)
    assert raised.value.translation_key == "nothing_to_skip"


# --------------------------------------------------------------------------------------
# The adapter's schedule block read
# --------------------------------------------------------------------------------------


async def test_the_adapter_reads_a_schedule_helper_s_blocks(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(
        hass, manager, home.fan, freezer, days="weekly_schedule", turn_off_after_min=30
    )
    await add_blocks(hass, manager, monday=MONDAY_EVENING)
    user = await system_user(hass, manager)

    blocks = await ha_adapter.async_schedule_blocks(hass, user, SCHEDULE)

    assert blocks is not None
    assert blocks["monday"] == MONDAY_EVENING
    assert blocks["sunday"] == []
    assert set(blocks) == {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    # A schedule from YAML has a registry entry under its key but no storage item.
    er.async_get(hass).async_get_or_create(
        "schedule", "schedule", "from_yaml", suggested_object_id="from_yaml"
    )
    assert await ha_adapter.async_schedule_blocks(hass, user, "schedule.from_yaml") is None
    with pytest.raises(ha_adapter.HelperError):
        await ha_adapter.async_schedule_blocks(hass, user, "timer.routine_living_room_fan")


# --------------------------------------------------------------------------------------
# The defaults a new routine takes (PRD 10.4)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "options",
    [
        {
            "default_late_start_window_min": 45,
            "default_catch_up": False,
            "default_respect_manual": False,
        }
    ],
)
async def test_new_routines_take_the_late_start_window_and_the_other_defaults(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(7))

    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.late_start_window_min == 45
    assert view.settings.catch_up is False
    assert view.settings.respect_manual is False
    inputs = inputs_of(hass, automation_id)
    assert inputs["late_start_window_min"] == 45
    assert inputs["late_window_end"] == "07:45:00"
    assert file_entry(hass, automation_id) is not None
