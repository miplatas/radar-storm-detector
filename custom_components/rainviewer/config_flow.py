"""Config Flow para RainViewer Storm Detector."""

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
    DEFAULT_MQTT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ZOOM,
    DEFAULT_TILE_X,
    DEFAULT_TILE_Y,
    DEFAULT_RAIN_THRESHOLD,
    DEFAULT_HAIL_THRESHOLD,
    DEFAULT_DIST_THRESHOLD,
    DEFAULT_GIF_SPEED,
)


class RainViewerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Flujo de configuración para RainViewer."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        ha_lat = self.hass.config.latitude
        ha_lon = self.hass.config.longitude

        # Pre-calcular tile sugerido a partir de la ubicación de HA
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
                    title=f"RainViewer ({lat:.4f}, {lon:.4f})",
                    data=user_input,
                )

        schema = vol.Schema({
            vol.Required(CONF_LATITUDE,  default=ha_lat):  vol.Coerce(float),
            vol.Required(CONF_LONGITUDE, default=ha_lon):  vol.Coerce(float),
            vol.Required(CONF_ZOOM,    default=DEFAULT_ZOOM):    vol.Coerce(int),
            vol.Required(CONF_TILE_X,  default=suggested_x):    vol.Coerce(int),
            vol.Required(CONF_TILE_Y,  default=suggested_y):    vol.Coerce(int),
            vol.Required(CONF_MQTT_BROKER, default=""):    str,
            vol.Optional(CONF_MQTT_PORT,    default=DEFAULT_MQTT_PORT):    vol.Coerce(int),
            vol.Optional(CONF_MQTT_USERNAME, default=""):  str,
            vol.Optional(CONF_MQTT_PASSWORD, default=""):  str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.Coerce(int),
            vol.Optional(CONF_RAIN_THRESHOLD, default=DEFAULT_RAIN_THRESHOLD): vol.Coerce(float),
            vol.Optional(CONF_HAIL_THRESHOLD, default=DEFAULT_HAIL_THRESHOLD): vol.Coerce(float),
            vol.Optional(CONF_DIST_THRESHOLD, default=DEFAULT_DIST_THRESHOLD): vol.Coerce(int),
            vol.Optional(CONF_GIF_SPEED,      default=DEFAULT_GIF_SPEED):      vol.Coerce(int),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RainViewerOptionsFlow(config_entry)


class RainViewerOptionsFlow(config_entries.OptionsFlow):
    """Flujo de opciones para RainViewer (actualizable sin reiniciar)."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options or self.config_entry.data

        schema = vol.Schema({
            vol.Optional(CONF_SCAN_INTERVAL,  default=opts.get(CONF_SCAN_INTERVAL,  DEFAULT_SCAN_INTERVAL)):  vol.Coerce(int),
            vol.Optional(CONF_RAIN_THRESHOLD, default=opts.get(CONF_RAIN_THRESHOLD, DEFAULT_RAIN_THRESHOLD)): vol.Coerce(float),
            vol.Optional(CONF_HAIL_THRESHOLD, default=opts.get(CONF_HAIL_THRESHOLD, DEFAULT_HAIL_THRESHOLD)): vol.Coerce(float),
            vol.Optional(CONF_DIST_THRESHOLD, default=opts.get(CONF_DIST_THRESHOLD, DEFAULT_DIST_THRESHOLD)): vol.Coerce(int),
            vol.Optional(CONF_GIF_SPEED,      default=opts.get(CONF_GIF_SPEED,      DEFAULT_GIF_SPEED)):      vol.Coerce(int),
        })

        return self.async_show_form(step_id="init", data_schema=schema)
