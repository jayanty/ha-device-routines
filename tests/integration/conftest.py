"""Fixtures for the manager tests (Build A lane 5): a synthetic home and a loaded entry.

`home` builds devices from another integration's config entry: a living room fan driven
by the real sandbox switch of the blueprint fixtures (so the shipped blueprint really
switches it), a desk lamp, a garage door cover and a contact sensor with nothing a routine
can drive, in a living room on a ground floor. `manager` loads the config entry in that
home with the real blueprint, which the manager installs itself, and returns the loaded
entry's `RoutineManager`.

The device page platforms (Build A lane 8) are the real ones: the Manual override switch
and the Paused until datetime claim the registry entries the manager creates at opt in,
render the manager's runtime state and call the manager back, so the blueprint reads the
integration's own entities.

Every name is generic and every id synthetic (CLAUDE.md Section 6).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    issue_registry as ir,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import dump, parse_yaml
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import markers
from custom_components.device_routines.config_flow import DeviceRoutinesConfigFlow
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.manager import DEBOUNCE_SECONDS, RoutineManager
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


@pytest.fixture
def options() -> dict[str, Any]:
    """The entry's options; a test overrides the fixture to change a setting."""
    return {}


@pytest.fixture
async def routines(hass: HomeAssistant, home: Home, options: dict[str, Any]) -> MockConfigEntry:
    """Load the config entry in the home with every platform; return the entry."""
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
