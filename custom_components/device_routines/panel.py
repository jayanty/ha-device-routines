"""The console: an admin only sidebar panel that serves the committed bundle (PRD 4.5).

The console's source lives in `frontend/` at the repository root and builds into one ES
module inside this package, `frontend/dist/device-routines-panel.js`, which is committed
(decision L62): the release zip and the dev channel carry it, and the Home Assistant
host needs no node. This module serves that directory and registers the
`device-routines-panel` web component as a custom panel for administrators, through the
core's public `panel_custom`, `http` and `frontend` APIs (`StaticPathConfig` comes from
its documented path, which the `http` package re-exports without an `__all__`: hence the
one type ignore). The bundle URL carries the integration's version, so a new release is
never read from a browser's cache; the file is served without long lived cache headers,
so a dev channel deploy of the same version is seen after a reload too.

The static path is registered once per Home Assistant run, because the HTTP server
cannot remove a route; the panel itself follows the config entry. A reload (a settings
change from the console's own Settings view) unloads and sets the entry up again under
the entry's setup lock, so the removal waits for that lock and leaves the panel that the
new setup registered: the open console stays where it is instead of vanishing from the
sidebar for a moment.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from homeassistant.components.frontend import async_remove_panel
from homeassistant.components.http import StaticPathConfig  # type: ignore[attr-defined]
from homeassistant.components.panel_custom import async_register_panel as register_custom_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, INTEGRATION_TITLE

PANEL_URL_PATH: Final = "device-routines"
WEB_COMPONENT: Final = "device-routines-panel"
SIDEBAR_ICON: Final = "mdi:calendar-clock"
# The integration's name, as the hub device and the config entry carry it. The core
# shows a custom panel's title as given (strings.json has no category for it), and the
# console's own header shows the same name from its translations (`panel.title`).
SIDEBAR_TITLE: Final = INTEGRATION_TITLE

STATIC_URL: Final = f"/{DOMAIN}/static"
BUNDLE: Final = "device-routines-panel.js"
DIST: Final = Path(__file__).parent / "frontend" / "dist"

# Set once the static path is served in this run; a route cannot be registered twice.
_STATIC_SERVED: Final[HassKey[bool]] = HassKey(f"{DOMAIN}_panel_static")


def bundle_url(version: str) -> str:
    """Return the URL the panel loads its module from, busted by the version."""
    return f"{STATIC_URL}/{BUNDLE}?v={version}"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the bundle (once per run) and register the admin only panel.

    A panel left by the unload of a reload, whose removal still waits for the setup
    lock, is replaced in place: removing and adding happen without a pause in between,
    so the frontend, which reads the panels after the change events, never misses it.
    """
    if not hass.data.get(_STATIC_SERVED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(DIST), cache_headers=False)]
        )
        hass.data[_STATIC_SERVED] = True
    integration = await async_get_integration(hass, DOMAIN)
    async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    await register_custom_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=WEB_COMPONENT,
        sidebar_title=SIDEBAR_TITLE,
        sidebar_icon=SIDEBAR_ICON,
        module_url=bundle_url(str(integration.version or "0.0.0")),
        require_admin=True,
    )


@callback
def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove the panel once the entry's unload is over, unless it was set up again."""
    entries = hass.config_entries.async_entries(DOMAIN)
    hass.async_create_task(_async_remove_unless_loaded(hass, entries), f"{DOMAIN} panel removal")


async def _async_remove_unless_loaded(hass: HomeAssistant, entries: Sequence[ConfigEntry]) -> None:
    """Wait for the setup lock (a reload holds it until the setup ran), then decide."""
    for entry in entries:
        async with entry.setup_lock:
            pass
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
