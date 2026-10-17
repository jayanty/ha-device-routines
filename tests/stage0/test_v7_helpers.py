"""Stage 0 V7, A5: creating timer and schedule helpers from integration code.

TECH_SPEC 4.2 named the storage collections of the timer and schedule components as the
primary path. On the pinned core each collection is a local variable of its component's
`async_setup`, referenced only by its WebSocket handlers, so code cannot reach it. What
code can reach is the registered WebSocket command itself: an `ActiveConnection` built
for a system administrator user dispatches `timer/create` and `schedule/create` in
process, through the same schema and handler the editor uses. The entity id and the label
are then set in the entity registry. The live half (the same commands over the API) is in
`docs/stage0-report.md`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.auth.const import GROUP_ID_ADMIN
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.setup import async_setup_component
import pytest


class InProcess:
    """One in process WebSocket connection; returns each command's result."""

    def __init__(self, hass: HomeAssistant, connection_user: Any) -> None:
        self.results: dict[int, dict[str, Any]] = {}
        self.connection = ActiveConnection(
            logging.getLogger(__name__),  # type: ignore[arg-type]
            hass,
            self._receive,
            connection_user,
            None,
            None,
        )
        self._next = 0

    def _receive(self, message: Any) -> None:
        if not isinstance(message, dict):
            message = json.loads(message)
        self.results[message["id"]] = message

    async def call(self, hass: HomeAssistant, **command: Any) -> dict[str, Any]:
        self._next += 1
        self.connection.async_handle({"id": self._next, **command})
        # Async command handlers run as background tasks, as they do for a socket.
        await hass.async_block_till_done(wait_background_tasks=True)
        assert self._next in self.results, self.results
        return self.results[self._next]


@pytest.fixture
async def connection(hass: HomeAssistant) -> InProcess:
    assert await async_setup_component(hass, "websocket_api", {})
    assert await async_setup_component(hass, "timer", {})
    assert await async_setup_component(hass, "schedule", {})
    user = await hass.auth.async_create_system_user("Device Routines", group_ids=[GROUP_ID_ADMIN])
    return InProcess(hass, user)


async def test_a_timer_with_a_chosen_entity_id_and_the_label(
    hass: HomeAssistant, connection: InProcess
) -> None:
    label = lr.async_get(hass).async_create("Routines")

    created = await connection.call(
        hass,
        type="timer/create",
        name="Routine living room fan",
        duration="00:30:00",
        restore=True,
    )

    assert created["success"], created
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("timer", "timer", created["result"]["id"])
    assert entity_id == "timer.routine_living_room_fan"
    registry.async_update_entity(
        entity_id, new_entity_id="timer.routine_living_room_fan_2", labels={label.label_id}
    )
    await hass.async_block_till_done()
    state = hass.states.get("timer.routine_living_room_fan_2")
    assert state is not None
    assert state.attributes["restore"] is True
    assert registry.async_get("timer.routine_living_room_fan_2").labels == {  # type: ignore[union-attr]
        label.label_id
    }

    deleted = await connection.call(hass, type="timer/delete", timer_id=created["result"]["id"])
    assert deleted["success"]
    assert hass.states.get("timer.routine_living_room_fan_2") is None


async def test_a_schedule_with_blocks(hass: HomeAssistant, connection: InProcess) -> None:
    created = await connection.call(
        hass,
        type="schedule/create",
        name="Routine living room fan",
        monday=[{"from": "17:00:00", "to": "24:00:00"}],
        tuesday=[{"from": "00:00:00", "to": "09:00:00"}],
    )

    assert created["success"], created
    assert hass.states.get("schedule.routine_living_room_fan") is not None

    deleted = await connection.call(
        hass, type="schedule/delete", schedule_id=created["result"]["id"]
    )
    assert deleted["success"]


async def test_a_non_admin_user_is_refused(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "websocket_api", {})
    assert await async_setup_component(hass, "timer", {})
    user = await hass.auth.async_create_system_user("Device Routines")
    connection = InProcess(hass, user)

    created = await connection.call(hass, type="timer/create", name="Routine fan")

    assert created["success"] is False
    assert created["error"]["code"] == "unauthorized"
