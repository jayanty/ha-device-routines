"""Exact conversion matches: hand written automations a routine can replace (PRD FR-M1).

`match(config, device)` returns the routine settings whose behavior is exactly the
automation's, or None. Exact means the routine does what the automation does and nothing
the automation does is lost, so the whole config is read, not only the parser's lines,
which leave out every action that is not on the device (decision L61). Two shapes match:

- FR-R1, scheduled times: exactly two enabled `time` triggers at fixed whole minute times
  (no entity, no offset), at different times; exactly one on action and one off action on
  one entity of the device, each run by exactly one of the two triggers through a `choose`
  option or an `if` on a `trigger` condition naming its id, and carrying nothing beyond
  the target; no condition, or only weekdays (a `time` condition with `weekday` alone, or
  the same `weekday` on both triggers). A window across midnight matches only every day:
  a routine ends it the day after each start day (FR-R1), the automation on its weekdays.
- FR-R3, Turn off after: exactly one enabled `state` trigger on one entity of the device,
  `to: "on"`, `from` absent or `"off"`, `for` a whole number of minutes from 1 to 1440;
  exactly one off action on that entity; no condition. Only for the domains whose state
  is on or off, where `to: "on"` is every turn on, as the routine's countdown reads it.

Everything else is None: a template, variables, a second entity or device, any other
action (a delay, a notification, a scene, a toggle), a disabled trigger, condition or
action, an action carrying data (a brightness), seconds, an entity held time, any other
condition. The settings carry the entity, the times or the duration and the days (a named
day set as its name, else Some days); every other field is the `RoutineSettings` default.
The caller validates the match against the device's profile, which applies the PRD 5.4
refusals. `match` never raises, whatever it is given.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time, timedelta
import re
from typing import Any, Final

from . import parser
from .domains import PROFILES
from .models import (
    ALL_DAYS,
    WEEKDAYS,
    WEEKEND,
    Days,
    DeviceContext,
    RoutineSettings,
    Weekday,
)

# The automation keys that do not change what it does; anything else (variables, a
# blueprint) is not an exact match.
_CONFIG_KEYS: Final = frozenset(
    {
        "id",
        "alias",
        "description",
        "mode",
        "max",
        "max_exceeded",
        "trace",
        "initial_state",
        "triggers",
        "trigger",
        "conditions",
        "condition",
        "actions",
        "action",
    }
)
_TIME_TRIGGER_KEYS: Final = frozenset(
    {"trigger", "platform", "id", "alias", "enabled", "at", "weekday"}
)
_STATE_TRIGGER_KEYS: Final = frozenset(
    {"trigger", "platform", "id", "alias", "enabled", "entity_id", "to", "from", "for"}
)
_WEEKDAY_CONDITION_KEYS: Final = frozenset({"condition", "alias", "enabled", "weekday"})
_TRIGGER_CONDITION_KEYS: Final = frozenset({"condition", "alias", "enabled", "id"})
_CHOOSE_KEYS: Final = frozenset({"choose", "alias", "enabled"})
_OPTION_KEYS: Final = frozenset({"conditions", "sequence", "alias"})
_IF_KEYS: Final = frozenset({"if", "then", "else", "alias", "enabled"})
_SERVICE_KEYS: Final = frozenset({"action", "service", "target", "alias", "enabled"})

# Domains whose state is only on or off, so `to: "on"` is every turn on (FR-R3).
_ON_OFF_DOMAINS: Final = frozenset({"switch", "light", "fan", "input_boolean", "humidifier"})
_WEEKDAY_VALUES: Final = frozenset(day.value for day in Weekday)
_NAMED_DAYS: Final[Mapping[frozenset[Weekday], Days]] = {
    ALL_DAYS: Days.EVERY_DAY,
    WEEKDAYS: Days.WEEKDAYS,
    WEEKEND: Days.WEEKENDS,
}
_REGISTRY_ID: Final = re.compile(r"[0-9a-f]{32}")
_MAX_MINUTES: Final = 1440

# A branch: the trigger ids that run it and the one step it runs.
type _Branch = tuple[frozenset[str], Any]


def match(config: Mapping[str, Any], device: DeviceContext) -> RoutineSettings | None:
    """Return the settings of the routine that does exactly what the automation does."""
    if not isinstance(config, Mapping) or not _only(config, _CONFIG_KEYS):
        return None
    triggers = _section(config, "triggers", "trigger")
    conditions = _section(config, "conditions", "condition")
    actions = _section(config, "actions", "action")
    if triggers is None or conditions is None or actions is None:
        return None
    if _templated([triggers, conditions, actions]):
        return None
    return _scheduled_times(triggers, conditions, actions, device) or _turn_off_after(
        triggers, conditions, actions, device
    )


# --------------------------------------------------------------------------------------
# FR-R1: two time triggers, one on and one off action
# --------------------------------------------------------------------------------------


def _scheduled_times(
    triggers: list[Any], conditions: list[Any], actions: list[Any], device: DeviceContext
) -> RoutineSettings | None:
    times = [_fixed_time(node, index) for index, node in enumerate(triggers)]
    if len(times) != 2 or None in times:  # noqa: PLR2004  # the shape's two triggers
        return None
    (first_id, first_at, first_days), (second_id, second_at, second_days) = (
        found for found in times if found is not None
    )
    if first_id == second_id or first_at == second_at or first_days != second_days:
        return None
    acted = _on_and_off(actions, frozenset({first_id, second_id}), device)
    days = _condition_days(conditions)
    if acted is None or days is None or (first_days is not None and days != ALL_DAYS):
        return None
    entity, on_id = acted
    on_at, off_at = (first_at, second_at) if on_id == first_id else (second_at, first_at)
    days = first_days or days
    if off_at < on_at and days != ALL_DAYS:
        return None
    named = _NAMED_DAYS.get(days)
    return RoutineSettings(
        target_entity=entity,
        on_time=on_at,
        off_time=off_at,
        days=named or Days.SOME_DAYS,
        day_set=ALL_DAYS if named else days,
    )


def _fixed_time(node: Any, index: int) -> tuple[str, time, frozenset[Weekday] | None] | None:
    """Return the id, time and weekdays of a time trigger at one whole minute time."""
    if not _trigger(node, "time", _TIME_TRIGGER_KEYS):
        return None
    trigger_id = _trigger_id(node, index)
    at = node.get("at")
    moment = parser.parse_time(at) if isinstance(at, str) else None
    if trigger_id is None or moment is None or moment.second:
        return None
    if "weekday" not in node:
        return trigger_id, moment, None
    days = _weekdays(node["weekday"])
    return None if days is None else (trigger_id, moment, days)


def _condition_days(conditions: list[Any]) -> frozenset[Weekday] | None:
    """Return the days the conditions allow: every day, or one `time` weekday condition's."""
    if not conditions:
        return ALL_DAYS
    if len(conditions) != 1 or not _condition(conditions[0], "time", _WEEKDAY_CONDITION_KEYS):
        return None
    return _weekdays(conditions[0].get("weekday"))


def _on_and_off(
    actions: list[Any], trigger_ids: frozenset[str], device: DeviceContext
) -> tuple[str, str] | None:
    """Return the entity and the on trigger's id when each trigger runs one of its actions."""
    branches = _branches(actions, trigger_ids)
    if branches is None or len(branches) != 2:  # noqa: PLR2004  # one branch per trigger
        return None
    selected = [ids for ids, _ in branches]
    if any(len(ids) != 1 for ids in selected) or frozenset().union(*selected) != trigger_ids:
        return None
    services = [_service(step, device) for _, step in branches]
    entities = {found[1] for found in services if found is not None}
    if None in services or len(entities) != 1:
        return None
    (entity,) = entities
    profile = PROFILES.get(entity.partition(".")[0])
    actions_run = [found[0] for found in services if found is not None]
    if profile is None or profile.on_action is None:
        return None
    if sorted(actions_run) != sorted([profile.on_action, profile.off_action]):
        return None
    return entity, next(iter(selected[actions_run.index(profile.on_action)]))


def _branches(actions: list[Any], trigger_ids: frozenset[str]) -> list[_Branch] | None:
    """Return what runs for which triggers: a `choose`, an `if` with `else`, or two `if`s."""
    if len(actions) == 1 and _plain(actions[0], _CHOOSE_KEYS) and "choose" in actions[0]:
        options = _as_list(actions[0]["choose"])
        found = [_option(option) for option in options]
        return None if None in found else [branch for branch in found if branch is not None]
    branches: list[_Branch] = []
    for step in actions:
        if not _plain(step, _IF_KEYS) or "if" not in step or "then" not in step:
            return None
        trigger_id = _trigger_condition(step["if"])
        then = _single(step["then"])
        if trigger_id is None or then is None:
            return None
        branches.append((frozenset({trigger_id}), then))
        if "else" in step:
            otherwise = _single(step["else"])
            if otherwise is None or len(actions) != 1:
                return None
            branches.append((trigger_ids - {trigger_id}, otherwise))
    return branches


def _option(option: Any) -> _Branch | None:
    """Return a `choose` option on one trigger condition with its one step."""
    if not isinstance(option, Mapping) or not _only(option, _OPTION_KEYS):
        return None
    trigger_id = _trigger_condition(option.get("conditions"))
    step = _single(option.get("sequence"))
    if trigger_id is None or step is None:
        return None
    return frozenset({trigger_id}), step


def _trigger_condition(value: Any) -> str | None:
    """Return the one trigger id that exactly one `trigger` condition names."""
    conditions = _as_list(value)
    if len(conditions) != 1 or not _condition(conditions[0], "trigger", _TRIGGER_CONDITION_KEYS):
        return None
    ids = _as_list(conditions[0].get("id"))
    if not ids or not all(isinstance(item, str) for item in ids) or len(set(ids)) != 1:
        return None
    named: str = ids[0]
    return named


# --------------------------------------------------------------------------------------
# FR-R3: one state trigger with `for`, one off action
# --------------------------------------------------------------------------------------


def _turn_off_after(
    triggers: list[Any], conditions: list[Any], actions: list[Any], device: DeviceContext
) -> RoutineSettings | None:
    if len(triggers) != 1 or conditions or len(actions) != 1:
        return None
    node = triggers[0]
    if not _trigger(node, "state", _STATE_TRIGGER_KEYS) or _trigger_id(node, 0) is None:
        return None
    entity = _entity(node.get("entity_id"), device)
    if entity is None or (domain := entity.partition(".")[0]) not in _ON_OFF_DOMAINS:
        return None
    minutes = _whole_minutes(node.get("for"))
    if (
        node.get("to") != "on"
        or node.get("from", "off") != "off"
        or minutes is None
        or not 1 <= minutes <= _MAX_MINUTES
        or _service(actions[0], device) != (PROFILES[domain].off_action, entity)
    ):
        return None
    return RoutineSettings(target_entity=entity, turn_off_after_min=minutes)


def _whole_minutes(value: Any) -> int | None:
    """Return a `for` period as whole minutes; None for seconds or anything unreadable."""
    try:
        period = parser.parse_duration(value)
    except OverflowError, ValueError:  # an infinite or huge number of seconds
        return None
    if period is None or period % timedelta(minutes=1):
        return None
    return period // timedelta(minutes=1)


# --------------------------------------------------------------------------------------
# Shared reading
# --------------------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    return [value]


def _only(node: Mapping[Any, Any], allowed: frozenset[str]) -> bool:
    return set(node) <= allowed


def _section(config: Mapping[str, Any], plural: str, singular: str) -> list[Any] | None:
    """Return an automation section by either of its names; None when both are given."""
    if plural in config and singular in config:
        return None
    return _as_list(config.get(plural, config.get(singular)))


def _plain(node: Any, allowed: frozenset[str]) -> bool:
    """Tell whether a node is an enabled mapping with only the allowed keys."""
    return isinstance(node, Mapping) and _only(node, allowed) and node.get("enabled", True) is True


def _trigger(node: Any, kind: str, allowed: frozenset[str]) -> bool:
    """Tell whether a node is a plain trigger of that kind, by `trigger` or legacy `platform`."""
    if not _plain(node, allowed) or ("trigger" in node and "platform" in node):
        return False
    return bool(node.get("trigger", node.get("platform")) == kind)


def _condition(node: Any, kind: str, allowed: frozenset[str]) -> bool:
    """Tell whether a node is a plain condition of that kind."""
    return _plain(node, allowed) and node.get("condition") == kind


def _trigger_id(node: Mapping[str, Any], index: int) -> str | None:
    """Return a trigger's id: its own text, or its position as the core names it."""
    trigger_id = node.get("id", str(index))
    return trigger_id if isinstance(trigger_id, str) else None


def _single(value: Any) -> Any:
    """Return the one step of a sequence; None for none or several."""
    steps = _as_list(value)
    return steps[0] if len(steps) == 1 else None


def _service(step: Any, device: DeviceContext) -> tuple[str, str] | None:
    """Return the action and the one device entity of a step that carries only a target."""
    if not _plain(step, _SERVICE_KEYS) or ("action" in step) == ("service" in step):
        return None
    action = step.get("action", step.get("service"))
    target = step.get("target")
    if (
        not isinstance(action, str)
        or not isinstance(target, Mapping)
        or set(target) != {"entity_id"}
    ):
        return None
    entity = _entity(target["entity_id"], device)
    return None if entity is None else (action, entity)


def _entity(value: Any, device: DeviceContext) -> str | None:
    """Return the one device entity a value names, by entity id or by registry id."""
    named = _as_list(value)
    if len(named) != 1 or not isinstance(named[0], str):
        return None
    entity: str | None = named[0]
    if entity is not None and _REGISTRY_ID.fullmatch(entity):
        entity = device.registry_ids.get(entity)
    return entity if entity in device.entity_ids else None


def _weekdays(value: Any) -> frozenset[Weekday] | None:
    days = _as_list(value)
    if not days or not all(isinstance(day, str) and day in _WEEKDAY_VALUES for day in days):
        return None
    return frozenset(Weekday(day) for day in days)


def _templated(value: Any) -> bool:
    """Tell whether a template appears anywhere in a value."""
    if isinstance(value, str):
        return "{{" in value or "{%" in value
    if isinstance(value, Mapping):
        return any(_templated(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_templated(item) for item in value)
    return False
