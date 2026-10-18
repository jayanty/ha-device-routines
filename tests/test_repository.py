"""Repository level invariants that hold from the first commit onward.

The manifest, the HACS metadata, the quality scale checklist, the translations and the
architecture's import rules are all things that drift quietly; each one is pinned here.
"""

from __future__ import annotations

import ast
import fnmatch
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from PIL import Image
import pytest
import yaml

from custom_components.device_routines.const import HEALTH_STATES
from tools import make_brand, style_check

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
    "conversion.py",
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
    # The console panel (Build B lane 21, F9): the core's public panel and static file APIs.
    "homeassistant.components.panel_custom",
    "homeassistant.components.http",
    "homeassistant.components.frontend",
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
    # `http` serves the console bundle. `frontend` and `panel_custom` are imported but not
    # declared: the core always loads the frontend first, hassfest allows both, and as
    # dependencies they would need the frontend package in the harness.
    assert set(manifest["dependencies"]) == {"automation", "blueprint", "timer", "schedule", "http"}
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

# The committed console bundle, relative to the repository root (decision L62).
BUNDLE_DIR = "custom_components/device_routines/frontend/dist"

REQUIRED_CHECKS = {
    "lint",
    "typecheck",
    "test (pinned)",
    "hassfest",
    "hacs",
    "privacy",
    "style",
    "deploy-tool-parity",
    "frontend",
}


def test_ci_job_names_are_the_required_checks_plus_the_promotion() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    jobs = workflow["jobs"]
    names = {job["name"].replace("${{ matrix.core }}", "pinned") for job in jobs.values()}

    assert names == REQUIRED_CHECKS | {"promote"}
    assert set(jobs["promote"]["needs"]) == set(jobs) - {"promote"}
    assert "refs/heads/dev" in jobs["promote"]["if"]


def test_ci_requires_the_frontend_check() -> None:
    """The console job builds from the lock and fails when the committed bundle is stale."""
    jobs = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"]
    job = jobs["frontend"]
    steps = job["steps"]
    commands = [step.get("run", "") for step in steps]
    node = next(step for step in steps if step.get("uses", "").startswith("actions/setup-node"))
    release = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "release.yml").read_text())
    release_node = next(
        step
        for step in release["jobs"]["release"]["steps"]
        if step.get("uses", "").startswith("actions/setup-node")
    )

    assert "frontend" in REQUIRED_CHECKS
    assert "frontend" in jobs["promote"]["needs"]
    assert job["defaults"]["run"]["working-directory"] == "frontend"
    for command in ("npm ci", "npm run typecheck", "npm test", "npm run build"):
        assert command in commands, command
    assert commands.index("npm run build") < len(commands) - 1, "the bundle check runs last"
    check = commands[-1]
    assert "status --porcelain --untracked-files=all" in check
    assert BUNDLE_DIR in check
    # The bundle CI checks is the bundle the release builds: one Node major for both.
    assert str(node["with"]["node-version"]) == str(release_node["with"]["node-version"])


def test_the_console_bundle_is_committed() -> None:
    """The dev channel deploys the commit archive and the host has no node (L62)."""
    listed = subprocess.run(
        ["git", "ls-files", "--", BUNDLE_DIR],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", f"{BUNDLE_DIR}/device-routines-panel.js"],
        cwd=REPO_ROOT,
        check=False,
    )
    stray = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", "frontend/dist/device-routines-panel.js"],
        cwd=REPO_ROOT,
        check=False,
    )

    assert listed == [f"{BUNDLE_DIR}/device-routines-panel.js"]
    assert ignored.returncode == 1, "the bundle must not be ignored"
    assert stray.returncode == 0, "any other dist/ stays ignored"


def test_the_release_workflow_builds_the_hacs_zip() -> None:
    path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(path.read_text())
    # PyYAML reads the bare `on` key as the boolean True.
    triggers = workflow.get("on", workflow.get(True))

    assert triggers["push"]["tags"] == ["v*"]
    assert "device_routines.zip" in path.read_text()
    assert "manifest.json" in path.read_text()


def test_a_beta_tag_is_compared_with_the_version_it_previews() -> None:
    """`v0.3.0-beta.1` must pass against manifest 0.3.0 and take the 0.3.0 notes (L33)."""
    path = REPO_ROOT / ".github" / "workflows" / "release.yml"
    workflow = yaml.safe_load(path.read_text())
    steps = {step.get("name"): step for step in workflow["jobs"]["release"]["steps"]}
    check = steps["The manifest version must match the tag"]["run"]
    notes = steps["Collect the release notes from the changelog"]["run"]
    for script in (check, notes):
        assert 'tag="${GITHUB_REF_NAME#v}"' in script
        assert '"${tag%%-beta.*}"' in script
    assert '[ "$release" != "$version" ]' in check
    assert "contains(github.ref_name, '-beta.')" in path.read_text()
    shell = ["bash", "-c", 'tag="$1"; echo "${tag%%-beta.*}"', "-"]
    for tag, release in (("0.3.0-beta.1", "0.3.0"), ("0.3.0", "0.3.0"), ("1.0.0-beta.12", "1.0.0")):
        result = subprocess.run([*shell, tag], capture_output=True, text=True, check=True)
        assert result.stdout.strip() == release


# --------------------------------------------------------------------------------------
# Brand images (Build B lane 23): the image rules of the home-assistant/brands README, and
# since decision L78 the copy the integration ships in its own `brand/` folder, which Home
# Assistant 2026.3 and later shows and the HACS brands check looks for.
# --------------------------------------------------------------------------------------

BRAND = REPO_ROOT / make_brand.BRAND_DIR
INTEGRATION_BRAND = REPO_ROOT / make_brand.INTEGRATION_BRAND_DIR
LOGOS = ("logo", "dark_logo")


@pytest.fixture(scope="module")
def drawn_brand() -> dict[str, Image.Image]:
    return make_brand.render_all()


def brand_image(name: str) -> Image.Image:
    with Image.open(BRAND / name) as image:
        image.load()
        return image


def test_the_brand_files_are_exactly_the_drawn_set() -> None:
    """`brand/` and the integration's `brand/` hold the drawn images and nothing else.

    `brand/brands/`, the layout of the brands pull request L78 dropped, is gone with it.
    """
    names = set(make_brand.ASSET_NAMES)

    assert {path.name for path in BRAND.iterdir()} == names
    assert {path.name for path in INTEGRATION_BRAND.iterdir()} == names
    assert {"icon.png", "icon@2x.png", "logo.png", "logo@2x.png"} <= names


@pytest.mark.parametrize("name", make_brand.ASSET_NAMES)
def test_every_brand_image_is_an_rgba_png_with_transparent_corners(name: str) -> None:
    image = brand_image(name)
    width, height = image.size
    corners = ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))

    assert image.format == "PNG"
    assert image.mode == "RGBA"
    assert not image.info.get("interlace"), "the drawing is written without interlacing"
    assert [image.getchannel("A").getpixel(corner) for corner in corners] == [0, 0, 0, 0]


@pytest.mark.parametrize("name", make_brand.ASSET_NAMES)
def test_every_brand_image_is_trimmed(name: str) -> None:
    """Something is drawn on every edge row and column: no transparent padding."""
    image = brand_image(name)

    assert image.getbbox(alpha_only=True) == (0, 0, *image.size)


def test_the_icons_are_square_at_256_and_512() -> None:
    assert brand_image("icon.png").size == (256, 256)
    assert brand_image("icon@2x.png").size == (512, 512)


@pytest.mark.parametrize("stem", LOGOS)
def test_the_logos_are_landscape_within_the_brands_limits(stem: str) -> None:
    """Shortest side 128 to 256, and 256 to 512 for @2x, which is exactly twice the size."""
    width, height = brand_image(f"{stem}.png").size
    double = brand_image(f"{stem}@2x.png").size

    assert width > height
    assert 128 <= height <= 256
    assert double == (2 * width, 2 * height)
    assert brand_image(f"{stem}.png").size == brand_image("logo.png").size


@pytest.mark.parametrize("name", make_brand.ASSET_NAMES)
def test_the_integrations_brand_folder_mirrors_brand(name: str) -> None:
    assert (INTEGRATION_BRAND / name).read_bytes() == (BRAND / name).read_bytes()


def test_the_hacs_brands_check_finds_the_icon_where_it_looks() -> None:
    """The HACS action passes its brands check on `<content path>/brand/icon.png` (L78).

    The content path is `custom_components/<domain>` because `hacs.json` does not set
    `content_in_root`. The check reads the repository tree, so the icon must not be
    ignored by git; it asks the brands repository only when the file is missing.
    """
    hacs = load_json(REPO_ROOT / "hacs.json")
    domain = load_json(COMPONENT / "manifest.json")["domain"]
    asset = f"custom_components/{domain}/brand/icon.png"
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", asset], cwd=REPO_ROOT, check=False
    )

    assert not hacs.get("content_in_root")
    assert (REPO_ROOT / asset).is_file()
    assert ignored.returncode == 1, "the brand icon must not be ignored"


def test_the_hacs_job_ignores_no_check() -> None:
    """Every HACS check runs, brands included, since the icon ships in the integration (L78)."""
    jobs = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"]
    action = next(
        step for step in jobs["hacs"]["steps"] if step.get("uses", "").startswith("hacs/action")
    )

    assert action["with"] == {"category": "integration"}


def test_the_release_zip_carries_the_brand_folder() -> None:
    """The zip is the whole integration folder, so `brand/` ships in it (L78)."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "release.yml").read_text())
    steps = {step.get("name"): step for step in workflow["jobs"]["release"]["steps"]}
    command = steps["Zip the integration"]["run"]
    excluded = re.findall(r"-x '([^']+)'", command)

    assert "(cd custom_components/device_routines && zip -r ../../device_routines.zip ." in command
    assert excluded == ["*__pycache__*", ".deployed"]
    for name in make_brand.ASSET_NAMES:
        assert not any(fnmatch.fnmatch(f"brand/{name}", pattern) for pattern in excluded)


@pytest.mark.parametrize("name", make_brand.ASSET_NAMES)
def test_make_brand_draws_the_committed_image_data(
    name: str, drawn_brand: dict[str, Image.Image]
) -> None:
    """The committed image is the drawing, pixel for pixel, on any platform."""
    committed = brand_image(name)

    assert (committed.mode, committed.size) == (drawn_brand[name].mode, drawn_brand[name].size)
    assert committed.tobytes() == drawn_brand[name].tobytes()


def test_make_brand_reproduces_the_committed_files_byte_for_byte() -> None:
    """`python -m tools.make_brand --check` passes: every file, both folders, no strays.

    The image data is pinned above everywhere. The bytes also depend on the zlib inside
    Pillow, so where re-encoding a committed image's own data does not give its bytes
    back, this platform's encoder differs from the one that wrote them and only the pixel
    test applies.
    """
    for name in make_brand.ASSET_NAMES:
        if make_brand.encode(brand_image(name)) != (BRAND / name).read_bytes():
            pytest.skip("this platform's PNG encoder writes other bytes for the same image")

    assert make_brand.check(REPO_ROOT) == []
