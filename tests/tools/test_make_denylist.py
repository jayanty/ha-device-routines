"""The denylist builder: every identifying token from the registries, generic words left out.

The registry sample below is invented. Nothing in it describes a real home.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import make_denylist

HEX_ID = "0123456789abcdef" * 2
MAC = ":".join(["00", "1a", "2b", "3c", "4d", "5e"])
HOST = "ha-zorblax" + ".local"

REGISTRIES = {
    "captured_at": "2026-01-01T00:00:00+00:00",
    "entities": [
        {
            "entity_id": "switch.zorblax_plug",
            "name": "Zorblax Plug",
            "original_name": "Quuxly Outlet",
            "device_id": HEX_ID,
            "area_id": "zorblax_hallway",
            "labels": ["frobnicate"],
        },
        {"entity_id": "light.kitchen", "name": "Kitchen", "original_name": None},
        {"entity_id": "sensor.qx", "name": "QX", "original_name": ""},
    ],
    "devices": [
        {
            "id": HEX_ID,
            "name": "Quuxly Outlet",
            "name_by_user": "Zorblax Plug",
            "manufacturer": "ACME",
            "model": "Plug 2000",
            "identifiers": [["zigbee", "0x00124b00zorb1234"]],
            "connections": [["mac", MAC]],
            "serial_number": "SN-ZORB-0001",
        },
        {
            "id": "f" * 32,
            "name": "Living Room",
            "name_by_user": None,
            "identifiers": [],
            "connections": [],
        },
    ],
    "areas": [
        {"id": "zorblax_hallway", "name": "Zorblax Hallway", "floor_id": "flr_up"},
        {"id": "office", "name": "Office", "floor_id": None},
        {"id": "living_room", "name": "Living Room", "floor_id": None},
    ],
    "floors": [
        {"floor_id": "flr_up", "name": "Upstairs"},
        {"floor_id": "quux_wing", "name": "Quux Wing"},
    ],
    "labels": [
        {"label_id": "frobnicate", "name": "Frobnicate"},
        {"label_id": "east", "name": "east"},
    ],
    "persons": [{"entity_id": "person.zed", "name": "Zed Zorblaxian"}],
    "users": ["zedz"],
    "hosts": [HOST],
    "extra": ["Quuxville Road", 42],
}


def _denylist() -> list[str]:
    return make_denylist.build_denylist(REGISTRIES)


@pytest.mark.parametrize(
    "token",
    [
        "switch.zorblax_plug",
        "Zorblax Plug",
        "Quuxly Outlet",
        HEX_ID,
        "zorblax_hallway",
        "Zorblax Hallway",
        "0x00124b00zorb1234",
        MAC,
        "SN-ZORB-0001",
        "flr_up",
        "Quux Wing",
        "quux_wing",
        "frobnicate",
        "person.zed",
        "Zed Zorblaxian",
        "zedz",
        HOST,
        "sensor.qx",
        "Quuxville Road",
    ],
)
def test_identifying_tokens_are_listed(token: str) -> None:
    assert token in _denylist()


@pytest.mark.parametrize(
    "token",
    [
        "Kitchen",  # a single generic word
        "Office",
        "office",
        "Living Room",  # a generic phrase
        "living_room",
        "Upstairs",
        "east",
        "QX",  # too short to mean anything
        "ACME",  # manufacturer and model are public product names
        "Plug 2000",
        "zigbee",  # an identifier's domain, not its value
        "mac",
        "light.kitchen",  # an entity id that is only a generic word names nothing
    ],
)
def test_generic_and_public_tokens_are_left_out(token: str) -> None:
    assert token not in _denylist()


def test_tokens_are_unique_ignoring_case_and_sorted() -> None:
    listed = _denylist()

    assert listed == sorted(listed, key=str.lower)
    assert len({token.lower() for token in listed}) == len(listed)


def test_allowed_tokens_are_left_out() -> None:
    listed = make_denylist.build_denylist(REGISTRIES, allow=["zedz"])

    assert "zedz" not in listed
    assert "Zed Zorblaxian" in listed


def test_is_generic_knows_words_and_phrases() -> None:
    assert make_denylist.is_generic("Garage")
    assert make_denylist.is_generic("master bedroom")
    assert make_denylist.is_generic("Front_Door")
    assert not make_denylist.is_generic("Zorblax Hallway")
    assert not make_denylist.is_generic("Garage Zorblax")


def test_an_empty_capture_builds_an_empty_list() -> None:
    assert make_denylist.build_denylist({}) == []


def test_main_writes_the_list_and_reports_only_a_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    captures = tmp_path / "registries.json"
    captures.write_text(json.dumps(REGISTRIES), encoding="utf-8")
    output = tmp_path / "denylist.txt"

    code = make_denylist.main(["--captures", str(captures), "--output", str(output)])

    assert code == 0
    written = output.read_text(encoding="utf-8")
    assert written.startswith("#")
    assert "Zorblax Hallway\n" in written
    out = capsys.readouterr().out
    assert "Zorblax" not in out
    assert str(len(_denylist())) in out


def test_main_fails_without_a_capture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = make_denylist.main(
        ["--captures", str(tmp_path / "missing.json"), "--output", str(tmp_path / "d.txt")]
    )

    assert code == 2
    assert "missing.json" in capsys.readouterr().out


def test_malformed_identifier_lists_are_ignored() -> None:
    data = {"devices": [{"id": "x" * 32, "identifiers": "not-a-list", "connections": [["mac"]]}]}

    assert make_denylist.build_denylist(data) == ["x" * 32]


# --------------------------------------------------------------------------------------
# Software, services and the core's own entities are not a home's data
# --------------------------------------------------------------------------------------

SOFTWARE = {
    "entities": [
        {"entity_id": "sun.sun"},
        {"entity_id": "zone.home"},
        {"entity_id": "weather.forecast_home"},
        {"entity_id": "sensor.sun_next_dawn"},
        {"entity_id": "sensor.backup_last_successful_automatic_backup"},
        {"entity_id": "update.home_assistant_core_update"},
        {"entity_id": "update.zorblax_card_update"},
        {"entity_id": "update.zorblax_plug_firmware"},
        {"entity_id": "button.homeassistant_restart"},
        {"entity_id": "sensor.automations"},
        {"entity_id": "switch.cloud_alexa"},
        {"entity_id": "conversation.home_assistant"},
    ],
    "devices": [
        {"id": "a" * 32, "name": "Home Assistant Core", "identifiers": [["hassio", "core"]]},
        {"id": "b" * 32, "name": "Zorblax Card", "identifiers": [["hacs", "123456"]]},
        {"id": "c" * 32, "name": "Repairs", "identifiers": [["spook", "repairs"]]},
        {"id": "d" * 32, "name": "Sun", "identifiers": [["sun", "01JJGM25W0KQY9BDABX5QBRJY4"]]},
        {"id": "e" * 32, "name": "home", "identifiers": [], "connections": [["mac", MAC]]},
        {
            "id": "f" * 32,
            "name": "Zorblax Hub",
            "name_by_user": "Watch",
            "identifiers": [["unifi", "zorb1"]],
        },
    ],
}


@pytest.mark.parametrize(
    "token",
    [
        "sun.sun",
        "zone.home",
        "weather.forecast_home",
        "sensor.sun_next_dawn",
        "sensor.backup_last_successful_automatic_backup",
        "update.home_assistant_core_update",
        "update.zorblax_card_update",
        "button.homeassistant_restart",
        "sensor.automations",
        "switch.cloud_alexa",
        "conversation.home_assistant",
        "Home Assistant Core",
        "Zorblax Card",
        "Repairs",
        "Sun",
        "home",
        "Watch",
        "core",
        "123456",
    ],
)
def test_software_and_core_tokens_are_left_out(token: str) -> None:
    assert token not in make_denylist.build_denylist(SOFTWARE)


@pytest.mark.parametrize("token", ["update.zorblax_plug_firmware", "Zorblax Hub", "zorb1", MAC])
def test_devices_from_the_home_still_count(token: str) -> None:
    listed = make_denylist.build_denylist(SOFTWARE)

    assert token in listed
    assert "a" * 32 in listed, "a device id is always listed, software or not"


@pytest.mark.parametrize(
    "token",
    [
        "Home Assistant",
        "Package",
        "Devices",
        "Backup",
        "Mac",
        "iPhone",
        "bar",
        "Main",
        "Guest Bathroom",
        "wine_cellar",
    ],
)
def test_more_words_everyone_uses_are_generic(token: str) -> None:
    assert make_denylist.is_generic(token)
