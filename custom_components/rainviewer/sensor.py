"""RainViewer Storm Detector sensors for Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
import re
from zoneinfo import ZoneInfo
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ALERT_ICONS, CONF_TIMEZONE
from .coordinator import RainViewerCoordinator

log = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create all sensors automatically."""
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
        RainViewerLastRadarUrlSensor(coordinator, entry),
        RainViewerLastRadarTimeSensor(coordinator, entry),
    ]

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class RainViewerBaseSensor(CoordinatorEntity, SensorEntity):
    """Base sensor for RainViewer."""

    def __init__(self, coordinator: RainViewerCoordinator, entry: ConfigEntry,
                 key: str, name: str, icon: str, unit: str | None = None):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"rainviewer_{entry.entry_id}_{key}"
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._entry = entry

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Storm Detector",
            "manufacturer": "Radar",
            "model": "Radar Storm Detector",
            "entry_type": "service",
        }

    def _data(self):
        return self.coordinator.data or {}


# ---------------------------------------------------------------------------
# Concrete sensors
# ---------------------------------------------------------------------------
class RainViewerAlertSensor(RainViewerBaseSensor):
    """Alert level: none / watch / warning / emergency."""

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
            "approaching":   d.get("proximity", {}).get("approaching", False),
        }


class RainViewerAlertMsgSensor(RainViewerBaseSensor):
    """Alert descriptive message."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "alert_msg", "Alert Message",
                         "mdi:message-alert")

    @property
    def native_value(self):
        return self._data().get("alert_msg", "Sin datos")


class RainViewerRainSensor(RainViewerBaseSensor):
    """Pixel fraction with rain (ligera + moderada)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "rain", "Rain Coverage",
                         "mdi:weather-rainy", "%")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("current", {}).get("rain", 0)
        return round(val * 100, 4)


class RainViewerHeavySensor(RainViewerBaseSensor):
    """Pixel fraction with heavy rain."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "heavy", "Heavy Rain Coverage",
                         "mdi:weather-pouring", "%")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("current", {}).get("heavy", 0)
        return round(val * 100, 4)


class RainViewerHailSensor(RainViewerBaseSensor):
    """Pixel fraction with hail."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "hail", "Hail Coverage",
                         "mdi:weather-hail", "%")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("current", {}).get("hail", 0)
        return round(val * 100, 4)


class RainViewerRainTrendSensor(RainViewerBaseSensor):
    """Tendency of rain (positive = increasing)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "rain_trend", "Rain Trend",
                         "mdi:trending-up")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("trend", {}).get("rain", 0)
        return round(val * 100, 5)


class RainViewerHailTrendSensor(RainViewerBaseSensor):
    """Tendency of hail."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "hail_trend", "Hail Trend",
                         "mdi:trending-up")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("trend", {}).get("hail", 0)
        return round(val * 100, 5)


class RainViewerDistanceSensor(RainViewerBaseSensor):
    """Estimated precipitation distance to the reference point (pixels)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "distance", "Storm Distance",
                         "mdi:map-marker-distance", "px")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("proximity", {}).get("dist_mean", -1)
        return round(val, 2) if val >= 0 else None

    @property
    def extra_state_attributes(self):
        p = self._data().get("proximity", {})
        return {
            "bearing":      p.get("bearing_mean"),
            "dist_max":     p.get("dist_max"),
            "approach_vel": p.get("approach_vel"),
            "core_growth":  p.get("core_growth"),
            "approaching":  p.get("approaching", False),
        }


class RainViewerDbzMeanSensor(RainViewerBaseSensor):
    """dBZ average of the latest frame."""

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
    """dBZ maximum of the latest frame."""

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
    """Storm approach velocity (px/frame; negative = approaching)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "vx", "Storm Approach Velocity",
                         "mdi:arrow-collapse-down", "px/frame")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self._data().get("proximity", {}).get("approach_vel", 0)


class RainViewerMovementVySensor(RainViewerBaseSensor):
    """Nearest storm bearing (compass: 0=N, 90=E, 180=S, 270=W)."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "vy", "Storm Bearing",
                         "mdi:compass-outline", "°")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        val = self._data().get("proximity", {}).get("bearing_mean")
        return round(val, 1) if val is not None else None


class RainViewerLastRadarUrlSensor(RainViewerBaseSensor):
    """URL of the latest analyzed radar PNG frame."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_radar_url", "Last Radar Image URL",
                         "mdi:radar")

    @property
    def native_value(self):
        return self._data().get("last_radar_url")

    @property
    def extra_state_attributes(self):
        url = self._data().get("last_radar_url")
        return {"url": url, "image_url": url}


class RainViewerLastRadarTimeSensor(RainViewerBaseSensor):
    """Human-readable timestamp of the latest analyzed radar frame."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_radar_time", "Last Radar Time",
                         "mdi:clock-outline")

    def _target_tz(self):
        cfg = {**self._entry.data, **self._entry.options}
        tz_name = cfg.get(CONF_TIMEZONE)
        if not tz_name and self.hass is not None:
            tz_name = self.hass.config.time_zone

        # New format: GMT offset selector values like "GMT -6".
        match = re.fullmatch(r"GMT\s*([+-])\s*(\d{1,2})", tz_name or "")
        if match:
            sign, hours = match.groups()
            offset_hours = int(hours) * (1 if sign == "+" else -1)
            return timezone(timedelta(hours=offset_hours))

        # Backward-compatible format from earlier versions: "UTC-06:00".
        match = re.fullmatch(r"UTC([+-])(\d{2}):00", tz_name or "")
        if match:
            sign, hours = match.groups()
            offset_hours = int(hours) * (1 if sign == "+" else -1)
            return timezone(timedelta(hours=offset_hours))

        try:
            return ZoneInfo(tz_name) if tz_name else timezone.utc
        except Exception:
            return timezone.utc

    @property
    def native_value(self):
        ts = self._data().get("last_radar_time")
        if ts is None:
            return None
        try:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(self._target_tz())
            return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except Exception:
            return str(ts)

    @property
    def extra_state_attributes(self):
        ts = self._data().get("last_radar_time")
        if ts is None:
            return {}
        try:
            tz = self._target_tz()
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz)
            return {
                "unix_timestamp": ts,
                "iso8601": dt.isoformat(),
                "timezone": str(tz),
            }
        except Exception:
            return {"unix_timestamp": ts}

