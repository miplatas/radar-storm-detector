"""RainViewer Storm Detector integration for Home Assistant."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE

from .const import DOMAIN, PLATFORMS
from .coordinator import RainViewerCoordinator

log = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Merge data + options (options override data when present).
    config = {**entry.data, **entry.options}
    config["latitude"]  = entry.data[CONF_LATITUDE]
    config["longitude"] = entry.data[CONF_LONGITUDE]

    coordinator = RainViewerCoordinator(hass, config)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listener to reload when options change.
    entry.async_on_unload(entry.add_update_listener(async_options_update_listener))

    log.info("RainViewer Storm Detector started for (%.4f, %.4f)",
             config["latitude"], config["longitude"])
    return True


async def async_options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the integration."""
    coordinator: RainViewerCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
