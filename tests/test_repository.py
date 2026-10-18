"""Repository level invariants that hold from the first commit onward.

The manifest, the HACS metadata, the quality scale checklist, the translations and the
architecture's import rules are all things that drift quietly; each one is pinned here.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from custom_components.device_routines.const import HEALTH_STATES
from tools import style_check

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "device_routines"

# The modules TECH_SPEC Section 2 declares pure: standard library and each other only.
# Modules that do not exist yet are skipped, so the list can be complete from day one.
PURE_MODULES = (
    "models.py",
    "domains.py",
    "compiler.py",
    "markers.py",
    "parser.py",
    "parser_grammar.py",
    "nextrun.py",
    "conflicts.py",
    "sentence.py",
    "settings.py",
)

# The modules allowed to reach Home Assistant internals (anything outside the public
# helpers). Everything else may import only `homeassistant.core`, `homeassistant.helpers`,
# `homeassistant.const`, `homeassistant.config_entries`, `homeassistant.exceptions`,
# `homeassistant.loader`, `homeassistant.util` and its own platform's base classes.
ADAPTER_MODULE = "ha_adapter.py"
ALLOWED_CORE_PREFIXES = (
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.const",
    "homeassistant.config_entries",
    "homeassistant.data_entry_flow",
    "homeassistant.exceptions",
    "homeassistant.loader",
    "homeassistant.util",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.switch",
    "homeassistant.components.button",
    "homeassistant.components.select",
    "homeassistant.components.number",
    "homeassistant.components.time",
    "homeassistant.components.datetime",
    "homeassistant.components.diagnostics",
    "homeassistant.components.repairs",
    "homeassistant.components.websocket_api",
)

# The official rule names of the Integration Quality Scale, as shipped with core 2026.10.
_OFFICIAL_RULE_TEXT = """
    action-exceptions action-setup appropriate-polling async-dependency brands
    common-modules config-entry-unloading config-flow config-flow-test-coverage
    dependency-transparency devices diagnostics discovery discovery-update-info
    docs-actions docs-conditions docs-configuration-parameters docs-data-update
    docs-examples docs-high-level-description docs-installation-instructions
    docs-installation-parameters docs-known-limitations docs-removal-instructions
    docs-supported-devices docs-supported-functions docs-triggers docs-troubleshooting
    docs-use-cases dynamic-devices entity-category entity-device-class
    entity-disabled-by-default entity-event-setup entity-translations entity-unavailable
    entity-unique-id exception-translations has-entity-name icon-translations
    inject-websession integration-owner log-when-unavailable parallel-updates
    reauthentication-flow reconfiguration-flow repair-issues runtime-data stale-devices
    strict-typing test-before-configure test-before-setup test-coverage
    unique-config-entry
"""
OFFICIAL_RULES = frozenset(_OFFICIAL_RULE_TEXT.split())
STATUSES = frozenset({"done", "exempt", "todo"})


def load_json(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def imports_of(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


# --------------------------------------------------------------------------------------
# Manifest and HACS metadata
# --------------------------------------------------------------------------------------


def test_the_manifest_has_what_hacs_and_hassfest_require() -> None:
    manifest = load_json(COMPONENT / "manifest.json")

    for key in ("domain", "name", "version", "codeowners", "documentation", "issue_tracker"):
        assert manifest[key], f"manifest.json is missing {key}"
    assert manifest["domain"] == "device_routines"
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "service"
    assert manifest["iot_class"] == "local_push"
    assert manifest["single_config_entry"] is True
    assert manifest["requirements"] == [], "no Python requirement without a decision"
    assert set(manifest["dependencies"]) == {"automation", "blueprint", "timer", "schedule"}
    assert manifest["after_dependencies"] == ["ai_task"]


def test_the_manifest_keys_are_sorted_the_way_hassfest_wants() -> None:
    keys = list(load_json(COMPONENT / "manifest.json"))

    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_hacs_json_matches_the_manifest() -> None:
    hacs = load_json(REPO_ROOT / "hacs.json")
    manifest = load_json(COMPONENT / "manifest.json")

    assert hacs["name"] == manifest["name"]
    assert hacs["zip_release"] is True
    assert hacs["filename"] == f"{manifest['domain']}.zip"
    assert hacs["render_readme"] is True


# --------------------------------------------------------------------------------------
# The quality scale checklist
# --------------------------------------------------------------------------------------


def quality_rules() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(
        (COMPONENT / "quality_scale.yaml").read_text(encoding="utf-8")
    )["rules"]
    return loaded


def test_the_checklist_accounts_for_exactly_the_official_rules() -> None:
    tracked = set(quality_rules())

    assert sorted(OFFICIAL_RULES - tracked) == []
    assert sorted(tracked - OFFICIAL_RULES) == []


@pytest.mark.parametrize("rule", sorted(OFFICIAL_RULES))
def test_every_rule_has_a_status_and_a_reason(rule: str) -> None:
    entry = quality_rules()[rule]

    assert entry["status"] in STATUSES
    assert len(entry["comment"].split()) >= 8, f"{rule}: say why, not just what"


def test_the_manifest_claims_no_tier() -> None:
    """The scale awards nothing to a custom integration, so claiming a tier would be a lie."""
    assert "quality_scale" not in load_json(COMPONENT / "manifest.json")


# --------------------------------------------------------------------------------------
# Translations
# --------------------------------------------------------------------------------------


def test_the_english_translation_equals_the_source_strings() -> None:
    assert load_json(COMPONENT / "translations" / "en.json") == load_json(
        COMPONENT / "strings.json"
    )


@pytest.mark.parametrize(
    "path",
    [
        COMPONENT / "strings.json",
        COMPONENT / "translations" / "en.json",
        COMPONENT / "icons.json",
        COMPONENT / "sentences" / "en.json",
    ],
    ids=lambda path: path.relative_to(COMPONENT).as_posix(),
)
def test_json_files_hold_no_duplicate_keys(path: Path) -> None:
    """A key added twice by two lanes would silently keep only the last value."""
    duplicates: list[str] = []

    def collect(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in pairs]
        duplicates.extend(sorted({key for key in keys if keys.count(key) > 1}))
        return dict(pairs)

    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=collect)
    assert not duplicates


def translation_keys_in_source() -> set[tuple[str, str]]:
    """Return (platform, key) for every translation key an entity module assigns."""
    found: set[tuple[str, str]] = set()
    platforms = {
        "sensor",
        "binary_sensor",
        "switch",
        "button",
        "select",
        "number",
        "time",
        "datetime",
    }
    for path in COMPONENT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "translation_key" and isinstance(keyword.value, ast.Constant):
                    found.add((path.stem, str(keyword.value.value)))
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "__init__"
                and path.stem in platforms
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add((path.stem, arg.value))
    return found


def test_every_entity_key_the_platforms_use_is_translated() -> None:
    strings = load_json(COMPONENT / "strings.json")["entity"]
    keys = {key for platform, key in translation_keys_in_source() if platform in strings}

    assert keys, "the collector found nothing, which would make this test meaningless"
    for platform, key in translation_keys_in_source():
        if platform in strings:
            assert key in strings[platform], f"{platform}.{key} has no translation"


def test_the_health_states_are_translated() -> None:
    strings = load_json(COMPONENT / "strings.json")

    assert set(strings["entity"]["sensor"]["health"]["state"]) == set(HEALTH_STATES)


# --------------------------------------------------------------------------------------
# Architecture: who may import what (TECH_SPEC Section 2)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("relative", PURE_MODULES)
def test_pure_modules_never_import_home_assistant(relative: str) -> None:
    path = COMPONENT / relative
    if not path.exists():
        pytest.skip(f"{relative} does not exist yet")

    for name in imports_of(path):
        assert not name.startswith("homeassistant"), f"{relative} imports {name}"
        assert not name.startswith(("voluptuous", "probatio")), f"{relative} imports {name}"


def test_only_the_adapter_reaches_internals() -> None:
    offenders = [
        f"{path.name}: {name}"
        for path in sorted(COMPONENT.glob("*.py"))
        if path.name != ADAPTER_MODULE
        for name in imports_of(path)
        if name.startswith("homeassistant") and not name.startswith(ALLOWED_CORE_PREFIXES)
    ]

    assert offenders == []


# --------------------------------------------------------------------------------------
# Style
# --------------------------------------------------------------------------------------


def test_no_em_dash_in_any_tracked_file() -> None:
    assert style_check.scan_files(style_check.tracked_files(REPO_ROOT)) == []


# --------------------------------------------------------------------------------------
# CI: the job names are the required checks on main
# --------------------------------------------------------------------------------------

REQUIRED_CHECKS = {
    "lint",
    "typecheck",
    "test (pinned)",
    "hassfest",
    "hacs",
    "privacy",
    "style",
    "deploy-tool-parity",
}


def test_ci_job_names_are_the_required_checks_plus_the_promotion() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    jobs = workflow["jobs"]
    names = {job["name"].replace("${{ matrix.core }}", "pinned") for job in jobs.values()}

    assert names == REQUIRED_CHECKS | {"promote"}
    assert set(jobs["promote"]["needs"]) == set(jobs) - {"promote"}
    assert "refs/heads/dev" in jobs["promote"]["if"]


def test_the_release_workflow_builds_the_hacs_zip() -> None:
    path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(path.read_text())
    # PyYAML reads the bare `on` key as the boolean True.
    triggers = workflow.get("on", workflow.get(True))

    assert triggers["push"]["tags"] == ["v*"]
    assert "device_routines.zip" in path.read_text()
    assert "manifest.json" in path.read_text()
