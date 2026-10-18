"""The markers of a managed routine: ownership M1 and M2, presentation M3 to M8 (TECH_SPEC 3.4)."""

from __future__ import annotations

import hashlib
from typing import Any

from homeassistant.util import slugify as ha_slugify
import pytest

from custom_components.device_routines import markers, sentence


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


# --------------------------------------------------------------------------------------
# Presentation markers M3 to M8 (lane 1 of Build A)
# --------------------------------------------------------------------------------------

PHRASES = sentence.load_phrases("en")


def test_lookalike_with_alias_label_and_category_is_not_owned() -> None:
    """Every presentation marker of a routine, on an automation without M1 and M2."""
    lookalike = {
        "id": "1700000000000",
        "alias": "Routine: Living room fan",
        "description": markers.presentation("Living room fan", PHRASES).description,
        "labels": [markers.LABEL_ID],
        "category": markers.CATEGORY_NAME,
        "icon": markers.ICON,
        "triggers": [],
        "actions": [],
    }
    assert not markers.is_owned(lookalike)
    assert not markers.has_routine_id(lookalike)
    assert markers.is_owned(owned() | {"alias": "Something else", "labels": []})


def test_presentation_constants() -> None:
    assert markers.LABEL_ID == "routines"
    assert markers.LABEL_NAME == "Routines"
    assert markers.CATEGORY_NAME == "Device Routines"
    assert markers.ICON == "mdi:calendar-clock"
    assert markers.REPLACED_LABEL_ID == "replaced_by_routine"


def test_presentation_reads_the_phrase_table() -> None:
    shown = markers.presentation("Living room fan", PHRASES)
    assert shown == markers.Presentation(
        alias="Routine: Living room fan",
        description=(
            "Managed by Device Routines. Change it on the Living room fan device page or in "
            "this form. Take control to turn it into a normal automation."
        ),
        icon="mdi:calendar-clock",
    )
    formerly = markers.presentation("Living room fan", PHRASES, formerly=True)
    assert formerly.alias == shown.alias
    assert formerly.description == "Formerly managed by Device Routines."
    braces = markers.presentation("Fan {1}", PHRASES)
    assert braces.alias == "Routine: Fan {1}"
    custom = {**PHRASES, "routine_alias": "Routine {device}"}
    assert markers.presentation("Fan", custom).alias == "Routine Fan"


def test_alias_is_generated_follows_history() -> None:
    history = ["Living room fan", "Lounge fan"]
    assert markers.alias_is_generated("Routine: Living room fan", history)
    assert markers.alias_is_generated("Routine: Lounge fan", history)
    assert not markers.alias_is_generated("Routine: Bedroom fan", history)
    assert not markers.alias_is_generated("Morning fan schedule", history)
    assert not markers.alias_is_generated("Routine: Living room fan", [])
    assert PHRASES["routine_alias"] == markers.DEFAULT_ALIAS_TEMPLATE
    assert markers.alias_is_generated("Routine Lounge fan", history, template="Routine {device}")


def test_config_hash_ignores_id_and_key_order() -> None:
    config = {
        "id": markers.automation_id("abc123"),
        "alias": "Routine: Living room fan",
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": {"a": 1, "b": [1, 2]}},
    }
    reordered = {
        "use_blueprint": {"input": {"b": [1, 2], "a": 1}, "path": markers.BLUEPRINT_PATH},
        "alias": "Routine: Living room fan",
    }
    digest = markers.config_hash(config)
    assert digest == markers.config_hash(reordered)
    assert digest == markers.config_hash(config | {"id": "something_else"})
    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert digest != markers.config_hash(config | {"alias": "Routine: Lounge fan"})
    assert markers.config_hash({"input": {"a": [2, 1]}}) != markers.config_hash(
        {"input": {"a": [1, 2]}}
    )
    expected = hashlib.sha256(b'{"alias":"x","n":"\\u00e9"}').hexdigest()
    assert markers.config_hash({"n": "é", "alias": "x", "id": "y"}) == expected


@pytest.mark.parametrize(
    "name",
    [
        "Living room fan",
        "Bob's lamp",
        "Café Lights",
        "Garage  Door #2",
        "Straße",
        "Ünïcödé fan",
        "ÆØÅ",
        "fan-1_a",
        "Kitchen/Island",
        "Shelf 1,000",
        "  ",
        "__Fan__",
    ],
)
def test_slugify_matches_home_assistant_for_latin_names(name: str) -> None:
    assert markers.slugify(name) == ha_slugify(name)


def test_slugify_never_returns_an_empty_slug() -> None:
    assert markers.slugify("") == "unknown"
    assert markers.slugify("日本") == "unknown"


def test_entity_id_for() -> None:
    assert markers.entity_id_for("Living room fan") == "automation.routine_living_room_fan"
    assert markers.entity_id_for("Café Lights") == "automation.routine_cafe_lights"


def test_helper_slug_avoids_collisions() -> None:
    assert markers.helper_slug("Living room fan", "device-1", set()) == "living_room_fan"
    assert markers.helper_slug("Living room fan", "device-1", {"bedroom_fan"}) == (
        "living_room_fan"
    )
    first = markers.helper_slug("Living room fan", "device-1", {"living_room_fan"})
    second = markers.helper_slug("Living room fan", "device-2", {"living_room_fan"})
    assert first != second
    suffix = markers.automation_id("device-1").removeprefix(markers.AUTOMATION_ID_PREFIX)[:6]
    assert first == f"living_room_fan_{suffix}"
    assert first == markers.helper_slug("Living room fan", "device-1", ["living_room_fan"])
