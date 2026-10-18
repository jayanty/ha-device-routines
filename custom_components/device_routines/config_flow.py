"""The config flow and the options flow (PRD D33 and 10.4, TECH_SPEC 4.12).

Setup has no fields: one confirmation creates the single entry. Once the entry is loaded,
the optional suggestions screen follows when the Schedule summary found devices that time
based automations drive: the options flow's `suggestions` step, chained as the created
entry's next flow (all unchecked; leaving them unchecked skips it).

The options flow is a menu of three pages:

- `settings`: every PRD 10.4 setting with its selector, validated by `settings.validate`;
  storing changed settings reloads the entry.
- `devices`: the devices with routine controls, picked from the eligible ones the manager
  lists and prefilled with the opted in set; a change opts devices in or out.
- `suggestions`: the setup screen again, repeatable.

The flows only show and pass on: eligibility, suggestions and opting in and out are the
manager's (PRD P16), the setting rules are `settings.py`'s.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    FlowType,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    Selector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import probatio as vol

from .const import DOMAIN, INTEGRATION_TITLE
from .manager import SOURCE_FLOW, DeviceChoice, RoutineManager
from .settings import BOOLEANS, ENUMS, RANGES, GlobalSettings, from_options, validate

STEP_SETTINGS: Final = "settings"
STEP_DEVICES: Final = "devices"
STEP_SUGGESTIONS: Final = "suggestions"
CONF_DEVICES: Final = "devices"
CONF_AI_TASK_ENTITY: Final = "ai_task_entity"

# The unit each number setting reads in, translated under `selector.<setting>`.
NUMBER_UNITS: Final[Mapping[str, str]] = {
    "default_late_start_window_min": "minutes",
    "cleanup_after_days": "days",
    "ai_calls_per_hour": "calls",
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

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        """Chain the suggestions screen when the loaded entry has something to suggest."""
        entry = result["result"]
        if entry.state is not ConfigEntryState.LOADED:
            return result
        manager: RoutineManager = entry.runtime_data.manager
        if not manager.suggested_devices():
            return result
        options = self.hass.config_entries.options
        menu = await options.async_init(entry.entry_id)
        step = await options.async_configure(menu["flow_id"], {"next_step_id": STEP_SUGGESTIONS})
        result["next_flow"] = (FlowType.OPTIONS_FLOW, step["flow_id"])
        return result

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004  # the signature Home Assistant calls
    ) -> DeviceRoutinesOptionsFlow:
        """Return the options flow."""
        return DeviceRoutinesOptionsFlow()


class DeviceRoutinesOptionsFlow(OptionsFlowWithReload):
    """Settings, devices and suggestions; storing changed settings reloads the entry."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002  # a menu reads no input
    ) -> ConfigFlowResult:
        """Offer the three pages."""
        return self.async_show_menu(
            step_id="init", menu_options=[STEP_SETTINGS, STEP_DEVICES, STEP_SUGGESTIONS]
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show every global setting and store valid choices."""
        values = from_options(self.config_entry.options).to_options()
        errors: dict[str, str] = {}
        if user_input is not None:
            values |= _settings_from_form(user_input)
            errors = {problem.key: problem.translation_key for problem in validate(values)}
            if not errors:
                return self.async_create_entry(data=from_options(values).to_options())
        return self.async_show_form(
            step_id=STEP_SETTINGS, data_schema=_settings_schema(values), errors=errors
        )

    async def async_step_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the devices with routine controls from the eligible ones."""
        if (manager := self._manager()) is None:
            return self.async_abort(reason="not_loaded")
        offered = [choice.device_id for choice in manager.eligible_devices()]
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            # The manager judges every chosen device (one removed meanwhile is an error);
            # only devices the picker offers are ever opted out.
            chosen = user_input[CONF_DEVICES]
            opted_in = set(manager.opted_in_devices())
            errors, placeholders = await _async_opt(
                manager,
                opt_in=[device for device in chosen if device not in opted_in],
                opt_out=[device for device in offered if device in opted_in - set(chosen)],
            )
            if not errors:
                return self._done()
        opted_in = set(manager.opted_in_devices())
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DEVICES, default=[device for device in offered if device in opted_in]
                ): _device_picker(self, manager.eligible_devices(), SelectSelectorMode.DROPDOWN)
            }
        )
        return self.async_show_form(
            step_id=STEP_DEVICES,
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_suggestions(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """List the devices time based automations drive, all unchecked; opt in the chosen."""
        if (manager := self._manager()) is None:
            return self.async_abort(reason="not_loaded")
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            errors, placeholders = await _async_opt(
                manager, opt_in=user_input[CONF_DEVICES], opt_out=()
            )
            if not errors:
                return self._done()
        suggested = manager.suggested_devices()
        if not suggested and not errors:
            return self.async_abort(reason="no_suggestions")
        schema = vol.Schema(
            {
                vol.Optional(CONF_DEVICES, default=[]): _device_picker(
                    self, suggested, SelectSelectorMode.LIST
                )
            }
        )
        return self.async_show_form(
            step_id=STEP_SUGGESTIONS,
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    def _manager(self) -> RoutineManager | None:
        """Return the loaded entry's manager, or None while the entry is not loaded."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return None
        manager: RoutineManager = self.config_entry.runtime_data.manager
        return manager

    def _done(self) -> ConfigFlowResult:
        """Finish with the options unchanged, so opting in or out reloads nothing."""
        return self.async_create_entry(data=dict(self.config_entry.options))


# --------------------------------------------------------------------------------------
# Form plumbing
# --------------------------------------------------------------------------------------


def _selector(key: str) -> Selector[Any]:
    """Return the selector of one global setting, from its kind in `settings.py`."""
    if key in ENUMS:
        return SelectSelector(
            SelectSelectorConfig(
                options=[member.value for member in ENUMS[key]],
                translation_key=key,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    if key in BOOLEANS:
        return BooleanSelector()
    if key in RANGES:
        low, high = RANGES[key]
        return NumberSelector(
            NumberSelectorConfig(
                min=low,
                max=high,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=NUMBER_UNITS[key],
                translation_key=key,
            )
        )
    return EntitySelector(EntitySelectorConfig(domain="ai_task"))


def _settings_schema(values: Mapping[str, Any]) -> vol.Schema:
    """Every setting in the PRD 10.4 order; the AI entity may be left empty (none)."""
    fields: dict[vol.Marker, Selector[Any]] = {}
    for key in GlobalSettings().to_options():
        marker: vol.Marker = (
            vol.Optional(key, description={"suggested_value": values.get(key)})
            if key == CONF_AI_TASK_ENTITY
            else vol.Required(key, default=values[key])
        )
        fields[marker] = _selector(key)
    return vol.Schema(fields)


def _settings_from_form(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Read the form back: whole numbers as integers, a cleared AI entity as none."""
    values = {key: _whole(value) if key in RANGES else value for key, value in user_input.items()}
    values.setdefault(CONF_AI_TASK_ENTITY, None)
    return values


def _whole(value: Any) -> Any:
    """Return a whole float as an integer; the number selector hands back floats."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _device_picker(
    flow: DeviceRoutinesOptionsFlow, choices: Iterable[DeviceChoice], mode: SelectSelectorMode
) -> SelectSelector:
    """Return a multiple choice of devices, each named with its area when it has one."""
    areas = ar.async_get(flow.hass)
    options: list[SelectOptionDict] = []
    for choice in choices:
        area = areas.async_get_area(choice.area_id) if choice.area_id else None
        label = f"{choice.name} ({area.name})" if area else choice.name
        options.append(SelectOptionDict(value=choice.device_id, label=label))
    return SelectSelector(SelectSelectorConfig(options=options, multiple=True, mode=mode))


async def _async_opt(
    manager: RoutineManager, *, opt_in: Iterable[str], opt_out: Iterable[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Opt devices in and out through the manager; return the form's errors if one fails."""
    try:
        for device_id in opt_in:
            await manager.async_opt_in(device_id, SOURCE_FLOW)
        for device_id in opt_out:
            await manager.async_opt_out(device_id, SOURCE_FLOW)
    except ServiceValidationError as err:
        return {CONF_DEVICES: str(err.translation_key)}, dict(err.translation_placeholders or {})
    return {}, {}
