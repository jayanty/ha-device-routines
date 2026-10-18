"""The only module that touches Home Assistant internals (TECH_SPEC 4.2, PRD D2).

Each capability is one small function. `check` runs at setup and says which capabilities
work on the running core; a failed one disables what depends on it and raises the single
`adapter_incompatible` Repairs issue, while routines keep running. Phase 1 needs the read
capabilities only; the write, blueprint, helper and catch up capabilities follow in
Phase 2.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import logging
from typing import Any, Final

from homeassistant.components import automation
from homeassistant.components.automation import DATA_COMPONENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

CAPABILITY_READ: Final = "read_automations"

# Every reference helper discovery uses (Stage 0 V2 and A3).
_REFERENCE_HELPERS: Final = (
    "entities_in_automation",
    "devices_in_automation",
    "areas_in_automation",
    "floors_in_automation",
    "labels_in_automation",
    "automations_with_entity",
)

# The automation component fires this after a reload; the SummaryCoordinator listens.
EVENT_AUTOMATION_RELOADED: Final = automation.EVENT_AUTOMATION_RELOADED


@dataclass(frozen=True, slots=True)
class AdapterReport:
    """Which capabilities work on the running core."""

    failed: tuple[str, ...] = ()
    details: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Tell whether every capability works."""
        return not self.failed

    def works(self, capability: str) -> bool:
        """Tell whether one capability works."""
        return capability not in self.failed


@dataclass(frozen=True, slots=True)
class AutomationRefs:
    """One loaded automation: its config and every id it references, resolved."""

    entity_id: str
    config: Mapping[str, Any]
    entities: frozenset[str]
    devices: frozenset[str]
    areas: frozenset[str]
    floors: frozenset[str]
    labels: frozenset[str]


def check(hass: HomeAssistant) -> AdapterReport:
    """Return which capabilities this core offers."""
    missing = [name for name in _REFERENCE_HELPERS if not callable(getattr(automation, name, None))]
    details: dict[str, str] = {}
    if missing:
        details[CAPABILITY_READ] = "missing helpers: " + ", ".join(missing)
    return AdapterReport(failed=tuple(details), details=details)


def automation_config(hass: HomeAssistant, entity_id: str) -> Mapping[str, Any] | None:
    """Return the config a loaded automation entity was built from, UI and YAML alike.

    None for an automation entity without one: a restored, unavailable registry entry, or
    a YAML automation ignored for a duplicate id (TECH_SPEC 4.2).
    """
    component = hass.data.get(DATA_COMPONENT)
    if component is None:
        return None
    entity = component.get_entity(entity_id)
    config = getattr(entity, "raw_config", None)
    return config if isinstance(config, Mapping) else None


def _resolved(hass: HomeAssistant, references: list[str]) -> frozenset[str]:
    """Resolve registry id references to entity ids, dropping any that do not resolve."""
    registry = er.async_get(hass)
    resolved = set()
    for reference in references:
        entity_id = er.async_resolve_entity_id(registry, reference)
        if entity_id is not None:
            resolved.add(entity_id)
    return frozenset(resolved)


def automation_references(hass: HomeAssistant) -> list[AutomationRefs]:
    """Return every loaded automation with a config and the ids it references."""
    found: list[AutomationRefs] = []
    helper: Callable[[HomeAssistant, str], list[str]]
    for entity_id in sorted(hass.states.async_entity_ids("automation")):
        config = automation_config(hass, entity_id)
        if config is None:
            continue
        ids: dict[str, frozenset[str]] = {}
        for kind in ("devices", "areas", "floors", "labels"):
            helper = getattr(automation, f"{kind}_in_automation")
            ids[kind] = frozenset(helper(hass, entity_id))
        found.append(
            AutomationRefs(
                entity_id=entity_id,
                config=config,
                entities=_resolved(hass, automation.entities_in_automation(hass, entity_id)),
                **ids,
            )
        )
    return found
