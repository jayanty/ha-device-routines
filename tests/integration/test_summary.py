"""The SummaryCoordinator and the Schedule sensor in a running Home Assistant (TECH_SPEC 4.4)."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from homeassistant.components import automation as automation_component
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import ha_adapter
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.entity import linked_device_info
from custom_components.device_routines.summary import (
    DEBOUNCE_SECONDS,
    SummaryCoordinator,
    _held_time,
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
    # No enabled item: the state falls back to the first line.
    assert state.state in {"9:00 AM: off", "5:00 PM: on"}


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
    assert ha_adapter.check(hass).ok
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
    assert report.failed == ("read_automations",)
    assert "labels_in_automation" in report.details["read_automations"]


def test_linked_device_info_by_connections() -> None:
    info = linked_device_info(frozenset(), frozenset({("mac", "aa:bb")}), "Plug")
    assert info == {"connections": {("mac", "aa:bb")}, "name": "Plug"}
