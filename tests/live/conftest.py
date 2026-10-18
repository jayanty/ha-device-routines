"""The read only live suite (TECH_SPEC 11.6): skipped unless local/live.env exists.

local/live.env holds two lines, `HA_URL=http://<host>:8123` and `HA_TOKEN=<long lived
token>`, and is never committed (local/ is ignored). Every request is a GET.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import urllib.request

import pytest

ENV = Path(__file__).resolve().parents[2] / "local" / "live.env"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations() -> None:
    """Override the package fixture: the live suite talks to a real instance only."""
    return


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
