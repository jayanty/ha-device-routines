"""Stage 0 V3, A9 as amended: the contexts a time triggered automation run produces.

The fixture is a live recording (anonymized): a time triggered automation turned a plug
on, then off. Phase 2 replays it through `attribution.py`; until then this test keeps
the recorded relation honest: every state change carries the exact context of the
`automation_triggered` event before it, and that context has no parent and no user,
the same shape a wall switch produces. Only the event map can tell them apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "attribution" / "v3_time_triggered.json"
)


def test_time_triggered_runs_are_parentless_and_reused_by_their_state_changes() -> None:
    recording: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    runs: set[str] = set()
    classified: list[str] = []

    for event in recording["events"]:
        context = event["context"]
        assert context["parent_id"] is None
        assert context["user_id"] is None
        if event["event_type"] == "automation_triggered":
            runs.add(context["id"])
        elif event["event_type"] == "state_changed":
            classified.append("automation" if context["id"] in runs else "device")

    assert classified == recording["expected"]
