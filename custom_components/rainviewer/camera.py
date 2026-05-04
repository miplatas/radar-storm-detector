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

from .const import DOMAIN, DEFAULT_FRAMES_N, DEFAULT_GIF_SPEED
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

def _fetch_image(url: str, is_osm: bool = False) -> Image.Image | None:
    """Descarga una imagen desde una URL y la retorna como PIL Image RGBA."""
    headers = {}
    if is_osm:
        headers["User-Agent"] = "RainViewerHA/1.1 (Home Assistant integration; github.com/miplatas/rainviewer_hacs)"
    try:
        r = requests.get(url, timeout=10, headers=headers)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        log.warning("No se pudo cargar imagen: %s → %s", url, e)
        return None


def _draw_home_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 10) -> None:
    """Dibuja un círculo rojo centrado en (cx, cy)."""
    r = size // 2
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=(220, 30, 30, 230),
        outline=(255, 255, 255, 255),
        width=1,
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
    base = _fetch_image(osm_url, is_osm=True)
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

    # Círculo rojo en el centro del tile = ubicación del usuario
    draw = ImageDraw.Draw(base)
    cx = tile_size // 2
    cy = tile_size // 2
    _draw_home_icon(draw, cx, cy, size=10)

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
        self._attr_content_type = "image/gif"

        # Velocidad del GIF en ms por frame (configurable por el usuario)
        config = {**entry.data, **entry.options}
        self._gif_speed: int = config.get("gif_speed", DEFAULT_GIF_SPEED)

        # Buffer circular de imágenes PIL compuestas (no PNG, para armar el GIF)
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
        """Llamado cuando el coordinador tiene datos nuevos — genera GIF en background."""
        data = self.coordinator.data
        if not data:
            return

        # Refrescar gif_speed por si el usuario lo cambió en opciones
        config = {**self._entry.data, **self._entry.options}
        self._gif_speed = config.get("gif_speed", DEFAULT_GIF_SPEED)

        radar_url = data.get("last_radar_url")
        last_time = data.get("last_radar_time")
        zoom = config.get("zoom", 7)
        tile_x = config.get("tile_x", 28)
        tile_y = config.get("tile_y", 54)

        if not radar_url:
            return

        # OSM tile URL
        osm_url = f"https://a.tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"

        # Generar imagen compuesta en executor y luego reconstruir GIF
        self.hass.async_add_executor_job(
            self._generate_and_store, osm_url, radar_url, last_time
        )
        super()._handle_coordinator_update()

    def _build_gif(self) -> bytes | None:
        """Construye un GIF animado con todos los frames del buffer."""
        frames = list(self._history)
        if not frames:
            return None

        pil_frames = [f["pil"] for f in frames]
        duration = self._gif_speed  # ms por frame

        buf = io.BytesIO()
        pil_frames[0].save(
            buf,
            format="GIF",
            save_all=True,
            append_images=pil_frames[1:],
            loop=0,           # loop infinito
            duration=duration,
            optimize=False,
        )
        return buf.getvalue()

    def _generate_and_store(self, osm_url: str, radar_url: str, timestamp) -> None:
        """Genera la imagen compuesta, la agrega al buffer y reconstruye el GIF."""
        png_bytes = _build_composite(osm_url, radar_url)
        if png_bytes is None:
            return

        # Convertir a PIL para el GIF (necesitamos paleta P para GIF)
        pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256)

        with self._lock:
            # Evitar duplicados
            if not self._history or self._history[-1]["radar_url"] != radar_url:
                self._history.append({
                    "timestamp": timestamp,
                    "radar_url": radar_url,
                    "pil":       pil_img,
                })

            # Reconstruir GIF con todos los frames acumulados
            self._current_image = self._build_gif()

        log.debug(
            "RainViewer Camera: GIF actualizado — %d frames @ %dms (%d bytes)",
            len(self._history), self._gif_speed,
            len(self._current_image) if self._current_image else 0,
        )

    def camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        with self._lock:
            return self._current_image

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        with self._lock:
            if self._current_image:
                return self._current_image

        # Generar GIF inmediatamente si no hay caché
        data = self.coordinator.data
        if not data:
            return None

        radar_url = data.get("last_radar_url")
        if not radar_url:
            return None

        config = {**self._entry.data, **self._entry.options}
        zoom   = config.get("zoom",   7)
        tile_x = config.get("tile_x", 28)
        tile_y = config.get("tile_y", 54)
        osm_url = f"https://a.tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"

        await self.hass.async_add_executor_job(
            self._generate_and_store, osm_url, radar_url, data.get("last_radar_time")
        )

        with self._lock:
            return self._current_image
