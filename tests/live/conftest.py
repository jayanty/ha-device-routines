"""The read only live suite (TECH_SPEC 11.6): skipped unless local/live.env exists.

local/live.env holds two lines, `HA_URL=http://<host>:8123` and `HA_TOKEN=<long lived
token>`, and is never committed (local/ is ignored). Every request is a GET.

The suite runs under the Home Assistant test plugin like every other test (`pytest -m
live`). The plugin blocks sockets, outbound connections and host name lookups in each
test's setup and fails a test at cleanup when it tried a blocked socket, so a live test
could never reach the instance (live finding F5). A test marked `live` gets the real
socket functions back for its duration; every other test keeps the plugin's guard.

Health's `commit` is checked against the tags the instance is deployed from (decision
L58, live finding F6): `deployed_versions` says which versions a commit with those tags
may run.
"""

from __future__ import annotations

from collections.abc import Iterable
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from typing import Any, Final
import urllib.request

import pytest

REPO: Final = Path(__file__).resolve().parents[2]
ENV = REPO / "local" / "live.env"
MANIFEST: Final = "custom_components/device_routines/manifest.json"
DEV_STABLE: Final = "dev-stable"
# A release tag: `v` and a version, with an optional pre release suffix (`-beta.2`).
RELEASE_TAG: Final = re.compile(r"v(?P<version>\d+\.\d+\.\d+)(?:-[0-9A-Za-z.]+)?")

# The real socket functions, read when pytest imports this file during collection, before
# the plugin's first test setup replaces them.
_REAL_SOCKET: Final[dict[str, Any]] = {
    name: getattr(socket, name)
    for name in ("socket", "getaddrinfo", "gethostbyname", "gethostbyname_ex")
}
_REAL_CONNECT: Final = socket.socket.connect


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations() -> None:
    """Override the package fixture: the live suite talks to a real instance only."""
    return


@pytest.fixture(autouse=True)
def live_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give a test marked `live` the real network until it ends (live finding F5).

    The plugin's setup has replaced `socket.socket` with a class that refuses anything
    but a Unix socket, limited `connect` on the real class to 127.0.0.1, and made the host
    name lookups refuse every name but the local ones. The monkeypatch puts the guard back
    when the test ends; the next test's setup would apply it again anyway.
    """
    if request.node.get_closest_marker("live") is None:
        return
    for name, real in _REAL_SOCKET.items():
        monkeypatch.setattr(socket, name, real)
    monkeypatch.setattr(socket.socket, "connect", _REAL_CONNECT)


def _settings() -> dict[str, str]:
    if not ENV.is_file():
        pytest.skip("local/live.env is missing")
    pairs = (line.split("=", 1) for line in ENV.read_text().splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs}


class Live:
    """GET only access to the instance's REST API."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.token = token

    def get(self, path: str) -> Any:
        request = urllib.request.Request(  # noqa: S310  # the owner's own instance
            f"{self.url}{path}", headers={"Authorization": f"Bearer {self.token}"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            return json.loads(response.read())

    def states(self) -> list[dict[str, Any]]:
        states: list[dict[str, Any]] = self.get("/api/states")
        return states


@pytest.fixture(scope="session")
def live() -> Live:
    settings = _settings()
    return Live(settings["HA_URL"], settings["HA_TOKEN"])


# --------------------------------------------------------------------------------------
# What the instance is deployed from (decision L58, live finding F6)
# --------------------------------------------------------------------------------------


def git(*args: str, repo: Path = REPO) -> str | None:
    """Run a read only git command in a clone; its output, or None when it fails.

    `GIT_DIR` and its kin would win over `-C`, so none of them is passed on.
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    return result.stdout if result.returncode == 0 else None


def tags_at(commit: str, repo: Path = REPO) -> list[str]:
    """Return the tags that point at a commit, annotated ones included; none if unknown."""
    return sorted((git("tag", "--points-at", commit, repo=repo) or "").split())


def manifest_version(commit: str, repo: Path = REPO) -> str | None:
    """Return the manifest's version at a commit, or None when it cannot be read."""
    try:
        version = json.loads(git("show", f"{commit}:{MANIFEST}", repo=repo) or "").get("version")
    except ValueError, AttributeError:
        return None
    return version if isinstance(version, str) else None


def release_version(tag: str) -> str | None:
    """Return the version a release tag names, without its pre release suffix, or None."""
    match = RELEASE_TAG.fullmatch(tag)
    return match["version"] if match else None


def deployed_versions(tags: Iterable[str], manifest: str | None) -> frozenset[str]:
    """Return the versions Health may report on a commit with these tags.

    A release tag names its version (every beta of 1.0.0 runs a manifest that says
    1.0.0); `dev-stable` names none, so the manifest at the commit does. Empty when no tag
    the instance is deployed from points at the commit.
    """
    names = list(tags)
    releases = frozenset(version for tag in names if (version := release_version(tag)))
    if releases:
        return releases
    if DEV_STABLE in names and manifest is not None:
        return frozenset({manifest})
    return frozenset()
