"""What the hub Health sensor reports: the running commit, the channel, the self checks.

`tools/ha_deploy.py` writes `.deployed` next to the code it deployed, and the Health sensor
reports what is in it so the deploy loop can end by comparing the `commit` attribute with
the sha that was pushed (PRD 11.2). Most installs never have that file: a HACS install is a
released archive the deploy tool never touched, and a missing file is what a normal install
looks like, not a fault. A missing, unreadable or half written file all read the same way
here: no deployment record, and the integration is otherwise well.

The file readers are plain functions over paths so they can be tested without a running
Home Assistant; `async_collect` is the one place that touches `hass`, and it runs the
readers in the executor because they block.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import partial
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from .const import (
    CHANNEL_DEV,
    CHANNEL_HACS,
    CHANNEL_UNKNOWN,
    DOMAIN,
    HEALTH_OK,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Where the deploy tool writes its marker: alongside the code it deployed. Module level so
# a test can point it somewhere harmless.
COMPONENT_DIR: Final = Path(__file__).parent
DEPLOYED_FILE_NAME: Final = ".deployed"

# HACS records what it installed here. Read only, and only to label the channel; nothing
# in this integration depends on the answer.
HACS_STORE: Final = Path(".storage") / "hacs.repositories"


@dataclass(frozen=True, slots=True)
class Deployment:
    """The commit that is running, as the deploy tool recorded it.

    `changed_files` is a count: the list is diagnostics material, not an attribute.
    """

    commit: str | None
    branch: str | None
    deployed_at: str | None
    previous_commit: str | None
    changed_files: int
    rollback_of: str | None


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The Health sensor's state and attributes (TECH_SPEC 10.3)."""

    state: str
    version: str
    commit: str | None
    branch: str | None
    deployed_at: str | None
    channel: str
    ha_version: str
    blueprint_schema: int | None
    blueprint_status: str | None
    owned_count: int
    loaded_count: int
    issues: tuple[str, ...]
    last_reconcile: str | None

    def as_attributes(self) -> dict[str, Any]:
        """Return the attributes the sensor exposes, with plain lists for JSON."""
        attributes = asdict(self)
        del attributes["state"]
        attributes["issues"] = list(self.issues)
        return attributes


def _text(value: object) -> str | None:
    """Return a string field, or None when it is missing or is not one."""
    return value if isinstance(value, str) else None


def read_deployment(component_dir: Path) -> Deployment | None:
    """Return what `.deployed` says, or None when there is nothing to say. Blocking."""
    path = component_dir / DEPLOYED_FILE_NAME
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError, ValueError:
        _LOGGER.warning(
            "%s exists but could not be read as JSON, so no deployment record is reported."
            " The running code is unaffected: this file only describes how it got here",
            path,
        )
        return None
    if not isinstance(data, dict):
        return None
    changed = data.get("changed_files")
    return Deployment(
        commit=_text(data.get("commit")),
        branch=_text(data.get("branch")),
        deployed_at=_text(data.get("deployed_at")),
        previous_commit=_text(data.get("previous_commit")),
        changed_files=len(changed) if isinstance(changed, list) else 0,
        rollback_of=_text(data.get("rollback_of")),
    )


def _hacs_lists_domain(config_dir: Path) -> bool:
    """Report whether the HACS store says it installed this integration. Blocking."""
    try:
        data: Any = json.loads((config_dir / HACS_STORE).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    repositories = data.get("data") if isinstance(data, dict) else None
    if not isinstance(repositories, dict):
        return False
    return any(
        isinstance(entry, dict) and entry.get("domain") == DOMAIN and bool(entry.get("installed"))
        for entry in repositories.values()
    )


def detect_channel(config_dir: Path, *, has_deployment: bool) -> str:
    """Return `dev`, `hacs` or `unknown` (TECH_SPEC 4.10). Blocking."""
    if has_deployment:
        return CHANNEL_DEV
    if _hacs_lists_domain(config_dir):
        return CHANNEL_HACS
    return CHANNEL_UNKNOWN


def build_report(
    *, deployment: Deployment | None, channel: str, version: str, ha_version: str
) -> HealthReport:
    """Assemble the report. The self checks arrive with the blueprint and the manager."""
    return HealthReport(
        state=HEALTH_OK,
        version=version,
        commit=deployment.commit if deployment else None,
        branch=deployment.branch if deployment else None,
        deployed_at=deployment.deployed_at if deployment else None,
        channel=channel,
        ha_version=ha_version,
        blueprint_schema=None,
        blueprint_status=None,
        owned_count=0,
        loaded_count=0,
        issues=(),
        last_reconcile=None,
    )


async def async_collect(hass: HomeAssistant, version: str) -> HealthReport:
    """Read the marker and the channel in the executor and build the report."""
    deployment = await hass.async_add_executor_job(read_deployment, COMPONENT_DIR)
    channel = await hass.async_add_executor_job(
        partial(detect_channel, Path(hass.config.config_dir), has_deployment=deployment is not None)
    )
    from homeassistant.const import __version__ as ha_version  # noqa: PLC0415

    return build_report(
        deployment=deployment, channel=channel, version=version, ha_version=ha_version
    )
