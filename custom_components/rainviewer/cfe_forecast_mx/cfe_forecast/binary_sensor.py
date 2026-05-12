"""
Plataforma binary_sensor para CFE Forecast MX.

Los sensors binarios están deendidos en sensor.py para aprovechar el mismo
DataUpdateCoordinator. Este módulo actúa como punto de entrada de la plataforma
y re-exporta las clases de alertas.

Sensors binarios disponibles:
  - cfe_alerta_expiracion_bolsa: kWh de bolsa próximos a vencer (30 days).
  - cfe_risk_dac: Risk de reclasificación a tariff DAC.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import (
    CFECoordinator,
    CFEAlertaExpiracionSensor,
    CFERiesgoDACBinarySensor,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """
    Configura los sensors binarios al cargar la integración.
    
    Recupera el coordinator compartido y crea las entidades binary_sensor.
    Los sensors binarios usan el mismo coordinator que los sensors regulares,
    por lo que no hay readings adicionales a la red.
    
    Args:
        hass: Instancia de Home Assistant.
        config_entry: Entrada de configuration de esta integración.
        async_add_entities: Función para registrar las entidades en HA.
    """
    coordinator: CFECoordinator = hass.data[DOMAIN][config_entry.entry_id]

    # Registrar los sensors binarios de alerta
    async_add_entities([
        CFEAlertaExpiracionSensor(coordinator, config_entry),
        CFERiesgoDACBinarySensor(coordinator, config_entry),
    ])

    _LOGGER.debug(
        "[CFE] Sensores binarios registrados para entry_id: %s",
        config_entry.entry_id,
    )
