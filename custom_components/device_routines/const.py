"""Constants shared across the integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "device_routines"
INTEGRATION_TITLE: Final = "Device Routines"

# The hub device that holds the house wide entities (PRD 4.4).
HUB_IDENTIFIER: Final = "hub"
HUB_MODEL: Final = "Hub"

# Platforms forwarded to the config entry, in setup order. Later phases append their
# platforms here.
PLATFORMS: Final[list[Platform]] = [Platform.BINARY_SENSOR, Platform.SENSOR]

# Health sensor states (TECH_SPEC 10.3).
HEALTH_OK: Final = "ok"
HEALTH_DEGRADED: Final = "degraded"
HEALTH_ERROR: Final = "error"
HEALTH_STATES: Final[list[str]] = [HEALTH_OK, HEALTH_DEGRADED, HEALTH_ERROR]

# How the running code reached this instance (TECH_SPEC 4.10).
CHANNEL_DEV: Final = "dev"
CHANNEL_HACS: Final = "hacs"
CHANNEL_UNKNOWN: Final = "unknown"
