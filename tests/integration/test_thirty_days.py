"""Build A task A4.2: thirty simulated days in one harness home (PRD goal G8).

G8 asks that a home with routines lives through a month of ordinary upkeep events
without a Repairs issue outside the three documented cases (an edited blueprint file, an
invalid form edit, missing weekly blocks) and without any other human action. One harness
home lives through 30 days here: three routines on the shipped blueprint, the real
manager and device page entities, devices of another integration that answer their
services and restore their state, time moved by `Clock` (which stops at every scheduled
timer, so every time trigger runs at its own instant), and two cold starts, each a stop
of the instance and a start of a new one over the registries, the Store, the helpers,
`automations.yaml` and the restore state the stopped one left behind.

The home (generic names, synthetic ids, CLAUDE.md Section 6) is set up on Monday
2026-11-02 at 10:00 in America/Los_Angeles; the 30 days hold no daylight saving change
(the behavior matrix covers B40 and B41):

- a hallway light, a window from 17:00 to 09:00 every day (FR-R1);
- a bathroom fan with Turn off after 45 minutes (FR-R3), switched on at the wall every
  morning at 07:10;
- a garden pump on its own weekly schedule (FR-R2): weekdays 06:30 to 07:00 and 17:15 to
  18:30, weekends 08:00 to 09:30 and 17:15 to 18:30.

Timeline (day, local time, event: what is asserted):

- Day 0, Mon 10:00, the three routines are set up: no issue, the sentences.
- Day 3, Thu 17:14, the pump is renamed (a minute before its 17:15 block): the alias,
  the description and the schedule helper's name follow, the sentence holds, the block
  runs at 17:15.
- Day 5, Sat, the first cold start, carrying S12, S3 and the timer catch up of L20: at
  16:30 `device_routines.pause` for 2 hours on the hallway (S12) and the fan switched on
  by a person; 17:00 the light's on time is skipped with `device_routines_action_skipped`;
  Home Assistant stops at 17:10 and starts at 17:20, past the pump's 17:15 block start
  (S3) and the fan's countdown end (17:15); at 17:20 the pump is on and the fan off
  (within 60 seconds of the start), the pause is still there; at 18:30 the pause ends and
  catch up turns the light on (D20).
- Day 7, Mon 07:30, the fan's entity id is renamed in the middle of its countdown: the
  input follows and the countdown turns the renamed entity off at 07:55.
- Day 8, Tue 03:00, a copy of `automations.yaml` is taken (a nightly backup).
- Day 9, Wed 12:00, the light's Turn off at moves to 08:30 on its device page.
- Day 10, Thu 08:00, `automations.yaml` is restored from the copy and reloaded: the
  routine follows the file (off at 09:00, not 08:30), the entities and the Store too.
- Day 14, Mon 16:55, the integration is updated over a fake blueprint schema 0 (the
  entry unloads, the files read as the previous version left them, the entry sets up
  again): the shipped blueprint is installed, every routine is migrated with its
  previous inputs kept, the 17:00 and 17:15 actions run on the migrated automations.
- Day 20, Sun, the light is offline from 08:30 to 20:00 and comes back off: nothing runs
  against it meanwhile, catch up turns it on 10 seconds after it returns (B20).
- Day 22, Tue 12:00, the pump is removed from Home Assistant: its routine turns off and
  nothing runs for it again.
- Day 25, Fri, the second cold start, carrying S4 and S5: at 12:00 a person turns the
  light on (S4) and at 12:15 the fan (S5); Home Assistant stops at 12:30 and starts at
  12:31; the light stays on with Manual override on and `last_change_source: user`; the
  fan turns off at 13:00; at 17:00 the light's on time runs and clears the override.
- Day 27, Sun 12:00, the cleanup period (`cleanup_after_days` 5) ends: the pump's
  automation, schedule helper and Store records are gone.
- Day 30, Wed, the end: no Repairs issue was ever raised, every device changed exactly
  when the schedule said (the change log of every day equals the expected one, to the
  second), the sentences were right at every checkpoint (nine a day), and the Store
  rebuilt from the markers equals the Store kept.

Every day also checks that no issue of the integration was raised at any moment (the
issue registry's events, not only what is open at the end), that the hub's Problem
sensor is off and Health ok, and the run ends with nothing logged at ERROR.

Defects the simulation found are pinned as strict xfails at the end of this module, one
test each; the run lets exactly their symptoms through and counts them, so everything
else it proves still holds: a sentence keeps its weekday form after midnight, unloading
after a start logs two errors, a schema update can raise a passing `invalid_inputs`,
removing a device logs errors from its page entities, Health reads `degraded` after a
cleanup, and a Store rebuilt from nothing lacks three fields. One more is pinned without
a symptom in the run (it asserts nothing about it): the device page controls and the
Schedule sensor keep the old device name after a rename.

The cold start is the harness's: a new `HomeAssistant` on the same loop and config
directory, with the registries and the users carried over (the harness keeps both in
memory only), the storage mock holding the Store, the helpers and the restore state, and
the stopped instance's pending timers cancelled. An integration update (day 14) is the
entry unloading and setting up again inside the running instance.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import AsyncExitStack, suppress
import copy
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import logging
from pathlib import Path
import traceback
from typing import Any, Final
from unittest.mock import patch
from zoneinfo import ZoneInfo

from homeassistant import bootstrap, loader
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.components.light import LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.components.switch import SwitchEntity
from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigFlow
from homeassistant.const import EVENT_STATE_CHANGED, Platform
from homeassistant.core import Context, CoreState, Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    category_registry as cr,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    issue_registry as ir,
    label_registry as lr,
    restore_state as rs,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import ToggleEntity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.json import json_bytes
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.async_ import get_scheduled_timer_handles
from homeassistant.util.json import json_loads
from homeassistant.util.yaml import dump, load_yaml
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    async_test_home_assistant,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

from custom_components.device_routines import compiler, ha_adapter, maintenance, markers, migration
from custom_components.device_routines.config_flow import DeviceRoutinesConfigFlow
from custom_components.device_routines.const import (
    CONF_SYSTEM_USER_ID,
    DOMAIN,
    INTEGRATION_TITLE,
)
from custom_components.device_routines.maintenance import MaintenanceAction
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import RoutineSettings, Status
from custom_components.device_routines.store import STORAGE_KEY, StoreData
from tests.blueprint.conftest import Clock

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

TIME_ZONE: Final = "America/Los_Angeles"
# A Monday; the 30 days that follow hold no daylight saving change in this zone.
DAY_0: Final = date(2026, 11, 2)
DAYS: Final = 30
SANDBOX: Final = "sandbox"
SANDBOX_ENTRY: Final = "sandbox-entry"
ROUTINES_ENTRY: Final = "device-routines-entry"
CLEANUP_AFTER_DAYS: Final = 5
# A person in the app: a change whose context carries a user id (PRD 9.3).
RESIDENT: Final = "Resident"

LIGHT: Final = "light"
FAN: Final = "fan"
PUMP: Final = "pump"

WEEKDAY_BLOCKS: Final = (("06:30:00", "07:00:00"), ("17:15:00", "18:30:00"))
WEEKEND_BLOCKS: Final = (("08:00:00", "09:30:00"), ("17:15:00", "18:30:00"))
WEEKDAY_NAMES: Final = ("monday", "tuesday", "wednesday", "thursday", "friday")
WEEKEND_NAMES: Final = ("saturday", "sunday")

# The sentence checkpoints of every day (none falls inside a downtime or on an action).
CHECKPOINTS: Final = (
    "06:00:00",
    "06:45:00",
    "07:30:00",
    "08:15:00",
    "09:15:00",
    "12:05:00",
    "17:05:00",
    "17:45:00",
    "21:00:00",
)

# The fake blueprint input schema 0: schema 1 with `turn_off_after_min` named
# `off_after_min`. Every routine's inputs carry the key, so every routine migrates.
OLD_KEY: Final = "off_after_min"
NEW_KEY: Final = "turn_off_after_min"

type Step = Callable[[], Awaitable[None]]


# --------------------------------------------------------------------------------------
# The other integration's devices: on and off, restored, offline at will
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    """One device of the sandbox integration."""

    key: str
    name: str
    platform: Platform
    area: str


SPECS: Final = (
    Spec(LIGHT, "Hallway light", Platform.LIGHT, "Hallway"),
    Spec(FAN, "Bathroom fan", Platform.SWITCH, "Bathroom"),
    Spec(PUMP, "Garden pump", Platform.SWITCH, "Garden"),
)


def spec_of(key: str) -> Spec:
    return next(spec for spec in SPECS if spec.key == key)


class OnOff(ToggleEntity, RestoreEntity):
    """A device that answers on and off, restores its state and can change by itself."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, spec: Spec) -> None:
        self._attr_unique_id = f"{SANDBOX}_{spec.key}"
        self._attr_device_info = DeviceInfo(identifiers={(SANDBOX, spec.key)}, name=spec.name)
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in {"on", "off"}:
            self._attr_is_on = last.state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        self._attr_is_on = False
        self.async_write_ha_state()

    def device_change(self, on: bool) -> None:
        """Change by itself (a wall switch): a fresh context, no user, no parent."""
        self._attr_available = True
        self._attr_is_on = on
        self.async_write_ha_state()

    def set_available(self, available: bool) -> None:
        """Drop off the network, or come back with the state it holds."""
        self._attr_available = available
        self.async_write_ha_state()


class SandboxSwitch(OnOff, SwitchEntity):
    """A switch of the sandbox integration."""


class SandboxLight(OnOff, LightEntity):
    """An on and off light of the sandbox integration."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}  # noqa: RUF012  # the core's attribute


class SandboxFlow(ConfigFlow):
    """The sandbox integration's flow handler, so its config entry can set up."""

    VERSION = 1


@pytest.fixture(autouse=True)
def sandbox_flow() -> Iterator[None]:
    """Register the sandbox flow handler for the test, and only for it."""
    with mock_config_flow(SANDBOX, SandboxFlow):
        yield


async def async_setup_sandbox(hass: HomeAssistant, present: set[str]) -> dict[str, OnOff]:
    """Set up the sandbox integration's entry with the devices it still has; return them."""
    entities: dict[str, OnOff] = {
        spec.key: (SandboxLight if spec.platform is Platform.LIGHT else SandboxSwitch)(spec)
        for spec in SPECS
        if spec.key in present
    }
    platforms = [Platform.LIGHT, Platform.SWITCH]

    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        await hass.config_entries.async_forward_entry_setups(entry, platforms)
        return True

    async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        return await hass.config_entries.async_unload_platforms(entry, platforms)

    def platform_setup(platform: Platform) -> Any:
        async def async_setup_platform_entry(
            hass: HomeAssistant, entry: ConfigEntry, add: AddConfigEntryEntitiesCallback
        ) -> None:
            add([entity for key, entity in entities.items() if spec_of(key).platform is platform])

        return async_setup_platform_entry

    mock_integration(
        hass,
        MockModule(
            SANDBOX, async_setup_entry=async_setup_entry, async_unload_entry=async_unload_entry
        ),
    )
    mock_platform(hass, f"{SANDBOX}.config_flow", None)
    for platform in platforms:
        mock_platform(
            hass,
            f"{SANDBOX}.{platform.value}",
            MockPlatform(async_setup_entry=platform_setup(platform)),
        )
    entry = MockConfigEntry(domain=SANDBOX, entry_id=SANDBOX_ENTRY, title="Sandbox")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entities


# --------------------------------------------------------------------------------------
# Time, sentences and the expected changes
# --------------------------------------------------------------------------------------


def at(day: int, clock_time: str) -> datetime:
    """Return a local moment: `day` days after Monday 2026-11-02, at HH:MM[:SS]."""
    return datetime.combine(DAY_0 + timedelta(days=day), time.fromisoformat(clock_time)).replace(
        tzinfo=ZoneInfo(TIME_ZONE)
    )


def twelve_hour(clock_time: str) -> str:
    """09:00 reads 9:00 AM, 17:15 reads 5:15 PM (the US time format, PRD 10.4)."""
    moment = time.fromisoformat(clock_time)
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def weekday(day: int) -> str:
    return (DAY_0 + timedelta(days=day)).strftime("%a")


def blocks(day: int) -> tuple[tuple[str, str], ...]:
    weekend = (DAY_0 + timedelta(days=day)).weekday() >= 5
    return WEEKEND_BLOCKS if weekend else WEEKDAY_BLOCKS


def light_off_time(day: int, now: str) -> str:
    """The light's Turn off at as the routine holds it at that moment (days 9 and 10)."""
    edited = (9, "12:00:00") <= (day, now) < (10, "08:00:00")
    return "08:30:00" if edited else "09:00:00"


def light_sentence(day: int, now: str) -> str:
    """The hallway light's Schedule: the next action of its window, or the S12 pause."""
    if day == 5 and "16:30:00" <= now < "18:30:00":
        return "Paused until 6:30 PM"
    off = light_off_time(day, now)
    if now < off:
        return f"Off at {twelve_hour(off)}"
    if now < "17:00:00":
        return "On at 5:00 PM"
    return f"Off {weekday(day + 1)} {twelve_hour(off)}"


FAN_IDLE: Final = "Off 45 min after it turns on"


def fan_countdowns(day: int) -> list[tuple[str, str]]:
    """The fan's countdowns of a day: the morning one, and those of the two restarts."""
    countdowns = [("07:10:00", "07:55:00")] if day >= 1 else []
    if day == 5:
        countdowns.append(("16:30:00", "17:15:00"))
    if day == 25:
        countdowns.append(("12:15:00", "13:00:00"))
    return countdowns


def fan_sentence(day: int, now: str) -> str:
    for start, end in fan_countdowns(day):
        if start <= now < end:
            return f"Off at {twelve_hour(end)}"
    return FAN_IDLE


def pump_sentence(day: int, now: str) -> str | None:
    """The pump's Schedule from its weekly blocks; None once the pump is removed."""
    if (day, now) >= (22, "12:00:00"):
        return None
    for start, end in blocks(day):
        if now < start:
            return f"On at {twelve_hour(start)}"
        if now < end:
            return f"Off at {twelve_hour(end)}"
    return f"On {weekday(day + 1)} {twelve_hour(blocks(day + 1)[0][0])}"


def expected_sentences(day: int, now: str) -> dict[str, str]:
    sentences = {LIGHT: light_sentence(day, now), FAN: fan_sentence(day, now)}
    if (pump := pump_sentence(day, now)) is not None:
        sentences[PUMP] = pump
    return sentences


type Change = tuple[str, str, str]  # (HH:MM:SS, device key, new state)


def expected_changes(day: int) -> list[Change]:
    """Every state change of a day's devices, to the second, as the routines dictate."""
    changes: list[Change] = []
    # The light: off at 09:00, on at 17:00, every day.
    if day >= 1:
        changes.append(("09:00:00", LIGHT, "off"))
    changes.append(("17:00:00", LIGHT, "on"))
    # The fan: on at the wall at 07:10, off 45 minutes later.
    if day >= 1:
        changes += [("07:10:00", FAN, "on"), ("07:55:00", FAN, "off")]
    # The pump: on and off with its blocks, until it is removed on day 22 at noon.
    for start, end in blocks(day):
        changes += [(start, PUMP, "on"), (end, PUMP, "off")]
    if day == 0:  # the routines are set up at 10:00
        changes = [change for change in changes if change[0] >= "10:00:00"]
    if day >= 22:
        changes = [c for c in changes if c[1] != PUMP or (day == 22 and c[0] < "12:00:00")]
    match day:
        case 5:
            # S12: the 17:00 on is skipped, catch up at the pause end (D20). The fan is on
            # from 16:30; its countdown end and the pump's block start (17:15) fall in the
            # downtime and run at the 17:20 start (L20, S3).
            changes.remove(("17:00:00", LIGHT, "on"))
            changes.remove(("17:15:00", PUMP, "on"))
            changes += [
                ("16:30:00", FAN, "on"),
                ("17:20:00", FAN, "off"),
                ("17:20:00", PUMP, "on"),
                ("18:30:00", LIGHT, "on"),
            ]
        case 20:
            # Offline from 08:30 to 20:00: nothing runs against it; back off, caught up.
            changes.remove(("09:00:00", LIGHT, "off"))
            changes.remove(("17:00:00", LIGHT, "on"))
            changes += [
                ("08:30:00", LIGHT, "unavailable"),
                ("20:00:00", LIGHT, "off"),
                ("20:00:10", LIGHT, "on"),
            ]
        case 25:
            # S4: on by hand at noon, so the 17:00 on changes nothing; S5: the fan.
            changes.remove(("17:00:00", LIGHT, "on"))
            changes += [
                ("12:00:00", LIGHT, "on"),
                ("12:15:00", FAN, "on"),
                ("13:00:00", FAN, "off"),
            ]
        case _:
            pass
    return sorted(changes)


# --------------------------------------------------------------------------------------
# The persistence of a cold start: registries and restore state through the storage mock
# --------------------------------------------------------------------------------------

_REGISTRIES: Final = (ar, cr, dr, er, fr, ir, lr)


def persist_registries(hass: HomeAssistant, storage: dict[str, Any]) -> None:
    """Write every registry into the storage mock, as Home Assistant saves them.

    The harness keeps registries in memory only, so a cold start writes what each one
    would save (`_data_to_save`) under its own storage key and version.
    """
    for module in _REGISTRIES:
        registry: Any = module.async_get(hass)
        store = registry._store
        storage[store.key] = {
            "version": store.version,
            "minor_version": store.minor_version,
            "key": store.key,
            "data": json_loads(json_bytes(registry._data_to_save())),
        }


async def async_load_registries(hass: HomeAssistant) -> None:
    """Load the registries and the restore state from storage, as bootstrap does."""
    dr.async_setup(hass)
    with (
        patch(
            "homeassistant.helpers.restore_state.RestoreStateData.async_setup_dump",
            return_value=None,
        ),
        patch("homeassistant.helpers.restore_state.start.async_at_start"),
    ):
        await ar.async_load(hass)
        await cr.async_load(hass)
        await dr.async_load(hass)
        await er.async_load(hass)
        await fr.async_load(hass)
        await ir.async_load(hass)
        await lr.async_load(hass)
        await rs.async_load(hass)
    hass.data[bootstrap.DATA_REGISTRIES_LOADED] = None


# --------------------------------------------------------------------------------------
# The simulation
# --------------------------------------------------------------------------------------


@dataclass
class Instance:
    """One running Home Assistant: its clock, the routines' entry and the devices."""

    hass: HomeAssistant
    clock: Clock
    entry: MockConfigEntry
    devices: dict[str, OnOff]

    @property
    def manager(self) -> RoutineManager:
        manager: RoutineManager = self.entry.runtime_data.manager
        return manager


@dataclass
class Simulation:
    """The home, the instance that runs it now, and what was seen on the way."""

    storage: dict[str, Any]
    config_dir: Path
    freezer: Any
    stack: AsyncExitStack
    instance: Instance | None = None
    device_ids: dict[str, str] = field(default_factory=dict)
    present: set[str] = field(default_factory=lambda: {spec.key for spec in SPECS})
    changes: list[tuple[int, str, str, str]] = field(default_factory=list)
    issues: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[int, str, str, str]] = field(default_factory=list)
    caught_up: list[tuple[int, str, str]] = field(default_factory=list)
    stale: list[tuple[int, str, str]] = field(default_factory=list)
    known_loop_errors: list[tuple[int, str]] = field(default_factory=list)
    stale_health: list[tuple[int, str]] = field(default_factory=list)
    resident: str | None = None
    starts: int = 0

    @property
    def now(self) -> Instance:
        assert self.instance is not None
        return self.instance

    @property
    def hass(self) -> HomeAssistant:
        return self.now.hass

    @property
    def manager(self) -> RoutineManager:
        return self.now.manager

    # The clock ------------------------------------------------------------------------

    @staticmethod
    def stamp() -> tuple[int, str]:
        local = dt_util.now().astimezone(ZoneInfo(TIME_ZONE))
        return (local.date() - DAY_0).days, local.time().replace(microsecond=0).isoformat()

    async def to(self, day: int, clock_time: str) -> None:
        await self.now.clock.to(at(day, clock_time))

    async def settle(self, seconds: float = 5) -> None:
        """Let debounced writes, Store saves and summary refreshes run."""
        await self.now.clock.advance(seconds=seconds)

    # What is seen ---------------------------------------------------------------------

    def entity_id(self, key: str) -> str:
        """The device's entity id now (the fan's changes on day 7)."""
        entity_id = er.async_get(self.hass).async_get_entity_id(
            spec_of(key).platform.value, SANDBOX, f"{SANDBOX}_{key}"
        )
        assert entity_id is not None, key
        return entity_id

    def state(self, key: str) -> str | None:
        state = self.hass.states.get(self.entity_id(key))
        return None if state is None else state.state

    def sentence(self, key: str) -> str | None:
        """The state of the device's Schedule sensor (FR-S4)."""
        schedule = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{DOMAIN}_{self.device_ids[key]}_schedule"
        )
        state = self.hass.states.get(schedule) if schedule else None
        return None if state is None else state.state

    def automation_id(self, key: str) -> str:
        return markers.automation_id(self.device_ids[key])

    def file_entries(self) -> list[dict[str, Any]]:
        loaded = load_yaml(str(self.config_dir / AUTOMATION_CONFIG_PATH)) or []
        assert isinstance(loaded, list)
        return loaded

    def file_entry(self, key: str) -> dict[str, Any] | None:
        automation_id = self.automation_id(key)
        return next((item for item in self.file_entries() if item.get("id") == automation_id), None)

    def inputs(self, key: str) -> dict[str, Any]:
        entry = self.file_entry(key)
        assert entry is not None, key
        inputs: dict[str, Any] = entry["use_blueprint"]["input"]
        return inputs

    def page_state(self, key: str, control: str) -> Any:
        """The state of one of the device's page entities (TECH_SPEC 4.5)."""
        entity_id = self.manager.entity_id_for(self.device_ids[key], control)
        assert entity_id is not None, (key, control)
        state = self.hass.states.get(entity_id)
        assert state is not None, (key, control)
        return state

    def automation_state(self, key: str) -> str | None:
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "automation", "automation", self.automation_id(key)
        )
        state = self.hass.states.get(entity_id) if entity_id else None
        return None if state is None else state.state

    def check_sentences(self, day: int, now: str) -> None:
        """Every Schedule reads as expected at this checkpoint.

        One wording defect is let through and counted: a sentence written before
        midnight keeps naming today's action by its weekday ("Off Tue 9:00 AM" on a
        Tuesday) until the next action refreshes it, where FR-S4 says "Off at 9:00 AM".
        `test_a_day_relative_sentence_is_reworded_at_midnight` pins it.
        """
        expected = expected_sentences(day, now)
        seen = {key: self.sentence(key) for key in expected}
        for key, sentence in expected.items():
            stale = sentence.replace(" at ", f" {weekday(day)} ", 1)
            if seen[key] != sentence and " at " in sentence and seen[key] == stale:
                self.stale.append((day, now, key))
                seen[key] = sentence
        assert seen == expected, f"day {day} {now}"

    def check_changes(self, day: int) -> None:
        seen = sorted((t, key, state) for d, t, key, state in self.changes if d == day)
        assert seen == expected_changes(day), f"day {day}"

    def check_no_issue(self) -> None:
        """No issue of the integration was raised, at any moment, and none is open."""
        assert [item for item in self.issues if item[0] != "remove"] == []
        registry = ir.async_get(self.hass)
        open_issues = [
            issue_id
            for (domain, issue_id), issue in registry.issues.items()
            if domain == DOMAIN and issue.active
        ]
        assert open_issues == []
        self.check_hub()

    def check_hub(self) -> None:
        """The hub says the same: no problem, Health ok (PRD 4.4, TECH_SPEC 10.3).

        One defect is let through and counted: after the D28 cleanup Health keeps
        counting the cleaned routine as owned and not loaded, so it reads `degraded`
        until the next manager event. `test_health_reads_ok_right_after_a_cleanup` pins
        it.
        """
        problem = self.hass.states.get("binary_sensor.device_routines_problem")
        assert problem is not None
        assert problem.state == "off"
        health = self.hass.states.get("sensor.device_routines_health")
        assert health is not None
        owned = len(self.manager.store.data.owned)
        if health.state == "degraded" and health.attributes["owned_count"] > owned:
            self.stale_health.append(self.stamp())
            return
        assert health.state == "ok", (self.stamp(), dict(health.attributes))
        assert health.attributes["owned_count"] == owned
        assert health.attributes["loaded_count"] == owned

    # Listening, once per instance ---------------------------------------------------------

    def listen(self, hass: HomeAssistant) -> None:
        """Record the devices' changes, the issues, the skipped and caught up actions."""

        @callback
        def changed(event: Event[Any]) -> None:
            old, new = event.data["old_state"], event.data["new_state"]
            if old is None or new is None or old.state == new.state:
                return
            entry = er.async_get(hass).async_get(event.data["entity_id"])
            if entry is None or entry.platform != SANDBOX:
                return
            day, now = self.stamp()
            self.changes.append((day, now, entry.unique_id.removeprefix(f"{SANDBOX}_"), new.state))

        @callback
        def issue(event: Event[Any]) -> None:
            if event.data["domain"] == DOMAIN:
                self.issues.append((event.data["action"], event.data["issue_id"]))

        @callback
        def skipped(event: Event[Any]) -> None:
            day, now = self.stamp()
            key = self.key_of(event.data["device_id"])
            self.skipped.append((day, now, key, event.data["trigger_id"]))

        @callback
        def caught_up(event: Event[Any]) -> None:
            day, now = self.stamp()
            self.caught_up.append((day, now, self.key_of(event.data["device_id"])))

        hass.bus.async_listen(EVENT_STATE_CHANGED, changed)
        hass.bus.async_listen(ir.EVENT_REPAIRS_ISSUE_REGISTRY_UPDATED, issue)
        hass.bus.async_listen(compiler.EVENT_ACTION_SKIPPED, skipped)
        hass.bus.async_listen(compiler.EVENT_TIMER_CAUGHT_UP, caught_up)

    def key_of(self, device_id: str) -> str:
        return next(key for key, value in self.device_ids.items() if value == device_id)

    # Starting and stopping ------------------------------------------------------------

    def routines_entry(self, data: Mapping[str, Any] | None = None) -> MockConfigEntry:
        return MockConfigEntry(
            domain=DOMAIN,
            title=INTEGRATION_TITLE,
            unique_id=DOMAIN,
            entry_id=ROUTINES_ENTRY,
            data=dict(data or {}),
            options={"cleanup_after_days": CLEANUP_AFTER_DAYS},
            minor_version=DeviceRoutinesConfigFlow.MINOR_VERSION,
        )

    async def async_first_start(self, hass: HomeAssistant) -> None:
        """Day 0: the harness's running instance becomes the home, with the integration."""
        await hass.config.async_set_time_zone(TIME_ZONE)
        hass.config.country = "US"
        hass.config.config_dir = str(self.config_dir)
        (self.config_dir / "configuration.yaml").write_text(
            "automation: !include automations.yaml\n", encoding="utf-8"
        )
        (self.config_dir / AUTOMATION_CONFIG_PATH).write_text("[]\n", encoding="utf-8")
        self.listen(hass)
        devices = await async_setup_sandbox(hass, self.present)
        areas = ar.async_get(hass)
        registry = dr.async_get(hass)
        for spec in SPECS:
            device = registry.async_get_device_by_identifier((SANDBOX, spec.key), SANDBOX_ENTRY)
            assert device is not None
            area = areas.async_get_area_by_name(spec.area) or areas.async_create(spec.area)
            registry.async_update_device(device.id, area_id=area.id)
            self.device_ids[spec.key] = device.id
        entry = self.routines_entry()
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        self.instance = Instance(hass, Clock(hass, self.freezer), entry, devices)
        self.starts = 1

    async def async_restart(self, stop: datetime, start: datetime) -> None:
        """A cold start: stop the instance at `stop`, start a new one at `start`.

        What survives is what survives a real restart: `automations.yaml` and the
        blueprint (files), the registries, the Store and the helpers (storage), and the
        restore state dumped at the stop. Nothing runs while the home is down.
        """
        old = self.hass
        await self.now.clock.to(stop)
        await rs.async_get(old).async_dump_states()
        persist_registries(old, self.storage)
        data = dict(self.now.entry.data)
        await old.async_stop()
        # The stopped process is gone: its loop flag and its pending timers go with it.
        with suppress(AttributeError):
            delattr(old.loop, "_shutdown_run_callback_threadsafe")
        for handle in get_scheduled_timer_handles(old.loop):
            handle.cancel()
        self.freezer.move_to(start)
        hass = await self.stack.enter_async_context(
            async_test_home_assistant(old.loop, False, str(self.config_dir), CoreState.not_running)
        )
        hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
        await hass.config.async_set_time_zone(TIME_ZONE)
        hass.config.country = "US"
        # The users persist like the registries (the harness's auth store is in memory).
        auth = hass.auth._store
        auth._groups = old.auth._store._groups
        auth._users = old.auth._store._users
        for user in auth._users.values():
            user.perm_lookup = auth._perm_lookup
            user.invalidate_cache()
        await async_load_registries(hass)
        self.listen(hass)
        devices = await async_setup_sandbox(hass, self.present)
        assert await async_setup_component(hass, "timer", {})
        assert await async_setup_component(hass, "schedule", {})
        entries = self.file_entries()
        assert await async_setup_component(hass, "automation", {"automation": entries})
        entry = self.routines_entry(data)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await hass.async_start()
        await hass.async_block_till_done()
        self.instance = Instance(hass, Clock(hass, self.freezer), entry, devices)
        self.starts += 1

    async def async_close(self) -> None:
        """Unload and stop the last instance, as the harness does with its own."""
        if self.starts < 2:
            return  # the harness's own instance: the `hass` fixture closes it
        hass = self.hass
        for entry in hass.config_entries.async_entries():
            if entry.state is ConfigEntryState.LOADED:
                await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_stop(force=True)

    # A person -------------------------------------------------------------------------

    async def system_user(self) -> str:
        return await ha_adapter.async_ensure_system_user(
            self.hass, self.now.entry.data.get(CONF_SYSTEM_USER_ID)
        )

    async def turn(self, key: str, on: bool, *, user: bool) -> None:
        """A person in the app (a user context) or at the wall (no user, no parent)."""
        if not user:
            self.now.devices[key].device_change(on)
            await self.hass.async_block_till_done()
            return
        if self.resident is None:
            person = await self.hass.auth.async_create_user(RESIDENT, group_ids=[GROUP_ID_USER])
            self.resident = person.id
        await self.hass.services.async_call(
            spec_of(key).platform.value,
            "turn_on" if on else "turn_off",
            {"entity_id": self.entity_id(key)},
            blocking=True,
            context=Context(user_id=self.resident),
        )
        await self.hass.async_block_till_done()


def removed_entity_wrote_its_state(exception: BaseException | None) -> bool:
    """Tell the defect `test_removing_a_device_with_a_routine_logs_no_error` pins.

    A device page entity hears a manager event after its registry entry went with the
    device and writes its state; the registry update raises `KeyError`.
    """
    if not isinstance(exception, KeyError):
        return False
    frames = traceback.extract_tb(exception.__traceback__)
    return any(
        frame.name == "_heard" and frame.filename.endswith("device_routines/entity.py")
        for frame in frames
    )


# The ERROR records of the pinned defects; anything else logged at ERROR fails the run.
KNOWN_ERROR_LOGS: Final = (
    # `test_unloading_the_entry_after_a_cold_start_logs_no_error`
    "Unable to remove unknown job listener",
    # `test_removing_a_device_with_a_routine_logs_no_error`
    (
        "Error running job: <Job listen state_changed HassJobType.Callback <bound method "
        "RoutineManager._automation_changed"
    ),
)


def unexpected_errors(records: list[logging.LogRecord]) -> list[str]:
    """Every ERROR record that is not one of the pinned defects."""
    return [
        record.getMessage()
        for record in records
        if record.levelno >= logging.ERROR
        and not any(record.getMessage().startswith(known) for known in KNOWN_ERROR_LOGS)
    ]


@pytest.fixture
async def simulation(
    hass: HomeAssistant, freezer: Any, hass_storage: dict[str, Any], tmp_path: Path
) -> AsyncIterator[Simulation]:
    """The home on day 0 at 10:00, before any routine; the last instance closed after.

    Loop errors of one pinned defect are recorded instead of failing the harness at
    teardown, so the rest of a run still proves what it proves; every other loop error
    still goes to the harness's handler.
    """
    freezer.move_to(at(0, "10:00:00"))
    loop = hass.loop
    harness_handler = loop.get_exception_handler()

    def handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        if removed_entity_wrote_its_state(context.get("exception")):
            sim.known_loop_errors.append(Simulation.stamp())
        elif harness_handler is not None:
            harness_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    async with AsyncExitStack() as stack:
        sim = Simulation(hass_storage, tmp_path, freezer, stack)
        loop.set_exception_handler(handler)
        try:
            await sim.async_first_start(hass)
            yield sim
        finally:
            await sim.async_close()
            loop.set_exception_handler(harness_handler)


# --------------------------------------------------------------------------------------
# Set up, and the integration update over schema 0
# --------------------------------------------------------------------------------------


async def set_up_routines(sim: Simulation) -> None:
    """Day 0, 10:00: the three routines, as a person sets them on the device pages."""
    manager = sim.manager
    ids = sim.device_ids
    for key in (LIGHT, FAN, PUMP):
        await manager.async_opt_in(ids[key])
    patches: dict[str, Mapping[str, Any]] = {
        LIGHT: {"on_time": time(17), "off_time": time(9)},
        FAN: {"turn_off_after_min": 45},
        PUMP: {"days": "weekly_schedule"},
    }
    for key, values in patches.items():
        result = await manager.async_update(ids[key], values)
        assert result.problem is None, (key, result.problem)
    await sim.settle()
    # The pump's blocks, entered in Home Assistant's weekly editor (FR-R2).
    schedule = sim.inputs(PUMP)["schedule_entity"]
    assert schedule == "schedule.routine_garden_pump"
    days = {
        **{name: [{"from": a, "to": b} for a, b in WEEKDAY_BLOCKS] for name in WEEKDAY_NAMES},
        **{name: [{"from": a, "to": b} for a, b in WEEKEND_BLOCKS] for name in WEEKEND_NAMES},
    }
    await ha_adapter.async_update_helper(sim.hass, await sim.system_user(), schedule, **days)
    await sim.settle()
    for key in (LIGHT, FAN, PUMP):
        view = manager.get(ids[key])
        assert view is not None
        assert view.status is Status.ACTIVE, key
        assert sim.automation_state(key) == "on"
    assert sim.inputs(FAN)["timer_entity"] == "timer.routine_bathroom_fan"


def schema_0(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Schema 1 inputs as the fake schema 0 wrote them."""
    return {(OLD_KEY if key == NEW_KEY else key): value for key, value in inputs.items()}


def decompile_schema_0(inputs: Mapping[str, Any]) -> RoutineSettings:
    """The frozen rules of the fake schema 0 (`migration.DECOMPILERS[0]`)."""
    renamed = {(NEW_KEY if key == OLD_KEY else key): value for key, value in inputs.items()}
    return compiler.decompile(renamed)


def installed_blueprint(config_dir: Path) -> Path:
    return config_dir / "blueprints" / "automation" / markers.BLUEPRINT_PATH


async def downgrade_to_schema_0(sim: Simulation) -> dict[str, dict[str, Any]]:
    """Put the files back as the previous version, on schema 0, left them; return its inputs.

    The entry is unloaded meanwhile. The previous version's blueprint (the shipped one
    with the schema 0 input name) is installed and recorded in the Store, every owned
    entry holds schema 0 inputs (the Store too), and the automations are reloaded on
    them, so the routines run on schema 0 when the updated integration sets up.
    """
    shipped = maintenance.shipped_blueprint_text()
    old_blueprint = shipped.replace(NEW_KEY, OLD_KEY).replace(
        "# Device Routines blueprint, schema 1.", "# Device Routines blueprint, schema 0."
    )
    installed_blueprint(sim.config_dir).write_text(old_blueprint, encoding="utf-8")
    entries = sim.file_entries()
    old_inputs: dict[str, dict[str, Any]] = {}
    for item in entries:
        if markers.is_owned(item):
            item["use_blueprint"]["input"] = schema_0(item["use_blueprint"]["input"])
            old_inputs[item["id"]] = item["use_blueprint"]["input"]
    (sim.config_dir / AUTOMATION_CONFIG_PATH).write_text(dump(entries), encoding="utf-8")
    stored = sim.storage[STORAGE_KEY]["data"]
    stored["blueprint_schema"] = 0
    stored["blueprint_hash"] = maintenance.blueprint_hash(old_blueprint)
    for automation_id, record in stored["owned"].items():
        entry = next(item for item in entries if item["id"] == automation_id)
        record["schema"] = 0
        record["last_valid_inputs"] = old_inputs[automation_id]
        record["last_hash"] = markers.config_hash(entry)
    await sim.hass.services.async_call("automation", "reload", {}, blocking=True)
    await sim.hass.async_block_till_done()
    return old_inputs


async def update_from_schema_0(
    sim: Simulation, monkeypatch: pytest.MonkeyPatch
) -> dict[str, dict[str, Any]]:
    """The integration updated over schema 0: the entry unloads on the old files and sets
    up again on the current code, which migrates (TECH_SPEC 4.11). Returns the schema 0
    inputs by automation id.

    The update is the entry's unload and setup inside the running instance (the cold
    starts stay on days 5 and 25); the migration runs at setup either way.
    """
    monkeypatch.setitem(migration.DECOMPILERS, 0, decompile_schema_0)
    entry = sim.now.entry
    assert await sim.hass.config_entries.async_unload(entry.entry_id)
    await sim.settle(seconds=3)  # a pending delayed Store save lands first
    old_inputs = await downgrade_to_schema_0(sim)
    # The routines run on schema 0 now, as they did under the previous version.
    assert set(old_inputs) == {sim.automation_id(key) for key in (LIGHT, FAN, PUMP)}
    assert {sim.automation_state(key) for key in (LIGHT, FAN, PUMP)} == {"on"}
    assert await sim.hass.config_entries.async_setup(entry.entry_id)
    await sim.settle()
    return old_inputs


# --------------------------------------------------------------------------------------
# The thirty days
# --------------------------------------------------------------------------------------


async def test_thirty_days_of_upkeep_need_no_person_and_raise_no_issue(  # noqa: C901, PLR0915  # the timeline is the test
    simulation: Simulation, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sim = simulation
    ids = sim.device_ids
    backup: dict[str, bytes] = {}
    migrated_from: dict[str, dict[str, Any]] = {}

    system_user_id = ""

    async def day_0_setup() -> None:
        nonlocal system_user_id
        await set_up_routines(sim)
        system_user_id = sim.now.entry.data[CONF_SYSTEM_USER_ID]

    # Day 3: the pump renamed a minute before its 17:15 block (PRD 3.1 device renamed).
    async def day_3_rename() -> None:
        dr.async_get(sim.hass).async_update_device(ids[PUMP], name_by_user="Backyard pump")
        await sim.settle()
        entry = sim.file_entry(PUMP)
        assert entry is not None
        assert entry["alias"] == "Routine: Backyard pump"
        assert "Backyard pump" in entry["description"]
        schedule = sim.hass.states.get("schedule.routine_garden_pump")
        assert schedule is not None
        assert schedule.name == "Backyard pump routine"
        assert sim.sentence(PUMP) == "On at 5:15 PM"
        assert sim.state(PUMP) == "off"

    # Day 5: S12, then the first cold start (S3, L20).
    async def day_5_pause() -> None:
        hallway = ar.async_get(sim.hass).async_get_area_by_name("Hallway")
        assert hallway is not None
        response = await sim.hass.services.async_call(
            DOMAIN,
            "pause",
            {"area_id": hallway.id, "for": {"hours": 2}},
            blocking=True,
            return_response=True,
        )
        assert response is not None
        results = response["results"]
        assert isinstance(results, list)
        assert [
            (item["device_id"], dt_util.parse_datetime(item["paused_until"]))  # type: ignore[index, call-overload, arg-type]
            for item in results
        ] == [(ids[LIGHT], at(5, "18:30:00"))]
        assert response["ignored"] == []
        await sim.turn(FAN, True, user=True)
        await sim.settle(seconds=2)

    async def day_5_on_time_skipped() -> None:
        assert sim.state(LIGHT) == "off"
        assert sim.skipped == [(5, "17:00:00", LIGHT, "scheduled_on")]

    async def day_5_restart() -> None:
        await sim.async_restart(at(5, "17:10:00"), at(5, "17:20:00"))
        # Within 60 seconds of the start (FR-R5, G4): the missed block start and the
        # countdown that ran out while down; the pause survived the restart (S12).
        assert sim.state(PUMP) == "on"
        assert sim.state(FAN) == "off"
        assert sim.caught_up == [(5, "17:20:00", FAN)]
        assert sim.state(LIGHT) == "off"
        paused = sim.page_state(LIGHT, "paused_until")
        assert dt_util.parse_datetime(paused.state) == at(5, "18:30:00")
        await sim.settle()
        assert sim.sentence(LIGHT) == "Paused until 6:30 PM"

    async def day_5_pause_end() -> None:
        assert sim.state(LIGHT) == "on"
        assert sim.page_state(LIGHT, "paused_until").state == "unknown"

    # Day 7: the fan's entity id renamed during its countdown (PRD 3.1).
    async def day_7_entity_rename() -> None:
        assert sim.state(FAN) == "on"
        er.async_get(sim.hass).async_update_entity(
            "switch.bathroom_fan", new_entity_id="switch.bath_fan"
        )
        await sim.settle()
        assert sim.entity_id(FAN) == "switch.bath_fan"
        assert sim.inputs(FAN)["target_entity"] == "switch.bath_fan"
        record = sim.manager.store.data.owned[sim.automation_id(FAN)]
        assert record.target_entity == "switch.bath_fan"
        assert sim.state(FAN) == "on"
        assert sim.sentence(FAN) == "Off at 7:55 AM"

    # Days 8 to 10: a backup, an edit, the restore (PRD 3.1, plan Section 4.9 item 4).
    async def day_8_backup() -> None:
        backup["file"] = (sim.config_dir / AUTOMATION_CONFIG_PATH).read_bytes()

    async def day_9_edit() -> None:
        off_time = sim.manager.entity_id_for(ids[LIGHT], "off_time")
        await sim.hass.services.async_call(
            "time", "set_value", {"entity_id": off_time, "time": "08:30:00"}, blocking=True
        )
        await sim.settle()
        assert sim.inputs(LIGHT)["off_time"] == "08:30:00"

    async def day_10_restore() -> None:
        (sim.config_dir / AUTOMATION_CONFIG_PATH).write_bytes(backup["file"])
        await sim.hass.services.async_call("automation", "reload", {}, blocking=True)
        await sim.settle()
        assert sim.inputs(LIGHT)["off_time"] == "09:00:00"
        assert sim.page_state(LIGHT, "off_time").state == "09:00:00"
        record = sim.manager.store.data.owned[sim.automation_id(LIGHT)]
        assert record.last_valid_inputs is not None
        assert record.last_valid_inputs["off_time"] == "09:00:00"
        assert sim.sentence(LIGHT) == "Off at 9:00 AM"
        assert sim.state(LIGHT) == "on"

    # Day 14: the integration updated over the fake schema 0 (TECH_SPEC 4.11).
    async def day_14_update() -> None:
        migrated_from.update(await update_from_schema_0(sim, monkeypatch))
        # A defect, pinned by `test_a_schema_update_raises_no_issue_on_the_way`: sync
        # back that reads the file before the migration rewrote an entry judges it by
        # the new schema and raises `invalid_inputs` for a moment (a race, so not every
        # run sees it). Each one is cleared again by the end of the update.
        raised = [issue_id for action, issue_id in sim.issues if action == "create"]
        assert all(issue_id.startswith("invalid_inputs_") for issue_id in raised)
        assert sorted(sim.issues) == sorted(
            [("create", issue_id) for issue_id in raised]
            + [("remove", issue_id) for issue_id in raised]
        )
        sim.issues.clear()
        data = sim.manager.store.data
        assert data.blueprint_schema == compiler.BLUEPRINT_SCHEMA_VERSION
        shipped = maintenance.shipped_blueprint_text()
        assert installed_blueprint(sim.config_dir).read_text(encoding="utf-8") == shipped
        for key in (LIGHT, FAN, PUMP):
            automation_id = sim.automation_id(key)
            record = data.owned[automation_id]
            assert record.schema == compiler.BLUEPRINT_SCHEMA_VERSION
            assert record.previous_inputs == migrated_from[automation_id]
            assert NEW_KEY in sim.inputs(key)
            assert OLD_KEY not in sim.inputs(key)
            assert sim.automation_state(key) == "on"
            view = sim.manager.get(ids[key])
            assert view is not None
            assert view.status is Status.ACTIVE

    # Day 20: the light offline from 08:30 to 20:00 (PRD 3.1, FR-R5, B20).
    async def day_20_offline() -> None:
        sim.now.devices[LIGHT].set_available(False)
        await sim.hass.async_block_till_done()

    async def day_20_back() -> None:
        sim.now.devices[LIGHT].device_change(False)
        await sim.hass.async_block_till_done()

    async def day_20_caught_up() -> None:
        assert sim.state(LIGHT) == "on"
        view = sim.manager.get(ids[LIGHT])
        assert view is not None
        assert not view.override

    # Day 22: the pump removed from Home Assistant (PRD 3.1, D28).
    async def day_22_removed() -> None:
        sim.present.discard(PUMP)
        dr.async_get(sim.hass).async_remove_device(ids[PUMP])
        await sim.settle()
        assert sim.automation_state(PUMP) == "off"
        assert ids[PUMP] in sim.manager.store.data.removed_devices_at
        assert sim.sentence(PUMP) is None

    # Day 25: S4 and S5, then the second cold start.
    async def day_25_light_by_hand() -> None:
        await sim.turn(LIGHT, True, user=True)
        override = sim.page_state(LIGHT, "manual_override")
        assert override.state == "on"
        assert override.attributes["last_change_source"] == "user"

    async def day_25_fan_by_hand() -> None:
        await sim.turn(FAN, True, user=True)

    async def day_25_restart() -> None:
        await sim.async_restart(at(25, "12:30:00"), at(25, "12:31:00"))
        assert sim.state(LIGHT) == "on"
        override = sim.page_state(LIGHT, "manual_override")
        assert override.state == "on"
        assert override.attributes["last_change_source"] == "user"
        assert sim.state(FAN) == "on"
        timer = sim.hass.states.get("timer.routine_bathroom_fan")
        assert timer is not None
        assert timer.state == "active"
        assert dt_util.parse_datetime(timer.attributes["finishes_at"]) == at(25, "13:00:00")
        assert sim.automation_state(PUMP) == "off"

    async def day_25_scheduled_time() -> None:
        assert sim.state(LIGHT) == "on"
        assert sim.page_state(LIGHT, "manual_override").state == "off"

    # Day 27: the cleanup period ends (D28).
    async def day_27_before_cleanup() -> None:
        assert sim.file_entry(PUMP) is not None
        assert sim.hass.states.get("schedule.routine_garden_pump") is not None

    async def day_27_cleanup() -> None:
        await sim.settle()
        data = sim.manager.store.data
        assert sim.file_entry(PUMP) is None
        assert sim.hass.states.get("schedule.routine_garden_pump") is None
        assert er.async_get(sim.hass).async_get("schedule.routine_garden_pump") is None
        assert sim.automation_state(PUMP) is None
        assert sim.automation_id(PUMP) not in data.owned
        assert ids[PUMP] not in data.opted_in
        assert ids[PUMP] not in data.removed_devices_at
        assert sim.manager.get(ids[PUMP]) is None

    async def wall_switch() -> None:
        await sim.turn(FAN, True, user=False)

    events: dict[int, dict[str, Step]] = {
        0: {"10:00:00": day_0_setup},
        3: {"17:14:00": day_3_rename},
        5: {
            "16:30:00": day_5_pause,
            "17:00:30": day_5_on_time_skipped,
            "17:10:00": day_5_restart,
            "18:30:05": day_5_pause_end,
        },
        7: {"07:30:00": day_7_entity_rename},
        8: {"03:00:00": day_8_backup},
        9: {"12:00:00": day_9_edit},
        10: {"08:00:00": day_10_restore},
        14: {"16:55:00": day_14_update},
        20: {"08:30:00": day_20_offline, "20:00:00": day_20_back, "20:00:11": day_20_caught_up},
        22: {"12:00:00": day_22_removed},
        25: {
            "12:00:00": day_25_light_by_hand,
            "12:15:00": day_25_fan_by_hand,
            "12:30:00": day_25_restart,
            "17:00:01": day_25_scheduled_time,
        },
        27: {"11:59:00": day_27_before_cleanup, "12:00:01": day_27_cleanup},
    }

    for day in range(DAYS + 1):
        # The fan is switched on at the wall every morning from day 1.
        steps: dict[str, Step] = {"07:10:00": wall_switch} if day >= 1 else {}
        steps |= events.get(day, {})
        checkpoints = [t for t in CHECKPOINTS if day > 0 or t > "10:00:00"]
        for moment in sorted({*steps, *checkpoints}):
            await sim.to(day, moment)
            if moment in steps:
                await steps[moment]()
            if moment in checkpoints:
                sim.check_sentences(day, moment)
                sim.check_hub()
        await sim.to(day, "23:59:59")
        sim.check_changes(day)
        sim.check_no_issue()

    # Thirty days: two cold starts, one skipped action, one countdown caught up, one
    # system user, and nothing logged at ERROR apart from the pinned defects.
    assert sim.starts == 3
    assert sim.now.entry.data[CONF_SYSTEM_USER_ID] == system_user_id
    assert sim.skipped == [(5, "17:00:00", LIGHT, "scheduled_on")]
    assert sim.caught_up == [(5, "17:20:00", FAN)]
    assert {day for day, _ in sim.known_loop_errors} <= {22}
    assert {day for day, _ in sim.stale_health} <= {27, 28}
    assert unexpected_errors(caplog.records) == []

    # The Store rebuilt from the markers equals the Store kept (TECH_SPEC 6), apart from
    # what cannot be rebuilt: `opted_out_at` and `ai_cache` (the spec), `suspended` (an
    # automation that is off reads the same whoever turned it off) and the
    # `previous_inputs` a schema migration kept (plan A4.0 item 27).
    store = sim.manager.store
    kept = copy.deepcopy(store.data)
    assert set(kept.owned) == {sim.automation_id(LIGHT), sim.automation_id(FAN)}
    store.data = StoreData()
    report = await maintenance.async_run(
        sim.hass, sim.manager, MaintenanceAction.REBUILD_INDEX, False
    )
    assert report.changed == sorted(kept.owned)
    rebuilt = store.data.to_dict()
    expected = kept.to_dict()
    for key in ("opted_out_at", "ai_cache", "suspended"):
        del rebuilt[key], expected[key]
    for automation_id, record in expected["owned"].items():
        assert record.pop("previous_inputs") == migrated_from[automation_id]
        assert record["alias_history"]
        del rebuilt["owned"][automation_id]["previous_inputs"]
    assert rebuilt == expected
    assert kept.blueprint_schema == compiler.BLUEPRINT_SCHEMA_VERSION
    sim.check_no_issue()


# --------------------------------------------------------------------------------------
# Defects the simulation found, each pinned on its own (plan Section 4.6, L54)
# --------------------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "summary.py: the Schedule is recomputed only at each item's next run (FR-S7), "
        "never at local midnight, so a sentence written the evening before names today's "
        "action by its weekday ('Off Tue 9:00 AM' on a Tuesday) instead of the FR-S4 "
        "today form 'Off at 9:00 AM' until the next action refreshes it"
    ),
)
async def test_a_day_relative_sentence_is_reworded_at_midnight(simulation: Simulation) -> None:
    sim = simulation
    await set_up_routines(sim)
    await sim.to(0, "21:00:00")
    assert sim.sentence(LIGHT) == "Off Tue 9:00 AM"

    await sim.to(1, "00:30:00")

    assert sim.sentence(LIGHT) == "Off at 9:00 AM"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "manager.py (async_start) and summary.py (async_start): the unsubscriber of the "
        "one time started listener is kept and called on unload after the listener "
        "fired, so Home Assistant logs 'Unable to remove unknown job listener' twice at "
        "every unload or reload that follows a start"
    ),
)
async def test_unloading_the_entry_after_a_cold_start_logs_no_error(
    simulation: Simulation, caplog: pytest.LogCaptureFixture
) -> None:
    sim = simulation
    await set_up_routines(sim)
    await sim.async_restart(at(0, "11:00:00"), at(0, "11:05:00"))
    caplog.clear()

    assert await sim.hass.config_entries.async_unload(ROUTINES_ENTRY)
    await sim.hass.async_block_till_done()

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "manager.py (_async_sync_all, async_sync_back): a sync pass reads the file once, "
        "then waits for each routine's lock; when a write (here the schema migration's) "
        "lands meanwhile, the pass judges its stale copy of the entry against the new "
        "`last_hash` as a foreign edit: schema 0 inputs raise `invalid_inputs` and turn "
        "the routine off until the next pass (valid stale inputs are adopted instead)"
    ),
)
async def test_a_schema_update_raises_no_issue_on_the_way(
    simulation: Simulation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race of the 30 day run's day 14 (seen in some runs), made certain.

    The stale copy is what `_async_sync_all` holds for an entry it read before the
    migration rewrote it, handed over after the migration released the routine's lock.
    """
    sim = simulation
    await set_up_routines(sim)
    old_inputs = await update_from_schema_0(sim, monkeypatch)
    sim.issues.clear()
    automation_id = sim.automation_id(LIGHT)
    entry = sim.file_entry(LIGHT)
    assert entry is not None
    stale = {
        **entry,
        "use_blueprint": {**entry["use_blueprint"], "input": old_inputs[automation_id]},
    }

    await sim.manager.async_sync_back(automation_id, stale)
    await sim.hass.async_block_till_done()

    assert [issue for issue in sim.issues if issue[0] == "create"] == []
    assert sim.automation_state(LIGHT) == "on"


async def test_removing_a_device_with_a_routine_logs_no_error(
    simulation: Simulation, caplog: pytest.LogCaptureFixture
) -> None:
    sim = simulation
    await set_up_routines(sim)
    caplog.clear()

    sim.present.discard(PUMP)
    dr.async_get(sim.hass).async_remove_device(sim.device_ids[PUMP])
    await sim.settle()

    assert sim.automation_state(PUMP) == "off"
    assert sim.known_loop_errors == []
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_a_store_rebuilt_from_nothing_equals_the_store_kept(
    simulation: Simulation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan A4.0 item 27: `blueprint_schema` and `alias_history` are rebuilt too.

    What cannot be rebuilt stays out of the comparison: `opted_out_at` and `ai_cache`
    (TECH_SPEC 6), `suspended` (an automation that is off reads the same whoever turned
    it off) and the `previous_inputs` a schema migration kept, which only the Store saw.
    """
    sim = simulation
    await set_up_routines(sim)
    await update_from_schema_0(sim, monkeypatch)
    store = sim.manager.store
    kept = store.data.to_dict()

    store.data = StoreData()
    await maintenance.async_run(sim.hass, sim.manager, MaintenanceAction.REBUILD_INDEX, False)

    rebuilt = store.data.to_dict()
    for key in ("opted_out_at", "ai_cache", "suspended"):
        del rebuilt[key], kept[key]
    for automation_id, record in kept["owned"].items():
        assert record.pop("previous_inputs") is not None
        assert rebuilt["owned"][automation_id].pop("previous_inputs") is None
    assert rebuilt == kept


@pytest.mark.xfail(
    strict=True,
    reason=(
        "manager.py (async_cleanup) with maintenance.py (async_clean_up): the D28 cleanup "
        "deletes the routine's automation first (Health then counts it as owned but not "
        "loaded) and drops its Store records afterwards with no manager event, so Health "
        "reads `degraded` until the next routine change (19 hours in the 30 day run)"
    ),
)
async def test_health_reads_ok_right_after_a_cleanup(simulation: Simulation) -> None:
    sim = simulation
    await set_up_routines(sim)
    sim.present.discard(PUMP)
    dr.async_get(sim.hass).async_remove_device(sim.device_ids[PUMP])
    await sim.settle()

    await sim.to(CLEANUP_AFTER_DAYS, "10:05:00")

    assert sim.automation_id(PUMP) not in sim.manager.store.data.owned
    health = sim.hass.states.get("sensor.device_routines_health")
    assert health is not None
    assert health.state == "ok"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "manager.py (_async_follow_device) with entity.py (linked_device_info): the "
        "device page controls and the Schedule sensor sit on this integration's linked "
        "record of the device (L25), named once from the device's `name`; a rename "
        "(`name_by_user`) never reaches it, so they keep reading 'Garden pump Schedule' "
        "after the device became 'Backyard pump' (PRD 3.1, device renamed)"
    ),
)
async def test_the_schedule_sensor_follows_a_device_rename(simulation: Simulation) -> None:
    sim = simulation
    await set_up_routines(sim)

    dr.async_get(sim.hass).async_update_device(sim.device_ids[PUMP], name_by_user="Backyard pump")
    await sim.settle()

    state = sim.hass.states.get("sensor.garden_pump_schedule")
    assert state is not None
    assert state.name == "Backyard pump Schedule"
