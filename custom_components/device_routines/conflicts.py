"""Conflict detection, without Repairs (TECH_SPEC 3.7, PRD FR-S6).

Two kinds: opposite actions on the same entity in the same minute, and an automation
action that contradicts a routine window (an off inside an on window, an on inside an off
window). Pure and O(n log n) in the number of occurrences.

A window with a sun bound (FR-R10) is placed with the caller's lookups, the ones the
occurrences were computed with; without them it has no expected state and nothing
contradicts it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations, groupby

from .models import ACTIVATING, DEACTIVATING, OPPOSITES, Conflict, Occurrence, RoutineSettings
from .nextrun import Lookups, expected_state

SAME_MINUTE = "opposite_same_minute"
OFF_IN_ON_WINDOW = "off_in_on_window"
ON_IN_OFF_WINDOW = "on_in_off_window"


@dataclass(frozen=True, slots=True)
class Planned:
    """One summary item's future actions; `routine` is set for a managed routine."""

    index: int
    entity_ids: tuple[str, ...]
    occurrences: tuple[Occurrence, ...]
    routine: RoutineSettings | None = None


def _minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def find(
    planned: Sequence[Planned], start: datetime, end: datetime, lookups: Lookups | None = None
) -> list[Conflict]:
    """Return every conflict among occurrences in [start, end), one per pair and reason.

    `lookups` give a routine's sun bounds, so a sun window has its window conflicts too.
    """
    events = sorted(
        (
            (entity, _minute(occurrence.at), item.index, occurrence)
            for item in planned
            for occurrence in item.occurrences
            if start <= occurrence.at < end and occurrence.verb is not None
            for entity in item.entity_ids
        ),
        key=lambda event: (event[0], event[1], event[2]),
    )
    found: dict[tuple[int, int, str], Conflict] = {}

    for _, group in groupby(events, key=lambda event: (event[0], event[1])):
        _same_minute([(index, occurrence) for _, _, index, occurrence in group], found)

    for routine_item in (item for item in planned if item.routine is not None):
        _against_window(routine_item, planned, (start, end), lookups, found)
    return sorted(found.values(), key=lambda c: (c.a, c.b, c.reason_key))


def _same_minute(
    bucket: list[tuple[int, Occurrence]], found: dict[tuple[int, int, str], Conflict]
) -> None:
    for (a, first), (b, second) in combinations(bucket, 2):
        if a == b or first.verb is None or OPPOSITES.get(first.verb) != second.verb:
            continue
        low, high = sorted((a, b))
        moment = min(first.at, second.at)
        found.setdefault((low, high, SAME_MINUTE), Conflict(low, high, SAME_MINUTE, moment))


def _against_window(
    routine_item: Planned,
    planned: Sequence[Planned],
    span: tuple[datetime, datetime],
    lookups: Lookups | None,
    found: dict[tuple[int, int, str], Conflict],
) -> None:
    start, end = span
    routine = routine_item.routine
    assert routine is not None  # noqa: S101  # the caller filters on it
    for other in planned:
        if other.index == routine_item.index or routine.target_entity not in other.entity_ids:
            continue
        for occurrence in other.occurrences:
            if not start <= occurrence.at < end:
                continue
            expected = expected_state(routine, occurrence.at, lookups=lookups)
            if occurrence.verb in DEACTIVATING and expected == "on":
                reason = OFF_IN_ON_WINDOW
            elif occurrence.verb in ACTIVATING and expected == "off":
                reason = ON_IN_OFF_WINDOW
            else:
                continue
            low, high = sorted((routine_item.index, other.index))
            found.setdefault((low, high, reason), Conflict(low, high, reason, occurrence.at))
