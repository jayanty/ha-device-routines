"""Fixtures for the manager tests (Build A lane 5): a synthetic home and a loaded entry.

`home` builds devices from another integration's config entry: a living room fan driven
by the real sandbox switch of the blueprint fixtures (so the shipped blueprint really
switches it), a desk lamp, a garage door cover and a contact sensor with nothing a routine
can drive, in a living room on a ground floor. `manager` loads the config entry in that
home with the real blueprint, which the manager installs itself, and returns the loaded
entry's `RoutineManager`.

The device page platforms arrive with Build A lane 8. Until then a small shim stands in
for the two entities the blueprint reads, the Manual override switch and the Paused until
datetime: they claim the registry entries the manager creates at opt in (same platform,
same unique ids), render the manager's runtime state and call the manager back, exactly
the contract lane 8 implements. Wave A4's contract tests prove the real chain.

Every name is generic and every id synthetic (CLAUDE.md Section 6).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    issue_registry as ir,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import dump, parse_yaml
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockPlatform,
    async_fire_time_changed,
    mock_platform,
)

import custom_components.device_routines as integration
from custom_components.device_routines import markers
from custom_components.device_routines.config_flow import DeviceRoutinesConfigFlow
from custom_components.device_routines.const import (
    DOMAIN,
    INTEGRATION_TITLE,
    KEY_MANUAL_OVERRIDE,
    KEY_PAUSED_UNTIL,
    PLATFORMS,
)
from custom_components.device_routines.manager import (
    DEBOUNCE_SECONDS,
    REASON_OPTED_IN,
    ManagerEvent,
    RoutineManager,
)
from custom_components.device_routines.summary import DEBOUNCE_SECONDS as SUMMARY_DEBOUNCE
from tests.blueprint.conftest import (  # noqa: F401  # fixtures re exported for this folder
    Clock,
    SandboxSwitch,
    clock,
    routine_config_dir,
    sandbox_switch,
    skipped_events,
)

FAN = "switch.living_room_fan"
LAMP = "light.desk_lamp"
GARAGE = "cover.garage_door"
DOOR = "binary_sensor.sandbox_contact"
OVERRIDE = "switch.living_room_fan_manual_override"
PAUSED = "datetime.living_room_fan_paused_until"
TIMER = "timer.routine_living_room_fan"
SCHEDULE = "schedule.routine_living_room_fan"
AUTOMATION = "automation.routine_living_room_fan"
ALIAS = "Routine: Living room fan"


@dataclass
class Home:
    """The synthetic home: device ids, the area, the floor and the fan's switch."""

    fan: str
    lamp: str
    garage: str
    door: str
    area: str
    floor: str
    switch: SandboxSwitch
    source: MockConfigEntry


def add_device(
    hass: HomeAssistant,
    source: MockConfigEntry,
    key: str,
    name: str,
    entity_id: str,
    state: str = "off",
    *,
    device_class: str | None = None,
) -> str:
    """Add a device of another integration with one registered entity and its state."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("sandbox", key)}, name=name
    )
    domain, _, object_id = entity_id.partition(".")
    er.async_get(hass).async_get_or_create(
        domain,
        "sandbox",
        key,
        device_id=device.id,
        suggested_object_id=object_id,
        original_device_class=device_class,
        config_entry=source,
    )
    attributes = {"friendly_name": name}
    if device_class:
        attributes["device_class"] = device_class
    hass.states.async_set(entity_id, state, attributes)
    return device.id


@pytest.fixture
async def home(
    hass: HomeAssistant,
    routine_config_dir: Path,  # noqa: F811  # the blueprint fixture, re exported above
    sandbox_switch: SandboxSwitch,  # noqa: F811  # the blueprint fixture, re exported above
) -> Home:
    """Build the synthetic home of the module docstring."""
    hass.config.country = "US"
    floor = fr.async_get(hass).async_create("Ground floor")
    area = ar.async_get(hass).async_create("Living room", floor_id=floor.floor_id)
    source = MockConfigEntry(domain="sandbox", title="Sandbox")
    source.add_to_hass(hass)
    devices = dr.async_get(hass)
    fan = devices.async_get_or_create(
        config_entry_id=source.entry_id, identifiers={("sandbox", "fan")}, name="Living room fan"
    )
    devices.async_update_device(fan.id, area_id=area.id)
    # The sandbox switch has no config entry, so its device link lasts until it is
    # added again (decision L36); the tests never add it again.
    er.async_get(hass).async_update_entity(FAN, device_id=fan.id)
    lamp = add_device(hass, source, "lamp", "Desk lamp", LAMP)
    devices.async_update_device(lamp, area_id=area.id)
    garage = add_device(
        hass, source, "garage", "Garage door", GARAGE, "closed", device_class="garage"
    )
    door = add_device(hass, source, "door", "Sandbox contact", DOOR, device_class="door")
    return Home(fan.id, lamp, garage, door, area.id, floor.floor_id, sandbox_switch, source)


# --------------------------------------------------------------------------------------
# The shim for the two entities the blueprint reads (Build A lane 8 replaces it)
# --------------------------------------------------------------------------------------


class _ShimEntity:
    """Renders the manager's runtime state of one device and follows its events."""

    _attr_should_poll = False
    _attr_unique_id: str | None = None

    def __init__(self, manager: RoutineManager, device_id: str, key: str) -> None:
        self.manager = manager
        self.device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{key}"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.manager.async_add_listener(self._heard))  # type: ignore[attr-defined]

    @callback
    def _heard(self, event: ManagerEvent) -> None:
        if event.device_id == self.device_id:
            self.async_write_ha_state()  # type: ignore[attr-defined]


class ShimOverride(_ShimEntity, SwitchEntity):
    """The Manual override switch: the manager's `override`, turned off by a person."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        super().__init__(manager, device_id, KEY_MANUAL_OVERRIDE)

    @property
    def is_on(self) -> bool:
        view = self.manager.get(self.device_id)
        return bool(view and view.override)

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        await self.manager.async_set_manual_override(self.device_id, on=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002  # the core's signature
        await self.manager.async_set_manual_override(self.device_id, on=False)


class ShimPausedUntil(_ShimEntity, DateTimeEntity):
    """The Paused until datetime: the manager's `paused_until`, set through `async_pause`."""

    def __init__(self, manager: RoutineManager, device_id: str) -> None:
        super().__init__(manager, device_id, KEY_PAUSED_UNTIL)

    @property
    def native_value(self) -> datetime | None:
        view = self.manager.get(self.device_id)
        return view.paused_until if view else None

    async def async_set_value(self, value: datetime) -> None:
        await self.manager.async_pause(self.device_id, until=value)


def _shim_platform(
    factory: Callable[[RoutineManager, str], _ShimEntity], key: str
) -> Callable[[HomeAssistant, ConfigEntry, AddEntitiesCallback], Awaitable[None]]:
    async def async_setup_entry(
        hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
    ) -> None:
        manager: RoutineManager = entry.runtime_data.manager

        @callback
        def add(device_ids: Iterator[str] | tuple[str, ...]) -> None:
            new = []
            for device_id in device_ids:
                entity_id = manager.entity_id_for(device_id, key)
                if entity_id is not None and hass.states.get(entity_id) is None:
                    new.append(factory(manager, device_id))
            async_add_entities(new)  # type: ignore[arg-type]

        @callback
        def heard(event: ManagerEvent) -> None:
            if event.reason == REASON_OPTED_IN and event.device_id is not None:
                add((event.device_id,))

        add(manager.opted_in_devices())
        entry.async_on_unload(manager.async_add_listener(heard))

    return async_setup_entry


@pytest.fixture
def options() -> dict[str, Any]:
    """The entry's options; a test overrides the fixture to change a setting."""
    return {}


@pytest.fixture
async def routines(
    hass: HomeAssistant, home: Home, options: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> MockConfigEntry:
    """Load the config entry in the home, with the shim platforms; return the entry."""
    # The real platforms load first: a platform import loads every name it is asked for,
    # so the two shims must be the only ones not yet cached.
    loaded = await async_get_integration(hass, DOMAIN)
    await loaded.async_get_platforms(PLATFORMS)
    mock_platform(
        hass,
        f"{DOMAIN}.switch",
        MockPlatform(async_setup_entry=_shim_platform(ShimOverride, KEY_MANUAL_OVERRIDE)),
    )
    mock_platform(
        hass,
        f"{DOMAIN}.datetime",
        MockPlatform(async_setup_entry=_shim_platform(ShimPausedUntil, KEY_PAUSED_UNTIL)),
    )
    monkeypatch.setattr(integration, "PLATFORMS", [*PLATFORMS, Platform.SWITCH, Platform.DATETIME])
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=INTEGRATION_TITLE,
        unique_id=DOMAIN,
        options=options,
        minor_version=DeviceRoutinesConfigFlow.MINOR_VERSION,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
def manager(routines: MockConfigEntry) -> RoutineManager:
    """The loaded entry's RoutineManager."""
    loaded: RoutineManager = routines.runtime_data.manager
    return loaded


# --------------------------------------------------------------------------------------
# Helpers the three manager test files share
# --------------------------------------------------------------------------------------


def automations_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.config_dir) / AUTOMATION_CONFIG_PATH


def file_entries(hass: HomeAssistant) -> list[dict[str, Any]]:
    loaded = parse_yaml(automations_path(hass).read_text(encoding="utf-8"))
    return list(loaded) if isinstance(loaded, list) else []


def file_entry(hass: HomeAssistant, automation_id: str) -> dict[str, Any] | None:
    return next((item for item in file_entries(hass) if item.get("id") == automation_id), None)


def inputs_of(hass: HomeAssistant, automation_id: str) -> dict[str, Any]:
    entry = file_entry(hass, automation_id)
    assert entry is not None, automation_id
    inputs: dict[str, Any] = entry["use_blueprint"]["input"]
    return inputs


def write_entries(hass: HomeAssistant, entries: Sequence[Mapping[str, Any]]) -> None:
    """Another writer (a person, the automation editor, git) saving the whole file."""
    automations_path(hass).write_text(dump([dict(item) for item in entries]), encoding="utf-8")


async def save_entry(hass: HomeAssistant, entry: Mapping[str, Any]) -> None:
    """Save one entry as the automation editor does: replace it, reload that id."""
    others = [item for item in file_entries(hass) if item.get("id") != entry["id"]]
    write_entries(hass, [*others, entry])
    await hass.services.async_call("automation", "reload", {"id": entry["id"]}, blocking=True)
    await hass.async_block_till_done()


async def reload_all(hass: HomeAssistant) -> None:
    await hass.services.async_call("automation", "reload", {}, blocking=True)
    await hass.async_block_till_done()


async def flush(hass: HomeAssistant, freezer: Any) -> None:
    """Let the one second debounce run out and the write finish."""
    freezer.tick(timedelta(seconds=DEBOUNCE_SECONDS + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def give_routine(
    hass: HomeAssistant, manager: RoutineManager, device_id: str, freezer: Any, **patch: Any
) -> str:
    """Opt a device in, apply a patch, write it; return the automation id.

    The summary's debounced index rebuild (two seconds) runs too, so the Schedule reads
    the new routine from its inputs.
    """
    await manager.async_opt_in(device_id)
    result = await manager.async_update(device_id, patch)
    assert result.problem is None, result.problem
    await flush(hass, freezer)
    freezer.tick(timedelta(seconds=SUMMARY_DEBOUNCE + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    view = manager.get(device_id)
    assert view is not None
    assert file_entry(hass, view.automation_id) is not None
    return view.automation_id


def issue_of(
    hass: HomeAssistant, issue_id: str, subject: str | None = None
) -> ir.IssueEntry | None:
    registry_id = issue_id if subject is None else f"{issue_id}_{subject}"
    return ir.async_get(hass).async_get_issue(DOMAIN, registry_id)


def state_of(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    return None if state is None else state.state


def now() -> datetime:
    return dt_util.utcnow()


__all__ = [
    "ALIAS",
    "AUTOMATION",
    "DOOR",
    "FAN",
    "GARAGE",
    "LAMP",
    "OVERRIDE",
    "PAUSED",
    "SCHEDULE",
    "TIMER",
    "Clock",
    "Home",
    "markers",
]
