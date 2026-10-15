"""The automation scrubber: free text and opaque ids out, structure kept.

Every value below is invented; the automations are synthetic shapes, not real ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools import scrub_automations

REGISTRY_ENTITY = "0123456789abcdef" * 2
OTHER_ENTITY = "fedcba9876543210" * 2
DEVICE = "1111222233334444" * 2

TIMED: dict[str, Any] = {
    "id": "1700000000000",
    "alias": "Zorblax fan nightly",
    "description": "Keeps the zorblax fan going at night for Zed",
    "triggers": [
        {"trigger": "time", "at": "17:00:00", "id": "on", "note": "Zed asked for this"},
        {"trigger": "webhook", "webhook_id": "secret-hook-value", "local_only": True},
    ],
    "conditions": [{"condition": "time", "weekday": ["mon", "tue"]}],
    "actions": [
        {
            "alias": "Turn the zorblax fan on",
            "action": "switch.turn_on",
            "target": {"entity_id": "switch.zorblax_fan"},
        },
        {
            "action": "notify.mobile_app_zeds_phone",
            "data": {"title": "Zorblax", "message": "See https://zorblax.example.org/x"},
        },
        {"stop": "Zed is away"},
        {"delay": "00:03:00"},
    ],
    "variables": {"link": "{{ 'https://zorblax.example.org/live' }}"},
    "mode": "single",
}
DEVICE_BASED: dict[str, Any] = {
    "id": "1700000000001",
    "alias": "Device based",
    "description": "",
    "triggers": [
        {
            "trigger": "device",
            "type": "turned_off",
            "device_id": DEVICE,
            "entity_id": REGISTRY_ENTITY,
            "domain": "switch",
            "for": {"seconds": 30},
        }
    ],
    "conditions": [
        {
            "condition": "device",
            "type": "is_off",
            "device_id": DEVICE,
            "entity_id": OTHER_ENTITY,
            "domain": "switch",
        }
    ],
    "actions": [
        {"action": "notify.mobile_app_zeds_phone", "data": {"message": "Restarted"}},
        {"action": "notify.notify", "data": {"message": "Restarted"}},
        {"type": "turn_on", "entity_id": REGISTRY_ENTITY, "domain": "switch"},
    ],
    "mode": "single",
}


def scrubbed(config: dict[str, Any], number: int = 1) -> dict[str, Any]:
    return scrub_automations.Scrubber().automation(number, config)


def test_free_text_is_replaced_and_notes_dropped() -> None:
    result = scrubbed(TIMED)
    text = json.dumps(result)

    assert result["id"] == "automation_01"
    assert result["alias"] == "Automation 01"
    assert result["description"] == "Description."
    for private in ("Zed", "zorblax.example.org", "secret-hook-value", "zeds_phone"):
        assert private not in text
    assert '"note"' not in text
    actions = result["actions"]
    assert isinstance(actions, list)
    assert actions[0]["alias"] == "Step"
    assert actions[1] == {
        "action": "notify.phone_1",
        "data": {"title": "Title", "message": "Message"},
    }
    assert actions[2] == {"stop": "Stopped."}


def test_structure_the_summary_reads_is_kept() -> None:
    result = scrubbed(TIMED)

    assert result["triggers"] == [
        {"trigger": "time", "at": "17:00:00", "id": "on"},
        {"trigger": "webhook", "webhook_id": "webhook_1", "local_only": True},
    ]
    assert result["conditions"] == TIMED["conditions"]
    actions = result["actions"]
    assert isinstance(actions, list)
    assert actions[0]["target"] == {"entity_id": "switch.zorblax_fan"}
    assert actions[3] == {"delay": "00:03:00"}
    assert result["mode"] == "single"
    assert result["variables"] == {"link": "{{ 'https://example.invalid/path' }}"}


def test_an_empty_description_stays_empty() -> None:
    assert scrubbed(DEVICE_BASED)["description"] == ""


def test_registry_ids_and_services_map_consistently_across_automations() -> None:
    scrubber = scrub_automations.Scrubber()
    first = scrubber.automation(1, TIMED)
    second = scrubber.automation(2, DEVICE_BASED)

    triggers = second["triggers"]
    actions = second["actions"]
    conditions = second["conditions"]
    assert isinstance(triggers, list)
    assert isinstance(actions, list)
    assert isinstance(conditions, list)
    fake = triggers[0]["entity_id"]
    assert fake != REGISTRY_ENTITY
    assert scrub_automations.REGISTRY_ID.match(fake)
    assert actions[2]["entity_id"] == fake
    assert conditions[0]["entity_id"] not in (fake, OTHER_ENTITY)
    # Device ids are left to the anonymizer, which knows them from the denylist.
    assert triggers[0]["device_id"] == DEVICE
    # The same phone maps to the same stand in; the built in notify service is kept.
    first_actions = first["actions"]
    assert isinstance(first_actions, list)
    assert actions[0]["action"] == first_actions[1]["action"] == "notify.phone_1"
    assert actions[1]["action"] == "notify.notify"


def test_related_keeps_only_what_the_summary_uses() -> None:
    scrubber = scrub_automations.Scrubber()
    related = scrubber.related(
        {
            "entity": ["switch.zorblax_fan", REGISTRY_ENTITY],
            "device": [DEVICE],
            "area": ["zorblax_hallway"],
            "config_entry": ["01ZORBLAX"],
            "integration": ["matter"],
        }
    )

    assert set(related) == {"entity", "device", "area"}
    assert REGISTRY_ENTITY not in related["entity"]
    assert "switch.zorblax_fan" in related["entity"]


def test_main_writes_generic_file_names(tmp_path: Path) -> None:
    source = tmp_path / "captures"
    (source / "config").mkdir(parents=True)
    (source / "related").mkdir()
    (source / "config" / "zorblax_fan_nightly.json").write_text(json.dumps(TIMED))
    (source / "config" / "device_based.json").write_text(json.dumps(DEVICE_BASED))
    (source / "related" / "zorblax_fan_nightly.json").write_text(
        json.dumps({"entity": ["switch.zorblax_fan"], "integration": ["matter"]})
    )
    output = tmp_path / "out"

    assert scrub_automations.main(["--output", str(output), str(source)]) == 0

    files = sorted(path.name for path in output.iterdir())
    assert files == ["automation_01.json", "automation_02.json"]
    first = json.loads((output / "automation_01.json").read_text())
    second = json.loads((output / "automation_02.json").read_text())
    # Sorted by source name: device_based first.
    assert "related" not in first
    assert first["config"]["alias"] == "Automation 01"
    assert second["related"] == {"entity": ["switch.zorblax_fan"]}


def test_main_refuses_an_empty_capture(tmp_path: Path) -> None:
    assert scrub_automations.main(["--output", str(tmp_path / "out"), str(tmp_path)]) == 2
