"""Config Flow for RainViewer Storm Detector."""

import logging
import math
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE

from .const import (
    DOMAIN,
    CONF_MQTT_BROKER,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_MQTT_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_ZOOM,
    CONF_TILE_X,
    CONF_TILE_Y,
    CONF_RAIN_THRESHOLD,
    CONF_HAIL_THRESHOLD,
    CONF_DIST_THRESHOLD,
    CONF_GIF_SPEED,
    CONF_MAP_STYLE,
    CONF_TEST_DRAW_PROXIMITY_CIRCLES,
    CONF_TIMEZONE,
    DEFAULT_MQTT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ZOOM,
    DEFAULT_TILE_X,
    DEFAULT_TILE_Y,
    DEFAULT_RAIN_THRESHOLD,
    DEFAULT_HAIL_THRESHOLD,
    DEFAULT_DIST_THRESHOLD,
    DEFAULT_GIF_SPEED,
    DEFAULT_MAP_STYLE,
    DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES,
    DEFAULT_TIMEZONE,
    MAP_STYLE_OPTIONS,
    TIMEZONE_OPTIONS,
)

log = logging.getLogger(__name__)


class RainViewerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configuration flow for RainViewer."""

    VERSION = 1

    @staticmethod
    def _normalize_timezone_option(tz_value):
        """Return a valid UTC offset option; fallback to default for legacy values."""
        return tz_value if tz_value in TIMEZONE_OPTIONS else DEFAULT_TIMEZONE

    @staticmethod
    def _normalize_map_style_option(style_value):
        """Return a valid map style option; fallback to default for legacy values."""
        return style_value if style_value in MAP_STYLE_OPTIONS else DEFAULT_MAP_STYLE

    async def async_step_user(self, user_input=None):
        errors = {}

        ha_lat = self.hass.config.latitude
        ha_lon = self.hass.config.longitude
        default_tz = DEFAULT_TIMEZONE

        # Pre-calculate suggested tile from the HA location
        def _lat_lon_to_tile(lat, lon, zoom):
            n = 2 ** zoom
            x = int((lon + 180.0) / 360.0 * n)
            lat_rad = math.radians(lat)
            y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
            return x, y

        suggested_x, suggested_y = _lat_lon_to_tile(ha_lat, ha_lon, DEFAULT_ZOOM)

        if user_input is not None:
            lat = user_input.get(CONF_LATITUDE)
            lon = user_input.get(CONF_LONGITUDE)

            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                errors["base"] = "invalid_location"
            else:
                await self.async_set_unique_id(f"rainviewer_{lat}_{lon}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Storm Detector ({lat:.4f}, {lon:.4f})",
                    data=user_input,
                )

        schema = vol.Schema({
            vol.Required(CONF_LATITUDE,  default=ha_lat):  vol.Coerce(float),
            vol.Required(CONF_LONGITUDE, default=ha_lon):  vol.Coerce(float),
            vol.Required(CONF_ZOOM,    default=DEFAULT_ZOOM):    vol.Coerce(int),
            vol.Required(CONF_TILE_X,  default=suggested_x):    vol.Coerce(int),
            vol.Required(CONF_TILE_Y,  default=suggested_y):    vol.Coerce(int),
            vol.Required(CONF_MQTT_BROKER, default=""):    str,
            vol.Optional(CONF_MQTT_PORT,    default=DEFAULT_MQTT_PORT):    vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Optional(CONF_MQTT_USERNAME, default=""):  str,
            vol.Optional(CONF_MQTT_PASSWORD, default=""):  str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
            vol.Optional(CONF_RAIN_THRESHOLD, default=DEFAULT_RAIN_THRESHOLD): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(CONF_HAIL_THRESHOLD, default=DEFAULT_HAIL_THRESHOLD): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(CONF_DIST_THRESHOLD, default=DEFAULT_DIST_THRESHOLD): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
            vol.Optional(CONF_GIF_SPEED,      default=DEFAULT_GIF_SPEED):      vol.All(vol.Coerce(int), vol.Range(min=100, max=5000)),
            vol.Optional(CONF_MAP_STYLE,      default=DEFAULT_MAP_STYLE):      vol.In(MAP_STYLE_OPTIONS),
            vol.Optional(
                CONF_TIMEZONE,
                default=self._normalize_timezone_option(default_tz),
            ): vol.In(TIMEZONE_OPTIONS),
            vol.Optional(
                CONF_TEST_DRAW_PROXIMITY_CIRCLES,
                default=DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES,
            ): bool,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RainViewerOptionsFlow()


class RainViewerOptionsFlow(config_entries.OptionsFlow):
    """Options flow for RainViewer (updateable without restart)."""

    def __init__(self):
        """Initialize options flow."""
        super().__init__()

    @staticmethod
    def _normalize_timezone_option(tz_value):
        """Return a valid UTC offset option; fallback to default for legacy values."""
        return tz_value if tz_value in TIMEZONE_OPTIONS else DEFAULT_TIMEZONE

    @staticmethod
    def _normalize_map_style_option(style_value):
        """Return a valid map style option; fallback to default for legacy values."""
        return style_value if style_value in MAP_STYLE_OPTIONS else DEFAULT_MAP_STYLE

    @staticmethod
    def _normalize_int(value, default):
        """Return an int value or fallback to default for legacy invalid values."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_float(value, default):
        """Return a float value or fallback to default for legacy invalid values."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_bool(value, default):
        """Return a bool value or fallback to default for legacy invalid values."""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return default

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            # Save options and schedule a refresh of coordinator data
            result = self.async_create_entry(title="", data=user_input)
            # Force coordinator update after options change
            coordinator = self.hass.data[DOMAIN].get(self.config_entry.entry_id)
            if coordinator:
                self.hass.async_create_task(coordinator.async_refresh())
            return result

        opts = self.config_entry.options or self.config_entry.data
        current_tz = opts.get(CONF_TIMEZONE, DEFAULT_TIMEZONE)
        current_map_style = opts.get(CONF_MAP_STYLE, DEFAULT_MAP_STYLE)
        current_scan_interval = opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        current_rain_threshold = opts.get(CONF_RAIN_THRESHOLD, DEFAULT_RAIN_THRESHOLD)
        current_hail_threshold = opts.get(CONF_HAIL_THRESHOLD, DEFAULT_HAIL_THRESHOLD)
        current_dist_threshold = opts.get(CONF_DIST_THRESHOLD, DEFAULT_DIST_THRESHOLD)
        current_gif_speed = opts.get(CONF_GIF_SPEED, DEFAULT_GIF_SPEED)
        current_draw_circles = opts.get(
            CONF_TEST_DRAW_PROXIMITY_CIRCLES,
            DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES,
        )

        try:
            schema = vol.Schema({
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self._normalize_int(current_scan_interval, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Optional(
                    CONF_RAIN_THRESHOLD,
                    default=self._normalize_float(current_rain_threshold, DEFAULT_RAIN_THRESHOLD),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                vol.Optional(
                    CONF_HAIL_THRESHOLD,
                    default=self._normalize_float(current_hail_threshold, DEFAULT_HAIL_THRESHOLD),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                vol.Optional(
                    CONF_DIST_THRESHOLD,
                    default=self._normalize_int(current_dist_threshold, DEFAULT_DIST_THRESHOLD),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
                vol.Optional(
                    CONF_GIF_SPEED,
                    default=self._normalize_int(current_gif_speed, DEFAULT_GIF_SPEED),
                ): vol.All(vol.Coerce(int), vol.Range(min=100, max=5000)),
                vol.Optional(
                    CONF_MAP_STYLE,
                    default=self._normalize_map_style_option(current_map_style),
                ): vol.In(MAP_STYLE_OPTIONS),
                vol.Optional(
                    CONF_TIMEZONE,
                    default=self._normalize_timezone_option(current_tz),
                ): vol.In(TIMEZONE_OPTIONS),
                vol.Optional(
                    CONF_TEST_DRAW_PROXIMITY_CIRCLES,
                    default=self._normalize_bool(
                        current_draw_circles,
                        DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES,
                    ),
                ): bool,
            })
        except Exception:
            log.exception("RainViewer options flow: failed to build schema, using safe defaults")
            schema = vol.Schema({
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(vol.Coerce(int), vol.Range(min=30, max=3600)),
                vol.Optional(CONF_RAIN_THRESHOLD, default=DEFAULT_RAIN_THRESHOLD): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                vol.Optional(CONF_HAIL_THRESHOLD, default=DEFAULT_HAIL_THRESHOLD): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
                vol.Optional(CONF_DIST_THRESHOLD, default=DEFAULT_DIST_THRESHOLD): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
                vol.Optional(CONF_GIF_SPEED, default=DEFAULT_GIF_SPEED): vol.All(vol.Coerce(int), vol.Range(min=100, max=5000)),
                vol.Optional(CONF_MAP_STYLE, default=DEFAULT_MAP_STYLE): vol.In(MAP_STYLE_OPTIONS),
                vol.Optional(CONF_TIMEZONE, default=DEFAULT_TIMEZONE): vol.In(TIMEZONE_OPTIONS),
                vol.Optional(
                    CONF_TEST_DRAW_PROXIMITY_CIRCLES,
                    default=DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES,
                ): bool,
            })

        return self.async_show_form(step_id="init", data_schema=schema)
