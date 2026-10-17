"""Stage 0 V13 throwaway integration: one purpose specific trigger and one condition."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Nothing to set up: the trigger and condition platforms are found on their own."""
    return True
