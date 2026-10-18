"""The deterministic schedule parser (TECH_SPEC 3.5, PRD FR-S2).

`summarize(config, device)` turns one automation config into one `ParsedLine` per action
on the device. Every construct it reads is listed in `parser_grammar`; anything else is
never guessed: it sets `custom_logic`, or, when nothing about an action was understood,
`understood = False`. The sentences themselves are built by `sentence.py`, so this module
deals in structure only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import time, timedelta
import re
from typing import Any

from . import parser_grammar as grammar
from .models import (
    CalendarTrigger,
    DeviceContext,
    FollowUp,
    NamedTrigger,
    NumericTrigger,
    ParsedLine,
    ParseError,
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

_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_REGISTRY_ID = re.compile(r"^[0-9a-f]{32}$")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_DURATION = re.compile(r"^(-)?(\d+):(\d{2})(?::(\d{2})(?:\.\d+)?)?$")
_IGNORED_UNAVAILABLE = frozenset({"unknown", "unavailable"})

# Keys every trigger may carry without changing what it means.
_TRIGGER_COMMON = frozenset({"trigger", "platform", "id", "alias", "enabled", "variables"})

# --------------------------------------------------------------------------------------
# Small value parsers
# --------------------------------------------------------------------------------------


def _templated(value: Any) -> bool:
    """Tell whether a template appears anywhere in a value."""
    if isinstance(value, str):
        return "{{" in value or "{%" in value
    if isinstance(value, Mapping):
        return any(_templated(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_templated(item) for item in value)
    return False


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    return [value]


def parse_time(value: Any) -> time | None:
    """`HH:MM` or `HH:MM:SS` as a time of day; None for anything else."""
    if not isinstance(value, str):
        return None
    match = _TIME.match(value.strip())
    if match is None:
        return None
    hours, minutes, seconds = int(match[1]), int(match[2]), int(match[3] or 0)
    if hours > 23 or minutes > 59 or seconds > 59:  # noqa: PLR2004
        return None
    return time(hours, minutes, seconds)


def _duration_text(value: str) -> timedelta | None:
    match = _DURATION.match(value.strip())
    if match is None:
        return None
    sign = -1 if match[1] else 1
    return sign * timedelta(hours=int(match[2]), minutes=int(match[3]), seconds=int(match[4] or 0))


def _duration_mapping(value: Mapping[str, Any]) -> timedelta | None:
    units = {"days", "hours", "minutes", "seconds", "milliseconds"}
    if not value or set(value) - units:
        return None
    if not all(_number(amount) is not None for amount in value.values()):
        return None
    return timedelta(**{unit: float(amount) for unit, amount in value.items()})


def parse_duration(value: Any) -> timedelta | None:
    """Read a time period: seconds, `[-]H:MM[:SS]` or a mapping; None otherwise."""
    if (seconds := _number(value)) is not None:
        return timedelta(seconds=seconds)
    if isinstance(value, str):
        return _duration_text(value)
    if isinstance(value, Mapping):
        return _duration_mapping(value)
    return None


def _weekdays(value: Any) -> frozenset[Weekday] | None:
    days = _as_list(value)
    if not days or not all(isinstance(day, str) and day in Weekday for day in days):
        return None
    return frozenset(Weekday(day) for day in days)


def _is_entity_id(value: Any) -> bool:
    return isinstance(value, str) and _ENTITY_ID.match(value) is not None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


# --------------------------------------------------------------------------------------
# Triggers
# --------------------------------------------------------------------------------------


def _resolve(entity: Any, device: DeviceContext) -> str | None:
    """Return an entity id, resolving a registry id; None when it cannot be resolved."""
    if not isinstance(entity, str):
        return None
    if _REGISTRY_ID.match(entity):
        return device.registry_ids.get(entity)
    return entity if _is_entity_id(entity) else None


def _only(node: Mapping[str, Any], allowed: Iterable[str]) -> bool:
    return set(node) <= _TRIGGER_COMMON | set(allowed)


def _time_triggers(node: Mapping[str, Any]) -> list[Trigger] | None:
    if not _only(node, {"at", "weekday"}):
        return None
    weekdays = None
    if "weekday" in node:
        weekdays = _weekdays(node["weekday"])
        if weekdays is None:
            return None
    found: list[Trigger] = []
    for at in _as_list(node.get("at")):
        if (fixed := parse_time(at)) is not None:
            found.append(TimeTrigger(at=fixed, weekdays=weekdays))
        elif _is_entity_id(at):
            found.append(TimeTrigger(entity=at, weekdays=weekdays))
        elif isinstance(at, Mapping) and _is_entity_id(at.get("entity_id")):
            offset = parse_duration(at.get("offset", 0))
            if offset is None or set(at) - {"entity_id", "offset"}:
                return None
            found.append(TimeTrigger(entity=at["entity_id"], offset=offset, weekdays=weekdays))
        else:
            return None
    return found or None


def _pattern_trigger(node: Mapping[str, Any]) -> list[Trigger] | None:
    if not _only(node, {"hours", "minutes", "seconds"}):
        return None
    fields: dict[str, str | None] = {}
    for unit in ("hours", "minutes", "seconds"):
        raw = node.get(unit)
        text = None if raw is None else str(raw)
        if text is not None and not grammar.PATTERN_FIELD.match(text):
            return None
        fields[unit] = text
    hours, minutes, seconds = fields["hours"], fields["minutes"], fields["seconds"]
    if hours is None and minutes is None and seconds is None:
        return None
    # The core defaults smaller units to zero when a larger one is given.
    if minutes is None and hours is not None:
        minutes = "0"
    if seconds is None and minutes is not None:
        seconds = "0"
    # Minute precision is the summary's resolution: a seconds pattern is not read.
    if seconds is None or not seconds.isdigit():
        return None
    return [PatternTrigger(hours=hours or "*", minutes=minutes or "*", seconds=seconds)]


def _sun_trigger(node: Mapping[str, Any]) -> list[Trigger] | None:
    if not _only(node, {"event", "offset"}) or node.get("event") not in grammar.SUN_EVENTS:
        return None
    offset = parse_duration(node.get("offset", 0))
    if offset is None:
        return None
    return [SunTrigger(event=node["event"], offset=offset)]


def _state_values(value: Any) -> tuple[bool, str | None]:
    """(understood, value) for a state trigger's `to` or `from`."""
    if value is None:
        return True, None
    values = _as_list(value)
    if len(values) == 1 and isinstance(values[0], str | bool):
        single = values[0]
        if isinstance(single, bool):
            return True, "on" if single else "off"
        return True, single
    return False, None


def _state_triggers(node: Mapping[str, Any], device: DeviceContext) -> list[Trigger] | None:
    if not _only(node, {"entity_id", "to", "from", "for", "not_to", "not_from"}):
        return None
    for key in ("not_to", "not_from"):
        if key in node and not set(_as_list(node[key])) <= _IGNORED_UNAVAILABLE:
            return None
    to_ok, to = _state_values(node.get("to"))
    from_ok, from_state = _state_values(node.get("from"))
    duration = None
    if "for" in node:
        duration = parse_duration(node["for"])
        if duration is None:
            return None
    entities = [_resolve(entity, device) for entity in _as_list(node.get("entity_id"))]
    if not (to_ok and from_ok) or not entities or None in entities:
        return None
    return [
        StateTrigger(entity=entity, to=to, from_state=from_state, duration=duration)
        for entity in entities
        if entity is not None
    ]


def _numeric_triggers(node: Mapping[str, Any], device: DeviceContext) -> list[Trigger] | None:
    if not _only(node, {"entity_id", "above", "below", "for"}):
        return None
    above, below = _number(node.get("above")), _number(node.get("below"))
    if (above is None) != ("above" not in node) or (below is None) != ("below" not in node):
        return None
    if above is None and below is None:
        return None
    duration = None
    if "for" in node:
        duration = parse_duration(node["for"])
        if duration is None:
            return None
    entities = [_resolve(entity, device) for entity in _as_list(node.get("entity_id"))]
    if not entities or None in entities:
        return None
    return [
        NumericTrigger(entity=entity, above=above, below=below, duration=duration)
        for entity in entities
        if entity is not None
    ]


def _start_trigger(node: Mapping[str, Any]) -> list[Trigger] | None:
    if not _only(node, {"event"}) or node.get("event") not in grammar.START_EVENTS:
        return None
    return [StartTrigger(event=node["event"])]


def _calendar_trigger(node: Mapping[str, Any]) -> list[Trigger] | None:
    if not _only(node, {"entity_id", "event", "offset"}):
        return None
    offset = parse_duration(node.get("offset", 0))
    if (
        node.get("event") not in grammar.CALENDAR_EVENTS
        or not _is_entity_id(node.get("entity_id"))
        or offset is None
    ):
        return None
    return [CalendarTrigger(entity=node["entity_id"], event=node["event"], offset=offset)]


def _device_trigger(node: Mapping[str, Any], device: DeviceContext) -> list[Trigger] | None:
    if not _only(node, {"device_id", "domain", "type", "entity_id", "for", "metadata"}):
        return None
    states = grammar.DEVICE_TRIGGER_STATES.get(str(node.get("type")))
    entity = _resolve(node.get("entity_id"), device)
    if states is None or entity is None:
        return None
    duration = None
    if "for" in node:
        duration = parse_duration(node["for"])
        if duration is None:
            return None
    return [StateTrigger(entity=entity, to=states[0], from_state=states[1], duration=duration)]


def _named_options(options: Any) -> bool:
    """Tell whether a purpose specific trigger's options leave its phrase true."""
    if options is None:
        return True
    if not isinstance(options, Mapping) or set(options) - {"behavior"}:
        return False
    return options.get("behavior", "each") in grammar.NAMED_TRIGGER_BEHAVIORS


def _named_trigger(
    kind: str, node: Mapping[str, Any], device: DeviceContext
) -> list[Trigger] | None:
    if not _only(node, {"target", "options"}) or not _named_options(node.get("options")):
        return None
    target = node.get("target") or {}
    if not isinstance(target, Mapping) or set(target) - {"entity_id"}:
        return None
    entities = [_resolve(entity, device) for entity in _as_list(target.get("entity_id"))]
    domain = kind.partition(".")[0]
    resolved = tuple(entity for entity in entities if entity is not None)
    if len(resolved) != len(entities) or any(
        entity.partition(".")[0] != domain for entity in resolved
    ):
        return None
    return [NamedTrigger(name=kind, entities=resolved)]


def parse_trigger(node: Any, device: DeviceContext) -> list[Trigger] | None:
    """Return what one trigger means, or None when it is outside the grammar."""
    if not isinstance(node, Mapping) or _templated(node):
        return None
    kind = str(node.get("trigger", node.get("platform", "")))
    if kind in grammar.NAMED_TRIGGERS:
        return _named_trigger(kind, node, device)
    simple = {
        "time": _time_triggers,
        "time_pattern": _pattern_trigger,
        "sun": _sun_trigger,
        "homeassistant": _start_trigger,
        "calendar": _calendar_trigger,
    }
    if kind in simple:
        return simple[kind](node)
    with_device = {
        "state": _state_triggers,
        "numeric_state": _numeric_triggers,
        "device": _device_trigger,
    }
    if kind in with_device:
        return with_device[kind](node, device)
    return None


@dataclass(frozen=True, slots=True)
class _TriggerEntry:
    trigger_id: str
    parsed: tuple[Trigger, ...] | None


def _triggers(config: Mapping[str, Any], device: DeviceContext) -> list[_TriggerEntry]:
    entries: list[_TriggerEntry] = []
    for index, node in enumerate(_as_list(config.get("triggers", config.get("trigger")))):
        if isinstance(node, Mapping) and node.get("enabled") is False:
            continue
        trigger_id = str(node.get("id", index)) if isinstance(node, Mapping) else str(index)
        parsed = parse_trigger(node, device)
        entries.append(_TriggerEntry(trigger_id, None if parsed is None else tuple(parsed)))
    return entries


# --------------------------------------------------------------------------------------
# Conditions
# --------------------------------------------------------------------------------------


def _condition_kind(node: Mapping[str, Any]) -> str | None:
    if "condition" in node:
        return str(node["condition"])
    shorthand = [key for key in grammar.LOGICAL_CONDITIONS if key in node]
    return shorthand[0] if len(shorthand) == 1 else None


def _children(node: Mapping[str, Any], kind: str) -> list[Any]:
    return _as_list(node.get("conditions", node.get(kind)))


def _understood_condition(node: Any) -> bool:
    """Tell whether a condition, nested or not, uses only the grammar."""
    if not isinstance(node, Mapping) or _templated(node):
        return False
    kind = _condition_kind(node)
    if kind in grammar.LOGICAL_CONDITIONS:
        children = [child for child in _children(node, kind) if _active(child)]
        return bool(children) and all(_understood_condition(child) for child in children)
    checks: dict[str | None, bool] = {
        None: False,
        "time": kind == "time" and _time_condition(node) is not None,
        "device": node.get("type") in grammar.DEVICE_CONDITION_TYPES,
        "trigger": True,
    }
    if kind in checks:
        return checks[kind]
    assert kind is not None  # noqa: S101  # None is in checks
    return kind in grammar.COUNTED_CONDITIONS or grammar.NAMED_CONDITION.match(kind) is not None


def _active(node: Any) -> bool:
    return not (isinstance(node, Mapping) and node.get("enabled") is False)


def _bound(value: Any) -> time | str | None:
    if (fixed := parse_time(value)) is not None:
        return fixed
    return value if _is_entity_id(value) else None


def _time_condition(
    node: Mapping[str, Any],
) -> tuple[frozenset[Weekday] | None, TimeWindow | None] | None:
    if set(node) - {"condition", "alias", "enabled", "weekday", "after", "before"}:
        return None
    weekdays = None
    if "weekday" in node:
        weekdays = _weekdays(node["weekday"])
        if weekdays is None:
            return None
    window = None
    if "after" in node or "before" in node:
        after = _bound(node.get("after")) if "after" in node else None
        before = _bound(node.get("before")) if "before" in node else None
        if ("after" in node and after is None) or ("before" in node and before is None):
            return None
        window = TimeWindow(after=after, before=before)
    return weekdays, window


@dataclass(frozen=True, slots=True)
class _Path:
    """What must hold for a step to run: trigger ids, days, windows and other conditions."""

    trigger_ids: frozenset[str] | None = None
    weekdays: frozenset[Weekday] | None = None
    windows: tuple[TimeWindow, ...] = ()
    count: int = 0
    custom: bool = False

    def opaque(self) -> _Path:
        return replace(self, custom=True)

    def restrict(self, ids: Iterable[str]) -> _Path:
        wanted = frozenset(ids)
        merged = wanted if self.trigger_ids is None else self.trigger_ids & wanted
        return replace(self, trigger_ids=merged)

    def exclude(self, ids: Iterable[str], every: Iterable[str]) -> _Path:
        base = frozenset(every) if self.trigger_ids is None else self.trigger_ids
        return replace(self, trigger_ids=base - frozenset(ids))

    def condition(self, node: Any) -> _Path:
        """Return this path with one more condition."""
        if not _active(node):
            return self
        if not _understood_condition(node):
            return self.opaque()
        assert isinstance(node, Mapping)  # noqa: S101  # _understood_condition checked it
        kind = _condition_kind(node)
        if kind == "time":
            parsed = _time_condition(node)
            assert parsed is not None  # noqa: S101
            weekdays, window = parsed
            path = self
            if weekdays is not None:
                merged = weekdays if self.weekdays is None else self.weekdays & weekdays
                path = replace(path, weekdays=merged)
            if window is not None:
                path = replace(path, windows=(*path.windows, window))
            return path
        if kind == "trigger":
            ids = [str(item) for item in _as_list(node.get("id"))]
            return self.restrict(ids)
        if kind in grammar.LOGICAL_CONDITIONS and _mentions_trigger(node):
            # A trigger condition inside and, or or not: the ids it selects depend on the
            # other branches, which the grammar does not reason about.
            return self.opaque()
        return replace(self, count=self.count + 1)

    def conditions(self, nodes: Iterable[Any]) -> _Path:
        path = self
        for node in nodes:
            path = path.condition(node)
        return path


def _mentions_trigger(node: Mapping[str, Any]) -> bool:
    kind = _condition_kind(node)
    if kind == "trigger":
        return True
    if kind in grammar.LOGICAL_CONDITIONS:
        return any(
            isinstance(child, Mapping) and _mentions_trigger(child)
            for child in _children(node, kind)
        )
    return False


def _trigger_only(nodes: Sequence[Any]) -> list[str] | None:
    """Return the trigger ids when every active condition is a trigger condition."""
    ids: list[str] = []
    active = [node for node in nodes if _active(node)]
    for node in active:
        if not (isinstance(node, Mapping) and node.get("condition") == "trigger"):
            return None
        ids.extend(str(item) for item in _as_list(node.get("id")))
    return ids if active else None


# --------------------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Builder:
    path: _Path
    entity_ids: tuple[str, ...]
    verb: Verb | None
    follow_ups: list[FollowUp] = field(default_factory=list)


@dataclass(slots=True)
class _Walk:
    """The state of one walk through an automation's actions."""

    device: DeviceContext
    every_trigger: tuple[str, ...]
    lines: list[_Builder] = field(default_factory=list)


def _target_values(step: Mapping[str, Any], key: str) -> set[str]:
    found: set[str] = set()
    for holder in (step, step.get("target"), step.get("data")):
        if isinstance(holder, Mapping):
            found.update(
                value
                for value in _as_list(holder.get(key))
                if isinstance(value, str) and not _templated(value)
            )
    return found


def _matched(step: Mapping[str, Any], domain: str, device: DeviceContext) -> tuple[str, ...]:
    """Return the device entities an action targets, directly or by device, area or label."""
    entities = {_resolve(value, device) or value for value in _target_values(step, "entity_id")}
    devices = _target_values(step, "device_id")
    areas = _target_values(step, "area_id")
    floors = _target_values(step, "floor_id")
    labels = _target_values(step, "label_id")
    matched = [
        entity.entity_id
        for entity in device.entities
        if domain in {"homeassistant", entity.domain}
        and (
            entity.entity_id in entities
            or (domain != "homeassistant" and "all" in entities)
            or device.device_id in devices
            or (entity.area_id is not None and entity.area_id in areas)
            or (entity.floor_id is not None and entity.floor_id in floors)
            or bool(entity.labels & labels)
        )
    ]
    return tuple(matched)


def _service_step(
    step: Mapping[str, Any], device: DeviceContext
) -> tuple[tuple[str, ...], Verb | None]:
    action = step.get("action", step.get("service"))
    if not isinstance(action, str) or _templated(action) or "." not in action:
        return (), None
    domain, service = action.split(".", 1)
    matched = _matched(step, domain, device)
    if not matched:
        return (), None
    if service not in grammar.DOMAIN_SERVICES.get(domain, frozenset()):
        return matched, None
    return matched, grammar.ACTION_VERBS[service]


def _device_step(
    step: Mapping[str, Any], device: DeviceContext
) -> tuple[tuple[str, ...], Verb | None]:
    domain = str(step.get("domain", ""))
    if "entity_id" in step:
        entity = _resolve(step["entity_id"], device)
        matched = tuple(e for e in device.entity_ids if e == entity)
    elif step.get("device_id") == device.device_id:
        matched = tuple(e.entity_id for e in device.entities if e.domain == domain)
    else:
        matched = ()
    return matched, grammar.DEVICE_ACTION_VERBS.get(str(step.get("type")))


def _is_device_step(step: Mapping[str, Any]) -> bool:
    return "device_id" in step and "domain" in step and "type" in step and "action" not in step


def _structural(step: Mapping[str, Any], path: _Path, state: _Walk) -> bool:
    """Walk a step that holds other steps; tell whether the step was one."""
    if "choose" in step:
        _choose(step, path, state)
    elif "if" in step:
        _if(step, path, state)
    elif "parallel" in step:
        for branch in _as_list(step["parallel"]):
            nested = branch.get("sequence", branch) if isinstance(branch, Mapping) else branch
            _walk(nested, path, state)
    elif "sequence" in step:
        _walk(step["sequence"], path, state)
    elif "repeat" in step:
        repeat = step["repeat"]
        _walk(repeat.get("sequence") if isinstance(repeat, Mapping) else None, path.opaque(), state)
    else:
        return False
    return True


def _acted_on(
    step: Mapping[str, Any], device: DeviceContext
) -> tuple[tuple[str, ...], Verb | None] | None:
    """Return the entities and verb of an action step; None when it is not one."""
    if _is_device_step(step):
        return _device_step(step, device)
    if "action" in step or "service" in step:
        return _service_step(step, device)
    return None


@dataclass(slots=True)
class _Cursor:
    """Where a walk through one sequence stands."""

    path: _Path
    current: _Builder | None = None
    since: timedelta | None = None

    def opaque(self) -> None:
        self.path, self.current = self.path.opaque(), None

    def delay(self, value: Any) -> None:
        delay = parse_duration(value)
        if delay is not None and self.current is not None:
            self.since = (self.since or timedelta(0)) + delay
            return
        # A templated delay, or one before the first device action, shifts a time the
        # line cannot show: say there is more to it.
        self.path = self.path.opaque()
        if delay is None:
            self.current = None

    def emit(self, matched: tuple[str, ...], verb: Verb | None, state: _Walk) -> None:
        current = self.current
        if (
            current is not None
            and self.since is not None
            and verb is not None
            and current.entity_ids == matched
        ):
            current.follow_ups.append(FollowUp(delay=self.since, verb=verb))
        else:
            self.current = _Builder(path=self.path, entity_ids=matched, verb=verb)
            state.lines.append(self.current)
        self.since = None


def _step(step: Mapping[str, Any], cursor: _Cursor, state: _Walk) -> None:
    """Apply one step that is neither disabled nor a stop."""
    if "delay" in step:
        cursor.delay(step["delay"])
    elif "condition" in step and "action" not in step:
        cursor.path, cursor.current = cursor.path.condition(step), None
    elif _structural(step, cursor.path, state):
        if "repeat" in step:
            cursor.path = cursor.path.opaque()
        cursor.current = None
    elif (
        any(key in step for key in grammar.OPAQUE_STEPS)
        or (acted := _acted_on(step, state.device)) is None
    ):
        cursor.opaque()
    elif acted[0]:
        cursor.emit(acted[0], acted[1], state)


def _walk(steps: Any, path: _Path, state: _Walk) -> None:
    """Walk one sequence; emit a builder for every action on the device."""
    cursor = _Cursor(path)
    for step in _as_list(steps):
        if not isinstance(step, Mapping):
            cursor.opaque()
        elif step.get("enabled") is False:
            continue
        elif "stop" in step:
            return
        else:
            _step(step, cursor, state)


def _option_conditions(option: Mapping[str, Any]) -> list[Any]:
    return _as_list(option.get("conditions", option.get("condition")))


def _choose(step: Mapping[str, Any], path: _Path, state: _Walk) -> None:
    options = [option for option in _as_list(step["choose"]) if isinstance(option, Mapping)]
    claimed: list[str] = []
    only_triggers = True
    for option in options:
        if option.get("enabled") is False:
            continue
        conditions = _option_conditions(option)
        _walk(option.get("sequence"), path.conditions(conditions), state)
        ids = _trigger_only(conditions)
        if ids is None:
            only_triggers = False
        else:
            claimed.extend(ids)
    if "default" in step:
        default = path.exclude(claimed, state.every_trigger) if only_triggers else path.opaque()
        _walk(step["default"], default, state)


def _if(step: Mapping[str, Any], path: _Path, state: _Walk) -> None:
    conditions = _as_list(step["if"])
    _walk(step.get("then"), path.conditions(conditions), state)
    if "else" not in step:
        return
    ids = _trigger_only(conditions)
    if ids is not None:
        otherwise = path.exclude(ids, state.every_trigger)
    elif not any(isinstance(c, Mapping) and _mentions_trigger(c) for c in conditions) and all(
        _understood_condition(c) for c in conditions
    ):
        # The else branch runs when the conditions fail: one more condition to pass.
        otherwise = replace(path, count=path.count + 1)
    else:
        otherwise = path.opaque()
    _walk(step["else"], otherwise, state)


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def _line(
    builder: _Builder,
    triggers: Sequence[_TriggerEntry],
    automation_id: str,
    alias: str,
) -> ParsedLine:
    path = builder.path
    selected = [
        entry
        for entry in triggers
        if path.trigger_ids is None or entry.trigger_id in path.trigger_ids
    ]
    understood = [trigger for entry in selected if entry.parsed for trigger in entry.parsed]
    custom = path.custom or any(entry.parsed is None for entry in selected)
    if builder.verb is None or not understood:
        return ParsedLine(
            automation_id=automation_id,
            alias=alias,
            entity_ids=builder.entity_ids,
            verb=builder.verb,
            custom_logic=True,
            understood=False,
        )
    return ParsedLine(
        automation_id=automation_id,
        alias=alias,
        entity_ids=builder.entity_ids,
        verb=builder.verb,
        triggers=tuple(understood),
        weekdays=path.weekdays,
        windows=path.windows,
        condition_count=path.count,
        follow_ups=tuple(builder.follow_ups),
        custom_logic=custom,
    )


def summarize(config: Any, device: DeviceContext) -> list[ParsedLine]:
    """One line per action of an automation that acts on the device."""
    if not isinstance(config, Mapping) or not ("actions" in config or "action" in config):
        raise ParseError("not_an_automation")
    automation_id = str(config.get("id", ""))
    alias = str(config.get("alias") or automation_id)
    triggers = _triggers(config, device)
    state = _Walk(device=device, every_trigger=tuple(entry.trigger_id for entry in triggers))
    path = _Path().conditions(_as_list(config.get("conditions", config.get("condition"))))
    _walk(config.get("actions", config.get("action")), path, state)
    return [_line(builder, triggers, automation_id, alias) for builder in state.lines]
