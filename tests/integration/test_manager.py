"""Build A lane 5: the RoutineManager in a running Home Assistant (TECH_SPEC 4.1, PRD 3.1).

Each test is named for the PRD row or plan item it proves. The routines run on the shipped
blueprint, which the manager installs itself; the device is the sandbox switch of the
blueprint fixtures, so a routine really switches it. Every id and name is synthetic.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

from homeassistant.core import CoreState, Event, HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    area_registry as ar,
    category_registry as cr,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.device_routines import compiler, ha_adapter, markers, migration
from custom_components.device_routines.config_flow import DeviceRoutinesConfigFlow
from custom_components.device_routines.const import (
    DOMAIN,
    ENTITY_PLATFORMS,
    EVENT_PAUSED,
    EVENT_RESUMED,
    INTEGRATION_TITLE,
)
from custom_components.device_routines.domains import profile_for
from custom_components.device_routines.manager import (
    ENTITY_KEYS,
    REASON_ACTION_SKIPPED,
    REASON_OPTED_IN,
    REASON_OPTED_OUT,
    IgnoredTarget,
    ManagerEvent,
    RestoredRuntime,
    RoutineManager,
    apply_patch,
)
from custom_components.device_routines.models import (
    Days,
    Occurrence,
    Pulse,
    RoutineSettings,
    Source,
    Status,
    Verb,
    Weekday,
)
from custom_components.device_routines.nextrun import routine_lines
from custom_components.device_routines.sentence import Writer, load_phrases
from tests.integration.conftest import (
    ALIAS,
    AUTOMATION,
    FAN,
    LAMP,
    OVERRIDE,
    PAUSED,
    TIMER,
    Clock,
    Home,
    add_device,
    file_entries,
    file_entry,
    flush,
    give_routine,
    inputs_of,
    issue_of,
    save_entry,
    state_of,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


def hear(manager: RoutineManager) -> list[ManagerEvent]:
    events: list[ManagerEvent] = []
    manager.async_add_listener(events.append)
    return events


def count_writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every automation write the adapter is asked for."""
    written: list[str] = []
    real = ha_adapter.async_write_automation

    async def spy(hass: HomeAssistant, automation_id: str, config: Any, guard: Any) -> Any:
        written.append(automation_id)
        return await real(hass, automation_id, config, guard)

    monkeypatch.setattr(ha_adapter, "async_write_automation", spy)
    return written


def registry_entry(hass: HomeAssistant, entity_id: str) -> er.RegistryEntry:
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None, entity_id
    return entry


def device_labels(hass: HomeAssistant, device_id: str) -> set[str]:
    device = dr.async_get(hass).async_get(device_id)
    assert device is not None
    return set(device.labels)


async def tick(hass: HomeAssistant, freezer: Any, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# Opting in and out (PRD 4.1, plan Section 4.4)
# --------------------------------------------------------------------------------------


async def test_opt_in_through_the_label_and_through_async_opt_in_are_equivalent_and_idempotent(
    hass: HomeAssistant, home: Home, manager: RoutineManager
) -> None:
    events = hear(manager)

    first = await manager.async_opt_in(home.fan)
    again = await manager.async_opt_in(home.fan)
    dr.async_get(hass).async_update_device(home.lamp, labels={markers.LABEL_ID})
    await hass.async_block_till_done()
    dr.async_get(hass).async_update_device(home.lamp, labels={markers.LABEL_ID, "spare"})
    await hass.async_block_till_done()

    assert (first.opted_in, first.changed, again.changed) == (True, True, False)

    def opted(device_id: str) -> tuple[bool, bool, bool, bool]:
        return (
            device_id in manager.store.data.opted_in,
            markers.LABEL_ID in device_labels(hass, device_id),
            manager.entity_id_for(device_id, "manual_override") is not None,
            manager.get(device_id) is not None,
        )

    assert opted(home.fan) == opted(home.lamp) == (True, True, True, True)
    assert [event.device_id for event in events if event.reason == REASON_OPTED_IN] == [
        home.fan,
        home.lamp,
    ]
    assert manager.opted_in_devices() == tuple(sorted({home.fan, home.lamp}))
    # The shim platforms claimed the registry entries the manager made.
    assert state_of(hass, OVERRIDE) == "off"
    assert state_of(hass, PAUSED) == "unknown"
    view = manager.get(home.lamp)
    assert view is not None
    assert view.status is Status.OFF
    assert view.settings.target_entity == LAMP
    assert view.automation_entity_id is None


async def test_opt_in_refuses_unknown_and_ineligible_devices(
    hass: HomeAssistant, home: Home, manager: RoutineManager, routines: MockConfigEntry
) -> None:
    hub = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "hub"), routines.entry_id)
    assert hub is not None
    for device_id, key in (
        ("no-such-device", "unknown_device"),
        (hub.id, "unknown_device"),
        (home.door, "not_eligible"),
    ):
        with pytest.raises(ServiceValidationError) as raised:
            await manager.async_opt_in(device_id)
        assert raised.value.translation_key == key
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_update(home.lamp, {"on_time": "07:00"})
    assert raised.value.translation_key == "not_opted_in"
    # The label on a device a routine cannot drive changes nothing, now or at reconcile.
    dr.async_get(hass).async_update_device(home.door, labels={markers.LABEL_ID})
    await hass.async_block_till_done()
    await manager.async_reconcile()
    assert home.door not in manager.store.data.opted_in


async def test_opt_out_turns_the_routine_off_removes_the_entities_and_records_opted_out_at(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23)
    )
    assert state_of(hass, AUTOMATION) == "on"
    await manager.async_update(home.fan, {"off_time": time(22)})
    events = hear(manager)

    result = await manager.async_opt_out(home.fan)
    await hass.async_block_till_done()

    assert (result.opted_in, result.changed) == (False, True)
    assert state_of(hass, AUTOMATION) == "off"
    assert state_of(hass, OVERRIDE) is None
    assert manager.entity_id_for(home.fan, "manual_override") is None
    assert manager.store.data.opted_out_at[home.fan] == dt_util.utcnow()
    assert markers.LABEL_ID not in device_labels(hass, home.fan)
    # The settings are kept, the pending change included.
    assert inputs_of(hass, automation_id)["off_time"] == "22:00:00"
    assert ManagerEvent("routine_changed", home.fan, REASON_OPTED_OUT) in events
    assert (await manager.async_opt_out(home.fan)).changed is False

    # Opting back in restores the previous settings and turns the routine back on.
    await manager.async_opt_in(home.fan)
    await hass.async_block_till_done()
    assert state_of(hass, AUTOMATION) == "on"
    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.off_time == time(22)
    assert home.fan not in manager.store.data.opted_out_at
    assert state_of(hass, OVERRIDE) == "off"


async def test_removing_the_label_from_a_device_opts_it_out(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))

    dr.async_get(hass).async_update_device(home.fan, labels=set())
    await hass.async_block_till_done()

    assert home.fan not in manager.store.data.opted_in
    assert state_of(hass, AUTOMATION) == "off"


# --------------------------------------------------------------------------------------
# The write path (PRD 7.2, TECH_SPEC 4.1)
# --------------------------------------------------------------------------------------


async def test_the_first_setting_creates_the_automation_with_m1_to_m8_and_the_helpers_it_needs(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await manager.async_opt_in(home.fan)

    result = await manager.async_update(home.fan, {"on_time": "07:00", "turn_off_after_min": 30})

    # The value shows at once; the write waits for the debounce.
    assert result.problem is None
    assert result.view is not None
    assert result.view.settings.on_time == time(7)
    automation_id = markers.automation_id(home.fan)
    assert file_entry(hass, automation_id) is None
    await flush(hass, freezer)

    entry = file_entry(hass, automation_id)
    assert entry is not None
    assert entry["id"] == automation_id  # M1
    assert entry["use_blueprint"]["path"] == markers.BLUEPRINT_PATH  # M2
    assert entry["alias"] == ALIAS  # M3
    generated = markers.presentation("Living room fan", manager.summary.phrases)
    assert entry["description"] == generated.description  # M4
    registered = registry_entry(hass, AUTOMATION)  # M8
    category = cr.async_get(hass).async_get_category(
        scope="automation", category_id=registered.categories["automation"]
    )
    assert category is not None
    assert category.name == markers.CATEGORY_NAME  # M5
    assert markers.LABEL_ID in registered.labels  # M6
    assert registered.icon == markers.ICON  # M7
    assert registered.area_id == home.area  # M9
    inputs = entry["use_blueprint"]["input"]
    profile = profile_for("switch")
    assert profile is not None
    refs = compiler.HelperRefs(
        home.fan, TIMER, override_entity=OVERRIDE, paused_until_entity=PAUSED
    )
    assert inputs == dict(compiler.compile(result.view.settings, profile, refs).inputs)
    assert markers.LABEL_ID in registry_entry(hass, TIMER).labels
    assert state_of(hass, TIMER) == "idle"
    assert hass.states.get(TIMER).attributes["restore"] is True  # type: ignore[union-attr]
    # last_hash and last_valid_inputs are recorded.
    record = manager.store.data.owned[automation_id]
    assert record.last_hash == markers.config_hash(entry)
    assert record.last_valid_inputs == inputs
    assert record.alias_history == (ALIAS,)
    assert state_of(hass, AUTOMATION) == "on"
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert view.automation_entity_id == AUTOMATION


async def test_five_settings_inside_one_second_produce_one_write(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await manager.async_opt_in(home.fan)
    written = count_writes(monkeypatch)

    for minute in range(5):
        result = await manager.async_update(home.fan, {"on_time": time(17, minute)})
        assert result.view is not None
        assert result.view.settings.on_time == time(17, minute)
        freezer.tick(timedelta(seconds=0.15))
    await flush(hass, freezer)

    automation_id = markers.automation_id(home.fan)
    assert written == [automation_id]
    assert inputs_of(hass, automation_id)["on_time"] == "17:04:00"
    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.on_time == time(17, 4)


async def test_an_invalid_patch_reverts_the_entity_and_returns_the_problem(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await manager.async_opt_in(home.fan)
    events = hear(manager)

    cases: list[tuple[dict[str, Any], str]] = [
        ({"on_time": time(17), "off_time": time(17)}, "same_on_and_off_time"),
        ({"turn_off_after_min": 30, "turn_back_on_after_min": 5}, "both_durations"),
        ({"bogus": 1}, "unknown_setting"),
        ({"on_time": "25:00"}, "invalid_value"),
        ({"turn_off_after_min": True}, "invalid_value"),
        ({"target_entity": LAMP}, "invalid_target"),
    ]
    for patch, key in cases:
        result = await manager.async_update(home.fan, patch)
        assert result.problem is not None
        assert result.problem.translation_key == key
        assert result.view is not None
        assert result.view.settings.on_time is None
    await flush(hass, freezer)

    # Listeners heard the routine as it was, so an entity showing the value reverts.
    assert [event.kind for event in events] == ["routine_changed"] * len(cases)
    assert file_entries(hass) == []


def test_the_patch_reads_native_and_json_values() -> None:
    base = RoutineSettings(target_entity=FAN)
    merged, problem = apply_patch(
        base,
        {
            "on_time": "07:30",
            "off_time": None,
            "days": "some_days",
            "day_set": ["mon", Weekday.WED],
            "schedule_entity": None,
            "turn_off_after_min": 30.0,
            "catch_up": False,
            "pulse": {"at": "08:00", "minutes": 4},
            "extra_conditions": [{"condition": "state"}],
            "target_entity": "switch.other",
        },
    )
    assert problem is None
    assert merged.on_time == time(7, 30)
    assert merged.days is Days.SOME_DAYS
    assert merged.day_set == {Weekday.MON, Weekday.WED}
    assert merged.pulse == Pulse(time(8), 4, 5)
    assert merged.turn_off_after_min == 30
    assert apply_patch(base, {"pulse": Pulse(time(9))})[0].pulse == Pulse(time(9))
    bad_patches: list[dict[str, Any]] = [
        {"on_time": 7},
        {"turn_off_after_min": 1.5},
        {"turn_off_after_min": "10"},
        {"day_set": "mon"},
        {"day_set": ["someday"]},
        {"pulse": "08:00"},
        {"pulse": {"at": None}},
        {"pulse": {}},
        {"extra_conditions": "always"},
        {"target_entity": "nonsense"},
        {"schedule_entity": 5},
        {"days": "fortnightly"},
        {"respect_manual": "yes"},
    ]
    for bad in bad_patches:
        assert apply_patch(base, bad)[1] is not None, bad


async def test_a_target_entity_rename_rewrites_the_input_and_reloads(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    reloads = async_capture_events(hass, ha_adapter.EVENT_AUTOMATION_RELOADED)

    er.async_get(hass).async_update_entity(FAN, new_entity_id="switch.living_room_fan_plug")
    await hass.async_block_till_done()

    assert inputs_of(hass, automation_id)["target_entity"] == "switch.living_room_fan_plug"
    assert reloads
    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.target_entity == "switch.living_room_fan_plug"
    assert manager.store.data.owned[automation_id].target_entity == "switch.living_room_fan_plug"
    assert state_of(hass, AUTOMATION) == "on"


async def test_a_helper_entity_rename_rewrites_the_input(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )

    er.async_get(hass).async_update_entity(TIMER, new_entity_id="timer.fan_countdown")
    await hass.async_block_till_done()
    er.async_get(hass).async_update_entity(OVERRIDE, new_entity_id="switch.fan_override")
    await hass.async_block_till_done()

    inputs = inputs_of(hass, automation_id)
    assert inputs["timer_entity"] == "timer.fan_countdown"
    assert inputs["override_entity"] == "switch.fan_override"


async def test_a_device_rename_follows_the_alias_only_while_it_is_still_generated(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    devices = dr.async_get(hass)

    devices.async_update_device(home.fan, name_by_user="Bedroom fan")
    await hass.async_block_till_done()

    entry = file_entry(hass, automation_id)
    assert entry is not None
    assert entry["alias"] == "Routine: Bedroom fan"
    assert "Bedroom fan device page" in entry["description"]
    assert manager.store.data.owned[automation_id].alias_history == (
        ALIAS,
        "Routine: Bedroom fan",
    )
    assert hass.states.get(TIMER).name == "Routine: Bedroom fan"  # type: ignore[union-attr]

    # A person's alias and description are theirs from then on.
    entry["alias"] = "Fan schedule"
    entry["description"] = "Mine."
    await save_entry(hass, entry)
    devices.async_update_device(home.fan, name_by_user="Hall fan")
    await hass.async_block_till_done()
    kept = file_entry(hass, automation_id)
    assert kept is not None
    assert (kept["alias"], kept["description"]) == ("Fan schedule", "Mine.")


async def test_a_device_area_change_moves_the_automation_while_assign_area_is_on(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))

    kitchen = ar.async_get(hass).async_create("Kitchen")
    dr.async_get(hass).async_update_device(home.fan, area_id=kitchen.id)
    await hass.async_block_till_done()

    assert registry_entry(hass, AUTOMATION).area_id == kitchen.id


@pytest.mark.parametrize(("days", "deleted"), [(2, True), (0, False)])
async def test_a_device_removal_turns_the_routine_off_and_cleanup_deletes_it_after_the_period(
    hass: HomeAssistant,
    home: Home,
    freezer: Any,
    routines: MockConfigEntry,
    days: int,
    deleted: bool,
) -> None:
    hass.config_entries.async_update_entry(routines, options={"cleanup_after_days": days})
    manager: RoutineManager = routines.runtime_data.manager
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    await tick(hass, freezer, 3)
    linked = dr.async_get(hass).async_get_device_by_identifier(
        ("sandbox", "fan"), routines.entry_id
    )
    assert linked is not None  # the Schedule sensor's linked record (L25)

    dr.async_get(hass).async_remove_device(home.fan)
    await hass.async_block_till_done()

    assert state_of(hass, AUTOMATION) == "off"
    assert manager.store.data.removed_devices_at[home.fan] == dt_util.utcnow()
    assert dr.async_get(hass).async_get(linked.id) is None
    assert state_of(hass, OVERRIDE) is None
    view = manager.get(home.fan)
    assert view is not None
    assert view.device_name == home.fan

    await tick(hass, freezer, 86400)
    assert file_entry(hass, automation_id) is not None
    await tick(hass, freezer, 400 * 86400)

    assert (file_entry(hass, automation_id) is None) is deleted
    assert (state_of(hass, TIMER) is None) is deleted
    assert (automation_id not in manager.store.data.owned) is deleted
    assert (home.fan not in manager.store.data.removed_devices_at) is deleted


async def test_deleting_the_routines_label_opts_nobody_out(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30)

    lr.async_get(hass).async_delete(markers.LABEL_ID)
    await hass.async_block_till_done()

    assert lr.async_get(hass).async_get_label(markers.LABEL_ID) is not None
    assert manager.store.data.opted_in == {home.fan}
    assert markers.LABEL_ID in device_labels(hass, home.fan)
    assert markers.LABEL_ID in registry_entry(hass, AUTOMATION).labels
    assert markers.LABEL_ID in registry_entry(hass, TIMER).labels
    assert state_of(hass, AUTOMATION) == "on"
    assert state_of(hass, OVERRIDE) == "off"


async def test_a_lookalike_automation_is_never_written_and_never_listed(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """S7: the same alias, description, label and category, without M1 and M2."""
    lookalike = {
        "id": "living_room_fan_schedule",
        "alias": ALIAS,
        "description": markers.presentation("Living room fan", manager.summary.phrases).description,
        "triggers": [{"trigger": "time", "at": "18:00:00"}],
        "actions": [{"action": "switch.turn_on", "target": {"entity_id": FAN}}],
    }
    await save_entry(hass, lookalike)
    assert registry_entry(hass, AUTOMATION).unique_id == "living_room_fan_schedule"

    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    ha_adapter.async_update_registry_entity(hass, AUTOMATION, labels={markers.LABEL_ID})
    await manager.async_reconcile()
    await manager.async_rebuild_index(dry_run=False)
    await hass.async_block_till_done()

    assert file_entry(hass, "living_room_fan_schedule") == lookalike
    assert [view.automation_id for view in manager.list()] == [automation_id]
    assert set(manager.store.data.owned) == {automation_id}
    view = manager.get(home.fan)
    assert view is not None
    assert view.automation_entity_id != AUTOMATION
    assert registry_entry(hass, AUTOMATION).unique_id == "living_room_fan_schedule"


async def test_two_devices_with_the_same_name_get_distinct_automation_ids_and_helper_ids(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    twin = add_device(hass, home.source, "fan_twin", "Living room fan", "switch.living_room_fan_2")

    first = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    second = await give_routine(
        hass, manager, twin, freezer, on_time=time(18), turn_off_after_min=20
    )

    assert first != second
    a, b = inputs_of(hass, first), inputs_of(hass, second)
    for key in ("timer_entity", "override_entity", "paused_until_entity"):
        assert a[key] != b[key], key
    assert a["timer_entity"] == TIMER
    assert b["timer_entity"].startswith(f"{TIMER}_")
    views = {view.device_id: view for view in manager.list()}
    assert views[home.fan].automation_entity_id == AUTOMATION
    assert views[twin].automation_entity_id == b["timer_entity"].replace("timer.", "automation.")
    assert state_of(hass, b["timer_entity"]) == "idle"


# --------------------------------------------------------------------------------------
# Skip, pause, resume (PRD 5.5, D18 to D21, L22, L40) on the real blueprint
# --------------------------------------------------------------------------------------


async def test_a_pause_schedules_a_resume_at_the_stored_time_and_resume_applies_catch_up(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    skipped_events: list[Event],
) -> None:
    clock.set(clock.at(0, "16:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    paused = async_capture_events(hass, EVENT_PAUSED)
    resumed = async_capture_events(hass, EVENT_RESUMED)

    result = await manager.async_pause(home.fan, until=clock.at(0, "18:30"))
    await hass.async_block_till_done()

    assert result.paused_until == clock.at(0, "18:30")
    assert state_of(hass, PAUSED) == dt_util.as_utc(clock.at(0, "18:30")).isoformat()
    assert [event.data["until"] for event in paused] == [clock.at(0, "18:30").isoformat()]
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.PAUSED
    assert view.sentence == "Paused until 6:30 PM"
    await clock.to(clock.at(0, "17:00:01"))
    assert home.switch.state_now == "off"
    assert [event.data["trigger_id"] for event in skipped_events] == ["scheduled_on"]

    await clock.to(clock.at(0, "18:30:01"))

    assert state_of(hass, PAUSED) == "unknown"
    assert home.switch.state_now == "on"  # the pause end catches up (D20)
    assert [event.data["device_id"] for event in resumed] == [home.fan]

    # A manual change while paused sets no override (D21); an early Resume catches up.
    await manager.async_pause(home.fan, duration=timedelta(hours=2))
    home.switch.device_change(on=False)
    await hass.async_block_till_done()
    assert state_of(hass, OVERRIDE) == "off"
    await clock.to(clock.at(0, "19:00"))
    resumed_early = await manager.async_resume(home.fan)
    await hass.async_block_till_done()
    assert resumed_early.paused_until is None
    assert home.switch.state_now == "on"
    assert len(resumed) == 2
    # Resuming a routine that is not paused changes nothing.
    assert (await manager.async_resume(home.fan)).paused_until is None
    assert len(resumed) == 2


async def test_pause_needs_exactly_one_future_value(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    for kwargs, key in (
        ({}, "pause_until_or_for"),
        ({"until": dt_util.utcnow(), "duration": timedelta(hours=1)}, "pause_until_or_for"),
        ({"until": dt_util.utcnow() - timedelta(minutes=1)}, "paused_until_in_past"),
    ):
        with pytest.raises(ServiceValidationError) as raised:
            await manager.async_pause(home.fan, **kwargs)
        assert raised.value.translation_key == key
    await manager.async_opt_in(home.lamp)
    for action in (manager.async_skip_next, manager.async_resume, manager.async_enable):
        with pytest.raises(ServiceValidationError) as raised:
            await action(home.lamp)
        assert raised.value.translation_key == "no_routine"


async def test_skip_next_sets_paused_until_from_skip_target(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    skipped_events: list[Event],
) -> None:
    """FR-R11 and S11: Wednesday 15:00, a 17:00 to 09:00 window, Skip next."""
    clock.set(clock.at(2, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))
    events = hear(manager)

    result = await manager.async_skip_next(home.fan)
    await hass.async_block_till_done()

    assert result.skipped_action == Occurrence(clock.at(2, "17:00"), Verb.ON)
    assert result.paused_until == clock.at(3, "09:01")
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.SKIPPING
    assert view.sentence == "Skipped, on Thu 5:00 PM"
    assert view.override is False  # a window start is not a window end (D18)

    await clock.to(clock.at(2, "17:00:01"))
    assert home.switch.state_now == "off"
    assert [(event.data["trigger_id"], event.data["action"]) for event in skipped_events] == [
        ("scheduled_on", "on")
    ]
    heard = [event for event in events if event.reason == REASON_ACTION_SKIPPED]
    assert heard[0].device_id == home.fan
    assert heard[0].data is not None
    assert heard[0].data["trigger_id"] == "scheduled_on"
    await clock.to(clock.at(3, "09:01:01"))
    assert [event.data["trigger_id"] for event in skipped_events] == [
        "scheduled_on",
        "scheduled_off",
    ]
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert home.switch.state_now == "off"
    await clock.to(clock.at(3, "17:00:01"))
    assert home.switch.state_now == "on"


async def test_skip_next_on_a_window_end_keeps_the_device_as_it_is_until_the_next_time(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    """D19 with L40: the skip sets the override, so the pause end's catch up waits."""
    clock.set(clock.at(0, "16:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await clock.to(clock.at(0, "20:00"))
    assert home.switch.state_now == "on"

    result = await manager.async_skip_next(home.fan)
    await hass.async_block_till_done()

    assert result.skipped_action == Occurrence(clock.at(0, "23:00"), Verb.OFF)
    assert state_of(hass, OVERRIDE) == "on"
    await clock.to(clock.at(0, "23:01:01"))
    assert home.switch.state_now == "on"
    assert state_of(hass, OVERRIDE) == "on"
    await clock.to(clock.at(1, "17:00:01"))
    assert state_of(hass, OVERRIDE) == "off"
    await clock.to(clock.at(1, "23:00:01"))
    assert home.switch.state_now == "off"


async def test_resume_clears_an_override_the_skip_set_so_the_window_catches_up(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "16:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await clock.to(clock.at(0, "20:00"))
    await manager.async_skip_next(home.fan)
    await hass.async_block_till_done()
    home.switch.device_change(on=False)
    await hass.async_block_till_done()

    await manager.async_resume(home.fan)
    await hass.async_block_till_done()

    assert state_of(hass, OVERRIDE) == "off"
    assert home.switch.state_now == "on"


async def test_a_pause_replaces_an_override_the_skip_set(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "16:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await clock.to(clock.at(0, "20:00"))
    await manager.async_skip_next(home.fan)

    await manager.async_pause(home.fan, until=clock.at(0, "21:00"))
    await hass.async_block_till_done()

    view = manager.get(home.fan)
    assert view is not None
    assert (view.override, view.status, view.skipped_action) == (False, Status.PAUSED, None)


async def test_skip_next_on_a_running_countdown_cancels_the_timer(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    """B33 with L40: the device stays as it is; the countdown does not resume later."""
    clock.set(clock.at(0, "10:00"))
    await give_routine(hass, manager, home.fan, freezer, turn_off_after_min=30)
    home.switch.device_change(on=True)
    await hass.async_block_till_done()
    assert state_of(hass, TIMER) == "active"

    result = await manager.async_skip_next(home.fan)
    await hass.async_block_till_done()

    assert result.skipped_action is not None
    assert result.skipped_action.verb is Verb.OFF
    assert state_of(hass, TIMER) == "idle"
    await clock.to(clock.at(0, "11:00"))
    assert home.switch.state_now == "on"
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_skip_next(home.fan)
    assert raised.value.translation_key == "nothing_to_skip"


# --------------------------------------------------------------------------------------
# Enable, disable, actions over targets (FR-R14, FR-R15, S13)
# --------------------------------------------------------------------------------------


async def test_enable_and_disable_follow_the_routine_switch(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    events = hear(manager)

    await manager.async_disable(home.fan)
    await hass.async_block_till_done()
    view = manager.get(home.fan)
    assert view is not None
    assert (view.enabled, view.status) == (False, Status.OFF)
    assert view.sentence == "Routine off"
    await manager.async_enable(home.fan)
    await hass.async_block_till_done()
    view = manager.get(home.fan)
    assert view is not None
    assert view.enabled is True
    # Turning the automation off elsewhere reaches the listeners (the Routine switch).
    before = len(events)
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": AUTOMATION}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(events) > before


async def test_actions_over_a_label_skip_routines_and_list_plain_devices_as_ignored(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """S13: a label covering one routine device and one plain device."""
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    evening = lr.async_get(hass).async_create("Evening")
    devices = dr.async_get(hass)
    for device_id in (home.fan, home.lamp):
        device = devices.async_get(device_id)
        assert device is not None
        devices.async_update_device(device_id, labels={*device.labels, evening.label_id})

    done = await manager.async_run_action("skip_next", {"label_id": evening.label_id})

    assert [result.device_id for result in done.results] == [home.fan]
    assert done.results[0].action == "skip_next"
    assert done.results[0].device_name == "Living room fan"
    assert done.ignored == (IgnoredTarget(home.lamp, "device", "no_routine"),)
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_run_action("resume", {"device_id": home.lamp})
    assert raised.value.translation_key == "no_routine_targets"
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_run_action("pause", {"device_id": home.fan})
    assert raised.value.translation_key == "pause_until_or_for"


async def test_targets_resolve_devices_entities_areas_floors_and_labels(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await manager.async_opt_in(home.lamp)
    empty = lr.async_get(hass).async_create("Unused")

    by_entity = manager.resolve_targets(
        {"entity_id": [FAN, OVERRIDE, AUTOMATION, "sensor.unknown", LAMP]}
    )
    assert by_entity.device_ids == (home.fan,)
    assert by_entity.ignored == (
        IgnoredTarget("sensor.unknown", "entity", "no_routine"),
        IgnoredTarget(home.lamp, "device", "no_routine"),
    )
    by_area = manager.resolve_targets({"area_id": home.area, "floor_id": [home.floor]})
    assert by_area.device_ids == (home.fan,)
    assert by_area.ignored == (IgnoredTarget(home.lamp, "device", "no_routine"),)
    nothing = manager.resolve_targets(
        {"label_id": empty.label_id, "area_id": "nowhere", "device_id": "no-such-device"}
    )
    assert nothing.device_ids == ()
    assert {item.kind for item in nothing.ignored} == {"device", "area", "label"}
    # A routine label target names every routine device.
    assert manager.resolve_targets({"label_id": markers.LABEL_ID}).device_ids == (home.fan,)

    paused = await manager.async_run_action(
        "pause", {"area_id": home.area}, duration=timedelta(hours=1)
    )
    assert [result.paused_until for result in paused.results] == [
        dt_util.utcnow() + timedelta(hours=1)
    ]
    for action in ("resume", "disable", "enable"):
        done = await manager.async_run_action(action, {"device_id": [home.fan]})
        assert done.results[0].action == action


# --------------------------------------------------------------------------------------
# Runtime state: attribution, the override, restore, the started event (L20, L35)
# --------------------------------------------------------------------------------------


async def test_a_manual_change_against_the_window_sets_the_override(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "12:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))

    runtime = manager.routine_for(FAN)
    assert runtime is not None
    assert (runtime.active, runtime.paused, runtime.expected) == (True, False, "off")
    home.switch.device_change(on=True)
    await hass.async_block_till_done()

    view = manager.get(home.fan)
    assert view is not None
    assert (view.override, view.last_change_source) == (True, Source.DEVICE)
    assert state_of(hass, OVERRIDE) == "on"
    # A person turns the override off: the blueprint catches up.
    await hass.services.async_call("switch", "turn_off", {"entity_id": OVERRIDE}, blocking=True)
    await hass.async_block_till_done()
    assert home.switch.state_now == "off"
    assert manager.routine_for(LAMP) is None
    # The sink ignores a device the manager does not know.
    await manager.async_set_override("no-such-device", on=True, source=Source.USER, new_state="on")


async def test_restored_runtime_is_handed_over_and_kept(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    later = dt_util.utcnow() + timedelta(hours=2)
    skipped = Occurrence(later - timedelta(minutes=1), Verb.OFF)

    await manager.async_restore_runtime(
        home.fan,
        RestoredRuntime(
            paused_until=later,
            skipped_action=skipped,
            override=True,
            override_by_skip=True,
            last_change_source=Source.USER,
        ),
    )

    assert manager.restore_data(home.fan) == RestoredRuntime(
        later, skipped, override=True, override_by_skip=True, last_change_source=Source.USER
    )
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.SKIPPING
    # A restored pause that already ended is dropped.
    await manager.async_restore_runtime(
        home.lamp, RestoredRuntime(paused_until=dt_util.utcnow() - timedelta(minutes=5))
    )
    await manager.async_restore_runtime(
        home.fan, RestoredRuntime(paused_until=dt_util.utcnow() - timedelta(minutes=5))
    )
    assert manager.restore_data(home.lamp) is None
    data = manager.restore_data(home.fan)
    assert data is not None
    assert data.paused_until == later


async def test_missed_timer_finishes_fire_the_caught_up_event_once_per_timer_after_start(
    hass: HomeAssistant, home: Home, hass_storage: dict[str, Any]
) -> None:
    """L20: timers the restore cache shows ran out during the restart are caught up."""

    def record(device_id: str, target: str, timer: str) -> dict[str, Any]:
        settings = RoutineSettings(target_entity=target, turn_off_after_min=30)
        profile = profile_for(target.partition(".")[0])
        assert profile is not None
        inputs = compiler.compile(settings, profile, compiler.HelperRefs(device_id, timer))
        return {
            "device_id": device_id,
            "target_entity": target,
            "last_valid_inputs": dict(inputs.inputs),
        }

    third = add_device(hass, home.source, "pump", "Garden pump", "switch.garden_pump")
    hass_storage["device_routines"] = {
        "version": 1,
        "minor_version": 1,
        "key": "device_routines",
        "data": {
            "owned": {
                markers.automation_id(home.fan): record(home.fan, FAN, TIMER),
                markers.automation_id(home.lamp): record(
                    home.lamp, LAMP, "timer.routine_desk_lamp"
                ),
                markers.automation_id(third): record(third, "switch.garden_pump", "timer.pump"),
            },
            "opted_in": [home.fan, home.lamp, third],
        },
    }
    past = (dt_util.utcnow() - timedelta(minutes=5)).isoformat()
    future = (dt_util.utcnow() + timedelta(minutes=5)).isoformat()
    mock_restore_cache(
        hass,
        [
            State(TIMER, "active", {"finishes_at": past}),
            State("timer.routine_desk_lamp", "active", {"finishes_at": past}),
            State("timer.pump", "active", {"finishes_at": future}),
        ],
    )
    hass.set_state(CoreState.not_running)
    caught_up = async_capture_events(hass, compiler.EVENT_TIMER_CAUGHT_UP)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_TITLE,
        unique_id=DOMAIN,
        minor_version=DeviceRoutinesConfigFlow.MINOR_VERSION,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert caught_up == []

    await hass.async_start()
    await hass.async_block_till_done()

    assert sorted(event.data["device_id"] for event in caught_up) == sorted([home.fan, home.lamp])
    manager: RoutineManager = entry.runtime_data.manager
    assert manager.health_inputs().last_reconcile is not None


async def test_listeners_receive_routine_changed_on_every_change_and_the_skip_is_re_emitted(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    events = hear(manager)
    seen: list[ManagerEvent] = []
    unsubscribe = manager.async_add_listener(seen.append)

    await manager.async_opt_in(home.fan)
    await manager.async_update(home.fan, {"on_time": time(17)})
    await flush(hass, freezer)
    hass.bus.async_fire(
        compiler.EVENT_ACTION_SKIPPED, {"device_id": home.fan, "trigger_id": "scheduled_on"}
    )
    hass.bus.async_fire(compiler.EVENT_ACTION_SKIPPED, {"device_id": "elsewhere"})
    await hass.async_block_till_done()
    unsubscribe()
    await manager.async_update(home.fan, {"on_time": time(18)})

    assert events[0] == ManagerEvent("routine_changed", home.fan, REASON_OPTED_IN)
    assert {event.kind for event in events} == {"routine_changed"}
    assert {event.device_id for event in events} == {home.fan}
    skipped = [event for event in events if event.reason == REASON_ACTION_SKIPPED]
    assert len(skipped) == 1
    assert skipped[0].data == {"device_id": home.fan, "trigger_id": "scheduled_on"}
    assert len(seen) == len(events) - 1


# --------------------------------------------------------------------------------------
# Views, the summary item, the config flow's lists, Health
# --------------------------------------------------------------------------------------


async def test_the_schedule_sensor_lists_the_routine_first_with_its_own_line(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any, clock: Clock
) -> None:
    clock.set(clock.at(0, "12:00"))
    await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_time=time(17),
        off_time=time(23),
        days="weekdays",
        pulse={"at": "08:00", "minutes": 3},
    )
    await tick(hass, freezer, 3)

    view = manager.get(home.fan)
    assert view is not None
    assert view.items[0].kind == "routine"
    assert view.items[0].summary == (
        "Weekdays 5:00 PM: on, Weekdays 11:00 PM: off, 8:00 AM: toggle for 3 min, then toggle"
    )
    assert view.next_action == Occurrence(clock.at(0, "17:00"), Verb.ON)
    assert view.sentence == "On at 5:00 PM"
    summary = manager.routine_summary(home.fan)
    assert summary is not None
    assert summary.status is Status.ACTIVE
    assert manager.routine_summary(home.lamp) is None


def test_routine_lines_read_every_option() -> None:
    writer = Writer(load_phrases("en"), "12h")

    def read(settings: RoutineSettings) -> list[str]:
        return [writer.line(line) for line in routine_lines(settings, "id", "alias")]

    assert read(RoutineSettings(target_entity=FAN, turn_back_on_after_min=10)) == [
        "On 10 min after it turns off"
    ]
    assert read(RoutineSettings(target_entity="cover.blind", turn_off_after_min=10)) == [
        "When it has not been closed for 10 min: close"
    ]
    assert read(
        RoutineSettings(
            target_entity=FAN, days=Days.WEEKLY_SCHEDULE, schedule_entity="schedule.week"
        )
    ) == ["When a block of schedule.week starts: on", "When a block of schedule.week ends: off"]
    assert read(RoutineSettings(target_entity="alarm.panel", off_time=time(9))) == ["9:00 AM: off"]


async def test_eligible_and_suggested_devices_for_the_config_flow(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    lamp_off = {
        "id": "desk_lamp_off",
        "alias": "Desk lamp off",
        "triggers": [{"trigger": "time", "at": "22:00:00"}],
        "actions": [{"action": "light.turn_off", "target": {"entity_id": LAMP}}],
    }
    await save_entry(hass, lamp_off)
    await tick(hass, freezer, 3)

    eligible = manager.eligible_devices()
    assert [choice.name for choice in eligible] == ["Desk lamp", "Garage door", "Living room fan"]
    assert eligible[0].targets == (LAMP,)
    assert eligible[0].area_id == home.area
    assert [choice.device_id for choice in manager.suggested_devices()] == [home.lamp]
    await manager.async_opt_in(home.lamp)
    assert manager.suggested_devices() == ()


async def test_health_inputs_and_unavailable_reasons(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))

    inputs = manager.health_inputs()
    assert (inputs.owned_count, inputs.loaded_count) == (1, 1)
    assert inputs.blueprint_status == "shipped"
    assert inputs.blueprint_schema == compiler.BLUEPRINT_SCHEMA_VERSION
    assert inputs.issues == ()
    assert inputs.adapter_failed == ()
    assert manager.unavailable_reason(home.fan) is None
    assert manager.adapter_report.ok
    assert manager.profile(home.fan) is not None
    assert manager.profile("no-such-device") is None


async def test_editing_is_refused_while_the_adapter_cannot_write(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    monkeypatch.setattr(
        ha_adapter,
        "check",
        lambda _hass: ha_adapter.AdapterReport(failed=(ha_adapter.CAPABILITY_WRITE,)),
    )
    events = hear(manager)

    await manager.async_reconcile()

    assert manager.unavailable_reason(home.fan) == "adapter_incompatible"
    assert issue_of(hass, "adapter_incompatible") is not None
    assert ManagerEvent("health_changed", None) in events
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_update(home.fan, {"on_time": time(18)})
    assert raised.value.translation_key == "editing_unavailable"


async def test_the_entry_unload_writes_what_is_pending(
    hass: HomeAssistant, home: Home, manager: RoutineManager, routines: MockConfigEntry
) -> None:
    await manager.async_opt_in(home.fan)
    await manager.async_update(home.fan, {"on_time": time(6, 45)})

    assert await hass.config_entries.async_unload(routines.entry_id)
    await hass.async_block_till_done()

    assert inputs_of(hass, markers.automation_id(home.fan))["on_time"] == "06:45:00"


async def test_a_write_that_fails_is_logged_and_retried_by_the_next_change(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await manager.async_opt_in(home.fan)

    async def broken(*_args: Any) -> Any:
        raise ha_adapter.AdapterError("synthetic failure")

    monkeypatch.setattr(ha_adapter, "async_write_automation", broken)
    await manager.async_update(home.fan, {"on_time": time(17)})
    await flush(hass, freezer)

    assert "Could not write the routine" in caplog.text
    assert file_entries(hass) == []
    monkeypatch.undo()
    await manager.async_update(home.fan, {"on_time": time(17, 30)})
    await flush(hass, freezer)
    assert inputs_of(hass, markers.automation_id(home.fan))["on_time"] == "17:30:00"


async def test_a_moved_file_raises_write_conflict_and_retry_writes(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    real = ha_adapter.async_write_automation

    async def conflict(*_args: Any) -> Any:
        raise ha_adapter.WriteConflictError("synthetic conflict")

    monkeypatch.setattr(ha_adapter, "async_write_automation", conflict)
    await manager.async_update(home.fan, {"on_time": time(18)})
    await flush(hass, freezer)

    assert issue_of(hass, "write_conflict", automation_id) is not None
    assert inputs_of(hass, automation_id)["on_time"] == "17:00:00"
    monkeypatch.setattr(ha_adapter, "async_write_automation", real)
    await manager.async_retry_write(automation_id)
    assert issue_of(hass, "write_conflict", automation_id) is None
    assert inputs_of(hass, automation_id)["on_time"] == "18:00:00"
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_retry_write(markers.automation_id("no-such-device"))
    assert raised.value.translation_key == "unknown_routine"


async def test_the_schema_migration_writes_through_the_manager_and_reports_failures(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await manager.async_write_settings(
        automation_id, RoutineSettings(target_entity=FAN, on_time=time(19))
    )
    assert inputs_of(hass, automation_id)["on_time"] == "19:00:00"

    async def conflict(*_args: Any) -> Any:
        raise ha_adapter.WriteConflictError("synthetic conflict")

    monkeypatch.setattr(ha_adapter, "async_write_automation", conflict)
    with pytest.raises(ha_adapter.WriteConflictError):
        await manager.async_write_settings(
            automation_id, RoutineSettings(target_entity=FAN, on_time=time(20))
        )
    with pytest.raises(Exception, match="invalid_inputs"):
        await manager.async_write_settings(
            automation_id, RoutineSettings(target_entity="sensor.thermometer", on_time=time(9))
        )
    monkeypatch.undo()

    async def failed(*_args: Any) -> list[str]:
        return [automation_id, markers.automation_id("no-such-device")]

    monkeypatch.setattr(migration, "async_migrate_blueprint_schema", failed)
    await manager.async_reconcile()
    assert issue_of(hass, "automation_load_failed", automation_id) is not None
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.INVALID
    # The next start migrates it: the issue clears.
    monkeypatch.undo()
    await manager.async_reconcile()
    assert issue_of(hass, "automation_load_failed", automation_id) is None


# --------------------------------------------------------------------------------------
# Edges: refused domains, races, devices without routines
# --------------------------------------------------------------------------------------


async def test_a_garage_door_cover_gets_no_opening_time(
    hass: HomeAssistant, home: Home, manager: RoutineManager
) -> None:
    """PRD 5.4: the refusal comes from the device class in the entity registry."""
    await manager.async_opt_in(home.garage)

    refused = await manager.async_update(home.garage, {"on_time": "07:00"})
    allowed = await manager.async_update(home.garage, {"off_time": "22:00"})

    assert refused.problem is not None
    assert refused.problem.translation_key == "on_time_not_supported"
    assert allowed.problem is None


async def test_a_target_renamed_before_the_first_write_is_written_with_its_new_id(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await manager.async_opt_in(home.fan)
    await manager.async_update(home.fan, {"on_time": time(17)})

    er.async_get(hass).async_update_entity(FAN, new_entity_id="switch.fan_plug")
    await hass.async_block_till_done()

    assert inputs_of(hass, markers.automation_id(home.fan))["target_entity"] == "switch.fan_plug"


async def test_a_rename_while_the_file_lacks_the_entry_writes_nothing(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    others = [item for item in file_entries(hass) if item.get("id") != automation_id]
    from tests.integration.conftest import write_entries  # noqa: PLC0415

    write_entries(hass, others)  # saved by someone else, not reloaded yet

    dr.async_get(hass).async_update_device(home.fan, name_by_user="Bedroom fan")
    dr.async_get(hass).async_update_device(home.lamp, name_by_user="Reading lamp")
    await manager.async_opt_in(home.lamp)
    dr.async_get(hass).async_update_device(home.lamp, name_by_user="Study lamp")
    await hass.async_block_till_done()

    assert file_entry(hass, automation_id) is None


async def test_a_write_after_opting_out_keeps_the_helpers_it_named(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await manager.async_opt_out(home.fan)

    await manager.async_write_settings(
        automation_id, RoutineSettings(target_entity=FAN, on_time=time(18))
    )

    inputs = inputs_of(hass, automation_id)
    assert (inputs["on_time"], inputs["override_entity"]) == ("18:00:00", OVERRIDE)


async def test_a_new_automation_the_reload_did_not_register_gets_no_presentation(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await manager.async_opt_in(home.fan)

    async def unregistered(*_args: Any) -> ha_adapter.WriteResult:
        return ha_adapter.WriteResult(hash="", created=True)

    monkeypatch.setattr(ha_adapter, "async_write_automation", unregistered)
    await manager.async_update(home.fan, {"on_time": time(17)})
    await flush(hass, freezer)

    assert markers.automation_id(home.fan) in manager.store.data.owned
    assert er.async_get(hass).async_get(AUTOMATION) is None


async def test_removing_a_device_without_a_routine_leaves_the_other_records(
    hass: HomeAssistant, home: Home, manager: RoutineManager
) -> None:
    await manager.async_opt_in(home.lamp)

    dr.async_get(hass).async_remove_device(home.lamp)
    await hass.async_block_till_done()

    assert home.lamp in manager.store.data.removed_devices_at


async def test_handlers_ignore_automations_the_manager_does_not_know(
    hass: HomeAssistant, manager: RoutineManager
) -> None:
    unknown = markers.automation_id("no-such-device")

    await manager.async_handle_removed(unknown)
    await manager.async_handle_detached(unknown)

    assert manager.list() == ()


async def test_skip_next_over_a_target_ignores_a_routine_with_nothing_to_skip(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await give_routine(hass, manager, home.lamp, freezer, turn_off_after_min=30)

    done = await manager.async_run_action("skip_next", {"area_id": home.area})

    assert [result.device_id for result in done.results] == [home.fan]
    assert done.ignored == (IgnoredTarget(home.lamp, "device", "nothing_to_skip"),)
    hub = manager.resolve_targets({"entity_id": "sensor.device_routines_health"})
    assert hub.device_ids == ()
    assert hub.ignored[0].reason == "no_routine"


async def test_view_carries_opted_in(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any, hass_ws_client: Any
) -> None:
    """L63 gap 1: an opted out routine waiting for cleanup is told apart from one that is off."""
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await manager.async_disable(home.fan)
    view = manager.get(home.fan)
    assert view is not None
    assert (view.status, view.opted_in) == (Status.OFF, True)

    await manager.async_opt_out(home.fan)

    view = manager.get(home.fan)
    assert view is not None
    assert (view.status, view.opted_in) == (Status.OFF, False)
    assert [(item.device_id, item.opted_in) for item in manager.list()] == [(home.fan, False)]
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "device_routines/routines/list"})
    response = await client.receive_json()
    assert response["success"], response
    (listed,) = response["result"]["routines"]
    assert (listed["status"], listed["opted_in"]) == ("off", False)
    assert list(listed)[-1] == "opted_in"  # appended last (plan 6.2.5)
    await manager.async_opt_in(home.fan)
    view = manager.get(home.fan)
    assert view is not None
    assert view.opted_in is True


async def test_ignored_targets_carry_placeholders(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any, hass_ws_client: Any
) -> None:
    """L63 gap 4: every ignored target renders its reason, with `target` and `device`.

    `device` is the device's name, or for a target that names no device its own name; a
    refusal keeps its own placeholders.
    """
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await give_routine(hass, manager, home.lamp, freezer, turn_off_after_min=30)
    attic = ar.async_get(hass).async_create("Attic")
    upstairs = fr.async_get(hass).async_create("Upstairs")
    unused = lr.async_get(hass).async_create("Unused")
    hass.states.async_set("sensor.outdoor_temperature", "12", {"friendly_name": "Outdoor"})

    resolved = manager.resolve_targets(
        {
            "device_id": [home.garage, "no-such-device"],
            "entity_id": ["sensor.outdoor_temperature", "sensor.unknown"],
            "area_id": [attic.id, "nowhere"],
            "floor_id": [upstairs.floor_id, "no-such-floor"],
            "label_id": [unused.label_id, "no-such-label"],
        }
    )

    assert {(i.target, i.kind, i.reason): dict(i.placeholders) for i in resolved.ignored} == {
        (home.garage, "device", "no_routine"): {"target": home.garage, "device": "Garage door"},
        ("no-such-device", "device", "no_routine"): {
            "target": "no-such-device",
            "device": "no-such-device",
        },
        ("sensor.outdoor_temperature", "entity", "no_routine"): {
            "target": "sensor.outdoor_temperature",
            "device": "Outdoor",
        },
        ("sensor.unknown", "entity", "no_routine"): {
            "target": "sensor.unknown",
            "device": "sensor.unknown",
        },
        (attic.id, "area", "no_routine"): {"target": attic.id, "device": "Attic"},
        ("nowhere", "area", "no_routine"): {"target": "nowhere", "device": "nowhere"},
        (upstairs.floor_id, "floor", "no_routine"): {
            "target": upstairs.floor_id,
            "device": "Upstairs",
        },
        ("no-such-floor", "floor", "no_routine"): {
            "target": "no-such-floor",
            "device": "no-such-floor",
        },
        (unused.label_id, "label", "no_routine"): {
            "target": unused.label_id,
            "device": "Unused",
        },
        ("no-such-label", "label", "no_routine"): {
            "target": "no-such-label",
            "device": "no-such-label",
        },
    }
    # A refusal of the action names its device, as its own placeholders do; the WebSocket
    # API carries them (the example in docs/api.md).
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "device_routines/routines/action",
            "action": "skip_next",
            "target": {"area_id": home.area},
        }
    )
    response = await client.receive_json()
    assert response["success"], response
    assert response["result"]["ignored"] == [
        {
            "target": home.lamp,
            "kind": "device",
            "reason": "nothing_to_skip",
            "placeholders": {"target": home.lamp, "device": "Desk lamp"},
        }
    ]
    # Placeholders are words, not identity.
    assert IgnoredTarget(home.lamp, "device", "no_routine") == IgnoredTarget(
        home.lamp, "device", "no_routine", {"device": "Desk lamp"}
    )


def hand_switching(key: str, at: str, service: str) -> dict[str, Any]:
    """A hand written automation switching the fan at a time."""
    return {
        "id": key,
        "alias": key.replace("_", " ").capitalize(),
        "triggers": [{"trigger": "time", "at": at}],
        "actions": [{"action": service, "target": {"entity_id": FAN}}],
    }


def found(conflicts: Any) -> set[tuple[str, Any]]:
    return {(conflict.reason_key, conflict.at) for conflict in conflicts}


async def test_an_update_answers_only_the_conflicts_its_new_settings_have(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    """The answer of a patch (`routines/set`) is consistent at once (FR-S6).

    The Schedule reads the routine from its written inputs a few seconds later; until
    then its conflicts are those of the old settings, and the view leaves out the ones
    the new settings no longer have.
    """
    clock.set(clock.at(0, "16:00"))  # Monday
    five, eight, eleven = clock.at(0, "17:00"), clock.at(0, "20:00"), clock.at(0, "23:00")
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    await save_entry(hass, hand_switching("early_fan_off", "17:00:00", "switch.turn_off"))
    await tick(hass, freezer, 3)
    view = manager.get(home.fan)
    assert view is not None
    assert found(view.conflicts) == {("opposite_same_minute", five), ("off_in_on_window", five)}

    # The start moves out of the conflict: the answer carries none.
    result = await manager.async_update(home.fan, {"on_time": "18:00"})

    assert result.view is not None
    assert result.view.conflicts == ()
    assert found(manager.summary.summaries[home.fan].conflicts) != set()  # not read yet
    await flush(hass, freezer)
    await tick(hass, freezer, 3)
    assert manager.summary.summaries[home.fan].conflicts == ()

    # The docs example: an automation turns the fan on at 23:00, the routine's end. Moving
    # the end to 22:30 ends the same minute conflict; the on in the off period stays, and
    # so do the conflicts of two other automations at 20:00, inside the window.
    await save_entry(hass, hand_switching("late_fan_on", "23:00:00", "switch.turn_on"))
    await save_entry(hass, hand_switching("evening_fan_on", "20:00:00", "switch.turn_on"))
    await save_entry(hass, hand_switching("evening_fan_off", "20:00:00", "switch.turn_off"))
    await tick(hass, freezer, 3)
    view = manager.get(home.fan)
    assert view is not None
    evening = {("opposite_same_minute", eight), ("off_in_on_window", eight)}
    assert found(view.conflicts) == {
        ("opposite_same_minute", eleven),
        ("on_in_off_window", eleven),
        *evening,
    }
    result = await manager.async_update(home.fan, {"off_time": "22:30"})
    assert result.view is not None
    assert found(result.view.conflicts) == {("on_in_off_window", eleven), *evening}
    await flush(hass, freezer)
    await tick(hass, freezer, 3)
    view = manager.get(home.fan)
    assert view is not None
    assert view.conflicts == manager.summary.summaries[home.fan].conflicts
    assert found(view.conflicts) == {("on_in_off_window", eleven), *evening}


def test_the_entity_keys_are_the_platform_keys_longest_first() -> None:
    """Plan A4.0 item 11: one source for the device page keys (`const.ENTITY_PLATFORMS`)."""
    assert set(ENTITY_KEYS) == set(ENTITY_PLATFORMS)
    assert len(ENTITY_KEYS) == len(ENTITY_PLATFORMS)
    assert [len(key) for key in ENTITY_KEYS] == sorted(map(len, ENTITY_KEYS), reverse=True)


async def test_a_device_without_a_routine_has_no_unavailable_reason(
    hass: HomeAssistant, home: Home, manager: RoutineManager
) -> None:
    for key in (None, "days", "on_time", "turn_back_on_after", "target"):
        assert manager.unavailable_reason(home.garage, key) is None, key


async def test_settings_are_held_in_the_form_the_inputs_read_back(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """Plan A4.0 item 21 (L38): canonical in memory, as after a restart.

    A day set chosen alone is Some days, and a named one reads as its name; a time sent
    with an offset is held without it.
    """
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))

    weekdays = ["mon", "tue", "wed", "thu", "fri"]
    result = await manager.async_update(home.fan, {"day_set": weekdays})
    assert result.view is not None
    assert result.view.settings.days is Days.WEEKDAYS
    result = await manager.async_update(home.fan, {"day_set": ["mon", "wed"]})
    assert result.view is not None
    assert (result.view.settings.days, result.view.settings.day_set) == (
        Days.SOME_DAYS,
        frozenset({Weekday.MON, Weekday.WED}),
    )
    result = await manager.async_update(home.fan, {"days": "every_day"})
    assert result.view is not None
    assert result.view.settings.day_set == frozenset(Weekday)
    result = await manager.async_update(home.fan, {"off_time": "08:30:00+02:00"})
    assert result.view is not None
    assert result.view.settings.off_time == time(8, 30)
    assert result.view.settings.off_time.tzinfo is None


async def test_a_rename_names_the_linked_record_and_a_gone_device_is_no_error(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    freezer: Any,
) -> None:
    """Plan A4.0 item 29 (L25): the page controls read the name the device shows."""
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    devices = dr.async_get(hass)

    devices.async_update_device(home.fan, name_by_user="Bedroom fan")
    await hass.async_block_till_done()

    linked = devices.async_get_device_by_identifier(("sandbox", "fan"), routines.entry_id)
    assert linked is not None
    assert linked.name == "Bedroom fan"
    override = hass.states.get(OVERRIDE)
    assert override is not None
    assert override.name == "Bedroom fan Manual override"
    manager._follow_linked_record("no-such-device")  # gone meanwhile: nothing to name
