"""Build A lane 5: sync back, take control and deletion (PRD 7.3 and 8.2, TECH_SPEC 4.1).

Each test edits `automations.yaml` the way the automation editor or a person does (replace
the entry, reload its id; or restore the whole file and reload everything) and checks
what the manager made of it. A delete in the automation editor goes through the core's
own config view, which reloads nothing (live validation A, F1). Every id and name is
synthetic.
"""

from __future__ import annotations

from datetime import time, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.device_routines import ha_adapter, markers
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import Status
from tests.integration.conftest import (
    AUTOMATION,
    LAMP,
    TIMER,
    Home,
    automations_path,
    file_entries,
    file_entry,
    give_routine,
    inputs_of,
    issue_of,
    reload_all,
    save_entry,
    state_of,
    write_entries,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


async def test_a_form_edit_with_a_hash_the_manager_did_not_write_updates_the_entities(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23)
    )
    entry = file_entry(hass, automation_id)
    assert entry is not None

    # The form changes a primary input only: the derived ones are stale afterwards.
    entry["use_blueprint"]["input"]["off_time"] = "09:00:00"
    await save_entry(hass, entry)

    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.off_time == time(9)
    assert view.status is Status.ACTIVE
    inputs = inputs_of(hass, automation_id)
    assert inputs["crosses_midnight"] is True  # the manager wrote the derived inputs back
    record = manager.store.data.owned[automation_id]
    assert record.last_valid_inputs == inputs
    assert record.last_hash == markers.config_hash(file_entry(hass, automation_id) or {})
    assert issue_of(hass, "invalid_inputs", automation_id) is None


async def test_an_edit_into_an_invalid_shape_turns_the_routine_off_and_raises_invalid_inputs(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["surprise"] = True
    await save_entry(hass, entry)
    edited = automations_path(hass).read_bytes()

    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.INVALID
    assert view.sentence == "Routine off"
    assert state_of(hass, AUTOMATION) == "off"
    assert automations_path(hass).read_bytes() == edited  # nothing overwritten
    issue = issue_of(hass, "invalid_inputs", automation_id)
    assert issue is not None
    assert issue.translation_placeholders == {
        "device": "Living room fan",
        "automation": AUTOMATION,
        "reason": "invalid_inputs",
    }
    # Another reload re-reads the same invalid entry: still off, still one issue.
    await reload_all(hass)
    assert automations_path(hass).read_bytes() == edited

    # The fix flow restores the last valid settings and turns the routine back on.
    await manager.async_restore_last_valid(automation_id)
    await hass.async_block_till_done()
    assert "surprise" not in inputs_of(hass, automation_id)
    assert issue_of(hass, "invalid_inputs", automation_id) is None
    assert state_of(hass, AUTOMATION) == "on"
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE


async def test_a_refused_action_does_the_same_and_correcting_the_form_brings_it_back(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["on_action"] = "lock.unlock"
    await save_entry(hass, entry)
    edited = automations_path(hass).read_bytes()

    issue = issue_of(hass, "invalid_inputs", automation_id)
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["reason"] == "refused_action"
    assert state_of(hass, AUTOMATION) == "off"
    assert automations_path(hass).read_bytes() == edited

    entry["use_blueprint"]["input"]["on_action"] = "switch.turn_on"
    entry["use_blueprint"]["input"]["on_time"] = "18:00:00"
    await save_entry(hass, entry)

    assert issue_of(hass, "invalid_inputs", automation_id) is None
    assert state_of(hass, AUTOMATION) == "on"
    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.on_time == time(18)


async def test_an_edit_the_compiler_rejects_or_for_an_unsupported_target_is_invalid(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23)
    )
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["off_time"] = "17:00:00"
    await save_entry(hass, entry)
    issue = issue_of(hass, "invalid_inputs", automation_id)
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["reason"] == "same_on_and_off_time"

    entry["use_blueprint"]["input"]["off_time"] = "23:00:00"
    entry["use_blueprint"]["input"]["target_entity"] = "sensor.thermometer"
    await save_entry(hass, entry)
    issue = issue_of(hass, "invalid_inputs", automation_id)
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["reason"] == "invalid_inputs"


async def test_take_control_makes_the_routine_detached_and_raises_detached_routine(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(23)
    )
    taken = {
        "id": automation_id,
        "alias": "Routine: Living room fan",
        "triggers": [{"trigger": "time", "at": "17:00:00"}],
        "actions": [
            {"action": "switch.turn_on", "target": {"entity_id": "switch.living_room_fan"}}
        ],
    }

    await save_entry(hass, taken)
    detached = automations_path(hass).read_bytes()

    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.DETACHED
    assert manager.unavailable_reason(home.fan) == "detached"
    assert automation_id not in manager.store.data.owned
    issue = issue_of(hass, "detached_routine", automation_id)
    assert issue is not None
    assert issue.translation_placeholders == {"device": "Living room fan", "automation": AUTOMATION}
    summary = manager.routine_summary(home.fan)
    assert summary is not None
    assert summary.status is Status.DETACHED
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_update(home.fan, {"on_time": time(18)})
    assert raised.value.translation_key == "detached"
    assert manager.resolve_targets({"device_id": home.fan}).ignored[0].reason == "detached"
    await reload_all(hass)
    assert automations_path(hass).read_bytes() == detached  # never touched again

    # The fix flow creates a new routine and leaves the detached automation alone, as
    # it does an automation that already took the next id.
    taken_next: dict[str, Any] = {
        "id": markers.automation_id(f"{home.fan}#2"),
        "alias": "Copy",
        "triggers": [],
        "actions": [],
    }
    await save_entry(hass, taken_next)
    await manager.async_create_new_routine(home.fan)
    await hass.async_block_till_done()
    view = manager.get(home.fan)
    assert view is not None
    assert view.automation_id == markers.automation_id(f"{home.fan}#3")
    assert file_entry(hass, taken_next["id"]) == taken_next
    freezer.tick(timedelta(seconds=3))  # the summary's debounced index rebuild
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    view = manager.get(home.fan)
    assert view is not None
    # The new routine reads once, from its inputs; the taken over one reads as detached.
    assert [item.kind for item in view.items] == ["routine", "detached_routine"]
    assert view.items[0].automation_entity == view.automation_entity_id
    assert view.status is Status.ACTIVE
    assert file_entry(hass, automation_id) == taken
    assert inputs_of(hass, view.automation_id)["on_time"] == "17:00:00"
    assert issue_of(hass, "detached_routine", automation_id) is None
    await manager.async_create_new_routine(home.fan)  # nothing detached: nothing happens
    await manager.async_create_new_routine("no-such-device")


async def test_a_write_racing_a_take_control_detaches_instead_of_writing(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    taken = {"id": automation_id, "alias": "Mine", "triggers": [], "actions": []}
    others = [item for item in file_entries(hass) if item.get("id") != automation_id]
    write_entries(hass, [*others, taken])  # saved, not yet reloaded

    await manager.async_update(home.fan, {"on_time": time(18)})
    await manager.async_flush()

    assert file_entry(hass, automation_id) == taken
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.DETACHED


async def test_a_deleted_automation_resets_the_settings_and_keeps_the_device_opted_in(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    others = [item for item in file_entries(hass) if item.get("id") != automation_id]

    write_entries(hass, others)
    await hass.services.async_call("automation", "reload", {"id": automation_id}, blocking=True)
    await hass.async_block_till_done()

    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.on_time is None
    assert view.status is Status.OFF
    assert home.fan in manager.store.data.opted_in
    assert automation_id not in manager.store.data.owned
    assert state_of(hass, TIMER) is None
    for issue_id in ("invalid_inputs", "detached_routine", "write_conflict"):
        assert issue_of(hass, issue_id, automation_id) is None
    assert manager.routine_summary(home.fan) is None
    # A new setting creates the routine again.
    await give_routine(hass, manager, home.fan, freezer, off_time=time(23))
    assert inputs_of(hass, automation_id)["off_time"] == "23:00:00"


async def delete_in_the_editor(hass: HomeAssistant, hass_client: Any, automation_id: str) -> None:
    """Delete an automation as the automation editor does, through the core's config view.

    The core removes the entry from the file and the entity's registry entry, and reloads
    nothing: no `automation_reloaded` fires.
    """
    assert await async_setup_component(hass, "config", {})
    reloads = async_capture_events(hass, ha_adapter.EVENT_AUTOMATION_RELOADED)
    client = await hass_client()
    response = await client.delete(f"/api/config/automation/config/{automation_id}")
    assert response.status == 200, await response.text()
    await hass.async_block_till_done()
    assert reloads == []
    assert file_entry(hass, automation_id) is None
    assert er.async_get(hass).async_get_entity_id("automation", "automation", automation_id) is None


async def test_an_owned_routine_deleted_in_the_editor_resets_at_once(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any, hass_client: Any
) -> None:
    """F1: the editor's delete resets the routine (PRD 8.2) without waiting for a reload."""
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )

    await delete_in_the_editor(hass, hass_client, automation_id)

    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.on_time is None
    assert view.status is Status.OFF
    assert home.fan in manager.store.data.opted_in
    assert automation_id not in manager.store.data.owned
    assert state_of(hass, TIMER) is None
    assert manager.routine_summary(home.fan) is None


async def test_a_detached_routine_deleted_in_the_editor_clears_its_issue(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any, hass_client: Any
) -> None:
    """F1: a deleted detached routine closes `detached_routine` and frees the controls."""
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await save_entry(hass, {"id": automation_id, "alias": "Mine", "triggers": [], "actions": []})
    assert issue_of(hass, "detached_routine", automation_id) is not None
    assert manager.unavailable_reason(home.fan) == "detached"

    await delete_in_the_editor(hass, hass_client, automation_id)

    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.OFF
    assert issue_of(hass, "detached_routine", automation_id) is None
    assert manager.unavailable_reason(home.fan) != "detached"
    # The device takes a new routine at the first setting, under the same id.
    await give_routine(hass, manager, home.fan, freezer, off_time=time(23))
    assert inputs_of(hass, automation_id)["off_time"] == "23:00:00"


async def test_deleting_another_automation_in_the_editor_leaves_the_routine_alone(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any, hass_client: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await save_entry(hass, {"id": "lamp_evening", "alias": "Lamp", "triggers": [], "actions": []})
    owned = file_entry(hass, automation_id)

    await delete_in_the_editor(hass, hass_client, "lamp_evening")

    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert view.settings.on_time == time(17)
    assert file_entry(hass, automation_id) == owned


async def test_a_sync_during_the_managers_own_delete_leaves_the_routine_to_it(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1: the manager's own delete removes the registry entry too; it resets alone.

    A sync back that runs in the middle (here forced while the helpers are deleted) finds
    the entry gone from the file and leaves the routine to the delete in progress.
    """
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    await manager.async_opt_out(home.fan)
    delete_helpers = manager._async_delete_helpers

    async def racing(refs: Any) -> None:
        manager._request_sync()
        assert manager._sync_task is not None
        await manager._sync_task
        assert automation_id in manager.store.data.owned  # left to the delete
        await delete_helpers(refs)

    monkeypatch.setattr(manager, "_async_delete_helpers", racing)
    await manager.async_delete_routine(home.fan)
    await hass.async_block_till_done()

    assert automation_id not in manager.store.data.owned
    assert manager.get(home.fan) is None
    assert file_entry(hass, automation_id) is None
    assert state_of(hass, TIMER) is None


async def test_a_restore_of_automations_yaml_from_git_rebuilds_the_index_and_the_entities_follow(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    committed = automations_path(hass).read_bytes()
    lamp_id = await give_routine(hass, manager, home.lamp, freezer, on_time=time(7))
    await manager.async_update(home.fan, {"on_time": time(18)})
    await manager.async_flush()
    lamp_entry = file_entry(hass, lamp_id)
    assert lamp_entry is not None
    # The Store forgets the fan and remembers the lamp, which the old file lacks.
    del manager.store.data.owned[automation_id]

    automations_path(hass).write_bytes(committed)
    await reload_all(hass)

    view = manager.get(home.fan)
    assert view is not None
    assert view.settings.on_time == time(17)
    assert manager.store.data.owned[automation_id].last_hash == markers.config_hash(
        file_entry(hass, automation_id) or {}
    )
    lamp = manager.get(home.lamp)
    assert lamp is not None
    assert lamp.settings.on_time is None
    assert lamp_id not in manager.store.data.owned
    # Restoring the newer file brings the lamp back from the markers alone.
    write_entries(hass, [*file_entries(hass), lamp_entry])
    await reload_all(hass)
    lamp = manager.get(home.lamp)
    assert lamp is not None
    assert lamp.settings.on_time == time(7)
    assert lamp.settings.target_entity == LAMP


async def test_an_owned_entry_without_a_device_is_left_alone(
    hass: HomeAssistant, home: Home, manager: RoutineManager, caplog: pytest.LogCaptureFixture
) -> None:
    orphan = {
        "id": markers.automation_id("synthetic-orphan"),
        "alias": "Orphan",
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": {"surprise": 1}},
    }
    write_entries(hass, [orphan])

    await reload_all(hass)

    assert "names no device" in caplog.text
    assert file_entries(hass) == [orphan]
    assert manager.store.data.owned == {}


async def test_a_malformed_file_is_reported_and_changes_nothing(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    automations_path(hass).write_text("not_a: list\n", encoding="utf-8")

    await manager.async_reconcile()

    assert "Could not read the automations file" in caplog.text
    assert automation_id in manager.store.data.owned


async def test_an_unknown_invalid_routine_is_indexed_off_and_has_nothing_to_restore(
    hass: HomeAssistant, home: Home, manager: RoutineManager
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

    assert manager.store.data.owned[automation_id].last_valid_inputs is None
    assert issue_of(hass, "invalid_inputs", automation_id) is not None
    with pytest.raises(ServiceValidationError) as raised:
        await manager.async_restore_last_valid(automation_id)
    assert raised.value.translation_key == "no_valid_settings"
    await manager.async_retry_write(automation_id)
    await manager.async_reconcile()
    assert file_entry(hass, automation_id) == invalid  # never overwritten


async def test_a_restore_that_cannot_write_keeps_the_issue(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.device_routines import ha_adapter  # noqa: PLC0415

    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["surprise"] = True
    await save_entry(hass, entry)

    async def broken(*_args: Any) -> Any:
        raise ha_adapter.AdapterError("synthetic failure")

    monkeypatch.setattr(ha_adapter, "async_write_automation", broken)
    await manager.async_restore_last_valid(automation_id)

    assert issue_of(hass, "invalid_inputs", automation_id) is not None
    assert state_of(hass, AUTOMATION) == "off"


async def test_a_routine_a_person_turned_off_stays_off_after_the_form_is_corrected(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await manager.async_disable(home.fan)
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["surprise"] = True
    await save_entry(hass, entry)
    del entry["use_blueprint"]["input"]["surprise"]

    await save_entry(hass, entry)

    assert issue_of(hass, "invalid_inputs", automation_id) is None
    assert state_of(hass, AUTOMATION) == "off"


async def test_a_detached_routine_deleted_or_restored_clears_its_issue(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    owned = file_entry(hass, automation_id)
    assert owned is not None
    taken = {"id": automation_id, "alias": "Mine", "triggers": [], "actions": []}
    await save_entry(hass, taken)
    assert issue_of(hass, "detached_routine", automation_id) is not None

    # Restored from git: owned again, the controls come back.
    await save_entry(hass, owned)
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert issue_of(hass, "detached_routine", automation_id) is None

    # Detached again, then deleted: the routine resets, nothing is left open.
    await save_entry(hass, taken)
    write_entries(hass, [item for item in file_entries(hass) if item.get("id") != automation_id])
    await reload_all(hass)
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.OFF
    assert issue_of(hass, "detached_routine", automation_id) is None


async def test_deleting_the_automation_of_an_opted_out_device_forgets_the_routine(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from custom_components.device_routines import ha_adapter  # noqa: PLC0415

    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    await manager.async_opt_out(home.fan)

    async def refused(*_args: Any) -> None:
        raise ha_adapter.HelperError("unauthorized", "synthetic refusal")

    monkeypatch.setattr(ha_adapter, "async_delete_helper", refused)
    write_entries(hass, [item for item in file_entries(hass) if item.get("id") != automation_id])
    await reload_all(hass)

    assert manager.get(home.fan) is None
    assert "Could not delete" in caplog.text
    assert state_of(hass, TIMER) == "idle"


async def test_a_custom_description_stays_while_a_generated_alias_follows_a_rename(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["description"] = "The fan we keep for summer."
    await save_entry(hass, entry)

    dr.async_get(hass).async_update_device(home.fan, name_by_user="Bedroom fan")
    await hass.async_block_till_done()

    renamed = file_entry(hass, automation_id)
    assert renamed is not None
    assert renamed["alias"] == "Routine: Bedroom fan"
    assert renamed["description"] == "The fan we keep for summer."


async def test_an_orphan_owned_entry_is_not_indexed_by_a_rebuild(
    hass: HomeAssistant, home: Home, manager: RoutineManager
) -> None:
    orphan = {
        "id": markers.automation_id("synthetic-orphan"),
        "alias": "Orphan",
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": {}},
    }
    write_entries(hass, [orphan])

    assert await manager.async_rebuild_index(dry_run=False) == []
    assert manager.store.data.owned == {}
