"""The integration's actions (TECH_SPEC 4.6; PRD 5.5, FR-R11 to FR-R15 and 10.4).

`skip_next`, `pause`, `resume`, `enable` and `disable` take a native target (devices,
entities, areas, floors and labels); `pause` also takes `until` or `for`, exactly one.
`maintenance` takes one of the maintenance actions and an optional dry run.

The actions are registered in `async_setup` (quality rule `action-setup`), so they exist
while no entry is loaded, and a call then raises the translated `not_loaded`. Each
handler is one call into the loaded entry's RoutineManager or into `maintenance.async_run`
(PRD P16): the manager resolves the target, applies D18 to D21, lists the targets without
a routine as ignored and raises `no_routine_targets` when none has one.

Responses are optional (`SupportsResponse.OPTIONAL`): `results` and `ignored` for the
routine actions, the maintenance report for `maintenance`, with datetimes as ISO strings.
`action_response` and `maintenance_response` are the one serialization of those results,
so other callers (the WebSocket commands) can answer in the same shape.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from typing import Any, Final

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import VolSchemaType
from homeassistant.util import dt as dt_util
from homeassistant.util.json import JsonObjectType
import probatio as vol

from . import maintenance
from .const import DOMAIN
from .maintenance import MaintenanceAction, MaintenanceReport
from .manager import ActionName, ActionResult, ActionResults, IgnoredTarget, RoutineManager
from .models import Occurrence

# Field names (services.yaml).
ATTR_UNTIL: Final = "until"
ATTR_FOR: Final = "for"
ATTR_ACTION: Final = "action"
ATTR_DRY_RUN: Final = "dry_run"

# Action names, in services.yaml order.
SERVICE_MAINTENANCE: Final = "maintenance"
ROUTINE_ACTIONS: Final[tuple[ActionName, ...]] = (
    "skip_next",
    "pause",
    "resume",
    "enable",
    "disable",
)
SERVICES: Final[tuple[str, ...]] = (*ROUTINE_ACTIONS, SERVICE_MAINTENANCE)

# The translation key a call gets while no entry is loaded.
NOT_LOADED: Final = "not_loaded"

# A native target: `entity_id`, `device_id`, `area_id`, `floor_id`, `label_id`.
TARGET_SCHEMA: Final = vol.Schema(cv.TARGET_SERVICE_FIELDS)

# `until` is read as local time when it carries no offset (the datetime selector sends
# none); `for` is a positive duration.
PAUSE_SCHEMA: Final = vol.All(
    vol.Schema(
        {
            **cv.TARGET_SERVICE_FIELDS,
            vol.Optional(ATTR_UNTIL): vol.All(cv.datetime, dt_util.as_local),
            vol.Optional(ATTR_FOR): cv.positive_time_period,
        }
    ),
    vol.ExactlyOne(ATTR_UNTIL, ATTR_FOR),
)

MAINTENANCE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_ACTION): vol.Coerce(MaintenanceAction),
        vol.Optional(ATTR_DRY_RUN, default=False): cv.boolean,
    }
)

_SCHEMAS: Final[Mapping[ActionName, VolSchemaType]] = {
    "skip_next": TARGET_SCHEMA,
    "pause": PAUSE_SCHEMA,
    "resume": TARGET_SCHEMA,
    "enable": TARGET_SCHEMA,
    "disable": TARGET_SCHEMA,
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register every action of the integration (quality rule `action-setup`)."""
    for action in ROUTINE_ACTIONS:
        hass.services.async_register(
            DOMAIN,
            action,
            _routine_handler(action),
            schema=_SCHEMAS[action],
            supports_response=SupportsResponse.OPTIONAL,
        )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MAINTENANCE,
        _async_maintenance,
        schema=MAINTENANCE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


@callback
def _manager(hass: HomeAssistant) -> RoutineManager:
    """Return the loaded entry's manager, or raise the translated `not_loaded`."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key=NOT_LOADED)
    manager: RoutineManager = entries[0].runtime_data.manager
    return manager


def _routine_handler(
    action: ActionName,
) -> Callable[[ServiceCall], Coroutine[Any, Any, ServiceResponse]]:
    """Return the handler of one routine action: the manager runs it over the target."""

    async def async_handle(call: ServiceCall) -> ServiceResponse:
        return action_response(
            await _manager(call.hass).async_run_action(
                action,
                call.data,
                until=call.data.get(ATTR_UNTIL),
                duration=call.data.get(ATTR_FOR),
            )
        )

    return async_handle


async def _async_maintenance(call: ServiceCall) -> ServiceResponse:
    """Run one maintenance action on the loaded entry's manager."""
    return maintenance_response(
        await maintenance.async_run(
            call.hass, _manager(call.hass), call.data[ATTR_ACTION], call.data[ATTR_DRY_RUN]
        )
    )


# --------------------------------------------------------------------------------------
# Responses (TECH_SPEC 4.6): the result dataclasses as plain JSON
# --------------------------------------------------------------------------------------


def action_response(done: ActionResults) -> JsonObjectType:
    """Return `results` (one per routine device) and `ignored` (every target left out)."""
    return {
        "results": [_result(result) for result in done.results],
        "ignored": [_ignored(item) for item in done.ignored],
    }


def maintenance_response(report: MaintenanceReport) -> JsonObjectType:
    """Return what a maintenance action changed, or with a dry run, what it would change."""
    return {
        "action": str(report.action),
        "changed": list(report.changed),
        "would_change": list(report.would_change),
    }


def _result(result: ActionResult) -> JsonObjectType:
    return {
        "device_id": result.device_id,
        "device_name": result.device_name,
        "action": result.action,
        "paused_until": result.paused_until.isoformat() if result.paused_until else None,
        "skipped_action": _occurrence(result.skipped_action),
        "next_action": _occurrence(result.next_action),
    }


def _occurrence(occurrence: Occurrence | None) -> JsonObjectType | None:
    if occurrence is None:
        return None
    return {
        "at": occurrence.at.isoformat(),
        "verb": str(occurrence.verb) if occurrence.verb else None,
    }


def _ignored(item: IgnoredTarget) -> JsonObjectType:
    return {"target": item.target, "kind": item.kind, "reason": item.reason}
