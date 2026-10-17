"""The probe's condition: a targeted switch is on."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.condition import Condition, make_entity_state_condition

CONDITIONS: dict[str, type[Condition]] = {
    "routine_active": make_entity_state_condition("switch", "on"),
}


async def async_get_conditions(hass: HomeAssistant) -> dict[str, type[Condition]]:
    """Return the probe's conditions."""
    return CONDITIONS
