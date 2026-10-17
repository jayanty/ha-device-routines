"""The probe's trigger: a targeted switch turned on."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.trigger import Trigger, make_entity_target_state_trigger

TRIGGERS: dict[str, type[Trigger]] = {
    "routine_started": make_entity_target_state_trigger("switch", "on"),
}


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Return the probe's triggers."""
    return TRIGGERS
