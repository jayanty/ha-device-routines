"""Behavior matrix: refused actions never fire (B39).

PRD 5.4: a routine never schedules, delays or re-triggers unlocking a lock, opening a
garage door, gate or door cover, opening a gas valve, or disarming (or any action on) an
alarm panel. The compiler refuses them and sync back refuses them again; the blueprint is
the third guard and holds whatever inputs it is given. A service only acts on entities of
its own domain and the blueprint always aims the on action at the target, so the guard
keys on the target: a lock or an alarm panel (by its states), or a garage, gate, door or
gas device class, never gets the on action.

The table runs every refused action through every path that can call the on action, with
the refused service mocked; the allowed control row proves each path really calls it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from tests.blueprint.conftest import (
    DEVICE_ID,
    EVENT_TIMER_CAUGHT_UP,
    OVERRIDE,
    PAUSED,
    SCHEDULE,
    TIMER,
    Clock,
    SandboxDateTime,
    SandboxSwitch,
    async_create_schedule,
    async_create_timer,
    inputs,
)

Routine = Callable[[Mapping[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class Target:
    """A device and the action pair a routine for it would carry."""

    entity_id: str
    on_action: str
    off_action: str
    inactive_state: str
    active_state: str
    device_class: str | None = None

    def inputs(self, **extra: Any) -> dict[str, Any]:
        return inputs(
            target_entity=self.entity_id,
            on_action=self.on_action,
            off_action=self.off_action,
            inactive_state=self.inactive_state,
            override_entity=OVERRIDE,
            paused_until_entity=PAUSED,
            **extra,
        )

    def set(self, hass: HomeAssistant, state: str) -> None:
        attributes = {} if self.device_class is None else {"device_class": self.device_class}
        hass.states.async_set(self.entity_id, state, attributes)


ALARM = "alarm_control_panel.house_alarm"
REFUSED = {
    "lock_unlock": Target("lock.front_door", "lock.unlock", "lock.lock", "locked", "unlocked"),
    "lock_open": Target("lock.front_door", "lock.open", "lock.lock", "locked", "unlocked"),
    "garage_open": Target(
        "cover.garage_door", "cover.open_cover", "cover.close_cover", "closed", "open", "garage"
    ),
    "gate_open": Target(
        "cover.driveway_gate", "cover.open_cover", "cover.close_cover", "closed", "open", "gate"
    ),
    "door_open": Target(
        "cover.patio_door", "cover.open_cover", "cover.close_cover", "closed", "open", "door"
    ),
    "gas_valve_open": Target(
        "valve.gas_main", "valve.open_valve", "valve.close_valve", "closed", "open", "gas"
    ),
    "alarm_disarm": Target(
        ALARM,
        "alarm_control_panel.alarm_disarm",
        "alarm_control_panel.alarm_arm_away",
        "armed_away",
        "disarmed",
    ),
    "alarm_trigger": Target(
        ALARM,
        "alarm_control_panel.alarm_trigger",
        "alarm_control_panel.alarm_arm_away",
        "armed_away",
        "triggered",
    ),
}
ALLOWED = Target(
    "input_boolean.sandbox_plug", "input_boolean.turn_on", "input_boolean.turn_off", "off", "on"
)


@dataclass
class Scene:
    hass: HomeAssistant
    clock: Clock
    routine: Routine
    target: Target
    override: SandboxSwitch
    paused: SandboxDateTime


async def reconnect(scene: Scene) -> None:
    scene.target.set(scene.hass, "unavailable")
    await scene.clock.advance(seconds=30)
    scene.target.set(scene.hass, scene.target.inactive_state)
    await scene.clock.advance(seconds=11)


async def scheduled_on(scene: Scene) -> None:
    await scene.routine(scene.target.inputs(on_time="10:01:00"))
    await scene.clock.to(scene.clock.at(0, "10:01:01"))


async def block_on(scene: Scene) -> None:
    await async_create_schedule(scene.hass, {"monday": [("10:01:00", "11:00:00")]})
    await scene.routine(scene.target.inputs(schedule_entity=SCHEDULE))
    await scene.clock.to(scene.clock.at(0, "10:01:01"))


async def catch_up_on_reconnect(scene: Scene) -> None:
    await scene.routine(scene.target.inputs(on_time="09:00:00", off_time="12:00:00"))
    await reconnect(scene)


async def one_shot_late_start(scene: Scene) -> None:
    await scene.routine(scene.target.inputs(on_time="09:55:00"))
    await reconnect(scene)


async def catch_up_at_pause_end(scene: Scene) -> None:
    await scene.routine(scene.target.inputs(on_time="09:00:00", off_time="12:00:00"))
    scene.paused.set(scene.clock.at(0, "10:30"))
    await scene.clock.to(scene.clock.at(0, "10:30"))
    scene.paused.set(None)
    await scene.hass.async_block_till_done()


async def catch_up_when_override_clears(scene: Scene) -> None:
    await scene.routine(scene.target.inputs(on_time="09:00:00", off_time="12:00:00"))
    scene.override.device_change(on=True)
    await scene.hass.async_block_till_done()
    scene.override.device_change(on=False)
    await scene.hass.async_block_till_done()


async def turn_back_on_after(scene: Scene) -> None:
    await async_create_timer(scene.hass)
    await scene.routine(scene.target.inputs(timer_entity=TIMER, turn_back_on_after_min=1))
    scene.target.set(scene.hass, scene.target.active_state)
    await scene.hass.async_block_till_done()
    scene.target.set(scene.hass, scene.target.inactive_state)
    await scene.hass.async_block_till_done()
    await scene.clock.advance(seconds=61)


async def caught_up_countdown(scene: Scene) -> None:
    await async_create_timer(scene.hass)
    await scene.routine(scene.target.inputs(timer_entity=TIMER, turn_back_on_after_min=1))
    scene.hass.bus.async_fire(EVENT_TIMER_CAUGHT_UP, {"device_id": DEVICE_ID})
    await scene.hass.async_block_till_done()


async def pulse(scene: Scene) -> None:
    await scene.routine(
        scene.target.inputs(pulse_at="10:01:00", pulse_minutes=1, pulse_min_steady_min=0)
    )
    await scene.clock.to(scene.clock.at(0, "10:01:01"), settle="yield")
    await scene.clock.to(scene.clock.at(0, "10:02:02"), settle="yield")
    await scene.hass.async_block_till_done()


PATHS = {
    "scheduled_on": scheduled_on,
    "block_on": block_on,
    "catch_up_on_reconnect": catch_up_on_reconnect,
    "one_shot_late_start": one_shot_late_start,
    "catch_up_at_pause_end": catch_up_at_pause_end,
    "catch_up_when_override_clears": catch_up_when_override_clears,
    "turn_back_on_after": turn_back_on_after,
    "caught_up_countdown": caught_up_countdown,
    "pulse": pulse,
}


async def run_path(
    hass: HomeAssistant,
    clock: Clock,
    routine: Routine,
    override: SandboxSwitch,
    paused: SandboxDateTime,
    target: Target,
    path: str,
) -> list[ServiceCall]:
    """Run one path against one target and return the calls of its on action."""
    clock.set(clock.at(0, "10:00"))
    on_domain, on_service = target.on_action.split(".")
    off_domain, off_service = target.off_action.split(".")
    on_calls = async_mock_service(hass, on_domain, on_service)
    async_mock_service(hass, off_domain, off_service)
    target.set(hass, target.inactive_state)
    await PATHS[path](Scene(hass, clock, routine, target, override, paused))
    return on_calls


@pytest.mark.parametrize("path", list(PATHS))
@pytest.mark.parametrize("refused", list(REFUSED))
async def test_b39_refused_actions_never_fire(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    refused: str,
    path: str,
) -> None:
    calls = await run_path(
        hass,
        clock,
        routine_automation,
        override_switch,
        paused_until,
        REFUSED[refused],
        path,
    )

    assert calls == []


@pytest.mark.parametrize("path", list(PATHS))
async def test_b39_control_every_path_calls_an_allowed_on_action(
    hass: HomeAssistant,
    clock: Clock,
    routine_automation: Routine,
    override_switch: SandboxSwitch,
    paused_until: SandboxDateTime,
    path: str,
) -> None:
    calls = await run_path(
        hass, clock, routine_automation, override_switch, paused_until, ALLOWED, path
    )

    assert [call.data["entity_id"] for call in calls] == [[ALLOWED.entity_id]]
