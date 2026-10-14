"""The zero field config flow (PRD D33): one click, one instance.

The optional suggestions screen that lists devices already driven by time based automations
arrives with the routines in Phase 2; the options flow arrives with the settings in Phase 1.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
import probatio as vol

from .const import DOMAIN, INTEGRATION_TITLE


class DeviceRoutinesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single config entry without asking anything."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show one empty confirmation form, then create the entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
        return self.async_create_entry(title=INTEGRATION_TITLE, data={})
