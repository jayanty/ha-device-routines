"""The grammar of the schedule summary, as data (TECH_SPEC 3.5, PRD FR-S2).

Every construct the parser reads is listed here and has a test. Anything not listed is
outside the grammar and makes a line say "plus custom logic", or, when nothing about an
action was understood, the single custom logic line. Adding a row here is how the parser
learns something new; there are no heuristics anywhere else.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Final

from .models import Verb

# Action services and the verb each one means, per domain. `homeassistant.*` acts on any
# domain and is matched against every entity of the device.
ACTION_VERBS: Final[Mapping[str, Verb]] = {
    "turn_on": Verb.ON,
    "turn_off": Verb.OFF,
    "toggle": Verb.TOGGLE,
    "start": Verb.START,
    "start_mowing": Verb.START,
    "return_to_base": Verb.DOCK,
    "dock": Verb.DOCK,
    "pause": Verb.PAUSE,
    "stop": Verb.STOP,
    "open_cover": Verb.OPEN,
    "close_cover": Verb.CLOSE,
    "open_valve": Verb.OPEN,
    "close_valve": Verb.CLOSE,
    "lock": Verb.LOCK,
    "unlock": Verb.UNLOCK,
}

# Which services each domain really has, so `light.start` is never read as a verb.
DOMAIN_SERVICES: Final[Mapping[str, frozenset[str]]] = {
    "switch": frozenset({"turn_on", "turn_off", "toggle"}),
    "light": frozenset({"turn_on", "turn_off", "toggle"}),
    "fan": frozenset({"turn_on", "turn_off", "toggle"}),
    "input_boolean": frozenset({"turn_on", "turn_off", "toggle"}),
    "humidifier": frozenset({"turn_on", "turn_off", "toggle"}),
    "climate": frozenset({"turn_on", "turn_off", "toggle"}),
    "media_player": frozenset({"turn_on", "turn_off", "toggle"}),
    "siren": frozenset({"turn_on", "turn_off", "toggle"}),
    "remote": frozenset({"turn_on", "turn_off", "toggle"}),
    "water_heater": frozenset({"turn_on", "turn_off"}),
    "vacuum": frozenset({"start", "return_to_base", "pause", "stop"}),
    "lawn_mower": frozenset({"start_mowing", "dock", "pause"}),
    "cover": frozenset({"open_cover", "close_cover", "toggle", "stop"}),
    "valve": frozenset({"open_valve", "close_valve", "toggle"}),
    "lock": frozenset({"lock", "unlock"}),
    "homeassistant": frozenset({"turn_on", "turn_off", "toggle"}),
}

# Device actions (`device_id`, `domain`, `type`) and their verbs.
DEVICE_ACTION_VERBS: Final[Mapping[str, Verb]] = {
    "turn_on": Verb.ON,
    "turn_off": Verb.OFF,
    "toggle": Verb.TOGGLE,
    "clean": Verb.START,
    "dock": Verb.DOCK,
    "open": Verb.OPEN,
    "close": Verb.CLOSE,
    "lock": Verb.LOCK,
    "unlock": Verb.UNLOCK,
}

# Device triggers that mean a state change, as (to, from) pairs.
DEVICE_TRIGGER_STATES: Final[Mapping[str, tuple[str | None, str | None]]] = {
    "turned_on": ("on", None),
    "turned_off": ("off", None),
    "changed_states": (None, None),
    "opened": ("open", None),
    "closed": ("closed", None),
    "locked": ("locked", None),
    "unlocked": ("unlocked", None),
    "docked": ("docked", None),
    "cleaning": ("cleaning", None),
}

# Device conditions that mean a state condition.
DEVICE_CONDITION_TYPES: Final[frozenset[str]] = frozenset(
    {"is_on", "is_off", "is_open", "is_closed", "is_locked", "is_unlocked", "is_docked"}
)

# Purpose specific triggers the grammar reads, each with its phrase key. A trigger reads
# only for targets of its own domain (the part before the dot): the core ignores others.
NAMED_TRIGGERS: Final[Mapping[str, str]] = {
    "schedule.block_started": "when_block_started",
    "schedule.block_ended": "when_block_ended",
    "timer.started": "when_timer_started",
    "timer.finished": "when_timer_finished",
    "timer.cancelled": "when_timer_cancelled",
    "vacuum.started_cleaning": "when_vacuum_started",
    "vacuum.returned_to_dock": "when_vacuum_docked",
    "vacuum.errored": "when_vacuum_errored",
}

# The `behavior` option of a purpose specific trigger that the phrase states: any one
# target is enough (`any` is the legacy name of `each`). `first` and `all` wait for the
# first or the last of several targets, and a `for` option for a held duration: neither is
# what the line says, so both are outside the grammar.
NAMED_TRIGGER_BEHAVIORS: Final[frozenset[str]] = frozenset({"each", "any"})

# Purpose specific conditions: `<domain>.is_<something>`, the shape core 2026.10 uses.
NAMED_CONDITION: Final = re.compile(r"^[a-z_]+\.is_[a-z_]+$")

# Plain condition kinds the grammar reads (time is handled on its own: weekdays and
# windows are folded into the line instead of being counted).
COUNTED_CONDITIONS: Final[frozenset[str]] = frozenset({"state", "numeric_state", "sun"})
LOGICAL_CONDITIONS: Final[frozenset[str]] = frozenset({"and", "or", "not"})

# `homeassistant` trigger events.
START_EVENTS: Final[frozenset[str]] = frozenset({"start", "shutdown"})

# Sun trigger events.
SUN_EVENTS: Final[frozenset[str]] = frozenset({"sunrise", "sunset"})

# Calendar trigger events.
CALENDAR_EVENTS: Final[frozenset[str]] = frozenset({"start", "end"})

# Action keys that are never understood on the way to a device action: they make a line
# say "plus custom logic" when they come before it in the same sequence.
OPAQUE_STEPS: Final[frozenset[str]] = frozenset(
    {
        "repeat",
        "wait_template",
        "wait_for_trigger",
        "variables",
        "event",
        "set_conversation_response",
    }
)

# A time pattern field: `*`, a number, or `/N`.
PATTERN_FIELD: Final = re.compile(r"^(\*|\d{1,2}|/\d{1,2})$")
