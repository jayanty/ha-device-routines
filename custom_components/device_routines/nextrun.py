"""Next runs and expected states (TECH_SPEC 3.6, PRD FR-S3).

Times are local wall clock. Daylight saving follows what the core time trigger does
(Stage 0 V10, decision L21): a wall clock time that does not exist on the spring forward
day does not run that day at all, and one that exists twice on the fall back day runs
twice, once per offset, an hour apart. `tests/stage0/test_v10_schedule_dst.py` holds the
core behavior; the tests of this module use the same dates.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from .models import (
    Days,
    Occurrence,
    ParsedLine,
    PatternTrigger,
    RoutineSettings,
    SunTrigger,
    TimeTrigger,
    TimeWindow,
    Trigger,
    Weekday,
)

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
