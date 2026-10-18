"""Repairs issues and their fix flows (TECH_SPEC 4.8).

Rule: self heal first, raise only when a person must decide, and make every issue fixable
or point at the exact place to act. The hub Problem sensor lists what is open here.

The manager raises and clears the issues in their situations (decision L41); the
`conflict` issue follows the Schedule summary (`summary.async_sync_conflict_issues`).
Every fixable issue has a fix flow with one confirm step that makes exactly one call into
the service layer and finishes (PRD P16): the flow decides nothing itself. A call that
fails, or leaves the issue open because the situation did not end, aborts with a
translated reason, so the issue stays for the next try.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
import logging
from typing import Final, Protocol

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.const import __version__ as HA_VERSION  # noqa: N812
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import probatio as vol

from . import maintenance
from .const import DOMAIN
from .ha_adapter import AdapterError, AdapterReport
from .models import RoutineView

_LOGGER = logging.getLogger(__name__)

ADAPTER_INCOMPATIBLE: Final = "adapter_incompatible"
BLUEPRINT_MODIFIED: Final = "blueprint_modified"
INVALID_INPUTS: Final = "invalid_inputs"
DETACHED_ROUTINE: Final = "detached_routine"
SCHEDULE_BLOCKS_NEEDED: Final = "schedule_blocks_needed"
WRITE_CONFLICT: Final = "write_conflict"
AUTOMATION_LOAD_FAILED: Final = "automation_load_failed"
CONFLICT: Final = "conflict"

# The Build A catalog (TECH_SPEC 4.8) and which issues offer a fix flow.
CATALOG: Final = frozenset(
    {
        ADAPTER_INCOMPATIBLE,
        BLUEPRINT_MODIFIED,
        INVALID_INPUTS,
        DETACHED_ROUTINE,
        SCHEDULE_BLOCKS_NEEDED,
        WRITE_CONFLICT,
        AUTOMATION_LOAD_FAILED,
        CONFLICT,
    }
)
FIXABLE: Final = frozenset(
    {BLUEPRINT_MODIFIED, INVALID_INPUTS, DETACHED_ROUTINE, WRITE_CONFLICT, AUTOMATION_LOAD_FAILED}
)
_ERRORS: Final = frozenset({ADAPTER_INCOMPATIBLE, AUTOMATION_LOAD_FAILED})

# Where a person acts on an issue that has no fix flow. A `homeassistant://` link opens a
# page of the Home Assistant frontend, as core's own issues do.
TROUBLESHOOTING_URL: Final = (
    "https://github.com/jayanty/ha-device-routines/blob/main/docs/user-guide.md#troubleshooting"
)
HELPERS_URL: Final = "homeassistant://config/helpers"
AUTOMATIONS_URL: Final = "homeassistant://config/automation/dashboard"
_LEARN_MORE: Final[Mapping[str, str]] = {
    ADAPTER_INCOMPATIBLE: TROUBLESHOOTING_URL,
    SCHEDULE_BLOCKS_NEEDED: HELPERS_URL,
    CONFLICT: AUTOMATIONS_URL,
}
# Issues whose situation shows only once, when it happens (a schedule recreated empty),
# so the issue outlives a restart until it is cleared. The next reconcile or sync finds
# every other situation again and raises its issue anew.
_PERSISTENT: Final = frozenset({SCHEDULE_BLOCKS_NEEDED})

# Why a fix flow ends without fixing, besides the manager's own translation keys
# (`unknown_routine`, `no_valid_settings`).
ABORT_NOT_LOADED: Final = "not_loaded"
ABORT_NOT_FIXED: Final = "not_fixed"
STEP_CONFIRM: Final = "confirm"
_UNKNOWN_ROUTINE: Final = "unknown_routine"


def issue_registry_id(issue_id: str, subject: str | None = None) -> str:
    """Return the registry id of an issue: the catalog id, plus its subject when it has one.

    Per routine issues carry the routine's automation id as their subject, so two routines
    can each have an `invalid_inputs` issue open at the same time.
    """
    return issue_id if subject is None else f"{issue_id}_{subject}"


@callback
def async_sync_issue(
    hass: HomeAssistant,
    issue_id: str,
    present: bool,
    placeholders: Mapping[str, str] | None = None,
    *,
    subject: str | None = None,
) -> None:
    """Raise a catalog issue while `present`, clear it otherwise; idempotent both ways."""
    if issue_id not in CATALOG:
        raise ValueError(f"{issue_id} is not in the Repairs catalog")
    registry_id = issue_registry_id(issue_id, subject)
    if not present:
        ir.async_delete_issue(hass, DOMAIN, registry_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        registry_id,
        is_fixable=issue_id in FIXABLE,
        is_persistent=issue_id in _PERSISTENT,
        learn_more_url=_LEARN_MORE.get(issue_id),
        severity=ir.IssueSeverity.ERROR if issue_id in _ERRORS else ir.IssueSeverity.WARNING,
        translation_key=issue_id,
        translation_placeholders=dict(placeholders or {}),
        data={"issue_id": issue_id, "subject": subject} if subject is not None else None,
    )


@callback
def async_sync_issues(
    hass: HomeAssistant, issue_id: str, wanted: Mapping[str, Mapping[str, str]]
) -> None:
    """Make the open issues of one catalog id exactly `wanted`, subject to placeholders.

    Each wanted subject is raised (or kept, its placeholders refreshed); every other issue
    of this catalog id is cleared, whoever raised it and whenever.
    """
    keep = {issue_registry_id(issue_id, subject) for subject in wanted}
    stale = [
        registry_id
        for (domain, registry_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.translation_key == issue_id and registry_id not in keep
    ]
    for registry_id in stale:
        ir.async_delete_issue(hass, DOMAIN, registry_id)
    for subject, placeholders in wanted.items():
        async_sync_issue(hass, issue_id, present=True, placeholders=placeholders, subject=subject)


@callback
def async_sync_adapter_issue(hass: HomeAssistant, report: AdapterReport) -> None:
    """Raise `adapter_incompatible` while a capability fails; clear it once all work."""
    if report.ok:
        ir.async_delete_issue(hass, DOMAIN, ADAPTER_INCOMPATIBLE)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        ADAPTER_INCOMPATIBLE,
        is_fixable=False,
        is_persistent=False,
        learn_more_url=TROUBLESHOOTING_URL,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ADAPTER_INCOMPATIBLE,
        translation_placeholders={
            "capabilities": ", ".join(report.failed),
            "ha_version": HA_VERSION,
        },
    )


@callback
def open_issue_ids(hass: HomeAssistant) -> list[str]:
    """Return the ids of this integration's open, not ignored, Repairs issues."""
    return sorted(
        issue_id
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.active and issue.dismissed_version is None
    )


# --------------------------------------------------------------------------------------
# Fix flows
# --------------------------------------------------------------------------------------


class FixTarget(maintenance.MaintenanceTarget, Protocol):
    """The manager's fix methods (plan Section 4.2) as the fix flows call them."""

    async def async_restore_last_valid(self, automation_id: str) -> None:
        """Write the last valid inputs back and turn the routine on."""

    async def async_regenerate(self, automation_id: str) -> None:
        """Write the last valid inputs again and check that the automation loads."""

    async def async_retry_write(self, automation_id: str) -> None:
        """Write the routine's settings again now."""

    async def async_create_new_routine(self, device_id: str) -> None:
        """Give a device whose routine was detached a new routine under a new id."""

    def list(self) -> tuple[RoutineView, ...]:
        """Return every routine the manager knows."""


type _Fix = Callable[[HomeAssistant, FixTarget, str], Awaitable[None]]


async def _reinstall_blueprint(hass: HomeAssistant, manager: FixTarget, _subject: str) -> None:
    """`blueprint_modified`: put the shipped file back; the automations using it reload."""
    await maintenance.async_run(
        hass, manager, maintenance.MaintenanceAction.REINSTALL_BLUEPRINT, dry_run=False
    )


async def _restore_last_valid(_hass: HomeAssistant, manager: FixTarget, subject: str) -> None:
    """`invalid_inputs`: restore `last_valid_inputs`."""
    await manager.async_restore_last_valid(subject)


async def _create_new_routine(_hass: HomeAssistant, manager: FixTarget, subject: str) -> None:
    """`detached_routine`: a new routine for the device; the detached one is untouched."""
    device_id = next(
        (view.device_id for view in manager.list() if view.automation_id == subject), None
    )
    if device_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=_UNKNOWN_ROUTINE,
            translation_placeholders={"automation": subject},
        )
    await manager.async_create_new_routine(device_id)


async def _retry_write(_hass: HomeAssistant, manager: FixTarget, subject: str) -> None:
    """`write_conflict`: retry the write."""
    await manager.async_retry_write(subject)


async def _regenerate(_hass: HomeAssistant, manager: FixTarget, subject: str) -> None:
    """`automation_load_failed`: regenerate from `last_valid_inputs`."""
    await manager.async_regenerate(subject)


_FIXES: Final[Mapping[str, _Fix]] = {
    BLUEPRINT_MODIFIED: _reinstall_blueprint,
    INVALID_INPUTS: _restore_last_valid,
    DETACHED_ROUTINE: _create_new_routine,
    WRITE_CONFLICT: _retry_write,
    AUTOMATION_LOAD_FAILED: _regenerate,
}
# A step ended the situation only when the manager cleared the issue, except a blueprint
# reinstall: once it returns, the shipped file is in place, even when it already was.
_CLEARED_BY_THE_MANAGER: Final = frozenset(_FIXES) - {BLUEPRINT_MODIFIED}


class FixFlow(RepairsFlow):
    """One confirm step, one call into the service layer, then done or a translated abort."""

    def __init__(self, catalog_id: str, subject: str | None) -> None:
        """Remember which catalog issue this is and which routine it is about."""
        self._catalog_id = catalog_id
        self._subject = subject or ""

    async def async_step_init(
        self,
        user_input: dict[str, str] | None = None,  # noqa: ARG002  # the core's signature
    ) -> RepairsFlowResult:
        """Show the confirm step; the core passes the issue id, which the flow knows."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Explain the one step; on submit, take it."""
        placeholders = self._placeholders()
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_CONFIRM,
                data_schema=vol.Schema({}),
                description_placeholders=placeholders,
            )
        manager = _loaded_manager(self.hass)
        if manager is None:
            return self.async_abort(reason=ABORT_NOT_LOADED, description_placeholders=placeholders)
        try:
            await _FIXES[self._catalog_id](self.hass, manager, self._subject)
        except ServiceValidationError as err:
            return self.async_abort(
                reason=err.translation_key or ABORT_NOT_FIXED,
                description_placeholders={**placeholders, **(err.translation_placeholders or {})},
            )
        except HomeAssistantError, AdapterError, OSError:
            _LOGGER.warning("The fix for %s failed", self.issue_id, exc_info=True)
            return self.async_abort(reason=ABORT_NOT_FIXED, description_placeholders=placeholders)
        if self._catalog_id in _CLEARED_BY_THE_MANAGER and self._issue() is not None:
            return self.async_abort(reason=ABORT_NOT_FIXED, description_placeholders=placeholders)
        return self.async_create_entry(data={})

    def _issue(self) -> ir.IssueEntry | None:
        return ir.async_get(self.hass).async_get_issue(DOMAIN, self.issue_id)

    def _placeholders(self) -> dict[str, str]:
        issue = self._issue()
        return dict(issue.translation_placeholders or {}) if issue is not None else {}


def _loaded_manager(hass: HomeAssistant) -> FixTarget | None:
    """Return the manager of the loaded config entry, or None while none is loaded."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        return None
    manager: FixTarget = entries[0].runtime_data.manager
    return manager


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Return the fix flow of a fixable issue (the Repairs platform entry point).

    `issue_id` is the registry id. A per routine issue's `data` names its catalog id and
    its subject, the routine's automation id (decision L41); a global issue's registry id
    is its catalog id.
    """
    catalog_id = str(data["issue_id"]) if data and "issue_id" in data else issue_id
    if catalog_id not in _FIXES:
        raise ValueError(f"{issue_id} has no fix flow")
    subject = data.get("subject") if data else None
    return FixFlow(catalog_id, None if subject is None else str(subject))
