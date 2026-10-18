"""The manual change attributor in a running Home Assistant (TECH_SPEC 4.3, PRD 9.3).

Recordings replay through the real event bus and state machine: `automation_triggered`
and `script_started` fill the run map, and a state change of a watched entity is
classified by its context and handed to the override sink. The lookup and the sink are
fakes of the contract (plan Section 4.2); the manager implements both in wave A2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.automation import (
    EVENT_AUTOMATION_TRIGGERED as CORE_AUTOMATION_TRIGGERED,
)
from homeassistant.components.script.const import EVENT_SCRIPT_STARTED as CORE_SCRIPT_STARTED
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STARTED,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Context, CoreState, HomeAssistant
import pytest

from custom_components.device_routines.attribution import (
    EVENT_AUTOMATION_TRIGGERED,
    EVENT_SCRIPT_STARTED,
    MAP_LIMIT,
    MAP_TTL,
    STARTUP_GRACE,
    Attributor,
    RoutineRuntime,
)
from custom_components.device_routines.models import Source

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "attribution"
FAN = "switch.living_room_fan"
LAMP = "light.desk_lamp"
VACUUM = "vacuum.robot_vacuum"
DEVICE = "device-living-room-fan"
START = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)


def load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return loaded


def scenario(name: str) -> dict[str, Any]:
    recording: dict[str, Any] = load("synthetic_contexts.json")["scenarios"][name]
    return recording


# The synthetic person of the app change; registry shaped ids live only in the fixtures.
PERSON: str = scenario("app_change")["events"][0]["context"]["user_id"]


def runtime(**overrides: Any) -> RoutineRuntime:
    """A routine that is active, not paused, respects manual changes and expects off."""
    base = RoutineRuntime(
        device_id=DEVICE,
        active=True,
        paused=False,
        respect_manual=True,
        expected="off",
        inactive_state="off",
    )
    return replace(base, **overrides)


@dataclass(frozen=True)
class Call:
    device_id: str
    on: bool | None
    source: Source
    new_state: str


@dataclass
class FakeLookup:
    """The manager's side of `RoutineLookup`: entity id to the routine's runtime facts."""

    routines: dict[str, RoutineRuntime] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)

    def routine_for(self, entity_id: str) -> RoutineRuntime | None:
        self.asked.append(entity_id)
        return self.routines.get(entity_id)


@dataclass
class FakeSink:
    """The manager's side of `OverrideSink`: records every call in order."""

    calls: list[Call] = field(default_factory=list)

    async def async_set_override(
        self, device_id: str, on: bool | None, source: Source, new_state: str
    ) -> None:
        self.calls.append(Call(device_id, on, source, new_state))


@dataclass
class Harness:
    hass: HomeAssistant
    lookup: FakeLookup
    sink: FakeSink
    attributor: Attributor

    @property
    def sources(self) -> list[Source]:
        return [call.source for call in self.sink.calls]

    @property
    def overrides(self) -> list[bool | None]:
        return [call.on for call in self.sink.calls]

    async def change(self, entity_id: str, state: str, context: Context | None = None) -> None:
        self.hass.states.async_set(entity_id, state, context=context or Context())
        await self.hass.async_block_till_done()

    async def run(self, event_type: str = EVENT_AUTOMATION_TRIGGERED) -> Context:
        """Fire a run event the way the automation and script components do."""
        context = Context()
        self.hass.bus.async_fire(
            event_type, {"name": "Some run", "entity_id": "automation.some_run"}, context=context
        )
        await self.hass.async_block_till_done()
        return context


def context_of(raw: Mapping[str, Any]) -> Context:
    return Context(user_id=raw["user_id"], parent_id=raw["parent_id"], id=raw["id"])


def prime(hass: HomeAssistant, recording: Mapping[str, Any]) -> None:
    """Give each recorded entity the state its first recorded change starts from."""
    for event in recording["events"]:
        data = event["data"]
        if (
            event["event_type"] == EVENT_STATE_CHANGED
            and hass.states.get(data["entity_id"]) is None
        ):
            hass.states.async_set(data["entity_id"], data["old_state"])


async def replay(hass: HomeAssistant, recording: Mapping[str, Any]) -> None:
    """Fire every recorded event, in order, with its recorded context."""
    for event in recording["events"]:
        context = context_of(event["context"])
        data = event["data"]
        if event["event_type"] == EVENT_STATE_CHANGED:
            hass.states.async_set(data["entity_id"], data["new_state"], context=context)
        else:
            hass.bus.async_fire(event["event_type"], data, context=context)
        await hass.async_block_till_done()


def build(hass: HomeAssistant, *routines: tuple[str, RoutineRuntime]) -> Harness:
    lookup = FakeLookup(dict(routines))
    sink = FakeSink()
    return Harness(hass, lookup, sink, Attributor(hass, lookup, sink))


@pytest.fixture
async def harness(hass: HomeAssistant, freezer: Any) -> AsyncIterator[Harness]:
    """A started attributor in a running instance, watching the fan, which is off."""
    freezer.move_to(START)
    hass.states.async_set(FAN, "off")
    built = build(hass, (FAN, runtime()))
    built.attributor.watch(FAN)
    await built.attributor.async_start()
    yield built
    built.attributor.async_stop()


# --------------------------------------------------------------------------------------
# Classification (B44 to B46 of TECH_SPEC 11.2, PRD 9.3)
# --------------------------------------------------------------------------------------


async def test_b44_time_triggered_automation_change_is_automation(hass: HomeAssistant) -> None:
    recording = load("v3_time_triggered.json")
    entity_id = recording["events"][1]["data"]["entity_id"]
    prime(hass, recording)
    harness = build(hass, (entity_id, runtime(expected="off")))
    harness.attributor.watch(entity_id)
    await harness.attributor.async_start()

    await replay(hass, recording)

    # The recorded contexts are parentless and userless, like a wall switch; only the run
    # map tells them apart, and an automation change never touches the override.
    assert harness.sources == [Source(value) for value in recording["expected"]]
    assert harness.overrides == [None, None]
    assert [call.new_state for call in harness.sink.calls] == ["on", "off"]
    harness.attributor.async_stop()


async def test_b45_wall_switch_change_is_device(hass: HomeAssistant) -> None:
    recording = scenario("wall_switch")
    prime(hass, recording)
    harness = build(hass, (FAN, runtime(expected="on")))
    harness.attributor.watch(FAN)
    await harness.attributor.async_start()

    await replay(hass, recording)

    assert harness.sources == [Source(value) for value in recording["expected"]]
    assert harness.sink.calls == [Call(DEVICE, True, Source.DEVICE, "off")]
    harness.attributor.async_stop()


async def test_b46_app_change_is_user(hass: HomeAssistant) -> None:
    recording = scenario("app_change")
    prime(hass, recording)
    harness = build(hass, (FAN, runtime(expected="off")))
    harness.attributor.watch(FAN)
    await harness.attributor.async_start()

    await replay(hass, recording)

    assert harness.sources == [Source(value) for value in recording["expected"]]
    assert harness.sink.calls == [Call(DEVICE, True, Source.USER, "on")]
    harness.attributor.async_stop()


async def test_script_started_contexts_count_as_automation(hass: HomeAssistant) -> None:
    recording = scenario("script_run")
    prime(hass, recording)
    harness = build(hass, (FAN, runtime(expected="off")))
    harness.attributor.watch(FAN)
    await harness.attributor.async_start()

    await replay(hass, recording)

    assert harness.sources == [Source(value) for value in recording["expected"]]
    assert harness.sink.calls == [Call(DEVICE, None, Source.AUTOMATION, "on")]
    harness.attributor.async_stop()


async def test_parent_id_in_the_map_counts(hass: HomeAssistant) -> None:
    recording = scenario("child_context")
    prime(hass, recording)
    harness = build(hass, (FAN, runtime(expected="off")))
    harness.attributor.watch(FAN)
    await harness.attributor.async_start()

    await replay(hass, recording)

    assert harness.sources == [Source(value) for value in recording["expected"]]
    # A parent the map has never seen proves nothing: the change is a person's or the
    # device's, by the user id.
    classify = harness.attributor.classify
    assert classify(Context(parent_id="01M56F1GV2JTRBW7T3YVQ5WWWV")) is Source.DEVICE
    assert classify(Context(user_id=PERSON, parent_id="01M56F1GV218VZFTN7MF3S18PB")) is (
        Source.USER
    )
    harness.attributor.async_stop()


async def test_a_run_wins_over_a_user_id(harness: Harness) -> None:
    """A script a person starts from a dashboard carries their user id, but it is a run."""
    started = Context(user_id=PERSON)
    harness.hass.bus.async_fire(EVENT_SCRIPT_STARTED, {"entity_id": "script.x"}, context=started)
    await harness.hass.async_block_till_done()

    assert harness.attributor.classify(started) is Source.AUTOMATION
    assert harness.attributor.classify(Context(user_id=PERSON)) is Source.USER
    assert harness.attributor.classify(Context()) is Source.DEVICE


def test_the_run_events_are_the_core_ones() -> None:
    assert EVENT_AUTOMATION_TRIGGERED == CORE_AUTOMATION_TRIGGERED
    assert EVENT_SCRIPT_STARTED == CORE_SCRIPT_STARTED


# --------------------------------------------------------------------------------------
# The run map: capped at 10,000 entries, each kept for 24 hours
# --------------------------------------------------------------------------------------


async def test_map_is_capped_and_expires(harness: Harness, freezer: Any) -> None:
    assert MAP_LIMIT == 10_000
    assert timedelta(hours=24) == MAP_TTL
    contexts = [Context() for _ in range(MAP_LIMIT + 1)]
    for context in contexts:
        harness.hass.bus.async_fire(EVENT_AUTOMATION_TRIGGERED, {}, context=context)
    await harness.hass.async_block_till_done()

    classify = harness.attributor.classify
    assert len(harness.attributor._runs) == MAP_LIMIT
    assert classify(contexts[0]) is Source.DEVICE  # the oldest made room for the newest
    assert classify(contexts[1]) is Source.AUTOMATION
    assert classify(contexts[-1]) is Source.AUTOMATION

    freezer.tick(MAP_TTL - timedelta(seconds=1))
    assert classify(contexts[-1]) is Source.AUTOMATION

    freezer.tick(timedelta(seconds=1))
    assert classify(contexts[-1]) is Source.DEVICE
    assert len(harness.attributor._runs) == 0


async def test_a_run_seen_again_is_kept_from_its_latest_sighting(
    harness: Harness, freezer: Any
) -> None:
    # An automation that calls a script: both events carry the same context, later.
    first = await harness.run()
    freezer.tick(timedelta(hours=1))
    second = await harness.run()
    freezer.tick(timedelta(hours=1))
    harness.hass.bus.async_fire(EVENT_SCRIPT_STARTED, {"entity_id": "script.x"}, context=first)
    await harness.hass.async_block_till_done()

    freezer.tick(MAP_TTL - timedelta(hours=1))  # 25 hours after the second run
    classify = harness.attributor.classify
    assert classify(second) is Source.DEVICE
    assert classify(first) is Source.AUTOMATION

    freezer.tick(timedelta(hours=1))
    assert classify(first) is Source.DEVICE


async def test_expired_runs_do_not_classify_state_changes(harness: Harness, freezer: Any) -> None:
    context = await harness.run()
    freezer.tick(MAP_TTL)

    await harness.change(FAN, "on", Context(id=context.id))

    assert harness.sink.calls == [Call(DEVICE, True, Source.DEVICE, "on")]


# --------------------------------------------------------------------------------------
# The startup grace: the first 30 seconds after Home Assistant started only fill the map
# --------------------------------------------------------------------------------------


async def test_first_30_seconds_only_fill_the_map(hass: HomeAssistant, freezer: Any) -> None:
    assert timedelta(seconds=30) == STARTUP_GRACE
    freezer.move_to(START)
    hass.set_state(CoreState.not_running)
    hass.states.async_set(FAN, "off")
    harness = build(hass, (FAN, runtime(expected="off")))
    harness.attributor.watch(FAN)
    await harness.attributor.async_start()

    # Booting: devices report, runs start, nothing is classified.
    run = await harness.run()
    await harness.change(FAN, "on")
    await harness.change(FAN, "off")
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    freezer.tick(STARTUP_GRACE - timedelta(seconds=1))
    await harness.change(FAN, "on")

    assert harness.sink.calls == []
    assert harness.lookup.asked == []

    # From the 30th second on, changes are classified, against a map filled during the grace.
    freezer.tick(timedelta(seconds=1))
    await harness.change(FAN, "off", Context(id=run.id))
    await harness.change(FAN, "on")

    assert harness.sink.calls == [
        Call(DEVICE, None, Source.AUTOMATION, "off"),
        Call(DEVICE, True, Source.DEVICE, "on"),
    ]
    harness.attributor.async_stop()


async def test_a_start_in_a_running_instance_has_no_grace(harness: Harness) -> None:
    """Loaded into a running instance (install, reload): devices are settled already."""
    assert harness.hass.state is CoreState.running

    await harness.change(FAN, "on")

    assert harness.sink.calls == [Call(DEVICE, True, Source.DEVICE, "on")]


async def test_the_grace_waits_for_started_however_long_the_boot_takes(
    hass: HomeAssistant, freezer: Any
) -> None:
    freezer.move_to(START)
    hass.set_state(CoreState.starting)
    hass.states.async_set(FAN, "off")
    harness = build(hass, (FAN, runtime()))
    harness.attributor.watch(FAN)
    await harness.attributor.async_start()

    freezer.tick(timedelta(minutes=10))
    await harness.change(FAN, "on")

    assert harness.sink.calls == []
    harness.attributor.async_stop()


# --------------------------------------------------------------------------------------
# The override rule (PRD FR-R6, 5.2, D21)
# --------------------------------------------------------------------------------------


async def test_manual_change_away_from_expected_sets_override(harness: Harness) -> None:
    # Off window: the wall switch turns the fan on.
    await harness.change(FAN, "on")
    # On window (the routine's own turn on is an automation change): the app turns it off.
    harness.lookup.routines[FAN] = runtime(expected="on")
    await harness.change(FAN, "off", Context(user_id=PERSON))

    assert harness.sink.calls == [
        Call(DEVICE, True, Source.DEVICE, "on"),
        Call(DEVICE, True, Source.USER, "off"),
    ]


async def test_manual_change_back_to_expected_clears_override(harness: Harness) -> None:
    # Two changes in one go: the sink sees them in the order they happened.
    harness.hass.states.async_set(FAN, "on", context=Context())
    harness.hass.states.async_set(FAN, "off", context=Context(user_id=PERSON))
    await harness.hass.async_block_till_done()

    assert harness.overrides == [True, False]
    assert harness.sources == [Source.DEVICE, Source.USER]


async def test_no_override_while_paused(harness: Harness) -> None:
    harness.lookup.routines[FAN] = runtime(paused=True)

    await harness.change(FAN, "on")
    await harness.change(FAN, "off", Context(user_id=PERSON))

    # D21: a pause keeps the routine's hands off; the source is still recorded.
    assert harness.sink.calls == [
        Call(DEVICE, None, Source.DEVICE, "on"),
        Call(DEVICE, None, Source.USER, "off"),
    ]


async def test_no_override_with_respect_manual_off(harness: Harness) -> None:
    harness.lookup.routines[FAN] = runtime(respect_manual=False)

    await harness.change(FAN, "on")

    assert harness.sink.calls == [Call(DEVICE, None, Source.DEVICE, "on")]


async def test_no_override_when_routine_inactive(harness: Harness) -> None:
    harness.lookup.routines[FAN] = runtime(active=False)

    await harness.change(FAN, "on", Context(user_id=PERSON))

    assert harness.sink.calls == [Call(DEVICE, None, Source.USER, "on")]


async def test_no_override_without_an_expected_state(harness: Harness) -> None:
    """A one shot time or a duration alone expects nothing between its actions."""
    harness.lookup.routines[FAN] = runtime(expected=None)

    await harness.change(FAN, "on")

    assert harness.sink.calls == [Call(DEVICE, None, Source.DEVICE, "on")]


async def test_automation_changes_never_touch_the_override(harness: Harness) -> None:
    run = await harness.run()

    await harness.change(FAN, "on", Context(id=run.id))
    await harness.change(FAN, "off", Context(parent_id=run.id))

    assert harness.sink.calls == [
        Call(DEVICE, None, Source.AUTOMATION, "on"),
        Call(DEVICE, None, Source.AUTOMATION, "off"),
    ]


async def test_the_inactive_state_reads_as_off_and_every_other_state_as_on(
    harness: Harness,
) -> None:
    harness.hass.states.async_set(VACUUM, "docked")
    harness.lookup.routines[VACUUM] = runtime(expected="off", inactive_state="docked")
    harness.attributor.watch(VACUUM)

    await harness.change(VACUUM, "cleaning", Context(user_id=PERSON))
    await harness.change(VACUUM, "returning")
    await harness.change(VACUUM, "docked")

    assert harness.sink.calls == [
        Call(DEVICE, True, Source.USER, "cleaning"),
        Call(DEVICE, True, Source.DEVICE, "returning"),
        Call(DEVICE, False, Source.DEVICE, "docked"),
    ]


# --------------------------------------------------------------------------------------
# What counts as a change, and what is watched
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("off", STATE_UNAVAILABLE),
        (STATE_UNAVAILABLE, "on"),
        ("on", STATE_UNKNOWN),
        (STATE_UNKNOWN, "on"),
        (STATE_UNKNOWN, STATE_UNAVAILABLE),
    ],
)
async def test_unknown_and_unavailable_are_not_changes(
    harness: Harness, before: str, after: str
) -> None:
    """A device dropping off or coming back is no one's change; catch up handles a return."""
    await harness.change(FAN, before)
    harness.sink.calls.clear()
    harness.lookup.asked.clear()

    await harness.change(FAN, after, Context(user_id=PERSON))

    assert harness.sink.calls == []
    assert harness.lookup.asked == []


async def test_attribute_updates_new_and_removed_entities_are_not_changes(
    harness: Harness,
) -> None:
    harness.hass.states.async_set(FAN, "off", {"friendly_name": "Fan"}, context=Context())
    await harness.hass.async_block_till_done()
    harness.attributor.watch(LAMP)
    await harness.change(LAMP, "on")
    harness.hass.states.async_remove(LAMP)
    await harness.hass.async_block_till_done()

    assert harness.sink.calls == []
    assert harness.lookup.asked == []


async def test_only_watched_entities_are_classified(harness: Harness) -> None:
    harness.lookup.routines[LAMP] = runtime(device_id="device-desk-lamp")
    harness.hass.states.async_set(LAMP, "off")
    await harness.change(LAMP, "on")
    assert harness.lookup.asked == []

    harness.attributor.watch(LAMP)
    await harness.change(LAMP, "off")
    await harness.change(LAMP, "on")
    harness.attributor.unwatch(LAMP)
    await harness.change(LAMP, "off")
    harness.attributor.unwatch(LAMP)  # unwatching twice is harmless

    assert harness.lookup.asked == [LAMP, LAMP]
    assert harness.sink.calls == [
        Call("device-desk-lamp", False, Source.DEVICE, "off"),
        Call("device-desk-lamp", True, Source.DEVICE, "on"),
    ]


async def test_a_watched_entity_without_a_routine_is_skipped(harness: Harness) -> None:
    harness.attributor.watch(LAMP)
    harness.hass.states.async_set(LAMP, "off")

    await harness.change(LAMP, "on")

    assert harness.lookup.asked == [LAMP]
    assert harness.sink.calls == []


# --------------------------------------------------------------------------------------
# Lifecycle: listeners come and go with start and stop
# --------------------------------------------------------------------------------------


def listener_counts(hass: HomeAssistant) -> dict[str, int]:
    return {str(event_type): count for event_type, count in hass.bus.async_listeners().items()}


@pytest.mark.parametrize("state", [CoreState.running, CoreState.not_running])
async def test_stop_removes_every_listener(
    hass: HomeAssistant, state: CoreState, caplog: pytest.LogCaptureFixture
) -> None:
    hass.set_state(state)
    before = listener_counts(hass)
    harness = build(hass, (FAN, runtime()))
    harness.attributor.watch(FAN)
    harness.attributor.watch(FAN)  # watching twice subscribes once
    await harness.attributor.async_start()
    await harness.attributor.async_start()  # starting twice subscribes once
    assert listener_counts(hass) != before

    harness.attributor.async_stop()

    assert listener_counts(hass) == before
    run = await harness.run()
    assert harness.attributor.classify(run) is Source.DEVICE
    hass.states.async_set(FAN, "on")
    await hass.async_block_till_done()
    assert harness.lookup.asked == []
    assert "Unable to remove" not in caplog.text


async def test_stop_after_the_started_event_logs_nothing(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    # The started event also runs the harness's own one time listeners, so only the event
    # types the attributor listens to are compared.
    ours = (EVENT_AUTOMATION_TRIGGERED, EVENT_SCRIPT_STARTED, str(EVENT_STATE_CHANGED))
    hass.set_state(CoreState.not_running)
    before = [listener_counts(hass).get(event_type, 0) for event_type in ours]
    harness = build(hass, (FAN, runtime()))
    harness.attributor.watch(FAN)
    await harness.attributor.async_start()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    caplog.clear()
    harness.attributor.async_stop()

    assert [listener_counts(hass).get(event_type, 0) for event_type in ours] == before
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == []


async def test_watching_before_the_start_subscribes_at_the_start(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set(FAN, "off")
    harness = build(hass, (FAN, runtime()))
    harness.attributor.watch(FAN)
    await harness.change(FAN, "on")
    assert harness.lookup.asked == []

    await harness.attributor.async_start()
    await harness.change(FAN, "off")

    assert harness.sink.calls == [Call(DEVICE, False, Source.DEVICE, "off")]
    harness.attributor.async_stop()


async def test_a_restart_of_the_attributor_watches_the_same_entities(harness: Harness) -> None:
    harness.attributor.async_stop()
    await harness.attributor.async_start()

    await harness.change(FAN, "on")

    assert harness.sink.calls == [Call(DEVICE, True, Source.DEVICE, "on")]
