"""Stage 0 V6, A2: writing one automation from code and reloading only that one.

TECH_SPEC 4.2's primary path replicates the config editor: load `automations.yaml`,
replace or append one entry, write the file atomically, then `automation.reload` with the
entry's id. A2 asks that this leaves every other automation running. The editor's own
lock is an instance attribute of its HTTP view (`BaseEditConfigView.mutation_lock`),
reachable only through the aiohttp router, so the adapter uses its own lock and a file
hash compare (the spec's stated alternative). A delete is a write plus a reload plus the
removal of the entity registry entry, as the editor's delete hook does.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from homeassistant.config import AUTOMATION_CONFIG_PATH
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump, load_yaml
import pytest

LONG_RUN = "automation.stage0_v6_long_run"
PROBE = "automation.stage0_v6_probe"


def long_run() -> dict[str, Any]:
    return {
        "id": "stage0_v6_long_run",
        "alias": "stage0 v6 long run",
        "triggers": [{"trigger": "event", "event_type": "stage0_v6_start"}],
        "actions": [{"delay": {"minutes": 10}}],
    }


def probe(minutes: int) -> dict[str, Any]:
    return {
        "id": "stage0_v6_probe",
        "alias": "stage0 v6 probe",
        "triggers": [{"trigger": "event", "event_type": "stage0_v6_probe"}],
        "actions": [{"delay": {"minutes": minutes}}],
    }


def write_entry(config_dir: Path, entry: dict[str, Any]) -> None:
    """The adapter's write: replace or append one entry by id, atomically."""
    path = config_dir / AUTOMATION_CONFIG_PATH
    current: list[dict[str, Any]] = load_yaml(str(path)) or []  # type: ignore[assignment]
    others = [item for item in current if item.get("id") != entry["id"]]
    write_utf8_file_atomic(str(path), dump([*others, entry]))


def delete_entry(config_dir: Path, entry_id: str) -> None:
    path = config_dir / AUTOMATION_CONFIG_PATH
    current: list[dict[str, Any]] = load_yaml(str(path)) or []  # type: ignore[assignment]
    write_utf8_file_atomic(str(path), dump([item for item in current if item["id"] != entry_id]))


@pytest.fixture
async def running(hass: HomeAssistant, tmp_path: Path) -> Path:
    """An instance with one automation whose run is in flight."""
    hass.config.config_dir = str(tmp_path)
    (tmp_path / "configuration.yaml").write_text(
        "automation: !include automations.yaml\n", encoding="utf-8"
    )
    (tmp_path / AUTOMATION_CONFIG_PATH).write_text("[]\n", encoding="utf-8")
    write_entry(tmp_path, long_run())
    assert await async_setup_component(
        hass, "automation", {"automation": load_yaml(str(tmp_path / AUTOMATION_CONFIG_PATH))}
    )
    await hass.async_block_till_done()
    hass.bus.async_fire("stage0_v6_start")
    await settle()
    assert hass.states.get(LONG_RUN).attributes["current"] == 1  # type: ignore[union-attr]
    return tmp_path


def in_flight(hass: HomeAssistant) -> int:
    state = hass.states.get(LONG_RUN)
    assert state is not None
    current: int = state.attributes["current"]
    return current


async def settle() -> None:
    """Let callbacks run without waiting for the in flight delay, as block_till_done would."""
    for _ in range(10):
        await asyncio.sleep(0)


async def reload_one(hass: HomeAssistant, entry_id: str) -> None:
    await hass.services.async_call("automation", "reload", {"id": entry_id}, blocking=True)
    await settle()


async def test_create_update_delete_leave_the_other_run_alone(
    hass: HomeAssistant, running: Path
) -> None:
    long_run_changed = hass.states.get(LONG_RUN).last_changed  # type: ignore[union-attr]

    write_entry(running, probe(1))
    await reload_one(hass, "stage0_v6_probe")
    assert hass.states.get(PROBE) is not None
    assert in_flight(hass) == 1

    write_entry(running, probe(2))
    await reload_one(hass, "stage0_v6_probe")
    assert in_flight(hass) == 1

    delete_entry(running, "stage0_v6_probe")
    await reload_one(hass, "stage0_v6_probe")
    # A reload alone leaves a restored, unavailable entity behind; the editor's delete
    # hook also removes the registry entry, and so must the adapter.
    leftover = hass.states.get(PROBE)
    assert leftover is not None
    assert leftover.state == "unavailable"
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("automation", "automation", "stage0_v6_probe")
    assert entity_id == PROBE
    registry.async_remove(entity_id)
    await settle()
    assert hass.states.get(PROBE) is None
    assert in_flight(hass) == 1
    assert hass.states.get(LONG_RUN).last_changed == long_run_changed  # type: ignore[union-attr]


async def test_a_full_reload_also_keeps_an_unchanged_automation_running(
    hass: HomeAssistant, running: Path
) -> None:
    write_entry(running, probe(1))

    await hass.services.async_call("automation", "reload", blocking=True)
    await settle()

    assert hass.states.get(PROBE) is not None
    assert in_flight(hass) == 1


async def test_rewriting_the_running_automation_itself_stops_its_run(
    hass: HomeAssistant, running: Path
) -> None:
    """What a routine update does to its own in flight run (a pulse in its delay)."""
    changed = long_run()
    changed["actions"] = [{"delay": {"minutes": 11}}]
    write_entry(running, changed)

    await reload_one(hass, "stage0_v6_long_run")

    assert in_flight(hass) == 0
