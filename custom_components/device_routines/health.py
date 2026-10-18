"""What the hub Health sensor reports: the running commit, the channel, the self checks.

`tools/ha_deploy.py` writes `.deployed` next to the code it deployed, and the Health sensor
reports what is in it so the deploy loop can end by comparing the `commit` attribute with
the sha that was pushed (PRD 11.2). Most installs never have that file: a HACS install is a
released archive the deploy tool never touched, and a missing file is what a normal install
looks like, not a fault. A missing, unreadable or half written file all read the same way
here: no deployment record, and the integration is otherwise well.

The self checks come from the RoutineManager (`health_inputs`, TECH_SPEC 10.3), which runs
them at every reconcile: whether the blueprint is the shipped one, how many owned
automations exist and how many loaded, the open Repairs issues and the adapter report. The
state follows three rules, the first that applies winning:

- `error` while the adapter is incompatible (a capability the routines need is missing
  on this core: editing is off, routines keep running);
- `degraded` while the blueprint was edited by hand, an owned automation does not load
  (fewer loaded than owned), or an `automation_load_failed` issue is open. The manager
  counts an automation the core is reloading as loaded until it is back or the reload
  ends, so a settings write never reads as a failed load (live finding F4);
- `ok` otherwise. Issues a person settles in Repairs (an invalid form edit, a detached
  routine, a conflict) are the routine's, not the integration's, and do not degrade it.

The file readers are plain functions over paths so they can be tested without a running
Home Assistant; `async_collect` reads them once in the executor, and `HealthMonitor` keeps
the report current afterwards from the manager's events and this integration's issues.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from functools import partial
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.issue_registry import EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED

from .const import (
    CHANNEL_DEV,
    CHANNEL_HACS,
    CHANNEL_UNKNOWN,
    DOMAIN,
    HEALTH_DEGRADED,
    HEALTH_ERROR,
    HEALTH_OK,
)
from .repairs import AUTOMATION_LOAD_FAILED

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .manager import HealthInputs, ManagerEvent

_LOGGER = logging.getLogger(__name__)

# Where the deploy tool writes its marker: alongside the code it deployed. Module level so
# a test can point it somewhere harmless.
COMPONENT_DIR: Final = Path(__file__).parent
DEPLOYED_FILE_NAME: Final = ".deployed"

# HACS records what it installed here. Read only, and only to label the channel; nothing
# in this integration depends on the answer.
HACS_STORE: Final = Path(".storage") / "hacs.repositories"

# The `blueprint_status` attribute (TECH_SPEC 10.3). The manager calls the shipped file
# `shipped`; a missing file is reinstalled by the same check that would report it, so
# the attribute reads null only until the first reconcile has looked, or while the
# adapter is incompatible and the reconcile stops before the blueprint step.
BLUEPRINT_OK: Final = "ok"
BLUEPRINT_MODIFIED: Final = "modified"
_BLUEPRINT_STATUSES: Final[dict[str, str]] = {
    "shipped": BLUEPRINT_OK,
    "modified": BLUEPRINT_MODIFIED,
}


@dataclass(frozen=True, slots=True)
class Deployment:
    """The commit that is running, as the deploy tool recorded it.

    `changed_files` is a count: the list is diagnostics material, not an attribute.
    """

    commit: str | None
    branch: str | None
    deployed_at: str | None
    previous_commit: str | None
    changed_files: int
    rollback_of: str | None


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The Health sensor's state and attributes (TECH_SPEC 10.3)."""

    state: str
    version: str
    commit: str | None
    branch: str | None
    deployed_at: str | None
    channel: str
    ha_version: str
    blueprint_schema: int | None
    blueprint_status: str | None
    owned_count: int
    loaded_count: int
    issues: tuple[str, ...]
    last_reconcile: str | None

    def as_attributes(self) -> dict[str, Any]:
        """Return the attributes the sensor exposes, with plain lists for JSON."""
        attributes = asdict(self)
        del attributes["state"]
        attributes["issues"] = list(self.issues)
        return attributes


class HealthSource(Protocol):
    """What Health reads from the RoutineManager."""

    def health_inputs(self) -> HealthInputs:
        """Return the self check results."""

    def async_add_listener(self, update: Callable[[ManagerEvent], None]) -> CALLBACK_TYPE:
        """Call `update` with every manager event; return the unsubscriber."""


def _text(value: object) -> str | None:
    """Return a string field, or None when it is missing or is not one."""
    return value if isinstance(value, str) else None


def read_deployment(component_dir: Path) -> Deployment | None:
    """Return what `.deployed` says, or None when there is nothing to say. Blocking."""
    path = component_dir / DEPLOYED_FILE_NAME
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError, ValueError:
        _LOGGER.warning(
            "%s exists but could not be read as JSON, so no deployment record is reported."
            " The running code is unaffected: this file only describes how it got here",
            path,
        )
        return None
    if not isinstance(data, dict):
        return None
    changed = data.get("changed_files")
    return Deployment(
        commit=_text(data.get("commit")),
        branch=_text(data.get("branch")),
        deployed_at=_text(data.get("deployed_at")),
        previous_commit=_text(data.get("previous_commit")),
        changed_files=len(changed) if isinstance(changed, list) else 0,
        rollback_of=_text(data.get("rollback_of")),
    )


def _hacs_lists_domain(config_dir: Path) -> bool:
    """Report whether the HACS store says it installed this integration. Blocking."""
    try:
        data: Any = json.loads((config_dir / HACS_STORE).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    repositories = data.get("data") if isinstance(data, dict) else None
    if not isinstance(repositories, dict):
        return False
    return any(
        isinstance(entry, dict) and entry.get("domain") == DOMAIN and bool(entry.get("installed"))
        for entry in repositories.values()
    )


def detect_channel(config_dir: Path, *, has_deployment: bool) -> str:
    """Return `dev`, `hacs` or `unknown` (TECH_SPEC 4.10). Blocking."""
    if has_deployment:
        return CHANNEL_DEV
    if _hacs_lists_domain(config_dir):
        return CHANNEL_HACS
    return CHANNEL_UNKNOWN


def _load_failed(issue_id: str) -> bool:
    """Tell whether a registry issue id is an `automation_load_failed` issue (L41)."""
    return issue_id == AUTOMATION_LOAD_FAILED or issue_id.startswith(f"{AUTOMATION_LOAD_FAILED}_")


def health_state(inputs: HealthInputs) -> str:
    """Return `ok`, `degraded` or `error` by the rules of the module docstring."""
    if inputs.adapter_failed:
        return HEALTH_ERROR
    if (
        inputs.blueprint_status == "modified"
        or inputs.loaded_count < inputs.owned_count
        or any(_load_failed(issue_id) for issue_id in inputs.issues)
    ):
        return HEALTH_DEGRADED
    return HEALTH_OK


def _routine_fields(inputs: HealthInputs) -> Mapping[str, Any]:
    """Return the report fields the manager's inputs decide."""
    status = inputs.blueprint_status
    return {
        "state": health_state(inputs),
        "blueprint_schema": inputs.blueprint_schema,
        "blueprint_status": None if status is None else _BLUEPRINT_STATUSES.get(status, status),
        "owned_count": inputs.owned_count,
        "loaded_count": inputs.loaded_count,
        "issues": tuple(inputs.issues),
        "last_reconcile": inputs.last_reconcile.isoformat() if inputs.last_reconcile else None,
    }


def build_report(
    *,
    deployment: Deployment | None,
    channel: str,
    version: str,
    ha_version: str,
    inputs: HealthInputs,
) -> HealthReport:
    """Assemble the report from the deploy record and the manager's self checks."""
    return HealthReport(
        version=version,
        commit=deployment.commit if deployment else None,
        branch=deployment.branch if deployment else None,
        deployed_at=deployment.deployed_at if deployment else None,
        channel=channel,
        ha_version=ha_version,
        **_routine_fields(inputs),
    )


async def async_collect(hass: HomeAssistant, version: str, manager: HealthSource) -> HealthReport:
    """Read the marker and the channel in the executor and build the report."""
    deployment = await hass.async_add_executor_job(read_deployment, COMPONENT_DIR)
    channel = await hass.async_add_executor_job(
        partial(detect_channel, Path(hass.config.config_dir), has_deployment=deployment is not None)
    )
    from homeassistant.const import __version__ as ha_version  # noqa: PLC0415

    return build_report(
        deployment=deployment,
        channel=channel,
        version=version,
        ha_version=ha_version,
        inputs=manager.health_inputs(),
    )


@callback
def _ours(event_data: Mapping[str, Any]) -> bool:
    return bool(event_data.get("domain") == DOMAIN)


class HealthMonitor:
    """Keeps the Health report current and tells the Health sensor when it changes.

    The deploy record is read once, at setup: a new one needs a restart to load anyway.
    The self checks are read again from the manager on every manager event (a reconcile
    ends with `health_changed`, a routine change can load or lose an automation) and on
    every change to this integration's Repairs issues, so `issues` stays current between
    reconciles. Listeners hear only a report that changed.
    """

    def __init__(self, hass: HomeAssistant, report: HealthReport, manager: HealthSource) -> None:
        """Hold the first report; nothing is followed before `async_start`."""
        self._hass = hass
        self._report = report
        self._manager = manager
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []

    @property
    def report(self) -> HealthReport:
        """The current report."""
        return self._report

    @callback
    def async_start(self) -> None:
        """Follow the manager and the issue registry."""
        self._unsubscribe = [
            self._manager.async_add_listener(self._manager_event),
            self._hass.bus.async_listen(
                EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED, self._issues_changed, event_filter=_ours
            ),
        ]

    @callback
    def async_stop(self) -> None:
        """Stop following; the last report stays readable."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Call `update` whenever the report changes; return the unsubscriber."""
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    @callback
    def async_refresh(self) -> None:
        """Read the self checks again and tell the listeners if the report changed."""
        report = replace(self._report, **_routine_fields(self._manager.health_inputs()))
        if report == self._report:
            return
        self._report = report
        for update in list(self._listeners):
            update()

    @callback
    def _manager_event(self, _event: ManagerEvent) -> None:
        self.async_refresh()

    @callback
    def _issues_changed(self, _event: Event[Any]) -> None:
        self.async_refresh()


async def async_start_monitor(
    hass: HomeAssistant, version: str, manager: HealthSource
) -> HealthMonitor:
    """Collect the first report and start following; the caller stops it on unload."""
    monitor = HealthMonitor(hass, await async_collect(hass, version, manager), manager)
    monitor.async_start()
    return monitor
