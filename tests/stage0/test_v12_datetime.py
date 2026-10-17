"""Stage 0 V12, A13: a `datetime` entity in time triggers and time conditions.

Paused until is a `datetime` entity. The blueprint's `pause_ended` trigger and its
`not_paused` condition would ideally read it natively. These probes record what the
pinned core accepts, how a timestamp sensor compares, whether the template fallback of
TECH_SPEC 5.4 behaves, and whether a restored `datetime` entity keeps its value.

Recorded results (core 2026.10.1): the time trigger accepts `input_datetime` and `sensor`
only, the time condition `input_datetime`, `time` and `sensor` only, so a `datetime`
entity fails both; a timestamp sensor works in both; the template fallback is correct; a
`datetime` entity that implements RestoreEntity gets its value back. The time condition
compares a timestamp sensor by its time of day only, so the sensor is no fallback for the
condition: the template is.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.components.datetime import DateTimeEntity
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import condition
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import probatio as vol
import pytest
from pytest_homeassistant_custom_component.common import (
    MockEntityPlatform,
    async_fire_time_changed,
    async_mock_service,
    mock_restore_cache,
)

PAUSED = "datetime.stage0_paused_until"
SENSOR = "sensor.stage0_paused_until"

NOT_PAUSED_TEMPLATE = (
    "{% set s = states(entity) %}"
    "{{ s in ('unknown', 'unavailable', '') or as_datetime(s) <= now() }}"
)


def automation_with(trigger: dict[str, Any]) -> dict[str, Any]:
    return {"triggers": [trigger], "actions": [{"action": "test.record"}]}


async def test_the_time_trigger_refuses_a_datetime_entity(hass: HomeAssistant) -> None:
    with pytest.raises(vol.Invalid, match="input_datetime"):
        await async_validate_config_item(
            hass, "stage0_trigger", automation_with({"trigger": "time", "at": PAUSED})
        )


async def test_the_time_condition_refuses_a_datetime_entity(hass: HomeAssistant) -> None:
    config = automation_with({"trigger": "homeassistant", "event": "start"})
    config["conditions"] = [{"condition": "time", "after": PAUSED}]

    with pytest.raises(vol.Invalid, match="Invalid time specified"):
        await async_validate_config_item(hass, "stage0_condition", config)


async def test_a_timestamp_sensor_works_in_trigger_and_condition(
    hass: HomeAssistant, freezer: Any
) -> None:
    end = dt_util.utcnow().replace(microsecond=0) + timedelta(minutes=5)
    hass.states.async_set(SENSOR, end.isoformat(), {"device_class": "timestamp"})
    calls = async_mock_service(hass, "test", "record")
    assert await async_setup_component(
        hass, "automation", {"automation": automation_with({"trigger": "time", "at": SENSOR})}
    )
    await hass.async_block_till_done()

    after_end = condition.async_from_config(hass, {"condition": "time", "after": SENSOR})
    checker = await after_end
    assert checker(hass) is False

    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert checker(hass) is True


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("unknown", True),
        ("unavailable", True),
        ("2026-10-17T10:00:00+00:00", True),
        ("2026-10-17T14:00:00+00:00", False),
    ],
)
async def test_the_template_fallback_reads_a_datetime_entity(
    hass: HomeAssistant, freezer: Any, state: str, expected: bool
) -> None:
    freezer.move_to(datetime(2026, 10, 17, 12, 0, tzinfo=dt_util.UTC))
    hass.states.async_set(PAUSED, state)

    rendered = Template(NOT_PAUSED_TEMPLATE, hass).async_render({"entity": PAUSED})

    assert rendered is expected


class RestoredDateTime(DateTimeEntity, RestoreEntity):
    """The shape Paused until takes: a datetime entity that restores its value."""

    _attr_name = "stage0 paused until"
    _attr_unique_id = "stage0_paused_until"
    _attr_native_value: datetime | None = None

    async def async_added_to_hass(self) -> None:
        if (last := await self.async_get_last_state()) is not None:
            self._attr_native_value = dt_util.parse_datetime(last.state)

    async def async_set_value(self, value: datetime) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


async def test_a_restored_datetime_entity_keeps_its_value(hass: HomeAssistant) -> None:
    stored = "2026-10-18T07:30:00+00:00"
    mock_restore_cache(hass, [State(PAUSED, stored)])
    platform = MockEntityPlatform(hass, domain="datetime", platform_name="stage0")

    await platform.async_add_entities([RestoredDateTime()])
    await hass.async_block_till_done()

    state = hass.states.get(PAUSED)
    assert state is not None
    assert state.state == stored


async def test_a_timestamp_sensor_condition_compares_the_time_of_day_only(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Why a timestamp sensor cannot carry Paused until in a time condition either.

    A pause until tomorrow 07:30 reads as over at 08:00 today, because the condition
    takes only the local time of day of the sensor's value.
    """
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to(datetime(2026, 10, 17, 8, 0, tzinfo=dt_util.UTC))
    hass.states.async_set(SENSOR, "2026-10-18T07:30:00+00:00", {"device_class": "timestamp"})

    assert condition.time(hass, after=SENSOR) is True
    assert Template(NOT_PAUSED_TEMPLATE, hass).async_render({"entity": SENSOR}) is False
