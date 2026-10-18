"""Next runs and expected states (TECH_SPEC 3.6, PRD FR-S3).

Times are local wall clock. Daylight saving follows what the core time trigger does
(Stage 0 V10, decision L21): a wall clock time that does not exist on the spring forward
day does not run that day at all, and one that exists twice on the fall back day runs
twice, once per offset, an hour apart. `tests/stage0/test_v10_schedule_dst.py` holds the
core behavior; the tests of this module use the same dates.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import IntEnum
from typing import Any, Final

from .domains import PROFILES
from .models import (
    ALL_DAYS,
    Days,
    FollowUp,
    NamedTrigger,
    Occurrence,
    ParsedLine,
    PatternTrigger,
    RoutineSettings,
    StateTrigger,
    SunTrigger,
    TimeTrigger,
    TimeWindow,
    Trigger,
    Verb,
    Weekday,
)
from .parser_grammar import ACTION_VERBS

# Sunrise or sunset for a local date, as an aware datetime; None when the sun does not
# rise or set that day. The summary passes Home Assistant's astral helper.
type SunLookup = Callable[[date, str], datetime | None]

# What an entity named in a time trigger or condition holds: a time of day (an
# input_datetime with a time only) or a moment (a timestamp sensor, a dated helper).
type EntityTimes = Mapping[str, time | datetime]

DEFAULT_HORIZON = timedelta(days=8)


@dataclass(frozen=True, slots=True)
class Lookups:
    """What a next run may need from the instance: the sun and entity held times."""

    sun: SunLookup | None = None
    entity_times: EntityTimes = field(default_factory=dict)


DEFAULT_LIMIT = 100


def wall_instants(day: date, at: time, tz: tzinfo) -> list[datetime]:
    """Return the instants a wall clock time has on a day: none, one, or two at fall back."""
    naive = datetime.combine(day, at)
    first = naive.replace(tzinfo=tz)
    if first.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive:
        return []
    second = naive.replace(tzinfo=tz, fold=1)
    if first.utcoffset() != second.utcoffset():
        return [first, second]
    return [first]


def in_window(at: time, after: time | None, before: time | None) -> bool:
    """Apply the core time condition's after and before rule to a time of day."""
    if after is not None and before is not None:
        if after < before:
            return after <= at < before
        return not before <= at < after
    if after is not None:
        return at >= after
    if before is not None:
        return at < before
    return True


class _UnknownBoundError(Exception):
    """A window bound names an entity whose time is not known."""


def _bound(value: time | str | None, entity_times: EntityTimes) -> time | None:
    """Return a fixed bound or a resolved entity bound; raise when it cannot be known."""
    if value is None or isinstance(value, time):
        return value
    held = entity_times.get(value)
    if held is None:
        raise _UnknownBoundError
    return held.timetz().replace(tzinfo=None) if isinstance(held, datetime) else held


def _window_filter(
    windows: Iterable[TimeWindow], entity_times: EntityTimes
) -> Callable[[time], bool] | None:
    """Return a predicate for every window, or None when a bound cannot be known."""
    try:
        bounds = [
            (_bound(window.after, entity_times), _bound(window.before, entity_times))
            for window in windows
        ]
    except _UnknownBoundError:
        return None
    return lambda at: all(in_window(at, after, before) for after, before in bounds)


def _days(start: date, horizon: timedelta) -> Iterator[date]:
    for offset in range(horizon.days + 1):
        yield start + timedelta(days=offset)


def _pattern_values(text: str, maximum: int) -> list[int]:
    if text == "*":
        return list(range(maximum))
    if text.startswith("/"):
        step = int(text[1:])
        return list(range(0, maximum, step)) if step else []
    value = int(text)
    return [value] if value < maximum else []


def _pattern_times(trigger: PatternTrigger) -> list[time]:
    hours = _pattern_values(trigger.hours, 24)
    minutes = _pattern_values(trigger.minutes, 60)
    second = int(trigger.seconds)
    if second > 59:  # noqa: PLR2004
        return []
    return [time(hour, minute, second) for hour in hours for minute in minutes]


def _time_instants(
    trigger: TimeTrigger, day: date, tz: tzinfo, entity_times: EntityTimes
) -> list[datetime]:
    if trigger.weekdays is not None and Weekday.of(datetime.combine(day, time())) not in (
        trigger.weekdays
    ):
        return []
    if trigger.at is not None:
        return wall_instants(day, trigger.at, tz)
    held = entity_times.get(trigger.entity or "")
    if isinstance(held, datetime):
        moment = held.astimezone(tz) + trigger.offset
        return [moment] if moment.date() == day else []
    if isinstance(held, time):
        return [instant + trigger.offset for instant in wall_instants(day, held, tz)]
    return []


def _trigger_instants(trigger: Trigger, day: date, tz: tzinfo, lookups: Lookups) -> list[datetime]:
    """Return the instants a timed trigger fires on one local day."""
    if isinstance(trigger, TimeTrigger):
        return _time_instants(trigger, day, tz, lookups.entity_times)
    if isinstance(trigger, PatternTrigger):
        return [i for at in _pattern_times(trigger) for i in wall_instants(day, at, tz)]
    if isinstance(trigger, SunTrigger) and lookups.sun is not None:
        moment = lookups.sun(day, trigger.event)
        return [] if moment is None else [moment.astimezone(tz) + trigger.offset]
    return []


def next_occurrences(
    line: ParsedLine,
    now: datetime,
    lookups: Lookups | None = None,
    *,
    horizon: timedelta = DEFAULT_HORIZON,
    limit: int = DEFAULT_LIMIT,
) -> list[Occurrence]:
    """Return the future runs of a timed line, follow ups included, in time order.

    `now` is an aware local datetime; its tzinfo is the Home Assistant time zone. A line
    whose window bounds name entities with no known time has no computable run.
    """
    if not line.understood or not line.timed:
        return []
    lookups = lookups or Lookups()
    allowed = _window_filter(line.windows, lookups.entity_times)
    if allowed is None:
        return []
    tz = now.tzinfo
    assert tz is not None  # noqa: S101  # the caller passes an aware datetime
    found: list[Occurrence] = []
    # Start a day early: a sun or entity trigger with an offset can move into today.
    for day in _days(now.date() - timedelta(days=1), horizon + timedelta(days=1)):
        today: list[Occurrence] = []
        for trigger in line.triggers:
            for instant in _trigger_instants(trigger, day, tz, lookups):
                local = instant.astimezone(tz)
                if line.weekdays is not None and Weekday.of(local) not in line.weekdays:
                    continue
                if not allowed(local.time()):
                    continue
                today.append(Occurrence(at=local, verb=line.verb))
                at = local
                for follow_up in line.follow_ups:
                    at += follow_up.delay
                    today.append(Occurrence(at=at, verb=follow_up.verb))
        found.extend(sorted((o for o in today if o.at > now), key=lambda o: o.at))
        if len(found) >= limit:
            break
    found.sort(key=lambda o: o.at)
    return found[:limit]


def next_run(line: ParsedLine, now: datetime, lookups: Lookups | None = None) -> datetime | None:
    """Return the first future run of a line, or None for an event driven line."""
    upcoming = next_occurrences(line, now, lookups, limit=1)
    return upcoming[0].at if upcoming else None


def earliest(occurrences: Iterable[Occurrence]) -> Occurrence | None:
    """Return the first occurrence; its verb is None when actions at that instant disagree.

    Two lines that run at the same instant with different actions are decided by their
    conditions, so the state names the time only.
    """
    ordered = sorted(occurrences, key=lambda occurrence: occurrence.at)
    if not ordered:
        return None
    first = ordered[0]
    verbs = {occurrence.verb for occurrence in ordered if occurrence.at == first.at}
    return first if len(verbs) == 1 else Occurrence(at=first.at, verb=None)


def expected_state(
    settings: RoutineSettings, now: datetime, schedule_state: str | None = None
) -> str | None:
    """Return `on` or `off` as a routine's window expects now; None without a window.

    A window belongs to the weekday it starts on: from 17:00 to 09:00 on weekdays, Monday
    08:00 is off, because Sunday is not a start day.
    """
    if settings.days is Days.WEEKLY_SCHEDULE:
        return schedule_state if schedule_state in {"on", "off"} else None
    if settings.on_time is None or settings.off_time is None:
        return None
    days = settings.effective_days
    at = now.time().replace(tzinfo=None)
    today = Weekday.of(now)
    yesterday = Weekday.of(now - timedelta(days=1))
    if settings.on_time < settings.off_time:
        inside = today in days and settings.on_time <= at < settings.off_time
    else:
        inside = (today in days and at >= settings.on_time) or (
            yesterday in days and at < settings.off_time
        )
    return "on" if inside else "off"


# --------------------------------------------------------------------------------------
# A routine's own actions and Skip next (PRD FR-R11, D18, D19; TECH_SPEC 3.6)
# --------------------------------------------------------------------------------------

# Skip next pauses until one minute after the last action it skips (FR-R11).
SKIP_MARGIN: Final = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class SkipTarget:
    """What Skip next skips and the Paused until value that skips it.

    `verb` and `at` are the action the Schedule state shows next; `paired_end` is the end
    of the window that action starts (D18), None for anything skipped alone (D19);
    `paused_until` is one minute after the last skipped action.
    """

    verb: Verb
    at: datetime
    paired_end: datetime | None
    paused_until: datetime


class _Kind(IntEnum):
    """What a routine action is; the value orders actions that share an instant."""

    WINDOW_START = 0
    WINDOW_END = 1
    ONE_SHOT = 2
    BLOCK_START = 3
    BLOCK_END = 4
    PULSE = 5
    COUNTDOWN = 6


@dataclass(frozen=True, slots=True)
class _Action:
    at: datetime
    verb: Verb
    kind: _Kind


def routine_verbs(target_entity: str) -> tuple[Verb, Verb]:
    """Return the verbs of a target's on and off actions, as the sentences name them."""
    profile = PROFILES.get(target_entity.partition(".")[0])
    if profile is None:
        return Verb.ON, Verb.OFF
    on = ACTION_VERBS[profile.on_action.partition(".")[2]] if profile.on_action else Verb.ON
    return on, ACTION_VERBS[profile.off_action.partition(".")[2]]


def routine_lines(settings: RoutineSettings, automation_id: str, alias: str) -> list[ParsedLine]:
    """Return the routine's actions as parsed lines the Writer renders, one per action.

    The Schedule summary reads an owned routine this way, from its inputs, rather than
    parsing the rendered blueprint (PRD 12's round trip; the parser cannot read the
    shipped blueprint): the manager's item and the summary's index say the same.
    """
    target = settings.target_entity
    on, off = routine_verbs(target)
    profile = PROFILES.get(target.partition(".")[0])
    inactive = profile.inactive_state if profile else "off"

    def line(verb: Verb, *triggers: Any, follow_ups: tuple[FollowUp, ...] = ()) -> ParsedLine:
        return ParsedLine(
            automation_id=automation_id,
            alias=alias,
            entity_ids=(target,),
            verb=verb,
            triggers=triggers,
            follow_ups=follow_ups,
        )

    def days(day_set: frozenset[Weekday]) -> frozenset[Weekday] | None:
        return None if day_set == ALL_DAYS else day_set

    lines: list[ParsedLine] = []
    if settings.on_time is not None:
        lines.append(
            line(on, TimeTrigger(at=settings.on_time, weekdays=days(settings.effective_days)))
        )
    if settings.off_time is not None:
        lines.append(line(off, TimeTrigger(at=settings.off_time, weekdays=days(settings.end_days))))
    if settings.days is Days.WEEKLY_SCHEDULE and settings.schedule_entity is not None:
        blocks = (settings.schedule_entity,)
        lines.append(line(on, NamedTrigger("schedule.block_started", blocks)))
        lines.append(line(off, NamedTrigger("schedule.block_ended", blocks)))
    active = "on" if inactive == "off" else None
    if settings.turn_off_after_min:
        period = timedelta(minutes=settings.turn_off_after_min)
        moved = None if active else inactive
        lines.append(line(off, StateTrigger(target, active, moved, period)))
    if settings.turn_back_on_after_min:
        period = timedelta(minutes=settings.turn_back_on_after_min)
        lines.append(line(on, StateTrigger(target, inactive, None, period)))
    if settings.pulse is not None:
        back = (FollowUp(timedelta(minutes=settings.pulse.minutes), Verb.TOGGLE),)
        lines.append(line(Verb.TOGGLE, TimeTrigger(at=settings.pulse.at), follow_ups=back))
    return lines


def _block_change(
    settings: RoutineSettings,
    schedule_state: str | None,
    lookups: Lookups | None,
    verbs: tuple[Verb, Verb],
    tz: tzinfo,
) -> _Action | None:
    """Return the weekly schedule's next change, from its `next_event` in the lookups."""
    if settings.days is not Days.WEEKLY_SCHEDULE or settings.schedule_entity is None:
        return None
    held = (lookups or Lookups()).entity_times.get(settings.schedule_entity)
    if not isinstance(held, datetime) or schedule_state not in {"on", "off"}:
        return None
    if schedule_state == "on":
        return _Action(held.astimezone(tz), verbs[1], _Kind.BLOCK_END)
    return _Action(held.astimezone(tz), verbs[0], _Kind.BLOCK_START)


def _countdown(
    settings: RoutineSettings, ends: datetime | None, verbs: tuple[Verb, Verb], tz: tzinfo
) -> _Action | None:
    """Return the running countdown's action: off after Turn off after, on after keep alive."""
    if ends is None:
        return None
    if settings.turn_off_after_min:
        return _Action(ends.astimezone(tz), verbs[1], _Kind.COUNTDOWN)
    if settings.turn_back_on_after_min:
        return _Action(ends.astimezone(tz), verbs[0], _Kind.COUNTDOWN)
    return None


def _upcoming(  # noqa: PLR0913  # the routine's whole runtime picture
    settings: RoutineSettings,
    now: datetime,
    schedule_state: str | None,
    lookups: Lookups | None,
    *,
    countdown_ends: datetime | None,
    not_before: datetime | None,
) -> list[_Action]:
    """Return the routine's actions after `now` and at or after `not_before`, in order."""
    tz = now.tzinfo
    assert tz is not None  # noqa: S101  # the caller passes an aware datetime
    start = now
    if not_before is not None and not_before.astimezone(tz) > now:
        start = not_before.astimezone(tz)
    verbs = routine_verbs(settings.target_entity)
    window = settings.on_time is not None and settings.off_time is not None
    timed: list[tuple[time, frozenset[Weekday], Verb, _Kind]] = []
    if settings.on_time is not None:
        kind = _Kind.WINDOW_START if window else _Kind.ONE_SHOT
        timed.append((settings.on_time, settings.effective_days, verbs[0], kind))
    if settings.off_time is not None:
        kind = _Kind.WINDOW_END if window else _Kind.ONE_SHOT
        timed.append((settings.off_time, settings.end_days, verbs[1], kind))
    if settings.pulse is not None:
        timed.append((settings.pulse.at, ALL_DAYS, Verb.TOGGLE, _Kind.PULSE))
    found: list[_Action] = []
    # A day early for a window that started yesterday; two days late for its end.
    for day in _days(start.date() - timedelta(days=1), DEFAULT_HORIZON + timedelta(days=2)):
        weekday = Weekday.of(datetime.combine(day, time()))
        for at, days, verb, kind in timed:
            if weekday in days:
                found.extend(_Action(instant, verb, kind) for instant in wall_instants(day, at, tz))
    extras = (
        _block_change(settings, schedule_state, lookups, verbs, tz),
        _countdown(settings, countdown_ends, verbs, tz),
    )
    found.extend(extra for extra in extras if extra is not None)
    found.sort(key=lambda action: (action.at, action.kind))
    return [action for action in found if action.at > now and action.at >= start]


def routine_occurrences(  # noqa: PLR0913  # the routine's whole runtime picture
    settings: RoutineSettings,
    now: datetime,
    schedule_state: str | None = None,
    lookups: Lookups | None = None,
    *,
    countdown_ends: datetime | None = None,
    not_before: datetime | None = None,
) -> list[Occurrence]:
    """Return a routine's coming actions, the first being the one its Schedule state shows.

    The actions mirror the blueprint (TECH_SPEC 5.5): the on time on the start days, the
    off time on the end days (a window belongs to the day it starts on), the pulse every
    day as a toggle, a weekly schedule's next change when `lookups.entity_times` holds the
    schedule's `next_event` (its state says whether that change is an end or a start), and
    a running countdown that ends at `countdown_ends`. Actions before `not_before` (a
    Paused until value) do not run and are left out; one exactly at it runs. Instants are
    in the zone of `now`, an aware local datetime.
    """
    return [
        Occurrence(action.at, action.verb)
        for action in _upcoming(
            settings,
            now,
            schedule_state,
            lookups,
            countdown_ends=countdown_ends,
            not_before=not_before,
        )
    ]


def skip_target(  # noqa: PLR0913  # the contract's five values, the countdown and the block
    settings: RoutineSettings,
    now: datetime,
    paused_until: datetime | None = None,
    schedule_state: str | None = None,
    sun: Lookups | None = None,
    *,
    countdown_ends: datetime | None = None,
    block: tuple[datetime, datetime] | None = None,
) -> SkipTarget | None:
    """Return what Skip next skips now, or None when nothing is scheduled.

    The skipped action is the first of `routine_occurrences` after the current Paused until,
    so pressing again extends the skip to the following action. A window start takes its
    paired end along (D18); a window end, a one shot run, a pulse or a running countdown is
    skipped alone (D19), and the manager cancels a skipped countdown's timer (FR-R11). A
    weekly schedule's next block start takes its block end along, as a window start does
    (decision L38): the schedule entity does not hold that end, so the manager reads the
    helper's blocks and passes the block's start and end as `block` (`block_bounds`); a
    block start without it, or with a block that does not start then, gives None. `sun`
    carries the lookups (the schedule's `next_event`; sunrise and sunset arrive with
    Build B).
    """
    upcoming = _upcoming(
        settings, now, schedule_state, sun, countdown_ends=countdown_ends, not_before=paused_until
    )
    if not upcoming:
        return None
    first = upcoming[0]
    if first.kind is _Kind.BLOCK_START:
        return _block_skip(first, block)
    paired_end = None
    if first.kind is _Kind.WINDOW_START:
        paired_end = next(
            (a.at for a in upcoming if a.kind is _Kind.WINDOW_END and a.at > first.at), None
        )
    return SkipTarget(first.verb, first.at, paired_end, (paired_end or first.at) + SKIP_MARGIN)


# --------------------------------------------------------------------------------------
# Weekly schedule blocks (Build A lane 14, decision L38)
# --------------------------------------------------------------------------------------

# A schedule helper's blocks per weekday: `from` and `to` wall clock times, `to` being
# `time.max` for a block that ends at midnight (the helper's 24:00:00).
type WeeklyBlocks = Mapping[Weekday, Sequence[tuple[time, time]]]

# The weekday keys of a `schedule/list` item, Monday first.
_SCHEDULE_DAYS: Final = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_END_OF_DAY: Final = "24:00"


def _block_time(value: Any) -> time | None:
    """Return a block bound as a time of day: 24:00 is `time.max`; None when unreadable."""
    if not isinstance(value, str):
        return None
    if value.startswith(_END_OF_DAY):
        return time.max
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


def weekly_blocks(item: Mapping[str, Any]) -> dict[Weekday, tuple[tuple[time, time], ...]]:
    """Read a schedule helper's blocks from its `schedule/list` item.

    Each weekday key holds a list of `{from, to}` mappings with `HH:MM:SS` times; the core
    writes a block ending at midnight as `24:00:00`. A block that does not read is left
    out, and a day without blocks is not in the result.
    """
    found: dict[Weekday, tuple[tuple[time, time], ...]] = {}
    for weekday, key in zip(Weekday, _SCHEDULE_DAYS, strict=True):
        spans = item.get(key)
        if not isinstance(spans, list):
            continue
        read = []
        for span in spans:
            if not isinstance(span, Mapping):
                continue
            start, end = _block_time(span.get("from")), _block_time(span.get("to"))
            if start is not None and end is not None:
                read.append((start, end))
        if read:
            found[weekday] = tuple(read)
    return found


def block_bounds(blocks: WeeklyBlocks, start: datetime) -> tuple[datetime, datetime] | None:
    """Return the block of a weekly schedule that starts at `start`, with its end.

    `start` is the schedule's `next_event` as an aware datetime; the result is in its zone,
    and the wall clock end is placed on its own day, so a block over a daylight saving
    night ends at the end the helper shows. Blocks that meet, on one day or across
    midnight, are one block: the schedule stays on between them (Stage 0 V10, A6). None
    when no block starts then, or when the blocks never end (on all week).
    """
    tz = start.tzinfo
    day = start.date()
    weekday = Weekday.of(start)
    at = start.time().replace(microsecond=0)

    def starting(on: Weekday, moment: time) -> time | None:
        return next((end for begin, end in blocks.get(on, ()) if begin == moment), None)

    end = starting(weekday, at)
    for _ in range(sum(len(spans) for spans in blocks.values())):
        if end is None:
            return None
        if end == time.max:
            day += timedelta(days=1)
            weekday = weekday.following
            following = starting(weekday, time(0))
            moment = time(0)
        else:
            following = starting(weekday, end)
            moment = end
        if following is None:
            return start, datetime.combine(day, moment).replace(tzinfo=tz)
        end = following
    return None


def _continues(blocks: WeeklyBlocks, weekday: Weekday, begin: time) -> bool:
    """Tell whether a block starting then continues another, so it starts nothing (A6)."""
    if any(end == begin for _start, end in blocks.get(weekday, ())):
        return True
    previous = list(Weekday)[(weekday.number - 1) % len(Weekday)]
    return begin == time(0) and any(end == time.max for _start, end in blocks.get(previous, ()))


def next_block(blocks: WeeklyBlocks, after: datetime) -> tuple[datetime, datetime] | None:
    """Return the first block of a weekly schedule that starts at or after `after`.

    With its end, as `block_bounds` gives it. `after` is a local moment: its zone is the
    wall clock the blocks are read in and the zone of the answer. Blocks that meet are
    one block (A6), so a block that continues another starts nothing. The manager asks
    it for what runs after a skipped block and what a second Skip next skips (L53).
    None without blocks, or when the blocks never end.
    """
    tz = after.tzinfo
    assert tz is not None  # noqa: S101  # the caller passes an aware datetime
    for offset in range(len(Weekday) + 1):
        day = after.date() + timedelta(days=offset)
        weekday = Weekday.of(datetime.combine(day, time()))
        for begin, _end in sorted(blocks.get(weekday, ())):
            if _continues(blocks, weekday, begin):
                continue
            for start in wall_instants(day, begin, tz):
                if start >= after:
                    return block_bounds(blocks, start)
    return None


def _block_skip(first: _Action, block: tuple[datetime, datetime] | None) -> SkipTarget | None:
    """Skip a weekly schedule's next block start with its end, when `block` is that block."""
    if block is None or block[0] != first.at:
        return None
    tz = first.at.tzinfo
    end = block[1].astimezone(tz)
    return SkipTarget(first.verb, first.at, end, end + SKIP_MARGIN)
