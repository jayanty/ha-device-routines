"""Phase 1 hub entities, the options flow, Repairs and diagnostics with a summary."""

from __future__ import annotations

import json
from typing import cast

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.device_routines import repairs
from custom_components.device_routines.config_flow import DeviceRoutinesOptionsFlow
from custom_components.device_routines.const import DOMAIN
from custom_components.device_routines.ha_adapter import AdapterReport

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


def hub_entity(hass: HomeAssistant, platform: str, key: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{DOMAIN}_hub_{key}")
    assert entity_id is not None
    return entity_id


async def test_hub_routines_and_problem_sensors(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    routines = hass.states.get(hub_entity(hass, "sensor", "hub_routines"))
    problem = hass.states.get(hub_entity(hass, "binary_sensor", "hub_problem"))

    assert routines is not None
    assert routines.state == "0"
    assert routines.attributes["routines"] == []
    assert problem is not None
    assert problem.state == "off"
    assert problem.attributes["issues"] == []
    assert problem.attributes["device_class"] == "problem"


async def test_the_problem_sensor_follows_open_issues(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    entity_id = hub_entity(hass, "binary_sensor", "hub_problem")

    repairs.async_sync_adapter_issue(hass, AdapterReport(failed=("read_automations",)))
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"
    assert state.attributes["issues"] == ["adapter_incompatible"]
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "adapter_incompatible")
    assert issue is not None
    assert issue.translation_placeholders is not None
    assert issue.translation_placeholders["capabilities"] == "read_automations"

    repairs.async_sync_adapter_issue(hass, AdapterReport())
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"  # type: ignore[union-attr]

    # Another integration's issue does not count.
    ir.async_create_issue(
        hass, "other", "x", is_fixable=False, severity=ir.IssueSeverity.WARNING, translation_key="x"
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"  # type: ignore[union-attr]


async def test_options_flow_stores_settings_and_reloads(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"]
    assert schema is not None
    defaults = {key.schema: key.default() for key in schema.schema}
    assert defaults == {"schedule_scope": "all", "time_format": "auto"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"schedule_scope": "none", "time_format": "24h"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {"schedule_scope": "none", "time_format": "24h"}
    assert init_integration.runtime_data.settings.time_format == "24h"


async def test_options_flow_refuses_an_invalid_value(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    flow = cast(
        "DeviceRoutinesOptionsFlow", hass.config_entries.options._progress[result["flow_id"]]
    )

    result = await flow.async_step_init({"schedule_scope": "everywhere", "time_format": "auto"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"schedule_scope": "invalid_choice"}


def test_every_options_error_and_selector_is_translated() -> None:
    from pathlib import Path  # noqa: PLC0415

    from custom_components.device_routines.config_flow import PHASE_1_SETTINGS  # noqa: PLC0415

    strings = json.loads(
        (Path(__file__).parents[2] / "custom_components" / DOMAIN / "strings.json").read_text()
    )
    for key, choices in PHASE_1_SETTINGS.items():
        assert set(strings["selector"][key]["options"]) == {member.value for member in choices}
        assert key in strings["options"]["step"]["init"]["data"]
        assert key in strings["options"]["step"]["init"]["data_description"]
    assert set(strings["options"]["error"]) == {
        "invalid_choice",
        "invalid_boolean",
        "out_of_range",
        "invalid_ai_task_entity",
        "unknown_setting",
    }


async def test_diagnostics_report_summary_shapes_without_names(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "fan")}, name="Secret attic fan"
    )
    er.async_get(hass).async_get_or_create(
        "fan", "other", "fan", device_id=device.id, suggested_object_id="secret_attic_fan"
    )
    hass.states.async_set("fan.secret_attic_fan", "off")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "id": "secret_alias",
                    "alias": "Secret alias",
                    "triggers": [{"trigger": "time", "at": "09:00"}],
                    "actions": [
                        {"action": "fan.turn_on", "target": {"entity_id": "fan.secret_attic_fan"}}
                    ],
                }
            ]
        },
    )
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert diagnostics["summary"]["devices"] == 1
    assert diagnostics["summary"]["per_device"] == [
        {
            "device": 0,
            "has_state": True,
            "conflicts": [],
            "items": [
                {
                    "kind": "automation",
                    "source": "parser",
                    "enabled": True,
                    "custom_logic": False,
                    "timed": True,
                }
            ],
        }
    ]
    text = json.dumps(diagnostics)
    for secret in ("Secret", "secret", device.id):
        assert secret not in text
