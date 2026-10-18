"""Domain profiles, global settings and conflicts (TECH_SPEC 3.2, 3.7, 3.9)."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.device_routines import conflicts, domains, settings
from custom_components.device_routines.models import (
    Conflict,
    Days,
    Occurrence,
    Option,
    ParseError,
    RoutineSettings,
    Verb,
    Weekday,
)

LA = ZoneInfo("America/Los_Angeles")

# --------------------------------------------------------------------------------------
# domains
# --------------------------------------------------------------------------------------


def test_every_supported_domain_has_a_profile() -> None:
    assert {
        "switch",
        "light",
        "fan",
        "input_boolean",
        "humidifier",
        "climate",
        "media_player",
        "vacuum",
        "lawn_mower",
        "cover",
        "lock",
        "valve",
    } == domains.SUPPORTED_DOMAINS
    inactive = {profile.domain: profile.inactive_state for profile in domains.PROFILES.values()}
    assert inactive["vacuum"] == inactive["lawn_mower"] == "docked"
    assert inactive["cover"] == inactive["valve"] == "closed"
    assert inactive["lock"] == "locked"
    assert inactive["climate"] == "off"


@pytest.mark.parametrize(
    ("domain", "device_class"),
    [("cover", "garage"), ("cover", "gate"), ("cover", "door"), ("valve", "gas")],
)
def test_refused_device_classes_lose_the_activating_action(domain: str, device_class: str) -> None:
    profile = domains.profile_for(domain, device_class)
    assert profile is not None
    assert profile.on_action is None
    assert profile.on_label_key is None
    assert Option.ON_TIME not in profile.options
    assert Option.OFF_TIME in profile.options


def test_profiles_without_an_on_action() -> None:
    for domain in ("lock", "media_player"):
        profile = domains.profile_for(domain)
        assert profile is not None
        assert profile.on_action is None
        assert Option.ON_TIME not in profile.options
    assert domains.profile_for("cover", "window") == domains.PROFILES["cover"]
    assert domains.profile_for("alarm_control_panel") is None


@pytest.mark.parametrize(
    ("action", "device_class", "refused"),
    [
        ("lock.unlock", None, True),
        ("lock.open", None, True),
        ("lock.lock", None, False),
        ("alarm_control_panel.alarm_disarm", None, True),
        ("cover.open_cover", "garage", True),
        ("cover.open_cover", "blind", False),
        ("cover.close_cover", "garage", False),
        ("valve.open_valve", "gas", True),
        ("valve.open_valve", "water", False),
        ("switch.turn_on", None, False),
        ("siren.turn_on", None, False),
    ],
)
def test_refused_actions(action: str, device_class: str | None, refused: bool) -> None:
    assert domains.is_refused_action(action, device_class) is refused


def test_pick_targets_keeps_registry_order() -> None:
    candidates = [
        domains.Candidate("sensor.power"),
        domains.Candidate("switch.plug"),
        domains.Candidate("switch.child_lock", entity_category="config"),
        domains.Candidate("light.ring", disabled=True),
        domains.Candidate("fan.fan"),
    ]
    assert domains.pick_targets(candidates) == ["switch.plug", "fan.fan"]


# --------------------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------------------


def test_defaults_match_prd_10_4() -> None:
    defaults = settings.GlobalSettings()
    assert defaults.to_options() == {
        "schedule_scope": "all",
        "time_format": "auto",
        "default_catch_up": True,
        "default_respect_manual": True,
        "default_late_start_window_min": 15,
        "cleanup_after_days": 30,
        "assign_area": True,
        "on_removal": "keep",
        "ai_task_entity": None,
        "ai_calls_per_hour": 20,
        "offer_conversions": True,
        "raise_conflict_repairs": True,
    }


def test_round_trip_through_options() -> None:
    chosen = settings.GlobalSettings(
        schedule_scope=settings.ScheduleScope.ROUTINES,
        time_format=settings.TimeFormat.H24,
        cleanup_after_days=0,
        ai_task_entity="ai_task.local",
    )
    assert settings.from_options(chosen.to_options()) == chosen


def test_from_options_is_lenient() -> None:
    loaded = settings.from_options(
        {
            "schedule_scope": "everywhere",
            "cleanup_after_days": 999,
            "legacy_key": 1,
            "assign_area": False,
        }
    )
    assert loaded == settings.GlobalSettings(assign_area=False)


@pytest.mark.parametrize(
    ("options", "keys"),
    [
        ({"schedule_scope": "none", "ai_calls_per_hour": 100}, []),
        ({"schedule_scope": "everywhere"}, ["invalid_choice"]),
        ({"default_catch_up": "yes"}, ["invalid_boolean"]),
        ({"cleanup_after_days": 366}, ["out_of_range"]),
        ({"ai_calls_per_hour": True}, ["out_of_range"]),
        ({"ai_task_entity": "sensor.x"}, ["invalid_ai_task_entity"]),
        ({"ai_task_entity": None}, []),
        ({"mystery": 1}, ["unknown_setting"]),
    ],
)
def test_validate(options: dict[str, Any], keys: list[str]) -> None:
    assert [problem.translation_key for problem in settings.validate(options)] == keys


def test_range_problem_names_the_bounds() -> None:
    (problem,) = settings.validate({"default_late_start_window_min": -1})
    assert problem.placeholders == {"min": "0", "max": "180"}


@pytest.mark.parametrize(
    ("time_format", "country", "resolved"),
    [
        ("auto", "US", "12h"),
        ("auto", "de", "24h"),
        ("auto", None, "24h"),
        ("24h", "US", "24h"),
        ("12h", "DE", "12h"),
    ],
)
def test_time_format_resolution(time_format: str, country: str | None, resolved: str) -> None:
    chosen = settings.GlobalSettings(time_format=settings.TimeFormat(time_format))
    assert chosen.resolved_time_format(country) == resolved


def test_migration_runs_each_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OPTIONS_VERSION", 2)
    monkeypatch.setattr(settings, "MIGRATIONS", {1: lambda old: {**old, "cleanup_after_days": 7}})
    assert settings.migrate({"assign_area": False}, 1) == {
        "assign_area": False,
        "cleanup_after_days": 7,
    }
    assert settings.migrate({"assign_area": False}, 2) == {"assign_area": False}


# --------------------------------------------------------------------------------------
# conflicts
# --------------------------------------------------------------------------------------

START = datetime(2026, 10, 19, 0, tzinfo=LA)
END = START + timedelta(days=1)
FAN = "fan.example_fan"


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return START.replace(hour=hour, minute=minute, second=second)


def planned(index: int, *occurrences: Occurrence, **extra: Any) -> conflicts.Planned:
    return conflicts.Planned(index=index, entity_ids=(FAN,), occurrences=occurrences, **extra)


def test_opposite_actions_in_the_same_minute() -> None:
    found = conflicts.find(
        [
            planned(0, Occurrence(at(9, 0, 0), Verb.ON)),
            planned(1, Occurrence(at(9, 0, 30), Verb.OFF), Occurrence(at(9, 0, 40), Verb.OFF)),
            planned(2, Occurrence(at(9, 0, 10), Verb.ON)),
            planned(3, Occurrence(at(9, 1), Verb.OFF)),
        ],
        START,
        END,
    )
    assert found == [
        Conflict(0, 1, conflicts.SAME_MINUTE, at(9)),
        Conflict(1, 2, conflicts.SAME_MINUTE, at(9, 0, 10)),
    ]


def test_same_item_other_entity_outside_range_or_undecided_is_no_conflict() -> None:
    other = conflicts.Planned(1, ("light.l",), (Occurrence(at(9), Verb.OFF),))
    found = conflicts.find(
        [
            planned(0, Occurrence(at(9), Verb.ON), Occurrence(at(9), Verb.OFF)),
            other,
            planned(2, Occurrence(at(9), None)),
            planned(3, Occurrence(END + timedelta(minutes=1), Verb.OFF)),
        ],
        START,
        END,
    )
    assert found == []


WINDOW = RoutineSettings(target_entity=FAN, on_time=time(17), off_time=time(9))


def test_actions_against_a_routine_window() -> None:
    found = conflicts.find(
        [
            planned(0, Occurrence(at(17), Verb.ON), routine=WINDOW),
            planned(1, Occurrence(at(22), Verb.OFF), Occurrence(at(23), Verb.OFF)),
            planned(2, Occurrence(at(12), Verb.ON)),
            planned(3, Occurrence(at(9), Verb.OFF), Occurrence(at(20), Verb.TOGGLE)),
            planned(4, Occurrence(END + timedelta(hours=1), Verb.OFF)),
        ],
        START,
        END,
    )
    assert found == [
        Conflict(0, 1, conflicts.OFF_IN_ON_WINDOW, at(22)),
        Conflict(0, 2, conflicts.ON_IN_OFF_WINDOW, at(12)),
    ]


def test_a_one_shot_routine_has_no_window_to_contradict() -> None:
    one_shot = RoutineSettings(
        target_entity=FAN, on_time=time(7), days=Days.SOME_DAYS, day_set=frozenset({Weekday.MON})
    )
    found = conflicts.find(
        [planned(0, routine=one_shot), planned(1, Occurrence(at(12), Verb.OFF))], START, END
    )
    assert found == []


def test_parse_error_carries_its_placeholders() -> None:
    error = ParseError("not_an_automation", {"alias": "x"})
    assert error.placeholders == {"alias": "x"}
    assert str(error) == "not_an_automation"


def test_weekends_effective_days() -> None:
    weekends = RoutineSettings(target_entity=FAN, days=Days.WEEKENDS)
    assert weekends.effective_days == frozenset({Weekday.SAT, Weekday.SUN})
