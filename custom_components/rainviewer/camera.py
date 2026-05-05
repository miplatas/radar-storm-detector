"""Cámara RainViewer — imagen compuesta: OSM + radar RGBA + HUD."""

from __future__ import annotations

import io
import logging
import math
from collections import deque
from datetime import datetime, timezone
from threading import Lock

import requests
from PIL import Image, ImageDraw, ImageFont

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DEFAULT_FRAMES_N, DEFAULT_GIF_SPEED
from .coordinator import RainViewerCoordinator

log = logging.getLogger(__name__)

HISTORY_SIZE = DEFAULT_FRAMES_N
TILE_SIZE = 256

_DBZ_LEVELS = [
    (5,  (4,   233, 231)),
    (10, (1,   159, 244)),
    (15, (3,   0,   244)),
    (20, (2,   253, 2)),
    (25, (1,   197, 1)),
    (30, (0,   142, 0)),
    (35, (253, 248, 2)),
    (40, (229, 188, 0)),
    (45, (253, 149, 0)),
    (50, (253, 0,   0)),
    (55, (212, 0,   0)),
    (60, (188, 0,   0)),
    (65, (248, 0,   253)),
    (70, (152, 84,  198)),
    (75, (255, 255, 255)),
]

# Fuentes cargadas una sola vez al importar el módulo
try:
    _FONT_BOLD  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
    _FONT_SMALL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
    _FONT_TINY  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 7)
except Exception:
    _FONT_BOLD  = ImageFont.load_default()
    _FONT_SMALL = _FONT_BOLD
    _FONT_TINY  = _FONT_BOLD


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RainViewerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RainViewerCamera(coordinator, entry)])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_image(url: str, is_osm: bool = False) -> Image.Image | None:
    headers = {}
    if is_osm:
        headers["User-Agent"] = "RainViewerHA/1.2 (Home Assistant; github.com/miplatas/rainviewer_hacs)"
    try:
        r = requests.get(url, timeout=10, headers=headers)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        log.warning("No se pudo cargar imagen: %s → %s", url, e)
        return None


def _lat_lon_to_pixel(lat: float, lon: float, tile_x: int, tile_y: int,
                      zoom: int, tile_size: int = TILE_SIZE) -> tuple[int, int]:
    n = 2 ** zoom
    gx = (lon + 180.0) / 360.0 * n * tile_size
    lat_rad = math.radians(lat)
    gy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * tile_size
    px = int(gx - tile_x * tile_size)
    py = int(gy - tile_y * tile_size)
    return px, py


def _build_base_image(osm_url: str, radar_url: str,
                      lat: float, lon: float,
                      tile_x: int, tile_y: int, zoom: int,
                      tile_size: int = TILE_SIZE) -> Image.Image | None:
    """
    Descarga OSM + radar y devuelve imagen RGB compuesta.
    Se llama UNA SOLA VEZ por frame nuevo — el resultado se cachea.
    """
    base = _fetch_image(osm_url, is_osm=True)
    if base is None:
        base = Image.new("RGBA", (tile_size, tile_size), (200, 200, 200, 255))
    else:
        base = base.resize((tile_size, tile_size)).convert("RGBA")

    radar = _fetch_image(radar_url)
    if radar is not None:
        radar = radar.resize((tile_size, tile_size)).convert("RGBA")
        r, g, b, a = radar.split()
        a = a.point(lambda v: int(v * 0.85))
        radar = Image.merge("RGBA", (r, g, b, a))
        base = Image.alpha_composite(base, radar)
        radar.close()

    draw = ImageDraw.Draw(base, "RGBA")
    cx, cy = _lat_lon_to_pixel(lat, lon, tile_x, tile_y, zoom, tile_size)
    cx = max(5, min(tile_size - 5, cx))
    cy = max(5, min(tile_size - 5, cy))
    rv = 5
    draw.ellipse([cx - rv, cy - rv, cx + rv, cy + rv],
                 fill=(220, 30, 30, 230), outline=(255, 255, 255, 255), width=2)

    return base.convert("RGB")


def _apply_hud(base_rgb: Image.Image, timestamp,
               frame_index: int, frame_total: int,
               tile_size: int = TILE_SIZE) -> Image.Image:
    """
    Aplica HUD (barra progreso + leyenda dBZ + footer) sobre copia de base_rgb.
    NO hace ninguna descarga de red.
    """
    img = base_rgb.copy().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    bar_h    = 6
    footer_h = 30

    # Barra de progreso
    draw.rectangle([0, 0, tile_size, bar_h + 2], fill=(0, 0, 0, 120))
    fill_w = int(tile_size * (frame_index + 1) / max(frame_total, 1))
    draw.rectangle([0, 0, fill_w, bar_h], fill=(30, 180, 255, 220))

    # Footer
    draw.rectangle([0, tile_size - footer_h, tile_size, tile_size], fill=(0, 0, 0, 160))

    try:
        ts_text = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        ts_text = str(timestamp) if timestamp else "—"
    try:
        bbox = _FONT_BOLD.getbbox(ts_text)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(ts_text) * 6
    draw.text((max(0, (tile_size - tw) // 2), tile_size - footer_h + 2),
              ts_text, fill=(255, 255, 255, 255), font=_FONT_BOLD)

    attr_text = "Map © OpenStreetMap  |  Radar © RainViewer"
    try:
        bbox2 = _FONT_SMALL.getbbox(attr_text)
        aw = bbox2[2] - bbox2[0]
    except Exception:
        aw = len(attr_text) * 5
    draw.text((max(0, (tile_size - aw) // 2), tile_size - footer_h + 16),
              attr_text, fill=(200, 200, 200, 200), font=_FONT_SMALL)

    # Leyenda dBZ
    legend_top    = bar_h + 4
    legend_bottom = tile_size - footer_h - 4
    band_h = (legend_bottom - legend_top) / len(_DBZ_LEVELS)
    draw.rectangle([0, bar_h + 2, 28, tile_size - footer_h], fill=(0, 0, 0, 140))

    for i, (dbz_val, (rv, gv, bv)) in enumerate(_DBZ_LEVELS):
        y0 = int(legend_top + i * band_h)
        y1 = int(legend_top + (i + 1) * band_h)
        draw.rectangle([2, y0, 12, y1], fill=(rv, gv, bv, 255))
        if i % 2 == 0:
            draw.text((14, y0), str(dbz_val), fill=(255, 255, 255, 230), font=_FONT_TINY)

    return img.convert("RGB")


# ---------------------------------------------------------------------------
# Entidad Camera
# ---------------------------------------------------------------------------

class RainViewerCamera(CoordinatorEntity, Camera):
    """
    Cámara RainViewer con GIF animado.
    - Descarga OSM + radar UNA SOLA VEZ por frame nuevo (cachea Image RGB)
    - _build_gif solo aplica HUD sobre imágenes ya cacheadas (sin red)
    - Libera memoria correctamente al cerrar frames
    """

    def __init__(self, coordinator: RainViewerCoordinator, entry: ConfigEntry):
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)

        self._entry = entry
        self._attr_name = "RainViewer Radar Image"
        self._attr_unique_id = f"rainviewer_{entry.entry_id}_camera"
        self._attr_icon = "mdi:radar"
        self._attr_content_type = "image/gif"

        config = {**entry.data, **entry.options}
        self._gif_speed: int = config.get("gif_speed", DEFAULT_GIF_SPEED)

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
        return {
            "history": [
                {"timestamp": f["timestamp"], "radar_url": f["radar_url"]}
                for f in self._history
            ],
            "frames_in_buffer": len(self._history),
        }

    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if not data:
            return

        config = {**self._entry.data, **self._entry.options}
        self._gif_speed = config.get("gif_speed", DEFAULT_GIF_SPEED)

        radar_url = data.get("last_radar_url")
        last_time = data.get("last_radar_time")
        if not radar_url:
            return

        zoom   = config.get("zoom",      7)
        tile_x = config.get("tile_x",   28)
        tile_y = config.get("tile_y",   54)
        lat    = config.get("latitude",  0.0)
        lon    = config.get("longitude", 0.0)
        osm_url = f"https://a.tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"

        self.hass.async_add_executor_job(
            self._fetch_and_store,
            osm_url, radar_url, last_time, lat, lon, tile_x, tile_y, zoom,
        )
        super()._handle_coordinator_update()

    def _fetch_and_store(self, osm_url: str, radar_url: str, timestamp,
                         lat: float, lon: float,
                         tile_x: int, tile_y: int, zoom: int) -> None:
        """Descarga base solo si el radar_url es nuevo, luego reconstruye GIF."""
        with self._lock:
            already = any(f["radar_url"] == radar_url for f in self._history)

        if not already:
            base_img = _build_base_image(osm_url, radar_url, lat, lon, tile_x, tile_y, zoom)
            if base_img is None:
                return
            with self._lock:
                # Si el deque está lleno, cerrar la imagen más antigua antes de descartar
                if len(self._history) == HISTORY_SIZE:
                    old = self._history[0]
                    try:
                        old["base_image"].close()
                    except Exception:
                        pass
                self._history.append({
                    "timestamp":  timestamp,
                    "radar_url":  radar_url,
                    "base_image": base_img,
                })

        gif = self._build_gif()
        with self._lock:
            self._current_image = gif

        log.debug("RainViewer Camera: GIF %d frames @ %dms (%d bytes)",
                  len(self._history), self._gif_speed, len(gif) if gif else 0)

    def _build_gif(self) -> bytes | None:
        """Construye GIF aplicando HUD sobre imágenes cacheadas. Sin red."""
        with self._lock:
            frames = list(self._history)

        if not frames:
            return None

        total = len(frames)
        pil_frames = []

        for i, f in enumerate(frames):
            base = f.get("base_image")
            if base is None:
                continue
            framed = _apply_hud(base, f["timestamp"], i, total)
            pil_frames.append(framed.convert("P", palette=Image.ADAPTIVE, colors=256))
            framed.close()

        if not pil_frames:
            return None

        buf = io.BytesIO()
        pil_frames[0].save(
            buf, format="GIF", save_all=True,
            append_images=pil_frames[1:],
            loop=0, duration=self._gif_speed, optimize=False,
        )
        for f in pil_frames:
            try:
                f.close()
            except Exception:
                pass

        return buf.getvalue()

    def camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        with self._lock:
            return self._current_image

    async def async_camera_image(self,
                                  width: int | None = None,
                                  height: int | None = None) -> bytes | None:
        with self._lock:
            if self._current_image:
                return self._current_image

        data = self.coordinator.data
        if not data:
            return None
        radar_url = data.get("last_radar_url")
        if not radar_url:
            return None

        config = {**self._entry.data, **self._entry.options}
        zoom   = config.get("zoom",      7)
        tile_x = config.get("tile_x",   28)
        tile_y = config.get("tile_y",   54)
        lat    = config.get("latitude",  0.0)
        lon    = config.get("longitude", 0.0)
        osm_url = f"https://a.tile.openstreetmap.org/{zoom}/{tile_x}/{tile_y}.png"

        await self.hass.async_add_executor_job(
            self._fetch_and_store,
            osm_url, radar_url, data.get("last_radar_time"),
            lat, lon, tile_x, tile_y, zoom,
        )

        with self._lock:
            return self._current_image

    async def async_will_remove_from_hass(self) -> None:
        """Libera imágenes PIL cacheadas al remover la entidad."""
        with self._lock:
            for f in self._history:
                try:
                    f["base_image"].close()
                except Exception:
                    pass
            self._history.clear()
            self._current_image = None
