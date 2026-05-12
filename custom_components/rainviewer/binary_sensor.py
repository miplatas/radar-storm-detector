"""RainViewer Storm Detector binary sensors for Home Assistant."""

from __future__ import annotations

import logging
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RainViewerCoordinator

log = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create binary sensors automatically."""
    coordinator: RainViewerCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        RainViewerRainBinarySensor(coordinator, entry),
        RainViewerHailBinarySensor(coordinator, entry),
        RainViewerStormApproachingSensor(coordinator, entry),
        RainViewerEmergencyBinarySensor(coordinator, entry),
    ])


class RainViewerBaseBinary(CoordinatorEntity, BinarySensorEntity):
    """Base class for binary sensors."""

    def __init__(self, coordinator, entry, key, name, icon, device_class=None):
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_unique_id = f"rainviewer_{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Storm Detector",
            "manufacturer": "RainViewer",
            "model": "Radar Storm Detector",
            "entry_type": "service",
        }

    def _data(self):
        return self.coordinator.data or {}


class RainViewerRainBinarySensor(RainViewerBaseBinary):
    """True when rain is detected."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "rain_detected", "Rain Detected",
                         "mdi:weather-rainy", BinarySensorDeviceClass.MOISTURE)

    @property
    def is_on(self):
        alert = self._data().get("alert", "none")
        return alert in ("watch", "warning", "emergency")


class RainViewerHailBinarySensor(RainViewerBaseBinary):
    """True when hail is detected."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "hail_detected", "Hail Detected",
                         "mdi:weather-hail")

    @property
    def is_on(self):
        hail = self._data().get("current", {}).get("hail", 0)
        return hail > 0.001

    @property
    def extra_state_attributes(self):
        return {
            "hail_coverage_pct": round(
                self._data().get("current", {}).get("hail", 0) * 100, 4
            )
        }


class RainViewerStormApproachingSensor(RainViewerBaseBinary):
    """True when the storm is approaching."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "approaching", "Storm Approaching",
                         "mdi:arrow-collapse-down")

    @property
    def is_on(self):
        return self._data().get("proximity", {}).get("approaching", False)


class RainViewerEmergencyBinarySensor(RainViewerBaseBinary):
    """True when alert level is 'emergency'."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "emergency", "Emergency Alert",
                         "mdi:alert", BinarySensorDeviceClass.SAFETY)

    @property
    def is_on(self):
        return self._data().get("alert", "none") == "emergency"
