"""Integración RainViewer Storm Detector para Home Assistant."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE

from .const import DOMAIN, PLATFORMS
from .coordinator import RainViewerCoordinator

log = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura la integración desde un config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Combinar data + options (options sobrescriben data si existen)
    config = {**entry.data, **entry.options}
    config["latitude"]  = entry.data[CONF_LATITUDE]
    config["longitude"] = entry.data[CONF_LONGITUDE]

    coordinator = RainViewerCoordinator(hass, config)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listener para recargar si cambian las opciones
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    log.info("RainViewer Storm Detector iniciado para (%.4f, %.4f)",
             config["latitude"], config["longitude"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga la integración."""
    coordinator: RainViewerCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la integración cuando cambian las opciones."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
