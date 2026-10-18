"""Build A lane 11: the Repairs catalog, its fix flows and the hub Problem sensor.

TECH_SPEC 4.8 row by row, through the real manager and the real files: each issue is
raised in its situation and cleared when the situation ends; each fixable issue's fix
flow runs through the core's Repairs flow manager and does exactly its one step; the
`conflict` issue follows FR-S6 behind `raise_conflict_repairs`; the Problem sensor on
the hub lists what is open. Every id and name is synthetic.
"""

from __future__ import annotations

from datetime import time, timedelta
import json
from pathlib import Path
from typing import Any

from homeassistant.components.repairs import RepairsFlowManager, repairs_flow_manager
from homeassistant.const import __version__ as HA_VERSION  # noqa: N812
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.device_routines import ha_adapter, maintenance, markers, repairs
from custom_components.device_routines.const import DOMAIN
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import Status
from custom_components.device_routines.summary import DEBOUNCE_SECONDS as SUMMARY_DEBOUNCE
from tests.integration.conftest import (
    ALIAS,
    AUTOMATION,
    FAN,
    LAMP,
    SCHEDULE,
    Home,
    automations_path,
    file_entries,
    file_entry,
    flush,
    give_routine,
    inputs_of,
    issue_of,
    reload_all,
    save_entry,
    state_of,
    write_entries,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

STRINGS = Path(repairs.__file__).parent / "strings.json"


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


@pytest.fixture
async def fixer(hass: HomeAssistant) -> RepairsFlowManager:
    """The core's Repairs flow manager, which the Repairs dashboard drives."""
    assert await async_setup_component(hass, "repairs", {})
    flows = repairs_flow_manager(hass)
    assert flows is not None
    return flows


async def fix(fixer: RepairsFlowManager, registry_id: str) -> FlowResult[Any, str]:
    """Open the fix flow of an issue, check its one confirm form, and submit it."""
    result = await fixer.async_init(DOMAIN, context={"issue_id": registry_id})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    issue = ir.async_get(fixer.hass).async_get_issue(DOMAIN, registry_id)
    assert issue is not None
    assert result["description_placeholders"] == issue.translation_placeholders
    return await fixer.async_configure(result["flow_id"], {})


def installed_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.config_dir) / "blueprints" / "automation" / markers.BLUEPRINT_PATH


async def rebuild(hass: HomeAssistant, freezer: Any) -> None:
    """Let the summary's debounced index rebuild run."""
    freezer.tick(timedelta(seconds=SUMMARY_DEBOUNCE + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def hand_automation(key: str, at: str, service: str, entity_id: str) -> dict[str, Any]:
    """A hand written automation: one time trigger, one action on one entity."""
    return {
        "id": f"hand_{key}",
        "alias": f"Hand {key.replace('_', ' ')}",
        "triggers": [{"trigger": "time", "at": at}],
        "actions": [{"action": service, "target": {"entity_id": entity_id}}],
    }


def problem_entity(hass: HomeAssistant) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{DOMAIN}_hub_hub_problem"
    )
    assert entity_id is not None
    return entity_id


def conflict_issues(hass: HomeAssistant) -> list[str]:
    return [issue for issue in repairs.open_issue_ids(hass) if issue.startswith("conflict")]


# --------------------------------------------------------------------------------------
# The strings: a fix flow for every fixable issue, a description for the others
# --------------------------------------------------------------------------------------


def test_every_fixable_issue_has_a_one_step_fix_flow_and_the_others_a_description() -> None:
    issues = json.loads(STRINGS.read_text(encoding="utf-8"))["issues"]

    for issue_id in repairs.CATALOG:
        strings = issues[issue_id]
        assert strings["title"]
        if issue_id in repairs.FIXABLE:
            # hassfest takes a description or a fix flow per issue, never both.
            assert "description" not in strings, issue_id
            flow = strings["fix_flow"]
            assert set(flow["step"]) == {"confirm"}, issue_id
            assert flow["step"]["confirm"]["title"]
            assert flow["step"]["confirm"]["description"]
            assert set(flow["abort"]) >= {repairs.ABORT_NOT_LOADED, repairs.ABORT_NOT_FIXED}
        else:
            assert "fix_flow" not in strings, issue_id
            assert strings["description"]
    assert "no_valid_settings" in issues["invalid_inputs"]["fix_flow"]["abort"]
    for issue_id in repairs.FIXABLE - {repairs.BLUEPRINT_MODIFIED}:
        assert "unknown_routine" in issues[issue_id]["fix_flow"]["abort"], issue_id
    assert {
        "blueprint_modified",
        "invalid_inputs",
        "detached_routine",
        "write_conflict",
        "automation_load_failed",
    } == repairs.FIXABLE


async def test_a_fix_flow_is_refused_for_an_issue_without_one(hass: HomeAssistant) -> None:
    for issue_id in ("schedule_blocks_needed", "conflict", "adapter_incompatible", "made_up"):
        with pytest.raises(ValueError, match="has no fix flow"):
            await repairs.async_create_fix_flow(hass, issue_id, None)
    with pytest.raises(ValueError, match="has no fix flow"):
        await repairs.async_create_fix_flow(
            hass, "conflict_x", {"issue_id": "conflict", "subject": "x"}
        )


# --------------------------------------------------------------------------------------
# adapter_incompatible: not fixable, names the capability and the core version
# --------------------------------------------------------------------------------------


async def test_adapter_incompatible_is_raised_while_a_capability_fails_and_cleared_after(
    hass: HomeAssistant, home: Home, manager: RoutineManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = ha_adapter.check
    monkeypatch.setattr(
        ha_adapter,
        "check",
        lambda _hass: ha_adapter.AdapterReport(failed=(ha_adapter.CAPABILITY_WRITE,)),
    )
    await manager.async_reconcile()

    issue = issue_of(hass, "adapter_incompatible")
    assert issue is not None
    assert not issue.is_fixable
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.learn_more_url == repairs.TROUBLESHOOTING_URL
    assert issue.translation_placeholders == {
        "capabilities": ha_adapter.CAPABILITY_WRITE,
        "ha_version": HA_VERSION,
    }

    monkeypatch.setattr(ha_adapter, "check", real)
    await manager.async_reconcile()
    assert issue_of(hass, "adapter_incompatible") is None


# --------------------------------------------------------------------------------------
# blueprint_modified: one step, reinstall the shipped file and reload
# --------------------------------------------------------------------------------------


async def test_blueprint_modified_is_raised_for_a_hand_edit_and_cleared_when_it_is_undone(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    shipped = installed_path(hass).read_text(encoding="utf-8")
    installed_path(hass).write_text(shipped + "# edited by hand\n", encoding="utf-8")

    await manager.async_reconcile()
    issue = issue_of(hass, "blueprint_modified")
    assert issue is not None
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.data is None

    installed_path(hass).write_text(shipped, encoding="utf-8")
    await manager.async_reconcile()
    assert issue_of(hass, "blueprint_modified") is None


async def test_the_blueprint_fix_reinstalls_the_shipped_file_and_reloads(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    fixer: RepairsFlowManager,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    edited = installed_path(hass).read_text(encoding="utf-8") + "# edited by hand\n"
    installed_path(hass).write_text(edited, encoding="utf-8")
    await manager.async_reconcile()
    assert issue_of(hass, "blueprint_modified") is not None
    automations_before = automations_path(hass).read_bytes()
    reloads = async_capture_events(hass, ha_adapter.EVENT_AUTOMATION_RELOADED)

    result = await fix(fixer, "blueprint_modified")
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert installed_path(hass).read_text(encoding="utf-8") == maintenance.shipped_blueprint_text()
    assert reloads  # the automations that use it were reloaded
    assert issue_of(hass, "blueprint_modified") is None
    assert manager.health_inputs().blueprint_status == "shipped"
    assert state_of(hass, AUTOMATION) == "on"
    # Exactly that step: the routines were not rewritten.
    assert automations_path(hass).read_bytes() == automations_before
    assert inputs_of(hass, automation_id)["on_time"] == "17:00:00"


async def test_a_blueprint_fix_that_cannot_install_aborts_and_keeps_the_issue(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    fixer: RepairsFlowManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edited = installed_path(hass).read_text(encoding="utf-8") + "# edited by hand\n"
    installed_path(hass).write_text(edited, encoding="utf-8")
    await manager.async_reconcile()

    async def broken(*_args: Any) -> bool:
        raise ha_adapter.AdapterError("synthetic failure")

    monkeypatch.setattr(ha_adapter, "async_install_blueprint", broken)
    result = await fix(fixer, "blueprint_modified")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_fixed"
    assert issue_of(hass, "blueprint_modified") is not None
    assert installed_path(hass).read_text(encoding="utf-8") == edited


async def test_a_blueprint_fix_on_a_file_already_shipped_finishes(
    hass: HomeAssistant, home: Home, manager: RoutineManager, fixer: RepairsFlowManager
) -> None:
    # The issue is stale: someone undid the edit before the next reconcile.
    repairs.async_sync_issue(hass, repairs.BLUEPRINT_MODIFIED, True)

    result = await fix(fixer, "blueprint_modified")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert issue_of(hass, "blueprint_modified") is None
    assert installed_path(hass).read_text(encoding="utf-8") == maintenance.shipped_blueprint_text()


# --------------------------------------------------------------------------------------
# invalid_inputs: one step, restore last_valid_inputs
# --------------------------------------------------------------------------------------


async def test_invalid_inputs_is_raised_by_an_invalid_edit_and_cleared_by_a_valid_one(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["on_action"] = "lock.unlock"
    await save_entry(hass, entry)

    issue = issue_of(hass, "invalid_inputs", automation_id)
    assert issue is not None
    assert issue.is_fixable
    assert issue.data == {"issue_id": "invalid_inputs", "subject": automation_id}
    assert state_of(hass, AUTOMATION) == "off"

    entry["use_blueprint"]["input"]["on_action"] = "switch.turn_on"
    await save_entry(hass, entry)
    assert issue_of(hass, "invalid_inputs", automation_id) is None
    assert state_of(hass, AUTOMATION) == "on"


async def test_the_invalid_inputs_fix_restores_the_last_valid_inputs(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    fixer: RepairsFlowManager,
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23)
    )
    valid = inputs_of(hass, automation_id)
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["surprise"] = True
    await save_entry(hass, entry)
    registry_id = f"invalid_inputs_{automation_id}"
    assert issue_of(hass, "invalid_inputs", automation_id) is not None

    result = await fix(fixer, registry_id)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert inputs_of(hass, automation_id) == valid
    assert manager.store.data.owned[automation_id].last_valid_inputs == valid
    assert state_of(hass, AUTOMATION) == "on"
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert issue_of(hass, "invalid_inputs", automation_id) is None


async def test_an_invalid_inputs_fix_with_nothing_to_restore_aborts_with_the_reason(
    hass: HomeAssistant, home: Home, manager: RoutineManager, fixer: RepairsFlowManager
) -> None:
    automation_id = markers.automation_id(home.lamp)
    invalid = {
        "id": automation_id,
        "alias": "Routine: Desk lamp",
        "use_blueprint": {
            "path": markers.BLUEPRINT_PATH,
            "input": {"device_id": home.lamp, "target_entity": LAMP, "surprise": 1},
        },
    }
    await save_entry(hass, invalid)

    result = await fix(fixer, f"invalid_inputs_{automation_id}")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_valid_settings"
    assert result["description_placeholders"] is not None
    assert result["description_placeholders"]["device"] == "Desk lamp"
    assert issue_of(hass, "invalid_inputs", automation_id) is not None
    assert file_entry(hass, automation_id) == invalid


async def test_a_restore_that_cannot_write_aborts_and_keeps_the_issue(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    fixer: RepairsFlowManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["surprise"] = True
    await save_entry(hass, entry)

    async def broken(*_args: Any) -> Any:
        raise ha_adapter.AdapterError("synthetic failure")

    monkeypatch.setattr(ha_adapter, "async_write_automation", broken)
    result = await fix(fixer, f"invalid_inputs_{automation_id}")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_fixed"
    assert issue_of(hass, "invalid_inputs", automation_id) is not None


# --------------------------------------------------------------------------------------
# detached_routine: one step, create a new routine; the detached one is never touched
# --------------------------------------------------------------------------------------


def taken_over(automation_id: str) -> dict[str, Any]:
    """The routine's automation after Take control: the same id, no blueprint."""
    return {
        "id": automation_id,
        "alias": ALIAS,
        "triggers": [{"trigger": "time", "at": "17:00:00"}],
        "actions": [{"action": "switch.turn_on", "target": {"entity_id": FAN}}],
    }


async def test_detached_routine_is_raised_by_take_control_and_cleared_by_a_restore(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    owned = file_entry(hass, automation_id)
    assert owned is not None

    await save_entry(hass, taken_over(automation_id))
    issue = issue_of(hass, "detached_routine", automation_id)
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_placeholders == {"device": "Living room fan", "automation": AUTOMATION}

    await save_entry(hass, owned)
    assert issue_of(hass, "detached_routine", automation_id) is None


async def test_detaching_clears_the_issues_only_an_owned_routine_can_have(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    for issue_id in (repairs.AUTOMATION_LOAD_FAILED, repairs.SCHEDULE_BLOCKS_NEEDED):
        repairs.async_sync_issue(hass, issue_id, True, {"device": "x"}, subject=automation_id)

    await save_entry(hass, taken_over(automation_id))

    assert repairs.open_issue_ids(hass) == [f"detached_routine_{automation_id}"]


async def test_the_detached_fix_creates_a_new_routine_and_never_touches_the_old_one(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    fixer: RepairsFlowManager,
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23)
    )
    taken = taken_over(automation_id)
    await save_entry(hass, taken)
    assert manager.unavailable_reason(home.fan) == "detached"

    result = await fix(fixer, f"detached_routine_{automation_id}")
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    new_id = markers.automation_id(f"{home.fan}#2")
    view = manager.get(home.fan)
    assert view is not None
    assert view.automation_id == new_id
    assert view.status is Status.ACTIVE
    assert manager.unavailable_reason(home.fan) is None
    assert inputs_of(hass, new_id)["on_time"] == "17:00:00"
    assert inputs_of(hass, new_id)["off_time"] == "23:00:00"
    assert file_entry(hass, automation_id) == taken  # never touched
    assert issue_of(hass, "detached_routine", automation_id) is None
    assert repairs.open_issue_ids(hass) == []


@pytest.mark.parametrize("flag", ["invalid", "load_failed"])
async def test_a_new_routine_drops_the_flags_of_the_detached_one(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any, flag: str
) -> None:
    """Plan A4.0 item 7 (L48): the new routine reads as itself at once, not as the old one.

    The old automation was invalid (a refused action in its form) or did not load (a
    condition the core does not know) when it was taken over; the new routine is written
    from valid settings, so it is active the moment the fix returns, before any sync.
    """
    if flag == "invalid":
        automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
        entry = file_entry(hass, automation_id)
        assert entry is not None
        entry["use_blueprint"]["input"]["on_action"] = "lock.unlock"
        await save_entry(hass, entry)
    else:
        broken = [{"condition": "no_such_condition"}]
        automation_id = await give_routine(
            hass, manager, home.fan, freezer, on_time=time(17), extra_conditions=broken
        )
        await manager.async_reconcile()
        await manager.async_reconcile()
        await manager.async_update(home.fan, {"extra_conditions": []})
        await flush(hass, freezer)
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.INVALID
    await save_entry(hass, taken_over(automation_id))

    await manager.async_create_new_routine(home.fan)

    view = manager.get(home.fan)
    assert view is not None
    assert view.automation_id == markers.automation_id(f"{home.fan}#2")
    assert view.status is Status.ACTIVE
    await hass.async_block_till_done()
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert repairs.open_issue_ids(hass) == []


async def test_a_detached_fix_for_a_routine_the_manager_no_longer_knows_aborts(
    hass: HomeAssistant, home: Home, manager: RoutineManager, fixer: RepairsFlowManager
) -> None:
    subject = markers.automation_id("no-such-device")
    repairs.async_sync_issue(
        hass, repairs.DETACHED_ROUTINE, True, {"device": "x", "automation": "y"}, subject=subject
    )

    result = await fix(fixer, f"detached_routine_{subject}")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown_routine"
    assert result["description_placeholders"] == {
        "device": "x",
        "automation": subject,
    }
    assert issue_of(hass, "detached_routine", subject) is not None


# --------------------------------------------------------------------------------------
# schedule_blocks_needed: not fixable, links to the helper, clears once blocks exist
# --------------------------------------------------------------------------------------


async def test_schedule_blocks_needed_is_raised_for_a_recreated_schedule_and_cleared_by_blocks(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.lamp, freezer, off_time=time(23))
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, days="weekly_schedule", schedule_entity=SCHEDULE
    )
    await manager.async_reconcile()
    await hass.async_block_till_done()

    issue = issue_of(hass, "schedule_blocks_needed", automation_id)
    assert issue is not None
    assert not issue.is_fixable
    assert issue.is_persistent  # only the recreation tells, so it outlives a restart
    assert issue.learn_more_url == repairs.HELPERS_URL
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["schedule"] == SCHEDULE
    with pytest.raises(ValueError, match="has no fix flow"):
        await repairs.async_create_fix_flow(hass, issue.issue_id, issue.data)

    # A state change of the empty schedule changes nothing; entering blocks clears it.
    hass.states.async_set(SCHEDULE, "off", {"next_event": None})
    await hass.async_block_till_done()
    assert issue_of(hass, "schedule_blocks_needed", automation_id) is not None
    user = await ha_adapter.async_ensure_system_user(hass, None)
    every_day = {
        day: [{"from": "07:00:00", "to": "22:00:00"}]
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    }
    await ha_adapter.async_update_helper(hass, user, SCHEDULE, **every_day)
    await hass.async_block_till_done()

    assert issue_of(hass, "schedule_blocks_needed", automation_id) is None


async def test_a_reconcile_clears_schedule_blocks_needed_once_the_schedule_has_blocks(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, days="weekly_schedule", schedule_entity=SCHEDULE
    )
    await manager.async_reconcile()
    await hass.async_block_till_done()
    user = await ha_adapter.async_ensure_system_user(hass, None)
    await ha_adapter.async_update_helper(
        hass, user, SCHEDULE, monday=[{"from": "07:00:00", "to": "22:00:00"}]
    )
    await hass.async_block_till_done()
    assert issue_of(hass, "schedule_blocks_needed", automation_id) is None
    # The issue outlives a restart while the blocks were entered with the integration
    # not loaded: the next reconcile finds the blocks and clears it.
    repairs.async_sync_issue(
        hass, repairs.SCHEDULE_BLOCKS_NEEDED, True, {"device": "x"}, subject=automation_id
    )

    await manager.async_reconcile()

    assert issue_of(hass, "schedule_blocks_needed", automation_id) is None


# --------------------------------------------------------------------------------------
# write_conflict: one step, retry
# --------------------------------------------------------------------------------------


async def conflicting_write(
    hass: HomeAssistant,
    manager: RoutineManager,
    device_id: str,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Change a setting while every write loses the race; return the real write."""
    real = ha_adapter.async_write_automation

    async def conflict(*_args: Any) -> Any:
        raise ha_adapter.WriteConflictError("synthetic conflict")

    monkeypatch.setattr(ha_adapter, "async_write_automation", conflict)
    await manager.async_update(device_id, {"on_time": time(18)})
    await flush(hass, freezer)
    return real


async def test_write_conflict_is_raised_by_a_lost_race_and_cleared_by_the_next_write(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    real = await conflicting_write(hass, manager, home.fan, freezer, monkeypatch)
    issue = issue_of(hass, "write_conflict", automation_id)
    assert issue is not None
    assert issue.is_fixable

    monkeypatch.setattr(ha_adapter, "async_write_automation", real)
    await manager.async_update(home.fan, {"on_time": time(19)})
    await flush(hass, freezer)
    assert issue_of(hass, "write_conflict", automation_id) is None
    assert inputs_of(hass, automation_id)["on_time"] == "19:00:00"


async def test_the_write_conflict_fix_retries_the_write(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    fixer: RepairsFlowManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    real = await conflicting_write(hass, manager, home.fan, freezer, monkeypatch)
    registry_id = f"write_conflict_{automation_id}"

    # Losing the race again keeps the issue for the next try.
    result = await fix(fixer, registry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_fixed"
    assert issue_of(hass, "write_conflict", automation_id) is not None
    assert inputs_of(hass, automation_id)["on_time"] == "17:00:00"

    monkeypatch.setattr(ha_adapter, "async_write_automation", real)
    result = await fix(fixer, registry_id)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert inputs_of(hass, automation_id)["on_time"] == "18:00:00"
    assert issue_of(hass, "write_conflict", automation_id) is None


async def test_a_retry_for_a_routine_that_is_gone_aborts_with_unknown_routine(
    hass: HomeAssistant, home: Home, manager: RoutineManager, fixer: RepairsFlowManager
) -> None:
    subject = markers.automation_id("no-such-device")
    repairs.async_sync_issue(hass, repairs.WRITE_CONFLICT, True, {"device": "x"}, subject=subject)

    result = await fix(fixer, f"write_conflict_{subject}")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown_routine"
    assert issue_of(hass, "write_conflict", subject) is not None


# --------------------------------------------------------------------------------------
# automation_load_failed: one step, regenerate from last_valid_inputs
# --------------------------------------------------------------------------------------


async def test_automation_load_failed_is_raised_after_one_regeneration_and_cleared_on_load(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_time=time(17),
        extra_conditions=[{"condition": "no_such_condition"}],
    )
    await manager.async_reconcile()
    issue = issue_of(hass, "automation_load_failed", automation_id)
    assert issue is not None
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.ERROR

    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["extra_conditions"] = []
    await save_entry(hass, entry)
    await manager.async_reconcile()
    assert state_of(hass, AUTOMATION) == "on"
    assert issue_of(hass, "automation_load_failed", automation_id) is None


async def test_the_load_failed_fix_regenerates_from_the_last_valid_inputs(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    fixer: RepairsFlowManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    valid = inputs_of(hass, automation_id)
    # The blueprint file went missing, so the automation does not load, and the one
    # regeneration of the next reconcile cannot write.
    installed_path(hass).unlink()
    await hass.services.async_call("automation", "reload", {"id": automation_id}, blocking=True)
    await hass.async_block_till_done()
    assert state_of(hass, AUTOMATION) == "unavailable"
    real = ha_adapter.async_write_automation

    async def broken(*_args: Any) -> Any:
        raise ha_adapter.AdapterError("synthetic failure")

    monkeypatch.setattr(ha_adapter, "async_write_automation", broken)
    await manager.async_reconcile()
    assert issue_of(hass, "automation_load_failed", automation_id) is not None
    writes: list[str] = []

    async def spy(*args: Any) -> Any:
        writes.append(args[1])
        return await real(*args)

    monkeypatch.setattr(ha_adapter, "async_write_automation", spy)
    result = await fix(fixer, f"automation_load_failed_{automation_id}")
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert writes == [automation_id]
    assert inputs_of(hass, automation_id) == valid
    assert state_of(hass, AUTOMATION) == "on"
    assert issue_of(hass, "automation_load_failed", automation_id) is None


async def test_a_regeneration_that_still_does_not_load_aborts_and_keeps_the_issue(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    fixer: RepairsFlowManager,
) -> None:
    automation_id = await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_time=time(17),
        extra_conditions=[{"condition": "no_such_condition"}],
    )
    await manager.async_reconcile()

    result = await fix(fixer, f"automation_load_failed_{automation_id}")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_fixed"
    assert result["description_placeholders"] is not None
    assert result["description_placeholders"]["automation"] == AUTOMATION
    assert issue_of(hass, "automation_load_failed", automation_id) is not None


# --------------------------------------------------------------------------------------
# Every fix flow needs the loaded entry, whose manager is the flows' target
# --------------------------------------------------------------------------------------


async def test_the_loaded_manager_is_what_the_fix_flows_call(manager: RoutineManager) -> None:
    target: repairs.FixTarget = manager  # mypy checks the protocol here
    assert target is manager


async def test_a_fix_while_the_entry_is_not_loaded_aborts(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    routines: MockConfigEntry,
    fixer: RepairsFlowManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    real = await conflicting_write(hass, manager, home.fan, freezer, monkeypatch)
    monkeypatch.setattr(ha_adapter, "async_write_automation", real)
    assert await hass.config_entries.async_unload(routines.entry_id)
    await hass.async_block_till_done()

    result = await fix(fixer, f"write_conflict_{automation_id}")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"
    assert issue_of(hass, "write_conflict", automation_id) is not None


# --------------------------------------------------------------------------------------
# Issues of a routine end with the routine
# --------------------------------------------------------------------------------------


async def test_cleaning_a_routine_up_clears_its_issues(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    for issue_id in (repairs.INVALID_INPUTS, repairs.SCHEDULE_BLOCKS_NEEDED):
        repairs.async_sync_issue(hass, issue_id, True, {"device": "x"}, subject=automation_id)
    await manager.async_opt_out(home.fan)

    await maintenance.async_run(hass, manager, maintenance.MaintenanceAction.CLEAN_UP_NOW, False)
    await hass.async_block_till_done()

    assert file_entry(hass, automation_id) is None
    assert repairs.open_issue_ids(hass) == []


# --------------------------------------------------------------------------------------
# conflict (FR-S6): a routine against another automation at the same minute, by setting
# --------------------------------------------------------------------------------------


async def test_conflict_is_raised_for_a_routine_against_an_automation_in_the_same_minute(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await save_entry(hass, hand_automation("fan_off", "17:00:00", "switch.turn_off", FAN))
    await rebuild(hass, freezer)

    issue = issue_of(hass, "conflict", automation_id)
    assert issue is not None
    assert not issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.learn_more_url == repairs.AUTOMATIONS_URL
    assert issue.translation_placeholders == {
        "device": "Living room fan",
        "first": ALIAS,
        "second": "Hand fan off",
        "time": "5:00 PM",
    }
    assert conflict_issues(hass) == [f"conflict_{automation_id}"]

    # A second automation at the same minute joins the same issue, named with the first.
    await save_entry(hass, hand_automation("fan_off_too", "17:00:00", "switch.turn_off", FAN))
    await rebuild(hass, freezer)
    issue = issue_of(hass, "conflict", automation_id)
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["second"] == "Hand fan off, Hand fan off too"

    # Moving both away from the routine's minute ends the collision.
    for key in ("fan_off", "fan_off_too"):
        await save_entry(hass, hand_automation(key, "17:05:00", "switch.turn_off", FAN))
    await rebuild(hass, freezer)
    assert conflict_issues(hass) == []


async def test_conflict_clears_when_the_routine_stops_running(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await save_entry(hass, hand_automation("fan_off", "17:00:00", "switch.turn_off", FAN))
    await rebuild(hass, freezer)
    assert issue_of(hass, "conflict", automation_id) is not None

    await manager.async_disable(home.fan)
    await hass.async_block_till_done()

    assert conflict_issues(hass) == []


async def test_no_conflict_issue_for_two_hand_written_automations_or_a_window(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23))
    # Two hand written automations collide on the lamp, and one turns the fan off inside
    # the routine's on window: both are listed as conflicts, neither is a Repairs issue.
    entries = [
        hand_automation("lamp_on", "08:00:00", "light.turn_on", LAMP),
        hand_automation("lamp_off", "08:00:00", "light.turn_off", LAMP),
        hand_automation("fan_off", "20:00:00", "switch.turn_off", FAN),
    ]
    write_entries(hass, [*file_entries(hass), *entries])
    await reload_all(hass)
    await rebuild(hass, freezer)

    summaries = manager.summary.summaries
    assert [c.reason_key for c in summaries[home.lamp].conflicts] == ["opposite_same_minute"]
    assert [c.reason_key for c in summaries[home.fan].conflicts] == ["off_in_on_window"]
    assert conflict_issues(hass) == []


@pytest.mark.parametrize("options", [{"raise_conflict_repairs": False}])
async def test_no_conflict_issue_while_raise_conflict_repairs_is_off(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await save_entry(hass, hand_automation("fan_off", "17:00:00", "switch.turn_off", FAN))
    await rebuild(hass, freezer)

    assert [c.reason_key for c in manager.summary.summaries[home.fan].conflicts] == [
        "opposite_same_minute"
    ]
    assert conflict_issues(hass) == []


async def test_turning_raise_conflict_repairs_off_clears_the_open_conflict_issues(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    routines: MockConfigEntry,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await save_entry(hass, hand_automation("fan_off", "17:00:00", "switch.turn_off", FAN))
    await rebuild(hass, freezer)
    assert issue_of(hass, "conflict", automation_id) is not None

    hass.config_entries.async_update_entry(routines, options={"raise_conflict_repairs": False})
    assert await hass.config_entries.async_reload(routines.entry_id)
    await hass.async_block_till_done()

    assert conflict_issues(hass) == []


# --------------------------------------------------------------------------------------
# The set sync behind the conflict issue
# --------------------------------------------------------------------------------------


async def test_syncing_an_issue_set_raises_the_wanted_and_clears_every_other(
    hass: HomeAssistant,
) -> None:
    repairs.async_sync_issue(hass, repairs.CONFLICT, True, {"device": "a"}, subject="stale")
    repairs.async_sync_issue(hass, repairs.INVALID_INPUTS, True, {"device": "a"}, subject="kept")

    repairs.async_sync_issues(hass, repairs.CONFLICT, {"one": {"device": "b"}})

    assert repairs.open_issue_ids(hass) == ["conflict_one", "invalid_inputs_kept"]
    repairs.async_sync_issues(hass, repairs.CONFLICT, {})
    assert repairs.open_issue_ids(hass) == ["invalid_inputs_kept"]


# --------------------------------------------------------------------------------------
# The hub Problem sensor
# --------------------------------------------------------------------------------------


async def test_the_problem_sensor_is_on_while_any_issue_is_open_and_lists_the_ids(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    entity_id = problem_entity(hass)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["issues"] == []

    fan_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    lamp_id = await give_routine(hass, manager, home.lamp, freezer, off_time=time(23))
    for automation_id in (fan_id, lamp_id):
        entry = file_entry(hass, automation_id)
        assert entry is not None
        entry["use_blueprint"]["input"]["surprise"] = True
        await save_entry(hass, entry)
    edited = installed_path(hass).read_text(encoding="utf-8") + "# edited by hand\n"
    installed_path(hass).write_text(edited, encoding="utf-8")
    await manager.async_reconcile()
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"
    assert state.attributes["issues"] == sorted(
        ["blueprint_modified", f"invalid_inputs_{fan_id}", f"invalid_inputs_{lamp_id}"]
    )

    # An ignored issue is not open; the others still are.
    ir.async_ignore_issue(hass, DOMAIN, "blueprint_modified", True)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["issues"] == sorted(
        [f"invalid_inputs_{fan_id}", f"invalid_inputs_{lamp_id}"]
    )

    for automation_id in (fan_id, lamp_id):
        await manager.async_restore_last_valid(automation_id)
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"
    assert state.attributes["issues"] == []
