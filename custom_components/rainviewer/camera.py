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
from PIL import Image, ImageDraw, ImageFont

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


def _draw_home_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int = 18) -> None:
    """Dibuja un círculo rojo centrado en (cx, cy)."""
    r = size // 2
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=(220, 30, 30, 230),
        outline=(255, 255, 255, 255),
        width=2,
    )


def _lat_lon_to_pixel(lat: float, lon: float, tile_x: int, tile_y: int,
                      zoom: int, tile_size: int = TILE_SIZE) -> tuple[int, int]:
    """
    Calcula la posición en píxeles (px, py) de una coordenada lat/lon
    dentro del tile (tile_x, tile_y) al nivel de zoom dado.
    """
    n = 2 ** zoom
    # Posición global en píxeles
    gx = (lon + 180.0) / 360.0 * n * tile_size
    lat_rad = math.radians(lat)
    gy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * tile_size
    # Posición relativa dentro del tile
    px = int(gx - tile_x * tile_size)
    py = int(gy - tile_y * tile_size)
    return px, py


def _build_composite(
    osm_url: str,
    radar_url: str,
    timestamp: str = "",
    frame_index: int = 0,
    frame_total: int = 1,
    lat: float = 0.0,
    lon: float = 0.0,
    tile_x: int = 0,
    tile_y: int = 0,
    zoom: int = 7,
    tile_size: int = TILE_SIZE,
) -> bytes | None:
    """
    Construye imagen compuesta:
      1. Capa base: tile OSM
      2. Capa radar: imagen RGBA de RainViewer
      3. Círculo rojo en la posición exacta de lat/lon del usuario
      4. HUD: barra de progreso arriba + timestamp + atribución abajo
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
        r, g, b, a = radar.split()
        a = a.point(lambda v: int(v * 0.85))
        radar = Image.merge("RGBA", (r, g, b, a))
        base = Image.alpha_composite(base, radar)

    draw = ImageDraw.Draw(base, "RGBA")

    # 3. Círculo rojo en la posición exacta del usuario
    cx, cy = _lat_lon_to_pixel(lat, lon, tile_x, tile_y, zoom, tile_size)
    # Clamp por si cae fuera del tile
    cx = max(5, min(tile_size - 5, cx))
    cy = max(5, min(tile_size - 5, cy))
    _draw_home_icon(draw, cx, cy, size=10)

    # 4. HUD — barra de progreso (arriba)
    bar_h = 6
    bar_bg_color  = (0, 0, 0, 120)
    bar_fill_color = (30, 180, 255, 220)

    # fondo oscuro de la barra
    draw.rectangle([0, 0, tile_size, bar_h + 2], fill=bar_bg_color)

    # relleno proporcional al frame actual
    if frame_total > 1:
        fill_w = int(tile_size * (frame_index + 1) / frame_total)
    else:
        fill_w = tile_size
    draw.rectangle([0, 0, fill_w, bar_h], fill=bar_fill_color)

    # 5. HUD — footer (abajo): timestamp + atribución
    label_h = 30  # dos líneas
    draw.rectangle([0, tile_size - label_h, tile_size, tile_size], fill=(0, 0, 0, 160))

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
        font_attr = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
    except Exception:
        font = ImageFont.load_default()
        font_attr = font

    # Línea 1 — timestamp centrado
    try:
        from datetime import datetime, timezone
        ts_text = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        ts_text = str(timestamp) if timestamp else "—"
    try:
        bbox = font.getbbox(ts_text)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(ts_text) * 6
    tx = max(0, (tile_size - tw) // 2)
    ty = tile_size - label_h + 2
    draw.text((tx, ty), ts_text, fill=(255, 255, 255, 255), font=font)

    # Línea 2 — atribución
    attr_text = "Map © OpenStreetMap  |  Radar © RainViewer"
    try:
        bbox2 = font_attr.getbbox(attr_text)
        aw = bbox2[2] - bbox2[0]
    except Exception:
        aw = len(attr_text) * 5
    ax = max(0, (tile_size - aw) // 2)
    ay = tile_size - label_h + 16
    draw.text((ax, ay), attr_text, fill=(200, 200, 200, 200), font=font_attr)

    # 6. Leyenda dBZ — franja vertical a la izquierda
    legend_w = 28          # ancho total de la leyenda
    legend_x0 = 0
    bar_x0 = legend_x0 + 2
    bar_x1 = legend_x0 + 12
    label_x = bar_x1 + 2

    # Rango dBZ de la leyenda
    dbz_levels = [
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

    # Fondo semitransparente de la leyenda
    draw.rectangle(
        [legend_x0, bar_h + 2, legend_x0 + legend_w, tile_size - label_h],
        fill=(0, 0, 0, 140),
    )

    # Área útil para la barra de colores (entre barra de progreso y timestamp)
    legend_top    = bar_h + 4
    legend_bottom = tile_size - 30 - 4  # respetar footer de 30px
    legend_height = legend_bottom - legend_top
    n = len(dbz_levels)
    band_h = legend_height / n

    for i, (dbz_val, (r, g, b)) in enumerate(dbz_levels):
        y0 = int(legend_top + i * band_h)
        y1 = int(legend_top + (i + 1) * band_h)
        draw.rectangle([bar_x0, y0, bar_x1, y1], fill=(r, g, b, 255))

        # Etiqueta numérica cada 2 niveles para no saturar
        if i % 2 == 0:
            try:
                font_sm = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 7
                )
            except Exception:
                font_sm = ImageFont.load_default()
            draw.text(
                (label_x, y0),
                str(dbz_val),
                fill=(255, 255, 255, 230),
                font=font_sm,
            )

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
            self._generate_and_store, osm_url, radar_url, last_time,
            config.get("latitude", 0.0), config.get("longitude", 0.0),
            tile_x, tile_y, zoom,
        )
        super()._handle_coordinator_update()

    def _generate_and_store(self, osm_url: str, radar_url: str, timestamp,
                            lat: float = 0.0, lon: float = 0.0,
                            tile_x: int = 0, tile_y: int = 0, zoom: int = 7) -> None:
        """Genera la imagen compuesta, la agrega al buffer y reconstruye el GIF."""
        png_bytes = _build_composite(
            osm_url, radar_url, timestamp=timestamp,
            frame_index=0, frame_total=1,
            lat=lat, lon=lon, tile_x=tile_x, tile_y=tile_y, zoom=zoom,
        )
        if png_bytes is None:
            return

        with self._lock:
            if not self._history or self._history[-1]["radar_url"] != radar_url:
                self._history.append({
                    "timestamp": timestamp,
                    "radar_url": radar_url,
                    "osm_url":   osm_url,
                    "radar_raw": radar_url,
                    "lat":       lat,
                    "lon":       lon,
                    "tile_x":    tile_x,
                    "tile_y":    tile_y,
                    "zoom":      zoom,
                })

            self._current_image = self._build_gif()

        log.debug(
            "RainViewer Camera: GIF actualizado — %d frames @ %dms (%d bytes)",
            len(self._history), self._gif_speed,
            len(self._current_image) if self._current_image else 0,
        )

    def _build_gif(self) -> bytes | None:
        """Construye un GIF animado con HUD por frame (barra de progreso + timestamp)."""
        frames = list(self._history)
        if not frames:
            return None

        total = len(frames)
        pil_frames = []

        for i, f in enumerate(frames):
            png = _build_composite(
                f["osm_url"],
                f["radar_raw"],
                timestamp=f["timestamp"],
                frame_index=i,
                frame_total=total,
                lat=f.get("lat", 0.0),
                lon=f.get("lon", 0.0),
                tile_x=f.get("tile_x", 0),
                tile_y=f.get("tile_y", 0),
                zoom=f.get("zoom", 7),
            )
            if png is None:
                continue
            pil_img = Image.open(io.BytesIO(png)).convert("RGB").convert(
                "P", palette=Image.ADAPTIVE, colors=256
            )
            pil_frames.append(pil_img)

        if not pil_frames:
            return None

        buf = io.BytesIO()
        pil_frames[0].save(
            buf,
            format="GIF",
            save_all=True,
            append_images=pil_frames[1:],
            loop=0,
            duration=self._gif_speed,
            optimize=False,
        )
        return buf.getvalue()

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
            self._generate_and_store, osm_url, radar_url, data.get("last_radar_time"),
            config.get("latitude", 0.0), config.get("longitude", 0.0),
            tile_x, tile_y, zoom,
        )

        with self._lock:
            return self._current_image
