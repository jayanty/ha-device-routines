"""Contract tests of Build A (plan Section 4.6, A4.1): the lanes built in parallel agree.

Three contracts, one part each:

1. `compiler.compile` against the installed blueprint. For every domain profile and option
   combination (hypothesis over `tests/unit/strategies.py`), the compiled inputs are the
   blueprint's inputs, key for key in order, each value of the type its selector holds,
   and the automation entry the manager writes validates the way the core validates a
   `use_blueprint` automation. The hand written `inputs()` mirror of the blueprint tests
   equals `compile` for the same settings.
2. One service layer (PRD P16). An AST check of every surface module: the device page
   platforms and their base classes, the actions, the WebSocket commands, the triggers,
   the conditions and the Repairs fix flows. The rule is written out in `P16_RULE`.
3. The round trip of PRD 12. For every valid settings, the Schedule sentence of the
   compiled routine equals the sentence generated from the settings: through the summary's
   decompile of the written automation, through the manager in a running Home Assistant
   (before and after a reload), and through the summary's parser alone, without the
   manager's item.

A disagreement found here is pinned as a strict xfail naming the module and the fix, not
worked around. Every name is generic and every id synthetic (CLAUDE.md Section 6).
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, fields, replace
from datetime import time, timedelta
import importlib
import importlib.util
import inspect
from pathlib import Path
import re
from typing import Any, Final, cast

from homeassistant.components.automation.config import (
    AUTOMATION_BLUEPRINT_SCHEMA,
    ValidationStatus,
    async_validate_config_item,
)
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.util.yaml import parse_yaml
from hypothesis import HealthCheck, Phase, given, settings as hypothesis_settings, strategies as st
import probatio as vol
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.device_routines import (
    compiler,
    ha_adapter,
    markers,
    summary as summary_module,
)
from custom_components.device_routines.domains import PROFILES, profile_for
from custom_components.device_routines.manager import RoutineManager
from custom_components.device_routines.models import (
    Days,
    DomainProfile,
    Option,
    Pulse,
    RoutineSettings,
    Status,
    TimeKind,
    Weekday,
)
from custom_components.device_routines.nextrun import routine_lines
from custom_components.device_routines.sentence import Writer, load_phrases
from custom_components.device_routines.summary import (
    DEBOUNCE_SECONDS as SUMMARY_DEBOUNCE,
    KIND_DETACHED,
    KIND_ROUTINE,
)
from tests.blueprint import conftest as mirror
from tests.blueprint.conftest import installed_blueprint  # noqa: F401  # a fixture
from tests.integration.conftest import (
    FAN,
    GARAGE,
    LAMP,
    Home,
    file_entry,
    flush,
    give_routine,
    save_entry,
)
from tests.unit import strategies

COMPONENT: Final = Path(compiler.__file__).parent
PACKAGE: Final = "custom_components.device_routines"
BLUEPRINT_SOURCE: Final = COMPONENT / "blueprints" / "device_routine.yaml"
DEVICE_ID: Final = "contract_device_living_room_fan"
DEVICE_NAME: Final = "Living room fan"
AUTOMATION_ENTITY: Final = "automation.routine_living_room_fan"
PHRASES: Final = load_phrases("en")
WRITER: Final = Writer(PHRASES, "12h")
WEEKDAY_ORDER: Final = tuple(day.value for day in Weekday)


def harness(examples: int) -> hypothesis_settings:
    """Hypothesis settings for a run on the harness: one Home Assistant for every example.

    No shrinking: an example costs a write, a reload and a rebuild, and the falsifying
    example is reported as drawn.
    """
    return hypothesis_settings(
        max_examples=examples,
        deadline=None,
        phases=(Phase.explicit, Phase.reuse, Phase.generate),
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )


def loose_routines() -> st.SearchStrategy[tuple[DomainProfile, str | None, RoutineSettings]]:
    """Draw a profile, its device class and valid settings in any form a caller may send.

    Without zones: a time with an offset next to one without breaks the manager, which
    `test_the_manager_holds_a_time_with_an_offset_in_the_form_it_reads_back` pins.
    """
    return strategies.profile_cases().flatmap(
        lambda case: strategies.loose_settings(case[0], zones=False).map(
            lambda settings: (*case, settings)
        )
    )


def routine_entry(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Return the `automations.yaml` entry the manager writes for a new routine.

    As `RoutineManager._entry_config` builds it: the generated alias and description, M1
    from the `device_id` input and M2 with the inputs.
    """
    shown = markers.presentation(DEVICE_NAME, PHRASES)
    return {
        "description": shown.description,
        "alias": shown.alias,
        "id": markers.automation_id(inputs["device_id"]),
        "use_blueprint": {"path": markers.BLUEPRINT_PATH, "input": dict(inputs)},
    }


def shipped_blueprint() -> Blueprint:
    """The shipped blueprint, as the core loads it."""
    data = parse_yaml(BLUEPRINT_SOURCE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return Blueprint(data, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)


SHIPPED: Final = shipped_blueprint()


@pytest.fixture
def expected_lingering_timers() -> bool:
    """A routine's daily time triggers stay scheduled when a test ends; that is no leak."""
    return True


# ======================================================================================
# 1. compile() against the installed blueprint
# ======================================================================================

REFS: Final = compiler.HelperRefs(
    DEVICE_ID,
    timer_entity="timer.routine_living_room_fan",
    override_entity="switch.living_room_fan_manual_override",
    paused_until_entity="datetime.living_room_fan_paused_until",
)
WINDOW: Final = RoutineSettings(FAN, on_time=time(17), off_time=time(9), turn_off_after_min=30)
_CLOCK: Final = re.compile(r"\d{2}:\d{2}:\d{2}")


def _entity_domains(options: Mapping[str, Any]) -> set[str]:
    """Return the domains an entity selector's filters offer; empty means any."""
    found: set[str] = set()
    for item in options.get("filter") or []:
        domain = item.get("domain")
        found.update([domain] if isinstance(domain, str) else domain or [])
    return found


def _kind_problems(kind: str, options: Mapping[str, Any], value: Any) -> list[str]:
    """Return how a value differs from what its selector holds (plan Section 4.2 types).

    The core coerces some values (a number selector takes "5", a boolean selector takes
    "on") and ignores an entity selector's `filter`, which only the form applies; the
    contract pins the plain YAML types, so both are checked here as well.
    """
    match kind:
        case "boolean":
            ok = type(value) is bool
        case "number":
            ok = (
                type(value) is int and (value - options.get("min", 0)) % options.get("step", 1) == 0
            )
        case "time":
            ok = isinstance(value, str) and _CLOCK.fullmatch(value) is not None
        case "text":
            ok = isinstance(value, str) and bool(value)
        case "select" if options.get("multiple"):
            ok = (
                isinstance(value, list)
                and value == [day for day in WEEKDAY_ORDER if day in value]
                and len(set(value)) == len(value)
            )
        case "select":
            # A single select (a bound's kind, schema 2) holds one of its option values.
            offered = [
                item["value"] if isinstance(item, dict) else item for item in options["options"]
            ]
            ok = isinstance(value, str) and value in offered
        case "entity":
            domains = _entity_domains(options)
            ok = isinstance(value, str) and (not domains or value.partition(".")[0] in domains)
        case "condition":
            ok = isinstance(value, list) and all(isinstance(item, dict) for item in value)
        case _:
            return [f"a {kind} selector the contract does not know"]
    return [] if ok else [f"{value!r} is not what a {kind} selector holds"]


def selector_problems(definitions: Mapping[str, Any], inputs: Mapping[str, Any]) -> list[str]:
    """Return every input that is unknown, missing or refused by its selector."""
    problems = [f"{key}: not an input of the blueprint" for key in inputs if key not in definitions]
    for key, definition in definitions.items():
        if key not in inputs:
            problems.append(f"{key}: not written")
            continue
        config = definition["selector"]
        ((kind, options),) = config.items()
        # Every concrete selector validates a value when called; the base class does not say.
        check = cast("Callable[[Any], Any]", selector.selector(config))
        try:
            check(inputs[key])
        except vol.Invalid as err:
            problems.append(f"{key}: {err}")
            continue
        problems += [
            f"{key}: {problem}" for problem in _kind_problems(kind, options or {}, inputs[key])
        ]
    return problems


async def automation_problems(hass: HomeAssistant, entry: dict[str, Any]) -> list[str]:
    """Validate an entry as the core validates a `use_blueprint` automation.

    `async_validate_config_item` is what the automation editor and a reload run: it loads
    the blueprint, checks the inputs are there, substitutes them and validates the
    result with the automation schema, its triggers, conditions and actions.
    """
    try:
        validated = await async_validate_config_item(hass, entry["id"], entry)
    except (vol.Invalid, HomeAssistantError) as err:
        return [f"automation: {err}"]
    assert validated is not None
    if validated.validation_status is not ValidationStatus.OK:
        return [f"automation: {validated.validation_status}: {validated.validation_error}"]
    return []


async def blueprint_problems(hass: HomeAssistant, entry: dict[str, Any]) -> list[str]:
    """Return why an entry is not a routine the installed blueprint runs; empty if it is."""
    blueprint = await async_get_blueprints(hass).async_get_blueprint(markers.BLUEPRINT_PATH)
    inputs = entry["use_blueprint"]["input"]
    return [*selector_problems(blueprint.inputs, inputs), *await automation_problems(hass, entry)]


# Every domain profile, a refused device class included, as `strategies.profile_cases`.
PROFILE_CASES: Final = [
    pytest.param(domain, device_class, id=f"{domain}-{device_class}")
    for domain in sorted(PROFILES)
    for device_class in strategies.device_classes(domain)
]


@pytest.mark.parametrize(("domain", "device_class"), PROFILE_CASES)
@harness(10)
@given(data=st.data(), refs=strategies.helper_refs())
async def test_compiled_inputs_validate_against_the_installed_blueprint(
    hass: HomeAssistant,
    installed_blueprint: Path,  # noqa: F811  # the fixture imported above
    domain: str,
    device_class: str | None,
    data: st.DataObject,
    refs: compiler.HelperRefs,
) -> None:
    profile = profile_for(domain, device_class)
    assert profile is not None
    settings = data.draw(strategies.routine_settings(profile), label="settings")
    inputs = compiler.compile(settings, profile, refs).inputs
    entry = routine_entry(inputs)

    assert tuple(inputs) == compiler.INPUT_KEYS
    assert markers.is_owned(entry)
    assert await blueprint_problems(hass, entry) == []


def _supports(profile: DomainProfile, option: Option) -> bool:
    needs_on = option in {Option.ON_TIME, Option.TURN_BACK_ON_AFTER, Option.PULSE}
    return option in profile.options and (profile.on_action is not None or not needs_on)


def every_option(profile: DomainProfile) -> list[RoutineSettings]:
    """Return settings that turn on every option the profile has, at the selectors' bounds.

    D27 allows one duration at a time, and a weekly schedule takes no times, so there are
    three: a window with Turn off after, a window with Turn back on after and a pulse, and
    a weekly schedule; each where the profile supports it.
    """
    window = RoutineSettings(
        f"{profile.domain}.living_room_fan",
        on_time=time(23, 59, 59) if _supports(profile, Option.ON_TIME) else None,
        off_time=time(0, 0, 30),
        days=Days.SOME_DAYS,
        day_set=frozenset({Weekday.MON, Weekday.WED, Weekday.SUN}),
        catch_up=False,
        late_start_window_min=compiler.MAX_LATE_START_MIN,
        respect_manual=False,
        extra_conditions=strategies.EXAMPLE_CONDITIONS,
        docked_guard=False,
    )
    found: list[RoutineSettings] = []
    if _supports(profile, Option.TURN_OFF_AFTER):
        found.append(replace(window, turn_off_after_min=compiler.MAX_DURATION_MIN))
    if _supports(profile, Option.TURN_BACK_ON_AFTER):
        pulse = Pulse(time(12), compiler.MAX_DURATION_MIN, compiler.MAX_DURATION_MIN)
        found.append(replace(window, turn_back_on_after_min=compiler.MAX_DURATION_MIN, pulse=pulse))
    weekly = replace(
        window,
        on_time=None,
        off_time=None,
        days=Days.WEEKLY_SCHEDULE,
        schedule_entity="schedule.routine_living_room_fan",
    )
    return [*found, weekly] if found else [window, weekly]


@pytest.mark.parametrize(("domain", "device_class"), PROFILE_CASES)
async def test_every_option_at_once_validates_against_the_installed_blueprint(
    hass: HomeAssistant,
    installed_blueprint: Path,  # noqa: F811  # the fixture imported above
    domain: str,
    device_class: str | None,
) -> None:
    profile = profile_for(domain, device_class)
    assert profile is not None
    for settings in every_option(profile):
        assert compiler.validate(settings, profile) == []
        entry = routine_entry(compiler.compile(settings, profile, REFS).inputs)
        assert await blueprint_problems(hass, entry) == [], settings


async def test_the_compiler_and_the_installed_blueprint_name_the_same_inputs(
    hass: HomeAssistant,
    installed_blueprint: Path,  # noqa: F811  # the fixture imported above
) -> None:
    blueprint = await async_get_blueprints(hass).async_get_blueprint(markers.BLUEPRINT_PATH)
    definitions = blueprint.inputs
    defaults = {key: item["default"] for key, item in definitions.items() if "default" in item}

    assert tuple(definitions) == compiler.INPUT_KEYS
    assert set(definitions) - set(defaults) == compiler.REQUIRED_KEYS
    assert defaults == dict(compiler.INPUT_DEFAULTS)
    # What `decompile` assumes for an omitted input is what the blueprint fills in.
    written = compiler.compile(RoutineSettings(FAN), PROFILES["switch"], REFS).inputs
    required = {key: written[key] for key in compiler.REQUIRED_KEYS}
    assert compiler.decompile(required) == RoutineSettings(FAN)
    text = blueprint.yaml()
    for name in (compiler.EVENT_ACTION_SKIPPED, compiler.EVENT_TIMER_CAUGHT_UP):
        assert name in text
    for sentinel in (
        compiler.UNUSED_TIMER,
        compiler.UNUSED_SCHEDULE,
        compiler.UNUSED_SWITCH,
        compiler.UNUSED_DATETIME,
    ):
        assert sentinel in text


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"turn_off_after_min": "30"}, id="minutes as text"),
        pytest.param({"turn_off_after_min": 1441}, id="minutes above the selector"),
        pytest.param({"turn_off_after_min": 2.5}, id="minutes off the step"),
        pytest.param({"late_start_window_min": 181}, id="late window above the selector"),
        pytest.param({"catch_up": "on"}, id="flag as text"),
        pytest.param({"on_time": "17:00"}, id="time without seconds"),
        pytest.param({"on_time": "25:00:00"}, id="time out of range"),
        pytest.param({"days_start": ["monday"]}, id="day that is not an option"),
        pytest.param({"days_start": ["tue", "mon"]}, id="days out of order"),
        pytest.param({"target_entity": "sensor.living_room_fan"}, id="target outside the filter"),
        pytest.param({"timer_entity": "switch.living_room_fan"}, id="timer outside the filter"),
        pytest.param({"on_action": ""}, id="empty action"),
        pytest.param({"extra_conditions": [{"condition": "nonsense"}]}, id="bad condition"),
        pytest.param({"extra_conditions": {"condition": "state"}}, id="condition not a list"),
        pytest.param({"unknown_input": 1}, id="unknown input"),
        pytest.param({"device_id": None}, id="missing required input"),
    ],
)
async def test_the_blueprint_check_refuses_what_the_form_would_not_write(
    hass: HomeAssistant,
    installed_blueprint: Path,  # noqa: F811  # the fixture imported above
    broken: dict[str, Any],
) -> None:
    inputs = dict(compiler.compile(WINDOW, PROFILES["switch"], REFS).inputs)
    entry = routine_entry(inputs)
    assert await blueprint_problems(hass, entry) == []

    changed = {**inputs, **broken}
    entry["use_blueprint"]["input"] = {k: v for k, v in changed.items() if v is not None}
    assert await blueprint_problems(hass, entry)


async def test_the_core_check_validates_the_substituted_automation(
    hass: HomeAssistant,
    installed_blueprint: Path,  # noqa: F811  # the fixture imported above
) -> None:
    """An input every selector accepts but the rendered automation refuses still fails."""
    blueprint = await async_get_blueprints(hass).async_get_blueprint(markers.BLUEPRINT_PATH)
    inputs = {
        **compiler.compile(WINDOW, PROFILES["switch"], REFS).inputs,
        "off_action": "switch turn off",
    }

    assert selector_problems(blueprint.inputs, inputs) == []
    assert await automation_problems(hass, routine_entry(inputs))


def mirror_overrides(
    settings: RoutineSettings,
    profile: DomainProfile,
    device_class: str | None,
    refs: compiler.HelperRefs,
) -> dict[str, Any]:
    """Return what a blueprint test passes `inputs()` for these settings: primary inputs only.

    `inputs()` derives the switches (`*_enabled`, the four sun flags), `crosses_midnight`,
    `days_end`, `late_window_end` and `late_sun_offset` itself, as TECH_SPEC 3.3 derives
    them; those are what the comparison with `compile` is about.
    """
    given: dict[str, Any] = {
        **mirror.target_inputs(profile.domain, settings.target_entity, device_class),
        "device_id": refs.device_id,
        "days_start": [day.value for day in Weekday if day in settings.effective_days],
        "turn_off_after_min": settings.turn_off_after_min,
        "turn_back_on_after_min": settings.turn_back_on_after_min,
        "catch_up": settings.catch_up,
        "late_start_window_min": settings.late_start_window_min,
        "respect_manual": settings.respect_manual,
        "override_entity": refs.override_entity,
        "paused_until_entity": refs.paused_until_entity,
        "docked_guard": settings.docked_guard,
        "extra_conditions": [dict(condition) for condition in settings.extra_conditions],
    }
    if settings.on_time is not None:
        given["on_time"] = settings.on_time.isoformat()
    if settings.off_time is not None:
        given["off_time"] = settings.off_time.isoformat()
    if settings.on_kind is not TimeKind.TIME:
        given["on_kind"] = settings.on_kind.value
        given["on_sun_offset"] = mirror.sun_offset(settings.on_sun_offset_min)
    if settings.off_kind is not TimeKind.TIME:
        given["off_kind"] = settings.off_kind.value
        given["off_sun_offset"] = mirror.sun_offset(settings.off_sun_offset_min)
    if settings.days is Days.WEEKLY_SCHEDULE:
        given["schedule_entity"] = settings.schedule_entity
    if settings.turn_off_after_min or settings.turn_back_on_after_min:
        given["timer_entity"] = refs.timer_entity
    if settings.pulse is not None:
        given["pulse_at"] = settings.pulse.at.isoformat()
        given["pulse_minutes"] = settings.pulse.minutes
        given["pulse_min_steady_min"] = settings.pulse.min_steady_min
    return given


def _shape(value: Any) -> Any:
    """Return a value's type tree, so `1` and `True` or `"a"` and `["a"]` never match."""
    if isinstance(value, list):
        return ("list", [_shape(item) for item in value])
    if isinstance(value, dict):
        return ("dict", {key: _shape(item) for key, item in value.items()})
    return type(value).__name__


@hypothesis_settings(max_examples=300, deadline=None)
@given(case=strategies.routines(), refs=strategies.helper_refs())
def test_the_blueprint_tests_mirror_equals_compile(
    case: tuple[DomainProfile, str | None, RoutineSettings], refs: compiler.HelperRefs
) -> None:
    profile, device_class, settings = case
    compiled = dict(compiler.compile(settings, profile, refs).inputs)
    written = mirror.inputs(**mirror_overrides(settings, profile, device_class, refs))

    assert list(written) == list(compiled)
    assert written == compiled
    assert _shape(written) == _shape(compiled)


def test_the_blueprint_tests_name_the_compilers_constants() -> None:
    assert mirror.INPUT_KEYS == compiler.INPUT_KEYS
    assert mirror.EVENT_ACTION_SKIPPED == compiler.EVENT_ACTION_SKIPPED
    assert mirror.EVENT_TIMER_CAUGHT_UP == compiler.EVENT_TIMER_CAUGHT_UP
    assert mirror.UNUSED_TIMER == compiler.UNUSED_TIMER
    assert mirror.UNUSED_SCHEDULE == compiler.UNUSED_SCHEDULE
    assert mirror.UNUSED_SWITCH == compiler.UNUSED_SWITCH
    assert mirror.UNUSED_DATETIME == compiler.UNUSED_DATETIME
    assert mirror.WEEKDAYS == WEEKDAY_ORDER
    # The mirror's defaults are the compiler's for the empty routine of the mirror's switch.
    empty = compiler.compile(
        RoutineSettings(mirror.SWITCH), PROFILES["switch"], compiler.HelperRefs(mirror.DEVICE_ID)
    )
    assert mirror.inputs() == dict(empty.inputs)


# ======================================================================================
# 2. One service layer (PRD P16)
# ======================================================================================

P16_RULE: Final = """
A surface module is a device page platform or its base classes, the actions, the WebSocket
commands, the integration triggers and conditions, or the Repairs fix flows. In a surface:

S1  Imports from this integration bind only types, constants and the shared entry points
    in ENTRY_POINTS; no function of another module, no private name, no other surface's
    helper.
S2  An attribute read off a bound module of this integration is a type, a constant or an
    entry point, the same as S1.
S3  The manager is reached only through its public API (a public member of
    RoutineManager); the summary only through its read API (SUMMARY_READ_API).
S4  No rule lives in a surface: it names no `Status` member and compares no `status`
    (what a status means is the service layer's), it branches on no routine setting (no
    comparison and no `if`, conditional or comprehension test reads a RoutineSettings field
    off a `.settings`; rendering one is fine), and an `available` property reads no
    RoutineView (the manager's `unavailable_reason` decides availability).
S5  Every entry point of a surface (an entity's write method, an action handler, a
    WebSocket command, a trigger's runner, a condition's check, a fix) reaches the
    manager, `maintenance.async_run` or the settings service.
"""

PLATFORMS: Final = (
    "binary_sensor",
    "button",
    "datetime",
    "number",
    "select",
    "sensor",
    "switch",
    "time",
)
SURFACES: Final = (
    *PLATFORMS,
    "entity",
    "services",
    "websocket_api",
    "trigger",
    "condition",
    "repairs",
)

# Functions a surface may import from this integration (S1, S2). The service entry points:
ENTRY_POINTS: Final = frozenset(
    {
        ("maintenance", "async_run"),
        ("settings", "from_options"),
        ("settings", "validate"),
        # Naming and plumbing, not behavior: a Schedule sensor's unique id, the platform
        # base helpers every device page control uses, and the open issue list the hub
        # Problem sensor shows (the catalog half of repairs.py, which the manager also reads).
        ("summary", "schedule_unique_id"),
        ("entity", "async_setup_device_entities"),
        ("entity", "linked_device_info"),
        ("repairs", "open_issue_ids"),
    }
)
SERVICE_CALLS: Final = frozenset(
    {("maintenance", "async_run"), ("settings", "from_options"), ("settings", "validate")}
)
SUMMARY_READ_API: Final = frozenset(
    {
        "summaries",
        "async_add_listener",
        "async_add_change_listener",
        "async_set_sensor_adder",
        "day_schedule",
    }
)
WRITE_METHODS: Final = frozenset(
    {
        "async_turn_on",
        "async_turn_off",
        "async_set_value",
        "async_set_native_value",
        "async_select_option",
        "async_press",
    }
)
# How a surface holds the manager and the summary (`Receivers`): a parameter annotated with
# one of these types, the runtime data's attribute, the attributes the base classes keep,
# the loaded entry lookups, and any name assigned from one of those.
_MANAGER_TYPES: Final = frozenset({"RoutineManager", "FixTarget", "MaintenanceTarget"})
_SUMMARY_TYPES: Final = frozenset({"SummaryCoordinator"})
_MANAGER_ATTRIBUTES: Final = frozenset({"manager", "_manager"})
_SUMMARY_ATTRIBUTES: Final = frozenset({"_summary", "_coordinator"})
_MANAGER_LOOKUPS: Final = frozenset({"_manager", "_loaded_manager", "loaded_manager"})


def _manager_api() -> frozenset[str]:
    """Return RoutineManager's public members, the attributes `__init__` sets included."""
    tree = ast.parse((COMPONENT / "manager.py").read_text(encoding="utf-8"))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RoutineManager"
    )
    assigned = {
        target.attr
        for node in ast.walk(cls)
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }
    members = set(dir(RoutineManager)) | assigned
    return frozenset(name for name in members if not name.startswith("_"))


MANAGER_API: Final = _manager_api()


@dataclass(frozen=True, slots=True)
class Finding:
    """One place a surface breaks the rule."""

    module: str
    line: int
    rule: str
    text: str

    def __str__(self) -> str:
        return f"{self.module}.py:{self.line}: {self.rule}: {self.text}"


def _type_names(annotation: ast.expr | None) -> set[str]:
    """Return every name an annotation mentions, quoted ones included."""
    if annotation is None:
        return set()
    found: set[str] = set()
    for sub in ast.walk(annotation):
        if isinstance(sub, ast.Name):
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            found.update(re.findall(r"\w+", sub.value))
    return found


_SCOPES: Final = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda


def _own_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """Yield the nodes of a scope's own code, not those of a nested function or class."""
    for child in ast.iter_child_nodes(scope):
        yield child
        if not isinstance(child, _SCOPES | ast.ClassDef):
            yield from _own_nodes(child)


def _bindings(scope: ast.AST) -> list[tuple[str, ast.expr]]:
    """Return the plain `name = value` bindings of a scope's own code."""
    found: list[tuple[str, ast.expr]] = []
    for node in _own_nodes(scope):
        if isinstance(node, ast.Assign):
            found += [(t.id, node.value) for t in node.targets if isinstance(t, ast.Name)]
        elif (
            isinstance(node, ast.AnnAssign | ast.NamedExpr)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            found.append((node.target.id, node.value))
    return found


@dataclass
class Receivers:
    """The names that hold the manager, the summary or the runtime data in one scope."""

    managers: set[str] = field(default_factory=set)
    summaries: set[str] = field(default_factory=set)
    runtimes: set[str] = field(default_factory=set)

    def inner(self, scope: ast.AST) -> Receivers:
        """Return a nested scope's names: the enclosing ones unless shadowed, its own."""
        parameters: list[ast.arg] = []
        if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            arguments = scope.args
            parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        bindings = _bindings(scope)
        shadowed = {arg.arg for arg in parameters} | {name for name, _ in bindings}
        found = Receivers(
            self.managers - shadowed, self.summaries - shadowed, self.runtimes - shadowed
        )
        for arg in parameters:
            names = _type_names(arg.annotation)
            if names & _MANAGER_TYPES:
                found.managers.add(arg.arg)
            if names & _SUMMARY_TYPES:
                found.summaries.add(arg.arg)
        size = -1
        while size != (size := len(found.managers) + len(found.summaries) + len(found.runtimes)):
            for name, value in bindings:
                if found.is_manager(value):
                    found.managers.add(name)
                if found.is_summary(value):
                    found.summaries.add(name)
                if found.is_runtime(value):
                    found.runtimes.add(name)
        return found

    def is_runtime(self, node: ast.expr) -> bool:
        """`entry.runtime_data`, or a name that holds it."""
        if isinstance(node, ast.Name):
            return node.id in self.runtimes
        return isinstance(node, ast.Attribute) and node.attr == "runtime_data"

    def is_manager(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.managers
        if isinstance(node, ast.Attribute):
            return node.attr in _MANAGER_ATTRIBUTES
        if isinstance(node, ast.Call):
            return isinstance(node.func, ast.Name) and node.func.id in _MANAGER_LOOKUPS
        return False

    def is_summary(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.summaries
        if isinstance(node, ast.Attribute):
            return node.attr in _SUMMARY_ATTRIBUTES or (
                node.attr == "summary"
                and (self.is_runtime(node.value) or self.is_manager(node.value))
            )
        return False


def _reads(node: ast.AST, attribute: str) -> bool:
    """Tell whether an expression reads an attribute of that name anywhere inside it."""
    return any(isinstance(sub, ast.Attribute) and sub.attr == attribute for sub in ast.walk(node))


# A routine setting: a RoutineSettings field, or one of its derived properties.
ROUTINE_SETTINGS: Final = frozenset(item.name for item in fields(RoutineSettings)) | {
    "effective_days",
    "end_days",
    "crosses_midnight",
    "has_on",
    "has_off",
    "nominal_on",
    "nominal_off",
}


def _reads_setting(node: ast.AST) -> bool:
    """Tell whether an expression reads a routine setting off a `.settings`."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Attribute)
            and sub.attr in ROUTINE_SETTINGS
            and isinstance(sub.value, ast.Attribute)
            and sub.value.attr == "settings"
        ):
            return True
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "getattr"
            and sub.args
            and isinstance(sub.args[0], ast.Attribute)
            and sub.args[0].attr == "settings"
        ):
            return True
    return False


def _tests(tree: ast.AST) -> Iterator[ast.expr]:
    """Yield every branch test: `if`, `while`, conditional expressions, comprehension ifs."""
    for node in ast.walk(tree):
        if isinstance(node, ast.If | ast.While | ast.IfExp):
            yield node.test
        elif isinstance(node, ast.comprehension):
            yield from node.ifs


@dataclass
class Surface:
    """One surface module, parsed, with what it binds from this integration."""

    name: str
    source: str
    tree: ast.Module = field(init=False)
    # Local name to (module, attribute); attribute None for a bound module.
    bound: dict[str, tuple[str, str | None]] = field(init=False, default_factory=dict)
    findings: list[Finding] = field(init=False, default_factory=list)
    scopes: dict[int, Receivers] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.tree = ast.parse(self.source)

        def visit(node: ast.AST, current: Receivers) -> None:
            if isinstance(node, _SCOPES):
                current = current.inner(node)
            self.scopes[id(node)] = current
            for child in ast.iter_child_nodes(node):
                visit(child, current)

        visit(self.tree, Receivers())

    def at(self, node: ast.AST) -> Receivers:
        """Return the receivers of the scope a node is in."""
        return self.scopes[id(node)]

    @classmethod
    def load(cls, name: str) -> Surface:
        return cls(name, (COMPONENT / f"{name}.py").read_text(encoding="utf-8"))

    def _flag(self, node: ast.AST, rule: str, text: str) -> None:
        finding = Finding(self.name, getattr(node, "lineno", 0), rule, text)
        if finding not in self.findings:
            self.findings.append(finding)

    # S1 and S2 ----------------------------------------------------------------------

    def _ours(self, node: ast.ImportFrom) -> str | None:
        """Return the module of this integration an import reads from, "" for the package."""
        if node.level == 1:
            return node.module or ""
        if node.module and (node.module == PACKAGE or node.module.startswith(f"{PACKAGE}.")):
            return node.module.removeprefix(PACKAGE).lstrip(".")
        return None

    def _judge(self, node: ast.AST, rule: str, module: str, name: str) -> None:
        owner = importlib.import_module(f"{PACKAGE}.{module}" if module else PACKAGE)
        value = getattr(owner, name)
        where = f"{module or '__init__'}.{name}"
        if name.startswith("_"):
            self._flag(node, rule, f"uses the private {where}")
        elif inspect.isroutine(value) and (module, name) not in ENTRY_POINTS:
            self._flag(node, rule, f"calls {where}, which is not a service entry point")

    def check_imports(self) -> None:
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.ImportFrom) or (module := self._ours(node)) is None:
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                if not module and importlib.util.find_spec(f"{PACKAGE}.{alias.name}") is not None:
                    self.bound[local] = (alias.name, None)
                    continue
                self.bound[local] = (module, alias.name)
                self._judge(node, "S1", module, alias.name)
        for node in ast.walk(self.tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and self.bound.get(node.value.id, ("", ""))[1] is None
            ):
                self._judge(node, "S2", self.bound[node.value.id][0], node.attr)

    # S3 -----------------------------------------------------------------------------

    def check_service_api(self) -> None:
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Attribute) or isinstance(node.ctx, ast.Store):
                continue
            if self.at(node).is_manager(node.value) and node.attr not in MANAGER_API:
                self._flag(node, "S3", f"reaches the manager's {node.attr}, not its public API")
            if self.at(node).is_summary(node.value) and node.attr not in SUMMARY_READ_API:
                self._flag(node, "S3", f"reaches the summary's {node.attr}, not its read API")

    # S4 -----------------------------------------------------------------------------

    def check_rules(self) -> None:
        self._check_status()
        self._check_settings()
        self._check_availability()

    def _check_status(self) -> None:
        for node in ast.walk(self.tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "Status"
            ):
                self._flag(node, "S4", f"names Status.{node.attr}: a status rule")
            if isinstance(node, ast.Compare) and _reads(node, "status"):
                self._flag(node, "S4", "compares a routine's status: a status rule")

    def _check_settings(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Compare) and _reads_setting(node):
                self._flag(node, "S4", "compares a routine setting: a settings rule")
        for test in _tests(self.tree):
            if _reads_setting(test):
                self._flag(test, "S4", "branches on a routine setting: a settings rule")

    def _check_availability(self) -> None:
        for node in ast.walk(self.tree):
            if (
                not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                or node.name != "available"
            ):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and (
                    sub.attr == "_view"
                    or (sub.attr == "get" and self.at(sub).is_manager(sub.value))
                ):
                    self._flag(
                        sub, "S4", "decides availability from the RoutineView, not the manager"
                    )

    def check(self) -> list[Finding]:
        self.check_imports()
        self.check_service_api()
        self.check_rules()
        return sorted(self.findings, key=lambda found: (found.line, found.rule, found.text))

    # S5 -----------------------------------------------------------------------------

    def _definitions(self) -> dict[str, list[ast.AST]]:
        """Every function, method and class of the module by name (methods by their name)."""
        found: dict[str, list[ast.AST]] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                found.setdefault(node.name, []).append(node)
        return found

    def _service_call(self, call: ast.Call) -> bool:
        func = call.func
        if isinstance(func, ast.Attribute):
            receivers = self.at(call)
            if receivers.is_manager(func.value) or (
                receivers.is_summary(func.value) and func.attr in SUMMARY_READ_API
            ):
                return True
            if func.attr == "_async_update" and isinstance(func.value, ast.Name):
                # The base class helper; `test_the_entity_base_hands_patches_to_the_manager`.
                return func.value.id == "self"
            if (
                isinstance(func.value, ast.Name)
                and self.bound.get(func.value.id, ("", ""))[1] is None
            ):
                return (self.bound[func.value.id][0], func.attr) in SERVICE_CALLS
        if isinstance(func, ast.Name) and func.id in self.bound:
            return self.bound[func.id] in SERVICE_CALLS
        return False

    def reaches_service(self, start: ast.AST) -> bool:
        """Tell whether a function reaches the service layer, through the module's own code."""
        definitions = self._definitions()
        seen: set[int] = set()
        todo = [start]
        while todo:
            node = todo.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            for call in (sub for sub in ast.walk(node) if isinstance(sub, ast.Call)):
                if self._service_call(call):
                    return True
                func = call.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "self"
                    else None
                )
                todo.extend(definitions.get(name or "", []))
        return False

    def entry_points(self) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
        """Return the functions through which Home Assistant or a person reaches this surface."""
        functions = [
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        by_name = {node.name: node for node in functions}
        found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for node in functions:
            decorated = {
                dec.func.id
                for dec in node.decorator_list
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name)
            }
            if (
                node.name in WRITE_METHODS | {"async_attach_runner", "_async_check"}
                or "websocket_command" in decorated
            ):
                found.append(node)
        for item in ast.walk(self.tree):
            # Action handlers: what `hass.services.async_register` is given.
            if (
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and item.func.attr == "async_register"
                and len(item.args) >= 3  # domain, action, handler
            ):
                handler = item.args[2]
                named = handler.func if isinstance(handler, ast.Call) else handler
                if isinstance(named, ast.Name) and named.id in by_name:
                    found.append(by_name[named.id])
            # Fix flows: the values of the `_FIXES` table.
            if isinstance(item, ast.AnnAssign | ast.Assign) and isinstance(item.value, ast.Dict):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                if any(isinstance(name, ast.Name) and name.id == "_FIXES" for name in targets):
                    found.extend(
                        by_name[value.id]
                        for value in item.value.values
                        if isinstance(value, ast.Name) and value.id in by_name
                    )
        return found


def _module_param(name: str, reason: str | None = None) -> Any:
    if reason is None:
        return pytest.param(name, id=name)
    return pytest.param(
        name, id=name, marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)
    )


# The surfaces that break P16 today, each with a reason naming the place and the smallest
# fix; the four found at the A4.1 dispatch (button, sensor, trigger, condition) were fixed
# by the carry over lane (plan A4.0 items 17 to 19).
CHECKS: Final[dict[str, str]] = {}


@pytest.mark.parametrize("module", [_module_param(name, CHECKS.get(name)) for name in SURFACES])
def test_a_surface_is_a_thin_caller_of_the_service_layer(module: str) -> None:
    findings = Surface.load(module).check()
    assert not findings, P16_RULE + "\n" + "\n".join(str(found) for found in findings)


@pytest.mark.parametrize("module", SURFACES)
def test_every_entry_point_of_a_surface_reaches_the_service_layer(module: str) -> None:
    surface = Surface.load(module)
    surface.check_imports()
    entry_points = surface.entry_points()
    if module not in {"binary_sensor", "sensor", "entity"}:
        assert entry_points, f"{module}.py: no entry point found"
    lost = [node.name for node in entry_points if not surface.reaches_service(node)]
    assert not lost, f"{module}.py: {lost} never reach the service layer\n{P16_RULE}"


def test_the_entity_base_hands_patches_to_the_manager() -> None:
    surface = Surface.load("entity")
    helper = next(
        node
        for node in ast.walk(surface.tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_update"
    )
    calls = [
        call.func
        for call in ast.walk(helper)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    ]
    assert any(
        func.attr == "async_update" and surface.at(func).is_manager(func.value) for func in calls
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("from .compiler import compile\n", "S1", id="a pure function"),
        pytest.param("from .manager import apply_patch\n", "S1", id="a service module function"),
        pytest.param("from .summary import _marked\n", "S1", id="a private name"),
        pytest.param("from .trigger import async_get_triggers\n", "S1", id="another surface"),
        pytest.param(
            "from custom_components.device_routines.nextrun import expected_state\n",
            "S1",
            id="an absolute import",
        ),
        pytest.param(
            "from . import nextrun\nnextrun.expected_state(1, 2, 3)\n", "S2", id="a module"
        ),
        pytest.param(
            "from . import maintenance\nmaintenance.cleanup_candidates()\n", "S2", id="maintenance"
        ),
        pytest.param("self._manager._routines.clear()\n", "S3", id="manager internals"),
        pytest.param("entry.runtime_data.manager._async_write(1)\n", "S3", id="a private method"),
        pytest.param("self._summary.async_refresh_device(1)\n", "S3", id="a summary write"),
        pytest.param(
            "def f(c: SummaryCoordinator):\n    c._index.clear()\n", "S3", id="a typed summary"
        ),
        pytest.param(
            "runtime = entry.runtime_data\nrouter = runtime.manager\nrouter._routines.clear()\n",
            "S3",
            id="a manager by assignment",
        ),
        pytest.param(
            "async def f(m: RoutineManager):\n    await m.summary.async_refresh_device(1)\n",
            "S3",
            id="the summary through the manager",
        ),
        pytest.param("x = view.status is Status.ACTIVE\n", "S4", id="a status rule"),
        pytest.param("x = view.status in PAUSING\n", "S4", id="a status set"),
        pytest.param("if view.settings.on_time:\n    pass\n", "S4", id="a settings branch"),
        pytest.param("x = view.settings.days == WEEKLY\n", "S4", id="a settings comparison"),
        pytest.param(
            "x = [k for k in KEYS if getattr(view.settings, k)]\n", "S4", id="a settings filter"
        ),
        pytest.param("x = 1 if v.settings.crosses_midnight else 2\n", "S4", id="a derived one"),
        pytest.param(
            "class A:\n    @property\n    def available(self):\n"
            "        return self._view is not None\n",
            "S4",
            id="availability from the view",
        ),
    ],
)
def test_the_p16_check_finds_each_kind_of_violation(source: str, expected: str) -> None:
    findings = Surface("snippet", source).check()
    assert findings
    assert {found.rule for found in findings} == {expected}, findings


def test_the_p16_check_passes_a_thin_caller() -> None:
    source = (
        "from . import maintenance\n"
        "from .const import DOMAIN\n"
        "from .entity import DeviceRoutinesDeviceEntity\n"
        "from .maintenance import MaintenanceAction\n"
        "from .models import Days, Status\n"
        "class A(DeviceRoutinesDeviceEntity):\n"
        "    @property\n"
        "    def available(self):\n"
        "        return self._reason is None\n"
        "    @property\n"
        "    def current_option(self):\n"
        "        view = self._view\n"
        "        return None if view is None else view.settings.days.value\n"
        "    async def async_press(self):\n"
        "        await self._manager.async_skip_next(self._device_id)\n"
        "        await maintenance.async_run(self.hass, self._manager, 'x', dry_run=False)\n"
    )
    surface = Surface("snippet", source)
    assert surface.check() == []
    # Comparing the global settings to see whether they changed is no routine rule, and a
    # device's summary (a DeviceSummary, not the coordinator) is plain data.
    assert Surface("snippet", "changed = runtime.settings != self._settings\n").check() == []
    data = "summary = self._coordinator.summaries[d]\nx = summary.state\n"
    assert Surface("snippet", data).check() == []
    assert [node.name for node in surface.entry_points()] == ["async_press"]
    assert surface.reaches_service(surface.entry_points()[0])
    lost = Surface("snippet", "async def async_press(self):\n    self.hass.bus.async_fire('x')\n")
    lost.check_imports()
    assert not lost.reaches_service(lost.entry_points()[0])


# ======================================================================================
# 3. The round trip of PRD 12: settings, compiled routine, Schedule sentence
# ======================================================================================


def sentence_parts(settings: RoutineSettings, writer: Writer = WRITER) -> list[str]:
    """The Schedule lines the manager generates from settings (`routine_summary`)."""
    automation_id = markers.automation_id(DEVICE_ID)
    alias = markers.presentation(DEVICE_NAME, PHRASES).alias
    return [writer.line(line) for line in routine_lines(settings, automation_id, alias)]


def sentence(settings: RoutineSettings, writer: Writer = WRITER) -> str:
    """The routine's Schedule item text, as `RoutineManager.routine_summary` joins it."""
    return (
        writer.say("list_separator").join(sentence_parts(settings, writer)) or writer.routine_kind()
    )


@hypothesis_settings(max_examples=400, deadline=None)
@given(case=loose_routines(), refs=strategies.helper_refs())
def test_the_summary_reads_a_written_routine_as_the_sentence_of_its_settings(
    case: tuple[DomainProfile, str | None, RoutineSettings], refs: compiler.HelperRefs
) -> None:
    """The summary decompiles an owned automation's inputs (decision L43), as the manager does.

    The manager reads the inputs back at the next start. Whatever form the settings came
    in, that reading gives the sentence the manager showed while it held the settings.
    """
    profile, _, settings = case
    entry = routine_entry(compiler.compile(settings, profile, refs).inputs)
    owned = summary_module._owned_routine(AUTOMATION_ENTITY, entry)

    assert owned is not None
    assert owned.settings == compiler.canonical(settings)
    assert sentence_parts(owned.settings) == sentence_parts(settings)


def render(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Return an owned entry as the core renders it: the automation the summary parses.

    `BlueprintInputs.async_substitute` is what `async_validate_config_item` runs; the
    result is the entity's `raw_config` (`ha_adapter.automation_config`), which
    `test_the_manager_writes_compile_and_the_schedule_shows_its_sentence` checks.
    """
    rendered: dict[str, Any] = BlueprintInputs(SHIPPED, dict(entry)).async_substitute()
    return rendered


# --------------------------------------------------------------------------------------
# The same round trip through the manager in a running Home Assistant
# --------------------------------------------------------------------------------------

# The devices of the integration fixtures' home, by target: a switch, a light and a garage
# door (a cover whose open the PRD 5.4 refusals take away).
TARGETS: Final = {FAN: ("fan", None), LAMP: ("lamp", None), GARAGE: ("garage", "garage")}


@st.composite
def home_routines(draw: st.DrawFn) -> RoutineSettings:
    """Draw valid settings, in any form, for one of the home's devices."""
    target = draw(st.sampled_from(sorted(TARGETS)))
    profile = profile_for(target.partition(".")[0], TARGETS[target][1])
    assert profile is not None
    loose = draw(strategies.loose_settings(profile, zones=False))
    return replace(loose, target_entity=target)


async def _settle(hass: HomeAssistant, freezer: Any) -> None:
    """Let the manager's write and the summary's debounced rebuild run."""
    await flush(hass, freezer)
    freezer.tick(timedelta(seconds=SUMMARY_DEBOUNCE + 0.1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _write(
    hass: HomeAssistant, home: Home, entry: MockConfigEntry, freezer: Any, settings: RoutineSettings
) -> tuple[str, RoutineManager]:
    """Hand every setting to the manager as one patch and let it write; return the device."""
    device_id: str = getattr(home, TARGETS[settings.target_entity][0])
    manager: RoutineManager = entry.runtime_data.manager
    if manager.get(device_id) is None:
        assert (await manager.async_opt_in(device_id)).opted_in
    patch = {item.name: getattr(settings, item.name) for item in fields(RoutineSettings)}
    result = await manager.async_update(device_id, patch)
    assert result.problem is None, result.problem
    await _settle(hass, freezer)
    return device_id, manager


@harness(12)
@given(settings=home_routines())
async def test_the_manager_writes_compile_and_the_schedule_shows_its_sentence(
    hass: HomeAssistant,
    home: Home,
    routines: MockConfigEntry,
    freezer: Any,
    settings: RoutineSettings,
) -> None:
    """Settings in, through `async_update`, the file, a reload, and the Schedule out."""
    device_id, manager = await _write(hass, home, routines, freezer, settings)

    view = manager.get(device_id)
    assert view is not None
    assert view.automation_entity_id is not None
    entry = file_entry(hass, view.automation_id)
    assert entry is not None
    inputs = entry["use_blueprint"]["input"]
    profile = manager.profile(device_id)
    assert profile is not None
    # The manager writes exactly what compile makes of the settings, and it loads.
    compiled = compiler.compile(settings, profile, compiler.refs_of(inputs)).inputs
    assert list(inputs) == list(compiled)
    assert inputs == compiled
    assert ha_adapter.automation_state(hass, view.automation_entity_id) is not None
    assert hass.states.get(view.automation_entity_id).state == "on"  # type: ignore[union-attr]
    # The core renders the entry the way `render` does: what the summary parses.
    assert ha_adapter.automation_config(hass, view.automation_entity_id) == render(entry)
    # The summary read the written file back to the settings.
    coordinator = routines.runtime_data.summary
    assert coordinator._index.routines[device_id].settings == compiler.canonical(settings)
    # The Schedule item is the sentence of the settings, before and after the entry reloads
    # (the manager then reads the routine from the file, as at a start).
    expected = sentence(settings, manager._writer(settings))
    item = coordinator.summaries[device_id].items[0]
    assert (item.kind, item.summary) == (KIND_ROUTINE, expected)

    assert await hass.config_entries.async_reload(routines.entry_id)
    await _settle(hass, freezer)
    manager = routines.runtime_data.manager
    reloaded = manager.get(device_id)
    assert reloaded is not None
    assert reloaded.settings == compiler.canonical(settings)
    # The writer names entities as they are now: the start recreates a linked schedule
    # helper that does not exist (PRD 3.1), so its name may be new.
    expected = sentence(settings, manager._writer(settings))
    item = routines.runtime_data.summary.summaries[device_id].items[0]
    assert (item.kind, item.summary) == (KIND_ROUTINE, expected)


@harness(4)
@given(settings=home_routines())
async def test_the_summary_reads_a_routine_as_its_sentence_without_the_manager(
    hass: HomeAssistant,
    home: Home,
    routines: MockConfigEntry,
    freezer: Any,
    settings: RoutineSettings,
) -> None:
    """The literal PRD 12 round trip: from the automation alone, as the summary indexes it."""
    device_id, manager = await _write(hass, home, routines, freezer, settings)
    view = manager.get(device_id)
    assert view is not None
    expected = sorted(sentence_parts(settings, manager._writer(settings)))
    coordinator = routines.runtime_data.summary
    coordinator.set_routine_provider(None)
    try:
        items = [
            item
            for item in coordinator.summaries[device_id].items
            if item.automation_entity == view.automation_entity_id
        ]
        shown = sorted(part for item in items for part in (item.parts or (item.summary,)))
    finally:
        coordinator.set_routine_provider(manager)
    assert shown == (expected or [WRITER.routine_kind()])


async def test_the_manager_holds_a_time_with_an_offset_in_the_form_it_reads_back(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    await manager.async_opt_in(home.fan)
    # The JSON a WebSocket client sends; routines/set hands it to the manager unchanged.
    patch = {"off_time": "09:00:00", "on_time": "17:00:00+00:00"}
    result = await manager.async_update(home.fan, patch)
    await _settle(hass, freezer)

    view = manager.get(home.fan)
    assert view is not None
    assert result.problem is not None or view.settings == compiler.canonical(view.settings)
    assert view.settings.on_time is None or view.settings.on_time.tzinfo is None


async def test_a_routine_taken_over_reads_as_detached_in_the_schedule(
    hass: HomeAssistant, home: Home, manager: RoutineManager, freezer: Any
) -> None:
    """Take control as the automation editor saves it: the rendered config, same id."""
    automation_id = await give_routine(
        hass, manager, home.fan, freezer, on_time=time(17), off_time=time(9)
    )
    entry = file_entry(hass, automation_id)
    assert entry is not None
    await save_entry(hass, await ha_adapter.async_take_control_config(hass, entry))
    await _settle(hass, freezer)

    view = manager.get(home.fan)
    assert view is not None
    assert view.status is Status.DETACHED
    items = manager.summary.summaries[home.fan].items
    own = {item.kind for item in items if item.automation_entity == view.automation_entity_id}
    assert own == {KIND_DETACHED}
