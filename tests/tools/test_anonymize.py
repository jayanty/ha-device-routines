"""The anonymizer: deterministic, complete and idempotent, keeping times and shapes.

Every token below is invented; the automation is a synthetic shape, not a real one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import anonymize

HEX_ID = "0123456789abcdef" * 2
MAC = ":".join(["00", "1a", "2b", "3c", "4d", "5e"])
DENYLIST = [
    "switch.zorblax_plug",
    "Zorblax Plug",
    "Zorblax Hallway",
    "zorblax_hallway",
    HEX_ID,
    MAC,
    "Zed Zorblaxian",
    "Quux Wing",
]
REGISTRIES = {
    "entities": [{"entity_id": "switch.zorblax_plug", "name": "Zorblax Plug"}],
    "devices": [{"id": HEX_ID, "name": "Zorblax Plug", "connections": [["mac", MAC]]}],
    "areas": [{"id": "zorblax_hallway", "name": "Zorblax Hallway"}],
    "floors": [{"floor_id": "quux_wing", "name": "Quux Wing"}],
    "labels": [],
    "persons": [{"entity_id": "person.zed", "name": "Zed Zorblaxian"}],
}
AUTOMATION = {
    "id": "1700000000000",
    "alias": "Zorblax Plug schedule",
    "description": "Runs in the Zorblax Hallway for Zed Zorblaxian",
    "triggers": [{"trigger": "time", "at": "17:00:00"}, {"trigger": "time", "at": "09:00:00"}],
    "actions": [
        {"action": "switch.turn_on", "target": {"entity_id": "switch.zorblax_plug"}},
        {"action": "switch.turn_off", "target": {"area_id": "zorblax_hallway"}},
        {"action": "notify.send", "data": {"device_id": HEX_ID, "mac": MAC}},
    ],
}


def _anonymizer(mapping: dict[str, str] | None = None) -> anonymize.Anonymizer:
    return anonymize.Anonymizer(
        DENYLIST, mapping or {}, categories=anonymize.categorize(REGISTRIES)
    )


def test_entity_ids_keep_their_domain() -> None:
    out = _anonymizer().anonymize("switch.zorblax_plug")

    assert out == "switch.example_switch_1"


def test_registry_categories_name_the_replacement() -> None:
    anonymizer = _anonymizer()

    assert anonymizer.anonymize("Zorblax Hallway") == "Area 1"
    assert anonymizer.anonymize("Quux Wing") == "Floor 1"
    assert anonymizer.anonymize("Zed Zorblaxian") == "Person 1"
    assert anonymizer.anonymize("Zorblax Plug") == "Device 1"


def test_a_slug_form_gets_a_slug_replacement() -> None:
    anonymizer = _anonymizer()

    assert anonymizer.anonymize("zorblax_hallway") == "area_1"
    assert anonymizer.anonymize("zorblax-hallway") == "area-1"


def test_ids_and_addresses_keep_their_shape() -> None:
    anonymizer = _anonymizer()

    new_id = anonymizer.anonymize(HEX_ID)
    assert new_id != HEX_ID
    assert len(new_id) == 32
    assert all(c in "0123456789abcdef" for c in new_id)
    assert anonymizer.anonymize(MAC) == "02:00:00:00:00:01"


def test_numbering_is_stable_through_the_saved_map(tmp_path: Path) -> None:
    first = _anonymizer()
    first.anonymize("Quux Wing")
    first.anonymize("Zorblax Hallway")
    path = tmp_path / "map.json"
    anonymize.save_map(path, first.mapping)

    second = _anonymizer(anonymize.load_map(path))

    assert second.anonymize("Zorblax Hallway") == "Area 1"
    assert second.anonymize("Quux Wing") == "Floor 1"


def test_a_token_without_a_category_becomes_an_example_name() -> None:
    anonymizer = anonymize.Anonymizer(["Zorblax Plug"], {})

    assert anonymizer.anonymize("the Zorblax Plug") == "the Example name 1"


def test_an_automation_keeps_its_shape_and_times() -> None:
    text = json.dumps(AUTOMATION, indent=2)
    anonymizer = _anonymizer()

    out = json.loads(anonymizer.anonymize(text))

    assert out["triggers"] == AUTOMATION["triggers"]
    assert out["id"] == AUTOMATION["id"]
    assert out["actions"][0]["target"]["entity_id"] == "switch.example_switch_1"
    assert out["actions"][1]["target"]["area_id"] == "area_1"
    assert out["alias"] == "Device 1 schedule"
    assert out["description"] == "Runs in the Area 1 for Person 1"
    assert out["actions"][2]["data"]["mac"] == "02:00:00:00:00:01"
    assert out["actions"][2]["data"]["device_id"] != HEX_ID


def test_nothing_survives() -> None:
    anonymizer = _anonymizer()
    text = json.dumps(AUTOMATION)

    # Quux Wing is not in the automation; zorblax_hallway is the slug spelling of an
    # area name already in the list, so it is folded into that token.
    assert set(anonymizer.surviving(text)) == set(DENYLIST) - {"Quux Wing", "zorblax_hallway"}
    assert anonymizer.surviving(anonymizer.anonymize(text)) == []


def test_anonymizing_is_deterministic_and_idempotent() -> None:
    text = json.dumps(AUTOMATION)

    once = _anonymizer().anonymize(text)
    again = _anonymizer().anonymize(text)
    twice = _anonymizer().anonymize(once)

    assert once == again
    assert twice == once


def test_longer_tokens_win_over_their_parts() -> None:
    anonymizer = anonymize.Anonymizer(["Zorblax", "Zorblax Plug"], {})

    assert anonymizer.anonymize("Zorblax Plug and Zorblax") == "Example name 1 and Example name 2"


def test_main_anonymizes_a_directory_and_writes_the_map(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "one.json").write_text(json.dumps(AUTOMATION), encoding="utf-8")
    (raw / "notes.yaml").write_text("alias: Zorblax Plug\n", encoding="utf-8")
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("\n".join(DENYLIST) + "\n", encoding="utf-8")
    registries = tmp_path / "registries.json"
    registries.write_text(json.dumps(REGISTRIES), encoding="utf-8")
    map_path = tmp_path / "map.json"
    out = tmp_path / "fixtures"

    code = anonymize.main(
        [
            "--denylist",
            str(denylist),
            "--map",
            str(map_path),
            "--registries",
            str(registries),
            "--output",
            str(out),
            str(raw),
        ]
    )

    assert code == 0
    assert json.loads((out / "one.json").read_text())["alias"] == "Device 1 schedule"
    assert (out / "notes.yaml").read_text() == "alias: Device 1\n"
    assert json.loads(map_path.read_text())["Zorblax Plug"] == "Device 1"
    printed = capsys.readouterr().out
    assert "2 files" in printed
    assert "Zorblax" not in printed


def test_main_fails_without_a_denylist(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = anonymize.main(
        [
            "--denylist",
            str(tmp_path / "none.txt"),
            "--map",
            str(tmp_path / "m.json"),
            "--output",
            str(tmp_path / "out"),
            str(tmp_path),
        ]
    )

    assert code == 2
    assert "none.txt" in capsys.readouterr().out


def test_identifiers_and_hosts_get_their_own_categories() -> None:
    host = "ha-zorblax" + ".local"
    registries = {
        "devices": [{"identifiers": [["zigbee", "0x00124b00zorb1234"], ["bad"]]}],
        "hosts": [host, 7],
    }
    anonymizer = anonymize.Anonymizer(
        ["0x00124b00zorb1234", host], {}, categories=anonymize.categorize(registries)
    )

    assert anonymizer.anonymize("0x00124b00zorb1234") == "serial-1"
    assert anonymizer.anonymize(host) == "example-host-1"


def test_a_missing_map_loads_as_empty(tmp_path: Path) -> None:
    assert anonymize.load_map(tmp_path / "none.json") == {}


def test_main_skips_binary_input_and_reports_survivors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "blob.bin").write_bytes(b"\xff\xfe Zorblax")
    # `Example name` is itself denylisted, so the stand in for Zorblax survives.
    (raw / "note.txt").write_text("Zorblax\n", encoding="utf-8")
    denylist = tmp_path / "denylist.txt"
    denylist.write_text("Zorblax\nExample name\n", encoding="utf-8")

    code = anonymize.main(
        [
            "--denylist",
            str(denylist),
            "--map",
            str(tmp_path / "map.json"),
            "--output",
            str(tmp_path / "out"),
            str(raw),
            str(tmp_path / "missing-input"),
        ]
    )

    assert code == 1
    assert not (tmp_path / "out" / "note.txt").exists()
    assert "survived" in capsys.readouterr().out
