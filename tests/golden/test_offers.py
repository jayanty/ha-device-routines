"""The golden corpus through the conversion offers (PRD FR-M1, plan 6.2.7, decisions L61, L65).

Every fixture of the corpus is loaded as a real automation next to the integration, each
action target standing for its own device as in `test_lines.py`, and the Schedule
summary's offers are read: exactly the automations a routine can replace exactly are
offered, each named here by its fixture number, and every other automation the parser
reads an action of on a device is named as not offered, with the reason. The match alone
(`conversion.match` per target, as `test_lines.py` reads the corpus) agrees, which also
covers the fixtures whose device triggers cannot load without their integration. A change
of the grammar, of `conversion.match` or of the offer rule that moves one fixture fails.
"""

from __future__ import annotations

from datetime import datetime, time
import json
from typing import Any, Final
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_routines import conversion, repairs
from custom_components.device_routines.const import DOMAIN, INTEGRATION_TITLE
from custom_components.device_routines.models import Days, DeviceContext, EntityRef, RoutineSettings
from custom_components.device_routines.summary import SummaryCoordinator
from tests.golden.test_lines import FILES, TARGET, lines_for

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

TZ: Final = "America/Los_Angeles"

# The exact matches: two daily times on one entity (FR-R1), off a while after any turn on
# (FR-R3). Four of the 51 fixtures.
OFFERED: Final[dict[str, RoutineSettings]] = {
    "automation_16": RoutineSettings("switch.example_switch_4", turn_off_after_min=60),
    "automation_23": RoutineSettings("light.example_light_2", turn_off_after_min=60),
    "synthetic_01": RoutineSettings(
        "fan.example_fan",
        on_time=time(17),
        off_time=time(9),
        days=Days.EVERY_DAY,
    ),
    "synthetic_03": RoutineSettings("fan.example_fan", turn_off_after_min=30),
}

# Every other fixture with an action the parser reads on a device, and why a routine would
# not do exactly what it does: the partial matches and the custom logic alike. The three
# controllers of device triggers (18, 35, 37) do not load in the harness; the match alone
# speaks for them.
NOT_OFFERED: Final[dict[str, str]] = {
    "automation_01": "a one shot start with a catch up trigger and seven guards, one a template",
    "automation_06": "numeric triggers chosen by templates, each action behind a state check",
    "automation_07": "state and numeric triggers on other entities, guarded by a template",
    "automation_08": "a state trigger on another entity, behind a state condition",
    "automation_12": "a turn off of another entity, behind a template condition",
    "automation_14": "a timer finishing, behind a state condition",
    "automation_15": "a motion trigger inside time windows, behind a template",
    "automation_17": "a motion trigger with variables, timers and templates",
    "automation_18": "a device trigger of a button",
    "automation_19": "off after an hour on, plus a second trigger and two conditions",
    "automation_24": "a turn off of another entity, behind a template condition",
    "automation_25": "a delay and a condition between the trigger and the action",
    "automation_26": "a motion trigger behind template windows",
    "automation_27": "an event of another entity, a second action and a template guard",
    "automation_29": "an event entity trigger, behind a docked condition",
    "automation_30": "an event entity trigger choosing between three actions",
    "automation_31": "a pulse: off for three minutes, then on (FR-R8, not a conversion)",
    "automation_35": "a controller of numeric triggers, scripts and timers",
    "automation_36": "a controller following five helpers and a time pattern",
    "automation_37": "a controller of numeric and device triggers and scripts",
    "automation_38": "a window plus a start and a reconnect trigger that catch up",
    "synthetic_02": "a one shot start behind a docked condition",
    "synthetic_04": "a pulse: off for three minutes, then on",
    "synthetic_05": "a sunset close (sun bounds are not a conversion shape)",
    "synthetic_06": "a one shot open on weekends",
    "synthetic_07": "a toggle on a time pattern inside a window",
    "synthetic_08": "a one shot start behind a template",
    "synthetic_09": "a custom event",
    "synthetic_10": "a catch up at start inside a window",
    "synthetic_11": "a repeated toggle",
    "synthetic_12": "a calendar event",
}


def load(path: Any) -> dict[str, Any]:
    config: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))["config"]
    return config


async def start(hass: HomeAssistant, freezer: Any) -> SummaryCoordinator:
    """Load the corpus with one device per action target, then the integration."""
    await hass.config.async_set_time_zone(TZ)
    hass.config.country = "US"
    freezer.move_to(datetime(2026, 10, 19, 8, tzinfo=ZoneInfo(TZ)))
    source = MockConfigEntry(domain="corpus", title="Corpus")
    source.add_to_hass(hass)
    configs = [load(path) for path in FILES]
    targets = sorted({found for config in configs for found in TARGET.findall(json.dumps(config))})
    for entity_id in targets:
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=source.entry_id, identifiers={("corpus", entity_id)}, name=entity_id
        )
        domain, _, object_id = entity_id.partition(".")
        er.async_get(hass).async_get_or_create(
            domain,
            "corpus",
            entity_id,
            device_id=device.id,
            suggested_object_id=object_id,
            config_entry=source,
        )
        hass.states.async_set(entity_id, "off")
    assert await async_setup_component(hass, "automation", {"automation": configs})
    await hass.async_block_till_done()
    entry = MockConfigEntry(domain=DOMAIN, title=INTEGRATION_TITLE, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    summary: SummaryCoordinator = entry.runtime_data.summary
    return summary


def matched(path: Any) -> dict[str, RoutineSettings]:
    """Return `conversion.match` for each action target of a fixture that matches."""
    config = load(path)
    found: dict[str, RoutineSettings] = {}
    for entity_id in sorted(set(TARGET.findall(json.dumps(config.get("actions"))))):
        device = DeviceContext(device_id=f"device_{entity_id}", entities=(EntityRef(entity_id),))
        if (settings := conversion.match(config, device)) is not None:
            found[path.stem] = settings
    return found


async def test_golden_corpus_offers_exactly_the_exact_matches(
    hass: HomeAssistant, freezer: Any
) -> None:
    summary = await start(hass, freezer)
    registry = er.async_get(hass)
    fixture_of = {
        registry.async_get_entity_id("automation", "automation", path.stem): path.stem
        for path in FILES
    }

    offers = summary.conversion_offers()

    # Exactly the exact matches, named by fixture number and counted, each offered once
    # with its Repairs issue.
    assert {offer.automation_id: offer.settings for offer in offers} == OFFERED
    assert len(offers) == 4
    assert sorted(fixture_of[offer.automation_entity_id] for offer in offers) == sorted(OFFERED)
    assert repairs.open_issue_ids(hass) == sorted(
        f"conversion_offer_{offer.automation_entity_id.partition('.')[2]}" for offer in offers
    )
    assert [offer.original_sentence for offer in offers] == [
        offer.routine_sentence for offer in offers
    ]
    # The match alone says the same for the whole corpus, loaded or not.
    assert {stem: settings for path in FILES for stem, settings in matched(path).items()} == (
        OFFERED
    )
    # Every other automation with an action on a device is named as not offered.
    acting = {path.stem for path in FILES if lines_for(path)}
    assert acting - set(OFFERED) == set(NOT_OFFERED)
    assert set(OFFERED) <= acting
