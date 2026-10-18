"""Behavior matrix: the integration disabled, the routine still runs (B43).

PRD P6 and 9.3: Home Assistant runs the routine; the integration only configures it. With
the config entry disabled, the Manual override and Paused until entities are unavailable
or gone, and the blueprint reads both as clear, so the routine keeps its schedule, its
countdowns and its catch up. The only thing that waits for the integration is a timer that
ran out during a restart (decision L20), which the user guide states.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.blueprint.conftest import (
    OVERRIDE,
    PAUSED,
    TIMER,
    Clock,
    SandboxDateTime,
    SandboxSwitch,
    async_add_sandbox_entities,
    inputs,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]


@pytest.mark.parametrize("helpers", ["gone", "unavailable"])
async def test_b43_integration_disabled_the_routine_still_runs(
    hass: HomeAssistant,
    clock: Clock,
    init_integration: MockConfigEntry,
    routine_automation: Routine,
    sandbox_switch: SandboxSwitch,
    routine_timer: str,
    helpers: str,
) -> None:
    clock.set(clock.at(0, "16:00"))
    assert await hass.config_entries.async_set_disabled_by(
        init_integration.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED
    if helpers == "unavailable":
        override = SandboxSwitch(OVERRIDE, "Living room fan manual override")
        paused = SandboxDateTime(PAUSED, "Living room fan paused until")
        await async_add_sandbox_entities(hass, "switch", override)
        await async_add_sandbox_entities(hass, "datetime", paused)
        override.device_change(on=True)
        paused.set(clock.at(1, "12:00"))
        override.set_available(False)
        paused.set_available(False)
    await routine_automation(
        inputs(
            on_time="17:00:00",
            off_time="23:00:00",
            timer_entity=TIMER,
            turn_off_after_min=30,
            override_entity=OVERRIDE,
            paused_until_entity=PAUSED,
        )
    )
    assert hass.states.get(OVERRIDE) is None or hass.states.get(OVERRIDE).state == "unavailable"  # type: ignore[union-attr]

    # The schedule runs.
    await clock.to(clock.at(0, "17:00:01"))
    assert sandbox_switch.state_now == "on"
    # Catch up runs on a reconnect: an override that cannot be read is no override.
    sandbox_switch.device_change(on=False)
    sandbox_switch.set_available(False)
    await clock.to(clock.at(0, "18:00"))
    sandbox_switch.set_available(True)
    await clock.to(clock.at(0, "18:00:11"))
    assert sandbox_switch.state_now == "on"
    await clock.to(clock.at(0, "23:00:01"))
    assert sandbox_switch.state_now == "off"
    # Countdowns run: a manual on after the window turns off after 30 minutes.
    await clock.to(clock.at(0, "23:10"))
    sandbox_switch.device_change(on=True)
    await hass.async_block_till_done()
    await clock.to(clock.at(0, "23:40:01"))
    assert sandbox_switch.state_now == "off"
