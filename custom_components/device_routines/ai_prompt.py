"""The fixed prompt of the optional AI summary (PRD FR-S5, TECH_SPEC 4.4).

What leaves the integration, exactly: for one automation whose schedule the parser
cannot fully read, its trigger, condition and action blocks as written (templates
included), with every entity named by its entity id. `blocks` takes out everything else
that could describe the home: aliases and descriptions at any depth, the editor's
`metadata`, and device, area, floor and label ids, which become numbered placeholders
(`device_1`, `area_1`, ...); an entity named by its registry id is named by its entity id
instead. No states, attributes or names are added. The summary sends the result to the
AI Task entity the person chose, through the core's `ai_task.generate_data` action, and
nowhere else. The options flow says the same in the `ai_task_entity` description.

Pure: the standard library only, so the prompt is a function of the blocks alone.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any, Final

# The name the AI Task sees for the job.
TASK_NAME: Final = "Device Routines schedule line"
# Answers longer than this are cut (FR-S5).
MAX_WORDS: Final = 12

PROMPT: Final = (
    "Describe one Home Assistant automation for a device's schedule overview. Its "
    "triggers, conditions and actions follow as JSON; entities appear by entity id only, "
    "and device_1, area_1 and the like stand for devices, areas, floors and labels. "
    f"Answer with one plain sentence of at most {MAX_WORDS} words that says when it acts "
    "and what it does. No quotes, no markdown, no entity ids."
)

# The blocks sent, each under its plural key; a config may use the singular one.
BLOCKS: Final = (("triggers", "trigger"), ("conditions", "condition"), ("actions", "action"))
# Keys that name or describe things in the home and say nothing about when or what.
_DROPPED: Final = frozenset({"alias", "description", "metadata"})
# Keys whose values are ids of registry objects, replaced by numbered placeholders.
_PLACEHOLDERS: Final[Mapping[str, str]] = {
    "device_id": "device",
    "area_id": "area",
    "floor_id": "floor",
    "label_id": "label",
}
_REGISTRY_ID: Final = re.compile(r"^[0-9a-f]{32}$")
# What an entity registry id that no longer resolves becomes.
UNKNOWN_ENTITY: Final = "unknown_entity"
_QUOTES: Final = "\"'`*"


def blocks(config: Mapping[str, Any], entity_ids: Mapping[str, str]) -> dict[str, list[Any]]:
    """Return the trigger, condition and action blocks of a config, as the AI sees them.

    `entity_ids` maps entity registry ids to entity ids (device triggers and the editor
    name entities by registry id). Every block is a list, missing ones empty.
    """
    numbered: dict[tuple[str, str], str] = {}

    def placeholder(kind: str, value: str) -> str:
        key = (kind, value)
        if key not in numbered:
            count = sum(1 for known in numbered if known[0] == kind)
            numbered[key] = f"{kind}_{count + 1}"
        return numbered[key]

    def scrub(value: Any, key: str | None = None) -> Any:
        if isinstance(value, Mapping):
            return {
                str(inner): scrub(item, str(inner))
                for inner, item in value.items()
                if inner not in _DROPPED
            }
        if isinstance(value, list | tuple):
            return [scrub(item, key) for item in value]
        if isinstance(value, str) and (kind := _PLACEHOLDERS.get(key or "")) is not None:
            return placeholder(kind, value)
        if isinstance(value, str) and key == "entity_id" and _REGISTRY_ID.match(value):
            return entity_ids.get(value, UNKNOWN_ENTITY)
        return value

    found: dict[str, list[Any]] = {}
    for plural, singular in BLOCKS:
        raw = config.get(plural, config.get(singular))
        listed = [] if raw is None else raw if isinstance(raw, list) else [raw]
        found[plural] = scrub(listed)
    return found


def instructions(found: Mapping[str, Any]) -> str:
    """Return the instructions for one automation: the fixed prompt, then its blocks."""
    return f"{PROMPT}\n\n{json.dumps(found, ensure_ascii=False, default=str)}"


def trim(answer: Any) -> str | None:
    """Return an answer as one line of at most `MAX_WORDS` words; None for no text.

    Surrounding quotes and markdown emphasis, line breaks and a closing full stop go,
    so the line reads like the parser's own lines.
    """
    if not isinstance(answer, str):
        return None
    words = " ".join(answer.split()).strip(_QUOTES).split()[:MAX_WORDS]
    text = " ".join(words).strip(_QUOTES).rstrip(".!").strip()
    return text or None
