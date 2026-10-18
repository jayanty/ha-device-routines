"""Build B lane 19: sun relative bounds (FR-R10) from the device page and the manager.

A side of a routine is a time of day, or sunrise or sunset with an offset (decision L60).
The device page shows each time with two advanced companions, the timing select (Time,
Sunrise, Sunset) and the sun offset number, which write blueprint input schema 2. The
manager places a sun bound where the blueprint runs it, through the core's astral helper
(plan 6.2.5), so catch up, the Manual override, Skip next, the next action and the
Schedule sentence of a sun routine agree with the blueprint. The tests run the real
manager, platforms and shipped blueprint over the synthetic home of `conftest.py`; the
sun instants come from `sun_instant`, the helper the blueprint matrix uses, so they follow
the real sun at the test instance's location. Monday 2026-10-19 is day 0. Every id and
name is synthetic.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.const import EntityCategory
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import dump
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.device_routines import compiler, maintenance, markers
from custom_components.device_routines.config_flow import DeviceRoutinesConfigFlow
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.domains import PROFILES
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import (
    Days,
    Occurrence,
    RoutineSettings,
    Source,
    Status,
    TimeKind,
    Verb,
)
from custom_components.device_routines.sentence import Writer, load_phrases
from custom_components.device_routines.store import STORAGE_KEY, OwnedRecord, StoreData
from tests.blueprint.conftest import async_install_blueprint, sun_instant
from tests.integration.conftest import (
    ALIAS,
    AUTOMATION,
    FAN,
    OVERRIDE,
    PAUSED,
    Clock,
    Home,
    add_device,
    flush,
    give_routine,
    inputs_of,
    state_of,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

SUN_KEYS = ("on_kind", "on_sun_offset", "off_kind", "off_sun_offset")
SECOND = timedelta(seconds=1)
# On 30 minutes after sunrise, off 30 minutes before sunset, every day.
DAYLIGHT: dict[str, Any] = {
    "on_kind": "sunrise",
    "on_sun_offset_min": 30,
    "off_kind": "sunset",
    "off_sun_offset_min": -30,
}
WRITER = Writer(load_phrases("en"), "12h")


def page(hass: HomeAssistant, device_id: str) -> dict[str, er.RegistryEntry]:
    """Every device page control of a device in the registry by key, the Schedule aside."""
    prefix = f"{DOMAIN}_{device_id}_"
    return {
        entry.unique_id.removeprefix(prefix): entry
        for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN
        and entry.unique_id.startswith(prefix)
        and entry.unique_id != f"{prefix}schedule"
    }


async def enable(
    hass: HomeAssistant, routines: MockConfigEntry, freezer: Any, device_id: str
) -> tuple[RoutineManager, dict[str, str]]:
    """Enable a device's sun companions, as a person does on the device page.

    Home Assistant reloads the entry 30 seconds later, which replaces the manager; returns
    the new manager and the companions' entity ids by key.
    """
    registry = er.async_get(hass)
    entries = page(hass, device_id)
    for key in SUN_KEYS:
        registry.async_update_entity(entries[key].entity_id, disabled_by=None)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    manager: RoutineManager = routines.runtime_data.manager
    return manager, {key: entries[key].entity_id for key in SUN_KEYS}


async def call(hass: HomeAssistant, domain: str, service: str, **data: Any) -> None:
    await hass.services.async_call(domain, service, data, blocking=True)
    await hass.async_block_till_done()


def at(hass: HomeAssistant, event: str, day: int, minutes: int) -> datetime:
    """When a sun bound runs on a day: the event plus an offset in minutes, local."""
    return sun_instant(hass, event, day, timedelta(minutes=minutes))


async def run_past(hass: HomeAssistant, freezer: Any, instant: datetime) -> None:
    """Let a sun trigger due at `instant` run a millisecond later, as a running instance does.

    `Clock` stops exactly at each timer, and the core's `sun` condition reads the instant of
    a `before` bound as still before (L64), so a run the trigger queues (the catch up after
    the override clears) would otherwise see the window it just ended. In a running
    instance the callback fires after its instant, never on it.
    """
    freezer.move_to(instant + timedelta(milliseconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# The companions on the device page (PRD 4.2, FR-R10)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_id", "state", "device_class", "on_label", "off_label"),
    [
        ("switch.sandbox_heater", "off", None, "turn_on_at", "turn_off_at"),
        ("vacuum.sandbox_vacuum", "docked", None, "start_at", "return_to_dock_at"),
        ("cover.sandbox_blind", "closed", None, "open_at", "close_at"),
        ("cover.sandbox_gate", "closed", "gate", None, "close_at"),
        ("lock.sandbox_lock", "locked", None, None, "lock_at"),
        ("media_player.sandbox_speaker", "off", None, None, "turn_off_at"),
    ],
)
async def test_companion_entities_exist_disabled_by_default_per_profile(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    entity_id: str,
    state: str,
    device_class: str | None,
    on_label: str | None,
    off_label: str,
) -> None:
    """Each side the profile has gets its timing and its offset, advanced, in its words."""
    object_id = entity_id.partition(".")[2]
    name = object_id.replace("_", " ").capitalize()
    device_id = add_device(
        hass, home.source, object_id, name, entity_id, state, device_class=device_class
    )

    await manager.async_opt_in(device_id)
    await hass.async_block_till_done()

    expected = {"off_kind", "off_sun_offset"} | (
        {"on_kind", "on_sun_offset"} if on_label else set()
    )
    entries = page(hass, device_id)
    assert {key for key in entries if key in SUN_KEYS} == expected
    assert expected <= manager.page_keys(device_id)
    for key in expected:
        entry = entries[key]
        label = on_label if key.startswith("on_") else off_label
        suffix = "kind" if key.endswith("_kind") else "sun_offset"
        assert entry.domain == ("select" if suffix == "kind" else "number"), key
        assert entry.unique_id == f"{DOMAIN}_{device_id}_{key}"
        assert entry.entity_category is EntityCategory.CONFIG, key
        assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION, key
        assert hass.states.get(entry.entity_id) is None, key
        assert entry.translation_key == f"{label}_{suffix}", key
        assert manager.entity_id_for(device_id, key) == entry.entity_id


async def test_enabled_companions_read_the_routine_in_the_words_of_the_domain(
    hass: HomeAssistant, home: Home, routines: MockConfigEntry, freezer: Any
) -> None:
    vacuum = add_device(
        hass, home.source, "vacuum", "Robot vacuum", "vacuum.robot_vacuum", "docked"
    )
    manager: RoutineManager = routines.runtime_data.manager
    await manager.async_opt_in(vacuum)
    await hass.async_block_till_done()

    manager, ids = await enable(hass, routines, freezer, vacuum)

    names = {key: hass.states.get(entity_id) for key, entity_id in ids.items()}
    assert {key: state.name for key, state in names.items() if state} == {
        "on_kind": "Robot vacuum Start timing",
        "on_sun_offset": "Robot vacuum Start sun offset",
        "off_kind": "Robot vacuum Return to dock timing",
        "off_sun_offset": "Robot vacuum Return to dock sun offset",
    }
    timing = names["on_kind"]
    assert timing is not None
    assert (timing.state, timing.attributes["options"]) == ("time", ["time", "sunrise", "sunset"])
    offset = names["on_sun_offset"]
    assert offset is not None
    assert offset.state == "unavailable"  # the side is a time: no offset applies
    assert offset.attributes["reason"] == "time_bound"
    assert (offset.attributes["min"], offset.attributes["max"]) == (-180, 180)
    assert (offset.attributes["step"], offset.attributes["mode"]) == (1, "box")
    assert offset.attributes["unit_of_measurement"] == "min"
    assert "device_class" not in offset.attributes


async def test_setting_a_kind_and_an_offset_writes_schema_2_inputs(
    hass: HomeAssistant, home: Home, routines: MockConfigEntry, clock: Clock, freezer: Any
) -> None:
    """The timing and offset controls write the inputs `compile` makes of the settings."""
    clock.set(clock.at(0, "12:00"))
    manager: RoutineManager = routines.runtime_data.manager
    await manager.async_opt_in(home.fan)
    await hass.async_block_till_done()
    manager, ids = await enable(hass, routines, freezer, home.fan)

    await call(hass, "select", "select_option", entity_id=ids["on_kind"], option="sunset")
    await call(hass, "number", "set_value", entity_id=ids["on_sun_offset"], value=-30)
    await call(hass, "select", "select_option", entity_id=ids["off_kind"], option="sunrise")
    await call(hass, "number", "set_value", entity_id=ids["off_sun_offset"], value=45)
    await flush(hass, freezer)

    view = manager.get(home.fan)
    assert view is not None
    settings = RoutineSettings(
        FAN,
        on_kind=TimeKind.SUNSET,
        on_sun_offset_min=-30,
        off_kind=TimeKind.SUNRISE,
        off_sun_offset_min=45,
    )
    assert view.settings == settings
    written = inputs_of(hass, view.automation_id)
    assert list(written) == list(compiler.INPUT_KEYS)
    assert (
        written == compiler.compile(settings, PROFILES["switch"], compiler.refs_of(written)).inputs
    )
    assert {key: written[key] for key in ("on_kind", "on_sun_offset", "off_kind")} == {
        "on_kind": "sunset",
        "on_sun_offset": "-00:30:00",
        "off_kind": "sunrise",
    }
    assert (written["on_at_sunset"], written["off_at_sunrise"]) == (True, True)
    assert (written["on_time_enabled"], written["off_time_enabled"]) == (False, False)
    assert written["crosses_midnight"] is True  # sunset to sunrise, by the nominal times
    assert written["late_sun_offset"] == "-00:15:00"
    assert state_of(hass, AUTOMATION) == "on"
    shown = {key: state_of(hass, entity_id) for key, entity_id in ids.items()}
    assert shown == {
        "on_kind": "sunset",
        "on_sun_offset": "-30",
        "off_kind": "sunrise",
        "off_sun_offset": "45",
    }


async def test_time_entity_unavailable_while_the_side_is_a_sun_bound(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """A time that follows the sun has no time of day to show: reason `sun_bound`."""
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    on_time = page(hass, home.fan)["on_time"].entity_id
    assert state_of(hass, on_time) == "17:00:00"

    result = await manager.async_update(home.fan, {"on_kind": "sunset"})
    await hass.async_block_till_done()

    assert result.problem is None
    state = hass.states.get(on_time)
    assert state is not None
    assert (state.state, state.attributes["reason"]) == ("unavailable", "sun_bound")
    assert manager.unavailable_reason(home.fan, "on_time") == "sun_bound"
    assert manager.unavailable_reason(home.fan, "off_time") is None
    assert manager.unavailable_reason(home.fan, "on_sun_offset") is None
    assert manager.unavailable_reason(home.fan, "on_kind") is None


async def test_offset_number_unavailable_while_the_side_is_a_time(
    hass: HomeAssistant, home: Home, routines: MockConfigEntry, freezer: Any
) -> None:
    """The twin: a sun offset applies only to a side that follows the sun, `time_bound`."""
    manager: RoutineManager = routines.runtime_data.manager
    await give_routine(hass, manager, home.fan, freezer, off_kind="sunset", off_sun_offset_min=15)
    manager, ids = await enable(hass, routines, freezer, home.fan)
    assert state_of(hass, ids["off_sun_offset"]) == "15"
    on_offset = hass.states.get(ids["on_sun_offset"])
    assert on_offset is not None
    assert (on_offset.state, on_offset.attributes["reason"]) == ("unavailable", "time_bound")

    await call(hass, "select", "select_option", entity_id=ids["off_kind"], option="time")

    off_offset = hass.states.get(ids["off_sun_offset"])
    assert off_offset is not None
    assert (off_offset.state, off_offset.attributes["reason"]) == ("unavailable", "time_bound")
    assert manager.unavailable_reason(home.fan, "off_sun_offset") == "time_bound"
    view = manager.get(home.fan)
    assert view is not None
    # Back to a time without one: the side is unset until a time is chosen.
    assert (view.settings.off_kind, view.settings.off_time) == (TimeKind.TIME, None)
    assert view.settings.off_sun_offset_min == 0


async def test_a_time_sent_alone_makes_its_side_a_time_again(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """`{"on_time": "07:00"}` from the API means 07:00, whatever the side followed."""
    await give_routine(hass, manager, home.fan, freezer, **DAYLIGHT)

    result = await manager.async_update(home.fan, {"on_time": "07:00"})
    assert result.view is not None
    assert (result.view.settings.on_kind, result.view.settings.on_time) == (
        TimeKind.TIME,
        time(7),
    )
    assert result.view.settings.off_kind is TimeKind.SUNSET  # the other side is untouched
    # A null time clears the side, the sun bound with it.
    result = await manager.async_update(home.fan, {"off_time": None})
    assert result.view is not None
    assert (result.view.settings.off_kind, result.view.settings.has_off) == (TimeKind.TIME, False)
    # A patch that names the kind too keeps it: the stray time is dropped.
    result = await manager.async_update(home.fan, {"on_time": "08:00", "on_kind": "sunrise"})
    assert result.view is not None
    assert (result.view.settings.on_kind, result.view.settings.on_time) == (
        TimeKind.SUNRISE,
        None,
    )


async def test_a_weekly_schedule_takes_the_place_of_a_sun_bound(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """Days set to Weekly schedule drops the sun bounds, as it drops the times (FR-R2)."""
    await give_routine(hass, manager, home.fan, freezer, **DAYLIGHT)

    result = await manager.async_update(home.fan, {"days": "weekly_schedule"})

    assert result.problem is None
    assert result.view is not None
    settings = result.view.settings
    assert (settings.days, settings.has_on, settings.has_off) == (
        Days.WEEKLY_SCHEDULE,
        False,
        False,
    )
    for key in ("on_time", "on_kind", "on_sun_offset", "off_kind", "off_sun_offset"):
        assert manager.unavailable_reason(home.fan, key) == "weekly_schedule", key
    # Naming a sun bound along with Weekly schedule is refused, as a time is.
    refused = await manager.async_update(home.fan, {"days": "weekly_schedule", "on_kind": "sunset"})
    assert refused.problem is not None
    assert refused.problem.translation_key == "times_with_weekly_schedule"


# --------------------------------------------------------------------------------------
# The manager follows the sun: catch up, the override, Skip next, the next action
# --------------------------------------------------------------------------------------


def daylight_store(device_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """The Store of an instance where the device already has the daylight routine."""
    data = StoreData(
        owned={
            entry["id"]: OwnedRecord(
                device_id=device_id,
                target_entity=FAN,
                last_hash=markers.config_hash(entry),
                last_valid_inputs=entry["use_blueprint"]["input"],
                alias_history=(ALIAS,),
            )
        },
        opted_in={device_id},
        blueprint_hash=maintenance.blueprint_hash(maintenance.shipped_blueprint_text()),
        blueprint_schema=compiler.BLUEPRINT_SCHEMA_VERSION,
    )
    return {"version": 1, "minor_version": 2, "key": STORAGE_KEY, "data": data.to_dict()}


@pytest.mark.parametrize(
    ("start", "before", "expected", "manual"),
    [
        # Day 1, three hours after sunrise: inside the window; the fan is off.
        (("sunrise", 180), "off", "on", False),
        # Day 1, two hours after sunset: outside it; the fan is on.
        (("sunset", 120), "on", "off", True),
    ],
    ids=["inside", "outside"],
)
async def test_catch_up_and_override_follow_a_sun_window(
    hass: HomeAssistant,
    home: Home,
    hass_storage: dict[str, Any],
    clock: Clock,
    freezer: Any,
    start: tuple[str, int],
    before: str,
    expected: str,
    manual: bool,
) -> None:
    """A cold start inside and outside a sun window, then a manual change against it.

    The start catches the fan up to the window. A change by hand that leaves the window's
    state turns the Manual override on, because the manager knows the sun window now (the
    attributor asks `routine_for`, which passes the sun lookup); a reconnect then keeps
    the device as it is, and the next sun bound runs and clears the override.
    """
    event, minutes = start
    clock.set(at(hass, event, 1, minutes))
    settings = RoutineSettings(
        FAN,
        on_kind=TimeKind.SUNRISE,
        on_sun_offset_min=30,
        off_kind=TimeKind.SUNSET,
        off_sun_offset_min=-30,
    )
    refs = compiler.HelperRefs(home.fan, override_entity=OVERRIDE, paused_until_entity=PAUSED)
    entry = {
        "id": markers.automation_id(home.fan),
        "alias": ALIAS,
        "description": markers.presentation("Living room fan", load_phrases("en")).description,
        "use_blueprint": {
            "path": markers.BLUEPRINT_PATH,
            "input": dict(compiler.compile(settings, PROFILES["switch"], refs).inputs),
        },
    }
    config_dir = Path(hass.config.config_dir)
    (config_dir / AUTOMATION_CONFIG_PATH).write_text(dump([entry]), encoding="utf-8")
    hass_storage[STORAGE_KEY] = daylight_store(home.fan, entry)
    await async_install_blueprint(hass)
    home.switch.device_change(on=before == "on")

    # Home Assistant starts with the routine in `automations.yaml` and the integration.
    hass.set_state(CoreState.not_running)
    assert await async_setup_component(hass, "automation", {"automation": [entry]})
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_TITLE,
        unique_id=DOMAIN,
        minor_version=DeviceRoutinesConfigFlow.MINOR_VERSION,
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_start()
    await hass.async_block_till_done()
    manager: RoutineManager = config_entry.runtime_data.manager

    assert home.switch.state_now == expected
    view = manager.get(home.fan)
    assert view is not None
    assert (view.status, view.override) == (Status.ACTIVE, False)
    runtime = manager.routine_for(FAN)
    assert runtime is not None
    assert runtime.expected == expected

    # Past the attribution's start grace, a change by hand against the window.
    await clock.advance(seconds=31)
    home.switch.device_change(on=manual)
    await hass.async_block_till_done()
    view = manager.get(home.fan)
    assert view is not None
    assert (view.override, view.last_change_source) == (True, Source.DEVICE)
    assert state_of(hass, OVERRIDE) == "on"
    # A reconnect catches nothing up while the override holds.
    home.switch.set_available(False)
    await hass.async_block_till_done()
    home.switch.set_available(True)
    await clock.advance(seconds=15)
    assert home.switch.state_now == ("on" if manual else "off")

    # The next sun bound runs and clears the override: tonight's end or tomorrow's start.
    following = at(hass, "sunset", 1, -30) if expected == "on" else at(hass, "sunrise", 2, 30)
    await clock.to(following - SECOND)
    await run_past(hass, freezer, following)
    assert state_of(hass, OVERRIDE) == "off"
    view = manager.get(home.fan)
    assert view is not None
    assert view.override is False
    assert home.switch.state_now == ("off" if expected == "on" else "on")


async def test_skip_next_on_a_sun_start_pairs_its_end(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    """D18: Skip next on a sun start skips its end too, until a minute after sunset - 30."""
    clock.set(clock.at(0, "04:00"))
    await give_routine(hass, manager, home.fan, freezer, **DAYLIGHT)
    skipped = async_capture_events(hass, compiler.EVENT_ACTION_SKIPPED)
    start, end = at(hass, "sunrise", 0, 30), at(hass, "sunset", 0, -30)
    button = page(hass, home.fan)["skip_next"].entity_id

    await call(hass, "button", "press", entity_id=button)

    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.SKIPPING
    assert view.skipped_action == Occurrence(start, Verb.ON)
    assert view.paused_until == end + timedelta(minutes=1)
    # The next action that really runs is tomorrow's start.
    assert view.next_action == Occurrence(at(hass, "sunrise", 1, 30), Verb.ON)
    await clock.to(start + SECOND)
    assert home.switch.state_now == "off"
    await clock.to(end + timedelta(minutes=2))
    assert home.switch.state_now == "off"
    assert [(event.data["trigger_id"], event.data["action"]) for event in skipped] == [
        ("scheduled_on", "on"),
        ("scheduled_off", "off"),
    ]
    view = manager.get(home.fan)
    assert view is not None
    assert (view.status, view.paused_until) == (Status.ACTIVE, None)
    await clock.to(at(hass, "sunrise", 1, 30) + SECOND)
    assert home.switch.state_now == "on"


async def test_next_action_and_sentence_of_a_sun_routine(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    """The view, the Schedule and the hub name the sun instants the blueprint runs at."""
    clock.set(clock.at(0, "12:00"))  # Monday noon
    await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_kind="sunset",
        on_sun_offset_min=30,
        off_kind="sunrise",
        days="weekdays",
    )
    sunset = at(hass, "sunset", 0, 30)

    view = manager.get(home.fan)
    assert view is not None
    assert view.next_action == Occurrence(sunset, Verb.ON)
    clock_text = WRITER.clock(sunset.time().replace(tzinfo=None))
    assert view.sentence == f"On at {clock_text}"
    (item,) = (item for item in view.items if item.automation_entity == AUTOMATION)
    assert item.parts == (
        "Sunset + 30 min, Weekdays only: on",
        "Sunrise, Tue, Wed, Thu, Fri, Sat only: off",
    )
    assert item.next_run == sunset
    (hub,) = manager.hub_routines()
    assert hub.next_action == view.sentence

    # After the start, the next action is Tuesday's sunrise; Friday's window ends on
    # Saturday, and no window starts at the weekend.
    await clock.to(sunset + SECOND)
    assert home.switch.state_now == "on"
    view = manager.get(home.fan)
    assert view is not None
    assert view.next_action == Occurrence(at(hass, "sunrise", 1, 0), Verb.OFF)
    await clock.to(at(hass, "sunrise", 5, 0) + SECOND)  # Saturday morning
    view = manager.get(home.fan)
    assert view is not None
    assert view.next_action == Occurrence(at(hass, "sunset", 7, 30), Verb.ON)  # Monday


async def test_only_when_gates_the_starts_in_the_schedule_line(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """FR-R9: the lines the blueprint gates read the conditions; an end never does."""
    guards = [
        {"condition": "state", "entity_id": "input_boolean.guest_mode", "state": "off"},
        {"condition": "numeric_state", "entity_id": "sensor.patio_light_level", "below": 20},
    ]
    await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_kind="sunset",
        off_time=time(23),
        extra_conditions=guards,
    )

    view = manager.get(home.fan)
    assert view is not None
    (item,) = (item for item in view.items if item.automation_entity == AUTOMATION)
    assert item.parts == ("Sunset: on (if 2 conditions pass)", "11:00 PM: off")
    # Counted conditions are understood: the item is no custom logic, as the index says.
    assert item.custom_logic is False
