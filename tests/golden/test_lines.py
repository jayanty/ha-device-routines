"""The golden corpus: every automation, every device it acts on, the exact lines (TECH_SPEC 11.4).

Each action target in a fixture stands for its own device. `expected_lines.json` holds the
lines the parser and the writer produce in 12 hour English; any difference fails. After a
deliberate grammar change, regenerate and review the diff line by line:

    .venv/bin/python -m tests.golden.test_lines --write
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

from custom_components.device_routines import parser
from custom_components.device_routines.models import DeviceContext, EntityRef
from custom_components.device_routines.sentence import Writer, load_phrases
from custom_components.device_routines.summary import SOURCE_NONE, SOURCE_PARSER

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXPECTED = Path(__file__).resolve().parent / "expected_lines.json"
FILES = sorted(FIXTURES.glob("automations/automation_*.json")) + sorted(
    FIXTURES.glob("synthetic/synthetic_*.json")
)
TARGET = re.compile(
    r'"((?:switch|light|fan|vacuum|lawn_mower|cover|lock|valve|climate|humidifier'
    r"|input_boolean|media_player)\.[a-z0-9_]+)\""
)


def lines_for(path: Path) -> dict[str, list[dict[str, str]]]:
    config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))["config"]
    writer = Writer(load_phrases("en"), "12h")
    targets = sorted(set(TARGET.findall(json.dumps(config.get("actions")))))
    found: dict[str, list[dict[str, str]]] = {}
    for entity_id in targets:
        device = DeviceContext(device_id=f"device_{entity_id}", entities=(EntityRef(entity_id),))
        parsed = parser.summarize(config, device)
        if parsed:
            found[entity_id] = [
                {
                    "line": writer.line(line),
                    "source": SOURCE_PARSER if line.understood else SOURCE_NONE,
                }
                for line in parsed
            ]
    return found


def corpus() -> dict[str, dict[str, list[dict[str, str]]]]:
    return {path.stem: lines_for(path) for path in FILES}


def test_every_fixture_produces_exactly_the_expected_lines() -> None:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    actual = corpus()

    assert sorted(actual) == sorted(expected)
    for name in sorted(expected):
        assert actual[name] == expected[name], name


def test_the_parse_rate_meets_g5() -> None:
    """G5 counts items parsed (a line from the parser, partial lines included) over all items.

    The corpus keeps its golden negatives on purpose: items whose only triggers mean
    something only a guess could say (an integration defined device trigger, a custom
    event) and must read as custom logic. They count in the denominator.
    """
    items = [item for lines in corpus().values() for group in lines.values() for item in group]
    parsed = sum(item["source"] == SOURCE_PARSER for item in items)

    assert len(items) >= 50
    # Task A4.3 (finding F3) brought the corpus from 45 to 51 of 56 items. Raise this
    # floor, never lower it.
    assert parsed / len(items) >= 0.90


if __name__ == "__main__":  # pragma: no cover
    if "--write" in sys.argv:
        EXPECTED.write_text(json.dumps(corpus(), indent=2, ensure_ascii=False) + "\n")
