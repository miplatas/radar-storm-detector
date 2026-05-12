"""
Módulo de inicialización para CFE Forecast MX.

Este archivo maneja el ciclo de vida completo de la integración:
  - async_setup_entry: Carga la integración al iniciar HA o al agregar la entrada.
  - async_unload_entry: Downloads limpiamente al eliminar la integración.
  - async_reload_entry: Recarga cuando se cambian las options.

La integración usa:
  - DataUpdateCoordinator para eficiencia (una sola update compartida).
  - helpers.storage.Store para persistir la energy bank entre restarts.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PLATFORMS, STORAGE_KEY, STORAGE_VERSION
from .sensor import CFECoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Configura la integración CFE Forecast MX a partir de una ConfigEntry.
    
    Este método se llama automáticamente cuando:
      - Home Assistant inicia y la integración ya estaba configurada.
      - El usuario agrega una nueva instancia desde la UI.
      - La integración se recarga (después de cambiar options).
    
    Flow:
      1. Crear el Store para persistencia de datos.
      2. Crear e inicializar el Coordinator.
      3. Cargar el estado guardado (energy bank, readings base).
      4. Realizar la primera update de datos.
      5. Registrar el coordinator en hass.data para que los sensors lo encuentren.
      6. Configurar las plataformas (sensor, binary_sensor).
    
    Args:
        hass: Instancia de Home Assistant.
        entry: Entrada de configuration de esta integración.
    
    Returns:
        True if la configuration fue exitosa, False en caso contrario.
    """
    _LOGGER.info(
        "[CFE] Iniciando CFE Forecast MX (entry_id: %s, tarifa: %s)",
        entry.entry_id,
        entry.data.get("tariff", "?"),
    )

    # ── Inicializar el namonthpace de datos para esta integración ──────────
    hass.data.setdefault(DOMAIN, {})

    # ── Crear el Store de persistencia ───────────────────────────────────
    # El Store guarda los datos en .storage/cfe_forecast_energy_store
    # y sobrevive restarts de Home Assistant.
    store = Store(
        hass,
        version=STORAGE_VERSION,
        key=STORAGE_KEY,
    )

    # ── Crear el Coordinator ─────────────────────────────────────────────
    coordinator = CFECoordinator(hass, entry, store)

    # ── Cargar el estado persistido ──────────────────────────────────────
    # Recupera la energy bank y las readings base guardadas previamente.
    # Si no hay datos guardados, el coordinator inicia desde cero.
    await coordinator.async_load_state()
    _LOGGER.debug("[CFE] Estado cargado del Store correctamente.")

    # ── Primera update de datos ───────────────────────────────────
    # Realiza la primera reading de sensors y cálculos.
    # Si falla, la integración no se carga (el error se muestra en la UI).
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info("[CFE] Primera actualización de datos completada.")

    # ── Registrar el coordinator en hass.data ────────────────────────────
    # Los sensors lo recuperarán usando: hass.data[DOMAIN][entry_id]
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # ── Configurar las plataformas ───────────────────────────────────────
    # Esto llama a async_setup_entry en sensor.py y binary_sensor.py
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("[CFE] Plataformas configuradas: %s", PLATFORMS)

    # ── Escuchar cambios de options ─────────────────────────────────────
    # Cuando el usuario edita las options, se recarga la integración automáticamente
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Downloads limpiamente la integración CFE Forecast MX.
    
    Se llama cuando el usuario elimina la integración desde la UI,
    o cuando HA necesita recargarla (por cambio de options).
    
    Flow:
      1. Downloadsr todas las plataformas registradas.
      2. Eliminar el coordinator del namonthpace de datos.
    
    Args:
        hass: Instancia de Home Assistant.
        entry: Entrada de configuration a downloadsr.
    
    Returns:
        True if la downloads fue exitosa.
    """
    _LOGGER.info("[CFE] Descargando CFE Forecast MX (entry_id: %s)", entry.entry_id)

    # Downloadsr todas las entidades de las plataformas
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Limpiar el coordinator del namonthpace de datos
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.info("[CFE] Integración descargada correctamente.")
    else:
        _LOGGER.error("[CFE] Error al descargar las plataformas de la integración.")

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Recarga la integración cuando se cambian las options.
    
    Este método es llamado automáticamente por el listener registrado
    en async_setup_entry cuando el usuario guarda cambios en Options Flow.
    
    La recarga es transparente para el usuario: las entidades se
    actualizan con la nueva configuration sin perder el historial de HA.
    
    Args:
        hass: Instancia de Home Assistant.
        entry: Entrada de configuration que fue modificada.
    """
    _LOGGER.info(
        "[CFE] Recargando integración por cambio de opciones (entry_id: %s)",
        entry.entry_id,
    )
    await hass.config_entries.async_reload(entry.entry_id)
