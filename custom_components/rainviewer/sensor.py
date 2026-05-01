"""Sensores de RainViewer Storm Detector para Home Assistant."""

from __future__ import annotations

import logging
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ALERT_ICONS
from .coordinator import RainViewerCoordinator

log = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea todos los sensores automáticamente."""
    coordinator: RainViewerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        RainViewerAlertSensor(coordinator, entry),
        RainViewerAlertMsgSensor(coordinator, entry),
        RainViewerRainSensor(coordinator, entry),
        RainViewerHeavySensor(coordinator, entry),
        RainViewerHailSensor(coordinator, entry),
        RainViewerRainTrendSensor(coordinator, entry),
        RainViewerHailTrendSensor(coordinator, entry),
        RainViewerDistanceSensor(coordinator, entry),
        RainViewerDbzMeanSensor(coordinator, entry),
        RainViewerDbzMaxSensor(coordinator, entry),
        RainViewerMovementVxSensor(coordinator, entry),
        RainViewerMovementVySensor(coordinator, entry),
    ]

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class RainViewerBaseSensor(CoordinatorEntity, SensorEntity):
    """Sensor base para RainViewer."""

    def __init__(self, coordinator: RainViewerCoordinator, entry: ConfigEntry,
                 key: str, name: str, icon: str, unit: str | None = None):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = f"RainViewer {name}"
        self._attr_unique_id = f"rainviewer_{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "RainViewer Storm Detector",
            "manufacturer": "RainViewer",
            "model": "Radar Storm Detector",
            "entry_type": "service",
        }

    def _data(self):
        return self.coordinator.data or {}


# ---------------------------------------------------------------------------
# Sensores concretos
# ---------------------------------------------------------------------------
class RainViewerAlertSensor(RainViewerBaseSensor):
    """Nivel de alerta: none / watch / warning / emergency."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "alert", "Alert Level",
                         "mdi:weather-lightning-rainy")

    @property
    def native_value(self):
        return self._data().get("alert", "unknown")

    @property
    def icon(self):
        level = self._data().get("alert", "none")
        return ALERT_ICONS.get(level, "mdi:weather-lightning-rainy")

    @property
    def extra_state_attributes(self):
        d = self._data()
        return {
            "alert_message": d.get("alert_msg", ""),
            "approaching":   d.get("movement", {}).get("approaching", False),
        }


class RainViewerAlertMsgSensor(RainViewerBaseSensor):
    """Mensaje descriptivo de la alerta."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "alert_msg", "Alert Message",
                         "mdi:message-alert")

    @property
    def native_value(self):
        return self._data().get("alert_msg", "Sin datos")


class RainViewerRainSensor(RainViewerBaseSensor):
    """Fracción de píxeles con lluvia (ligera + moderada)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "rain", "Rain Coverage",
                         "mdi:weather-rainy", "%")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("current", {}).get("rain", 0)
        return round(val * 100, 4)


class RainViewerHeavySensor(RainViewerBaseSensor):
    """Fracción de píxeles con lluvia intensa."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "heavy", "Heavy Rain Coverage",
                         "mdi:weather-pouring", "%")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("current", {}).get("heavy", 0)
        return round(val * 100, 4)


class RainViewerHailSensor(RainViewerBaseSensor):
    """Fracción de píxeles con granizo."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "hail", "Hail Coverage",
                         "mdi:weather-hail", "%")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("current", {}).get("hail", 0)
        return round(val * 100, 4)


class RainViewerRainTrendSensor(RainViewerBaseSensor):
    """Tendencia de lluvia (positivo = aumentando)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "rain_trend", "Rain Trend",
                         "mdi:trending-up")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("trend", {}).get("rain", 0)
        return round(val * 100, 5)


class RainViewerHailTrendSensor(RainViewerBaseSensor):
    """Tendencia de granizo."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "hail_trend", "Hail Trend",
                         "mdi:trending-up")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("trend", {}).get("hail", 0)
        return round(val * 100, 5)


class RainViewerDistanceSensor(RainViewerBaseSensor):
    """Distancia estimada de la precipitación al punto de referencia (píxeles)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "distance", "Storm Distance",
                         "mdi:map-marker-distance", "px")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("movement", {}).get("distance", -1)
        return round(val, 2) if val >= 0 else None


class RainViewerDbzMeanSensor(RainViewerBaseSensor):
    """dBZ promedio del último frame."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "dbz_mean", "dBZ Mean",
                         "mdi:radar", "dBZ")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        frames = self._data().get("frames", [])
        if not frames:
            return None
        return frames[-1].get("dbz", {}).get("mean", 0)


class RainViewerDbzMaxSensor(RainViewerBaseSensor):
    """dBZ máximo del último frame."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "dbz_max", "dBZ Max",
                         "mdi:radar", "dBZ")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        frames = self._data().get("frames", [])
        if not frames:
            return None
        return frames[-1].get("dbz", {}).get("max", 0)


class RainViewerMovementVxSensor(RainViewerBaseSensor):
    """Vector de movimiento horizontal de la tormenta."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "vx", "Storm Movement X",
                         "mdi:arrow-right", "px/frame")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self._data().get("movement", {}).get("vx", 0)


class RainViewerMovementVySensor(RainViewerBaseSensor):
    """Vector de movimiento vertical de la tormenta."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "vy", "Storm Movement Y",
                         "mdi:arrow-down", "px/frame")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self._data().get("movement", {}).get("vy", 0)
