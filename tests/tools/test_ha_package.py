"""The development channel package: valid for the core, and safe in what it may restart."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.components.input_boolean import CONFIG_SCHEMA as INPUT_BOOLEAN_SCHEMA
from homeassistant.components.input_datetime import CONFIG_SCHEMA as INPUT_DATETIME_SCHEMA
from homeassistant.components.input_text import CONFIG_SCHEMA as INPUT_TEXT_SCHEMA
from homeassistant.components.shell_command import CONFIG_SCHEMA as SHELL_COMMAND_SCHEMA
from homeassistant.core import HomeAssistant
import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[2] / "tools" / "ha_package" / "device_routines_dev.yaml"
README = PACKAGE.with_name("README.md")


def package() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(PACKAGE.read_text(encoding="utf-8"))
    return loaded


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


def test_the_package_has_the_sections_the_spec_names() -> None:
    assert set(package()) == {
        "shell_command",
        "rest",
        "input_boolean",
        "input_datetime",
        "input_text",
        "automation",
    }


def test_the_owner_placeholder_is_the_only_thing_to_edit() -> None:
    text = PACKAGE.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    assert body.count("<owner>") == 2
    assert "jayanty" not in body


def test_the_three_shell_commands_and_the_sensor_exist() -> None:
    loaded = package()

    assert set(loaded["shell_command"]) == {
        "deploy_device_routines",
        "rollback_device_routines",
        "device_routines_deploy_status",
    }
    for command in loaded["shell_command"].values():
        assert command.startswith("python3 /config/tools/ha_deploy.py ")
        assert "--domain device_routines" in command
    assert loaded["rest"][0]["sensor"][0]["unique_id"] == "device_routines_dev_stable"
    assert loaded["rest"][0]["scan_interval"] == 600


def test_the_helper_sections_validate() -> None:
    loaded = package()

    SHELL_COMMAND_SCHEMA({"shell_command": loaded["shell_command"]})
    INPUT_BOOLEAN_SCHEMA({"input_boolean": loaded["input_boolean"]})
    INPUT_DATETIME_SCHEMA({"input_datetime": loaded["input_datetime"]})
    INPUT_TEXT_SCHEMA({"input_text": loaded["input_text"]})


def test_the_helpers_keep_their_values_across_restarts() -> None:
    """`initial:` would reset a user's choice on every restart (best practice)."""
    loaded = package()

    for section in ("input_boolean", "input_datetime", "input_text"):
        for helper in loaded[section].values():
            assert "initial" not in helper


@pytest.mark.parametrize("index", [0, 1, 2])
async def test_each_automation_validates_against_the_core(hass: HomeAssistant, index: int) -> None:
    automation = package()["automation"][index]

    validated = await async_validate_config_item(hass, str(index), automation)

    assert validated is not None, "the core refused the automation configuration"


def test_the_automations_are_the_three_the_spec_names() -> None:
    automations = package()["automation"]

    assert [a["id"] for a in automations] == [
        "device_routines_dev_deploy",
        "device_routines_restart_window",
        "device_routines_post_restart_check",
    ]
    for automation in automations:
        assert automation["description"]
        assert automation["alias"].startswith("Device Routines: ")


def test_every_shell_command_called_is_defined() -> None:
    loaded = package()
    defined = {f"shell_command.{name}" for name in loaded["shell_command"]}
    called = {
        node["action"]
        for node in walk(loaded["automation"])
        if isinstance(node.get("action"), str) and node["action"].startswith("shell_command.")
    }

    assert called == defined


def test_a_restart_is_only_ever_behind_the_opt_in_switch() -> None:
    """PRD D30: nothing restarts Home Assistant unless the switch is on."""
    loaded = package()
    guarded = 0
    for automation in loaded["automation"]:
        restarts = [
            node for node in walk(automation) if node.get("action") == "homeassistant.restart"
        ]
        if not restarts:
            continue
        conditions = [
            node
            for node in walk(automation)
            if node.get("condition") == "state"
            and node.get("entity_id") == "input_boolean.device_routines_auto_restart"
            and node.get("state") == "on"
        ]
        assert conditions, f"{automation['id']} restarts without the opt in switch"
        guarded += len(restarts)

    assert guarded == 2


def test_the_integration_is_never_reloaded_as_a_substitute() -> None:
    actions = {node.get("action") for node in walk(package()["automation"])}

    assert "homeassistant.reload_config_entry" not in actions
    assert "homeassistant.reload_all" not in actions


def test_the_readme_covers_the_bootstrap_and_the_rollback() -> None:
    text = README.read_text(encoding="utf-8")

    for phrase in ("Bootstrap", "restart policy", "rolling back", "HACS channel", "<owner>"):
        assert phrase.lower() in text.lower(), phrase
