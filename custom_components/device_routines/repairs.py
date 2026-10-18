"""Repairs issues (TECH_SPEC 4.8).

Rule: self heal first, raise only when a person must decide, and make every issue fixable
or point at the exact place to act. The hub Problem sensor lists what is open here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from homeassistant.const import __version__ as HA_VERSION  # noqa: N812
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .ha_adapter import AdapterReport

ADAPTER_INCOMPATIBLE: Final = "adapter_incompatible"
BLUEPRINT_MODIFIED: Final = "blueprint_modified"
INVALID_INPUTS: Final = "invalid_inputs"
DETACHED_ROUTINE: Final = "detached_routine"
SCHEDULE_BLOCKS_NEEDED: Final = "schedule_blocks_needed"
WRITE_CONFLICT: Final = "write_conflict"
AUTOMATION_LOAD_FAILED: Final = "automation_load_failed"
CONFLICT: Final = "conflict"

# The Build A catalog (TECH_SPEC 4.8) and which issues offer a fix flow. Lane 11 of Build A
# adds the flows; until then a fixable issue is raised the same way and only listed.
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
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR if issue_id in _ERRORS else ir.IssueSeverity.WARNING,
        translation_key=issue_id,
        translation_placeholders=dict(placeholders or {}),
        data={"issue_id": issue_id, "subject": subject} if subject is not None else None,
    )


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
