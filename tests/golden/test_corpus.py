"""The golden corpus: anonymized automations captured from a real instance (Stage 0 V2).

The fixtures are the configs the loaded automation entities expose, with free text and
opaque ids replaced (`tools/scrub_automations.py`, then `tools/anonymize.py`). These tests
keep the corpus honest: every file is still an automation the core accepts, and the shapes
later phases rely on are present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.core import HomeAssistant
import pytest

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "automations"
FILES = sorted(CORPUS.glob("automation_*.json"))
SYNTHETIC = sorted((CORPUS.parent / "synthetic").glob("synthetic_*.json"))


def load(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return record


def walk(node: Any) -> list[dict[str, Any]]:
    """Every mapping in a nested config, depth first."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(walk(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(walk(item))
    return found


def uses_device_automation(config: dict[str, Any]) -> bool:
    """Device triggers, conditions and actions need their integration loaded to validate."""
    return any(
        node.get("trigger") == "device"
        or node.get("condition") == "device"
        or ("device_id" in node and "type" in node and "domain" in node)
        for node in walk(config)
    )


def test_the_corpus_is_complete() -> None:
    assert len(FILES) == 39
    for path in FILES:
        record = load(path)
        assert set(record) <= {"config", "related"}
        assert record["config"]["id"] == path.stem


@pytest.mark.parametrize("path", FILES + SYNTHETIC, ids=[path.stem for path in FILES + SYNTHETIC])
async def test_each_automation_validates_against_the_core(hass: HomeAssistant, path: Path) -> None:
    config = load(path)["config"]
    if uses_device_automation(config):
        pytest.skip("device automations validate only with their integration loaded")

    validated = await async_validate_config_item(hass, path.stem, config)

    assert validated is not None
    assert validated.validation_status == "ok", validated.validation_error


def test_the_shapes_later_phases_need_are_present() -> None:
    """Time windows, run timers, device triggers, reference gaps and custom logic."""
    configs = [load(path)["config"] for path in FILES]
    nodes = [node for config in configs for node in walk(config)]

    assert any(node.get("trigger") == "time" for node in nodes)
    assert any(node.get("trigger") == "homeassistant" for node in nodes)
    assert any(node.get("trigger") == "state" and "for" in node for node in nodes)
    assert any(node.get("condition") == "template" for node in nodes)
    assert any(node.get("trigger") == "schedule.block_started" for node in nodes)
    assert any(node.get("condition") == "switch.is_on" for node in nodes)
    assert sum(uses_device_automation(config) for config in configs) >= 3
