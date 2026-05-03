"""Cámara RainViewer — imagen compuesta: OSM + ícono de casa + radar RGBA."""

from __future__ import annotations

import io
import logging
import math
import time
from collections import deque
from threading import Lock

import requests
import numpy as np
from PIL import Image, ImageDraw

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEFAULT_FRAMES_N
from .coordinator import RainViewerCoordinator

log = logging.getLogger(__name__)

# Cuántos frames históricos conservar en el buffer
HISTORY_SIZE = DEFAULT_FRAMES_N

# Tamaño del tile en píxeles
TILE_SIZE = 256


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RainViewerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RainViewerCamera(coordinator, entry)])


# ---------------------------------------------------------------------------
# Helpers de imagen (corren en executor)
# ---------------------------------------------------------------------------

def _fetch_image(url: str) -> Image.Image | None:
    """Descarga una imagen desde una URL y la retorna como PIL Image RGBA."""
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        log.warning("No se pudo cargar imagen: %s → %s", url, e)
        return None


def _draw_home_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 18) -> None:
    """Dibuja un ícono de casa centrado en (cx, cy)."""
    h = size
    w = int(h * 0.85)
    hw = w // 2
    roof_h = h // 2

    # Cuerpo de la casa
    body_top = cy - h // 4
    body_bottom = cy + h // 2
    body_left = cx - hw
    body_right = cx + hw
    draw.rectangle(
        [body_left, body_top, body_right, body_bottom],
        fill=(255, 255, 255, 230),
        outline=(30, 30, 30, 255),
        width=2,
    )

    # Techo (triángulo)
    roof_apex = (cx, cy - h // 4 - roof_h)
    roof_left = (cx - hw - 3, body_top)
    roof_right = (cx + hw + 3, body_top)
    draw.polygon([roof_apex, roof_left, roof_right], fill=(220, 60, 60, 230), outline=(30, 30, 30, 255))

    # Puerta
    door_w = max(4, w // 4)
    door_h = max(6, h // 4)
    door_left = cx - door_w // 2
    door_top = body_bottom - door_h
    draw.rectangle(
        [door_left, door_top, door_left + door_w, body_bottom],
        fill=(100, 60, 20, 220),
    )


def _build_composite(
    osm_url: str,
    radar_url: str,
    tile_size: int = TILE_SIZE,
) -> bytes | None:
    """
    Construye imagen compuesta:
      1. Capa base: tile OSM
      2. Capa radar: imagen RGBA de RainViewer (transparente donde no llueve)
      3. Capa ícono: casa en el centro del tile (pixel 128,128)
    Retorna bytes PNG.
    """
    # 1. Mapa base
    base = _fetch_image(osm_url)
    if base is None:
        base = Image.new("RGBA", (tile_size, tile_size), (200, 200, 200, 255))
    else:
        base = base.resize((tile_size, tile_size)).convert("RGBA")

    # 2. Capa radar
    radar = _fetch_image(radar_url)
    if radar is not None:
        radar = radar.resize((tile_size, tile_size)).convert("RGBA")
        # Mezclar: alpha del radar al 80 % para no tapar todo el mapa
        r, g, b, a = radar.split()
        a = a.point(lambda v: int(v * 0.85))
        radar = Image.merge("RGBA", (r, g, b, a))
        base = Image.alpha_composite(base, radar)

    # 3. Ícono de casa en el centro
    draw = ImageDraw.Draw(base)
    cx = tile_size // 2
    cy = tile_size // 2
    # Sombra
    _draw_home_icon(draw, cx + 2, cy + 2, size=20)
    # Ícono real
    _draw_home_icon(draw, cx, cy, size=20)

    # Exportar PNG
    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Entidad Camera
# ---------------------------------------------------------------------------

class RainViewerCamera(CoordinatorEntity, Camera):
    """
    Cámara que muestra la imagen de radar más reciente con mapa base y
    un ícono de casa en la posición del usuario.
    Mantiene un historial de los últimos N frames.
    """

    def __init__(self, coordinator: RainViewerCoordinator, entry: ConfigEntry):
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)

        self._entry = entry
        self._attr_name = "RainViewer Radar Image"
        self._attr_unique_id = f"rainviewer_{entry.entry_id}_camera"
        self._attr_icon = "mdi:radar"

        # Buffer circular de imágenes PNG (bytes)
        self._history: deque[dict] = deque(maxlen=HISTORY_SIZE)
        self._lock = Lock()
        self._current_image: bytes | None = None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "RainViewer Storm Detector",
            "manufacturer": "RainViewer",
            "model": "Radar Storm Detector",
            "entry_type": "service",
        }

    @property
    def extra_state_attributes(self):
        """Expone el historial de URLs analizadas."""
        return {
            "history": [
                {"timestamp": f["timestamp"], "radar_url": f["radar_url"]}
                for f in self._history
            ],
            "frames_in_buffer": len(self._history),
        }

    def _handle_coordinator_update(self) -> None:
        """Llamado cuando el coordinador tiene datos nuevos — genera imagen en background."""
        data = self.coordinator.data
        if not data:
            return

        radar_url = data.get("last_radar_url")
        last_time = data.get("last_radar_time")
        zoom = self._entry.data.get("zoom", 7)
        tile_x = self._entry.data.get("tile_x", 28)
        tile_y = self._entry.data.get("tile_y", 54)

        if not radar_url:
            return

        # OSM tile URL
        osm_url = f"https://a.tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"

        # Generar imagen en executor para no bloquear el event loop
        self.hass.async_add_executor_job(
            self._generate_and_store, osm_url, radar_url, last_time
        )
        super()._handle_coordinator_update()

    def _generate_and_store(self, osm_url: str, radar_url: str, timestamp) -> None:
        """Genera la imagen compuesta y la almacena en el buffer (corre en thread pool)."""
        png_bytes = _build_composite(osm_url, radar_url)
        if png_bytes is None:
            return

        with self._lock:
            # Evitar duplicados: solo agregar si la URL es nueva
            if not self._history or self._history[-1]["radar_url"] != radar_url:
                self._history.append({
                    "timestamp": timestamp,
                    "radar_url": radar_url,
                    "image":     png_bytes,
                })
            self._current_image = png_bytes

        log.debug("RainViewer Camera: imagen actualizada (%d bytes)", len(png_bytes))

    def camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Retorna la imagen más reciente del buffer."""
        with self._lock:
            return self._current_image

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Versión async — delega a executor si no hay imagen en caché."""
        with self._lock:
            if self._current_image:
                return self._current_image

        # Si todavía no hay imagen, intentar generar una inmediatamente
        data = self.coordinator.data
        if not data:
            return None

        radar_url = data.get("last_radar_url")
        if not radar_url:
            return None

        zoom = self._entry.data.get("zoom", 7)
        tile_x = self._entry.data.get("tile_x", 28)
        tile_y = self._entry.data.get("tile_y", 54)
        osm_url = f"https://a.tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"

        png_bytes = await self.hass.async_add_executor_job(
            _build_composite, osm_url, radar_url
        )

        with self._lock:
            self._current_image = png_bytes

        return png_bytes
