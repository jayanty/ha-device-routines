"""Build A lane 12: the WebSocket API, the console contract (TECH_SPEC 4.7, PRD 7.5).

Every command goes through the test WebSocket client and is compared with what the
service layer itself returns (`plain` serializes the manager's own result independently
of the module under test), so a command is proven to be a thin caller. The home is the
synthetic one of `conftest.py`: a living room fan on the sandbox switch, a desk lamp, a
garage door and a contact sensor; Monday 2026-10-19 in Los Angeles. Every name is generic.
"""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
from datetime import date, datetime, time, timedelta
import json
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import ha_adapter, maintenance, markers, websocket_api
from custom_components.device_routines.manager import (
    SCHEDULE_DEBOUNCE_SECONDS as SCHEDULE_DEBOUNCE,
    ActionResults,
    RoutineManager,
)
from custom_components.device_routines.models import Weekday
from custom_components.device_routines.settings import GlobalSettings, TimeFormat
from custom_components.device_routines.summary import DEBOUNCE_SECONDS as SUMMARY_DEBOUNCE
from tests.integration.conftest import (
    FAN,
    LAMP,
    Clock,
    Home,
    file_entries,
    flush,
    give_routine,
    inputs_of,
    reload_all,
    write_entries,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

PREFIX = "device_routines"
ROUTINE = "automation.routine_living_room_fan"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def _default(value: Any) -> Any:
    if isinstance(value, datetime | time):
        return value.isoformat()
    if isinstance(value, frozenset):
        return [day.value for day in Weekday if day in value]
    raise TypeError(value)


def plain(value: Any) -> Any:
    """What a service layer result looks like as JSON, built apart from the module."""
    if isinstance(value, tuple | list):
        return [plain(item) for item in value]
    return json.loads(json.dumps(dataclasses.asdict(value), default=_default))


async def call(client: Any, message: dict[str, Any]) -> Any:
    """Send one command and return its result; fail on an error or an event."""
    await client.send_json_auto_id(message)
    response = await client.receive_json()
    assert response["type"] == "result", response
    assert response["success"], response
    return response["result"]


async def refusal(client: Any, message: dict[str, Any]) -> dict[str, Any]:
    """Send one command and return its error."""
    await client.send_json_auto_id(message)
    response = await client.receive_json()
    assert response["type"] == "result", response
    assert not response["success"], response
    error: dict[str, Any] = response["error"]
    return error


async def events_before(client: Any, message: dict[str, Any]) -> tuple[list[Any], Any]:
    """Send one command; return the events pushed before its result, and the result."""
    await client.send_json_auto_id(message)
    events: list[Any] = []
    while True:
        response = await client.receive_json()
        if response["type"] == "event":
            events.append(response["event"])
            continue
        assert response["success"], response
        return events, response["result"]


def translated(code: str, **placeholders: str) -> dict[str, Any]:
    """The error a refusal of the service layer carries."""
    return {
        "code": code,
        "translation_key": code,
        "translation_domain": "device_routines",
        "translation_placeholders": placeholders,
    }


def without_message(error: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in error.items() if key != "message"}


async def window(hass: HomeAssistant, manager: RoutineManager, home: Home, freezer: Any) -> str:
    """Give the fan a 17:00 to 23:00 routine on Monday at 16:00; return its automation id."""
    return await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))


async def settle_summary(hass: HomeAssistant, freezer: Any) -> None:
    freezer.tick(timedelta(seconds=SUMMARY_DEBOUNCE + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def add_automations(hass: HomeAssistant, freezer: Any, *entries: dict[str, Any]) -> None:
    """Hand written automations, saved next to the routines and reloaded."""
    write_entries(hass, [*file_entries(hass), *entries])
    await reload_all(hass)
    await settle_summary(hass, freezer)


def timed(key: str, at: str, service: str, entity_id: str) -> dict[str, Any]:
    return {
        "id": key,
        "alias": key.replace("_", " ").capitalize(),
        "triggers": [{"trigger": "time", "at": at}],
        "actions": [{"action": service, "target": {"entity_id": entity_id}}],
    }


@pytest.fixture
def at_four(clock: Clock) -> Clock:
    """Monday 16:00, before the fan's routine starts at 17:00."""
    clock.set(clock.at(0, "16:00"))
    return clock


# --------------------------------------------------------------------------------------
# routines/list and routines/get
# --------------------------------------------------------------------------------------


async def test_routines_list_and_get_return_the_managers_own_views(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
) -> None:
    await window(hass, manager, home, freezer)
    await manager.async_opt_in(home.lamp)
    client = await hass_ws_client(hass)

    listed = await call(client, {"type": f"{PREFIX}/routines/list"})
    one = await call(client, {"type": f"{PREFIX}/routines/get", "device_id": home.fan})

    assert listed == {"routines": plain(manager.list())}
    assert one == plain(manager.get(home.fan))
    assert [view["device_name"] for view in listed["routines"]] == ["Desk lamp", "Living room fan"]
    assert one["automation_entity_id"] == ROUTINE
    assert one["status"] == "active"
    assert one["enabled"] is True


async def test_datetimes_and_times_serialize_as_iso_strings(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
) -> None:
    await window(hass, manager, home, freezer)
    client = await hass_ws_client(hass)
    await call(
        client,
        {
            "type": f"{PREFIX}/routines/action",
            "action": "pause",
            "target": {"device_id": home.fan},
            "until": "2026-10-19T18:30:00-07:00",
        },
    )

    view = await call(client, {"type": f"{PREFIX}/routines/get", "device_id": home.fan})

    assert view["settings"]["on_time"] == "17:00:00"
    assert view["settings"]["off_time"] == "23:00:00"
    assert view["settings"]["day_set"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert view["settings"]["days"] == "every_day"
    assert view["paused_until"] == "2026-10-19T18:30:00-07:00"
    assert view["next_action"] == {"at": "2026-10-19T23:00:00-07:00", "verb": "off"}
    assert view["items"][0]["next_run"] == "2026-10-19T23:00:00-07:00"
    assert view["status"] == "paused"
    assert view == plain(manager.get(home.fan))


async def test_routines_get_refuses_a_device_without_routine_controls(
    hass: HomeAssistant, home: Home, manager: RoutineManager, hass_ws_client: Any
) -> None:
    client = await hass_ws_client(hass)

    error = await refusal(client, {"type": f"{PREFIX}/routines/get", "device_id": home.garage})
    unknown = await refusal(client, {"type": f"{PREFIX}/routines/get", "device_id": "nowhere"})

    assert without_message(error) == translated("not_opted_in", device="Garage door")
    assert error["message"]
    assert unknown["translation_placeholders"] == {"device": "nowhere"}


# --------------------------------------------------------------------------------------
# routines/set
# --------------------------------------------------------------------------------------


async def test_routines_set_applies_a_valid_patch_and_returns_the_view(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
) -> None:
    automation_id = await window(hass, manager, home, freezer)
    client = await hass_ws_client(hass)

    view = await call(
        client,
        {
            "type": f"{PREFIX}/routines/set",
            "device_id": home.fan,
            "settings": {"off_time": "22:30", "days": "some_days", "day_set": ["sat", "mon"]},
        },
    )

    assert view == plain(manager.get(home.fan))
    assert view["settings"]["off_time"] == "22:30:00"
    assert view["settings"]["days"] == "some_days"
    assert view["settings"]["day_set"] == ["mon", "sat"]
    await flush(hass, freezer)
    assert inputs_of(hass, automation_id)["off_time"] == "22:30:00"


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        ({"off_time": "17:00"}, translated("same_on_and_off_time", setting="off_time")),
        ({"colour": "red"}, translated("unknown_setting", setting="colour")),
        (
            {"turn_off_after_min": "soon"},
            translated("invalid_value", setting="turn_off_after_min"),
        ),
        (
            {"target_entity": LAMP},
            translated("invalid_target", setting="target_entity", entity=LAMP),
        ),
    ],
)
async def test_routines_set_returns_the_problem_of_an_invalid_patch(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
    patch: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    await window(hass, manager, home, freezer)
    client = await hass_ws_client(hass)

    error = await refusal(
        client, {"type": f"{PREFIX}/routines/set", "device_id": home.fan, "settings": patch}
    )

    assert without_message(error) == expected
    view = manager.get(home.fan)
    assert view is not None
    assert (view.settings.on_time, view.settings.off_time) == (time(17), time(23))


async def test_routines_set_refuses_a_device_without_routine_controls(
    hass: HomeAssistant, home: Home, manager: RoutineManager, hass_ws_client: Any
) -> None:
    client = await hass_ws_client(hass)

    error = await refusal(
        client,
        {"type": f"{PREFIX}/routines/set", "device_id": home.lamp, "settings": {"on_time": "7:00"}},
    )

    assert without_message(error) == translated("not_opted_in", device="Desk lamp")


# --------------------------------------------------------------------------------------
# routines/action
# --------------------------------------------------------------------------------------

TARGETS: dict[str, Callable[[Home], dict[str, Any]]] = {
    "device": lambda home: {"device_id": home.fan},
    "entity": lambda _: {"entity_id": FAN},
    "area": lambda home: {"area_id": home.area},
    "floor": lambda home: {"floor_id": home.floor},
    "label": lambda _: {"label_id": markers.LABEL_ID},
}


@pytest.mark.parametrize("kind", sorted(TARGETS))
@pytest.mark.parametrize("action", ["skip_next", "pause", "resume", "enable", "disable"])
async def test_routines_action_runs_each_action_over_each_target_kind(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    kind: str,
) -> None:
    await window(hass, manager, home, freezer)
    returned: list[ActionResults] = []
    asked: list[tuple[Any, ...]] = []
    real = manager.async_run_action

    async def spy(name: Any, target: Any, **kwargs: Any) -> ActionResults:
        asked.append((name, dict(target), kwargs))
        result = await real(name, target, **kwargs)
        returned.append(result)
        return result

    monkeypatch.setattr(manager, "async_run_action", spy)
    client = await hass_ws_client(hass)
    message = {"type": f"{PREFIX}/routines/action", "action": action, "target": TARGETS[kind](home)}
    if action == "pause":
        message["for"] = "01:30:00"

    result = await call(client, message)

    assert result == plain(returned[0])
    duration = timedelta(hours=1, minutes=30) if action == "pause" else None
    target = {key: [value] for key, value in TARGETS[kind](home).items()}
    assert asked == [(action, target, {"until": None, "duration": duration})]
    assert [(item["device_id"], item["action"]) for item in result["results"]] == [
        (home.fan, action)
    ]
    # An area or a floor also covers the desk lamp, which has no routine (S13).
    ignored = [] if kind in {"device", "entity", "label"} else [home.lamp]
    assert [item["target"] for item in result["ignored"]] == ignored
    assert all(item["reason"] == "no_routine" for item in result["ignored"])


async def test_routines_action_takes_a_local_until_and_refuses_what_the_manager_refuses(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
) -> None:
    await window(hass, manager, home, freezer)
    client = await hass_ws_client(hass)
    fan = {"device_id": home.fan}

    # A datetime without an offset is the instance's local time.
    paused = await call(
        client,
        {
            "type": f"{PREFIX}/routines/action",
            "action": "pause",
            "target": fan,
            "until": "2026-10-19 18:30:00",
        },
    )
    both = await refusal(
        client,
        {
            "type": f"{PREFIX}/routines/action",
            "action": "pause",
            "target": fan,
            "until": "2026-10-19T19:00:00-07:00",
            "for": 600,
        },
    )
    everything = await refusal(
        client, {"type": f"{PREFIX}/routines/action", "action": "resume", "target": "all"}
    )
    nobody = await refusal(
        client,
        {
            "type": f"{PREFIX}/routines/action",
            "action": "resume",
            "target": {"device_id": home.lamp},
        },
    )
    unknown = await refusal(
        client, {"type": f"{PREFIX}/routines/action", "action": "explode", "target": fan}
    )

    assert paused["results"][0]["paused_until"] == "2026-10-19T18:30:00-07:00"
    assert without_message(both) == translated("pause_until_or_for")
    assert without_message(everything) == translated("target_all_reserved")
    assert without_message(nobody) == translated("no_routine_targets")
    assert unknown["code"] == "invalid_format"


# --------------------------------------------------------------------------------------
# devices/opt
# --------------------------------------------------------------------------------------


async def test_devices_opt_lists_suggests_and_opts_in_and_out(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
) -> None:
    await add_automations(hass, freezer, timed("morning_lamp", "07:00", "light.turn_on", LAMP))
    client = await hass_ws_client(hass)

    eligible = await call(client, {"type": f"{PREFIX}/devices/opt", "op": "list"})
    suggested = await call(client, {"type": f"{PREFIX}/devices/opt", "op": "suggest"})
    opted_in = await call(
        client, {"type": f"{PREFIX}/devices/opt", "op": "in", "device_id": [home.lamp]}
    )
    view = manager.get(home.lamp)
    opted_out = await call(
        client, {"type": f"{PREFIX}/devices/opt", "op": "out", "device_id": home.lamp}
    )

    assert eligible == {"devices": plain(manager.eligible_devices())}
    assert {"Desk lamp", "Living room fan"} <= {device["name"] for device in eligible["devices"]}
    assert suggested == {
        "devices": [
            {"device_id": home.lamp, "name": "Desk lamp", "area_id": home.area, "targets": [LAMP]}
        ]
    }
    assert opted_in == {
        "results": [
            {"device_id": home.lamp, "opted_in": True, "changed": True, "view": plain(view)}
        ]
    }
    assert opted_out["results"][0] == {
        "device_id": home.lamp,
        "opted_in": False,
        "changed": True,
        "view": plain(manager.get(home.lamp)),
    }
    assert home.lamp not in manager.store.data.opted_in


async def test_devices_opt_refuses_a_device_a_routine_cannot_drive(
    hass: HomeAssistant, home: Home, manager: RoutineManager, hass_ws_client: Any
) -> None:
    client = await hass_ws_client(hass)

    error = await refusal(
        client, {"type": f"{PREFIX}/devices/opt", "op": "in", "device_id": [home.door]}
    )
    nothing = await call(client, {"type": f"{PREFIX}/devices/opt", "op": "in"})

    assert without_message(error) == translated("not_eligible", device="Sandbox contact")
    assert nothing == {"results": []}


# --------------------------------------------------------------------------------------
# schedule/today
# --------------------------------------------------------------------------------------


async def test_schedule_today_lists_routines_and_automations_with_conflicts(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
    routines: MockConfigEntry,
) -> None:
    await window(hass, manager, home, freezer)
    await add_automations(
        hass,
        freezer,
        timed("morning_lamp", "07:00", "light.turn_on", LAMP),
        timed("late_fan_on", "23:00", "switch.turn_on", FAN),
    )
    client = await hass_ws_client(hass)

    today = await call(client, {"type": f"{PREFIX}/schedule/today"})
    tuesday = await call(client, {"type": f"{PREFIX}/schedule/today", "date": "2026-10-20"})

    summary = routines.runtime_data.summary
    assert today == {"date": "2026-10-19", "items": plain(summary.day_schedule(date(2026, 10, 19)))}
    assert tuesday["items"] == plain(summary.day_schedule(date(2026, 10, 20)))
    area = home.area
    # The hand written 23:00 on opposes the routine's 23:00 off and lands outside its
    # window (FR-S6), so both are marked; the 07:00 lamp is planned before now.
    assert today["items"] == [
        {
            "time": "2026-10-19T07:00:00-07:00",
            "device_id": home.lamp,
            "area_id": area,
            "action": "on",
            "kind": "automation",
            "automation": "automation.morning_lamp",
            "conflict": False,
        },
        {
            "time": "2026-10-19T17:00:00-07:00",
            "device_id": home.fan,
            "area_id": area,
            "action": "on",
            "kind": "routine",
            "automation": ROUTINE,
            "conflict": False,
        },
        {
            "time": "2026-10-19T23:00:00-07:00",
            "device_id": home.fan,
            "area_id": area,
            "action": "on",
            "kind": "automation",
            "automation": "automation.late_fan_on",
            "conflict": True,
        },
        {
            "time": "2026-10-19T23:00:00-07:00",
            "device_id": home.fan,
            "area_id": area,
            "action": "off",
            "kind": "routine",
            "automation": ROUTINE,
            "conflict": True,
        },
    ]
    assert tuesday["date"] == "2026-10-20"
    times = [item["time"][11:16] for item in tuesday["items"]]
    assert times == ["07:00", "17:00", "23:00", "23:00"]
    invalid = await refusal(client, {"type": f"{PREFIX}/schedule/today", "date": "someday"})
    assert invalid["code"] == "invalid_format"


# --------------------------------------------------------------------------------------
# settings/get and settings/set
# --------------------------------------------------------------------------------------


async def test_settings_get_and_set_store_the_options_and_reload_the_entry(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    hass_ws_client: Any,
) -> None:
    client = await hass_ws_client(hass)

    current = await call(client, {"type": f"{PREFIX}/settings/get"})
    changed = await call(
        client,
        {
            "type": f"{PREFIX}/settings/set",
            "settings": {"time_format": "24h", "cleanup_after_days": 10},
        },
    )
    await hass.async_block_till_done()

    assert current == GlobalSettings().to_options()
    assert changed == {**current, "time_format": "24h", "cleanup_after_days": 10}
    assert routines.options["time_format"] == "24h"
    # Storing the options reloaded the entry, which runs with them under a new manager.
    assert routines.runtime_data.settings.time_format is TimeFormat.H24
    assert routines.runtime_data.manager is not manager
    assert await call(client, {"type": f"{PREFIX}/settings/get"}) == changed

    # The same values again change nothing and reload nothing.
    reloaded = routines.runtime_data.manager
    again = await call(
        client, {"type": f"{PREFIX}/settings/set", "settings": {"time_format": "24h"}}
    )
    await hass.async_block_till_done()
    assert again == changed
    assert routines.runtime_data.manager is reloaded


@pytest.mark.parametrize(
    ("patch", "expected"),
    [
        (
            {"time_format": "13h"},
            translated("invalid_choice", setting="time_format", allowed="auto, 12h, 24h"),
        ),
        (
            {"cleanup_after_days": 400},
            translated("out_of_range", setting="cleanup_after_days", min="0", max="365"),
        ),
        ({"assign_area": "yes"}, translated("invalid_boolean", setting="assign_area")),
        (
            {"ai_task_entity": "light.desk_lamp"},
            translated("invalid_ai_task_entity", setting="ai_task_entity"),
        ),
        ({"colour": "red"}, translated("unknown_setting", setting="colour")),
    ],
)
async def test_settings_set_refuses_invalid_values_and_stores_nothing(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    hass_ws_client: Any,
    patch: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    client = await hass_ws_client(hass)

    error = await refusal(client, {"type": f"{PREFIX}/settings/set", "settings": patch})
    await hass.async_block_till_done()

    assert without_message(error) == expected
    assert dict(routines.options) == {}
    assert routines.runtime_data.manager is manager


# --------------------------------------------------------------------------------------
# maintenance
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    "action", ["clean_up_now", "rebuild_index", "reinstall_blueprint", "refresh_summaries"]
)
async def test_maintenance_reports_what_was_or_would_be_changed(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
    action: str,
    dry_run: bool,
) -> None:
    await window(hass, manager, home, freezer)
    await manager.async_opt_in(home.lamp)
    await manager.async_opt_out(home.lamp)
    expected = await maintenance.async_run(hass, manager, action, dry_run=True)
    client = await hass_ws_client(hass)

    report = await call(
        client, {"type": f"{PREFIX}/maintenance", "action": action, "dry_run": dry_run}
    )

    changes = plain(expected)["would_change"]
    assert report == {
        "action": action,
        "changed": [] if dry_run else changes,
        "would_change": changes if dry_run else [],
    }


async def test_maintenance_runs_for_real_by_default_and_refuses_unknown_actions(
    hass: HomeAssistant, home: Home, manager: RoutineManager, hass_ws_client: Any
) -> None:
    await manager.async_opt_in(home.lamp)
    await manager.async_opt_out(home.lamp)
    client = await hass_ws_client(hass)

    report = await call(client, {"type": f"{PREFIX}/maintenance", "action": "clean_up_now"})
    unknown = await refusal(client, {"type": f"{PREFIX}/maintenance", "action": "defragment"})

    assert report == {"action": "clean_up_now", "changed": [home.lamp], "would_change": []}
    assert home.lamp not in manager.store.data.opted_out_at
    assert unknown["code"] == "invalid_format"


async def test_a_maintenance_failure_is_answered_with_its_translation(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    hass_ws_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan A4.0 item 5: the console gets the translated error, never a bare one."""

    async def unreadable(*_args: Any) -> list[Any]:
        raise ha_adapter.AdapterError("automations.yaml does not hold a list")

    monkeypatch.setattr(ha_adapter, "async_read_automations", unreadable)
    client = await hass_ws_client(hass)

    error = await refusal(client, {"type": f"{PREFIX}/maintenance", "action": "rebuild_index"})

    assert error["code"] == "home_assistant_error"
    assert error["translation_key"] == "maintenance_failed"
    assert error["translation_domain"] == "device_routines"
    assert error["translation_placeholders"] == {
        "action": "rebuild_index",
        "error": "automations.yaml does not hold a list",
    }


# --------------------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------------------

WRITING: list[dict[str, Any]] = [
    {"type": f"{PREFIX}/routines/set", "device_id": "any", "settings": {}},
    {"type": f"{PREFIX}/routines/action", "action": "resume", "target": {"device_id": "any"}},
    {"type": f"{PREFIX}/devices/opt", "op": "list"},
    {"type": f"{PREFIX}/settings/set", "settings": {}},
    {"type": f"{PREFIX}/maintenance", "action": "refresh_summaries", "dry_run": True},
]
READING: list[dict[str, Any]] = [
    {"type": f"{PREFIX}/routines/list"},
    {"type": f"{PREFIX}/schedule/today"},
    {"type": f"{PREFIX}/settings/get"},
    {"type": f"{PREFIX}/subscribe"},
]


@pytest.mark.parametrize("message", WRITING, ids=lambda message: message["type"])
async def test_writing_commands_refuse_a_user_who_is_not_an_admin(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    hass_ws_client: Any,
    hass_read_only_access_token: str,
    message: dict[str, Any],
) -> None:
    client = await hass_ws_client(hass, hass_read_only_access_token)

    error = await refusal(client, dict(message))

    assert error["code"] == "unauthorized"


@pytest.mark.parametrize("message", READING, ids=lambda message: message["type"])
async def test_reading_commands_answer_every_user(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    hass_ws_client: Any,
    hass_read_only_access_token: str,
    message: dict[str, Any],
) -> None:
    client = await hass_ws_client(hass, hass_read_only_access_token)

    await call(client, dict(message))


# --------------------------------------------------------------------------------------
# subscribe
# --------------------------------------------------------------------------------------

LIST = {"type": f"{PREFIX}/routines/list"}


def opted_out(home: Home) -> dict[str, Any]:
    """The event a manager pushes when the desk lamp is opted out."""
    return {"kind": "routine_changed", "device_id": home.lamp, "reason": "opted_out", "data": None}


async def test_subscribe_pushes_the_managers_events_and_stops_on_unsubscribe(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
) -> None:
    await window(hass, manager, home, freezer)
    client = await hass_ws_client(hass)
    _, subscribed = await events_before(client, {"type": f"{PREFIX}/subscribe"})
    subscription = 1

    await manager.async_opt_in(home.lamp)
    opted_in, _ = await events_before(client, LIST)
    await manager.async_reconcile()
    reconciled, _ = await events_before(client, LIST)
    await call(client, {"type": f"{PREFIX}/settings/set", "settings": {"time_format": "24h"}})
    await hass.async_block_till_done()
    after_set, _ = await events_before(client, LIST)
    await routines.runtime_data.manager.async_opt_out(home.lamp)
    from_new_manager, _ = await events_before(client, LIST)
    await call(client, {"type": "unsubscribe_events", "subscription": subscription})
    await routines.runtime_data.manager.async_opt_in(home.lamp)
    after_unsubscribe, _ = await events_before(client, LIST)

    assert subscribed is None
    assert opted_in == [
        {"kind": "routine_changed", "device_id": home.lamp, "reason": "opted_in", "data": None}
    ]
    kinds = [event["kind"] for event in reconciled]
    assert {"schedule_changed", "health_changed"} <= set(kinds)
    assert set(kinds) <= {"routine_changed", "schedule_changed", "health_changed"}
    # The new settings reloaded the entry: the subscription follows the new manager and
    # says first that the settings changed.
    assert after_set[0] == {
        "kind": "settings_changed",
        "device_id": None,
        "reason": None,
        "data": None,
    }
    assert [event["kind"] for event in after_set].count("settings_changed") == 1
    assert opted_out(home) in from_new_manager
    assert after_unsubscribe == []


async def test_an_edit_of_a_hand_written_automation_pushes_schedule_changed(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
) -> None:
    """Plan A4.0 item 8 (L49): the console's Today view hears hand written edits too.

    The summary tells the manager once its views moved; the manager pushes one
    `schedule_changed` a second later, however many automations the edit touched.
    """
    await window(hass, manager, home, freezer)
    client = await hass_ws_client(hass)
    await call(client, {"type": f"{PREFIX}/subscribe"})

    await add_automations(
        hass,
        freezer,
        timed("lamp_on", "07:00:00", "light.turn_on", LAMP),
        timed("lamp_off", "21:00:00", "light.turn_off", LAMP),
    )
    early, _ = await events_before(client, LIST)
    freezer.tick(timedelta(seconds=SCHEDULE_DEBOUNCE + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    pushed, _ = await events_before(client, LIST)

    assert early == []
    assert pushed == [{"kind": "schedule_changed", "device_id": None, "reason": None, "data": None}]

    # An edit that moves no view pushes nothing.
    await add_automations(hass, freezer)
    freezer.tick(timedelta(seconds=SCHEDULE_DEBOUNCE + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    quiet, _ = await events_before(client, LIST)
    assert quiet == []


async def test_subscribe_carries_the_data_of_a_skipped_action(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    hass_ws_client: Any,
) -> None:
    client = await hass_ws_client(hass)
    await call(client, {"type": f"{PREFIX}/subscribe"})
    await manager.async_opt_in(home.fan)
    await events_before(client, LIST)

    hass.bus.async_fire(
        "device_routines_action_skipped",
        {"device_id": home.fan, "action": "on", "at": "2026-10-19T17:00:00-07:00"},
    )
    await hass.async_block_till_done()
    events, _ = await events_before(client, LIST)

    assert events == [
        {
            "kind": "routine_changed",
            "device_id": home.fan,
            "reason": "device_routines_action_skipped",
            "data": {"device_id": home.fan, "action": "on", "at": "2026-10-19T17:00:00-07:00"},
        }
    ]


async def test_subscribe_keeps_working_across_reloads_and_waits_for_the_entry(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    hass_ws_client: Any,
) -> None:
    client = await hass_ws_client(hass)
    await call(client, {"type": f"{PREFIX}/subscribe"})

    # A reload without a settings change: no settings_changed, the new manager is heard.
    assert await hass.config_entries.async_reload(routines.entry_id)
    await hass.async_block_till_done()
    reloaded, _ = await events_before(client, LIST)
    await routines.runtime_data.manager.async_opt_in(home.lamp)
    heard, _ = await events_before(client, LIST)

    assert "settings_changed" not in [event["kind"] for event in reloaded]
    assert {"schedule_changed", "health_changed"} <= {event["kind"] for event in reloaded}
    assert [event["reason"] for event in heard] == ["opted_in"]

    # While the entry is unloaded, commands are refused and a new subscription waits.
    assert await hass.config_entries.async_unload(routines.entry_id)
    await hass.async_block_till_done()
    error = await refusal(client, LIST)
    waiting = await hass_ws_client(hass)
    await call(waiting, {"type": f"{PREFIX}/subscribe"})
    # One that ends before any entry is set up never listened to a manager.
    await call(waiting, {"type": f"{PREFIX}/subscribe"})
    await call(waiting, {"type": "unsubscribe_events", "subscription": 2})
    assert await hass.config_entries.async_setup(routines.entry_id)
    await hass.async_block_till_done()
    await routines.runtime_data.manager.async_opt_out(home.lamp)
    attached, _ = await events_before(waiting, LIST)

    assert without_message(error) == translated("not_loaded")
    assert opted_out(home) in attached


async def test_registering_again_keeps_one_listener_per_subscription(
    hass: HomeAssistant, home: Home, manager: RoutineManager, hass_ws_client: Any
) -> None:
    client = await hass_ws_client(hass)
    await call(client, {"type": f"{PREFIX}/subscribe"})

    websocket_api.async_register(hass)
    websocket_api.async_register(hass)
    await manager.async_opt_in(home.lamp)
    events, listed = await events_before(client, LIST)

    assert [event["reason"] for event in events] == ["opted_in"]
    assert listed == {"routines": plain(manager.list())}
