"""Build A lane 5: reconcile and self healing (TECH_SPEC 7, PRD 3.1).

Every step of the checklist runs twice in the idempotence test; the others provoke one
situation of the PRD 3.1 table each and check the automatic response and the Repairs
issue, if any. Every id and name is synthetic.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
    label_registry as lr,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_routines import ha_adapter, maintenance, markers
from custom_components.device_routines.const import DOMAIN
from custom_components.device_routines.maintenance import MaintenanceAction
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import Status
from tests.integration.conftest import (
    AUTOMATION,
    FAN,
    SCHEDULE,
    TIMER,
    Home,
    automations_path,
    file_entry,
    give_routine,
    inputs_of,
    issue_of,
    save_entry,
    state_of,
)

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

OLD_BLUEPRINT = maintenance.SHIPPED_BLUEPRINT.read_text(encoding="utf-8").replace(
    "# Device Routines blueprint, schema 1.",
    "# Device Routines blueprint, schema 1, an older build.",
)


def installed_path(hass: HomeAssistant) -> Any:
    from pathlib import Path  # noqa: PLC0415

    return Path(hass.config.config_dir) / "blueprints" / "automation" / markers.BLUEPRINT_PATH


def snapshot(hass: HomeAssistant, manager: RoutineManager) -> dict[str, Any]:
    """Everything a reconcile could change."""
    return {
        "file": automations_path(hass).read_bytes(),
        "blueprint": installed_path(hass).read_bytes(),
        "store": manager.store.data.to_dict(),
        "issues": sorted(
            issue_id for (domain, issue_id) in ir.async_get(hass).issues if domain == DOMAIN
        ),
        "entities": sorted(er.async_get(hass).entities),
        "labels": sorted(lr.async_get(hass).labels),
    }


async def test_every_reconcile_step_is_idempotent(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30)
    await give_routine(hass, manager, home.lamp, freezer, off_time=time(23))

    await manager.async_reconcile()
    first = snapshot(hass, manager)
    await manager.async_reconcile()

    assert snapshot(hass, manager) == first
    assert first["issues"] == []
    assert manager.health_inputs().blueprint_status == "shipped"


async def test_a_missing_blueprint_is_installed_and_the_routines_load_again(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    installed_path(hass).unlink()
    await hass.services.async_call("automation", "reload", {"id": automation_id}, blocking=True)
    await hass.async_block_till_done()
    assert state_of(hass, AUTOMATION) == "unavailable"

    await manager.async_reconcile()
    await hass.async_block_till_done()

    assert installed_path(hass).read_text(encoding="utf-8") == maintenance.shipped_blueprint_text()
    assert state_of(hass, AUTOMATION) == "on"  # regenerated once, and it loads
    assert issue_of(hass, "automation_load_failed", automation_id) is None
    assert manager.health_inputs().loaded_count == 1


async def test_a_modified_blueprint_raises_blueprint_modified_and_is_left_alone(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    edited = installed_path(hass).read_text(encoding="utf-8") + "# edited by hand\n"
    installed_path(hass).write_text(edited, encoding="utf-8")

    await manager.async_reconcile()

    assert installed_path(hass).read_text(encoding="utf-8") == edited
    assert issue_of(hass, "blueprint_modified") is not None
    assert manager.health_inputs().blueprint_status == "modified"
    assert state_of(hass, AUTOMATION) == "on"

    # The Repairs fix (the maintenance action) puts the shipped file back.
    report = await maintenance.async_run(
        hass, manager, MaintenanceAction.REINSTALL_BLUEPRINT, False
    )
    assert report.changed == [markers.BLUEPRINT_PATH]
    assert issue_of(hass, "blueprint_modified") is None
    assert manager.health_inputs().blueprint_status == "shipped"


async def test_a_previously_shipped_blueprint_is_upgraded(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    await ha_adapter.async_install_blueprint(hass, OLD_BLUEPRINT)
    manager.store.data.blueprint_hash = maintenance.blueprint_hash(OLD_BLUEPRINT)

    await manager.async_reconcile()

    assert installed_path(hass).read_text(encoding="utf-8") == maintenance.shipped_blueprint_text()
    assert manager.store.data.blueprint_hash == maintenance.blueprint_hash(
        maintenance.shipped_blueprint_text()
    )
    assert issue_of(hass, "blueprint_modified") is None


async def test_a_missing_timer_helper_is_recreated_with_the_same_entity_id(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    user = await ha_adapter.async_ensure_system_user(hass, None)
    await ha_adapter.async_delete_helper(hass, user, TIMER)
    await hass.async_block_till_done()
    assert state_of(hass, TIMER) is None

    await manager.async_reconcile()
    await hass.async_block_till_done()

    assert state_of(hass, TIMER) == "idle"
    assert inputs_of(hass, automation_id)["timer_entity"] == TIMER
    assert markers.LABEL_ID in er.async_get(hass).async_get(TIMER).labels  # type: ignore[union-attr]
    assert issue_of(hass, "schedule_blocks_needed", automation_id) is None


async def test_a_missing_weekly_schedule_is_recreated_and_raises_schedule_blocks_needed(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        days="weekly_schedule",
        schedule_entity=SCHEDULE,
    )
    assert state_of(hass, SCHEDULE) is None

    await manager.async_reconcile()
    await hass.async_block_till_done()

    assert state_of(hass, SCHEDULE) == "off"
    issue = issue_of(hass, "schedule_blocks_needed", automation_id)
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["schedule"] == SCHEDULE


async def test_an_owned_automation_that_fails_to_load_is_regenerated_once_then_reported(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    automation_id = await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_time=time(17),
        extra_conditions=[{"condition": "no_such_condition"}],
    )
    assert state_of(hass, AUTOMATION) == "unavailable"
    events: list[Any] = []
    real = ha_adapter.async_write_automation

    async def spy(*args: Any) -> Any:
        events.append(args[1])
        return await real(*args)

    monkeypatch.setattr(ha_adapter, "async_write_automation", spy)
    await manager.async_reconcile()
    await manager.async_reconcile()

    assert events == [automation_id]  # regenerated once, not at every reconcile
    issue = issue_of(hass, "automation_load_failed", automation_id)
    assert issue is not None
    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.INVALID
    assert manager.health_inputs().loaded_count == 0

    # Correcting the inputs in the form, then the fix flow, loads it again.
    entry = file_entry(hass, automation_id)
    assert entry is not None
    entry["use_blueprint"]["input"]["extra_conditions"] = []
    await save_entry(hass, entry)
    await manager.async_regenerate(automation_id)
    assert state_of(hass, AUTOMATION) == "on"
    assert issue_of(hass, "automation_load_failed", automation_id) is None


async def test_a_missing_target_turns_the_routine_off_until_it_returns(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    registry = er.async_get(hass)

    registry.async_remove(FAN)
    hass.states.async_remove(FAN)
    await hass.async_block_till_done()
    await manager.async_reconcile()

    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.MISSING_TARGET
    assert manager.unavailable_reason(home.fan) == "missing_target"
    assert state_of(hass, AUTOMATION) == "off"
    assert view.sentence == "Routine off"

    registry.async_get_or_create(
        "switch", "sandbox", "fan_again", suggested_object_id="living_room_fan"
    )
    await hass.async_block_till_done()

    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.ACTIVE
    assert state_of(hass, AUTOMATION) == "on"


@pytest.mark.parametrize(("options", "follows"), [({}, True), ({"assign_area": False}, False)])
async def test_the_area_follows_the_device_when_assign_area_is_on(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any, follows: bool
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    registry = er.async_get(hass)
    registry.async_update_entity(AUTOMATION, area_id=None)

    await manager.async_reconcile()

    entry = registry.async_get(AUTOMATION)
    assert entry is not None
    assert (entry.area_id == home.area) is follows


async def test_reconcile_stops_at_an_incompatible_adapter(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    installed_path(hass).unlink()
    monkeypatch.setattr(
        ha_adapter,
        "check",
        lambda _hass: ha_adapter.AdapterReport(failed=(ha_adapter.CAPABILITY_BLUEPRINT,)),
    )

    await manager.async_reconcile()

    assert not installed_path(hass).exists()
    assert issue_of(hass, "adapter_incompatible") is not None
    assert manager.health_inputs().adapter_failed == (ha_adapter.CAPABILITY_BLUEPRINT,)


async def test_the_label_and_the_opted_in_set_agree_after_a_reconcile(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """TECH_SPEC 7 step 6 in both directions, and a device removed while down."""
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    garage = home.garage
    manager.store.data.opted_in.discard(home.fan)  # labelled, not in the set
    manager.store.data.opted_in.add(home.lamp)  # in the set, not labelled
    gone = dr.async_get(hass).async_get_or_create(
        config_entry_id=home.source.entry_id, identifiers={("sandbox", "gone")}, name="Gone"
    )
    manager.store.data.opted_in.add(gone.id)
    dr.async_get(hass).async_remove_device(gone.id)
    await hass.async_block_till_done()

    await manager.async_reconcile()
    removed_at = manager.store.data.removed_devices_at[gone.id]
    await manager.async_reconcile()

    data = manager.store.data
    assert home.fan in data.opted_in
    assert home.lamp not in data.opted_in
    assert home.lamp in data.opted_out_at
    assert data.removed_devices_at[gone.id] == removed_at
    assert garage not in data.opted_in


async def test_a_deleted_label_found_at_reconcile_is_recreated_and_applied_again(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    # The label went while the integration was not listening.
    monkeypatch.setattr(manager, "_label_registry_updated", lambda _event: None)
    for unsubscribe in manager._unsubscribe:
        unsubscribe()
    lr.async_get(hass).async_delete(markers.LABEL_ID)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get(home.fan)
    assert device is not None
    assert markers.LABEL_ID not in device.labels
    manager.store.data.opted_in.add("synthetic-gone-device")
    # A rebuild while the label is gone keeps the opted in set (plan Section 4.9).
    await manager.async_rebuild_index(dry_run=False)
    assert home.fan in manager.store.data.opted_in

    await manager.async_reconcile()

    device = dr.async_get(hass).async_get(home.fan)
    assert device is not None
    assert markers.LABEL_ID in device.labels
    assert home.fan in manager.store.data.opted_in


async def test_the_maintenance_side_rebuilds_refreshes_and_cleans_up(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    routines: MockConfigEntry,
) -> None:
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    lamp_id = await give_routine(hass, manager, home.lamp, freezer, on_time=time(7))
    del manager.store.data.owned[automation_id]

    would = await manager.async_rebuild_index(dry_run=True)
    assert would == [automation_id]
    assert automation_id not in manager.store.data.owned
    assert await manager.async_rebuild_index(dry_run=False) == [automation_id]
    assert set(manager.store.data.owned) == {automation_id, lamp_id}
    assert await manager.async_rebuild_index(dry_run=False) == []

    refreshed = await maintenance.async_run(
        hass, manager, MaintenanceAction.REFRESH_SUMMARIES, False
    )
    assert refreshed.changed == sorted([home.fan, home.lamp])
    assert await manager.async_refresh_summaries(dry_run=True) == sorted([home.fan, home.lamp])

    await manager.async_opt_out(home.lamp)
    assert await manager.async_cleanup(dry_run=True) == []
    cleaned = await maintenance.async_run(hass, manager, MaintenanceAction.CLEAN_UP_NOW, False)
    assert cleaned.changed == [home.lamp]
    assert file_entry(hass, lamp_id) is None
    assert manager.get(home.lamp) is None
    await manager.async_delete_routine(home.lamp)  # nothing left: no error


async def test_setting_up_creates_the_label_the_category_and_the_blueprint(
    hass: HomeAssistant, home: Home, manager: RoutineManager
) -> None:
    """PRD 3.1, Integration installed: no fields, the label, category and blueprint exist."""
    from homeassistant.helpers import category_registry as cr  # noqa: PLC0415

    label = lr.async_get(hass).async_get_label(markers.LABEL_ID)
    assert label is not None
    assert (label.name, label.icon) == (markers.LABEL_NAME, markers.ICON)
    categories = cr.async_get(hass).async_list_categories(scope="automation")
    assert [(item.name, item.icon) for item in categories] == [
        (markers.CATEGORY_NAME, markers.ICON)
    ]
    assert installed_path(hass).read_text(encoding="utf-8") == maintenance.shipped_blueprint_text()
    assert manager.store.data.blueprint_schema == 1
    assert manager.list() == ()


@pytest.mark.parametrize("options", [{"cleanup_after_days": 1}])
async def test_an_opted_out_routine_is_cleaned_up_after_the_period(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """PRD 3.1, Device opted out: settings kept, then deleted after the period (D28)."""
    from datetime import timedelta  # noqa: PLC0415

    from pytest_homeassistant_custom_component.common import (  # noqa: PLC0415
        async_fire_time_changed,
    )

    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), turn_off_after_min=30
    )
    await manager.async_opt_out(home.fan)
    freezer.tick(timedelta(hours=23))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert file_entry(hass, automation_id) is not None

    freezer.tick(timedelta(hours=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert file_entry(hass, automation_id) is None
    assert state_of(hass, TIMER) is None
    assert home.fan not in manager.store.data.opted_out_at
    assert manager.get(home.fan) is None
    assert manager.routine_for(FAN) is None
