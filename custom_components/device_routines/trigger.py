"""Purpose specific triggers: a routine skipped an action, paused or resumed (PRD FR-R17).

`device_routines.action_skipped`, `device_routines.paused` and `device_routines.resumed`
in the core's integration trigger shape (Stage 0 V13): a `target` (device, area, label,
floor or entity) that the manager resolves to routine devices, and the `behavior` option
each, first or all. They are thin readers (PRD P16):

- The moment is a bus event: the manager's `device_routines_paused` and
  `device_routines_resumed`, and the blueprint's `device_routines_action_skipped`.
- Whether a routine is paused or active is its view's status (`RoutineManager.get`):
  paused means `paused` or `skipping` (a skip is a pause until its paired end, D18 and
  D19); active means `active` (on, valid and not paused).
- `paused` fires when the event's routine reads paused, `resumed` when it reads active
  again; `action_skipped` fires for every skip, which only a paused routine makes.
- `first` fires only while the event's routine is the one targeted routine in that state
  (paused for `paused` and `action_skipped`, active for `resumed`); `all` only while every
  targeted routine is. As the core's state triggers count the states as of each change,
  the listener is a callback, which the bus runs at the moment the event is fired, before
  any later change; an area action that pauses two routines one after the other therefore
  fires `first` for the first and `all` for the second.
- Nothing fires while the config entry is not loaded, and an event about a device the
  target does not resolve to a routine never fires.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Final, cast

from homeassistant.const import CONF_OPTIONS, CONF_TARGET
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.trigger import (
    ATTR_BEHAVIOR,
    BEHAVIOR_ALL,
    BEHAVIOR_EACH,
    BEHAVIOR_FIRST,
    Trigger,
    TriggerActionRunner,
    TriggerConfig,
    TriggerNotTriggeredReporter,
)
from homeassistant.helpers.typing import ConfigType
import probatio as vol

from . import DeviceRoutinesConfigEntry
from .compiler import EVENT_ACTION_SKIPPED
from .const import DOMAIN, EVENT_PAUSED, EVENT_RESUMED
from .manager import RoutineManager
from .models import RoutineView, Status

# Statuses a routine is paused in: a skip pauses until its paired end (D18, D19).
PAUSED_STATUSES: Final = frozenset({Status.PAUSED, Status.SKIPPING})

TRIGGER_SCHEMA: Final = vol.Schema(
    {
        vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
        vol.Required(CONF_OPTIONS, default={}): {
            vol.Required(ATTR_BEHAVIOR, default=BEHAVIOR_EACH): vol.In(
                [BEHAVIOR_EACH, BEHAVIOR_FIRST, BEHAVIOR_ALL]
            ),
        },
    }
)


def loaded_manager(hass: HomeAssistant) -> RoutineManager | None:
    """Return the manager of the loaded config entry, or None while it is not loaded."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        return None
    entry: DeviceRoutinesConfigEntry = entries[0]
    return entry.runtime_data.manager


def routine_is_paused(view: RoutineView | None) -> bool:
    """Tell whether a routine is paused or skipping."""
    return view is not None and view.status in PAUSED_STATUSES


def routine_is_active(view: RoutineView | None) -> bool:
    """Tell whether a routine is on, valid and neither paused nor skipping."""
    return view is not None and view.status is Status.ACTIVE


class RoutineEventTrigger(Trigger):
    """A trigger on one bus event about a routine, for the routine devices of a target."""

    event_type: ClassVar[str]
    happened: ClassVar[str]
    # Whether the event itself proves the routine is in the trigger's state.
    event_proves_state: ClassVar[bool] = False

    @staticmethod
    def in_state(view: RoutineView | None) -> bool:
        """Tell whether a routine is in the state this trigger is about."""
        raise NotImplementedError

    @classmethod
    async def async_validate_config(
        cls,
        hass: HomeAssistant,  # noqa: ARG003  # the core's signature
        config: ConfigType,
    ) -> ConfigType:
        """Validate the target and the behavior."""
        return cast("ConfigType", TRIGGER_SCHEMA(config))

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        """Keep the target and the behavior."""
        super().__init__(hass, config)
        self._target: Mapping[str, Any] = config.target or {}
        self._behavior: str = (config.options or {}).get(ATTR_BEHAVIOR, BEHAVIOR_EACH)

    def fires(self, manager: RoutineManager, device_id: str) -> bool:
        """Decide, as of the event, whether it fires for the device the event names."""
        targeted = manager.resolve_targets(self._target).device_ids
        if device_id not in targeted:
            return False
        held = {target: self.in_state(manager.get(target)) for target in targeted}
        held[device_id] = held[device_id] or self.event_proves_state
        if not held[device_id]:
            return False
        if self._behavior == BEHAVIOR_FIRST:
            return sum(held.values()) == 1
        if self._behavior == BEHAVIOR_ALL:
            return all(held.values())
        return True

    async def async_attach_runner(
        self,
        run_action: TriggerActionRunner,
        did_not_trigger: TriggerNotTriggeredReporter | None = None,  # noqa: ARG002  # the core's signature
    ) -> CALLBACK_TYPE:
        """Listen to the event with a callback, which the bus runs as the event is fired."""

        @callback
        def heard(event: Event[Mapping[str, Any]]) -> None:
            manager = loaded_manager(self._hass)
            device_id = str(event.data.get("device_id"))
            if manager is None or not self.fires(manager, device_id):
                return
            view = manager.get(device_id)
            name = view.device_name if view is not None else device_id
            run_action(
                {**event.data, "device_name": name},
                f"{name} routine {self.happened}",
                event.context,
            )

        return self._hass.bus.async_listen(self.event_type, heard)


class ActionSkippedTrigger(RoutineEventTrigger):
    """A scheduled action or countdown did not run because the routine was paused."""

    event_type = EVENT_ACTION_SKIPPED
    happened = "skipped an action"
    event_proves_state = True

    @staticmethod
    def in_state(view: RoutineView | None) -> bool:
        """Tell whether a routine is paused: only a paused routine skips."""
        return routine_is_paused(view)


class PausedTrigger(RoutineEventTrigger):
    """A routine became paused or skipping, from any source."""

    event_type = EVENT_PAUSED
    happened = "paused"

    @staticmethod
    def in_state(view: RoutineView | None) -> bool:
        """Tell whether a routine is paused or skipping."""
        return routine_is_paused(view)


class ResumedTrigger(RoutineEventTrigger):
    """A pause or skip ended, by time or by Resume, and the routine runs again."""

    event_type = EVENT_RESUMED
    happened = "resumed"

    @staticmethod
    def in_state(view: RoutineView | None) -> bool:
        """Tell whether a routine is active again."""
        return routine_is_active(view)


TRIGGERS: Final[dict[str, type[Trigger]]] = {
    "action_skipped": ActionSkippedTrigger,
    "paused": PausedTrigger,
    "resumed": ResumedTrigger,
}


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Return the integration's purpose specific triggers."""
    return TRIGGERS
