"""Read only checks against the development instance (TECH_SPEC 11.6). Never runs in CI."""

from __future__ import annotations

from typing import Any

import pytest

from tests.live.conftest import Live, deployed_versions, manifest_version, tags_at

pytestmark = pytest.mark.live


def ours(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in states if s["entity_id"].startswith(("sensor.", "binary_sensor."))]


def schedule_sensors(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        s
        for s in ours(states)
        if s["entity_id"].endswith("_schedule") and "items" in s["attributes"]
    ]


def test_health_runs_the_deployed_commit(live: Live) -> None:
    """The instance moves only by hand deploys of tags (L58): Health's commit is a tag's.

    A release tag's commit, or `dev-stable`'s, as this clone's tags say (fetch the tags
    first), and the version that tag names.
    """
    health = live.get("/api/states/sensor.device_routines_health")
    attributes = health["attributes"]
    commit = attributes["commit"]
    assert commit, "Health names no commit: the instance has no deploy record"
    tags = tags_at(commit)
    versions = deployed_versions(tags, manifest_version(commit))

    assert health["state"] == "ok"
    assert versions, f"no release tag and no dev-stable points at {commit} here: {tags}"
    assert attributes["version"] in versions, (attributes["version"], tags)


def test_schedule_sensors_exist_with_valid_states(live: Live) -> None:
    sensors = schedule_sensors(live.states())

    assert sensors, "no Schedule sensor at all"
    for sensor in sensors:
        assert sensor["state"] not in {"unknown", "unavailable"}, sensor["entity_id"]
        assert len(sensor["state"]) <= 40
        assert sensor["attributes"]["items"]


def test_no_open_issue_from_this_integration(live: Live) -> None:
    problems = [
        s
        for s in live.states()
        if s["entity_id"].startswith("binary_sensor.")
        and s["entity_id"].endswith("device_routines_problem")
    ]

    assert len(problems) == 1
    assert problems[0]["state"] == "off", problems[0]["attributes"]["issues"]


def test_share_of_unparsed_lines_is_reported(live: Live) -> None:
    items = [item for s in schedule_sensors(live.states()) for item in s["attributes"]["items"]]
    unparsed = sum(item["source"] == "none" for item in items)

    print(f"items={len(items)} source_none={unparsed}")  # noqa: T201  # recorded evidence
    assert items
