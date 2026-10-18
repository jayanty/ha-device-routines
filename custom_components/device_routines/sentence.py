"""Every user visible sentence of the schedule summary (TECH_SPEC 3.8, PRD FR-S2, FR-S4).

Sentences are assembled from a phrase table, `sentences/<lang>.json`, so a language is
added without code. The table lives next to the translations rather than inside them
because hassfest accepts only its own sections in `strings.json` (decision L27).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta
import json
from pathlib import Path
from typing import Any, Final

from .models import (
    ALL_DAYS,
    WEEKDAYS,
    WEEKEND,
    CalendarTrigger,
    FollowUp,
    NamedTrigger,
    NumericTrigger,
    Occurrence,
    ParsedLine,
    PatternTrigger,
    StartTrigger,
    StateTrigger,
    SunTrigger,
    TimeTrigger,
    TimeWindow,
    Trigger,
    Verb,
    Weekday,
)
from .parser_grammar import NAMED_TRIGGERS

STATE_CAP: Final = 40
SENTENCES_DIR: Final = Path(__file__).parent / "sentences"
DEFAULT_LANGUAGE: Final = "en"
TIME_FORMATS: Final = ("12h", "24h")

type Phrases = Mapping[str, str]

# A from state that is the plain opposite of the to state adds nothing to "turns on".
_OPPOSITE_STATES: Final[Mapping[str, str]] = {"on": "off", "off": "on"}

# Durations shorter than this read in minutes ("90 min"); longer ones in hours.
_HOURS_FROM: Final = 7200


def load_phrases(language: str) -> dict[str, str]:
    """Read the phrase table for a language, falling back to English. Blocking I/O."""
    path = SENTENCES_DIR / f"{language}.json"
    if not path.is_file():
        path = SENTENCES_DIR / f"{DEFAULT_LANGUAGE}.json"
    loaded: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


class Writer:
    """Builds sentences for one language, time format and set of entity names."""

    def __init__(
        self, phrases: Phrases, time_format: str, names: Mapping[str, str] | None = None
    ) -> None:
        if time_format not in TIME_FORMATS:
            raise ValueError(time_format)
        self.phrases = phrases
        self.time_format = time_format
        self.names: Mapping[str, str] = names or {}

    def say(self, key: str, **values: object) -> str:
        """Return one phrase with its placeholders filled."""
        return self.phrases[key].format(**values)

    # ----------------------------------------------------------------------------------
    # Values
    # ----------------------------------------------------------------------------------

    def clock(self, at: time) -> str:
        """Return a time of day: 9:00 AM in 12 hour format, 09:00 in 24 hour format."""
        seconds = f":{at.second:02d}" if at.second else ""
        if self.time_format == "24h":
            return f"{at.hour:02d}:{at.minute:02d}{seconds}"
        hour = at.hour % 12 or 12
        key = "time_am" if at.hour < 12 else "time_pm"  # noqa: PLR2004
        return self.say(key, time=f"{hour}:{at.minute:02d}{seconds}")

    def duration(self, period: timedelta) -> str:
        """Return a duration as hours, minutes and seconds: 1 h 30 min, 3 min, 45 s."""
        total = int(abs(period).total_seconds())
        hours, rest = divmod(total, 3600) if total >= _HOURS_FROM else (0, total)
        minutes, seconds = divmod(rest, 60)
        parts = [
            self.say(key, count=count)
            for key, count in (
                ("duration_hours", hours),
                ("duration_minutes", minutes),
                ("duration_seconds", seconds),
            )
            if count
        ]
        return " ".join(parts) or self.say("duration_seconds", count=0)

    def days(self, days: frozenset[Weekday]) -> str:
        """Return a day set: Weekdays, Weekends, or the days in week order."""
        if days == WEEKDAYS:
            return self.say("days_weekdays")
        if days == WEEKEND:
            return self.say("days_weekends")
        if not days:
            return self.say("days_none")
        ordered = sorted(days, key=lambda day: day.number)
        return self.say("list_separator").join(self.say(f"weekday_{day}") for day in ordered)

    def subject(self, entity: str, line: ParsedLine) -> str:
        """Return `it` for the line's own entity, else the entity's name."""
        if entity in line.entity_ids:
            return self.say("subject_self")
        return self.names.get(entity, entity)

    @staticmethod
    def number(value: float) -> str:
        """Return a number without a trailing .0."""
        return str(int(value)) if value == int(value) else str(value)

    def offset(self, base: str, offset: timedelta) -> str:
        """Return a base time with a signed offset, or the base alone."""
        if not offset:
            return base
        key = "offset_minus" if offset < timedelta(0) else "offset_plus"
        return self.say(key, base=base, duration=self.duration(offset))

    # ----------------------------------------------------------------------------------
    # Clauses
    # ----------------------------------------------------------------------------------

    def timed_clauses(self, line: ParsedLine) -> list[str]:
        """Return the clauses of a line's timed triggers, fixed times grouped by days."""
        groups: dict[frozenset[Weekday] | None, list[time]] = {}
        clauses: list[str] = []
        for trigger in line.triggers:
            if isinstance(trigger, TimeTrigger) and trigger.at is not None:
                groups.setdefault(trigger.weekdays, []).append(trigger.at)
            elif isinstance(trigger, TimeTrigger | SunTrigger | PatternTrigger):
                clauses.append(self.timed(trigger, line))
        grouped: list[str] = []
        line_days = line.weekdays if _folded(line) else None
        for days, times in groups.items():
            listed = self.say("list_separator").join(self.clock(at) for at in sorted(times))
            effective = self._effective_days(days, line_days)
            grouped.append(listed if effective == ALL_DAYS else f"{self.days(effective)} {listed}")
        return grouped + clauses

    @staticmethod
    def _effective_days(
        own: frozenset[Weekday] | None, line: frozenset[Weekday] | None
    ) -> frozenset[Weekday]:
        days = ALL_DAYS
        for limit in (own, line):
            if limit is not None:
                days &= limit
        return days

    def timed(self, trigger: TimeTrigger | SunTrigger | PatternTrigger, line: ParsedLine) -> str:
        """Return the clause of one timed trigger that is not a fixed time."""
        if isinstance(trigger, SunTrigger):
            return self.offset(self.say(f"sun_{trigger.event}"), trigger.offset)
        if isinstance(trigger, PatternTrigger):
            return self.pattern(trigger)
        entity = self.say("entity_time", subject=self.subject(trigger.entity or "", line))
        clause = self.offset(entity, trigger.offset)
        if trigger.weekdays is not None and trigger.weekdays != ALL_DAYS:
            return f"{self.days(trigger.weekdays)} {clause}"
        return clause

    def pattern(self, trigger: PatternTrigger) -> str:
        """Return a time pattern clause; anything unusual reads as a time pattern."""
        if trigger.seconds != "0":
            return self.say("pattern_custom")
        if trigger.hours == "*" and trigger.minutes == "*":
            return self.say("pattern_every_minute")
        if trigger.hours == "*" and trigger.minutes.startswith("/"):
            return self.say("pattern_every_minutes", count=int(trigger.minutes[1:]))
        if trigger.hours == "*" and trigger.minutes.isdigit():
            return self.say("pattern_every_hour_at", minute=f"{int(trigger.minutes):02d}")
        if trigger.hours.isdigit() and trigger.minutes.isdigit():
            hours, minutes = int(trigger.hours), int(trigger.minutes)
            if hours < 24 and minutes < 60:  # noqa: PLR2004
                return self.clock(time(hours, minutes))
        return self.say("pattern_custom")

    def change(self, trigger: StateTrigger) -> str:
        """Return what a state trigger waits for: turns on, is off for 5 min, changes."""
        to, origin = trigger.to, trigger.from_state
        if origin is not None and to is not None and _OPPOSITE_STATES.get(to) != origin:
            text = self.say("change_from_to", origin=origin, state=to)
            if trigger.duration is None:
                return text
            return self.say(
                "duration_suffix", clause=text, duration=self.duration(trigger.duration)
            )
        if trigger.duration is not None:
            return self._held(to, origin, trigger.duration)
        return self._moved(to, origin)

    def _moved(self, to: str | None, origin: str | None) -> str:
        if to in {"on", "off"}:
            return self.say(f"change_{to}")
        if to is not None:
            return self.say("change_to", state=to)
        if origin is not None:
            return self.say("change_from", state=origin)
        return self.say("change_any")

    def _held(self, to: str | None, origin: str | None, period: timedelta) -> str:
        duration = self.duration(period)
        if to in {"on", "off"}:
            return self.say(f"held_{to}", duration=duration)
        if to is not None:
            return self.say("held_to", state=to, duration=duration)
        if origin is not None:
            return self.say("held_from", state=origin, duration=duration)
        return self.say("held_any", duration=duration)

    def event_clauses(self, line: ParsedLine) -> list[str]:
        """Return the event clauses; state triggers waiting for the same change share one.

        "When A, B or C changes" instead of "when A changes or when B changes or ...".
        """
        groups: dict[tuple[str | None, str | None, timedelta | None], list[str]] = {}
        order: list[tuple[str, Any]] = []
        for trigger in line.triggers:
            if isinstance(trigger, StateTrigger):
                key = (trigger.to, trigger.from_state, trigger.duration)
                if key not in groups:
                    groups[key] = []
                    order.append(("state", trigger))
                subject = self.subject(trigger.entity, line)
                if subject not in groups[key]:
                    groups[key].append(subject)
            elif (clause := self.event(trigger, line)) is not None:
                order.append(("clause", clause))
        clauses: list[str] = []
        for kind, value in order:
            if kind == "clause":
                clauses.append(value)
                continue
            subjects = groups[(value.to, value.from_state, value.duration)]
            clauses.append(
                self.say("when_state", subject=self.subjects(subjects), change=self.change(value))
            )
        return clauses

    def subjects(self, names: Sequence[str]) -> str:
        """Return names as a list: A, B or C."""
        if len(names) == 1:
            return names[0]
        head = self.say("list_separator").join(names[:-1])
        return f"{head}{self.say('or_separator')}{names[-1]}"

    def event(self, trigger: Trigger, line: ParsedLine) -> str | None:
        """Return the clause of an event trigger; None for a timed one."""
        if isinstance(trigger, StateTrigger):
            subject = self.subject(trigger.entity, line)
            return self.say("when_state", subject=subject, change=self.change(trigger))
        if isinstance(trigger, NumericTrigger):
            return self._numeric(trigger, line)
        if isinstance(trigger, StartTrigger):
            return self.say(f"when_{trigger.event}")
        if isinstance(trigger, CalendarTrigger):
            clause = self.say(
                f"when_calendar_{trigger.event}", subject=self.subject(trigger.entity, line)
            )
            return self.offset(clause, trigger.offset)
        if isinstance(trigger, NamedTrigger):
            subjects = [self.subject(entity, line) for entity in trigger.entities]
            subject = self.say("or_separator").join(subjects) or self.say("subject_any")
            values = self.subjects(trigger.values) if trigger.values else ""
            return self.say(NAMED_TRIGGERS[trigger.name], subject=subject, values=values)
        return None

    def _numeric(self, trigger: NumericTrigger, line: ParsedLine) -> str:
        subject = self.subject(trigger.entity, line)
        if trigger.above is not None and trigger.below is not None:
            clause = self.say(
                "when_between",
                subject=subject,
                above=self.number(trigger.above),
                below=self.number(trigger.below),
            )
        elif trigger.above is not None:
            clause = self.say("when_above", subject=subject, value=self.number(trigger.above))
        else:
            assert trigger.below is not None  # noqa: S101  # the parser requires a bound
            clause = self.say("when_below", subject=subject, value=self.number(trigger.below))
        if trigger.duration is None:
            return clause
        return self.say("duration_suffix", clause=clause, duration=self.duration(trigger.duration))

    def window(self, window: TimeWindow, line: ParsedLine) -> str:
        """Return a time condition's window as a qualifier."""
        after = self._bound(window.after, line)
        before = self._bound(window.before, line)
        if after is not None and before is not None:
            return self.say("qualifier_between", after=after, before=before)
        if after is not None:
            return self.say("qualifier_after", after=after)
        return self.say("qualifier_before", before=before)

    def _bound(self, value: time | str | None, line: ParsedLine) -> str | None:
        if value is None:
            return None
        if isinstance(value, time):
            return self.clock(value)
        return self.say("entity_time", subject=self.subject(value, line))

    # ----------------------------------------------------------------------------------
    # Lines
    # ----------------------------------------------------------------------------------

    def action(self, verb: Verb, follow_ups: Sequence[FollowUp]) -> str:
        """Return the action part: off, or off for 3 min, then on."""
        text = self.say(f"verb_{verb}")
        for follow_up in follow_ups:
            text = self.say(
                "follow_up",
                action=text,
                duration=self.duration(follow_up.delay),
                verb=self.say(f"verb_{follow_up.verb}"),
            )
        return text

    def tail(self, line: ParsedLine) -> str:
        """Return the condition count and the custom logic note, if any."""
        text = ""
        if line.condition_count == 1:
            text += self.say("conditions_one")
        elif line.condition_count > 1:
            text += self.say("conditions_many", count=line.condition_count)
        if line.custom_logic:
            text += self.say("plus_custom")
        return text

    def _after_form(self, line: ParsedLine) -> str | None:
        """Return "Off 60 min after it turns on" when a line has exactly that shape."""
        if len(line.triggers) != 1 or line.weekdays is not None or line.windows:
            return None
        trigger = line.triggers[0]
        if not (
            isinstance(trigger, StateTrigger)
            and trigger.duration is not None
            and trigger.to in {"on", "off"}
            and trigger.from_state is None
            and trigger.entity in line.entity_ids
            and line.verb is not None
            and not line.follow_ups
        ):
            return None
        text = self.say(
            "line_after",
            verb=self.say(f"verb_{line.verb}"),
            duration=self.duration(trigger.duration),
            subject=self.say("subject_self"),
            change=self.say(f"change_{trigger.to}"),
        )
        return _capitalized(text) + self.tail(line)

    def line(self, line: ParsedLine) -> str:
        """Return the summary line of one action on a device."""
        if not line.understood or line.verb is None:
            return self.say("automation_custom", alias=line.alias)
        if (after := self._after_form(line)) is not None:
            return after
        clauses = self.timed_clauses(line)
        clauses += self.event_clauses(line)
        qualifiers = [self.window(window, line) for window in line.windows]
        if line.weekdays is not None and not _folded(line):
            qualifiers.insert(0, self.say("qualifier_days", days=self.days(line.weekdays)))
        when = self.say("or_separator").join(clauses)
        action = self.action(line.verb, line.follow_ups)
        if qualifiers:
            qualified = self.say("list_separator").join(qualifiers)
            text = self.say("line_qualified", when=when, qualifiers=qualified, action=action)
        else:
            text = self.say("line", when=when, action=action)
        return _capitalized(text) + self.tail(line)

    # ----------------------------------------------------------------------------------
    # The sensor state
    # ----------------------------------------------------------------------------------

    def state(self, upcoming: Occurrence | None, fallback: str | None, now: datetime) -> str | None:
        """Return the Schedule sensor state, at most 40 characters; None with nothing to say.

        The earliest timed action wins: "Off at 9:00 AM" today, "Start Wed 9:45 AM" on
        another day. Past the cap the weekday goes, then the sentence falls back to
        "Next: 9:45 AM". With no timed action the first event driven line is shown.
        """
        if upcoming is not None:
            at = upcoming.at
            clock = self.clock(at.time().replace(tzinfo=None))
            candidates: list[str] = []
            if upcoming.verb is not None:
                verb = self.say(f"state_verb_{upcoming.verb}")
                if at.date() == now.date():
                    candidates.append(self.say("state_today", verb=verb, time=clock))
                else:
                    weekday = self.say(f"weekday_{Weekday.of(at)}")
                    candidates.append(
                        self.say("state_other_day", verb=verb, weekday=weekday, time=clock)
                    )
                    candidates.append(self.say("state_short", verb=verb, time=clock))
            candidates.append(self.say("state_next", time=clock))
            return self.capped(next((c for c in candidates if len(c) <= STATE_CAP), candidates[-1]))
        if fallback:
            return self.capped(fallback)
        return None

    def capped(self, text: str) -> str:
        """Return text cut to the state cap with an ellipsis."""
        if len(text) <= STATE_CAP:
            return text
        ellipsis = self.say("ellipsis")
        return text[: STATE_CAP - len(ellipsis)].rstrip() + ellipsis

    # ----------------------------------------------------------------------------------
    # The states of a routine (PRD FR-S4): skipped, paused, off
    # ----------------------------------------------------------------------------------

    def skipped(self, verb: Verb, at: datetime, now: datetime) -> str:
        """Return the state of a skipping routine, naming the next action that will run.

        "Skipped, on Thu 5:00 PM". At most 40 characters: past the cap the weekday goes,
        then the text is cut. A week or more ahead the date replaces the weekday.
        """
        action = self.say(f"verb_{verb}")
        return self._fitting(
            [self.say("state_skipped", action=action, when=when) for when in self._when(at, now)]
        )

    def paused(self, until: datetime, now: datetime) -> str:
        """Return the state of a paused routine: "Paused until Sun 6:00 PM", capped alike."""
        return self._fitting(
            [self.say("state_paused", when=when) for when in self._when(until, now)]
        )

    def routine_off(self) -> str:
        """Return the state of a routine whose Routine switch is off: "Routine off"."""
        return self.capped(self.say("state_routine_off"))

    def automations_off(self, count: int) -> str:
        """Return the state of a device whose automations are all off: "Automation off".

        "Automations off" for several; nothing they would do is planned. A routine that is
        off reads "Routine off" instead (`routine_off`).
        """
        key = "state_automation_off" if count == 1 else "state_automations_off"
        return self.capped(self.say(key))

    def routine_kind(self, *, detached: bool = False) -> str:
        """Return how a routine item is labeled: Routine, or Detached routine."""
        return self.say("kind_detached" if detached else "kind_routine")

    def _when(self, at: datetime, now: datetime) -> list[str]:
        """Return the ways to say when, longest first.

        Today the time; within the coming week the weekday and the time, or the time
        alone; later the date and the time.
        """
        moment = at.astimezone(now.tzinfo)
        clock = self.clock(moment.time().replace(tzinfo=None))
        days = (moment.date() - now.date()).days
        if days == 0:
            return [clock]
        if 0 < days < len(Weekday):
            return [f"{self.say(f'weekday_{Weekday.of(moment)}')} {clock}", clock]
        return [f"{moment.date().isoformat()} {clock}"]

    def _fitting(self, candidates: Sequence[str]) -> str:
        """Return the first candidate within the cap, or the last one cut to it."""
        return self.capped(next((c for c in candidates if len(c) <= STATE_CAP), candidates[-1]))


def _folded(line: ParsedLine) -> bool:
    """Tell whether a line's weekdays read as part of its fixed times."""
    return all(isinstance(t, TimeTrigger) and t.at is not None for t in line.triggers)


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]
