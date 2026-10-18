"""The config flow, the options flow and removing the integration (Build A lane 10).

Setup is one empty confirmation, followed by the optional suggestions screen when the
summary flagged devices (PRD D33). The options flow is a menu of the settings page, the
devices picker and the suggestions screen (TECH_SPEC 4.12). Removing the entry applies On
removal (PRD 8.2, acceptance S8). Every name is generic and every id synthetic.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState, FlowType
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    category_registry as cr,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
    label_registry as lr,
)
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    NumberSelector,
    SelectSelector,
)
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import dump
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import ha_adapter, markers, repairs
from custom_components.device_routines.config_flow import (
    CONF_DEVICES,
    NUMBER_UNITS,
    DeviceRoutinesOptionsFlow,
)
from custom_components.device_routines.const import CONF_SYSTEM_USER_ID, DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.sentence import load_phrases
from custom_components.device_routines.settings import (
    BOOLEANS,
    ENUMS,
    RANGES,
    GlobalSettings,
    OnRemoval,
    TimeFormat,
)
from custom_components.device_routines.store import STORAGE_KEY
from custom_components.device_routines.summary import DEBOUNCE_SECONDS as SUMMARY_DEBOUNCE
from tests.blueprint.conftest import SandboxSwitch, async_add_sandbox_entities
from tests.integration.conftest import (
    ALIAS,
    AUTOMATION,
    GARAGE,
    LAMP,
    OVERRIDE,
    PAUSED,
    SCHEDULE,
    TIMER,
    Clock,
    Home,
    automations_path,
    file_entries,
    file_entry,
    flush,
    give_routine,
    issue_of,
    save_entry,
    state_of,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

STRINGS = json.loads(
    (Path(__file__).parents[2] / "custom_components" / DOMAIN / "strings.json").read_text(
        encoding="utf-8"
    )
)
FORMERLY = load_phrases("en")["formerly_managed"]
HEATER = "switch.hallway_heater"
HEATER_AUTOMATION = "automation.routine_hallway_heater"
HEATER_TIMER = "timer.routine_hallway_heater"

# A hand written automation that switches the desk lamp at a set time, and one that
# closes the garage door on an event (not time based, so never a suggestion).
LAMP_MORNINGS: dict[str, Any] = {
    "id": "desk_lamp_mornings",
    "alias": "Desk lamp mornings",
    "triggers": [{"trigger": "time", "at": "07:00:00"}],
    "actions": [{"action": "light.turn_on", "target": {"entity_id": LAMP}}],
}
GARAGE_ON_EVENT: dict[str, Any] = {
    "id": "garage_door_on_event",
    "alias": "Garage door on event",
    "triggers": [{"trigger": "event", "event_type": "leaving_home"}],
    "actions": [{"action": "cover.close_cover", "target": {"entity_id": GARAGE}}],
}


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def field(result: Mapping[str, Any], key: str) -> tuple[Any, Any]:
    """Return the marker and the selector of one field of a form."""
    for marker, selector in result["data_schema"].schema.items():
        if marker.schema == key:
            return marker, selector
    raise AssertionError(key)


def offered(result: Mapping[str, Any]) -> list[str]:
    _, selector = field(result, CONF_DEVICES)
    return [option["value"] for option in selector.config["options"]]


def option_labels(result: Mapping[str, Any]) -> list[str]:
    _, selector = field(result, CONF_DEVICES)
    return [option["label"] for option in selector.config["options"]]


def prefilled(result: Mapping[str, Any]) -> Any:
    marker, _ = field(result, CONF_DEVICES)
    return marker.default()


async def open_page(hass: HomeAssistant, entry_id: str, page: str) -> dict[str, Any]:
    """Open the options flow and choose one page of its menu."""
    menu = await hass.config_entries.options.async_init(entry_id)
    assert menu["type"] is FlowResultType.MENU
    chosen = await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": page}
    )
    return cast("dict[str, Any]", chosen)


async def submit(hass: HomeAssistant, result: Mapping[str, Any], data: Any) -> dict[str, Any]:
    done = await hass.config_entries.options.async_configure(result["flow_id"], data)
    await hass.async_block_till_done()
    return cast("dict[str, Any]", done)


async def with_timed_automations(hass: HomeAssistant) -> None:
    """The desk lamp is switched at a set time; the garage door only on an event."""
    assert await async_setup_component(hass, "automation", {})
    await save_entry(hass, LAMP_MORNINGS)
    await save_entry(hass, GARAGE_ON_EVENT)


async def rebuild_summary(hass: HomeAssistant, freezer: Any) -> None:
    """Let the summary's debounced index rebuild run."""
    freezer.tick(SUMMARY_DEBOUNCE + 0.1)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def add_heater(hass: HomeAssistant, home: Home) -> str:
    """A second real switch on its own device, so two routines run side by side."""
    await async_add_sandbox_entities(hass, "switch", SandboxSwitch(HEATER, "Hallway heater"))
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=home.source.entry_id,
        identifiers={("sandbox", "heater")},
        name="Hallway heater",
    )
    er.async_get(hass).async_update_entity(HEATER, device_id=device.id)
    return device.id


def labels_of(hass: HomeAssistant, device_id: str) -> set[str]:
    device = dr.async_get(hass).async_get(device_id)
    assert device is not None
    return set(device.labels)


def routine_entries(hass: HomeAssistant) -> list[dict[str, Any]]:
    return [item for item in file_entries(hass) if markers.has_routine_id(item)]


def blueprint_text(hass: HomeAssistant) -> str | None:
    return ha_adapter.installed_blueprint_text(hass)


def assert_kept(hass: HomeAssistant, automation_id: str, alias: str) -> str:
    """Check one kept routine is the plain form Take control makes; return it as text."""
    kept = file_entry(hass, automation_id)
    assert kept is not None
    assert ha_adapter.is_detached(kept)
    assert kept["alias"] == alias
    assert kept["description"] == FORMERLY
    text = json.dumps(kept)
    # The entry's own page entities go with it; the kept automation names the sentinels.
    assert OVERRIDE not in text
    assert PAUSED not in text
    assert "switch.device_routines_unused" in text
    assert "datetime.device_routines_unused" in text
    return text


def raise_persistent_issue(hass: HomeAssistant, automation_id: str) -> None:
    """A Repairs issue that survives restarts, as `schedule_blocks_needed` is (lane 11)."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{repairs.SCHEDULE_BLOCKS_NEEDED}_{automation_id}",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=repairs.SCHEDULE_BLOCKS_NEEDED,
        translation_placeholders={"device": "x", "schedule": "y"},
    )


def issues_of_ours(hass: HomeAssistant) -> list[str]:
    return [issue_id for domain, issue_id in ir.async_get(hass).issues if domain == DOMAIN]


def category_id(hass: HomeAssistant) -> str | None:
    return next(
        (
            item.category_id
            for item in cr.async_get(hass).async_list_categories(scope="automation")
            if item.name == markers.CATEGORY_NAME
        ),
        None,
    )


# --------------------------------------------------------------------------------------
# The config flow and the suggestions screen at setup (PRD D33)
# --------------------------------------------------------------------------------------


async def test_the_user_step_has_no_fields_and_creates_the_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    schema = result["data_schema"]
    assert schema is None or not schema.schema

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == INTEGRATION_TITLE
    assert result["data"] == {}
    assert result["result"].unique_id == DOMAIN
    # Nothing to suggest in an empty home: no second screen.
    assert "next_flow" not in result
    assert not hass.config_entries.options.async_progress()


async def test_a_second_instance_is_refused(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_setup_offers_the_devices_the_summary_flagged_all_unchecked(
    hass: HomeAssistant, home: Home
) -> None:
    await with_timed_automations(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    flow_type, flow_id = result["next_flow"]
    assert flow_type is FlowType.OPTIONS_FLOW
    entry = result["result"]
    manager: RoutineManager = entry.runtime_data.manager
    screen = await hass.config_entries.options.async_configure(flow_id)
    assert screen["type"] is FlowResultType.FORM
    assert screen["step_id"] == "suggestions"
    assert offered(screen) == [home.lamp]
    assert option_labels(screen) == ["Desk lamp (Living room)"]
    assert prefilled(screen) == []
    _, selector = field(screen, CONF_DEVICES)
    assert selector.config["multiple"] is True
    assert selector.config["mode"] == "list"

    done = await submit(hass, screen, {CONF_DEVICES: [home.lamp]})

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert manager.opted_in_devices() == (home.lamp,)
    assert markers.LABEL_ID in labels_of(hass, home.lamp)
    # Opting in is not a settings change: the options stay, the entry is not reloaded.
    assert entry.options == {}
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.manager is manager


async def test_the_suggestions_screen_at_setup_is_skippable(
    hass: HomeAssistant, home: Home
) -> None:
    await with_timed_automations(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    screen = await hass.config_entries.options.async_configure(result["next_flow"][1])

    done = await submit(hass, screen, {})

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].runtime_data.manager.opted_in_devices() == ()
    assert markers.LABEL_ID not in labels_of(hass, home.lamp)


async def test_an_entry_that_did_not_load_gets_no_suggestions_screen(
    hass: HomeAssistant, home: Home
) -> None:
    await with_timed_automations(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    with patch("custom_components.device_routines.async_setup_entry", return_value=False):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].state is ConfigEntryState.SETUP_ERROR
    assert "next_flow" not in result


# --------------------------------------------------------------------------------------
# The options flow: the menu, the devices picker and the suggestions page
# --------------------------------------------------------------------------------------


async def test_the_options_flow_is_a_menu_of_three_pages(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == ["settings", "devices", "suggestions"]
    assert set(STRINGS["options"]["step"]["init"]["menu_options"]) == set(result["menu_options"])


async def test_the_devices_picker_lists_eligible_devices_prefilled_with_the_opted_in_set(
    hass: HomeAssistant, home: Home, manager: RoutineManager, routines: MockConfigEntry
) -> None:
    await manager.async_opt_in(home.fan)

    page = await open_page(hass, routines.entry_id, "devices")

    assert page["type"] is FlowResultType.FORM
    assert page["step_id"] == "devices"
    # The contact sensor has nothing a routine can drive; the hub is the integration's.
    assert offered(page) == [home.lamp, home.garage, home.fan]
    assert option_labels(page) == [
        "Desk lamp (Living room)",
        "Garage door",
        "Living room fan (Living room)",
    ]
    assert prefilled(page) == [home.fan]

    done = await submit(hass, page, {CONF_DEVICES: [home.lamp]})

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert manager.opted_in_devices() == (home.lamp,)
    assert markers.LABEL_ID in labels_of(hass, home.lamp)
    assert markers.LABEL_ID not in labels_of(hass, home.fan)
    assert home.fan in manager.store.data.opted_out_at
    assert routines.options == {}
    assert routines.runtime_data.manager is manager


async def test_the_devices_picker_reports_a_device_removed_meanwhile(
    hass: HomeAssistant, home: Home, manager: RoutineManager, routines: MockConfigEntry
) -> None:
    page = await open_page(hass, routines.entry_id, "devices")
    dr.async_get(hass).async_remove_device(home.lamp)
    await hass.async_block_till_done()

    again = await submit(hass, page, {CONF_DEVICES: [home.lamp]})

    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {CONF_DEVICES: "unknown_device"}
    assert again["description_placeholders"] == {"device": home.lamp}
    assert home.lamp not in offered(again)
    assert manager.opted_in_devices() == ()


async def test_the_suggestions_page_is_repeatable_in_the_options(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    freezer: Any,
) -> None:
    await with_timed_automations(hass)
    await rebuild_summary(hass, freezer)

    page = await open_page(hass, routines.entry_id, "suggestions")

    assert page["step_id"] == "suggestions"
    assert offered(page) == [home.lamp]
    assert prefilled(page) == []
    done = await submit(hass, page, {CONF_DEVICES: [home.lamp]})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert manager.opted_in_devices() == (home.lamp,)

    # Nothing left to suggest: the page says so.
    page = await open_page(hass, routines.entry_id, "suggestions")
    assert page["type"] is FlowResultType.ABORT
    assert page["reason"] == "no_suggestions"


async def test_the_suggestions_page_reports_a_device_removed_meanwhile(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    routines: MockConfigEntry,
    freezer: Any,
) -> None:
    await with_timed_automations(hass)
    await rebuild_summary(hass, freezer)
    page = await open_page(hass, routines.entry_id, "suggestions")
    dr.async_get(hass).async_remove_device(home.lamp)
    await hass.async_block_till_done()

    again = await submit(hass, page, {CONF_DEVICES: [home.lamp]})

    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {CONF_DEVICES: "unknown_device"}
    assert offered(again) == []
    assert manager.opted_in_devices() == ()


async def test_the_device_pages_need_a_loaded_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()

    for page in ("devices", "suggestions"):
        result = await open_page(hass, init_integration.entry_id, page)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "not_loaded"


# --------------------------------------------------------------------------------------
# The settings page (PRD 10.4)
# --------------------------------------------------------------------------------------


async def test_the_settings_page_offers_every_setting_with_its_default(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    page = await open_page(hass, init_integration.entry_id, "settings")

    assert page["type"] is FlowResultType.FORM
    assert page["step_id"] == "settings"
    defaults = GlobalSettings().to_options()
    assert [marker.schema for marker in page["data_schema"].schema] == list(defaults)
    for key, default in defaults.items():
        marker, selector = field(page, key)
        if key in ENUMS:
            assert isinstance(selector, SelectSelector)
            assert selector.config["options"] == [member.value for member in ENUMS[key]]
            assert selector.config["translation_key"] == key
        elif key in BOOLEANS:
            assert isinstance(selector, BooleanSelector)
        elif key in RANGES:
            assert isinstance(selector, NumberSelector)
            assert (selector.config["min"], selector.config["max"]) == RANGES[key]
            assert selector.config["step"] == 1
            assert selector.config["unit_of_measurement"] == NUMBER_UNITS[key]
        else:
            assert isinstance(selector, EntitySelector)
            assert selector.config["domain"] == ["ai_task"]
            assert marker.description == {"suggested_value": None}
            continue
        assert marker.default() == default


async def test_the_settings_page_stores_valid_choices_and_reloads(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    choices = {
        "schedule_scope": "none",
        "time_format": "24h",
        "default_catch_up": False,
        "default_respect_manual": False,
        "default_late_start_window_min": 45,
        "cleanup_after_days": 0,
        "assign_area": False,
        "on_removal": "delete",
        "ai_calls_per_hour": 5,
        "offer_conversions": False,
        "raise_conflict_repairs": False,
    }
    page = await open_page(hass, init_integration.entry_id, "settings")

    done = await submit(hass, page, {**choices, "ai_task_entity": "ai_task.local_model"})

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {**choices, "ai_task_entity": "ai_task.local_model"}
    # The number selector hands back floats; whole numbers are stored as integers.
    assert type(init_integration.options["default_late_start_window_min"]) is int
    settings = init_integration.runtime_data.settings
    assert settings.on_removal is OnRemoval.DELETE
    assert settings.time_format is TimeFormat.H24

    # Clearing the AI entity stores none.
    page = await open_page(hass, init_integration.entry_id, "settings")
    marker, _ = field(page, "ai_task_entity")
    assert marker.description == {"suggested_value": "ai_task.local_model"}
    await submit(hass, page, choices)
    assert init_integration.options["ai_task_entity"] is None


async def test_settings_validation_errors_are_translated(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    page = await open_page(hass, init_integration.entry_id, "settings")
    flow = cast("DeviceRoutinesOptionsFlow", hass.config_entries.options._progress[page["flow_id"]])

    result = await flow.async_step_settings(
        {
            "schedule_scope": "everywhere",
            "default_catch_up": "yes",
            "cleanup_after_days": 400,
            "ai_calls_per_hour": 2.5,
            "ai_task_entity": "light.desk_lamp",
        }
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        "schedule_scope": "invalid_choice",
        "default_catch_up": "invalid_boolean",
        "cleanup_after_days": "out_of_range",
        "ai_calls_per_hour": "out_of_range",
        "ai_task_entity": "invalid_ai_task_entity",
    }
    for error in result["errors"].values():
        assert error in STRINGS["options"]["error"]
    # The form shows what was entered, so it can be corrected.
    marker, _ = field(result, "cleanup_after_days")
    assert marker.default() == 400
    assert init_integration.options == {}


def test_every_flow_string_is_translated() -> None:
    options = STRINGS["options"]
    settings_page = options["step"]["settings"]
    for key in GlobalSettings().to_options():
        assert key in settings_page["data"], key
        # Build A lane 14 writes the AI entity's description: what is sent and where.
        if key != "ai_task_entity":
            assert key in settings_page["data_description"], key
    for key, choices in ENUMS.items():
        assert set(STRINGS["selector"][key]["options"]) == {member.value for member in choices}
    for key, unit in NUMBER_UNITS.items():
        assert unit in STRINGS["selector"][key]["unit_of_measurement"], key
    for page in ("devices", "suggestions"):
        assert CONF_DEVICES in options["step"][page]["data"]
    assert set(options["error"]) == {
        "invalid_choice",
        "invalid_boolean",
        "out_of_range",
        "invalid_ai_task_entity",
        "unknown_setting",
        "unknown_device",
        "not_eligible",
    }
    assert set(options["abort"]) == {"not_loaded", "no_suggestions"}


# --------------------------------------------------------------------------------------
# Removing the integration (PRD 8.2, acceptance S8)
# --------------------------------------------------------------------------------------


async def test_removing_with_keep_leaves_standalone_automations_that_still_run(
    hass: HomeAssistant,
    home: Home,
    routines: MockConfigEntry,
    clock: Clock,
    freezer: Any,
    hass_storage: dict[str, Any],
) -> None:
    """S8: every routine becomes a standalone automation that still runs."""
    clock.set(clock.at(0, "06:00"))
    manager: RoutineManager = routines.runtime_data.manager
    heater = await add_heater(hass, home)
    fan_id = await give_routine(
        hass, manager, home.fan, freezer, on_time="17:00", turn_off_after_min=30
    )
    heater_id = await give_routine(
        hass, manager, heater, freezer, on_time="07:00", off_time="08:00"
    )
    await save_entry(hass, LAMP_MORNINGS)
    repairs.async_sync_issue(hass, repairs.WRITE_CONFLICT, True, {"device": "x"}, subject=fan_id)
    raise_persistent_issue(hass, heater_id)
    ir.async_create_issue(
        hass,
        "other",
        "other_issue",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="other_issue",
    )
    user_id = routines.data[CONF_SYSTEM_USER_ID]
    registry = er.async_get(hass)
    before = registry.async_get(AUTOMATION)
    assert before is not None
    assert STORAGE_KEY in hass_storage

    await hass.config_entries.async_remove(routines.entry_id)
    await hass.async_block_till_done()

    # Each routine is the plain automation Take control makes, same id, same entity.
    assert TIMER in assert_kept(hass, fan_id, ALIAS)
    assert_kept(hass, heater_id, "Routine: Hallway heater")
    assert file_entry(hass, LAMP_MORNINGS["id"]) == LAMP_MORNINGS
    after = registry.async_get(AUTOMATION)
    assert after is not None
    assert (after.unique_id, after.labels, after.categories) == (
        before.unique_id,
        before.labels,
        before.categories,
    )
    assert state_of(hass, AUTOMATION) == "on"
    assert state_of(hass, HEATER_AUTOMATION) == "on"
    # The timer the kept automation uses stays; so do the label and the category.
    assert state_of(hass, TIMER) == "idle"
    assert lr.async_get(hass).async_get_label(markers.LABEL_ID) is not None
    assert category_id(hass) is not None
    # What only the integration used is gone.
    assert await hass.async_add_executor_job(blueprint_text, hass) is None
    assert await hass.auth.async_get_user(user_id) is None
    # Every issue of the integration goes, the persistent one included; others stay.
    assert issues_of_ours(hass) == []
    assert ir.async_get(hass).async_get_issue("other", "other_issue") is not None
    assert STORAGE_KEY not in hass_storage
    assert hass.config_entries.async_get_entry(routines.entry_id) is None
    assert registry.async_get(OVERRIDE) is None

    # And they still run.
    await clock.to(clock.at(0, "07:00:01"))
    assert state_of(hass, HEATER) == "on"
    await clock.to(clock.at(0, "08:00:01"))
    assert state_of(hass, HEATER) == "off"
    await clock.to(clock.at(0, "17:00:01"))
    assert home.switch.state_now == "on"
    assert state_of(hass, TIMER) == "active"
    await clock.to(clock.at(0, "17:30:01"))
    assert home.switch.state_now == "off"


@pytest.mark.parametrize("options", [{"on_removal": "delete"}])
async def test_removing_with_delete_removes_every_routine_and_its_helpers(
    hass: HomeAssistant,
    home: Home,
    routines: MockConfigEntry,
    freezer: Any,
    hass_storage: dict[str, Any],
) -> None:
    manager: RoutineManager = routines.runtime_data.manager
    heater = await add_heater(hass, home)
    fan_id = await give_routine(
        hass, manager, home.fan, freezer, on_time="17:00", turn_off_after_min=30
    )
    heater_id = await give_routine(
        hass, manager, heater, freezer, on_time="07:00", turn_off_after_min=20
    )
    # A timer without the Routines label is not the integration's to delete.
    ha_adapter.async_update_registry_entity(hass, HEATER_TIMER, labels=set())
    # An edit left the fan's inputs unreadable: its helpers come from the Store.
    broken = file_entry(hass, fan_id)
    assert broken is not None
    broken["use_blueprint"]["input"]["unknown_input"] = 1
    await save_entry(hass, broken)
    assert issue_of(hass, repairs.INVALID_INPUTS, fan_id) is not None
    raise_persistent_issue(hass, heater_id)
    # Both devices opted out: nothing carries the label once the routines are gone.
    await manager.async_opt_out(home.fan)
    await manager.async_opt_out(heater)
    await hass.async_block_till_done()
    user_id = routines.data[CONF_SYSTEM_USER_ID]

    await hass.config_entries.async_remove(routines.entry_id)
    await hass.async_block_till_done()

    assert routine_entries(hass) == []
    registry = er.async_get(hass)
    for entity_id in (AUTOMATION, HEATER_AUTOMATION, TIMER):
        assert registry.async_get(entity_id) is None, entity_id
        assert state_of(hass, entity_id) is None, entity_id
    assert state_of(hass, HEATER_TIMER) == "idle"
    assert await hass.async_add_executor_job(blueprint_text, hass) is None
    assert await hass.auth.async_get_user(user_id) is None
    assert lr.async_get(hass).async_get_label(markers.LABEL_ID) is None
    assert category_id(hass) is None
    assert issues_of_ours(hass) == []
    assert STORAGE_KEY not in hass_storage


@pytest.mark.parametrize("options", [{"on_removal": "delete"}])
async def test_removing_with_delete_takes_a_kept_weekly_schedule_along(
    hass: HomeAssistant, home: Home, routines: MockConfigEntry, freezer: Any
) -> None:
    """Plan A4.0 item 15: the routine's own schedule, kept after Days changed back."""
    manager: RoutineManager = routines.runtime_data.manager
    await give_routine(hass, manager, home.fan, freezer, days="weekly_schedule")
    await manager.async_update(home.fan, {"days": "every_day", "on_time": "17:00"})
    await flush(hass, freezer)
    assert state_of(hass, SCHEDULE) is not None

    await hass.config_entries.async_remove(routines.entry_id)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(SCHEDULE) is None
    assert state_of(hass, SCHEDULE) is None


async def test_removing_an_entry_that_never_had_a_routine_leaves_nothing_behind(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    assert lr.async_get(hass).async_get_label(markers.LABEL_ID) is not None
    assert await hass.async_add_executor_job(blueprint_text, hass) is not None

    await hass.config_entries.async_remove(init_integration.entry_id)
    await hass.async_block_till_done()

    assert lr.async_get(hass).async_get_label(markers.LABEL_ID) is None
    assert category_id(hass) is None
    assert await hass.async_add_executor_job(blueprint_text, hass) is None
    assert STORAGE_KEY not in hass_storage
    users = await hass.auth.async_get_users()
    assert not [user for user in users if user.name == INTEGRATION_TITLE]


async def test_a_failing_removal_step_is_logged_and_the_others_still_run(
    hass: HomeAssistant,
    routines: MockConfigEntry,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    person = await hass.auth.async_create_user("Pat")
    hass.config_entries.async_update_entry(routines, data={CONF_SYSTEM_USER_ID: person.id})
    hass_storage[STORAGE_KEY] = {"version": 9, "minor_version": 1, "key": STORAGE_KEY, "data": {}}
    automations_path(hass).write_text("not_a: list\n", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        await hass.config_entries.async_remove(routines.entry_id)
        await hass.async_block_till_done()

    assert "Could not read the Device Routines storage file" in caplog.text
    assert "Could not read the automations file" in caplog.text
    assert "The stored system user was left alone" in caplog.text
    assert await hass.auth.async_get_user(person.id) is not None
    assert automations_path(hass).read_text(encoding="utf-8") == "not_a: list\n"
    assert await hass.async_add_executor_job(blueprint_text, hass) is not None
    assert hass.config_entries.async_get_entry(routines.entry_id) is None


@pytest.mark.parametrize("options", [{"on_removal": "keep"}, {"on_removal": "delete"}])
async def test_a_routine_taken_over_after_the_scan_is_left_alone(
    hass: HomeAssistant,
    home: Home,
    routines: MockConfigEntry,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager: RoutineManager = routines.runtime_data.manager
    fan_id = await give_routine(
        hass, manager, home.fan, freezer, on_time="17:00", turn_off_after_min=30
    )
    scanned = file_entries(hass)
    # A person takes control in the editor between the removal's scan and its write.
    taken = {key: value for key, value in scanned[0].items() if key != "use_blueprint"}
    automations_path(hass).write_text(dump([taken]), encoding="utf-8")

    async def the_scan(hass: HomeAssistant) -> list[dict[str, Any]]:
        return scanned

    monkeypatch.setattr(ha_adapter, "async_read_automations", the_scan)
    with caplog.at_level(logging.WARNING):
        await hass.config_entries.async_remove(routines.entry_id)
        await hass.async_block_till_done()

    assert fan_id in caplog.text
    assert file_entry(hass, fan_id) == taken
    assert state_of(hass, TIMER) == "idle"


@pytest.mark.parametrize("options", [{"on_removal": "delete"}])
async def test_a_helper_that_cannot_be_deleted_is_logged(
    hass: HomeAssistant,
    home: Home,
    routines: MockConfigEntry,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager: RoutineManager = routines.runtime_data.manager
    fan_id = await give_routine(
        hass, manager, home.fan, freezer, on_time="17:00", turn_off_after_min=30
    )

    async def refuse(hass: HomeAssistant, user_id: str, entity_id: str) -> None:
        raise ha_adapter.HelperError("not_found", entity_id)

    monkeypatch.setattr(ha_adapter, "async_delete_helper", refuse)
    with caplog.at_level(logging.WARNING):
        await hass.config_entries.async_remove(routines.entry_id)
        await hass.async_block_till_done()

    assert f"Could not delete {TIMER}" in caplog.text
    assert file_entry(hass, fan_id) is None
    assert state_of(hass, TIMER) == "idle"
