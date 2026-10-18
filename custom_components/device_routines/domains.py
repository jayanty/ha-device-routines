"""Domain profiles: what a routine can do with each supported domain (PRD 5.3, TECH_SPEC 3.2).

The refusals of PRD 5.4 live here as data: a profile for a refused device class has no
activating action, so neither the compiler nor the controls can offer one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from .models import DomainProfile, Option

_ALL = frozenset(Option)
_TIMES_DAYS = frozenset({Option.ON_TIME, Option.OFF_TIME, Option.DAYS})
_OFF_DAYS_AFTER = frozenset({Option.OFF_TIME, Option.DAYS, Option.TURN_OFF_AFTER})


def _toggle_profile(domain: str) -> DomainProfile:
    return DomainProfile(
        domain=domain,
        on_action=f"{domain}.turn_on",
        off_action=f"{domain}.turn_off",
        inactive_state="off",
        on_label_key="turn_on_at",
        off_label_key="turn_off_at",
        options=_ALL,
    )


PROFILES: Mapping[str, DomainProfile] = {
    **{
        domain: _toggle_profile(domain)
        for domain in ("switch", "light", "fan", "input_boolean", "humidifier")
    },
    "climate": replace(_toggle_profile("climate"), options=_TIMES_DAYS | {Option.TURN_OFF_AFTER}),
    "media_player": DomainProfile(
        domain="media_player",
        on_action=None,
        off_action="media_player.turn_off",
        inactive_state="off",
        on_label_key=None,
        off_label_key="turn_off_at",
        options=_OFF_DAYS_AFTER,
    ),
    "vacuum": DomainProfile(
        domain="vacuum",
        on_action="vacuum.start",
        off_action="vacuum.return_to_base",
        inactive_state="docked",
        on_label_key="start_at",
        off_label_key="return_to_dock_at",
        options=_TIMES_DAYS,
    ),
    "lawn_mower": DomainProfile(
        domain="lawn_mower",
        on_action="lawn_mower.start_mowing",
        off_action="lawn_mower.dock",
        inactive_state="docked",
        on_label_key="start_at",
        off_label_key="return_to_dock_at",
        options=_TIMES_DAYS,
    ),
    "cover": DomainProfile(
        domain="cover",
        on_action="cover.open_cover",
        off_action="cover.close_cover",
        inactive_state="closed",
        on_label_key="open_at",
        off_label_key="close_at",
        options=_TIMES_DAYS | {Option.TURN_OFF_AFTER},
        refused_device_classes=frozenset({"garage", "gate", "door"}),
    ),
    "lock": DomainProfile(
        domain="lock",
        on_action=None,
        off_action="lock.lock",
        inactive_state="locked",
        on_label_key=None,
        off_label_key="lock_at",
        options=_OFF_DAYS_AFTER,
    ),
    "valve": DomainProfile(
        domain="valve",
        on_action="valve.open_valve",
        off_action="valve.close_valve",
        inactive_state="closed",
        on_label_key="open_at",
        off_label_key="close_at",
        options=_TIMES_DAYS | {Option.TURN_OFF_AFTER},
        refused_device_classes=frozenset({"gas"}),
    ),
}

SUPPORTED_DOMAINS: frozenset[str] = frozenset(PROFILES)

# Options that need an activating action; a profile without one cannot offer them.
_NEEDS_ON_ACTION = frozenset({Option.ON_TIME, Option.TURN_BACK_ON_AFTER, Option.PULSE})


def profile_for(domain: str, device_class: str | None = None) -> DomainProfile | None:
    """Return the profile for an entity with the PRD 5.4 refusals applied, or None."""
    profile = PROFILES.get(domain)
    if profile is None:
        return None
    if device_class is not None and device_class in profile.refused_device_classes:
        return replace(
            profile,
            on_action=None,
            on_label_key=None,
            options=profile.options - _NEEDS_ON_ACTION,
        )
    return profile


def is_refused_action(action: str, device_class: str | None) -> bool:
    """Tell whether PRD 5.4 forbids a routine to schedule, delay or re-trigger an action."""
    domain, _, service = action.partition(".")
    if domain == "lock" and service in {"unlock", "open"}:
        return True
    if domain == "alarm_control_panel":
        return True
    profile = PROFILES.get(domain)
    if profile is None or profile.on_action != action:
        return False
    return device_class is not None and device_class in profile.refused_device_classes


@dataclass(frozen=True, slots=True)
class Candidate:
    """An entity of a device as `pick_targets` sees it."""

    entity_id: str
    entity_category: str | None = None
    disabled: bool = False


def pick_targets(entities: Iterable[Candidate]) -> list[str]:
    """Return the controllable entities: supported domain, no category, registry order."""
    return [
        entity.entity_id
        for entity in entities
        if entity.entity_category is None
        and not entity.disabled
        and entity.entity_id.split(".", 1)[0] in SUPPORTED_DOMAINS
    ]
