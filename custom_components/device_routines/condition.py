"""Purpose specific conditions: a routine is paused, or active (PRD FR-R17).

`device_routines.is_paused` and `device_routines.is_active` in the core's integration
condition shape (Stage 0 V13): a `target` (device, area, label, floor or entity) that the
manager resolves to routine devices, and the `behavior` option any or all. They read the
manager's views and hold no rules (PRD P16):

- `is_paused`: the view's `is_paused`: `paused` or `skipping` (a skip is a pause until
  its paired end, D18 and D19).
- `is_active`: the view's `is_active`: on, valid, attached, its target present, and
  neither paused nor skipping. A routine that is off is neither paused nor active.
- `all` asks it of every routine the target names, `any` of at least one.
- A target that names no routine, or a config entry that is not loaded, is false.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Unpack, cast

from homeassistant.const import CONF_OPTIONS, CONF_TARGET
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.condition import (
    ATTR_BEHAVIOR,
    BEHAVIOR_ALL,
    BEHAVIOR_ANY,
    Condition,
    ConditionCheckParams,
    ConditionConfig,
)
from homeassistant.helpers.typing import ConfigType
import probatio as vol

from . import DeviceRoutinesConfigEntry
from .const import DOMAIN
from .manager import RoutineManager
from .models import RoutineView

CONDITION_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
        vol.Required(CONF_OPTIONS, default={}): {
            vol.Required(ATTR_BEHAVIOR, default=BEHAVIOR_ANY): vol.In([BEHAVIOR_ANY, BEHAVIOR_ALL]),
        },
    }
)


def _loaded_manager(hass: HomeAssistant) -> RoutineManager | None:
    """Return the manager of the loaded config entry, or None while it is not loaded."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        return None
    entry: DeviceRoutinesConfigEntry = entries[0]
    return entry.runtime_data.manager


class RoutineStateCondition(Condition):
    """True when any or all of the routine devices of a target are in a state."""

    @staticmethod
    def holds(view: RoutineView | None) -> bool:
        """Tell whether one routine is in the state this condition is about."""
        raise NotImplementedError

    @classmethod
    async def async_validate_config(
        cls,
        hass: HomeAssistant,  # noqa: ARG003  # the core's signature
        config: ConfigType,
    ) -> ConfigType:
        """Validate the target and the behavior."""
        return cast("ConfigType", CONDITION_SCHEMA(config))

    def __init__(self, hass: HomeAssistant, config: ConditionConfig) -> None:
        """Keep the target and the behavior."""
        super().__init__(hass, config)
        self._target: Mapping[str, Any] = config.target or {}
        self._behavior: str = (config.options or {}).get(ATTR_BEHAVIOR, BEHAVIOR_ANY)

    def _async_check(self, **kwargs: Unpack[ConditionCheckParams]) -> bool:  # noqa: ARG002  # the core's signature
        """Ask the manager's views; false without a loaded entry or a routine."""
        manager = _loaded_manager(self._hass)
        if manager is None:
            return False
        targeted = manager.resolve_targets(self._target).device_ids
        held = [self.holds(manager.get(device_id)) for device_id in targeted]
        if not held:
            return False
        return all(held) if self._behavior == BEHAVIOR_ALL else any(held)


class IsPausedCondition(RoutineStateCondition):
    """The routine is paused or skipping."""

    @staticmethod
    def holds(view: RoutineView | None) -> bool:
        """Tell whether the routine is paused or skipping."""
        return view is not None and view.is_paused


class IsActiveCondition(RoutineStateCondition):
    """The routine is on and not paused."""

    @staticmethod
    def holds(view: RoutineView | None) -> bool:
        """Tell whether the routine is on and not paused."""
        return view is not None and view.is_active


CONDITIONS: Final[dict[str, type[Condition]]] = {
    "is_paused": IsPausedCondition,
    "is_active": IsActiveCondition,
}


async def async_get_conditions(hass: HomeAssistant) -> dict[str, type[Condition]]:
    """Return the integration's purpose specific conditions."""
    return CONDITIONS
