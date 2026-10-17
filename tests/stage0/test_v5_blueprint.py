"""Stage 0 V5, A1 and A8: installing a blueprint from integration code and its features.

A1: an integration installs a blueprint through the automation component's
`DomainBlueprints` and automations can use it after an automation reload, no restart.
A8: collapsible input sections, a `condition` selector, `enabled: !input` on a trigger
and on a condition, the sentinel pattern, and the purpose specific `timer.finished`
trigger on a sentinel timer. The live half (the same file saved over the WebSocket API,
which calls the same method) is in `docs/stage0-report.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.components.automation.config import (
    AUTOMATION_BLUEPRINT_SCHEMA,
    async_validate_config_item,
)
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.core import Event, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import parse_yaml
import pytest

BLUEPRINT_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "stage0" / "stage0_probe.yaml"
BLUEPRINT_PATH = "device_routines/stage0_probe.yaml"
TARGET = "switch.living_room_fan"


def probe_automation(**inputs: Any) -> dict[str, Any]:
    return {
        "id": "stage0_v5",
        "alias": "stage0 v5",
        "use_blueprint": {
            "path": BLUEPRINT_PATH,
            "input": {"target_entity": TARGET, **inputs},
        },
    }


@pytest.fixture
async def installed(hass: HomeAssistant, tmp_path: Path) -> None:
    """Install the probe blueprint the way the integration will, into a scratch config."""
    hass.config.config_dir = str(tmp_path)
    assert await async_setup_component(hass, "automation", {})
    data = parse_yaml(BLUEPRINT_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    blueprint = Blueprint(
        data,
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )

    overrode = await async_get_blueprints(hass).async_add_blueprint(
        blueprint, BLUEPRINT_PATH, allow_override=True
    )

    assert overrode is False
    assert (tmp_path / "blueprints" / "automation" / BLUEPRINT_PATH).is_file()


async def test_sections_and_the_condition_selector_are_kept(
    hass: HomeAssistant, installed: None
) -> None:
    blueprint = await async_get_blueprints(hass).async_get_blueprint(BLUEPRINT_PATH)

    sections = blueprint.metadata["input"]
    assert set(sections) == {"target", "schedule", "timers", "advanced"}
    assert sections["advanced"]["collapsed"] is True
    assert sections["advanced"]["input"]["extra_conditions"]["selector"] == {"condition": {}}


async def test_enabled_inputs_switch_a_trigger_and_a_condition_off(
    hass: HomeAssistant, installed: None
) -> None:
    validated = await async_validate_config_item(hass, "stage0_v5", probe_automation())

    assert validated is not None
    assert validated.validation_status == "ok", validated.validation_error
    config = dict(validated)
    assert config["triggers"][0]["enabled"] is False
    assert config["conditions"][1]["enabled"] is False
    # The sentinel timer validates even though the entity never exists.
    assert config["triggers"][1]["target"] == {"entity_id": ["timer.device_routines_unused"]}


async def test_the_installed_blueprint_runs_after_a_reload(
    hass: HomeAssistant, installed: None, tmp_path: Path
) -> None:
    ran: list[Event] = []
    hass.bus.async_listen("stage0_probe_ran", ran.append)
    hass.states.async_set(TARGET, "off")
    # The automation appears in the config only now, after the blueprint was installed;
    # an automation reload picks both up with no restart.
    (tmp_path / "configuration.yaml").write_text(
        "automation: !include automations.yaml\n", encoding="utf-8"
    )
    (tmp_path / "automations.yaml").write_text(json.dumps([probe_automation()]), encoding="utf-8")

    await hass.services.async_call("automation", "reload", blocking=True)
    await hass.async_block_till_done()
    hass.bus.async_fire("device_routines_timer_caught_up", {"device_id": "stage0"})
    await hass.async_block_till_done()

    # The guard condition is switched off by its input, the extra conditions are empty and
    # the sentinel Paused until reads unknown, so the run goes through.
    assert [event.data["trigger_id"] for event in ran] == ["timer_done"]


async def test_enabling_the_guard_input_turns_the_condition_on(
    hass: HomeAssistant, installed: None
) -> None:
    ran: list[Event] = []
    hass.bus.async_listen("stage0_probe_ran", ran.append)
    hass.states.async_set(TARGET, "off")

    assert await async_setup_component(
        hass, "automation", {"automation": probe_automation(guard_enabled=True)}
    )
    await hass.async_block_till_done()
    hass.bus.async_fire("device_routines_timer_caught_up", {"device_id": "stage0"})
    await hass.async_block_till_done()

    assert ran == []
