"""Raising and clearing catalog issues (TECH_SPEC 4.8); the fix flows are lane 11's."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import pytest

from custom_components.device_routines import repairs
from custom_components.device_routines.const import DOMAIN

STRINGS = Path(repairs.__file__).parent / "strings.json"


def test_every_catalog_issue_has_a_title() -> None:
    issues = json.loads(STRINGS.read_text(encoding="utf-8"))["issues"]
    assert set(issues) >= repairs.CATALOG
    assert all(issues[key]["title"] for key in repairs.CATALOG)
    assert repairs.FIXABLE < repairs.CATALOG


def test_issue_registry_id() -> None:
    assert repairs.issue_registry_id(repairs.BLUEPRINT_MODIFIED) == "blueprint_modified"
    assert (
        repairs.issue_registry_id(repairs.INVALID_INPUTS, "device_routines_0123456789ab")
        == "invalid_inputs_device_routines_0123456789ab"
    )


async def test_raise_and_clear_a_per_routine_issue(hass: HomeAssistant) -> None:
    subject = "device_routines_0123456789ab"
    placeholders = {"device": "Living room fan", "automation": "Routine: Living room fan"}
    for _ in range(2):
        repairs.async_sync_issue(
            hass, repairs.INVALID_INPUTS, True, placeholders | {"reason": "x"}, subject=subject
        )
    other = "device_routines_ba9876543210"
    repairs.async_sync_issue(hass, repairs.INVALID_INPUTS, True, placeholders, subject=other)
    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"invalid_inputs_{subject}")
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_key == "invalid_inputs"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.data == {"issue_id": "invalid_inputs", "subject": subject}
    assert repairs.open_issue_ids(hass) == [f"invalid_inputs_{subject}", f"invalid_inputs_{other}"]

    for _ in range(2):
        repairs.async_sync_issue(hass, repairs.INVALID_INPUTS, False, subject=subject)
    assert repairs.open_issue_ids(hass) == [f"invalid_inputs_{other}"]


async def test_global_issues_and_severity(hass: HomeAssistant) -> None:
    repairs.async_sync_issue(hass, repairs.SCHEDULE_BLOCKS_NEEDED, True)
    repairs.async_sync_issue(hass, repairs.AUTOMATION_LOAD_FAILED, True, subject="a")
    registry = ir.async_get(hass)
    blocks = registry.async_get_issue(DOMAIN, "schedule_blocks_needed")
    assert blocks is not None
    assert not blocks.is_fixable
    assert blocks.data is None
    failed = registry.async_get_issue(DOMAIN, "automation_load_failed_a")
    assert failed is not None
    assert failed.severity is ir.IssueSeverity.ERROR


async def test_an_unknown_issue_is_refused(hass: HomeAssistant) -> None:
    with pytest.raises(ValueError, match="not in the Repairs catalog"):
        repairs.async_sync_issue(hass, "made_up", True)
