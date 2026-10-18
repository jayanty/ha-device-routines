"""The zero field config flow (PRD D33): one click, one instance.

The optional suggestions screen that lists devices already driven by time based automations
arrives with the routines in Phase 2. The options flow has the settings page; Phase 1 offers
the settings the summary uses, and the rest join as their features ship (plan task 3.9).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import probatio as vol

from .const import DOMAIN, INTEGRATION_TITLE
from .settings import ScheduleScope, TimeFormat, from_options, validate

# The settings Phase 1 offers, each a select with translated options.
PHASE_1_SETTINGS: dict[str, type[ScheduleScope | TimeFormat]] = {
    "schedule_scope": ScheduleScope,
    "time_format": TimeFormat,
}


class DeviceRoutinesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single config entry without asking anything."""

    VERSION = 1
    MINOR_VERSION = 2  # the options version (settings.OPTIONS_VERSION, migration.py)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show one empty confirmation form, then create the entry."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}))
        return self.async_create_entry(title=INTEGRATION_TITLE, data={})

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004  # the signature Home Assistant calls
    ) -> DeviceRoutinesOptionsFlow:
        """Return the options flow."""
        return DeviceRoutinesOptionsFlow()


class DeviceRoutinesOptionsFlow(OptionsFlowWithReload):
    """The settings page; storing new options reloads the entry."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the settings page and store valid choices."""
        errors: dict[str, str] = {}
        if user_input is not None:
            problems = validate(user_input)
            errors = {problem.key: problem.translation_key for problem in problems}
            if not errors:
                return self.async_create_entry(data={**self.config_entry.options, **user_input})
        current = from_options(self.config_entry.options).to_options()
        schema = vol.Schema(
            {
                vol.Required(key, default=current[key]): SelectSelector(
                    SelectSelectorConfig(
                        options=[member.value for member in choices],
                        translation_key=key,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
                for key, choices in PHASE_1_SETTINGS.items()
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
