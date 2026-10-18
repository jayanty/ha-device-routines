"""The WebSocket API: the console contract (TECH_SPEC 4.7, PRD 7.5, decision D31).

Every command is a thin caller of the loaded entry's RoutineManager, its
SummaryCoordinator, `settings` or `maintenance` (PRD P16): it checks the shape of the
request, calls one method and returns that method's result as JSON. Payloads are flat and
mirror the service layer: a dataclass serializes with `dataclasses.asdict`, datetimes and
times as ISO 8601 strings, enums as their values and a set of weekdays as a list from
Monday to Sunday. `docs/api.md` documents every command with examples.

Errors. A refusal of the service layer (a `ServiceValidationError`, or the `Problem` a
patch or a settings change returned) is an error whose `code` is its translation key,
with `translation_domain`, `translation_key` and `translation_placeholders`; a problem
about one setting names it in the `setting` placeholder. A request of the wrong shape
gets the core's `invalid_format`, and a writing command from a user who is not an
administrator the core's `unauthorized`.

Reloads. Storing new global settings reloads the config entry, which replaces the manager
(as the options flow does). Commands look the loaded entry up at every call. Every setup
calls `async_register`, which registers the commands again (the core replaces them in
place) and tells every live subscription to listen to the new manager before it starts;
a subscription pushes `settings_changed` when the settings the entry runs with differ
from those it ran with before. A subscription made while no entry is set up waits for
the next one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, time
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.const import (
    ERR_HOME_ASSISTANT_ERROR,
    WebSocketCommandHandler,
)
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.util import dt as dt_util
import probatio as vol

from . import maintenance
from .const import DOMAIN
from .maintenance import MaintenanceAction
from .manager import ManagerEvent, RoutineManager
from .models import Problem
from .settings import GlobalSettings, from_options, validate

if TYPE_CHECKING:
    from . import DeviceRoutinesConfigEntry

# Sent by every setup once the entry's runtime data exists: subscriptions attach to it.
SIGNAL_ATTACH: Final = f"{DOMAIN}_websocket_attach"

ACTIONS: Final = ("skip_next", "pause", "resume", "enable", "disable")
OPS: Final = ("list", "suggest", "in", "out")
# PRD 4.4 and D24: accepted by the schema, refused until a house wide pause exists.
TARGET_ALL: Final = "all"

type Handler = Callable[[HomeAssistant, ActiveConnection, dict[str, Any]], Awaitable[None]]


# --------------------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------------------


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every command and attach live subscriptions to the entry being set up.

    Called from `async_setup_entry` after the runtime data exists and before the manager
    starts, at every setup; registering again replaces the commands in place.
    """
    for command in COMMANDS:
        async_register_command(hass, command)
    async_dispatcher_send(hass, SIGNAL_ATTACH)


# --------------------------------------------------------------------------------------
# Plumbing: the loaded entry, refusals and JSON
# --------------------------------------------------------------------------------------


def _loaded(hass: HomeAssistant) -> DeviceRoutinesConfigEntry:
    """Return the loaded config entry, or refuse with `not_loaded`."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        raise _refused("not_loaded")
    entry: DeviceRoutinesConfigEntry = entries[0]
    return entry


def _manager(hass: HomeAssistant) -> RoutineManager:
    return _loaded(hass).runtime_data.manager


def _with_runtime(hass: HomeAssistant) -> DeviceRoutinesConfigEntry | None:
    """Return the entry whose runtime data exists (loaded or being set up), or None."""
    return next(
        (
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if getattr(entry, "runtime_data", None) is not None
        ),
        None,
    )


def _refused(key: str, placeholders: Mapping[str, str] | None = None) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=dict(placeholders or {}),
    )


def _problem(problem: Problem) -> ServiceValidationError:
    """Turn a returned problem into the refusal it stands for, naming its setting."""
    return _refused(problem.translation_key, {"setting": problem.key, **problem.placeholders})


def _device_name(hass: HomeAssistant, device_id: str) -> str:
    device = dr.async_get(hass).async_get(device_id)
    return (device.name_by_user or device.name or device_id) if device else device_id


def _refusals(func: Handler) -> Handler:
    """Answer a refusal of the service layer with its translation key and placeholders.

    The core would answer it too, as `home_assistant_error`, and log it as an error; a
    refused setting is an answer, not a fault.
    """

    @wraps(func)
    async def handle(
        hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
    ) -> None:
        try:
            await func(hass, connection, msg)
        except ServiceValidationError as err:
            connection.send_error(
                msg["id"],
                err.translation_key or ERR_HOME_ASSISTANT_ERROR,
                str(err),
                translation_key=err.translation_key,
                translation_domain=err.translation_domain,
                translation_placeholders=err.translation_placeholders,
            )

    return handle


def _order(item: Any) -> tuple[int, str]:
    """Sort enum members in their declared order (Monday first), anything else by text."""
    return (list(type(item)).index(item), "") if isinstance(item, Enum) else (0, str(item))


def as_json(value: Any) -> Any:
    """Return a service layer value as JSON (see the module docstring)."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {str(key): as_json(item) for key, item in value.items()}
    if isinstance(value, frozenset | set):
        value = sorted(value, key=_order)
    if isinstance(value, list | tuple):
        return [as_json(item) for item in value]
    return _scalar(value)


def _scalar(value: Any) -> Any:
    """Return a single value as JSON: ISO 8601 for datetimes and times, enum values."""
    if isinstance(value, datetime | time):
        return value.isoformat()
    return value.value if isinstance(value, Enum) else value


def _aware(value: datetime) -> datetime:
    """Read a datetime without an offset as the instance's local time."""
    return value if value.tzinfo else value.replace(tzinfo=dt_util.get_default_time_zone())


# --------------------------------------------------------------------------------------
# Routines
# --------------------------------------------------------------------------------------


@websocket_command({vol.Required("type"): f"{DOMAIN}/routines/list"})
@async_response
@_refusals
async def ws_routines_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return every routine the manager knows, as `RoutineManager.list`."""
    connection.send_result(msg["id"], {"routines": as_json(_manager(hass).list())})


@websocket_command({vol.Required("type"): f"{DOMAIN}/routines/get", vol.Required("device_id"): str})
@async_response
@_refusals
async def ws_routines_get(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return one device's routine, as `RoutineManager.get`; refuse a device without one."""
    view = _manager(hass).get(msg["device_id"])
    if view is None:
        raise _refused("not_opted_in", {"device": _device_name(hass, msg["device_id"])})
    connection.send_result(msg["id"], as_json(view))


@require_admin
@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/routines/set",
        vol.Required("device_id"): str,
        vol.Required("settings"): dict,
    }
)
@async_response
@_refusals
async def ws_routines_set(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Apply a partial settings update, as `RoutineManager.async_update`, or refuse it."""
    result = await _manager(hass).async_update(msg["device_id"], msg["settings"])
    if result.problem is not None:
        raise _problem(result.problem)
    connection.send_result(msg["id"], as_json(result.view))


@require_admin
@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/routines/action",
        vol.Required("action"): vol.In(ACTIONS),
        vol.Required("target"): vol.Any(TARGET_ALL, vol.Schema(cv.TARGET_FIELDS)),
        vol.Optional("until"): vol.All(cv.datetime, _aware),
        vol.Optional("for"): cv.positive_time_period,
    }
)
@async_response
@_refusals
async def ws_routines_action(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Skip, pause, resume, enable or disable over a target, as the actions do."""
    if msg["target"] == TARGET_ALL:
        raise _refused("target_all_reserved")
    results = await _manager(hass).async_run_action(
        msg["action"], msg["target"], until=msg.get("until"), duration=msg.get("for")
    )
    connection.send_result(msg["id"], as_json(results))


@require_admin
@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/devices/opt",
        vol.Required("op"): vol.In(OPS),
        vol.Optional("device_id", default=list): vol.All(cv.ensure_list, [str]),
    }
)
@async_response
@_refusals
async def ws_devices_opt(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List eligible or suggested devices, or opt devices in or out one after another."""
    manager = _manager(hass)
    payload: dict[str, Any]
    if msg["op"] == "list":
        payload = {"devices": as_json(manager.eligible_devices())}
    elif msg["op"] == "suggest":
        payload = {"devices": as_json(manager.suggested_devices())}
    else:
        opt = manager.async_opt_in if msg["op"] == "in" else manager.async_opt_out
        payload = {"results": [as_json(await opt(device_id)) for device_id in msg["device_id"]]}
    connection.send_result(msg["id"], payload)


# --------------------------------------------------------------------------------------
# The schedule, the settings and maintenance
# --------------------------------------------------------------------------------------


@websocket_command(
    {vol.Required("type"): f"{DOMAIN}/schedule/today", vol.Optional("date"): cv.date}
)
@async_response
@_refusals
async def ws_schedule_today(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return a local day's planned actions (today by default) from the summary."""
    summary = _loaded(hass).runtime_data.summary
    day = msg.get("date") or dt_util.now().date()
    items = summary.day_schedule(day)
    connection.send_result(msg["id"], {"date": day.isoformat(), "items": as_json(items)})


@websocket_command({vol.Required("type"): f"{DOMAIN}/settings/get"})
@async_response
@_refusals
async def ws_settings_get(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the global settings as the entry options hold them."""
    connection.send_result(msg["id"], from_options(_loaded(hass).options).to_options())


@require_admin
@websocket_command({vol.Required("type"): f"{DOMAIN}/settings/set", vol.Required("settings"): dict})
@async_response
@_refusals
async def ws_settings_set(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Store a partial settings change as the options flow does; the entry reloads."""
    entry = _loaded(hass)
    if problems := validate(msg["settings"]):
        raise _problem(problems[0])
    options = {**entry.options, **msg["settings"]}
    changed = hass.config_entries.async_update_entry(entry, options=options)
    # The answer goes out first: the reload starts at once and subscriptions hear it.
    connection.send_result(msg["id"], from_options(options).to_options())
    if changed:
        hass.config_entries.async_schedule_reload(entry.entry_id)


@require_admin
@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/maintenance",
        vol.Required("action"): vol.In([action.value for action in MaintenanceAction]),
        vol.Optional("dry_run", default=False): bool,
    }
)
@async_response
@_refusals
async def ws_maintenance(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Run one maintenance action, as `maintenance.async_run`."""
    report = await maintenance.async_run(hass, _manager(hass), msg["action"], msg["dry_run"])
    connection.send_result(msg["id"], as_json(report))


# --------------------------------------------------------------------------------------
# Conversion offers (Build B lane 20: PRD FR-M1)
# --------------------------------------------------------------------------------------


@websocket_command({vol.Required("type"): f"{DOMAIN}/conversions/list"})
@async_response
@_refusals
async def ws_conversions_list(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the hand written automations a routine can replace exactly, from the summary."""
    summary = _loaded(hass).runtime_data.summary
    connection.send_result(msg["id"], {"offers": as_json(summary.conversion_offers())})


@require_admin
@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/conversions/convert",
        vol.Required("automation_entity_id"): cv.entity_domain("automation"),
    }
)
@async_response
@_refusals
async def ws_conversions_convert(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Convert one offered automation, as `RoutineManager.async_convert_automation`."""
    view = await _manager(hass).async_convert_automation(msg["automation_entity_id"])
    connection.send_result(msg["id"], as_json(view))


# --------------------------------------------------------------------------------------
# subscribe
# --------------------------------------------------------------------------------------


class _Subscription:
    """One `subscribe` command: manager events to the connection, across entry reloads."""

    def __init__(self, hass: HomeAssistant, connection: ActiveConnection, msg_id: int) -> None:
        self._hass = hass
        self._connection = connection
        self._msg_id = msg_id
        self._detach: CALLBACK_TYPE | None = None
        self._settings: GlobalSettings | None = None
        self._unsubscribe = async_dispatcher_connect(hass, SIGNAL_ATTACH, self._attach)
        self._attach()

    @callback
    def _attach(self) -> None:
        """Listen to the manager of the entry with runtime data; say if settings changed."""
        entry = _with_runtime(self._hass)
        if entry is None:
            return
        runtime = entry.runtime_data
        if self._detach is not None:
            self._detach()
        self._detach = runtime.manager.async_add_listener(self._heard)
        if self._settings is not None and runtime.settings != self._settings:
            self._heard(ManagerEvent("settings_changed", None))
        self._settings = runtime.settings

    @callback
    def _heard(self, event: ManagerEvent) -> None:
        self._connection.send_event(self._msg_id, as_json(event))

    @callback
    def async_stop(self) -> None:
        """Stop listening: the client unsubscribed or the connection closed."""
        self._unsubscribe()
        if self._detach is not None:
            self._detach()


@websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """Push `routine_changed`, `schedule_changed`, `settings_changed` and `health_changed`."""
    subscription = _Subscription(hass, connection, msg["id"])
    connection.subscriptions[msg["id"]] = subscription.async_stop
    connection.send_result(msg["id"])


COMMANDS: Final[tuple[WebSocketCommandHandler, ...]] = (
    ws_routines_list,
    ws_routines_get,
    ws_routines_set,
    ws_routines_action,
    ws_devices_opt,
    ws_schedule_today,
    ws_settings_get,
    ws_settings_set,
    ws_maintenance,
    ws_conversions_list,
    ws_conversions_convert,
    ws_subscribe,
)
