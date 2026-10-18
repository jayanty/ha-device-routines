"""Build A lane 14: the optional AI summary (PRD FR-S5, TECH_SPEC 4.4).

A fake AI Task entity stands in for the person's model: an `ai_task.local_model` state
and the core's `ai_task.generate_data` action, registered with the same response shape
(`conversation_id`, `data`). The integration only ever calls that public action, so the
fake proves what is sent, when, how often and what is shown. Every id and name is
synthetic.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timedelta
import json
import logging
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import (
    CoreState,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import ai_prompt, ha_adapter, markers
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.sentence import load_phrases
from custom_components.device_routines.settings import from_options
from custom_components.device_routines.store import RoutineStore
from custom_components.device_routines.summary import (
    AI_STARTUP_DELAY,
    SOURCE_AI,
    SummaryCoordinator,
    TokenBucket,
    schedule_unique_id,
)

TZ = "America/Los_Angeles"
LA = ZoneInfo(TZ)
FAN = "fan.living_room_fan"
AI_ENTITY = "ai_task.local_model"
AI_ON = {"ai_task_entity": AI_ENTITY}
HOT = "{{ states('sensor.outdoor_temperature') | float(0) > 25 }}"
DARK = "{{ is_state('sun.sun', 'below_horizon') }}"
ANSWER = "Turns the fan on when it is hot outside"

# The AI path waits on point in time listeners and the summary's next run timer.
pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])


class FakeAiTask:
    """The AI Task entity's generate data action, answering from a queue of replies."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.calls: list[dict[str, Any]] = []
        self.replies: deque[Any] = deque()
        self.gate: asyncio.Event | None = None
        self.in_flight = 0
        self.most_in_flight = 0
        hass.states.async_set(AI_ENTITY, "unknown", {"friendly_name": "Local model"})
        hass.services.async_register(
            "ai_task", "generate_data", self._generate, supports_response=SupportsResponse.ONLY
        )

    async def _generate(self, call: ServiceCall) -> ServiceResponse:
        self.calls.append(dict(call.data))
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        try:
            if self.gate is not None:
                await self.gate.wait()
            reply = self.replies.popleft() if self.replies else ANSWER
            if isinstance(reply, Exception):
                raise reply
            return {"conversation_id": "conversation", "data": reply}
        finally:
            self.in_flight -= 1

    def sent_blocks(self) -> list[dict[str, Any]]:
        """Return the blocks each call carried, read back from its instructions."""
        found = []
        for call in self.calls:
            prompt, _, payload = call["instructions"].partition("\n\n")
            assert prompt == ai_prompt.PROMPT
            found.append(json.loads(payload))
        return found


@pytest.fixture
def ai(hass: HomeAssistant) -> FakeAiTask:
    return FakeAiTask(hass)


@pytest.fixture
async def home(hass: HomeAssistant, freezer: Any) -> dict[str, Any]:
    """A fan device in a living room; Monday 2026-10-19 08:00."""
    await hass.config.async_set_time_zone(TZ)
    hass.config.country = "US"
    freezer.move_to(datetime(2026, 10, 19, 8, tzinfo=LA))
    area = ar.async_get(hass).async_create("Living room")
    other = MockConfigEntry(domain="other", title="Other")
    other.add_to_hass(hass)
    fan = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "fan")}, name="Living room fan"
    )
    dr.async_get(hass).async_update_device(fan.id, area_id=area.id)
    fan_entry = er.async_get(hass).async_get_or_create(
        "fan", "other", "fan", device_id=fan.id, suggested_object_id="living_room_fan"
    )
    hass.states.async_set(FAN, "off", {"friendly_name": "Living room fan"})
    return {"fan": fan, "area": area, "fan_entry": fan_entry}


def templated(key: str = "fan_hot", template: str = HOT) -> dict[str, Any]:
    """An automation the parser cannot read: a template trigger."""
    return {
        "id": key,
        "alias": key.replace("_", " ").capitalize(),
        "description": "Cools the living room on hot days.",
        "triggers": [{"trigger": "template", "value_template": template}],
        "actions": [{"action": "fan.turn_on", "target": {"entity_id": FAN}}],
    }


def evening(home: dict[str, Any]) -> dict[str, Any]:
    """A partly read automation: a state trigger by registry id, then a template condition."""
    return {
        "id": "fan_evening",
        "alias": "Fan off in the evening",
        "trigger": {"trigger": "state", "entity_id": home["fan_entry"].id, "to": "on"},
        "condition": [{"condition": "template", "value_template": DARK}],
        "action": [
            {
                "alias": "Quiet the living room",
                "action": "fan.turn_off",
                "metadata": {},
                "target": {"area_id": home["area"].id, "device_id": [home["fan"].id]},
            }
        ],
    }


WINDOW = {
    "id": "fan_window",
    "alias": "Fan window",
    "triggers": [{"trigger": "time", "at": "17:00:00"}],
    "actions": [{"action": "fan.turn_on", "target": {"entity_id": FAN}}],
}


async def start(
    hass: HomeAssistant, automations: list[dict[str, Any]], options: Mapping[str, Any]
) -> MockConfigEntry:
    assert await async_setup_component(hass, "automation", {"automation": automations})
    await hass.async_block_till_done()
    entry = MockConfigEntry(
        domain=DOMAIN, title=INTEGRATION_TITLE, unique_id=DOMAIN, options=dict(options)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def wait(hass: HomeAssistant, freezer: Any, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def past_startup(hass: HomeAssistant, freezer: Any) -> None:
    await wait(hass, freezer, AI_STARTUP_DELAY + timedelta(seconds=1))


def items(hass: HomeAssistant, home: dict[str, Any]) -> list[tuple[str, str]]:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, schedule_unique_id(home["fan"].id)
    )
    state = hass.states.get(entity_id or "")
    assert state is not None
    return [(item["summary"], item["source"]) for item in state.attributes["items"]]


def store_of(entry: MockConfigEntry) -> RoutineStore:
    store: RoutineStore = entry.runtime_data.store
    return store


async def rebuild(hass: HomeAssistant, freezer: Any) -> None:
    """An automation reload that changes nothing: the index is rebuilt after its debounce."""
    hass.bus.async_fire(ha_adapter.EVENT_AUTOMATION_RELOADED)
    await wait(hass, freezer, timedelta(seconds=3))


async def replace_automations(
    hass: HomeAssistant, freezer: Any, automations: list[dict[str, Any]]
) -> None:
    """Reload the automation component with another YAML configuration."""
    with patch(
        "homeassistant.config.load_yaml_config_file", return_value={"automation": automations}
    ):
        await hass.services.async_call("automation", "reload", blocking=True)
    await wait(hass, freezer, timedelta(seconds=3))


def digest_of(hass: HomeAssistant, entity_id: str) -> str:
    config = ha_adapter.automation_config(hass, entity_id)
    assert config is not None
    return markers.config_hash(config)


# --------------------------------------------------------------------------------------
# Off by default
# --------------------------------------------------------------------------------------


async def test_the_ai_summary_is_off_by_default(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    entry = await start(hass, [templated(), WINDOW], {})

    await wait(hass, freezer, timedelta(minutes=30))

    assert ai.calls == []
    assert ("Automation: Fan hot (custom logic)", "none") in items(hass, home)
    assert store_of(entry).data.ai_cache == {}


# --------------------------------------------------------------------------------------
# What is sent, when and how often
# --------------------------------------------------------------------------------------


async def test_only_unread_automations_are_sent_as_blocks_with_entity_ids_only(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    await start(hass, [templated(), evening(home), WINDOW], AI_ON)

    await past_startup(hass, freezer)

    assert [(call["task_name"], call["entity_id"]) for call in ai.calls] == [
        (ai_prompt.TASK_NAME, AI_ENTITY),
        (ai_prompt.TASK_NAME, AI_ENTITY),
    ]
    sent = ai.sent_blocks()
    # One automation per call, in entity id order; the fully read window is never sent.
    assert sent == [
        {
            "triggers": [{"trigger": "template", "value_template": HOT}],
            "conditions": [],
            "actions": [{"action": "fan.turn_on", "target": {"entity_id": FAN}}],
        },
        {
            "triggers": [{"trigger": "state", "entity_id": FAN, "to": "on"}],
            "conditions": [{"condition": "template", "value_template": DARK}],
            "actions": [
                {
                    "action": "fan.turn_off",
                    "target": {"area_id": "area_1", "device_id": ["device_1"]},
                }
            ],
        },
    ]
    everything = " ".join(call["instructions"] for call in ai.calls)
    for private in (
        "Fan hot",
        "Fan off in the evening",
        "Cools the living room",
        "Quiet the living room",
        "Living room",
        json.dumps(home["area"].id),
        home["fan"].id,
        home["fan_entry"].id,
    ):
        assert private not in everything


async def test_one_automation_at_a_time(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    ai.gate = asyncio.Event()
    await start(hass, [templated(), templated("fan_dark", DARK)], AI_ON)

    freezer.tick(AI_STARTUP_DELAY + timedelta(seconds=1))
    async_fire_time_changed(hass)
    for _ in range(5):
        await asyncio.sleep(0)

    assert len(ai.calls) == 1
    ai.gate.set()
    await hass.async_block_till_done()

    assert len(ai.calls) == 2
    assert ai.most_in_flight == 1


async def test_nothing_is_sent_during_the_first_five_minutes(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    await start(hass, [templated()], AI_ON)

    await wait(hass, freezer, AI_STARTUP_DELAY - timedelta(seconds=5))
    assert ai.calls == []
    # A rebuild inside the five minutes sends nothing either.
    await rebuild(hass, freezer)
    assert ai.calls == []

    await wait(hass, freezer, timedelta(seconds=3))

    assert len(ai.calls) == 1


async def test_the_five_minutes_start_when_home_assistant_has_started(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    hass.set_state(CoreState.not_running)
    await start(hass, [templated()], AI_ON)
    await wait(hass, freezer, AI_STARTUP_DELAY * 2)
    assert ai.calls == []

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    await wait(hass, freezer, AI_STARTUP_DELAY - timedelta(seconds=5))
    assert ai.calls == []
    await wait(hass, freezer, timedelta(seconds=6))

    assert len(ai.calls) == 1


@pytest.mark.parametrize("calls_per_hour", [1])
async def test_the_token_bucket_holds_calls_to_ai_calls_per_hour(
    hass: HomeAssistant,
    home: dict[str, Any],
    ai: FakeAiTask,
    freezer: Any,
    calls_per_hour: int,
) -> None:
    await start(
        hass,
        [templated(), templated("fan_dark", DARK)],
        {**AI_ON, "ai_calls_per_hour": calls_per_hour},
    )
    await past_startup(hass, freezer)
    assert len(ai.calls) == 1

    await wait(hass, freezer, timedelta(minutes=59))
    assert len(ai.calls) == 1

    await wait(hass, freezer, timedelta(minutes=1))
    assert len(ai.calls) == 2


def test_the_token_bucket_gives_each_token_back_an_hour_after_it_was_spent() -> None:
    bucket = TokenBucket(2)
    start = datetime(2026, 10, 19, 8, tzinfo=LA)

    assert bucket.next_free(start) == start
    bucket.take(start)
    bucket.take(start + timedelta(minutes=10))
    assert bucket.next_free(start + timedelta(minutes=20)) == start + timedelta(hours=1)
    later = start + timedelta(hours=1)
    assert bucket.next_free(later) == later
    bucket.take(later)
    assert bucket.next_free(later) == start + timedelta(hours=1, minutes=10)


# --------------------------------------------------------------------------------------
# What is shown, and the cache
# --------------------------------------------------------------------------------------


async def test_the_answer_reads_with_the_ai_suffix_and_source_ai(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    ai.replies.append(
        '  "Turns the fan on whenever the outdoor temperature rises above\n'
        'twenty five degrees, day or night."  '
    )
    await start(hass, [templated(), WINDOW], AI_ON)
    assert ("Automation: Fan hot (custom logic)", "none") in items(hass, home)

    await past_startup(hass, freezer)

    shown = items(hass, home)
    assert (
        "Turns the fan on whenever the outdoor temperature rises above twenty five (AI)",
        SOURCE_AI,
    ) in shown
    assert ("5:00 PM: on", "parser") in shown


async def test_answers_are_cached_by_config_hash_in_the_store(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    entry = await start(hass, [templated()], AI_ON)
    await past_startup(hass, freezer)
    digest = digest_of(hass, "automation.fan_hot")

    cache = store_of(entry).data.ai_cache
    assert list(cache) == [digest]
    assert cache[digest].text == ANSWER
    assert len(ai.calls) == 1

    # A restart reads the cache: the line shows at once, nothing is asked again.
    await wait(hass, freezer, timedelta(seconds=2))  # the Store's delayed save
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert (f"{ANSWER} (AI)", SOURCE_AI) in items(hass, home)
    await past_startup(hass, freezer)
    assert len(ai.calls) == 1

    # A rebuild of the same config asks nothing.
    await rebuild(hass, freezer)
    assert len(ai.calls) == 1

    # The automation changes: a new answer, and the old one leaves the cache.
    ai.replies.append("Turns the fan on after dark")
    await replace_automations(hass, freezer, [templated(template=DARK)])

    assert len(ai.calls) == 2
    cache = store_of(entry).data.ai_cache
    assert digest not in cache
    assert [entry.text for entry in cache.values()] == ["Turns the fan on after dark"]
    assert ("Turns the fan on after dark (AI)", SOURCE_AI) in items(hass, home)


@pytest.mark.parametrize(
    "reply",
    [HomeAssistantError("the model is offline"), "", None, {"line": "structured"}],
)
async def test_a_failed_answer_is_not_asked_again_until_the_automation_changes(
    hass: HomeAssistant,
    home: dict[str, Any],
    ai: FakeAiTask,
    freezer: Any,
    reply: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ai.replies.append(reply)
    entry = await start(hass, [templated()], AI_ON)
    with caplog.at_level(logging.DEBUG):
        await past_startup(hass, freezer)

    assert "automation.fan_hot" in caplog.text
    assert len(ai.calls) == 1
    assert store_of(entry).data.ai_cache == {}
    assert ("Automation: Fan hot (custom logic)", "none") in items(hass, home)
    await rebuild(hass, freezer)
    await wait(hass, freezer, timedelta(hours=2))
    assert len(ai.calls) == 1
    # A changed automation is asked about again.
    await replace_automations(hass, freezer, [templated(template=DARK)])
    assert len(ai.calls) == 2


async def test_an_ai_task_entity_that_does_not_exist_fails_quietly(
    hass: HomeAssistant, home: dict[str, Any], freezer: Any
) -> None:
    """No `ai_task` action at all: the call fails once, the line stays the parser's."""
    entry = await start(hass, [templated()], AI_ON)

    await past_startup(hass, freezer)

    assert store_of(entry).data.ai_cache == {}
    assert ("Automation: Fan hot (custom logic)", "none") in items(hass, home)


async def test_a_stop_cancels_the_call_in_flight(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    ai.gate = asyncio.Event()
    entry = await start(hass, [templated(), templated("fan_dark", DARK)], AI_ON)
    freezer.tick(AI_STARTUP_DELAY + timedelta(seconds=1))
    async_fire_time_changed(hass)
    for _ in range(5):
        await asyncio.sleep(0)
    assert len(ai.calls) == 1
    store = store_of(entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    ai.gate.set()
    await hass.async_block_till_done()

    assert len(ai.calls) == 1
    assert store.data.ai_cache == {}


async def test_an_automation_gone_since_the_index_was_built_is_not_sent(
    hass: HomeAssistant,
    home: dict[str, Any],
    ai: FakeAiTask,
    freezer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its config is read again for the AI; one that no longer reads is skipped."""
    real_config = ha_adapter.automation_config
    real_references = ha_adapter.automation_references

    def without_hot(hass: HomeAssistant, entity_id: str) -> Mapping[str, Any] | None:
        return None if entity_id == "automation.fan_hot" else real_config(hass, entity_id)

    def references(hass: HomeAssistant) -> list[ha_adapter.AutomationRefs]:
        monkeypatch.setattr(ha_adapter, "automation_config", real_config)
        try:
            return real_references(hass)
        finally:
            monkeypatch.setattr(ha_adapter, "automation_config", without_hot)

    monkeypatch.setattr(ha_adapter, "automation_references", references)
    monkeypatch.setattr(ha_adapter, "automation_config", without_hot)
    await start(hass, [templated(), templated("fan_dark", DARK)], AI_ON)

    await past_startup(hass, freezer)

    assert [blocks["triggers"][0]["value_template"] for blocks in ai.sent_blocks()] == [DARK]


async def test_an_unload_before_home_assistant_started_asks_nothing(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    hass.set_state(CoreState.not_running)
    entry = await start(hass, [templated()], AI_ON)

    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    await past_startup(hass, freezer)

    assert ai.calls == []


async def test_a_coordinator_without_a_store_never_asks(
    hass: HomeAssistant, home: dict[str, Any], ai: FakeAiTask, freezer: Any
) -> None:
    """The AI path needs the Store for its cache; a bare coordinator has none."""
    assert await async_setup_component(hass, "automation", {"automation": [templated()]})
    summary = SummaryCoordinator(hass, "entry", from_options(AI_ON), load_phrases("en"))
    await summary.async_start()
    await past_startup(hass, freezer)
    summary.async_stop()

    assert ai.calls == []


# --------------------------------------------------------------------------------------
# The prompt (pure)
# --------------------------------------------------------------------------------------


def test_the_blocks_take_singular_keys_and_scrub_every_depth() -> None:
    config = {
        "alias": "Mine",
        "trigger": {"trigger": "state", "entity_id": ["a" * 32, "light.desk_lamp", "b" * 32]},
        "condition": {"condition": "state", "entity_id": "c" * 32, "state": "on", "for": 5},
        "actions": [
            {"choose": [{"conditions": [], "sequence": [{"delay": 30, "alias": "Wait"}]}]},
            {"action": "light.turn_on", "target": {"label_id": ["evening", "night"]}},
            {"action": "light.turn_off", "target": {"floor_id": "upstairs", "area_id": "den"}},
            {"action": "light.turn_off", "target": {"label_id": "evening", "area_id": "den"}},
        ],
    }

    found = ai_prompt.blocks(config, {"a" * 32: "light.porch", "c" * 32: "light.hall"})

    assert found == {
        "triggers": [
            {
                "trigger": "state",
                "entity_id": ["light.porch", "light.desk_lamp", ai_prompt.UNKNOWN_ENTITY],
            }
        ],
        "conditions": [{"condition": "state", "entity_id": "light.hall", "state": "on", "for": 5}],
        "actions": [
            {"choose": [{"conditions": [], "sequence": [{"delay": 30}]}]},
            {"action": "light.turn_on", "target": {"label_id": ["label_1", "label_2"]}},
            {"action": "light.turn_off", "target": {"floor_id": "floor_1", "area_id": "area_1"}},
            {"action": "light.turn_off", "target": {"label_id": "label_1", "area_id": "area_1"}},
        ],
    }
    assert ai_prompt.blocks({}, {}) == {"triggers": [], "conditions": [], "actions": []}
    assert ai_prompt.instructions(found).startswith(ai_prompt.PROMPT + "\n\n{")


THIRTEEN = "one two three four five six seven eight nine ten eleven twelve thirteen"


@pytest.mark.parametrize(
    ("answer", "line"),
    [
        ("Turns the fan on at noon.", "Turns the fan on at noon"),
        ('"**Every weekday morning**"', "Every weekday morning"),
        (THIRTEEN, THIRTEEN.rsplit(" ", 1)[0]),
        ("  \n ", None),
        ("...", None),
        (None, None),
        (42, None),
    ],
)
def test_answers_are_trimmed_to_twelve_words(answer: Any, line: str | None) -> None:
    assert ai_prompt.trim(answer) == line
