"""Build A lane 9: the actions (TECH_SPEC 4.6, PRD 5.5, FR-R11 to FR-R15, S13).

Every action is called the way a script or a dashboard button calls it: through the
service registry, with a native target, on the synthetic home of the manager fixtures and
the real blueprint. What an action does to a routine is the manager's and is proven in
`test_manager.py`; these tests prove the registration, the schemas, the targets, the
ignored list, the errors and the response shape. Every id and name is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, ServiceResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, label_registry as lr
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import probatio as vol
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import yaml

from custom_components.device_routines import services
from custom_components.device_routines.const import DOMAIN
from custom_components.device_routines.domains import SUPPORTED_DOMAINS
from custom_components.device_routines.maintenance import MaintenanceAction, MaintenanceReport
from custom_components.device_routines.manager import (
    ActionResult,
    ActionResults,
    IgnoredTarget,
    RoutineManager,
)
from custom_components.device_routines.models import Occurrence, Status, Verb
from tests.integration.conftest import AUTOMATION, FAN, GARAGE, Clock, Home, give_routine

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

COMPONENT = Path(services.__file__).parent
ROUTINE_ACTIONS = ("skip_next", "pause", "resume", "enable", "disable")
RESULT_FIELDS = {
    "device_id",
    "device_name",
    "action",
    "paused_until",
    "skipped_action",
    "next_action",
}


async def call(
    hass: HomeAssistant, service: str, target: dict[str, Any] | None = None, **data: Any
) -> dict[str, Any]:
    """Call an action the way a script does and return its response."""
    response: ServiceResponse = await hass.services.async_call(
        DOMAIN, service, data, target=target, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    assert isinstance(response, dict)
    json.dumps(response)  # a response is plain JSON: datetimes are ISO strings
    return response


def moment(value: Any) -> datetime:
    assert isinstance(value, str)
    return datetime.fromisoformat(value)


def label_devices(hass: HomeAssistant, name: str, *device_ids: str) -> str:
    """Create a label and put it on the devices; return the label id."""
    label = lr.async_get(hass).async_create(name)
    devices = dr.async_get(hass)
    for device_id in device_ids:
        device = devices.async_get(device_id)
        assert device is not None
        devices.async_update_device(device_id, labels={*device.labels, label.label_id})
    return label.label_id


def status_of(manager: RoutineManager, device_id: str) -> Status:
    view = manager.get(device_id)
    assert view is not None
    return view.status


# --------------------------------------------------------------------------------------
# Registration (quality rule action-setup)
# --------------------------------------------------------------------------------------


async def test_the_actions_exist_before_an_entry_loads_and_say_so_when_none_is(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert set(hass.services.async_services_for_domain(DOMAIN)) == set(services.SERVICES)
    for action, data in (
        ("skip_next", {"device_id": "any-device"}),
        ("pause", {"device_id": "any-device", "for": {"hours": 1}}),
        ("resume", {}),
        ("enable", {}),
        ("disable", {}),
        ("maintenance", {"action": "refresh_summaries"}),
    ):
        with pytest.raises(ServiceValidationError) as raised:
            await hass.services.async_call(DOMAIN, action, data, blocking=True)
        assert (raised.value.translation_domain, raised.value.translation_key) == (
            DOMAIN,
            "not_loaded",
        )


async def test_the_actions_outlive_an_unloaded_entry_and_say_it_is_not_loaded(
    hass: HomeAssistant, home: Home, routines: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_unload(routines.entry_id)
    await hass.async_block_till_done()

    assert set(hass.services.async_services_for_domain(DOMAIN)) == set(services.SERVICES)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            DOMAIN, "skip_next", {}, target={"device_id": home.fan}, blocking=True
        )
    assert raised.value.translation_key == "not_loaded"


# --------------------------------------------------------------------------------------
# Targets and the ignored list (FR-R15, S13)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["device", "entity", "area", "floor", "label"])
async def test_every_routine_action_takes_device_entity_area_floor_and_label_targets(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    clock: Clock,
    freezer: Any,
    kind: str,
) -> None:
    clock.set(clock.at(0, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    evening = label_devices(hass, "Evening", home.fan, home.lamp)
    target = {
        "device": {"device_id": home.fan},
        "entity": {"entity_id": FAN},
        "area": {"area_id": home.area},
        "floor": {"floor_id": home.floor},
        "label": {"label_id": evening},
    }[kind]
    # An area, floor or label also covers the desk lamp, which has no routine (S13).
    plain = (
        []
        if kind in {"device", "entity"}
        else [{"target": home.lamp, "kind": "device", "reason": "no_routine"}]
    )

    for action, data, status in (
        ("skip_next", {}, Status.SKIPPING),
        ("pause", {"for": {"hours": 1}}, Status.PAUSED),
        ("resume", {}, Status.ACTIVE),
        ("disable", {}, Status.OFF),
        ("enable", {}, Status.ACTIVE),
    ):
        response = await call(hass, action, target, **data)

        assert [(item["device_id"], item["action"]) for item in response["results"]] == [
            (home.fan, action)
        ], action
        assert response["ignored"] == plain, action
        assert status_of(manager, home.fan) is status, action


async def test_skip_next_on_a_label_skips_the_routine_and_lists_the_plain_device(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    """S13: a dashboard button calls skip_next on a label over one routine and one plain device."""
    clock.set(clock.at(2, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))
    evening = label_devices(hass, "Evening", home.fan, home.lamp)

    response = await call(hass, "skip_next", {"label_id": evening})

    assert [item["device_id"] for item in response["results"]] == [home.fan]
    assert response["ignored"] == [{"target": home.lamp, "kind": "device", "reason": "no_routine"}]
    assert status_of(manager, home.fan) is Status.SKIPPING


async def test_the_ignored_list_names_every_target_without_a_routine_with_its_reason(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "10:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    # The lamp has a routine, but only a run timer that is not running: nothing to skip.
    await give_routine(hass, manager, home.lamp, freezer, turn_off_after_min=30)
    unused = lr.async_get(hass).async_create("Unused")

    response = await call(
        hass,
        "skip_next",
        {
            "device_id": [home.fan, home.lamp, home.garage],
            "entity_id": ["sensor.no_such_sensor"],
            "area_id": ["no_such_area"],
            "label_id": [unused.label_id],
        },
    )

    assert [item["device_id"] for item in response["results"]] == [home.fan]
    assert response["ignored"] == [
        {"target": home.garage, "kind": "device", "reason": "no_routine"},
        {"target": "sensor.no_such_sensor", "kind": "entity", "reason": "no_routine"},
        {"target": "no_such_area", "kind": "area", "reason": "no_routine"},
        {"target": unused.label_id, "kind": "label", "reason": "no_routine"},
        {"target": home.lamp, "kind": "device", "reason": "nothing_to_skip"},
    ]


async def test_a_target_without_any_routine_raises_no_routine_targets(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    plain = label_devices(hass, "Plain", home.lamp, home.garage)

    for action in ROUTINE_ACTIONS:
        data = {"for": {"minutes": 30}} if action == "pause" else {}
        for target in ({"device_id": home.lamp}, {"entity_id": GARAGE}, {"label_id": plain}, None):
            with pytest.raises(ServiceValidationError) as raised:
                await hass.services.async_call(DOMAIN, action, data, target=target, blocking=True)
            assert (raised.value.translation_domain, raised.value.translation_key) == (
                DOMAIN,
                "no_routine_targets",
            ), (action, target)
    assert status_of(manager, home.fan) is Status.ACTIVE


# --------------------------------------------------------------------------------------
# Pause: until or for, exactly one (FR-R12)
# --------------------------------------------------------------------------------------


async def test_pause_takes_exactly_one_of_until_and_for(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    target = {"device_id": home.fan}

    for data in (
        {},
        {"until": clock.at(0, "18:00").isoformat(), "for": {"hours": 1}},
        {"for": "-00:10:00"},
        {"for": "soon"},
        {"until": "not a time"},
    ):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(DOMAIN, "pause", data, target=target, blocking=True)
    assert status_of(manager, home.fan) is Status.ACTIVE

    # The datetime selector sends a local time without an offset.
    naive = clock.at(0, "18:30").replace(tzinfo=None).isoformat(sep=" ")
    response = await call(hass, "pause", target, until=naive)
    assert moment(response["results"][0]["paused_until"]) == clock.at(0, "18:30")
    assert status_of(manager, home.fan) is Status.PAUSED

    # An offset is kept; a datetime object from a script works too.
    response = await call(hass, "pause", target, until=dt_util.as_utc(clock.at(0, "19:00")))
    assert moment(response["results"][0]["paused_until"]) == clock.at(0, "19:00")

    # The duration selector sends hours, minutes and seconds.
    response = await call(
        hass, "pause", target, **{"for": {"hours": 2, "minutes": 15, "seconds": 0}}
    )
    paused_until = dt_util.utcnow() + timedelta(hours=2, minutes=15)
    assert moment(response["results"][0]["paused_until"]) == paused_until
    response = await call(hass, "pause", target, **{"for": "00:45:00"})
    assert moment(response["results"][0]["paused_until"]) == dt_util.utcnow() + timedelta(
        minutes=45
    )


@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason=(
        "manager gap (lane 9 report): async_run_action checks paused_until_in_past per "
        "device and lists every device as ignored instead of raising, as FR-R12 asks"
    ),
)
async def test_a_pause_that_ends_now_or_in_the_past_is_rejected_with_a_translated_error(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))

    for data in ({"until": clock.at(0, "14:00").isoformat()}, {"for": "00:00:00"}):
        with pytest.raises(ServiceValidationError) as raised:
            await hass.services.async_call(
                DOMAIN, "pause", data, target={"device_id": home.fan}, blocking=True
            )
        assert raised.value.translation_key == "paused_until_in_past"


# --------------------------------------------------------------------------------------
# Responses (TECH_SPEC 4.6)
# --------------------------------------------------------------------------------------


async def test_skip_next_responds_with_the_tech_spec_fields(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    """FR-R11's example: Wednesday 15:00, a 17:00 to 09:00 window, Skip next."""
    clock.set(clock.at(2, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))

    response = await call(hass, "skip_next", {"device_id": home.fan})

    assert set(response) == {"results", "ignored"}
    assert response["ignored"] == []
    [result] = response["results"]
    assert set(result) == RESULT_FIELDS
    assert (result["device_id"], result["device_name"], result["action"]) == (
        home.fan,
        "Living room fan",
        "skip_next",
    )
    assert moment(result["paused_until"]) == clock.at(3, "09:01")
    assert result["skipped_action"]["verb"] == "on"
    assert moment(result["skipped_action"]["at"]) == clock.at(2, "17:00")
    assert result["next_action"]["verb"] == "on"
    assert moment(result["next_action"]["at"]) == clock.at(3, "17:00")


async def test_a_response_is_optional_and_the_action_runs_without_one(
    hass: HomeAssistant, home: Home, manager: RoutineManager, clock: Clock, freezer: Any
) -> None:
    clock.set(clock.at(0, "15:00"))
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))

    assert (
        await hass.services.async_call(
            DOMAIN, "pause", {"for": {"hours": 1}}, target={"device_id": home.fan}, blocking=True
        )
        is None
    )
    assert status_of(manager, home.fan) is Status.PAUSED

    response = await call(hass, "resume", {"device_id": home.fan})
    [result] = response["results"]
    assert (result["paused_until"], result["skipped_action"]) == (None, None)
    assert result["next_action"]["verb"] == "on"
    assert moment(result["next_action"]["at"]) == clock.at(0, "17:00")


def test_the_response_serializes_every_field_as_plain_json() -> None:
    at = datetime(2026, 10, 19, 17, 0, tzinfo=UTC)
    done = ActionResults(
        results=(
            ActionResult("device-a", "Device A", "skip_next", at, Occurrence(at, Verb.ON), None),
            ActionResult("device-b", "Device B", "pause", None, None, Occurrence(at, None)),
        ),
        ignored=(IgnoredTarget("label-a", "label", "no_routine"),),
    )

    assert services.action_response(done) == {
        "results": [
            {
                "device_id": "device-a",
                "device_name": "Device A",
                "action": "skip_next",
                "paused_until": "2026-10-19T17:00:00+00:00",
                "skipped_action": {"at": "2026-10-19T17:00:00+00:00", "verb": "on"},
                "next_action": None,
            },
            {
                "device_id": "device-b",
                "device_name": "Device B",
                "action": "pause",
                "paused_until": None,
                "skipped_action": None,
                "next_action": {"at": "2026-10-19T17:00:00+00:00", "verb": None},
            },
        ],
        "ignored": [{"target": "label-a", "kind": "label", "reason": "no_routine"}],
    }
    report = MaintenanceReport(MaintenanceAction.CLEAN_UP_NOW, would_change=["device-a"])
    assert services.maintenance_response(report) == {
        "action": "clean_up_now",
        "changed": [],
        "would_change": ["device-a"],
    }
    assert type(services.maintenance_response(report)["action"]) is str


# --------------------------------------------------------------------------------------
# Maintenance (PRD 10.4, TECH_SPEC 4.6)
# --------------------------------------------------------------------------------------


async def test_maintenance_runs_each_action_with_and_without_a_dry_run(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))

    assert await call(hass, "maintenance", action="refresh_summaries", dry_run=True) == {
        "action": "refresh_summaries",
        "changed": [],
        "would_change": [home.fan],
    }
    assert await call(hass, "maintenance", action="refresh_summaries") == {
        "action": "refresh_summaries",
        "changed": [home.fan],
        "would_change": [],
    }
    for action in ("clean_up_now", "rebuild_index", "reinstall_blueprint"):
        assert await call(hass, "maintenance", action=action, dry_run=True) == {
            "action": action,
            "changed": [],
            "would_change": [],
        }, action

    # An opted out device is a cleanup candidate: the dry run lists it, the run removes it.
    await manager.async_opt_out(home.fan)
    await hass.async_block_till_done()
    dry = await call(hass, "maintenance", action="clean_up_now", dry_run=True)
    assert dry["would_change"] == [home.fan]
    assert manager.store.data.opted_out_at.keys() == {home.fan}
    assert (
        await hass.services.async_call(
            DOMAIN, "maintenance", {"action": "clean_up_now"}, blocking=True
        )
        is None
    )
    assert manager.store.data.opted_out_at == {}
    assert hass.states.get(AUTOMATION) is None

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "maintenance", {"action": "format_everything"}, blocking=True
        )
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "maintenance", {}, blocking=True)


# --------------------------------------------------------------------------------------
# services.yaml and its translations (hassfest's services check, locally)
# --------------------------------------------------------------------------------------


def load_services_yaml() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (COMPONENT / "services.yaml").read_text(encoding="utf-8")
    )
    # hassfest accepts only action slugs as top level keys (no hidden anchor keys).
    assert all(name.isidentifier() and name.islower() for name in loaded), list(loaded)
    return loaded


def load_strings() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    return loaded


def test_every_action_and_field_in_services_yaml_is_translated() -> None:
    described = load_services_yaml()
    strings = load_strings()

    assert set(described) == set(services.SERVICES) == set(strings["services"])
    for name, spec in described.items():
        # Names and descriptions live in strings.json, as hassfest wants for translations.
        assert not {"name", "description"} & set(spec), name
        text = strings["services"][name]
        assert text["name"], name
        assert text["description"], name
        fields = spec.get("fields") or {}
        assert set(fields) == set(text.get("fields", {})), name
        for field, field_spec in fields.items():
            assert not {"name", "description"} & set(field_spec), (name, field)
            assert text["fields"][field]["name"], (name, field)
            assert text["fields"][field]["description"], (name, field)
            select = (field_spec["selector"] or {}).get("select")
            if select is not None:
                options = strings["selector"][select["translation_key"]]["options"]
                assert set(options) == set(select["options"]), (name, field)
    assert services.NOT_LOADED in strings["exceptions"]


def test_the_actions_and_their_fields_are_the_tech_spec_ones() -> None:
    described = load_services_yaml()

    for name in ROUTINE_ACTIONS:
        # Every routine action takes a native target, narrowed to the entities a routine
        # can drive (and routine automations), never to this integration's own records.
        [entity_filter] = described[name]["target"]["entity"]
        assert set(entity_filter["domain"]) == SUPPORTED_DOMAINS | {"automation"}, name
        assert "device" not in described[name]["target"], name
    assert set(described["pause"]["fields"]) == {"until", "for"}
    assert "datetime" in described["pause"]["fields"]["until"]["selector"]
    assert "duration" in described["pause"]["fields"]["for"]["selector"]
    for name in ("skip_next", "resume", "enable", "disable"):
        assert not described[name].get("fields"), name
    assert "target" not in described["maintenance"]
    action = described["maintenance"]["fields"]["action"]
    assert action["required"] is True
    assert action["selector"]["select"]["options"] == [item.value for item in MaintenanceAction]
    assert described["maintenance"]["fields"]["dry_run"]["default"] is False


async def test_the_core_reads_services_yaml_and_offers_optional_responses(
    hass: HomeAssistant,
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    descriptions = (await async_get_all_descriptions(hass))[DOMAIN]

    assert set(descriptions) == set(services.SERVICES)
    for name, description in descriptions.items():
        assert description["response"] == {"optional": True}, name
    for name in ROUTINE_ACTIONS:
        assert descriptions[name]["target"]["entity"], name
    assert set(descriptions["pause"]["fields"]) == {"until", "for"}
    assert set(descriptions["maintenance"]["fields"]) == {"action", "dry_run"}


def test_the_pause_schema_reads_a_duration_as_a_timedelta() -> None:
    validated = services.PAUSE_SCHEMA({"device_id": "device-a", "for": {"minutes": 90}})

    assert validated["for"] == timedelta(minutes=90)
    assert validated["device_id"] == ["device-a"]
