"""Repairs issues (TECH_SPEC 4.8). Phase 1 raises `adapter_incompatible` only.

Rule: self heal first, raise only when a person must decide, and make every issue fixable
or point at the exact place to act. The hub Problem sensor lists what is open here.
"""

from __future__ import annotations

from typing import Final

from homeassistant.const import __version__ as HA_VERSION  # noqa: N812
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .ha_adapter import AdapterReport

ADAPTER_INCOMPATIBLE: Final = "adapter_incompatible"


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
