"""Fixtures for the device routine blueprint and its behavior matrix (TECH_SPEC 5 and 11.2).

Everything here runs the real core: the blueprint is installed the way the integration
installs it (`DomainBlueprints.async_add_blueprint`, Stage 0 V5), helpers are created
through their WebSocket commands dispatched in process (V7, decision L23), a routine is an
owned entry of `automations.yaml` (markers M1 and M2) loaded by an automation reload, and
a restart is a cold start over a restore cache (V10). Time moves with the `freezer`
through `Clock`, which stops at every scheduled timer on the way, so a time trigger always
runs at its own instant.

Reused by later lanes (plan Section 4.3): `installed_blueprint`, `routine_automation`,
`sandbox_switch`, `routine_timer`, `routine_schedule`, `override_switch`, `paused_until`
and `cold_start`, plus the hand written input factory `inputs(**overrides)`, which mirrors
what `compiler.compile` emits (wave A4 compares the two). Each fixture's contract is in its
docstring. A test uses either the per entity fixtures (a running instance) or `cold_start`
(a start over restored states), never both: the cold start builds the same entities itself
after the restore cache is in place.

Build B (plan Section 6.2.1): the mirror is blueprint input schema 2, the 29 inputs of
schema 1 plus the nine of sun bounds; `schema_1_inputs(**overrides)` writes what a schema 1
compiler wrote, `SCHEMA_1_BLUEPRINT` is the schema 1 file as v0.3.0-beta.1 shipped it, and
`sun_instant(hass, event, day, offset)` says when a sun bound runs on a day (lane 19 reuses
all three).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
import logging
from pathlib import Path
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.datetime import DateTimeEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.vacuum import StateVacuumEntity
from homeassistant.components.vacuum.const import VacuumActivity, VacuumEntityFeature
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.core import CoreState, Event, HomeAssistant, State
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.async_ import get_scheduled_timer_handles
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml, parse_yaml
import pytest
from pytest_homeassistant_custom_component.common import (
    MockPlatform,
    async_capture_events,
    async_fire_time_changed,
    mock_platform,
    mock_restore_cache,
)

from custom_components.device_routines import markers
from custom_components.device_routines.domains import profile_for

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
BLUEPRINT_SOURCE: Final = (
    REPO_ROOT / "custom_components" / "device_routines" / "blueprints" / "device_routine.yaml"
)
# The schema 1 file byte for byte as v0.3.0-beta.1 shipped it, for the upgrade rows (B50).
SCHEMA_1_BLUEPRINT: Final = (
    REPO_ROOT / "tests" / "fixtures" / "blueprint" / "device_routine_schema_1.yaml"
)

# The compiler's names (plan Sections 4.2 and 6.2.1), written out by hand: lane 1 wrote
# `compiler.py` in parallel, lane 16 moves it to schema 2 in parallel, and the contract
# tests compare these with it.
EVENT_ACTION_SKIPPED: Final = "device_routines_action_skipped"
EVENT_TIMER_CAUGHT_UP: Final = "device_routines_timer_caught_up"
UNUSED_TIMER: Final = "timer.device_routines_unused"
UNUSED_SCHEDULE: Final = "schedule.device_routines_unused"
UNUSED_SWITCH: Final = "switch.device_routines_unused"
UNUSED_DATETIME: Final = "datetime.device_routines_unused"
BLUEPRINT_SCHEMA_VERSION: Final = 2
SCHEMA_1_INPUT_KEYS: Final = (
    "target_entity",
    "on_action",
    "off_action",
    "inactive_state",
    "device_id",
    "on_time_enabled",
    "on_time",
    "off_time_enabled",
    "off_time",
    "days_start",
    "days_end",
    "crosses_midnight",
    "schedule_enabled",
    "schedule_entity",
    "timer_entity",
    "turn_off_after_min",
    "turn_back_on_after_min",
    "catch_up",
    "late_start_window_min",
    "late_window_end",
    "respect_manual",
    "override_entity",
    "paused_until_entity",
    "pulse_enabled",
    "pulse_at",
    "pulse_minutes",
    "pulse_min_steady_min",
    "docked_guard",
    "extra_conditions",
)
# The inputs Device Routines sets itself and `decompile` never reads (owner decision O3,
# decision L74). The four without a default (the profile's actions and off state, the
# device id) stay in Target under the device, each description starting "Set by Device
# Routines:", because the core's form keeps a section holding an input without a default
# open; the derived inputs and the helper entities fill the collapsed last section.
SET_IN_TARGET: Final = (
    "on_action",
    "off_action",
    "inactive_state",
    "device_id",
)
SET_IN_MANAGED_SECTION: Final = (
    "on_at_sunrise",
    "on_at_sunset",
    "off_at_sunrise",
    "off_at_sunset",
    "days_end",
    "crosses_midnight",
    "timer_entity",
    "late_window_end",
    "late_sun_offset",
    "override_entity",
    "paused_until_entity",
)
SET_BY_DEVICE_ROUTINES: Final = (*SET_IN_TARGET, *SET_IN_MANAGED_SECTION)
# The 38 inputs in file order, the order the core flattens the sections in: Target (the
# device, then the four set by Device Routines), what a person may change in the form
# (Schedule, Timers, Behavior, Advanced), then the collapsed last section.
INPUT_KEYS: Final = (
    "target_entity",
    *SET_IN_TARGET,
    "on_time_enabled",
    "on_time",
    "on_kind",
    "on_sun_offset",
    "off_time_enabled",
    "off_time",
    "off_kind",
    "off_sun_offset",
    "days_start",
    "schedule_enabled",
    "schedule_entity",
    "turn_off_after_min",
    "turn_back_on_after_min",
    "catch_up",
    "late_start_window_min",
    "respect_manual",
    "pulse_enabled",
    "pulse_at",
    "pulse_minutes",
    "pulse_min_steady_min",
    "docked_guard",
    "extra_conditions",
    *SET_IN_MANAGED_SECTION,
)
# The nine inputs schema 2 adds (plan Section 6.2.1), in their order among the 38.
SCHEMA_2_NEW_KEYS: Final = tuple(key for key in INPUT_KEYS if key not in SCHEMA_1_INPUT_KEYS)
WEEKDAYS: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# A bound's kind (`models.TimeKind`) and the nominal sun times that decide only whether a
# window crosses midnight (`models.NOMINAL_SUN_TIMES`, decision L60).
TIME_KINDS: Final = ("time", "sunrise", "sunset")
NOMINAL_SUN_TIMES: Final[Mapping[str, time]] = {"sunrise": time(6), "sunset": time(18)}

# The synthetic home every test uses. Generic names only (CLAUDE.md Section 6).
TIME_ZONE: Final = "America/Los_Angeles"
MONDAY: Final = date(2026, 10, 19)
DEVICE_ID: Final = "sandbox_device_living_room_fan"
AUTOMATION_ID: Final = markers.automation_id(DEVICE_ID)
ALIAS: Final = "Routine: Living room fan"
AUTOMATION: Final = "automation.routine_living_room_fan"
SWITCH: Final = "switch.living_room_fan"
OVERRIDE: Final = "switch.living_room_fan_manual_override"
PAUSED: Final = "datetime.living_room_fan_paused_until"
TIMER: Final = "timer.routine_living_room_fan"
SCHEDULE: Final = "schedule.routine_living_room_fan"
VACUUM: Final = "vacuum.robot_vacuum"

_SANDBOX: Final = "sandbox"
_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------
# Inputs: the hand written mirror of compiler.compile
# --------------------------------------------------------------------------------------


def target_inputs(domain: str, entity_id: str, device_class: str | None = None) -> dict[str, Any]:
    """Return the Target section for an entity of a domain, from its domain profile.

    A profile without an activating action (lock, media player, a garage, gate or door
    cover, a gas valve) still needs a valid service name in `on_action`, because the
    blueprint calls it by name; like the compiler, the mirror puts the profile's off
    action there, which can only make the device safer.
    """
    profile = profile_for(domain, device_class)
    assert profile is not None, domain
    return {
        "target_entity": entity_id,
        "on_action": profile.on_action or profile.off_action,
        "off_action": profile.off_action,
        "inactive_state": profile.inactive_state,
    }


_DEFAULTS: Final[Mapping[str, Any]] = {
    **target_inputs("switch", SWITCH),
    "device_id": DEVICE_ID,
    "on_time_enabled": False,
    "on_time": "00:00:00",
    "on_kind": "time",
    "on_sun_offset": "00:00:00",
    "off_time_enabled": False,
    "off_time": "00:00:00",
    "off_kind": "time",
    "off_sun_offset": "00:00:00",
    "on_at_sunrise": False,
    "on_at_sunset": False,
    "off_at_sunrise": False,
    "off_at_sunset": False,
    "days_start": list(WEEKDAYS),
    "days_end": list(WEEKDAYS),
    "crosses_midnight": False,
    "schedule_enabled": False,
    "schedule_entity": UNUSED_SCHEDULE,
    "timer_entity": UNUSED_TIMER,
    "turn_off_after_min": 0,
    "turn_back_on_after_min": 0,
    "catch_up": True,
    "late_start_window_min": 15,
    "late_window_end": "00:15:00",
    "late_sun_offset": "00:15:00",
    "respect_manual": True,
    "override_entity": UNUSED_SWITCH,
    "paused_until_entity": UNUSED_DATETIME,
    "pulse_enabled": False,
    "pulse_at": "00:00:00",
    "pulse_minutes": 3,
    "pulse_min_steady_min": 5,
    "docked_guard": True,
    "extra_conditions": [],
}


def _shift_days(days: Iterable[str]) -> list[str]:
    """Return a day set moved one day later, in Monday to Sunday order."""
    moved = {WEEKDAYS[(WEEKDAYS.index(day) + 1) % 7] for day in days}
    return [day for day in WEEKDAYS if day in moved]


def _plus_minutes(clock_time: str, minutes: int) -> str:
    """Return an HH:MM:SS time some minutes later, wrapped at midnight."""
    moment = datetime.combine(MONDAY, time.fromisoformat(clock_time)) + timedelta(minutes=minutes)
    return moment.time().isoformat()


def sun_offset(minutes: int) -> str:
    """Return an offset in whole minutes as `compile` writes it: `[-]HH:MM:00`.

    The leading `-` (before the event) appears only for a negative offset.
    """
    hours, rest = divmod(abs(minutes), 60)
    return f"{'-' if minutes < 0 else ''}{hours:02d}:{rest:02d}:00"


def offset_minutes(text: str) -> int:
    """Return the whole minutes of an offset text, `[-]H:MM` or `[-]HH:MM:SS`.

    Seconds are dropped toward zero, as `decompile` reads them (plan Section 6.2.1).
    """
    negative = text.startswith("-")
    hours, minutes, *_ = text.lstrip("+-").split(":")
    total = int(hours) * 60 + int(minutes)
    return -total if negative else total


def _nominal(kind: str, clock_time: str, offset: str) -> time:
    """Return a bound's time for ordering: its time, or the nominal sun time plus the offset."""
    if kind == "time":
        return time.fromisoformat(clock_time)
    return time.fromisoformat(
        _plus_minutes(NOMINAL_SUN_TIMES[kind].isoformat(), offset_minutes(offset))
    )


def _side_set(values: Mapping[str, Any], side: str) -> bool:
    """A side is set when its time flag or either of its sun flags is on (plan 6.2.1)."""
    return any(values[f"{side}_{flag}"] for flag in ("time_enabled", "at_sunrise", "at_sunset"))


def inputs(**overrides: Any) -> dict[str, Any]:
    """Return the 38 blueprint inputs of schema 2 in order, as `compile` would emit them.

    Unused helpers are the sentinels and every flag has its spec default. The derived
    inputs follow from what is given, as TECH_SPEC 3.3 and plan Section 6.2.1 derive them,
    unless given too: `on_time_enabled` and `off_time_enabled` turn on when their time is
    given for a time bound; `on_at_sunrise`, `on_at_sunset`, `off_at_sunrise` and
    `off_at_sunset` follow `on_kind` and `off_kind`; `schedule_enabled` and `pulse_enabled`
    turn on when their entity or time is given; `crosses_midnight` when the on bound is
    later than the off bound, a sun bound read at its nominal time plus its offset (sunrise
    06:00, sunset 18:00, decision L60); `days_end` is `days_start` shifted by one day for a
    window crossing midnight; `late_window_end` is the on time plus the late start window
    and `late_sun_offset` the on offset plus the late start window. A sun bound keeps its
    time at the `00:00:00` sentinel; offsets are text, as `sun_offset` writes them.
    """
    unknown = set(overrides) - set(INPUT_KEYS)
    if unknown:
        raise KeyError(f"not a blueprint input: {sorted(unknown)}")
    values = {**_DEFAULTS, **overrides}

    def derive(key: str, value: Any) -> None:
        if key not in overrides:
            values[key] = value

    for side in ("on", "off"):
        assert values[f"{side}_kind"] in TIME_KINDS, values[f"{side}_kind"]
        derive(
            f"{side}_time_enabled", f"{side}_time" in overrides and values[f"{side}_kind"] == "time"
        )
        for event in ("sunrise", "sunset"):
            derive(f"{side}_at_{event}", values[f"{side}_kind"] == event)
    derive("schedule_enabled", "schedule_entity" in overrides)
    derive("pulse_enabled", "pulse_at" in overrides)
    derive(
        "crosses_midnight",
        _side_set(values, "on")
        and _side_set(values, "off")
        and _nominal(values["on_kind"], values["on_time"], values["on_sun_offset"])
        > _nominal(values["off_kind"], values["off_time"], values["off_sun_offset"]),
    )
    days_start = [day for day in WEEKDAYS if day in values["days_start"]]
    derive("days_start", days_start)
    derive("days_end", _shift_days(days_start) if values["crosses_midnight"] else days_start)
    late = values["late_start_window_min"]
    derive("late_window_end", _plus_minutes(values["on_time"], late))
    derive("late_sun_offset", sun_offset(offset_minutes(values["on_sun_offset"]) + late))
    return {key: values[key] for key in INPUT_KEYS}


def schema_1_inputs(**overrides: Any) -> dict[str, Any]:
    """Return the 29 inputs a schema 1 compiler wrote for the same time bound settings.

    The schema 1 mirror is the schema 2 one without the nine new inputs: every new input
    defaults to schema 1 behavior, so a time bound routine reads the same on both.
    """
    refused = set(overrides) - set(SCHEMA_1_INPUT_KEYS)
    if refused:
        raise KeyError(f"not a schema 1 input: {sorted(refused)}")
    written = inputs(**overrides)
    return {key: written[key] for key in SCHEMA_1_INPUT_KEYS}


def sun_instant(
    hass: HomeAssistant, event: str, day: int | date, offset: timedelta = timedelta()
) -> datetime:
    """Return when a sun bound runs on a day: its sunrise or sunset plus the offset, local.

    `day` counts days after Monday 2026-10-19, as `Clock.at` does, or is a date. The event
    comes from the core's astral helper for the test instance's location, the helper the
    summary's sun lookup uses; the sun trigger and the sun condition read the same astral
    event for that local day. A day without the event fails the test.
    """
    when = MONDAY + timedelta(days=day) if isinstance(day, int) else day
    moment = get_astral_event_date(hass, event, when)
    assert moment is not None, f"no {event} on {when}"
    local = (moment + offset).astimezone(ZoneInfo(hass.config.time_zone))
    assert local.date() == when, f"{event} plus {offset} leaves {when}"
    return local


def owned_automation(routine_inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Return the `automations.yaml` entry of a routine: markers M1 and M2 and the inputs."""
    return {
        "id": AUTOMATION_ID,
        "alias": ALIAS,
        "description": "Managed by Device Routines.",
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": dict(routine_inputs)},
    }


# --------------------------------------------------------------------------------------
# Sandbox entities: a real switch, datetime and vacuum on a mocked platform
# --------------------------------------------------------------------------------------


class SandboxSwitch(SwitchEntity, RestoreEntity):
    """A switch that answers its services, restores its state and can change by itself."""

    _attr_should_poll = False

    def __init__(self, entity_id: str, name: str) -> None:
        self.entity_id = entity_id
        self._attr_name = name
        self._attr_unique_id = f"sandbox_{entity_id}"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        self._attr_is_on = False
        self.async_write_ha_state()

    @property
    def state_now(self) -> str | None:
        """The state the state machine holds for this entity right now."""
        state = self.hass.states.get(self.entity_id)
        return None if state is None else state.state

    def device_change(self, on: bool) -> None:
        """Change by itself, as a wall switch or the device's own timer does."""
        self._attr_available = True
        self._attr_is_on = on
        self.async_write_ha_state()

    def set_available(self, available: bool) -> None:
        """Drop off the network, or come back with the state it had."""
        self._attr_available = available
        self.async_write_ha_state()


class SandboxDateTime(DateTimeEntity, RestoreEntity):
    """The shape of Paused until: a datetime entity that restores its value (V12)."""

    _attr_should_poll = False

    def __init__(self, entity_id: str, name: str) -> None:
        self.entity_id = entity_id
        self._attr_name = name
        self._attr_unique_id = f"sandbox_{entity_id}"
        self._attr_native_value: datetime | None = None

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) is not None:
            self._attr_native_value = dt_util.parse_datetime(last.state)

    async def async_set_value(self, value: datetime) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

    def set(self, value: datetime | None) -> None:
        """Set or clear the value, as the integration does for pause, skip and resume."""
        self._attr_native_value = value
        self.async_write_ha_state()

    def set_available(self, available: bool) -> None:
        """Go unavailable, as when the integration is unloaded, or come back."""
        self._attr_available = available
        self.async_write_ha_state()


class SandboxVacuum(StateVacuumEntity, RestoreEntity):
    """A robot vacuum that starts, returns to its dock and restores its activity."""

    _attr_should_poll = False
    _attr_supported_features = (
        VacuumEntityFeature.START | VacuumEntityFeature.RETURN_HOME | VacuumEntityFeature.STATE
    )

    def __init__(self, entity_id: str, name: str) -> None:
        self.entity_id = entity_id
        self._attr_name = name
        self._attr_unique_id = f"sandbox_{entity_id}"
        self._attr_activity = VacuumActivity.DOCKED

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) is not None:
            self._attr_activity = VacuumActivity(last.state)

    async def async_start(self) -> None:
        self._attr_activity = VacuumActivity.CLEANING
        self.async_write_ha_state()

    async def async_return_to_base(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        self._attr_activity = VacuumActivity.DOCKED
        self.async_write_ha_state()

    def device_change(self, activity: VacuumActivity) -> None:
        """Change by itself, as a vacuum that leaves or reaches its dock does."""
        self._attr_activity = activity
        self.async_write_ha_state()


async def async_add_sandbox_entities(hass: HomeAssistant, domain: str, *entities: Entity) -> None:
    """Add entities to the `sandbox` platform of a domain, setting the domain up once."""
    adders: dict[str, AddEntitiesCallback] = hass.data.setdefault(f"{_SANDBOX}_adders", {})
    if domain not in adders:

        async def async_setup_platform(
            hass: HomeAssistant,
            config: ConfigType,
            async_add_entities: AddEntitiesCallback,
            discovery_info: DiscoveryInfoType | None = None,
        ) -> None:
            adders[domain] = async_add_entities

        mock_platform(
            hass,
            f"{_SANDBOX}.{domain}",
            MockPlatform(async_setup_platform=async_setup_platform),
        )
        if domain in hass.config.components:
            # The integration's own platforms set the component up already.
            await async_load_platform(hass, domain, _SANDBOX, {}, {})
        else:
            assert await async_setup_component(hass, domain, {domain: {"platform": _SANDBOX}})
        await hass.async_block_till_done()
    adders[domain](list(entities))
    await hass.async_block_till_done()


# --------------------------------------------------------------------------------------
# Helpers through the in process WebSocket dispatch (V7, decision L23)
# --------------------------------------------------------------------------------------


class InProcess:
    """One in process WebSocket connection for a system administrator user."""

    def __init__(self, hass: HomeAssistant, user: Any) -> None:
        self.results: dict[int, dict[str, Any]] = {}
        self.connection = ActiveConnection(
            logging.getLogger(__name__),  # type: ignore[arg-type]
            hass,
            self._receive,
            user,
            None,
            None,
        )
        self._next = 0

    def _receive(self, message: Any) -> None:
        if not isinstance(message, dict):
            message = json.loads(message)
        self.results[message["id"]] = message

    async def call(self, hass: HomeAssistant, **command: Any) -> dict[str, Any]:
        """Dispatch one command and return its result message."""
        self._next += 1
        self.connection.async_handle({"id": self._next, **command})
        # Async command handlers run as background tasks, as they do for a socket.
        await hass.async_block_till_done(wait_background_tasks=True)
        result = self.results[self._next]
        assert result["success"], result
        return result


async def async_connection(hass: HomeAssistant) -> InProcess:
    """Return the shared in process connection, setting its components up once."""
    if (existing := hass.data.get(f"{_SANDBOX}_connection")) is not None:
        assert isinstance(existing, InProcess)
        return existing
    assert await async_setup_component(hass, "websocket_api", {})
    user = await hass.auth.async_create_system_user("Device Routines", group_ids=[GROUP_ID_ADMIN])
    connection = InProcess(hass, user)
    hass.data[f"{_SANDBOX}_connection"] = connection
    return connection


async def async_create_timer(hass: HomeAssistant) -> str:
    """Create the routine's timer helper with restore on, as the adapter will."""
    assert await async_setup_component(hass, "timer", {})
    connection = await async_connection(hass)
    await connection.call(
        hass, type="timer/create", name="Routine living room fan", duration="00:30:00", restore=True
    )
    assert hass.states.get(TIMER) is not None
    return TIMER


Blocks = Mapping[str, Sequence[tuple[str, str]]]


async def async_create_schedule(hass: HomeAssistant, blocks: Blocks) -> str:
    """Create the routine's weekly schedule helper with blocks per weekday name."""
    assert await async_setup_component(hass, "schedule", {})
    connection = await async_connection(hass)
    days = {
        day: [{"from": start, "to": end} for start, end in spans] for day, spans in blocks.items()
    }
    await connection.call(hass, type="schedule/create", name="Routine living room fan", **days)
    assert hass.states.get(SCHEDULE) is not None
    return SCHEDULE


# --------------------------------------------------------------------------------------
# The routine itself: the blueprint, the owned automation, a cold start
# --------------------------------------------------------------------------------------


def write_automation(config_dir: Path, entry: Mapping[str, Any]) -> None:
    """Replace or append one entry of `automations.yaml` by id, atomically (V6)."""
    path = config_dir / AUTOMATION_CONFIG_PATH
    current: list[dict[str, Any]] = load_yaml(str(path)) or []  # type: ignore[assignment]
    others = [item for item in current if item.get("id") != entry["id"]]
    write_utf8_file_atomic(str(path), dump([*others, dict(entry)]))


def automation_entries(config_dir: Path) -> list[dict[str, Any]]:
    """Return the entries of `automations.yaml`."""
    loaded: list[dict[str, Any]] = load_yaml(str(config_dir / AUTOMATION_CONFIG_PATH)) or []  # type: ignore[assignment]
    return loaded


@dataclass
class Home:
    """What a cold start built: the same entities the per entity fixtures provide."""

    switch: SandboxSwitch
    override: SandboxSwitch
    paused: SandboxDateTime
    timer: str
    schedule: str | None
    vacuum: SandboxVacuum | None


class Clock:
    """Time travel that stops at every scheduled timer on the way to the target.

    A jump straight over two scheduled moments would run both callbacks at the target
    time, in heap order; walking from one due timer to the next runs each at its own
    instant, the way the event loop would.
    """

    def __init__(self, hass: HomeAssistant, freezer: Any) -> None:
        self._hass = hass
        self._freezer = freezer

    @property
    def zone(self) -> ZoneInfo:
        """The instance's time zone, read each time so a test may change it."""
        return ZoneInfo(self._hass.config.time_zone)

    def at(self, day: int, clock_time: str) -> datetime:
        """Return a local moment: `day` days after Monday 2026-10-19, at HH:MM[:SS]."""
        return datetime.combine(
            MONDAY + timedelta(days=day), time.fromisoformat(clock_time)
        ).replace(tzinfo=self.zone)

    def set(self, moment: datetime) -> None:
        """Put the clock somewhere before anything is scheduled."""
        self._freezer.move_to(moment)

    @property
    def now(self) -> datetime:
        """The local time now."""
        return dt_util.now().astimezone(self.zone)

    async def to(self, target: datetime, *, settle: Literal["block", "yield"] = "block") -> None:
        """Move to `target`, firing every timer due on the way at its own time.

        `settle="yield"` lets callbacks run without `async_block_till_done`, which would
        wait for an automation that sits in a delay (a pulse) and hang the test.
        """
        goal = dt_util.as_utc(target)
        for _ in range(100_000):
            now = dt_util.utcnow()
            loop_now = self._hass.loop.time()
            upcoming = [
                due
                for handle in get_scheduled_timer_handles(self._hass.loop)
                if not handle.cancelled()
                and now < (due := now + timedelta(seconds=handle.when() - loop_now)) <= goal
            ]
            if not upcoming:
                break
            await self._fire_at(min(upcoming), settle)
        await self._fire_at(goal, settle)

    async def advance(self, *, settle: Literal["block", "yield"] = "block", **delta: float) -> None:
        """Move forward by a duration, for example `minutes=5`."""
        await self.to(dt_util.utcnow() + timedelta(**delta), settle=settle)

    async def _fire_at(self, moment: datetime, settle: Literal["block", "yield"]) -> None:
        self._freezer.move_to(moment)
        async_fire_time_changed(self._hass)
        if settle == "block":
            await self._hass.async_block_till_done()
        else:
            for _ in range(50):
                await asyncio.sleep(0)


def skipped(events: Sequence[Event]) -> list[tuple[str, str]]:
    """Return the (trigger id, action) pairs of captured skipped action events."""
    return [(event.data["trigger_id"], event.data["action"]) for event in events]


def restored_timer(finishes_at: datetime, duration_min: int) -> State:
    """The state a running routine timer leaves in the restore cache at shutdown (V10)."""
    duration = str(timedelta(minutes=duration_min))
    return State(
        TIMER,
        "active",
        {
            "duration": duration,
            "remaining": duration,
            "finishes_at": dt_util.as_utc(finishes_at).isoformat(),
            "last_transition": "started",
            "restore": True,
        },
    )


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Daily time triggers stay scheduled when a test ends; that is the point, not a leak."""
    return True


@pytest.fixture
async def routine_config_dir(hass: HomeAssistant, tmp_path: Path) -> Path:
    """A scratch config directory whose `configuration.yaml` includes `automations.yaml`."""
    await hass.config.async_set_time_zone(TIME_ZONE)
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text(
        "automation: !include automations.yaml\n", encoding="utf-8"
    )
    (tmp_path / AUTOMATION_CONFIG_PATH).write_text("[]\n", encoding="utf-8")
    return tmp_path


async def async_install_blueprint(hass: HomeAssistant, source: Path = BLUEPRINT_SOURCE) -> Path:
    """Install a blueprint file at `markers.BLUEPRINT_PATH`; return the installed file.

    The install goes through `DomainBlueprints.async_add_blueprint`, the method the
    `blueprint/save` command and the adapter use (V5). Over an installed file it also
    reloads the automations built on it, as an upgrade of the shipped file does.
    """
    data = parse_yaml(await hass.async_add_executor_job(source.read_text, "utf-8"))
    assert isinstance(data, dict)
    blueprint = Blueprint(data, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)
    await async_get_blueprints(hass).async_add_blueprint(
        blueprint, markers.BLUEPRINT_PATH, allow_override=True
    )
    await hass.async_block_till_done()
    installed = Path(hass.config.config_dir) / "blueprints" / "automation" / markers.BLUEPRINT_PATH
    assert installed.is_file()
    return installed


@pytest.fixture
async def installed_blueprint(hass: HomeAssistant, routine_config_dir: Path) -> Path:
    """Install the shipped blueprint at `markers.BLUEPRINT_PATH`; return the installed file.

    The install goes through `async_install_blueprint`. The automation component is not
    set up here, so a cold start can still set it up before Home Assistant starts.
    """
    installed = await async_install_blueprint(hass)
    assert installed == routine_config_dir / "blueprints" / "automation" / markers.BLUEPRINT_PATH
    return installed


@pytest.fixture
async def sandbox_switch(hass: HomeAssistant) -> SandboxSwitch:
    """The routine's device: `switch.living_room_fan`, off, a real entity on a mocked platform.

    Its services work, it restores its state, and `device_change(on)` changes it the way a
    wall switch does (a fresh context with no user and no parent); `set_available(False)`
    drops it off the network.
    """
    switch = SandboxSwitch(SWITCH, "Living room fan")
    await async_add_sandbox_entities(hass, "switch", switch)
    return switch


@pytest.fixture
async def override_switch(hass: HomeAssistant) -> SandboxSwitch:
    """A stand in for the integration's Manual override switch, off, restored.

    The blueprint only reads it and turns it off; the integration owns it in production.
    """
    switch = SandboxSwitch(OVERRIDE, "Living room fan manual override")
    await async_add_sandbox_entities(hass, "switch", switch)
    return switch


@pytest.fixture
async def paused_until(hass: HomeAssistant) -> SandboxDateTime:
    """A stand in for the integration's Paused until entity, unknown, restored.

    `set(moment)` pauses or skips until then; `set(None)` clears it, `set(now)` resumes.
    """
    entity = SandboxDateTime(PAUSED, "Living room fan paused until")
    await async_add_sandbox_entities(hass, "datetime", entity)
    return entity


@pytest.fixture
async def sandbox_vacuum(hass: HomeAssistant) -> SandboxVacuum:
    """A robot vacuum, `vacuum.robot_vacuum`, docked, restored, for the docked guard."""
    vacuum = SandboxVacuum(VACUUM, "Robot vacuum")
    await async_add_sandbox_entities(hass, "vacuum", vacuum)
    return vacuum


@pytest.fixture
async def routine_timer(hass: HomeAssistant) -> str:
    """The routine's timer helper `timer.routine_living_room_fan`, restore on, idle."""
    return await async_create_timer(hass)


@pytest.fixture
def routine_schedule(hass: HomeAssistant) -> Callable[[Blocks], Awaitable[str]]:
    """A factory for the routine's weekly schedule helper `schedule.routine_living_room_fan`.

    Call it with blocks per weekday name, for example
    `{"monday": [("17:00:00", "22:00:00")]}`; it returns the entity id.
    """

    async def create(blocks: Blocks) -> str:
        return await async_create_schedule(hass, blocks)

    return create


@pytest.fixture
def routine_automation(
    hass: HomeAssistant, installed_blueprint: Path
) -> Callable[[Mapping[str, Any]], Awaitable[str]]:
    """A factory that writes the owned routine automation and loads it; returns its entity id.

    It writes the entry with M1 (`markers.automation_id(DEVICE_ID)`) and M2 (the blueprint
    path) into `automations.yaml`, sets the automation component up on first use and
    reloads that one automation, as the integration's write path does. Calling it again
    replaces the inputs. Works beside a loaded config entry.
    """

    async def write(routine_inputs: Mapping[str, Any]) -> str:
        config_dir = Path(hass.config.config_dir)
        write_automation(config_dir, owned_automation(routine_inputs))
        if "automation" not in hass.config.components:
            assert await async_setup_component(hass, "automation", {})
        await hass.services.async_call("automation", "reload", {"id": AUTOMATION_ID}, blocking=True)
        await hass.async_block_till_done()
        state = hass.states.get(AUTOMATION)
        assert state is not None, "the routine did not load"
        assert state.state == "on", state
        return AUTOMATION

    return write


@pytest.fixture
def cold_start(hass: HomeAssistant, installed_blueprint: Path) -> Callable[..., Awaitable[Home]]:
    """A factory for a start of Home Assistant over a restore cache (V10).

    `await cold_start(restore_states, routine=inputs(...), schedule=blocks, vacuum=False)`
    puts the core in `not_running`, fills the restore cache, builds the sandbox switch, the
    override switch, Paused until, the timer helper and, when asked, the schedule helper and
    the vacuum, writes the routine into `automations.yaml`, sets the automation component up
    from it and starts Home Assistant, so the routine's start trigger runs. Use it instead
    of the per entity fixtures, never together with them.
    """

    async def start(
        restore_states: Sequence[State] = (),
        *,
        routine: Mapping[str, Any] | None = None,
        schedule: Blocks | None = None,
        vacuum: bool = False,
    ) -> Home:
        assert "switch" not in hass.config.components, "cold_start builds the entities itself"
        hass.set_state(CoreState.not_running)
        mock_restore_cache(hass, restore_states)
        switch = SandboxSwitch(SWITCH, "Living room fan")
        override = SandboxSwitch(OVERRIDE, "Living room fan manual override")
        paused = SandboxDateTime(PAUSED, "Living room fan paused until")
        await async_add_sandbox_entities(hass, "switch", switch, override)
        await async_add_sandbox_entities(hass, "datetime", paused)
        robot = None
        if vacuum:
            robot = SandboxVacuum(VACUUM, "Robot vacuum")
            await async_add_sandbox_entities(hass, "vacuum", robot)
        timer = await async_create_timer(hass)
        schedule_entity = None if schedule is None else await async_create_schedule(hass, schedule)
        config_dir = Path(hass.config.config_dir)
        if routine is not None:
            write_automation(config_dir, owned_automation(routine))
        assert await async_setup_component(
            hass, "automation", {"automation": automation_entries(config_dir)}
        )
        await hass.async_block_till_done()
        await hass.async_start()
        await hass.async_block_till_done()
        return Home(switch, override, paused, timer, schedule_entity, robot)

    return start


@pytest.fixture
def clock(hass: HomeAssistant, freezer: Any) -> Clock:
    """Time travel through `Clock`: `clock.set(moment)` first, then `await clock.to(moment)`."""
    return Clock(hass, freezer)


@pytest.fixture
def skipped_events(hass: HomeAssistant) -> list[Event]:
    """Every `device_routines_action_skipped` event fired during the test."""
    return async_capture_events(hass, EVENT_ACTION_SKIPPED)
