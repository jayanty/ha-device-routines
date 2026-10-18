"""Build B lane 21: the console in Home Assistant (PRD 4.5, plan 6.2.8, decision L62).

The panel is a registered, admin only custom panel that serves the committed bundle and
follows the config entry. The console's recorded payloads (`frontend/test/fixtures/
api.json`, extracted from `docs/api.md`) are proven against the real WebSocket API: every
request example is sent through the harness WebSocket client to the synthetic home that
`docs/api.md` describes, and its answer is compared by shape with the recorded response,
so what the console's own tests feed it is what the integration sends. The table follows
the fixture: a command that `docs/api.md` documents joins it when the fixture is
extracted again. A command whose example needs more than the documented home gets a
seed in `SEEDS`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from homeassistant.components.frontend import DATA_PANELS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import slugify
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.device_routines import panel
from custom_components.device_routines.manager import RoutineManager
from tests.integration.conftest import FAN, LAMP, Clock, Home
from tests.integration.test_websocket_api import add_automations, events_before, timed, window

pytestmark = pytest.mark.parametrize("expected_lingering_timers", [True])

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "frontend" / "test" / "fixtures" / "api.json"
CONSOLE_WORDS = REPO_ROOT / "frontend" / "src" / "translations" / "en.json"
MANIFEST = REPO_ROOT / "custom_components" / "device_routines" / "manifest.json"
PREFIX = "device_routines/"
VERSION = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


def registered(hass: HomeAssistant) -> dict[str, Any] | None:
    """The panel as the frontend's `get_panels` would answer it, or None."""
    found = hass.data.get(DATA_PANELS, {}).get(panel.PANEL_URL_PATH)
    return None if found is None else dict(found.to_response())


# --------------------------------------------------------------------------------------
# The panel
# --------------------------------------------------------------------------------------


async def test_panel_is_registered_admin_only_and_removed_on_unload(
    hass: HomeAssistant, routines: MockConfigEntry
) -> None:
    assert registered(hass) == {
        "component_name": "custom",
        "icon": "mdi:calendar-clock",
        "title": "Device Routines",
        "default_visible": True,
        "config": {
            "_panel_custom": {
                "name": "device-routines-panel",
                "embed_iframe": False,
                "trust_external": False,
                "handle_safe_area": False,
                "module_url": f"/device_routines/static/device-routines-panel.js?v={VERSION}",
            }
        },
        "url_path": "device-routines",
        "require_admin": True,
        "config_panel_domain": None,
        "show_in_sidebar": True,
    }

    assert await hass.config_entries.async_unload(routines.entry_id)
    await hass.async_block_till_done()
    assert registered(hass) is None

    # Set up again in the same run: the panel returns and the static path, which the
    # server cannot register twice, is not registered again.
    assert await hass.config_entries.async_setup(routines.entry_id)
    await hass.async_block_till_done()
    assert registered(hass) is not None


async def test_a_reload_keeps_the_panel_registered_throughout(
    hass: HomeAssistant, routines: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A settings change from the console reloads the entry; the open console stays."""
    present_during_setup: list[bool] = []
    real = panel.async_register_panel

    async def spy(hass: HomeAssistant) -> None:
        present_during_setup.append(registered(hass) is not None)
        await real(hass)

    monkeypatch.setattr(panel, "async_register_panel", spy)

    assert await hass.config_entries.async_reload(routines.entry_id)
    await hass.async_block_till_done()

    assert present_during_setup == [True]
    assert registered(hass) is not None


async def test_a_reload_that_fails_removes_the_panel(
    hass: HomeAssistant, routines: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(hass: HomeAssistant) -> None:
        raise RuntimeError("the store cannot be read")

    monkeypatch.setattr(panel, "async_register_panel", broken)

    await hass.config_entries.async_reload(routines.entry_id)
    await hass.async_block_till_done()

    assert routines.state is ConfigEntryState.SETUP_ERROR
    assert registered(hass) is None


async def test_an_unload_that_fails_keeps_the_panel(
    hass: HomeAssistant, routines: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(*_args: Any) -> bool:
        return False

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", refuse)

    assert not await hass.config_entries.async_unload(routines.entry_id)
    await hass.async_block_till_done()

    assert registered(hass) is not None


async def test_bundle_is_served_with_the_version_query(
    hass: HomeAssistant, routines: MockConfigEntry, hass_client: Any
) -> None:
    found = registered(hass)
    assert found is not None
    url = found["config"]["_panel_custom"]["module_url"]
    client = await hass_client()

    served = await client.get(url)
    body = await served.read()
    missing = await client.get(f"{panel.STATIC_URL}/missing.js")

    assert url == panel.bundle_url(VERSION)
    assert served.status == 200
    assert body == (panel.DIST / panel.BUNDLE).read_bytes()
    assert served.content_type in {"application/javascript", "text/javascript"}
    # No long lived cache: a dev channel deploy keeps the version and changes the bytes.
    assert "max-age" not in served.headers.get("Cache-Control", "")
    assert b'customElements.define("device-routines-panel"' in body
    assert missing.status == 404


def test_the_sidebar_title_is_the_name_the_console_shows() -> None:
    """A custom panel's title has no translation category in the core: it is the name."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    words = json.loads(CONSOLE_WORDS.read_text(encoding="utf-8"))

    assert panel.SIDEBAR_TITLE == manifest["name"] == words["panel"]["title"]
    assert panel.WEB_COMPONENT == "device-routines-panel"
    assert panel.SIDEBAR_ICON == "mdi:calendar-clock"


# --------------------------------------------------------------------------------------
# Every console command against the real WebSocket API
# --------------------------------------------------------------------------------------


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    return "string" if isinstance(value, str) else type(value).__name__


def shape_problems(answer: Any, example: Any, path: str = "$") -> list[str]:
    """Where the answer's shape differs from the example's, empty when it conforms.

    Every key the example shows must be in the answer, with the same JSON type; null on
    either side matches anything (a value that is sometimes absent). A list the example
    fills must be filled, and each of its items must conform to one of the example's
    items. Keys the answer has beyond the example are allowed: the examples may shorten.
    """
    if example is None or answer is None:
        return []
    if isinstance(example, dict):
        return _object_problems(answer, example, path)
    if isinstance(example, list):
        return _list_problems(answer, example, path)
    if _kind(answer) != _kind(example):
        return [f"{path}: {_kind(answer)} where the example has {_kind(example)}"]
    return []


def _object_problems(answer: Any, example: dict[str, Any], path: str) -> list[str]:
    if not isinstance(answer, dict):
        return [f"{path}: {_kind(answer)} where the example has an object"]
    problems: list[str] = []
    for key, value in example.items():
        if key not in answer:
            problems.append(f"{path}.{key}: missing")
        else:
            problems.extend(shape_problems(answer[key], value, f"{path}.{key}"))
    return problems


def _list_problems(answer: Any, example: list[Any], path: str) -> list[str]:
    if not isinstance(answer, list):
        return [f"{path}: {_kind(answer)} where the example has a list"]
    if example and not answer:
        return [f"{path}: empty where the example lists items; seed the home (SEEDS)"]
    problems: list[str] = []
    for index, item in enumerate(answer):
        tried = [shape_problems(item, candidate, f"{path}[{index}]") for candidate in example]
        if tried and all(tried):
            problems.extend(tried[0])
    return problems


@pytest.mark.parametrize(
    ("answer", "example", "problems"),
    [
        ({"a": 1, "b": "x", "extra": True}, {"a": 2, "b": "y"}, []),
        ({"a": "1"}, {"a": 1}, ["$.a: string where the example has number"]),
        ({"a": 1}, {"a": True}, ["$.a: number where the example has boolean"]),
        ({}, {"a": 1}, ["$.a: missing"]),
        ({"a": None}, {"a": {"b": 1}}, []),
        ({"a": {"b": 1}}, {"a": None}, []),
        ([], [{"a": 1}], ["$: empty where the example lists items; seed the home (SEEDS)"]),
        ([{"a": 1}, {"b": "x"}], [{"a": 1}, {"b": "y"}], []),
        ([{"c": 1}], [{"a": 1}, {"a": 1, "b": 1}], ["$[0].a: missing"]),
        ([{"a": "x"}], [{"a": 1}], ["$[0].a: string where the example has number"]),
        ([1], [], []),
        ("x", {"a": 1}, ["$: string where the example has an object"]),
        ({"a": 1}, [1], ["$: dict where the example has a list"]),
    ],
)
def test_the_shape_comparison(answer: Any, example: Any, problems: list[str]) -> None:
    assert shape_problems(answer, example) == problems


@dataclass
class Seeded:
    """The documented home, loaded, with its clock on Monday 2026-10-19 at 4:00 PM."""

    hass: HomeAssistant
    home: Home
    manager: RoutineManager
    freezer: Any


async def lamp_waits_for_cleanup(seeded: Seeded) -> None:
    """The maintenance example cleans up the desk lamp, opted in and out again."""
    await seeded.manager.async_opt_in(seeded.home.lamp)
    await seeded.manager.async_opt_out(seeded.home.lamp)


# What a section's examples need beyond the home docs/api.md describes.
SEEDS: dict[str, Callable[[Seeded], Awaitable[None]]] = {
    "maintenance": lamp_waits_for_cleanup,
}


def console_examples() -> list[Any]:
    """Every request example of the console's fixture, by section and position."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        pytest.param(section, example, content["events"], id=f"{section}[{index}]")
        for section, content in fixture.items()
        for index, example in enumerate(content["examples"])
        if example["request"] is not None
    ]


def with_real_ids(value: Any, ids: dict[str, str]) -> Any:
    """Replace the document's readable device ids (`dev_desk_lamp`) with the home's."""
    if isinstance(value, dict):
        return {key: with_real_ids(item, ids) for key, item in value.items()}
    if isinstance(value, list):
        return [with_real_ids(item, ids) for item in value]
    return ids.get(value, value) if isinstance(value, str) else value


def readable_ids(hass: HomeAssistant, home: Home) -> dict[str, str]:
    """`dev_` plus the slug of each device's name, as docs/api.md writes device ids."""
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), home.source.entry_id)
    return {f"dev_{slugify(device.name)}": device.id for device in devices if device.name}


@pytest.fixture
def at_four(clock: Clock) -> Clock:
    """Monday 16:00, as docs/api.md; set before the client's access token is made."""
    clock.set(clock.at(0, "16:00"))
    return clock


@pytest.mark.parametrize(("section", "example", "events"), console_examples())
async def test_every_console_command_answers_as_its_example(
    hass: HomeAssistant,
    home: Home,
    manager: RoutineManager,
    at_four: Clock,
    freezer: Any,
    hass_ws_client: Any,
    section: str,
    example: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    await window(hass, manager, home, freezer)
    await add_automations(
        hass,
        freezer,
        timed("morning_lamp", "07:00", "light.turn_on", LAMP),
        timed("late_fan_on", "23:00", "switch.turn_on", FAN),
    )
    if seed := SEEDS.get(section):
        await seed(Seeded(hass, home, manager, freezer))
    request = {key: value for key, value in example["request"].items() if key != "id"}
    assert request["type"].startswith(PREFIX)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(with_real_ids(request, readable_ids(hass, home)))
    while (message := await client.receive_json())["type"] != "result":
        pass
    await hass.async_block_till_done()

    assert message["success"], message
    assert shape_problems(message["result"], example["response"]) == []
    if events:
        # A subscription pushes events shaped as the recorded ones.
        await manager.async_opt_in(home.lamp)
        pushed, _ = await events_before(client, {"type": f"{PREFIX}routines/list"})
        assert pushed
        for event in pushed:
            problems = [shape_problems(event, recorded["event"]) for recorded in events]
            assert not all(problems), problems
