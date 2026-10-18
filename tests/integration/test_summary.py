"""The SummaryCoordinator and the Schedule sensor in a running Home Assistant (TECH_SPEC 4.4)."""

from __future__ import annotations

import ast
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from homeassistant.components import automation as automation_component
from homeassistant.components.automation import DATA_COMPONENT
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import compiler, domains, ha_adapter, markers
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.entity import linked_device_info
from custom_components.device_routines.models import (
    Days,
    Occurrence,
    RoutineSettings,
    Status,
    SummaryItem,
    TimeKind,
    Verb,
)
from custom_components.device_routines.sentence import STATE_CAP, Writer, load_phrases
from custom_components.device_routines.settings import GlobalSettings
from custom_components.device_routines.summary import (
    DEBOUNCE_SECONDS,
    KIND_AUTOMATION,
    KIND_ROUTINE,
    SOURCE_PARSER,
    RoutineItemsProvider,
    RoutineSummary,
    SummaryCoordinator,
    _attribute_moment,
    _held_time,
    _moment,
    _NameLookup,
    schedule_unique_id,
)

TZ = "America/Los_Angeles"
LA = ZoneInfo(TZ)
FAN = "fan.living_room_fan"
LAMP = "light.desk_lamp"

# Daily windows and timers; most tests start on Monday 2026-10-19 at 08:00.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


def automation(key: str, triggers: Any, actions: Any, **extra: Any) -> dict[str, Any]:
    return {
        "id": key,
        "alias": key.replace("_", " ").title(),
        "triggers": triggers,
        "actions": actions,
        **extra,
    }


def at(time_text: str, key: str | None = None) -> dict[str, Any]:
    trigger: dict[str, Any] = {"trigger": "time", "at": time_text}
    if key:
        trigger["id"] = key
    return trigger


def action(service: str, target: dict[str, Any]) -> dict[str, Any]:
    return {"action": service, "target": target}


WINDOW = automation(
    "fan_window",
    [at("17:00", "on"), at("09:00", "off")],
    [
        {
            "choose": [
                {
                    "conditions": [{"condition": "trigger", "id": "on"}],
                    "sequence": [action("fan.turn_on", {"entity_id": FAN})],
                },
                {
                    "conditions": [{"condition": "trigger", "id": "off"}],
                    "sequence": [action("fan.turn_off", {"entity_id": FAN})],
                },
            ]
        }
    ],
)


@pytest.fixture
async def home(hass: HomeAssistant, freezer: Any) -> dict[str, Any]:
    """A fan device in a living room on the ground floor, a desk lamp with a label."""
    await hass.config.async_set_time_zone(TZ)
    hass.config.country = "US"
    freezer.move_to(datetime(2026, 10, 19, 8, tzinfo=LA))
    floor = fr.async_get(hass).async_create("Ground floor")
    area = ar.async_get(hass).async_create("Living room", floor_id=floor.floor_id)
    label = lr.async_get(hass).async_create("Evening")
    other = MockConfigEntry(domain="other", title="Other")
    other.add_to_hass(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    fan = devices.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "fan")}, name="Living room fan"
    )
    devices.async_update_device(fan.id, area_id=area.id)
    lamp = devices.async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "lamp")}, name="Desk lamp"
    )
    devices.async_update_device(lamp.id, labels={label.label_id})
    fan_entry = entities.async_get_or_create(
        "fan", "other", "fan", device_id=fan.id, suggested_object_id="living_room_fan"
    )
    entities.async_get_or_create(
        "light", "other", "lamp", device_id=lamp.id, suggested_object_id="desk_lamp"
    )
    hass.states.async_set(FAN, "off", {"friendly_name": "Living room fan"})
    hass.states.async_set(LAMP, "off", {"friendly_name": "Desk lamp"})
    hass.states.async_set("binary_sensor.door", "off", {"friendly_name": "Front door"})
    return {
        "floor": floor,
        "area": area,
        "label": label,
        "fan": fan,
        "lamp": lamp,
        "fan_entry": fan_entry,
    }


async def start(
    hass: HomeAssistant, automations: list[dict[str, Any]], options: dict[str, Any] | None = None
) -> MockConfigEntry:
    assert await async_setup_component(hass, "automation", {"automation": automations})
    await hass.async_block_till_done()
    entry = MockConfigEntry(
        domain=DOMAIN, title=INTEGRATION_TITLE, unique_id=DOMAIN, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def schedule_entity(hass: HomeAssistant, device_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, schedule_unique_id(device_id))


def coordinator(entry: MockConfigEntry) -> SummaryCoordinator:
    summary: SummaryCoordinator = entry.runtime_data.summary
    return summary


async def settle(hass: HomeAssistant, freezer: Any, seconds: float = DEBOUNCE_SECONDS + 1) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# Discovery and the sensor
# --------------------------------------------------------------------------------------


async def test_a_window_automation_gives_the_device_a_schedule(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    await start(hass, [WINDOW])

    entity_id = schedule_entity(hass, home["fan"].id)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Off at 9:00 AM"
    assert state.attributes["friendly_name"] == "Living room fan Schedule"
    items = state.attributes["items"]
    assert [item["summary"] for item in items] == ["9:00 AM: off", "5:00 PM: on"]
    assert items[0] == {
        "kind": "automation",
        "automation": "automation.fan_window",
        "alias": "Fan Window",
        "summary": "9:00 AM: off",
        "next_run": "2026-10-19T09:00:00-07:00",
        "source": "parser",
        "enabled": True,
    }
    assert state.attributes["paused_until"] is None
    assert state.attributes["skipped_action"] is None
    assert state.attributes["conflicts"] == []
    # The lamp has no automation acting on it, so it has no sensor (FR-S4).
    assert schedule_entity(hass, home["lamp"].id) is None


async def test_the_sensor_lands_on_a_record_linked_to_the_users_device(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    entry = await start(hass, [WINDOW])

    entity_id = schedule_entity(hass, home["fan"].id)
    assert entity_id is not None
    registered = er.async_get(hass).async_get(entity_id)
    assert registered is not None
    record = dr.async_get(hass).async_get(registered.device_id or "")
    assert record is not None
    assert record.identifiers == home["fan"].identifiers
    assert record.name == "Living room fan"
    # The linked record belongs to this entry and never gets a Schedule sensor itself.
    assert record.config_entry_id == entry.entry_id
    assert record.id not in coordinator(entry).summaries


async def test_area_floor_label_and_device_targets_are_discovered(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    entry = await start(
        hass,
        [
            automation(
                "by_area", [at("07:00")], [action("fan.turn_on", {"area_id": home["area"].id})]
            ),
            automation(
                "by_floor",
                [at("07:10")],
                [action("fan.turn_off", {"floor_id": home["floor"].floor_id})],
            ),
            automation(
                "by_label",
                [at("21:00")],
                [action("light.turn_off", {"label_id": home["label"].label_id})],
            ),
            automation(
                "by_device", [at("07:20")], [action("fan.toggle", {"device_id": home["fan"].id})]
            ),
            automation(
                "by_registry_id",
                [{"trigger": "state", "entity_id": "binary_sensor.door", "to": "on"}],
                [
                    {
                        "device_id": home["fan"].id,
                        "domain": "fan",
                        "type": "turn_on",
                        "entity_id": home["fan_entry"].id,
                    }
                ],
            ),
        ],
    )
    summaries = coordinator(entry).summaries

    fan_lines = [item.summary for item in summaries[home["fan"].id].items]
    assert fan_lines == [
        "7:00 AM: on",
        "7:10 AM: off",
        "7:20 AM: toggle",
        "When Front door turns on: on",
    ]
    assert [item.summary for item in summaries[home["lamp"].id].items] == ["9:00 PM: off"]


async def test_automations_that_only_read_a_device_are_ignored(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    entry = await start(
        hass,
        [
            automation(
                "reads_fan",
                [{"trigger": "state", "entity_id": FAN, "to": "on"}],
                [action("light.turn_on", {"entity_id": LAMP})],
            )
        ],
    )

    assert home["fan"].id not in coordinator(entry).summaries
    assert [item.summary for item in coordinator(entry).summaries[home["lamp"].id].items] == [
        "When Living room fan turns on: on"
    ]


async def test_custom_logic_and_event_lines(hass: HomeAssistant, home: dict[str, Any]) -> None:
    await start(
        hass,
        [
            automation(
                "templated",
                [{"trigger": "template", "value_template": "{{ true }}"}],
                [action("fan.turn_on", {"entity_id": FAN})],
            ),
            automation(
                "after_on",
                [{"trigger": "state", "entity_id": FAN, "to": "on", "for": "01:00:00"}],
                [action("fan.turn_off", {"entity_id": FAN})],
            ),
        ],
    )

    state = hass.states.get(schedule_entity(hass, home["fan"].id) or "")
    assert state is not None
    assert state.state == "Off 60 min after it turns on"
    assert [(i["summary"], i["source"]) for i in state.attributes["items"]] == [
        ("Off 60 min after it turns on", "parser"),
        ("Automation: Templated (custom logic)", "none"),
    ]


# --------------------------------------------------------------------------------------
# Recompute triggers
# --------------------------------------------------------------------------------------


async def test_the_next_run_timer_moves_the_state_on(
    hass: HomeAssistant, home: dict[str, Any], freezer: Any
) -> None:
    await start(hass, [WINDOW])
    entity_id = schedule_entity(hass, home["fan"].id) or ""

    await settle(hass, freezer, seconds=3600 + 1)

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "On at 5:00 PM"

    freezer.move_to(datetime(2026, 10, 19, 17, 0, 2, tzinfo=LA))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "Off Tue 9:00 AM"  # type: ignore[union-attr]


async def test_turning_an_automation_off_marks_its_items(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    await start(hass, [WINDOW])
    entity_id = schedule_entity(hass, home["fan"].id) or ""

    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": "automation.fan_window"}, blocking=True
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert [item["enabled"] for item in state.attributes["items"]] == [False, False]
    assert all(item["next_run"] is None for item in state.attributes["items"])
    # No enabled item: nothing is planned, and the state says why (live validation A, F2).
    # One automation reads in the singular, however many lines it has.
    assert state.state == "Automation off"


async def test_a_device_whose_automations_are_all_off_reads_automations_off(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    """F2: two automations off read "Automations off"; one turned back on names its action."""
    early = automation("early_off", [at("08:30")], [action("fan.turn_off", {"entity_id": FAN})])
    await start(hass, [WINDOW, early])
    entity_id = schedule_entity(hass, home["fan"].id) or ""

    for automation_entity in ("automation.fan_window", "automation.early_off"):
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": automation_entity}, blocking=True
        )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "Automations off"  # type: ignore[union-attr]

    await hass.services.async_call(
        "automation", "turn_on", {"entity_id": "automation.early_off"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "Off at 8:30 AM"  # type: ignore[union-attr]


async def test_a_reload_rebuilds_the_index_after_the_debounce(
    hass: HomeAssistant, home: dict[str, Any], freezer: Any
) -> None:
    entry = await start(hass, [WINDOW])

    hass.bus.async_fire(ha_adapter.EVENT_AUTOMATION_RELOADED)
    await hass.async_block_till_done()
    builds = 0
    original = coordinator(entry)._build_index

    def counting() -> Any:
        nonlocal builds
        builds += 1
        return original()

    coordinator(entry)._build_index = counting  # type: ignore[method-assign]
    hass.bus.async_fire(ha_adapter.EVENT_AUTOMATION_RELOADED)
    hass.bus.async_fire(ha_adapter.EVENT_AUTOMATION_RELOADED)
    await hass.async_block_till_done()
    assert builds == 0
    await settle(hass, freezer)
    assert builds == 1


async def test_registry_changes_rebuild_but_own_entities_do_not(
    hass: HomeAssistant, home: dict[str, Any], freezer: Any
) -> None:
    entry = await start(hass, [WINDOW])
    summary = coordinator(entry)
    calls: list[str] = []
    original = summary._build_index

    def counting() -> Any:
        calls.append("build")
        return original()

    summary._build_index = counting  # type: ignore[method-assign]

    # This integration's own registry entries are ignored.
    own = schedule_entity(hass, home["fan"].id) or ""
    er.async_get(hass).async_update_entity(own, name="Fan plan")
    await settle(hass, freezer)
    assert calls == []

    # Moving the lamp into the living room is a foreign change.
    dr.async_get(hass).async_update_device(home["lamp"].id, area_id=home["area"].id)
    await settle(hass, freezer)
    assert calls == ["build"]
    assert summary._foreign_change({"area_id": "x"}) is True


async def test_an_entity_time_change_refreshes_the_view(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    hass.states.async_set("input_datetime.wake", "07:30:00", {"has_date": False, "has_time": True})
    await start(
        hass,
        [
            automation(
                "wake", [at("input_datetime.wake")], [action("fan.turn_on", {"entity_id": FAN})]
            )
        ],
    )
    entity_id = schedule_entity(hass, home["fan"].id) or ""
    assert hass.states.get(entity_id).state == "On Tue 7:30 AM"  # type: ignore[union-attr]

    hass.states.async_set("input_datetime.wake", "09:15:00", {"has_date": False, "has_time": True})
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "On at 9:15 AM"  # type: ignore[union-attr]


async def test_an_automation_removed_drops_the_sensor(
    hass: HomeAssistant, home: dict[str, Any], freezer: Any
) -> None:
    entry = await start(hass, [WINDOW])
    assert schedule_entity(hass, home["fan"].id) is not None

    with patch.object(ha_adapter, "automation_references", return_value=[]):
        hass.states.async_remove("automation.fan_window")
        await settle(hass, freezer)

    assert coordinator(entry).summaries == {}
    assert schedule_entity(hass, home["fan"].id) is None


async def test_startup_before_home_assistant_runs_rebuilds_on_started(
    hass: HomeAssistant, home: dict[str, Any], freezer: Any
) -> None:
    hass.set_state(CoreState.not_running)
    entry = await start(hass, [WINDOW])
    builds: list[int] = []
    original = coordinator(entry)._build_index

    def counting() -> Any:
        builds.append(1)
        return original()

    coordinator(entry)._build_index = counting  # type: ignore[method-assign]

    hass.bus.async_fire("homeassistant_started")
    await settle(hass, freezer)

    assert builds == [1]


async def test_core_config_changes_refresh_the_view(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    entry = await start(hass, [WINDOW])
    entity_id = schedule_entity(hass, home["fan"].id) or ""

    hass.config.country = "DE"
    hass.bus.async_fire("core_config_updated")
    await hass.async_block_till_done()

    # The coordinator's settings say auto, so the country now resolves to 24 hours.
    assert coordinator(entry).settings.time_format == "auto"
    assert hass.states.get(entity_id).state == "Off at 09:00"  # type: ignore[union-attr]


# --------------------------------------------------------------------------------------
# Scope and lifecycle
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["none", "routines"])
async def test_scopes_without_sensors(
    hass: HomeAssistant, home: dict[str, Any], scope: str
) -> None:
    entry = await start(hass, [WINDOW], options={"schedule_scope": scope})

    assert home["fan"].id in coordinator(entry).summaries
    assert schedule_entity(hass, home["fan"].id) is None


async def test_a_scope_change_removes_stale_sensors_on_reload(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    entry = await start(hass, [WINDOW])
    assert schedule_entity(hass, home["fan"].id) is not None

    hass.config_entries.async_update_entry(entry, options={"schedule_scope": "none"})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert schedule_entity(hass, home["fan"].id) is None


async def test_unload_stops_the_coordinator(hass: HomeAssistant, home: dict[str, Any]) -> None:
    entry = await start(hass, [WINDOW])
    summary = coordinator(entry)

    assert await hass.config_entries.async_unload(entry.entry_id)

    assert summary._unsubscribe == []
    assert summary._timer is None


def test_no_interval_or_time_pattern_listener_exists() -> None:
    """TECH_SPEC 4.4 and 12: nothing in the integration polls."""
    component = Path(__file__).resolve().parents[2] / "custom_components" / "device_routines"
    forbidden = {
        "async_track_time_interval",
        "async_track_time_change",
        "async_track_utc_time_change",
        "track_time_interval",
    }
    for path in component.glob("*.py"):
        names = {
            alias.name
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert not names & forbidden, path.name


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


async def test_held_time(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone(TZ)
    hass.states.async_set("input_datetime.t", "07:30:00", {"has_date": False})
    hass.states.async_set("input_datetime.d", "2026-10-20 07:30:00", {"has_date": True})
    hass.states.async_set("sensor.ts", "2026-10-20T14:30:00+00:00")
    hass.states.async_set("sensor.bad", "soon")
    hass.states.async_set("sensor.unknown", "unknown")

    assert str(_held_time(hass.states.get("input_datetime.t"))) == "07:30:00"
    assert _held_time(hass.states.get("input_datetime.d")) == datetime(
        2026, 10, 20, 7, 30, tzinfo=LA
    )
    assert _held_time(hass.states.get("sensor.ts")) == datetime(
        2026, 10, 20, 14, 30, tzinfo=ZoneInfo("UTC")
    )
    assert _held_time(hass.states.get("sensor.bad")) is None
    assert _held_time(hass.states.get("sensor.unknown")) is None
    assert _held_time(None) is None


async def test_adapter_check_and_config_reads(hass: HomeAssistant) -> None:
    # A bare core has no automation reload service and no helper commands; reads work.
    assert ha_adapter.check(hass).works(ha_adapter.CAPABILITY_READ)
    assert ha_adapter.automation_config(hass, "automation.none") is None
    assert ha_adapter.automation_references(hass) == []
    report = ha_adapter.AdapterReport(failed=("read_automations",))
    assert not report.works("read_automations")
    assert report.works("write_automations")


async def test_sun_triggers_window_entities_and_unknown_names(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    hass.states.async_set("input_datetime.end", "23:00:00", {"has_date": False})
    entry = await start(
        hass,
        [
            automation(
                "at_sunset",
                [{"trigger": "sun", "event": "sunset"}],
                [action("fan.turn_on", {"entity_id": FAN})],
                conditions=[{"condition": "time", "before": "input_datetime.end"}],
            ),
            automation(
                "ghost_trigger",
                [{"trigger": "state", "entity_id": "binary_sensor.ghost", "to": "on"}],
                [action("fan.turn_off", {"entity_id": FAN})],
            ),
        ],
    )
    items = coordinator(entry).summaries[home["fan"].id].items

    assert items[0].summary == "Sunset, before the time in end: on"
    assert items[0].next_run is not None
    assert items[1].summary == "When binary_sensor.ghost turns on: off"


async def test_a_device_removed_before_the_rebuild_is_skipped(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    entry = await start(hass, [WINDOW])

    dr.async_get(hass).async_remove_device(home["fan"].id)
    coordinator(entry)._refresh_views()

    assert coordinator(entry).summaries == {}


async def test_a_config_the_parser_refuses_is_skipped(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    refs = ha_adapter.AutomationRefs(
        entity_id="automation.broken",
        config={"triggers": []},
        entities=frozenset({FAN}),
        devices=frozenset(),
        areas=frozenset(),
        floors=frozenset(),
        labels=frozenset(),
    )
    with patch.object(ha_adapter, "automation_references", return_value=[refs]):
        entry = await start(hass, [])

    assert coordinator(entry).summaries == {}


async def test_name_lookup_is_a_mapping(hass: HomeAssistant, home: dict[str, Any]) -> None:
    lookup = _NameLookup(hass)

    assert lookup[FAN] == "Living room fan"
    assert lookup.get("sensor.missing") is None
    assert len(lookup) == len(list(lookup)) == hass.states.async_entity_ids_count()


async def test_adapter_reports_missing_helpers_and_skips_configless_automations(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert await async_setup_component(hass, "automation", {"automation": []})
    hass.states.async_set("automation.restored", "unavailable")
    assert ha_adapter.automation_references(hass) == []

    monkeypatch.delattr(automation_component, "labels_in_automation")
    report = ha_adapter.check(hass)
    assert ha_adapter.CAPABILITY_READ in report.failed
    assert "labels_in_automation" in report.details["read_automations"]


def test_linked_device_info_by_connections() -> None:
    info = linked_device_info(frozenset(), frozenset({("mac", "aa:bb")}), "Plug")
    assert info == {"connections": {("mac", "aa:bb")}, "name": "Plug"}


async def test_identical_items_of_one_automation_read_once(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    entry = await start(
        hass,
        [
            automation(
                "scripted_twice",
                [{"trigger": "event", "event_type": "a"}],
                [
                    action("fan.turn_on", {"entity_id": FAN}),
                    {"delay": "{{ 5 }}"},
                    action("fan.turn_on", {"entity_id": FAN}),
                ],
            )
        ],
    )

    items = coordinator(entry).summaries[home["fan"].id].items
    assert [item.summary for item in items] == ["Automation: Scripted Twice (custom logic)"]


async def test_an_entity_time_that_is_not_known_has_no_run(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    hass.states.async_set("input_datetime.wake", "unknown", {"has_date": False})
    entry = await start(
        hass,
        [
            automation(
                "wake", [at("input_datetime.wake")], [action("fan.turn_on", {"entity_id": FAN})]
            )
        ],
    )

    items = coordinator(entry).summaries[home["fan"].id].items
    assert items[0].summary == "The time in wake: on"
    assert items[0].next_run is None


# --------------------------------------------------------------------------------------
# Routines (Build A lane 7): the provider, the state forms, owned and detached automations
# --------------------------------------------------------------------------------------

ROUTINE_ENTITY = "automation.routine_living_room_fan"
ROUTINE_ALIAS = "Routine: Living room fan"
TIMER = "timer.routine_living_room_fan"
WEEKLY_HELPER = "schedule.routine_living_room_fan"
NIGHTLY = RoutineSettings(target_entity=FAN, on_time=time(17), off_time=time(9))

# A stand in for the shipped blueprint at the M2 path: every input of the contract, and a
# body the parser reads ("5:00 PM: on"), so an owned automation is discoverable.
ROUTINE_BLUEPRINT = "\n".join(
    [
        "blueprint:",
        "  name: Device routine test double",
        "  domain: automation",
        "  input:",
        *(f"    {key}:" for key in compiler.INPUT_KEYS),
        "triggers:",
        "  - trigger: time",
        "    at: !input on_time",
        "actions:",
        "  - action: fan.turn_on",
        "    target:",
        "      entity_id: !input target_entity",
        "",
    ]
)


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=LA)


class FakeProvider:
    """A RoutineItemsProvider the way the manager will be one, holding canned summaries."""

    def __init__(self) -> None:
        self.summaries: dict[str, RoutineSummary] = {}
        self.asked: list[str] = []

    def routine_summary(self, device_id: str) -> RoutineSummary | None:
        self.asked.append(device_id)
        return self.summaries.get(device_id)


def routine_item(
    summary: str = "5:00 PM to 9:00 AM", next_run: datetime | None = None
) -> SummaryItem:
    return SummaryItem(
        kind=KIND_ROUTINE,
        automation_entity=ROUTINE_ENTITY,
        alias=ROUTINE_ALIAS,
        summary=summary,
        next_run=next_run,
        source=SOURCE_PARSER,
        enabled=True,
        custom_logic=False,
    )


def routine_summary(
    status: Status = Status.ACTIVE,
    paused_until: datetime | None = None,
    skipped: Occurrence | None = None,
    items: tuple[SummaryItem, ...] | None = None,
    settings: RoutineSettings | None = None,
) -> RoutineSummary:
    return RoutineSummary(
        items=(routine_item(),) if items is None else items,
        paused_until=paused_until,
        skipped_action=skipped,
        status=status,
        settings=settings,
    )


def routine_config(
    device_id: str, settings: RoutineSettings = NIGHTLY, **refs: str
) -> dict[str, Any]:
    """An owned routine automation (M1 and M2) with the compiler's inputs."""
    profile = domains.profile_for("fan")
    assert profile is not None
    compiled = compiler.compile(settings, profile, compiler.HelperRefs(device_id, **refs))
    return {
        "id": markers.automation_id(device_id),
        "alias": ROUTINE_ALIAS,
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": dict(compiled.inputs)},
    }


@pytest.fixture
def routine_blueprint(hass: HomeAssistant, tmp_path: Path) -> None:
    """Put the stand in blueprint at the M2 path of a scratch config directory."""
    hass.config.config_dir = str(tmp_path)
    path = tmp_path / "blueprints" / "automation" / markers.BLUEPRINT_PATH
    path.parent.mkdir(parents=True)
    path.write_text(ROUTINE_BLUEPRINT, encoding="utf-8")


def sensor_state(hass: HomeAssistant, device_id: str) -> State:
    state = hass.states.get(schedule_entity(hass, device_id) or "")
    assert state is not None
    return state


async def with_provider(entry: MockConfigEntry, provider: FakeProvider) -> SummaryCoordinator:
    summary = coordinator(entry)
    summary.set_routine_provider(provider)
    await summary.hass.async_block_till_done()
    return summary


def test_the_fake_provider_meets_the_protocol() -> None:
    provider: RoutineItemsProvider = FakeProvider()
    assert provider.routine_summary("device") is None


async def test_a_routine_item_sorts_above_automation_items(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    fan = home["fan"].id
    early = automation("early_off", [at("08:30")], [action("fan.turn_off", {"entity_id": FAN})])
    entry = await start(hass, [routine_config(fan), early])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary(items=(routine_item(next_run=local(19, 9)),))

    await with_provider(entry, provider)

    state = sensor_state(hass, fan)
    items = state.attributes["items"]
    # The routine sorts first although the hand written action runs earlier, and the owned
    # automation is not read a second time: the provider's item is its line.
    assert [(item["kind"], item["summary"]) for item in items] == [
        ("routine", "5:00 PM to 9:00 AM"),
        ("automation", "8:30 AM: off"),
    ]
    assert items[0]["next_run"] == "2026-10-19T09:00:00-07:00"
    assert state.state == "Off at 8:30 AM"
    assert state.attributes["paused_until"] is None
    assert state.attributes["skipped_action"] is None


async def test_an_active_routine_names_its_next_action_from_its_inputs(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    fan = home["fan"].id
    entry = await start(hass, [routine_config(fan)])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary()

    await with_provider(entry, provider)

    # Monday 08:00 inside the 17:00 to 09:00 window: the routine's own off is next.
    assert sensor_state(hass, fan).state == "Off at 9:00 AM"


async def test_the_state_reads_skipped_paused_and_routine_off(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None, freezer: Any
) -> None:
    """FR-S4 and the FR-R11 acceptance: Wednesday 15:00, a 17:00 to 09:00 window."""
    freezer.move_to(local(21, 15))
    fan = home["fan"].id
    entry = await start(hass, [routine_config(fan)])
    provider = FakeProvider()
    summary = await with_provider(entry, provider)

    def show(routine: RoutineSummary) -> State:
        provider.summaries[fan] = routine
        summary.async_refresh_device(fan)
        return sensor_state(hass, fan)

    # Skip next skipped tonight's start (and its end); the state names what really runs.
    skipping = show(
        routine_summary(Status.SKIPPING, local(22, 9, 1), Occurrence(local(21, 17), Verb.ON))
    )
    assert skipping.state == "Skipped, on Thu 5:00 PM"
    assert skipping.attributes["paused_until"] == "2026-10-22T09:01:00-07:00"
    assert skipping.attributes["skipped_action"] == "5:00 PM: on"
    assert skipping.attributes["items"][0]["summary"] == "5:00 PM to 9:00 AM"

    pressed_again = show(
        routine_summary(Status.SKIPPING, local(23, 9, 1), Occurrence(local(22, 17), Verb.ON))
    )
    assert pressed_again.state == "Skipped, on Fri 5:00 PM"
    assert pressed_again.attributes["skipped_action"] == "Thu 5:00 PM: on"

    paused = show(routine_summary(Status.PAUSED, local(25, 18)))
    assert paused.state == "Paused until Sun 6:00 PM"
    assert paused.attributes["paused_until"] == "2026-10-25T18:00:00-07:00"
    assert paused.attributes["skipped_action"] is None

    states = [skipping.state, pressed_again.state, paused.state]
    for status in (Status.OFF, Status.INVALID, Status.MISSING_TARGET):
        off = show(routine_summary(status))
        assert off.state == "Routine off"
        assert off.attributes["paused_until"] is None
        states.append(off.state)
    assert all(len(text) <= STATE_CAP for text in states)

    # A pause that ended is over, whatever the status still says.
    assert show(routine_summary(Status.PAUSED, local(21, 14))).state == "On at 5:00 PM"


async def test_hand_written_lines_are_unchanged_by_a_pause(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    fan = home["fan"].id
    entry = await start(hass, [routine_config(fan), WINDOW])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary()
    summary = await with_provider(entry, provider)
    active = sensor_state(hass, fan)

    provider.summaries[fan] = routine_summary(Status.PAUSED, local(25, 18))
    summary.async_refresh_device(fan)
    paused = sensor_state(hass, fan)

    def hand_written(state: State) -> list[dict[str, Any]]:
        return [item for item in state.attributes["items"] if item["kind"] == "automation"]

    assert hand_written(paused) == hand_written(active)
    assert [item["summary"] for item in hand_written(paused)] == ["9:00 AM: off", "5:00 PM: on"]
    assert all(item["next_run"] is not None for item in hand_written(paused))
    assert paused.state == "Paused until Sun 6:00 PM"


async def test_refresh_device_recomputes_one_device_without_rebuilding_the_index(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    fan, lamp = home["fan"].id, home["lamp"].id
    lamp_off = automation(
        "lamp_off", [at("21:00")], [action("light.turn_off", {"entity_id": LAMP})]
    )
    entry = await start(hass, [routine_config(fan), lamp_off])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary()
    summary = await with_provider(entry, provider)
    builds: list[int] = []
    original = summary._build_index

    def counting() -> Any:
        builds.append(1)
        return original()

    summary._build_index = counting  # type: ignore[method-assign]
    lamp_updates: list[int] = []
    summary.async_add_listener(lamp, lambda: lamp_updates.append(1))
    provider.asked.clear()
    lamp_before = summary.summaries[lamp]

    provider.summaries[fan] = routine_summary(Status.PAUSED, local(25, 18))
    summary.async_refresh_device(fan)
    await hass.async_block_till_done()

    assert builds == []
    assert provider.asked == [fan]
    assert lamp_updates == []
    assert summary.summaries[lamp] is lamp_before
    assert sensor_state(hass, fan).state == "Paused until Sun 6:00 PM"

    # Nothing changed: nothing is pushed.
    fan_updates: list[int] = []
    summary.async_add_listener(fan, lambda: fan_updates.append(1))
    summary.async_refresh_device(fan)
    assert fan_updates == []


async def test_a_detached_routine_reads_as_detached_through_the_parser(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    """Take control kept M1 and dropped M2 (Stage 0 V8): an automation like any other."""
    fan, lamp = home["fan"].id, home["lamp"].id
    entry = await start(
        hass,
        [
            automation(
                markers.automation_id(fan),
                [at("17:00")],
                [action("fan.turn_on", {"entity_id": FAN})],
                alias=ROUTINE_ALIAS,
            ),
            automation(
                markers.automation_id(lamp),
                [{"trigger": "template", "value_template": "{{ true }}"}],
                [action("light.turn_on", {"entity_id": LAMP})],
                alias="Routine: Desk lamp",
            ),
        ],
    )

    fan_items = sensor_state(hass, fan).attributes["items"]
    assert [(i["kind"], i["summary"], i["source"]) for i in fan_items] == [
        ("detached_routine", "5:00 PM: on", "parser")
    ]
    # A line the parser cannot read names its kind with the translated phrase.
    lamp_items = sensor_state(hass, lamp).attributes["items"]
    assert [(i["kind"], i["summary"], i["source"]) for i in lamp_items] == [
        ("detached_routine", "Detached routine", "none")
    ]

    # The manager reports the routine detached: its items give way to the parsed line.
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary(Status.DETACHED)
    await with_provider(entry, provider)
    state = sensor_state(hass, fan)
    assert [(i["kind"], i["summary"]) for i in state.attributes["items"]] == [
        ("detached_routine", "5:00 PM: on")
    ]
    assert state.state == "On at 5:00 PM"


async def test_an_owned_routine_without_a_provider_item_reads_as_its_settings(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    """Plan A4.0 item 20 (PRD 12): the index reads an owned routine through its inputs.

    Not through the rendered blueprint (here a stand in that only turns the fan on), so
    the lines are those of the settings, as the manager's item has them.
    """
    fan = home["fan"].id
    early = automation("early_off", [at("08:30")], [action("fan.turn_off", {"entity_id": FAN})])
    entry = await start(hass, [routine_config(fan), early])

    routine = {
        ("routine", "5:00 PM: on", ROUTINE_ALIAS),
        ("routine", "9:00 AM: off", ROUTINE_ALIAS),
    }
    other = [("automation", "8:30 AM: off", "Early Off")]

    def read(items: list[dict[str, Any]]) -> None:
        shown = [(i["kind"], i["summary"], i["alias"]) for i in items]
        assert set(shown[:2]) == routine
        assert shown[2:] == other

    items = sensor_state(hass, fan).attributes["items"]
    read(items)
    assert items[0]["automation"] == ROUTINE_ENTITY

    # A provider that does not know the routine leaves the indexed lines in place.
    provider = FakeProvider()
    summary = await with_provider(entry, provider)
    read(sensor_state(hass, fan).attributes["items"])
    assert fan in provider.asked

    # So does one that knows it but has no line for it; its status still reads.
    provider.summaries[fan] = routine_summary(Status.OFF, items=())
    summary.async_refresh_device(fan)
    state = sensor_state(hass, fan)
    read(state.attributes["items"])
    assert state.state == "Routine off"


async def test_routine_with_only_when_reads_if_1_condition_passes(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    """FR-R9: the Schedule line of a start the blueprint gates counts its conditions.

    The end is never gated (L64), so it reads as it did; the index reads the owned routine
    from its inputs, as the manager's own item does.
    """
    fan = home["fan"].id
    guarded = RoutineSettings(
        target_entity=FAN,
        on_time=time(17),
        off_time=time(9),
        extra_conditions=(
            {"condition": "state", "entity_id": "input_boolean.guest_mode", "state": "off"},
        ),
    )

    await start(hass, [routine_config(fan, guarded)])

    # Monday 08:00, inside the window: the end comes first.
    items = sensor_state(hass, fan).attributes["items"]
    assert [(item["kind"], item["summary"]) for item in items] == [
        ("routine", "9:00 AM: off"),
        ("routine", "5:00 PM: on (if 1 condition passes)"),
    ]


async def test_an_owned_routine_the_parser_cannot_read_names_its_kind(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    refs = ha_adapter.AutomationRefs(
        entity_id=ROUTINE_ENTITY,
        config={
            "id": markers.automation_id(home["fan"].id),
            "alias": ROUTINE_ALIAS,
            "triggers": [{"trigger": "template", "value_template": "{{ true }}"}],
            "actions": [action("fan.turn_on", {"entity_id": FAN})],
        },
        entities=frozenset({FAN}),
        devices=frozenset(),
        areas=frozenset(),
        floors=frozenset(),
        labels=frozenset(),
        blueprint={"path": markers.BLUEPRINT_PATH},
    )
    with patch.object(ha_adapter, "automation_references", return_value=[refs]):
        entry = await start(hass, [])

    items = coordinator(entry).summaries[home["fan"].id].items
    assert [(item.kind, item.summary) for item in items] == [("routine", "Routine")]
    # Inputs the compiler cannot read give no routine to compute from.
    assert coordinator(entry)._index.routines == {}


async def test_a_running_countdown_feeds_the_state(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    fan = home["fan"].id
    timed = RoutineSettings(target_entity=FAN, turn_off_after_min=30)
    hass.states.async_set(TIMER, "active", {"finishes_at": "2026-10-19T15:30:00+00:00"})
    entry = await start(hass, [routine_config(fan, timed, timer_entity=TIMER)])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary(items=(routine_item("Off 30 min after it turns on"),))
    await with_provider(entry, provider)

    assert sensor_state(hass, fan).state == "Off at 8:30 AM"

    # The countdown is cancelled: the timer's own state change refreshes the view.
    hass.states.async_set(TIMER, "idle", {})
    await hass.async_block_till_done()
    assert sensor_state(hass, fan).state == "Off 30 min after it turns on"

    # Skipping the countdown leaves nothing to name: the state reads the pause.
    provider.summaries[fan] = routine_summary(
        Status.SKIPPING,
        local(19, 8, 31),
        Occurrence(local(19, 8, 30), Verb.OFF),
        items=(routine_item("Off 30 min after it turns on"),),
    )
    coordinator(entry).async_refresh_device(fan)
    state = sensor_state(hass, fan)
    assert state.state == "Paused until 8:31 AM"
    assert state.attributes["skipped_action"] == "8:30 AM: off"


async def test_the_routine_rows_prefer_the_managers_settings(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    """L69's second carry over: the settings the provider hands over win over the inputs.

    The inputs say 17:00 to 19:00; the manager already holds 10:00 to 21:00, a change the
    debounced write has not written yet. The state, the conflicts and the Today view read
    the manager's, so an automation turning the fan off at 20:00, outside the written
    window, already conflicts.
    """
    fan = home["fan"].id
    written = RoutineSettings(target_entity=FAN, on_time=time(17), off_time=time(19))
    held = RoutineSettings(target_entity=FAN, on_time=time(10), off_time=time(21))
    evening = automation("evening_off", [at("20:00")], [action("fan.turn_off", {"entity_id": FAN})])
    entry = await start(hass, [routine_config(fan, written), evening])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary()
    summary = await with_provider(entry, provider)
    assert sensor_state(hass, fan).state == "On at 5:00 PM"
    assert summary.summaries[fan].conflicts == ()

    provider.summaries[fan] = routine_summary(settings=held)
    summary.async_refresh_device(fan)

    state = sensor_state(hass, fan)
    assert state.state == "On at 10:00 AM"
    assert state.attributes["conflicts"] == [
        {"items": [0, 1], "reason": "off_in_on_window", "at": "2026-10-19T20:00:00-07:00"}
    ]
    assert [
        (item.time, item.action, item.kind, item.conflict)
        for item in summary.day_schedule(date(2026, 10, 19))
    ] == [
        (local(19, 10), Verb.ON, KIND_ROUTINE, False),
        (local(19, 20), Verb.OFF, KIND_AUTOMATION, True),
        (local(19, 21), Verb.OFF, KIND_ROUTINE, False),
    ]


async def test_a_sun_window_routine_gets_window_conflicts(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    """L69's first carry over: the Schedule places a sun window with its sun lookups.

    From sunset to sunrise, on Monday at 08:00: an automation turning the fan off at
    10:00 PM acts inside the window and one turning it on at noon outside it; both
    conflict, in the Schedule and in the Today view.
    """
    fan = home["fan"].id
    dusk = RoutineSettings(target_entity=FAN, on_kind=TimeKind.SUNSET, off_kind=TimeKind.SUNRISE)
    late = automation("late_off", [at("22:00")], [action("fan.turn_off", {"entity_id": FAN})])
    noon = automation("noon_on", [at("12:00")], [action("fan.turn_on", {"entity_id": FAN})])
    entry = await start(hass, [routine_config(fan, dusk), late, noon])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary()
    summary = await with_provider(entry, provider)

    found = summary.summaries[fan]
    assert [(found.items[c.b].alias, c.reason_key, c.at) for c in found.conflicts] == [
        ("Noon On", "on_in_off_window", local(19, 12)),
        ("Late Off", "off_in_on_window", local(19, 22)),
    ]
    assert {
        (item.automation, item.conflict)
        for item in summary.day_schedule(date(2026, 10, 19))
        if item.kind == KIND_AUTOMATION
    } == {("automation.noon_on", True), ("automation.late_off", True)}


async def test_a_hand_written_sun_trigger_reads_to_the_minute(
    hass: HomeAssistant, home: dict[str, Any], freezer: Any
) -> None:
    """L69's third carry over for a hand written line: at sunset, "On at 6:10 PM".

    The sun instant keeps its seconds where it is scheduled (`next_run`, the next view
    refresh); the follow up of a sun trigger reads to the minute too, and a time written
    with seconds keeps them.
    """
    moment = get_astral_event_date(hass, "sunset", date(2026, 10, 19))
    assert moment is not None
    sunset = moment.astimezone(LA)
    assert sunset.second or sunset.microsecond  # the test location's sunset has seconds
    at_sunset = automation(
        "at_sunset",
        [{"trigger": "sun", "event": "sunset"}],
        [
            action("fan.turn_on", {"entity_id": FAN}),
            {"delay": {"minutes": 3}},
            action("fan.turn_off", {"entity_id": FAN}),
        ],
    )
    precise = automation(
        "precise_lamp", [at("17:30:15")], [action("light.turn_on", {"entity_id": LAMP})]
    )
    entry = await start(hass, [at_sunset, precise])
    fan, lamp = home["fan"].id, home["lamp"].id
    writer = Writer(load_phrases("en"), "12h")

    def minute(instant: datetime) -> str:
        return writer.clock(instant.time().replace(second=0, microsecond=0, tzinfo=None))

    state = sensor_state(hass, fan)
    assert state.attributes["items"][0]["summary"] == "Sunset: on for 3 min, then off"
    assert state.state == f"On at {minute(sunset)}"
    assert state.attributes["items"][0]["next_run"] == sunset.isoformat()
    assert coordinator(entry).summaries[fan].next_change == sunset
    assert sensor_state(hass, lamp).state == "On at 5:30:15 PM"

    # A minute after sunset (no trigger runs: no time change fires), the off comes next.
    freezer.move_to(sunset + timedelta(minutes=1))
    coordinator(entry)._refresh_views()
    await hass.async_block_till_done()
    assert sensor_state(hass, fan).state == f"Off at {minute(sunset + timedelta(minutes=3))}"


async def test_a_weekly_schedule_feeds_the_state(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    fan = home["fan"].id
    weekly = RoutineSettings(
        target_entity=FAN, days=Days.WEEKLY_SCHEDULE, schedule_entity=WEEKLY_HELPER
    )
    hass.states.async_set(WEEKLY_HELPER, "off", {"next_event": local(19, 18)})
    entry = await start(hass, [routine_config(fan, weekly)])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary(items=(routine_item("Weekly schedule"),))
    await with_provider(entry, provider)

    assert sensor_state(hass, fan).state == "On at 6:00 PM"

    hass.states.async_set(WEEKLY_HELPER, "on", {"next_event": "2026-10-19T22:00:00-07:00"})
    await hass.async_block_till_done()
    assert sensor_state(hass, fan).state == "Off at 10:00 PM"

    hass.states.async_set(WEEKLY_HELPER, "on", {})
    await hass.async_block_till_done()
    assert sensor_state(hass, fan).state == "Weekly schedule"


async def test_a_routine_turned_off_in_home_assistant_runs_nothing(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    fan = home["fan"].id
    noon = automation("noon_on", [at("12:00")], [action("fan.turn_on", {"entity_id": FAN})])
    entry = await start(hass, [routine_config(fan), noon])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary()
    await with_provider(entry, provider)
    # While the routine runs, the noon on contradicts its off window (FR-S6).
    assert sensor_state(hass, fan).attributes["conflicts"] == [
        {"items": [0, 1], "reason": "on_in_off_window", "at": "2026-10-19T12:00:00-07:00"}
    ]

    # The automation entity is off before the manager caught up: no routine action counts.
    await hass.services.async_call(
        "automation", "turn_off", {"entity_id": ROUTINE_ENTITY}, blocking=True
    )
    await hass.async_block_till_done()
    state = sensor_state(hass, fan)
    assert state.state == "On at 12:00 PM"
    assert state.attributes["conflicts"] == []


async def test_the_view_refreshes_when_a_pause_ends(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None, freezer: Any
) -> None:
    fan = home["fan"].id
    entry = await start(hass, [routine_config(fan)])
    provider = FakeProvider()
    provider.summaries[fan] = routine_summary(Status.PAUSED, local(19, 10))
    await with_provider(entry, provider)
    assert sensor_state(hass, fan).state == "Paused until 10:00 AM"
    assert coordinator(entry).summaries[fan].next_change == local(19, 10)

    freezer.move_to(datetime(2026, 10, 19, 10, 0, 2, tzinfo=LA))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert sensor_state(hass, fan).state == "On at 5:00 PM"


async def test_a_routine_the_index_does_not_hold_comes_from_the_provider(
    hass: HomeAssistant, home: dict[str, Any]
) -> None:
    lamp = home["lamp"].id
    entry = await start(hass, [WINDOW])
    provider = FakeProvider()
    summary = await with_provider(entry, provider)
    assert lamp not in summary.summaries

    # The manager names a routine whose automation is not loaded yet.
    provider.summaries[lamp] = routine_summary(items=(routine_item(next_run=local(19, 21)),))
    summary.async_refresh_device(lamp)
    await hass.async_block_till_done()
    state = sensor_state(hass, lamp)
    assert [item["kind"] for item in state.attributes["items"]] == ["routine"]
    # Without the routine's inputs the action is not known, only its time.
    assert state.state == "Next: 9:00 PM"

    provider.summaries[lamp] = routine_summary(
        Status.SKIPPING, local(19, 21, 1), Occurrence(local(19, 21), Verb.OFF)
    )
    summary.async_refresh_device(lamp)
    assert sensor_state(hass, lamp).state == "Paused until 9:01 PM"

    # A full refresh keeps asking about it.
    summary._refresh_views()
    assert lamp in summary.summaries

    # The routine is gone: so are the summary and the sensor, and nobody asks again.
    del provider.summaries[lamp]
    summary.async_refresh_device(lamp)
    await hass.async_block_till_done()
    assert lamp not in summary.summaries
    assert schedule_entity(hass, lamp) is None
    provider.asked.clear()
    summary._refresh_views()
    assert lamp not in provider.asked

    # A routine with no line and no automation has nothing to show.
    provider.summaries[lamp] = routine_summary(items=())
    summary.async_refresh_device(lamp)
    assert lamp not in summary.summaries

    # Nor does a device that is gone from the registry.
    summary.async_refresh_device("no_such_device")
    assert "no_such_device" not in summary.summaries


async def test_the_routines_scope_shows_devices_with_routines(
    hass: HomeAssistant, home: dict[str, Any], routine_blueprint: None
) -> None:
    fan, lamp = home["fan"].id, home["lamp"].id
    lamp_off = automation(
        "lamp_off", [at("21:00")], [action("light.turn_off", {"entity_id": LAMP})]
    )
    entry = await start(
        hass, [routine_config(fan), lamp_off], options={"schedule_scope": "routines"}
    )

    # The owned automation makes the fan a device with a routine; the lamp has none.
    assert schedule_entity(hass, fan) is not None
    assert schedule_entity(hass, lamp) is None

    provider = FakeProvider()
    provider.summaries[lamp] = routine_summary()
    summary = await with_provider(entry, provider)
    summary.async_refresh_device(lamp)
    await hass.async_block_till_done()
    assert schedule_entity(hass, lamp) is not None


async def test_the_provider_is_not_asked_before_the_start_or_after_the_stop(
    hass: HomeAssistant,
) -> None:
    summary = SummaryCoordinator(hass, "entry", GlobalSettings(), load_phrases("en"))
    provider = FakeProvider()

    summary.set_routine_provider(provider)
    summary.async_refresh_device("device")

    assert provider.asked == []
    assert summary.summaries == {}
    await summary.async_start()
    assert provider.asked == ["device"]
    summary.async_stop()
    provider.asked.clear()
    summary.async_refresh_device("device")
    summary.set_routine_provider(None)
    assert provider.asked == []


def test_moments_from_state_attributes() -> None:
    aware = datetime(2026, 10, 19, 8, tzinfo=LA)
    assert _moment(aware) == aware
    assert _moment("2026-10-19T15:00:00+00:00") == aware
    assert _moment(aware.replace(tzinfo=None)) == aware
    assert _moment("soon") is None
    assert _moment(None) is None
    timer = State(TIMER, "active", {"finishes_at": "2026-10-19T15:00:00+00:00"})
    assert _attribute_moment(timer, "finishes_at", "active") == aware
    assert _attribute_moment(timer, "finishes_at", "idle") is None
    assert _attribute_moment(None, "finishes_at") is None


async def test_the_adapter_reads_the_blueprint_block_ownership_needs(
    hass: HomeAssistant,
    home: dict[str, Any],
    routine_blueprint: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entity's config is the rendered one, without use_blueprint, so M2 is read apart."""
    fan = home["fan"].id
    owned = routine_config(fan)
    await start(hass, [owned, WINDOW])

    rendered = ha_adapter.automation_config(hass, ROUTINE_ENTITY)
    assert rendered is not None
    assert "use_blueprint" not in rendered
    assert markers.has_routine_id(rendered)
    assert not markers.is_owned(rendered)
    by_entity = {refs.entity_id: refs for refs in ha_adapter.automation_references(hass)}
    assert by_entity[ROUTINE_ENTITY].blueprint == owned["use_blueprint"]
    assert by_entity["automation.fan_window"].blueprint is None
    assert markers.is_owned({**rendered, "use_blueprint": by_entity[ROUTINE_ENTITY].blueprint})

    # When the entity's inputs attribute moves, the public helper still names the path.
    entity = hass.data[DATA_COMPONENT].get_entity(ROUTINE_ENTITY)
    monkeypatch.setattr(
        automation_component,
        "blueprint_in_automation",
        lambda _hass, entity_id: markers.BLUEPRINT_PATH if entity_id == ROUTINE_ENTITY else None,
    )
    monkeypatch.setattr(entity, "_blueprint_inputs", None)
    assert ha_adapter.automation_blueprint(hass, ROUTINE_ENTITY) == {"path": markers.BLUEPRINT_PATH}
    assert ha_adapter.automation_blueprint(hass, "automation.fan_window") is None
