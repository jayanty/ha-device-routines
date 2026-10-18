"""Pure module tests need no Home Assistant instance."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations() -> None:
    """Override the package fixture: these tests never start Home Assistant."""
    return
