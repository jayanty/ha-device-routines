"""Build B lane 20: conversion offers (PRD FR-M1 and 8.3, plan 6.2.5 and 6.2.7).

A hand written automation that a routine on its device can replace exactly (decisions L61
and L65) is offered once, in Repairs and to the console, while `offer_conversions` is
on, while it is turned on and while its device has no routine. Confirming creates the
routine, turns the original off and labels it `Replaced by routine`, and never edits it:
turning it back on is the undo. The home is the synthetic one of `conftest.py`: a living
room fan on the sandbox switch, a desk lamp, a garage door and a contact sensor; Monday
2026-10-19 at 4:00 PM in Los Angeles. Every name is generic.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

from homeassistant.components.repairs import RepairsFlowManager, repairs_flow_manager
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    category_registry as cr,
    entity_registry as er,
    issue_registry as ir,
    label_registry as lr,
)
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import ha_adapter, markers, repairs
from custom_components.device_routines.const import DOMAIN
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import Days, RoutineSettings, Status
from custom_components.device_routines.summary import (
    DEBOUNCE_SECONDS as SUMMARY_DEBOUNCE,
    ConversionOffer,
)
from tests.integration.conftest import (
    ALIAS,
    AUTOMATION,
    FAN,
    GARAGE,
    LAMP,
    Clock,
    Home,
    add_device,
    file_entries,
    file_entry,
    give_routine,
    issue_of,
    reload_all,
    save_entry,
    state_of,
    write_entries,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

EVENING = "automation.fan_evening"
FAILSAFE = "automation.lamp_failsafe"
EVENING_SETTINGS = RoutineSettings(FAN, on_time=time(17), off_time=time(23))
FAILSAFE_SETTINGS = RoutineSettings(LAMP, turn_off_after_min=60)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def step(service: str, entity_id: str) -> dict[str, Any]:
    """An action step as the automation editor saves it."""
    return {"action": service, "metadata": {}, "data": {}, "target": {"entity_id": entity_id}}


def window(
    key: str, alias: str, on_at: str, off_at: str, entity_id: str = FAN, **extra: Any
) -> dict[str, Any]:
    """An exact FR-R1 match: two time triggers, a `choose` that turns one entity on and off."""
    domain = entity_id.partition(".")[0]
    return {
        "id": key,
        "alias": alias,
        "description": "",
        "triggers": [
            {"trigger": "time", "at": on_at, "id": "start"},
            {"trigger": "time", "at": off_at, "id": "stop"},
        ],
        "conditions": [],
        "actions": [
            {
                "choose": [
                    {
                        "conditions": [{"condition": "trigger", "id": ["start"]}],
                        "sequence": [step(f"{domain}.turn_on", entity_id)],
                    },
                    {
                        "conditions": [{"condition": "trigger", "id": ["stop"]}],
                        "sequence": [step(f"{domain}.turn_off", entity_id)],
                    },
                ]
            }
        ],
        "mode": "single",
        **extra,
    }


def failsafe(key: str, alias: str, minutes: int, entity_id: str = LAMP) -> dict[str, Any]:
    """An exact FR-R3 match: off a number of minutes after anything turns it on."""
    domain = entity_id.partition(".")[0]
    return {
        "id": key,
        "alias": alias,
        "description": "",
        "triggers": [
            {
                "trigger": "state",
                "entity_id": [entity_id],
                "to": "on",
                "for": {"hours": 0, "minutes": minutes, "seconds": 0},
            }
        ],
        "conditions": [],
        "actions": [step(f"{domain}.turn_off", entity_id)],
        "mode": "single",
    }


FAN_EVENING = window("1760000000001", "Fan evening", "17:00:00", "23:00:00")
LAMP_FAILSAFE = failsafe("1760000000002", "Lamp failsafe", 60)


async def settle(hass: HomeAssistant, freezer: Any) -> None:
    """Let the summary's debounced index rebuild run."""
    freezer.tick(timedelta(seconds=SUMMARY_DEBOUNCE + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def add_automations(hass: HomeAssistant, freezer: Any, *entries: dict[str, Any]) -> None:
    """Hand written automations, saved next to the routines and reloaded."""
    write_entries(hass, [*file_entries(hass), *entries])
    await reload_all(hass)
    await settle(hass, freezer)


def offered(manager: RoutineManager) -> list[str]:
    return [offer.automation_entity_id for offer in manager.summary.conversion_offers()]


def offer_issues(hass: HomeAssistant) -> list[str]:
    return [issue for issue in repairs.open_issue_ids(hass) if issue.startswith("conversion_offer")]


def registered(hass: HomeAssistant, entity_id: str) -> er.RegistryEntry:
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None, entity_id
    return entry


async def turn(hass: HomeAssistant, entity_id: str, *, on: bool) -> None:
    await hass.services.async_call(
        "automation", "turn_on" if on else "turn_off", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


@pytest.fixture
def at_four(clock: Clock) -> Clock:
    """Monday 16:00, an hour before the fan's evening starts."""
    clock.set(clock.at(0, "16:00"))
    return clock


@pytest.fixture
async def fixer(hass: HomeAssistant) -> RepairsFlowManager:
    """The core's Repairs flow manager, which the Repairs dashboard drives."""
    assert await async_setup_component(hass, "repairs", {})
    flows = repairs_flow_manager(hass)
    assert flows is not None
    return flows


# --------------------------------------------------------------------------------------
# What is offered
# --------------------------------------------------------------------------------------


async def test_exact_matches_are_offered_once_per_automation(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    fan_failsafe = failsafe("1760000000003", "Fan failsafe", 30, FAN)
    # A partial match: the window also notifies, which a routine would drop.
    notifying = window("1760000000004", "Lamp evening", "18:00:00", "22:00:00", LAMP)
    notifying["actions"][0]["choose"][0]["sequence"].append({"action": "notify.notify"})
    await add_automations(hass, freezer, FAN_EVENING, LAMP_FAILSAFE, fan_failsafe, notifying)

    offers = manager.summary.conversion_offers()

    # By device name, then alias: each exact automation once, the device's two included.
    assert [(offer.device_name, offer.alias) for offer in offers] == [
        ("Desk lamp", "Lamp failsafe"),
        ("Living room fan", "Fan evening"),
        ("Living room fan", "Fan failsafe"),
    ]
    assert offers[1] == ConversionOffer(
        automation_id="1760000000001",
        automation_entity_id=EVENING,
        alias="Fan evening",
        device_id=home.fan,
        device_name="Living room fan",
        settings=EVENING_SETTINGS,
        original_sentence="5:00 PM: on, 11:00 PM: off",
        routine_sentence="5:00 PM: on, 11:00 PM: off",
    )
    assert offers[0].settings == FAILSAFE_SETTINGS
    assert offer_issues(hass) == [
        "conversion_offer_fan_evening",
        "conversion_offer_fan_failsafe",
        "conversion_offer_lamp_failsafe",
    ]
    assert manager.summary.offer_for("automation.lamp_evening") is None

    # Another rebuild finds the same offers, each still once.
    await reload_all(hass)
    await settle(hass, freezer)
    assert manager.summary.conversion_offers() == offers
    assert len(offer_issues(hass)) == 3


async def test_the_issue_shows_both_sentences(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    fixer: RepairsFlowManager,
) -> None:
    await add_automations(hass, freezer, FAN_EVENING, LAMP_FAILSAFE)

    issue = issue_of(hass, "conversion_offer", "fan_evening")
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_key == "conversion_offer"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.data == {"issue_id": "conversion_offer", "subject": "fan_evening"}
    assert issue.translation_placeholders == {
        "alias": "Fan evening",
        "device": "Living room fan",
        "original": "5:00 PM: on, 11:00 PM: off",
        "routine": "5:00 PM: on, 11:00 PM: off",
    }
    failsafe_issue = issue_of(hass, "conversion_offer", "lamp_failsafe")
    assert failsafe_issue is not None
    assert failsafe_issue.translation_placeholders == {
        "alias": "Lamp failsafe",
        "device": "Desk lamp",
        "original": "Off 60 min after it turns on",
        "routine": "Off 60 min after it turns on",
    }

    # Two steps: both sentences first, then the confirmation; nothing changes before it.
    result = await fixer.async_init(DOMAIN, context={"issue_id": "conversion_offer_fan_evening"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "compare"
    assert result["description_placeholders"] == issue.translation_placeholders
    result = await fixer.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == issue.translation_placeholders
    assert manager.get(home.fan) is None
    assert state_of(hass, EVENING) == "on"


async def test_no_offer_for_a_device_with_a_routine(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await add_automations(hass, freezer, FAN_EVENING, LAMP_FAILSAFE)

    assert offered(manager) == [FAILSAFE]
    assert offer_issues(hass) == ["conversion_offer_lamp_failsafe"]

    # Routine controls alone are no routine: the lamp opted in keeps its offer.
    await manager.async_opt_in(home.lamp)
    assert offered(manager) == [FAILSAFE]

    # A routine taken over (detached) still counts: the device gets no offer.
    automation_id = markers.automation_id(home.fan)
    await save_entry(
        hass,
        {
            "id": automation_id,
            "alias": ALIAS,
            "triggers": [{"trigger": "time", "at": "17:00:00"}],
            "actions": [{"action": "switch.turn_on", "target": {"entity_id": FAN}}],
        },
    )
    await settle(hass, freezer)
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.DETACHED
    assert offered(manager) == [FAILSAFE]


async def test_no_offer_for_a_disabled_automation(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    starts_off = window("1760000000005", "Lamp mornings", "07:00:00", "08:00:00", LAMP)
    starts_off["initial_state"] = False
    await add_automations(hass, freezer, FAN_EVENING, starts_off)
    assert offered(manager) == [EVENING]

    # Converting a disabled one would start a schedule nobody runs today (L66).
    await turn(hass, EVENING, on=False)
    assert offered(manager) == []
    assert offer_issues(hass) == []

    await turn(hass, EVENING, on=True)
    await turn(hass, "automation.lamp_mornings", on=True)
    assert offered(manager) == ["automation.lamp_mornings", EVENING]


@pytest.mark.parametrize("options", [{"offer_conversions": False}])
async def test_no_offer_while_offer_conversions_is_off(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    routines: MockConfigEntry,
) -> None:
    await add_automations(hass, freezer, FAN_EVENING, LAMP_FAILSAFE)

    assert offered(manager) == []
    assert offer_issues(hass) == []
    with pytest.raises(ServiceValidationError) as refused:
        await manager.async_convert_automation(EVENING)
    assert refused.value.translation_key == "conversion_not_offered"

    # Turned on: offered; off again: every offer issue clears at the next setup.
    hass.config_entries.async_update_entry(routines, options={"offer_conversions": True})
    assert await hass.config_entries.async_reload(routines.entry_id)
    await hass.async_block_till_done()
    assert len(offer_issues(hass)) == 2
    hass.config_entries.async_update_entry(routines, options={"offer_conversions": False})
    assert await hass.config_entries.async_reload(routines.entry_id)
    await hass.async_block_till_done()
    assert offer_issues(hass) == []


async def test_no_offer_for_a_refused_action_or_an_entity_a_routine_cannot_drive(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """PRD 5.4: a garage door is never opened on a schedule, so it is never offered."""
    lock = "switch.desk_lamp_child_lock"
    er.async_get(hass).async_get_or_create(
        "switch",
        "sandbox",
        "lamp_child_lock",
        device_id=home.lamp,
        suggested_object_id="desk_lamp_child_lock",
        entity_category=EntityCategory.CONFIG,
        config_entry=home.source,
    )
    hass.states.async_set(lock, "off")
    garage = window("1760000000006", "Garage hours", "08:00:00", "18:00:00", GARAGE)
    garage["actions"][0]["choose"][0]["sequence"] = [step("cover.open_cover", GARAGE)]
    garage["actions"][0]["choose"][1]["sequence"] = [step("cover.close_cover", GARAGE)]
    child_lock = window("1760000000007", "Child lock", "20:00:00", "07:00:00", lock)
    await add_automations(hass, freezer, garage, child_lock)

    assert offered(manager) == []
    assert offer_issues(hass) == []


async def test_no_offer_for_an_automation_without_an_id(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """Without an id there is no registry entry to carry the `Replaced by routine` label."""
    anonymous = window("unused", "Anonymous evening", "17:00:00", "23:00:00")
    del anonymous["id"]
    await add_automations(hass, freezer, anonymous)

    assert state_of(hass, "automation.anonymous_evening") == "on"
    assert offered(manager) == []


# --------------------------------------------------------------------------------------
# Converting
# --------------------------------------------------------------------------------------


async def test_confirming_creates_the_routine_turns_the_original_off_and_labels_it(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    fixer: RepairsFlowManager,
) -> None:
    await add_automations(hass, freezer, FAN_EVENING)
    original = file_entry(hass, FAN_EVENING["id"])
    assert original is not None

    result = await fixer.async_init(DOMAIN, context={"issue_id": "conversion_offer_fan_evening"})
    result = await fixer.async_configure(result["flow_id"], {})
    result = await fixer.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The routine, with M1 to M8 and the offer's settings over the global defaults.
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert view.settings == RoutineSettings(FAN, on_time=time(17), off_time=time(23))
    entry = file_entry(hass, markers.automation_id(home.fan))
    assert entry is not None
    assert entry["id"] == markers.automation_id(home.fan)  # M1
    assert entry["use_blueprint"]["path"] == markers.BLUEPRINT_PATH  # M2
    assert entry["alias"] == ALIAS  # M3
    generated = markers.presentation("Living room fan", manager.summary.phrases)
    assert entry["description"] == generated.description  # M4
    routine = registered(hass, AUTOMATION)  # M8
    category = cr.async_get(hass).async_get_category(
        scope="automation", category_id=routine.categories["automation"]
    )
    assert category is not None
    assert category.name == markers.CATEGORY_NAME  # M5
    assert markers.LABEL_ID in routine.labels  # M6
    assert routine.icon == markers.ICON  # M7
    assert state_of(hass, AUTOMATION) == "on"
    # The original: turned off, labeled, its config and its registry entry otherwise as
    # they were, no marker on it.
    assert state_of(hass, EVENING) == "off"
    assert file_entry(hass, FAN_EVENING["id"]) == original
    label = lr.async_get(hass).async_get_label(markers.REPLACED_LABEL_ID)
    assert label is not None
    assert label.name == "Replaced by routine"
    replaced = registered(hass, EVENING)
    assert replaced.labels == {markers.REPLACED_LABEL_ID}
    assert replaced.categories == {}
    assert replaced.icon is None
    assert not markers.has_routine_id(original)
    # The offer ended with the conversion.
    assert offered(manager) == []
    assert offer_issues(hass) == []

    # At 5:00 PM the routine turns the fan on; the original no longer runs.
    await at_four.to(at_four.at(0, "17:00:30"))
    assert state_of(hass, FAN) == "on"
    state = hass.states.get(EVENING)
    assert state is not None
    assert state.attributes["last_triggered"] is None


async def test_the_original_keeps_its_own_labels(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    await add_automations(hass, freezer, LAMP_FAILSAFE)
    mine = lr.async_get(hass).async_create("Lighting")
    er.async_get(hass).async_update_entity(FAILSAFE, labels={mine.label_id})

    view = await manager.async_convert_automation(FAILSAFE)

    assert view.settings.turn_off_after_min == 60
    assert view.settings.days is Days.EVERY_DAY
    assert registered(hass, FAILSAFE).labels == {mine.label_id, markers.REPLACED_LABEL_ID}
    assert markers.LABEL_ID not in registered(hass, FAILSAFE).labels


@pytest.mark.parametrize(
    "options",
    [
        {
            "default_catch_up": False,
            "default_respect_manual": False,
            "default_late_start_window_min": 30,
        }
    ],
)
async def test_a_conversion_applies_the_offer_over_the_global_defaults(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """Exactly as an opt in plus an update: the offer's fields, the defaults for the rest."""
    await add_automations(hass, freezer, FAN_EVENING)
    offer = manager.summary.offer_for(EVENING)
    assert offer is not None
    assert offer.settings == EVENING_SETTINGS

    view = await manager.async_convert_automation(EVENING)

    assert view.settings == RoutineSettings(
        FAN,
        on_time=time(17),
        off_time=time(23),
        catch_up=False,
        respect_manual=False,
        late_start_window_min=30,
    )


async def test_an_offer_gone_before_confirm_aborts(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    fixer: RepairsFlowManager,
) -> None:
    await add_automations(hass, freezer, FAN_EVENING)
    result = await fixer.async_init(DOMAIN, context={"issue_id": "conversion_offer_fan_evening"})
    result = await fixer.async_configure(result["flow_id"], {})
    assert result["step_id"] == "confirm"

    # The original is turned off while the confirmation is open: the offer ends.
    await turn(hass, EVENING, on=False)
    assert issue_of(hass, "conversion_offer", "fan_evening") is None
    result = await fixer.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_fixed"
    # The abort names the automation and the device the steps showed.
    placeholders = result["description_placeholders"]
    assert placeholders is not None
    assert placeholders["alias"] == "Fan evening"
    assert placeholders["device"] == "Living room fan"
    # Nothing was converted.
    assert manager.get(home.fan) is None
    assert file_entry(hass, markers.automation_id(home.fan)) is None
    assert registered(hass, EVENING).labels == set()


async def test_an_automation_edited_since_the_rebuild_is_not_converted(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """Inside the rebuild's debounce the offer still shows; the edit is what counts."""
    await add_automations(hass, freezer, FAN_EVENING)
    edited = window(FAN_EVENING["id"], "Fan evening", "17:00:00", "22:00:00")
    write_entries(hass, [edited])
    await hass.services.async_call("automation", "reload", {"id": edited["id"]}, blocking=True)

    assert offered(manager) == [EVENING]
    with pytest.raises(ServiceValidationError) as refused:
        await manager.async_convert_automation(EVENING)

    assert refused.value.translation_key == "conversion_not_offered"
    assert refused.value.translation_placeholders == {"automation": EVENING}
    assert manager.get(home.fan) is None
    await settle(hass, freezer)
    offers = manager.summary.conversion_offers()
    assert [offer.settings.off_time for offer in offers] == [time(22)]


async def test_turning_the_original_back_on_is_the_undo(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    await add_automations(hass, freezer, FAN_EVENING)
    await manager.async_convert_automation(EVENING)
    await settle(hass, freezer)

    await turn(hass, EVENING, on=True)
    await settle(hass, freezer)

    # The routine stays; the original runs again; no offer returns while the fan has a
    # routine.
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert state_of(hass, EVENING) == "on"
    assert offered(manager) == []
    assert offer_issues(hass) == []
    await at_four.to(at_four.at(0, "17:00:30"))
    state = hass.states.get(EVENING)
    assert state is not None
    assert state.attributes["last_triggered"] is not None
    assert state_of(hass, FAN) == "on"


# --------------------------------------------------------------------------------------
# Refusals and failures: the original stays untouched
# --------------------------------------------------------------------------------------


async def test_a_stale_offer_for_a_device_with_a_routine_is_refused(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_automations(hass, freezer, FAN_EVENING)
    offer = manager.summary.offer_for(EVENING)
    assert offer is not None
    await give_routine(hass, manager, home.fan, freezer, on_time=time(6))
    monkeypatch.setattr(manager.summary, "offer_for", lambda _entity_id: offer)

    with pytest.raises(ServiceValidationError) as refused:
        await manager.async_convert_automation(EVENING)

    assert refused.value.translation_key == "device_has_routine"
    assert refused.value.translation_placeholders == {"device": "Living room fan"}
    assert state_of(hass, EVENING) == "on"
    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.on_time == time(6)


async def test_no_conversion_while_editing_is_unavailable(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_automations(hass, freezer, FAN_EVENING)
    monkeypatch.setattr(
        ha_adapter,
        "check",
        lambda _hass: ha_adapter.AdapterReport(failed=(ha_adapter.CAPABILITY_WRITE,)),
    )
    await manager.async_reconcile()

    with pytest.raises(ServiceValidationError) as refused:
        await manager.async_convert_automation(EVENING)

    assert refused.value.translation_key == "editing_unavailable"
    assert manager.get(home.fan) is None
    assert state_of(hass, EVENING) == "on"


async def test_a_device_changed_since_the_rebuild_keeps_the_original(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """A blind that became a garage door inside the rebuild's debounce: PRD 5.4 refuses."""
    blind = "cover.patio_blind"
    device = add_device(hass, home.source, "blind", "Patio blind", blind, "closed")
    hours = window("1760000000008", "Blind hours", "08:00:00", "18:00:00", blind)
    hours["actions"][0]["choose"][0]["sequence"] = [step("cover.open_cover", blind)]
    hours["actions"][0]["choose"][1]["sequence"] = [step("cover.close_cover", blind)]
    await add_automations(hass, freezer, hours)
    assert offered(manager) == ["automation.blind_hours"]
    er.async_get(hass).async_update_entity(blind, device_class="garage")

    with pytest.raises(ServiceValidationError) as refused:
        await manager.async_convert_automation("automation.blind_hours")

    assert refused.value.translation_key == "on_time_not_supported"
    assert refused.value.translation_placeholders is not None
    assert refused.value.translation_placeholders["setting"] == "on_time"
    # The device is opted in, with no routine written; the original runs as before.
    assert file_entry(hass, markers.automation_id(device)) is None
    assert state_of(hass, "automation.blind_hours") == "on"
    await settle(hass, freezer)
    assert offered(manager) == []


async def test_a_write_that_fails_leaves_the_original_untouched(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    fixer: RepairsFlowManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_automations(hass, freezer, FAN_EVENING)

    async def broken(*_args: Any) -> Any:
        raise ha_adapter.AdapterError("synthetic failure")

    monkeypatch.setattr(ha_adapter, "async_write_automation", broken)
    with pytest.raises(HomeAssistantError) as failed:
        await manager.async_convert_automation(EVENING)
    assert failed.value.translation_key == "conversion_failed"
    assert failed.value.translation_placeholders == {
        "alias": "Fan evening",
        "device": "Living room fan",
    }
    assert state_of(hass, EVENING) == "on"
    assert registered(hass, EVENING).labels == set()
    assert file_entry(hass, markers.automation_id(home.fan)) is None

    # Through Repairs the same failure aborts and keeps the offer for another try.
    result = await fixer.async_init(DOMAIN, context={"issue_id": "conversion_offer_fan_evening"})
    result = await fixer.async_configure(result["flow_id"], {})
    result = await fixer.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_fixed"
    assert issue_of(hass, "conversion_offer", "fan_evening") is not None


async def test_an_original_deleted_while_converting_has_nothing_to_label(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await add_automations(hass, freezer, FAN_EVENING)
    real = ha_adapter.async_write_automation

    async def write_then_delete(*args: Any) -> Any:
        written = await real(*args)
        er.async_get(hass).async_remove(EVENING)
        return written

    monkeypatch.setattr(ha_adapter, "async_write_automation", write_then_delete)
    view = await manager.async_convert_automation(EVENING)

    assert view.settings == EVENING_SETTINGS
    assert er.async_get(hass).async_get(EVENING) is None
    assert lr.async_get(hass).async_get_label(markers.REPLACED_LABEL_ID) is not None


async def test_an_offer_is_not_a_problem(
    hass: HomeAssistant, home: Home, manager: RoutineManager, at_four: Clock, freezer: Any
) -> None:
    """An open offer leaves the hub Problem sensor off and Health's issues out (L67)."""
    problem = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{DOMAIN}_hub_hub_problem"
    )
    assert problem is not None
    await add_automations(hass, freezer, FAN_EVENING)

    assert offer_issues(hass) == ["conversion_offer_fan_evening"]
    assert repairs.problem_issue_ids(hass) == []
    assert state_of(hass, problem) == "off"
    assert manager.health_inputs().issues == ()

    # A problem beside the offer turns the sensor on and is the only one Health lists.
    repairs.async_sync_issue(hass, repairs.ADAPTER_INCOMPATIBLE, present=True)
    await hass.async_block_till_done()
    assert repairs.problem_issue_ids(hass) == [repairs.ADAPTER_INCOMPATIBLE]
    assert state_of(hass, problem) == "on"
    assert manager.health_inputs().issues == (repairs.ADAPTER_INCOMPATIBLE,)
