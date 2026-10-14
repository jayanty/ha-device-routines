"""The Health sensor and what it reads: the deploy marker, the manifest, the channel."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_routines import health
from custom_components.device_routines.const import DOMAIN

HEALTH = "sensor.device_routines_health"
SHA = "0123456789abcdef0123456789abcdef01234567"
MARKER = {
    "commit": SHA,
    "branch": "dev-stable",
    "deployed_at": "2026-10-13T20:00:00Z",
    "previous_commit": None,
    "changed_files": ["const.py", "sensor.py"],
}


# --------------------------------------------------------------------------------------
# Reading the deploy marker (blocking, pure functions)
# --------------------------------------------------------------------------------------


def test_no_marker_means_no_deployment(tmp_path: Path) -> None:
    assert health.read_deployment(tmp_path) is None


def test_the_marker_is_read(tmp_path: Path) -> None:
    (tmp_path / ".deployed").write_text(json.dumps(MARKER), encoding="utf-8")

    deployment = health.read_deployment(tmp_path)

    assert deployment == health.Deployment(
        commit=SHA,
        branch="dev-stable",
        deployed_at="2026-10-13T20:00:00Z",
        previous_commit=None,
        changed_files=2,
        rollback_of=None,
    )


@pytest.mark.parametrize("body", ["{not json", '["a list"]', ""])
def test_a_damaged_marker_reads_as_no_deployment(tmp_path: Path, body: str) -> None:
    (tmp_path / ".deployed").write_text(body, encoding="utf-8")

    assert health.read_deployment(tmp_path) is None


def test_a_rollback_marker_names_what_it_rolled_back(tmp_path: Path) -> None:
    marker = dict(MARKER, rollback_of="f" * 40)
    (tmp_path / ".deployed").write_text(json.dumps(marker), encoding="utf-8")

    deployment = health.read_deployment(tmp_path)

    assert deployment is not None
    assert deployment.rollback_of == "f" * 40


# --------------------------------------------------------------------------------------
# Channel
# --------------------------------------------------------------------------------------


def test_a_deployment_means_the_dev_channel(tmp_path: Path) -> None:
    assert health.detect_channel(tmp_path, has_deployment=True) == "dev"


def test_the_hacs_store_listing_the_domain_means_the_hacs_channel(tmp_path: Path) -> None:
    store = tmp_path / ".storage" / "hacs.repositories"
    store.parent.mkdir()
    store.write_text(
        json.dumps(
            {
                "data": {
                    "1": {"domain": "other", "installed": True},
                    "2": {"domain": DOMAIN, "installed": True, "full_name": "x/y"},
                }
            }
        ),
        encoding="utf-8",
    )

    assert health.detect_channel(tmp_path, has_deployment=False) == "hacs"


def test_the_hacs_store_knowing_but_not_installing_is_not_the_hacs_channel(
    tmp_path: Path,
) -> None:
    store = tmp_path / ".storage" / "hacs.repositories"
    store.parent.mkdir()
    store.write_text(
        json.dumps({"data": {"2": {"domain": DOMAIN, "installed": False}}}), encoding="utf-8"
    )

    assert health.detect_channel(tmp_path, has_deployment=False) == "unknown"


@pytest.mark.parametrize("body", [None, "{broken", '{"data": "nope"}', '{"data": {"1": 5}}'])
def test_no_usable_hacs_store_means_unknown(tmp_path: Path, body: str | None) -> None:
    if body is not None:
        store = tmp_path / ".storage" / "hacs.repositories"
        store.parent.mkdir()
        store.write_text(body, encoding="utf-8")

    assert health.detect_channel(tmp_path, has_deployment=False) == "unknown"


# --------------------------------------------------------------------------------------
# The sensor
# --------------------------------------------------------------------------------------


async def test_the_health_sensor_without_a_deployment(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    state = hass.states.get(HEALTH)

    assert state is not None
    assert state.state == "ok"
    assert state.attributes["version"] == integration.version
    assert state.attributes["commit"] is None
    assert state.attributes["branch"] is None
    assert state.attributes["deployed_at"] is None
    assert state.attributes["channel"] == "unknown"
    assert state.attributes["ha_version"] == hass.config.as_dict()["version"]
    assert state.attributes["blueprint_schema"] is None
    assert state.attributes["blueprint_status"] is None
    assert state.attributes["owned_count"] == 0
    assert state.attributes["loaded_count"] == 0
    assert state.attributes["issues"] == []
    assert state.attributes["last_reconcile"] is None
    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == ["ok", "degraded", "error"]


async def test_the_health_sensor_with_a_deployment(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".deployed").write_text(json.dumps(MARKER), encoding="utf-8")
    monkeypatch.setattr(health, "COMPONENT_DIR", tmp_path)
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(HEALTH)

    assert state is not None
    assert state.attributes["commit"] == SHA
    assert state.attributes["branch"] == "dev-stable"
    assert state.attributes["deployed_at"] == "2026-10-13T20:00:00Z"
    assert state.attributes["channel"] == "dev"
