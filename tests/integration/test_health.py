"""The Health sensor and what it reads: the deploy marker, the channel, the routines.

TECH_SPEC 10.3 is the contract: the state is `ok`, `degraded` (the blueprint was edited by
hand, or an owned automation does not load) or `error` (the adapter is incompatible); the
attributes carry the deploy record (`version`, `commit`, `branch`, `deployed_at`,
`channel`, `ha_version`), which the deploy tool's post restart check reads, and the
routine checks (`blueprint_schema`, `blueprint_status`, `owned_count`, `loaded_count`,
`issues`, `last_reconcile`), which the manager supplies. Every id and name is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, time
import json
from pathlib import Path
from typing import Any

from homeassistant.core import CALLBACK_TYPE, CoreState, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_routines import compiler, ha_adapter, health, markers, repairs
from custom_components.device_routines.const import DOMAIN
from custom_components.device_routines.maintenance import MaintenanceAction, async_run
from custom_components.device_routines.manager import HealthInputs, ManagerEvent, RoutineManager
from tests.integration.conftest import Home, give_routine, issue_of

HEALTH = "sensor.device_routines_health"
SHA = "0123456789abcdef0123456789abcdef01234567"
MARKER = {
    "commit": SHA,
    "branch": "dev-stable",
    "deployed_at": "2026-10-13T20:00:00Z",
    "previous_commit": None,
    "changed_files": ["const.py", "sensor.py"],
}
# A per routine issue carries the routine's automation id (decision L41).
ROUTINE_ID = "device_routines_0123456789ab"

# The manager's routines leave their own timers behind (pause ends, cleanup).
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


# --------------------------------------------------------------------------------------
# Reading the deploy marker (blocking, pure functions)
# --------------------------------------------------------------------------------------


def test_no_marker_means_no_deployment(tmp_path: Path) -> None:
    assert health.read_deployment(tmp_path) is None


def test_the_marker_is_read(tmp_path: Path) -> None:
    (tmp_path / ".deployed").write_text(json.dumps(MARKER), encoding="utf-8")

    deployment = health.read_deployment(tmp_path)

    assert deployment == health.Deployment(
        commit=SHA,
        branch="dev-stable",
        deployed_at="2026-10-13T20:00:00Z",
        previous_commit=None,
        changed_files=2,
        rollback_of=None,
    )


@pytest.mark.parametrize("body", ["{not json", '["a list"]', ""])
def test_a_damaged_marker_reads_as_no_deployment(tmp_path: Path, body: str) -> None:
    (tmp_path / ".deployed").write_text(body, encoding="utf-8")

    assert health.read_deployment(tmp_path) is None


def test_a_rollback_marker_names_what_it_rolled_back(tmp_path: Path) -> None:
    marker = dict(MARKER, rollback_of="f" * 40)
    (tmp_path / ".deployed").write_text(json.dumps(marker), encoding="utf-8")

    deployment = health.read_deployment(tmp_path)

    assert deployment is not None
    assert deployment.rollback_of == "f" * 40


# --------------------------------------------------------------------------------------
# Channel
# --------------------------------------------------------------------------------------


def test_a_deployment_means_the_dev_channel(tmp_path: Path) -> None:
    assert health.detect_channel(tmp_path, has_deployment=True) == "dev"


def test_the_hacs_store_listing_the_domain_means_the_hacs_channel(tmp_path: Path) -> None:
    store = tmp_path / ".storage" / "hacs.repositories"
    store.parent.mkdir()
    store.write_text(
        json.dumps(
            {
                "data": {
                    "1": {"domain": "other", "installed": True},
                    "2": {"domain": DOMAIN, "installed": True, "full_name": "x/y"},
                }
            }
        ),
        encoding="utf-8",
    )

    assert health.detect_channel(tmp_path, has_deployment=False) == "hacs"


def test_the_hacs_store_knowing_but_not_installing_is_not_the_hacs_channel(
    tmp_path: Path,
) -> None:
    store = tmp_path / ".storage" / "hacs.repositories"
    store.parent.mkdir()
    store.write_text(
        json.dumps({"data": {"2": {"domain": DOMAIN, "installed": False}}}), encoding="utf-8"
    )

    assert health.detect_channel(tmp_path, has_deployment=False) == "unknown"


@pytest.mark.parametrize("body", [None, "{broken", '{"data": "nope"}', '{"data": {"1": 5}}'])
def test_no_usable_hacs_store_means_unknown(tmp_path: Path, body: str | None) -> None:
    if body is not None:
        store = tmp_path / ".storage" / "hacs.repositories"
        store.parent.mkdir()
        store.write_text(body, encoding="utf-8")

    assert health.detect_channel(tmp_path, has_deployment=False) == "unknown"


# --------------------------------------------------------------------------------------
# The rules: ok, degraded, error (TECH_SPEC 10.3)
# --------------------------------------------------------------------------------------


def inputs(**changes: Any) -> HealthInputs:
    """Inputs of a healthy instance with two routines; a test changes what it needs."""
    healthy = HealthInputs(
        owned_count=2,
        loaded_count=2,
        issues=(),
        last_reconcile=datetime(2026, 10, 19, 8, 0, tzinfo=UTC),
        blueprint_status="shipped",
        blueprint_schema=compiler.BLUEPRINT_SCHEMA_VERSION,
        adapter_failed=(),
    )
    return replace(healthy, **changes)


def report(source: HealthInputs) -> health.HealthReport:
    return health.build_report(
        deployment=None, channel="unknown", version="0.3.0", ha_version="2026.10.2", inputs=source
    )


def test_every_check_passing_reads_ok() -> None:
    assert health.health_state(inputs()) == "ok"


@pytest.mark.parametrize(
    "changes",
    [
        {"blueprint_status": "modified"},
        {"loaded_count": 1},
        {"issues": (repairs.issue_registry_id(repairs.AUTOMATION_LOAD_FAILED, ROUTINE_ID),)},
    ],
    ids=["blueprint_modified", "automation_not_loaded", "load_failed_issue"],
)
def test_degraded_on_a_modified_blueprint_or_an_automation_that_does_not_load(
    changes: dict[str, Any],
) -> None:
    assert health.health_state(inputs(**changes)) == "degraded"


def test_issues_a_person_resolves_in_repairs_do_not_degrade_health() -> None:
    """A routine edited into an invalid state or two automations colliding is the
    routine's problem, shown in Repairs; the integration itself is well."""
    issues = tuple(
        repairs.issue_registry_id(issue_id, ROUTINE_ID)
        for issue_id in (repairs.INVALID_INPUTS, repairs.DETACHED_ROUTINE, repairs.CONFLICT)
    )

    assert health.health_state(inputs(issues=issues)) == "ok"


def test_an_incompatible_adapter_reads_error_even_when_degraded_too() -> None:
    failing = inputs(
        adapter_failed=(ha_adapter.CAPABILITY_WRITE,),
        blueprint_status="modified",
        loaded_count=0,
    )

    assert health.health_state(failing) == "error"


def test_the_report_carries_every_routine_attribute() -> None:
    issue = repairs.issue_registry_id(repairs.CONFLICT, ROUTINE_ID)

    built = report(inputs(owned_count=3, loaded_count=3, issues=(issue,)))

    assert built.state == "ok"
    assert built.as_attributes() == {
        "version": "0.3.0",
        "commit": None,
        "branch": None,
        "deployed_at": None,
        "channel": "unknown",
        "ha_version": "2026.10.2",
        "blueprint_schema": compiler.BLUEPRINT_SCHEMA_VERSION,
        "blueprint_status": "ok",
        "owned_count": 3,
        "loaded_count": 3,
        "issues": [issue],
        "last_reconcile": "2026-10-19T08:00:00+00:00",
    }


@pytest.mark.parametrize(
    ("status", "shown"), [("shipped", "ok"), ("modified", "modified"), (None, None)]
)
def test_the_blueprint_status_reads_ok_modified_or_not_checked_yet(
    status: str | None, shown: str | None
) -> None:
    assert report(inputs(blueprint_status=status)).blueprint_status == shown


def test_before_the_first_reconcile_there_is_no_time() -> None:
    assert report(inputs(last_reconcile=None)).last_reconcile is None


# --------------------------------------------------------------------------------------
# The monitor: what keeps the report current
# --------------------------------------------------------------------------------------


class FakeManager:
    """The two methods Health reads, with inputs a test sets and events it fires."""

    def __init__(self) -> None:
        self.inputs = inputs()
        self.listeners: list[Callable[[ManagerEvent], None]] = []

    def health_inputs(self) -> HealthInputs:
        return self.inputs

    @callback
    def async_add_listener(self, update: Callable[[ManagerEvent], None]) -> CALLBACK_TYPE:
        self.listeners.append(update)

        @callback
        def remove() -> None:
            self.listeners.remove(update)

        return remove

    def fire(self, kind: str = "health_changed") -> None:
        for update in list(self.listeners):
            update(ManagerEvent(kind, None))  # type: ignore[arg-type]


async def test_the_monitor_follows_manager_events_and_this_integrations_issues(
    hass: HomeAssistant,
) -> None:
    manager = FakeManager()
    monitor = health.HealthMonitor(hass, report(manager.inputs), manager)
    monitor.async_start()
    heard: list[str] = []
    remove = monitor.async_add_listener(lambda: heard.append(monitor.report.state))

    manager.inputs = inputs(blueprint_status="modified")
    manager.fire()
    assert heard == ["degraded"]
    assert monitor.report.blueprint_status == "modified"

    # Any manager event refreshes; an unchanged report is not announced again.
    manager.fire("routine_changed")
    assert heard == ["degraded"]

    # An issue of another integration is not ours to read; one of ours is.
    manager.inputs = inputs(issues=("conflict_x",))
    ir.async_create_issue(
        hass,
        "other_domain",
        "something",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="something",
    )
    await hass.async_block_till_done()
    assert heard == ["degraded"]
    repairs.async_sync_issue(hass, repairs.CONFLICT, present=True, subject="x")
    await hass.async_block_till_done()
    assert heard == ["degraded", "ok"]
    assert monitor.report.issues == ("conflict_x",)

    # Stopped, it hears nothing and keeps its last report.
    remove()
    monitor.async_stop()
    manager.inputs = inputs(adapter_failed=(ha_adapter.CAPABILITY_READ,))
    manager.fire()
    repairs.async_sync_issue(hass, repairs.CONFLICT, present=False, subject="x")
    await hass.async_block_till_done()
    assert manager.listeners == []
    assert monitor.report.state == "ok"


# --------------------------------------------------------------------------------------
# The sensor
# --------------------------------------------------------------------------------------


async def test_the_health_sensor_without_a_deployment(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    state = hass.states.get(HEALTH)

    assert state is not None
    assert state.state == "ok"
    assert state.attributes["version"] == integration.version
    assert state.attributes["commit"] is None
    assert state.attributes["branch"] is None
    assert state.attributes["deployed_at"] is None
    assert state.attributes["channel"] == "unknown"
    assert state.attributes["ha_version"] == hass.config.as_dict()["version"]
    # Setting up in a running instance reconciles at once: the blueprint is installed.
    assert state.attributes["blueprint_status"] == "ok"
    assert state.attributes["owned_count"] == 0
    assert state.attributes["loaded_count"] == 0
    assert state.attributes["issues"] == []
    assert dt_util.parse_datetime(state.attributes["last_reconcile"]) is not None
    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == ["ok", "degraded", "error"]


async def test_the_health_sensor_with_a_deployment(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The deploy tool's post restart check reads `commit` and the state: unchanged."""
    (tmp_path / ".deployed").write_text(json.dumps(MARKER), encoding="utf-8")
    monkeypatch.setattr(health, "COMPONENT_DIR", tmp_path)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(HEALTH)

    assert state is not None
    assert state.state == "ok"
    assert state.attributes["commit"] == SHA
    assert state.attributes["branch"] == "dev-stable"
    assert state.attributes["deployed_at"] == "2026-10-13T20:00:00Z"
    assert state.attributes["channel"] == "dev"


async def test_while_home_assistant_boots_health_waits_for_the_first_reconcile(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    hass.set_state(CoreState.not_running)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    booting = hass.states.get(HEALTH)
    assert booting is not None
    assert booting.state == "ok"
    assert booting.attributes["blueprint_status"] is None
    assert booting.attributes["last_reconcile"] is None

    await hass.async_start()
    await hass.async_block_till_done()

    started = hass.states.get(HEALTH)
    assert started is not None
    assert started.attributes["blueprint_status"] == "ok"
    assert dt_util.parse_datetime(started.attributes["last_reconcile"]) is not None


async def test_the_health_sensor_counts_the_routines_and_their_automations(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9))
    await give_routine(hass, manager, home.lamp, freezer, turn_off_after_min=30)

    state = hass.states.get(HEALTH)

    assert state is not None
    assert state.state == "ok"
    assert state.attributes["owned_count"] == 2
    assert state.attributes["loaded_count"] == 2
    assert state.attributes["blueprint_status"] == "ok"
    assert state.attributes["blueprint_schema"] == compiler.BLUEPRINT_SCHEMA_VERSION
    assert state.attributes["issues"] == []


async def test_an_owned_automation_that_does_not_load_turns_health_degraded(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    # A condition the core does not know keeps the automation from loading.
    automation_id = await give_routine(
        hass,
        manager,
        home.fan,
        freezer,
        on_time=time(17),
        extra_conditions=[{"condition": "no_such_condition"}],
    )

    # Seen at once, from the counts, before any reconcile looks at it.
    state = hass.states.get(HEALTH)
    assert state is not None
    assert state.state == "degraded"
    assert (state.attributes["owned_count"], state.attributes["loaded_count"]) == (1, 0)

    # Reconcile regenerates it once, then reports it (TECH_SPEC 7 step 5).
    await manager.async_reconcile()
    await hass.async_block_till_done()
    state = hass.states.get(HEALTH)
    assert state is not None
    assert state.state == "degraded"
    issue = repairs.issue_registry_id(repairs.AUTOMATION_LOAD_FAILED, automation_id)
    assert issue in state.attributes["issues"]


async def test_a_hand_edited_blueprint_turns_health_degraded_until_it_is_reinstalled(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    installed = Path(hass.config.config_dir) / "blueprints" / "automation" / markers.BLUEPRINT_PATH
    installed.write_text(installed.read_text(encoding="utf-8") + "\n# edited\n", "utf-8")

    await manager.async_reconcile()
    await hass.async_block_till_done()

    state = hass.states.get(HEALTH)
    assert state is not None
    assert state.state == "degraded"
    assert state.attributes["blueprint_status"] == "modified"
    assert repairs.BLUEPRINT_MODIFIED in state.attributes["issues"]

    await async_run(hass, manager, MaintenanceAction.REINSTALL_BLUEPRINT, dry_run=False)
    await hass.async_block_till_done()

    state = hass.states.get(HEALTH)
    assert state is not None
    assert state.state == "ok"
    assert state.attributes["blueprint_status"] == "ok"
    assert state.attributes["issues"] == []


async def test_an_incompatible_adapter_turns_health_error_and_back(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    real_check = ha_adapter.check
    monkeypatch.setattr(
        ha_adapter,
        "check",
        lambda _hass: ha_adapter.AdapterReport(failed=(ha_adapter.CAPABILITY_WRITE,)),
    )

    await manager.async_reconcile()
    await hass.async_block_till_done()

    state = hass.states.get(HEALTH)
    assert state is not None
    assert state.state == "error"
    assert repairs.ADAPTER_INCOMPATIBLE in state.attributes["issues"]
    # The routine keeps running: its automation is still loaded.
    assert state.attributes["loaded_count"] == 1

    monkeypatch.setattr(ha_adapter, "check", real_check)
    await manager.async_reconcile()
    await hass.async_block_till_done()

    state = hass.states.get(HEALTH)
    assert state is not None
    assert state.state == "ok"
    assert issue_of(hass, repairs.ADAPTER_INCOMPATIBLE) is None


async def test_the_issues_attribute_follows_repairs_between_reconciles(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    automation_id = await give_routine(hass, manager, home.fan, freezer, on_time=time(17))
    before = hass.states.get(HEALTH)
    assert before is not None
    reconciled = before.attributes["last_reconcile"]

    # The conflict issue is raised by the summary, not by the manager (FR-S6).
    repairs.async_sync_issue(
        hass,
        repairs.CONFLICT,
        present=True,
        placeholders={"device": "x", "first": "a", "second": "b", "time": "5:00 PM"},
        subject=automation_id,
    )
    await hass.async_block_till_done()

    state = hass.states.get(HEALTH)
    assert state is not None
    assert state.attributes["issues"] == [
        repairs.issue_registry_id(repairs.CONFLICT, automation_id)
    ]
    assert state.attributes["last_reconcile"] == reconciled
    assert state.state == "ok"


async def test_health_stops_following_when_the_entry_unloads(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    monitor: health.HealthMonitor = init_integration.runtime_data.health

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    repairs.async_sync_issue(hass, repairs.BLUEPRINT_MODIFIED, present=True)
    await hass.async_block_till_done()

    assert monitor.report.issues == ()
