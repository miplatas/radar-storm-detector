"""Coordinador de actualización de datos para RainViewer."""

import logging
import json
import time
from datetime import timedelta

import paho.mqtt.client as mqtt
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    MQTT_TOPIC_STATUS,
    MQTT_TOPIC_ALERT,
    DEFAULT_FRAMES_N,
)
from .radar import run_analysis

log = logging.getLogger(__name__)


class RainViewerCoordinator(DataUpdateCoordinator):
    """Coordinador que obtiene datos del radar y los publica en MQTT."""

    def __init__(self, hass: HomeAssistant, config: dict):
        self.lat = config["latitude"]
        self.lon = config["longitude"]
        self.zoom = config.get("zoom", 7)
        self.tile_x = config.get("tile_x", 28)
        self.tile_y = config.get("tile_y", 54)
        self.rain_threshold = config.get("rain_threshold", 0.005)
        self.hail_threshold = config.get("hail_threshold", 0.001)
        self.dist_threshold = config.get("dist_threshold", 30)
        self.mqtt_broker = config.get("mqtt_broker")
        self.mqtt_port = config.get("mqtt_port", 1883)
        self.mqtt_user = config.get("mqtt_username", "")
        self.mqtt_pass = config.get("mqtt_password", "")
        self._mqtt_client = None

        scan_interval = config.get("scan_interval", 300)

        super().__init__(
            hass,
            log,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------
    def _setup_mqtt(self):
        """Crea y conecta cliente MQTT."""
        if self._mqtt_client is not None:
            return

        client = mqtt.Client(client_id="ha-rainviewer", clean_session=True)
        if self.mqtt_user:
            client.username_pw_set(self.mqtt_user, self.mqtt_pass)

        def on_connect(c, userdata, flags, rc):
            if rc == 0:
                log.info("RainViewer: MQTT conectado a %s:%s", self.mqtt_broker, self.mqtt_port)
            else:
                log.warning("RainViewer: MQTT error de conexión rc=%s", rc)

        def on_disconnect(c, userdata, rc):
            if rc != 0:
                log.warning("RainViewer: MQTT desconectado inesperadamente rc=%s", rc)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect

        try:
            client.connect(self.mqtt_broker, self.mqtt_port, keepalive=60)
            client.loop_start()
            time.sleep(0.5)
            self._mqtt_client = client
        except Exception as e:
            log.error("RainViewer: No se pudo conectar al broker MQTT: %s", e)
            self._mqtt_client = None

    def _publish(self, payload: dict, alert_level: str):
        """Publica datos en MQTT."""
        if self._mqtt_client is None:
            return
        msg = json.dumps(payload, ensure_ascii=False)
        try:
            self._mqtt_client.publish(MQTT_TOPIC_STATUS, msg, qos=1, retain=True)
            log.debug("RainViewer: publicado en %s", MQTT_TOPIC_STATUS)
            if alert_level != "none":
                self._mqtt_client.publish(MQTT_TOPIC_ALERT, msg, qos=1, retain=True)
                log.info("RainViewer: alerta [%s] publicada en %s", alert_level.upper(), MQTT_TOPIC_ALERT)
        except Exception as e:
            log.error("RainViewer: error publicando en MQTT: %s", e)

    # ------------------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------------------
    async def _async_update_data(self):
        """Obtiene datos del radar (ejecutado en thread pool para no bloquear HA)."""
        try:
            result = await self.hass.async_add_executor_job(
                run_analysis,
                self.lat,
                self.lon,
                self.zoom,
                self.tile_x,
                self.tile_y,
                DEFAULT_FRAMES_N,
                self.rain_threshold,
                self.hail_threshold,
                self.dist_threshold,
            )
        except Exception as e:
            raise UpdateFailed(f"Error analizando radar: {e}") from e

        if result is None:
            raise UpdateFailed("No se obtuvieron datos del radar RainViewer")

        payload, alert_level = result

        # Conectar MQTT si no está conectado y publicar
        if self.mqtt_broker:
            self._setup_mqtt()
            self._publish(payload, alert_level)

        return payload

    async def async_shutdown(self):
        """Desconectar MQTT al remover la integración."""
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            self._mqtt_client = None
