"""Ownership markers M1 and M2 (TECH_SPEC 3.4)."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.device_routines import markers


def owned(device_id: str = "abc123") -> dict[str, Any]:
    return {
        "id": markers.automation_id(device_id),
        "alias": "Routine: Living room fan",
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": {}},
    }


def test_automation_id_is_stable_and_matches_m1() -> None:
    first = markers.automation_id("abc123")
    assert first == markers.automation_id("abc123")
    assert first != markers.automation_id("abc124")
    assert first.startswith(markers.AUTOMATION_ID_PREFIX)
    assert len(first) == len(markers.AUTOMATION_ID_PREFIX) + 12
    assert markers.has_routine_id({"id": first})


def test_is_owned_needs_both_markers() -> None:
    assert markers.is_owned(owned())
    lookalike = owned() | {"id": "routine_living_room_fan"}
    assert not markers.is_owned(lookalike)
    other_blueprint = owned() | {"use_blueprint": {"path": "someone/else.yaml", "input": {}}}
    assert not markers.is_owned(other_blueprint)
    taken_control = {key: value for key, value in owned().items() if key != "use_blueprint"}
    assert not markers.is_owned(taken_control)
    assert markers.has_routine_id(taken_control)


@pytest.mark.parametrize(
    "identifier",
    [
        None,
        42,
        "device_routines_",
        "device_routines_0123456789ab\n",
        "device_routines_0123456789AB",
        "device_routines_0123456789abc",
        "xdevice_routines_0123456789ab",
    ],
)
def test_m1_is_exact(identifier: object) -> None:
    config = {"id": identifier, "use_blueprint": {"path": markers.BLUEPRINT_PATH}}
    assert not markers.has_routine_id(config)
    assert not markers.is_owned(config)


def test_m2_must_be_a_mapping() -> None:
    assert not markers.is_owned(owned() | {"use_blueprint": markers.BLUEPRINT_PATH})
