"""Build A lane 6: the four maintenance actions (PRD 10.4, D28, TECH_SPEC 4.6 and 4.7).

The actions run against a fake of the manager's side of the contract (`MaintenanceTarget`);
the blueprint reinstall goes through the real adapter into a scratch configuration
directory, with a synthetic stand in for the shipped blueprint (lane 2 writes the real
one). Every id and name is synthetic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any

from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import dump
import pytest

from custom_components.device_routines import ha_adapter, maintenance, markers
from custom_components.device_routines.const import DOMAIN
from custom_components.device_routines.maintenance import (
    MaintenanceAction,
    MaintenanceReport,
    MaintenanceTarget,
)
from custom_components.device_routines.store import OwnedRecord, RoutineStore, StoreData

FAN_DEVICE = "synthetic-living-room-fan"
LAMP_DEVICE = "synthetic-reading-lamp"
PUMP_DEVICE = "synthetic-garden-pump"
FAN_ID = markers.automation_id(FAN_DEVICE)
LAMP_ID = markers.automation_id(LAMP_DEVICE)
PUMP_ID = markers.automation_id(PUMP_DEVICE)
ORPHAN_ID = markers.automation_id("synthetic-orphan")

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
OPTED_OUT = NOW - timedelta(days=2)
REMOVED = NOW - timedelta(hours=1)

BLUEPRINT = """\
# Device Routines blueprint (a synthetic stand in for the shipped file).
blueprint:
  name: Synthetic routine
  domain: automation
  input:
    device_id:
      name: Device
triggers:
  - trigger: event
    event_type: synthetic_routine_probe
    event_data:
      device_id: !input device_id
actions:
  - event: synthetic_routine_ran
    event_data:
      device_id: !input device_id
      edition: shipped
"""
HAND_EDITED = BLUEPRINT.replace("edition: shipped", "edition: hand edited")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeManager:
    """The manager's side of `MaintenanceTarget`, as lane 5 will implement it.

    `artifacts` maps each device to what Home Assistant holds for its routine (the
    automation, helpers and entities); `stale_index` holds the automation ids a rebuild
    would correct; `stale_summaries` the devices whose summaries are out of date.
    """

    def __init__(self, routines: RoutineStore) -> None:
        self._store = routines
        self.artifacts: dict[str, set[str]] = {
            FAN_DEVICE: {FAN_ID, "timer.routine_living_room_fan"},
            LAMP_DEVICE: {LAMP_ID},
            PUMP_DEVICE: {PUMP_ID, "schedule.routine_garden_pump"},
        }
        self.stale_index: set[str] = {ORPHAN_ID, LAMP_ID}
        self.summary_devices = [FAN_DEVICE, LAMP_DEVICE]
        self.stale_summaries: set[str] = {FAN_DEVICE}
        self.refuse_delete: set[str] = set()
        self.deleted: list[str] = []
        self.reinstalled = 0

    @property
    def store(self) -> RoutineStore:
        return self._store

    async def async_delete_routine(self, device_id: str) -> None:
        if device_id in self.refuse_delete:
            raise ha_adapter.AdapterError("synthetic failure")
        self.artifacts.pop(device_id, None)
        self.deleted.append(device_id)

    async def async_rebuild_index(self, *, dry_run: bool) -> list[str]:
        changes = sorted(self.stale_index)
        if not dry_run:
            self.stale_index.clear()
        return changes

    async def async_refresh_summaries(self, *, dry_run: bool) -> list[str]:
        if not dry_run:
            self.stale_summaries.clear()
        return list(self.summary_devices)

    async def async_blueprint_reinstalled(self) -> None:
        self.reinstalled += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "artifacts": {key: sorted(value) for key, value in self.artifacts.items()},
            "stale_index": sorted(self.stale_index),
            "stale_summaries": sorted(self.stale_summaries),
            "reinstalled": self.reinstalled,
        }


def record(device_id: str, target: str) -> OwnedRecord:
    return OwnedRecord(device_id=device_id, target_entity=target, last_hash="0" * 64)


def owned_routine(device_id: str) -> dict[str, Any]:
    return {
        "id": markers.automation_id(device_id),
        "alias": "Routine: Living room fan",
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": {"device_id": device_id}},
    }


@pytest.fixture
async def config_dir(hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A scratch configuration with a hand edited blueprint and one routine using it."""
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text(
        "automation: !include automations.yaml\n", encoding="utf-8"
    )
    shipped = tmp_path / "shipped" / "device_routine.yaml"
    shipped.parent.mkdir()
    shipped.write_text(BLUEPRINT, encoding="utf-8")
    monkeypatch.setattr(maintenance, "SHIPPED_BLUEPRINT", shipped)
    installed(tmp_path).parent.mkdir(parents=True)
    installed(tmp_path).write_text(HAND_EDITED, encoding="utf-8")
    entries = [owned_routine(FAN_DEVICE)]
    (tmp_path / AUTOMATION_CONFIG_PATH).write_text(dump(entries), encoding="utf-8")
    assert await async_setup_component(hass, "automation", {"automation": entries})
    await hass.async_block_till_done()
    return tmp_path


def installed(config: Path) -> Path:
    return config / "blueprints" / "automation" / markers.BLUEPRINT_PATH


@pytest.fixture
def routines(hass: HomeAssistant, hass_storage: dict[str, Any]) -> RoutineStore:
    """One routine in use, one device opted out, one device removed from Home Assistant."""
    loaded = RoutineStore(hass)
    loaded.data = StoreData(
        owned={
            FAN_ID: record(FAN_DEVICE, "fan.living_room"),
            LAMP_ID: record(LAMP_DEVICE, "light.reading_lamp"),
            PUMP_ID: record(PUMP_DEVICE, "switch.garden_pump"),
        },
        opted_in={FAN_DEVICE, PUMP_DEVICE},
        opted_out_at={LAMP_DEVICE: OPTED_OUT},
        removed_devices_at={PUMP_DEVICE: REMOVED},
        blueprint_hash=sha256(BLUEPRINT),
        blueprint_schema=1,
    )
    return loaded


@pytest.fixture
def manager(routines: RoutineStore) -> FakeManager:
    return FakeManager(routines)


def state_of(config: Path, manager: FakeManager, hass_storage: dict[str, Any]) -> dict[str, Any]:
    """Everything an action could change."""
    return {
        "manager": manager.snapshot(),
        "store": manager.store.data.to_dict(),
        "saved": hass_storage.get("device_routines"),
        "blueprint": installed(config).read_bytes() if installed(config).exists() else None,
    }


async def settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


def test_the_actions_are_the_prd_10_4_names() -> None:
    assert [action.value for action in MaintenanceAction] == [
        "clean_up_now",
        "rebuild_index",
        "reinstall_blueprint",
        "refresh_summaries",
    ]


def test_the_fake_satisfies_the_protocol(manager: FakeManager) -> None:
    target: MaintenanceTarget = manager
    assert target.store is manager.store


@pytest.mark.parametrize("action", list(MaintenanceAction))
async def test_every_action_is_idempotent(
    hass: HomeAssistant,
    config_dir: Path,
    manager: FakeManager,
    hass_storage: dict[str, Any],
    action: MaintenanceAction,
) -> None:
    first = await maintenance.async_run(hass, manager, action, dry_run=False)
    after_first = state_of(config_dir, manager, hass_storage)

    second = await maintenance.async_run(hass, manager, action, dry_run=False)

    assert state_of(config_dir, manager, hass_storage) == after_first
    assert first.changed
    assert first.would_change == second.would_change == []
    if action is MaintenanceAction.REFRESH_SUMMARIES:
        # Recomputing is the action: it reports what it recomputed, every time.
        assert second.changed == first.changed
    else:
        assert second.changed == []


@pytest.mark.parametrize("action", list(MaintenanceAction))
async def test_dry_run_changes_nothing_and_reports_what_it_would(
    hass: HomeAssistant,
    config_dir: Path,
    manager: FakeManager,
    hass_storage: dict[str, Any],
    action: MaintenanceAction,
) -> None:
    before = state_of(config_dir, manager, hass_storage)

    dry = await maintenance.async_run(hass, manager, action, dry_run=True)

    assert state_of(config_dir, manager, hass_storage) == before
    assert dry == MaintenanceReport(action=action, changed=[], would_change=dry.would_change)
    assert dry.would_change

    real = await maintenance.async_run(hass, manager, action, dry_run=False)

    assert real.changed == dry.would_change
    assert real.would_change == []


async def test_clean_up_now_deletes_every_candidate_whatever_its_age(
    hass: HomeAssistant, manager: FakeManager, hass_storage: dict[str, Any]
) -> None:
    """D28: the button is for people who do not want to wait for the cleanup period."""
    report = await maintenance.async_run(
        hass, manager, MaintenanceAction.CLEAN_UP_NOW, dry_run=False
    )

    assert report == MaintenanceReport(
        action=MaintenanceAction.CLEAN_UP_NOW, changed=[PUMP_DEVICE, LAMP_DEVICE]
    )
    assert manager.deleted == [PUMP_DEVICE, LAMP_DEVICE]
    assert set(manager.artifacts) == {FAN_DEVICE}
    data = manager.store.data
    assert set(data.owned) == {FAN_ID}
    assert data.opted_in == {FAN_DEVICE}
    assert data.opted_out_at == {}
    assert data.removed_devices_at == {}
    saved = hass_storage["device_routines"]["data"]
    assert list(saved["owned"]) == [FAN_ID]
    assert saved["opted_out_at"] == {}


async def test_clean_up_now_continues_past_a_failed_delete(
    hass: HomeAssistant, manager: FakeManager
) -> None:
    manager.refuse_delete = {PUMP_DEVICE}

    report = await maintenance.async_run(
        hass, manager, MaintenanceAction.CLEAN_UP_NOW, dry_run=False
    )

    assert report.changed == [LAMP_DEVICE]
    data = manager.store.data
    assert data.removed_devices_at == {PUMP_DEVICE: REMOVED}
    assert PUMP_ID in data.owned
    assert PUMP_DEVICE in data.opted_in

    manager.refuse_delete = set()
    retried = await maintenance.async_run(
        hass, manager, MaintenanceAction.CLEAN_UP_NOW, dry_run=False
    )

    assert retried.changed == [PUMP_DEVICE]
    assert set(manager.store.data.owned) == {FAN_ID}


async def test_clean_up_with_nothing_to_do_saves_nothing(
    hass: HomeAssistant, manager: FakeManager, hass_storage: dict[str, Any]
) -> None:
    assert await maintenance.async_clean_up(manager, []) == []
    assert "device_routines" not in hass_storage


def test_cleanup_candidates() -> None:
    """Opted out and not opted back in, or removed from Home Assistant (D28)."""
    data = StoreData(
        opted_in={FAN_DEVICE, PUMP_DEVICE},
        opted_out_at={FAN_DEVICE: OPTED_OUT, LAMP_DEVICE: OPTED_OUT, PUMP_DEVICE: OPTED_OUT},
        removed_devices_at={PUMP_DEVICE: REMOVED, LAMP_DEVICE: REMOVED},
    )

    # The lamp was opted out before it was removed: the earlier moment counts.
    assert maintenance.cleanup_candidates(data) == {LAMP_DEVICE: OPTED_OUT, PUMP_DEVICE: REMOVED}


def test_due_for_cleanup_follows_cleanup_after_days() -> None:
    data = StoreData(
        opted_out_at={LAMP_DEVICE: NOW - timedelta(days=31)},
        removed_devices_at={
            PUMP_DEVICE: NOW - timedelta(days=29),
            FAN_DEVICE: NOW - timedelta(days=30),
        },
    )

    assert maintenance.due_for_cleanup(data, NOW, 30) == [FAN_DEVICE, LAMP_DEVICE]
    assert maintenance.due_for_cleanup(data, NOW, 365) == []
    assert maintenance.due_for_cleanup(data, NOW, 0) == [], "0 means never"
    assert maintenance.next_cleanup_at(data, 30) == NOW - timedelta(days=1)
    assert maintenance.next_cleanup_at(data, 0) is None
    assert maintenance.next_cleanup_at(StoreData(), 30) is None


async def test_reinstall_blueprint_restores_the_shipped_file_usable_at_once(
    hass: HomeAssistant, config_dir: Path, manager: FakeManager, hass_storage: dict[str, Any]
) -> None:
    manager.store.data.blueprint_hash = sha256(HAND_EDITED)
    ran: list[Event] = []
    hass.bus.async_listen("synthetic_routine_ran", ran.append)

    report = await maintenance.async_run(
        hass, manager, MaintenanceAction.REINSTALL_BLUEPRINT, dry_run=False
    )

    assert report.changed == [markers.BLUEPRINT_PATH]
    assert installed(config_dir).read_text(encoding="utf-8") == BLUEPRINT
    assert manager.store.data.blueprint_hash == sha256(BLUEPRINT)
    assert hass_storage["device_routines"]["data"]["blueprint_hash"] == sha256(BLUEPRINT)
    assert manager.reinstalled == 1
    hass.bus.async_fire("synthetic_routine_probe", {"device_id": FAN_DEVICE})
    await settle()
    assert [event.data["edition"] for event in ran] == ["shipped"]

    again = await maintenance.async_run(
        hass, manager, MaintenanceAction.REINSTALL_BLUEPRINT, dry_run=False
    )

    assert again.changed == []
    assert manager.reinstalled == 1


async def test_reinstall_blueprint_installs_a_missing_file(
    hass: HomeAssistant, config_dir: Path, manager: FakeManager
) -> None:
    installed(config_dir).unlink()

    dry = await maintenance.async_run(
        hass, manager, MaintenanceAction.REINSTALL_BLUEPRINT, dry_run=True
    )
    assert dry.would_change == [markers.BLUEPRINT_PATH]
    assert not installed(config_dir).exists()

    report = await maintenance.async_run(
        hass, manager, MaintenanceAction.REINSTALL_BLUEPRINT, dry_run=False
    )

    assert report.changed == [markers.BLUEPRINT_PATH]
    assert installed(config_dir).read_text(encoding="utf-8") == BLUEPRINT


@pytest.mark.parametrize(
    ("action", "method"),
    [
        (MaintenanceAction.REBUILD_INDEX, "async_rebuild_index"),
        (MaintenanceAction.REFRESH_SUMMARIES, "async_refresh_summaries"),
    ],
)
@pytest.mark.parametrize("dry_run", [True, False])
async def test_the_manager_primitives_get_the_dry_run_flag(
    hass: HomeAssistant,
    manager: FakeManager,
    action: MaintenanceAction,
    method: str,
    dry_run: bool,
) -> None:
    calls: list[bool] = []
    original: Callable[..., Any] = getattr(manager, method)

    async def spy(*, dry_run: bool) -> list[str]:
        calls.append(dry_run)
        result: list[str] = await original(dry_run=dry_run)
        return result

    setattr(manager, method, spy)

    await maintenance.async_run(hass, manager, action, dry_run=dry_run)

    assert calls == [dry_run]


async def test_async_run_takes_the_action_name(hass: HomeAssistant, manager: FakeManager) -> None:
    """Actions, the button and the WebSocket command pass the name as text."""
    report = await maintenance.async_run(hass, manager, "rebuild_index", dry_run=True)

    assert report.action is MaintenanceAction.REBUILD_INDEX
    assert report.would_change == sorted([ORPHAN_ID, LAMP_ID])
    with pytest.raises(ValueError, match="defragment"):
        await maintenance.async_run(hass, manager, "defragment", dry_run=True)


async def test_the_shipped_blueprint_is_read_from_the_package(
    hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    component = Path(maintenance.__file__).parent
    assert component / "blueprints" / "device_routine.yaml" == maintenance.SHIPPED_BLUEPRINT
    stand_in = tmp_path / "device_routine.yaml"
    stand_in.write_text(BLUEPRINT, encoding="utf-8")
    monkeypatch.setattr(maintenance, "SHIPPED_BLUEPRINT", stand_in)

    assert maintenance.shipped_blueprint_text() == BLUEPRINT
    assert maintenance.blueprint_hash(BLUEPRINT) == sha256(BLUEPRINT)


@pytest.mark.parametrize(
    "failure",
    [
        ha_adapter.AdapterError("automations.yaml does not hold a list"),
        ha_adapter.HelperError("timeout", "schedule/delete did not answer"),
        OSError("disk full"),
        HomeAssistantError("an untranslated core error"),
    ],
    ids=["adapter", "helper", "os", "untranslated"],
)
async def test_a_failure_is_a_translated_home_assistant_error(
    hass: HomeAssistant, manager: FakeManager, failure: Exception
) -> None:
    """Plan A4.0 item 5, quality rule `action-exceptions`: never a bare adapter error."""

    async def failing(*, dry_run: bool) -> list[str]:
        raise failure

    manager.async_rebuild_index = failing  # type: ignore[method-assign]

    with pytest.raises(HomeAssistantError) as raised:
        await maintenance.async_run(hass, manager, MaintenanceAction.REBUILD_INDEX, dry_run=False)

    assert type(raised.value) is HomeAssistantError
    assert raised.value.__cause__ is failure
    assert (raised.value.translation_domain, raised.value.translation_key) == (
        DOMAIN,
        "maintenance_failed",
    )
    assert raised.value.translation_placeholders == {
        "action": "rebuild_index",
        "error": str(failure),
    }


async def test_a_translated_refusal_passes_unchanged(
    hass: HomeAssistant, manager: FakeManager
) -> None:
    refusal = ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")

    async def refusing(*, dry_run: bool) -> list[str]:
        raise refusal

    manager.async_refresh_summaries = refusing  # type: ignore[method-assign]

    with pytest.raises(ServiceValidationError) as raised:
        await maintenance.async_run(hass, manager, "refresh_summaries", dry_run=True)

    assert raised.value is refusal
