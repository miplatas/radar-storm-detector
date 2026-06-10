"""Radar camera - composite image: OSM + radar RGBA + HUD."""

from __future__ import annotations

import io
import logging
import math
from collections import deque, OrderedDict
from datetime import datetime, timezone
from datetime import timedelta
from threading import Lock
import re
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    DEFAULT_FRAMES_N,
    DEFAULT_GIF_SPEED,
    CONF_MAP_STYLE,
    CONF_TIMEZONE,
    DEFAULT_MAP_STYLE,
    MAP_TILE_URLS,
    CONF_TEST_DRAW_PROXIMITY_CIRCLES,
    DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES,
)
from .coordinator import RainViewerCoordinator
from .radar import build_dbz_array, _LUT_RGB

log = logging.getLogger(__name__)

HISTORY_SIZE = DEFAULT_FRAMES_N
TILE_SIZE = 256
IMAGE_CACHE_MAX_ITEMS = 24
EARTH_RADIUS_M = 6378137.0

_IMAGE_CACHE_LOCK = Lock()
_IMAGE_BYTES_CACHE: OrderedDict[str, bytes] = OrderedDict()

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

# Fonts loaded only once at module import
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
    async_add_entities([
        RainViewerCamera(coordinator, entry),
        RainViewerColorScaleCamera(coordinator, entry),
        RainViewerDbzGrayCamera(coordinator, entry),
    ])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_image(url: str, is_osm: bool = False) -> Image.Image | None:
    with _IMAGE_CACHE_LOCK:
        cached = _IMAGE_BYTES_CACHE.get(url)
        if cached is not None:
            _IMAGE_BYTES_CACHE.move_to_end(url)

    headers = {}
    if is_osm:
        headers["User-Agent"] = "RadarStormDetectorHA/1.2 (Home Assistant; github.com/miplatas/radar-storm-detector)"

    content = cached
    if content is None:
        try:
            with requests.get(url, timeout=10, headers=headers) as r:
                r.raise_for_status()
                content = r.content
        except Exception as e:
            log.warning("Could not load image: %s -> %s", url, e)
            return None

        with _IMAGE_CACHE_LOCK:
            _IMAGE_BYTES_CACHE[url] = content
            _IMAGE_BYTES_CACHE.move_to_end(url)
            while len(_IMAGE_BYTES_CACHE) > IMAGE_CACHE_MAX_ITEMS:
                _IMAGE_BYTES_CACHE.popitem(last=False)

    try:
        with Image.open(io.BytesIO(content)) as img:
            return img.convert("RGBA")
    except Exception as e:
        log.warning("Could not decode image: %s -> %s", url, e)
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


def _km_per_pixel(lat: float, zoom: int, tile_size: int = TILE_SIZE) -> float:
    """Ground resolution in kilometers per pixel for XYZ/Web Mercator tiles."""
    lat_rad = math.radians(lat)
    meters_per_px = (
        math.cos(lat_rad) * 2.0 * math.pi * EARTH_RADIUS_M /
        (tile_size * (2 ** zoom))
    )
    return max(meters_per_px / 1000.0, 0.0)


def _resolve_timezone(tz_name: str | None):
    if tz_name:
        match = re.fullmatch(r"GMT\s*([+-])\s*(\d{1,2})", tz_name)
        if match:
            sign, hours = match.groups()
            offset_hours = int(hours) * (1 if sign == "+" else -1)
            return timezone(timedelta(hours=offset_hours)), f"GMT {offset_hours:+d}"

        match = re.fullmatch(r"UTC([+-])(\d{2}):00", tz_name)
        if match:
            sign, hours = match.groups()
            offset_hours = int(hours) * (1 if sign == "+" else -1)
            return timezone(timedelta(hours=offset_hours)), f"GMT {offset_hours:+d}"

        try:
            return ZoneInfo(tz_name), tz_name
        except Exception:
            pass

    return timezone.utc, "UTC"


def _build_base_image(osm_url: str, radar_url: str,
                      lat: float, lon: float,
                      tile_x: int, tile_y: int, zoom: int,
                      tile_size: int = TILE_SIZE) -> Image.Image | None:
    """
    Downloads OSM + radar and returns a composed RGB image.
    Called ONLY ONCE per new frame - the result is cached.
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

    return base.convert("RGB")


def _apply_hud(base_rgb: Image.Image, timestamp,
               frame_index: int, frame_total: int,
               draw_test_circles: bool = False,
               home_px: tuple[int, int] | None = None,
               dist_mean: float | None = None,
               dist_max: float | None = None,
               km_per_px: float = 1.0,
               bearing_mean: float | None = None,
               target_tz=timezone.utc,
               tz_label: str = "UTC",
               tile_size: int = TILE_SIZE) -> Image.Image:
    """
    Applies HUD (progress bar + dBZ legend + footer) over a copy of base_rgb.
    No network downloads happen here.
    """
    img = base_rgb.copy().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    bar_h    = 6
    footer_h = 30

    # Layer: home marker (casa)
    if home_px is not None:
        hx = max(5, min(tile_size - 5, int(home_px[0])))
        hy = max(5, min(tile_size - 5, int(home_px[1])))
        rv = 5
        draw.ellipse([hx - rv, hy - rv, hx + rv, hy + rv],
                     fill=(220, 30, 30, 230), outline=(255, 255, 255, 255), width=2)

    # Layer: circles and bearing line
    if draw_test_circles and home_px is not None:
        hx = max(0, min(tile_size - 1, int(home_px[0])))
        hy = max(0, min(tile_size - 1, int(home_px[1])))
        px_per_km = 1.0 / km_per_px if km_per_px > 0 else 0.0

        if dist_mean is not None and dist_mean >= 0:
            r = int(round(dist_mean * px_per_km))
            draw.ellipse([hx - r, hy - r, hx + r, hy + r], outline=(0, 255, 255, 220), width=2)

        if dist_max is not None and dist_max >= 0:
            r = int(round(dist_max * px_per_km))
            draw.ellipse([hx - r, hy - r, hx + r, hy + r], outline=(255, 80, 255, 220), width=2)

        if bearing_mean is not None and dist_mean is not None and dist_mean >= 0:
            ang = math.radians(float(bearing_mean))
            dist_mean_px = dist_mean * px_per_km
            ex = int(round(hx + dist_mean_px * math.sin(ang)))
            ey = int(round(hy - dist_mean_px * math.cos(ang)))
            draw.line([(hx, hy), (ex, ey)], fill=(255, 255, 255, 230), width=2)

    # Progress bar
    draw.rectangle([0, 0, tile_size, bar_h + 2], fill=(0, 0, 0, 120))
    fill_w = int(tile_size * (frame_index + 1) / max(frame_total, 1))
    draw.rectangle([0, 0, fill_w, bar_h], fill=(30, 180, 255, 220))

    # Footer
    draw.rectangle([0, tile_size - footer_h, tile_size, tile_size], fill=(0, 0, 0, 160))

    try:
        dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).astimezone(target_tz)
        ts_text = dt.strftime(f"%Y-%m-%d %H:%M {tz_label}")
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

    # dBZ legend
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

    #if draw_test_circles and home_px is not None:
    #    draw.text((9, tile_size - footer_h - 12), "     C", fill=(255, 255, 0, 230), font=_FONT_TINY)

    return img.convert("RGB")


# ---------------------------------------------------------------------------
# Camera entity
# ---------------------------------------------------------------------------

class RainViewerCamera(CoordinatorEntity, Camera):
    """
    RainViewer camera with animated GIF.
    - Downloads OSM + radar only once per new frame (caches RGB Image)
    - _build_gif only applies HUD over cached images (no network)
    - Releases memory properly when closing frames
    """

    def __init__(self, coordinator: RainViewerCoordinator, entry: ConfigEntry):
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)

        self._entry = entry
        self._attr_name = "Radar Image"
        self._attr_unique_id = f"radar_storm_detector_{entry.entry_id}_camera"
        self._attr_icon = "mdi:radar"
        self._attr_content_type = "image/gif"

        config = {**entry.data, **entry.options}
        self._gif_speed: int = config.get("gif_speed", DEFAULT_GIF_SPEED)
        self._draw_test_circles: bool = config.get(
            CONF_TEST_DRAW_PROXIMITY_CIRCLES,
            DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES,
        )

        self._history: deque[dict] = deque(maxlen=HISTORY_SIZE)
        self._lock = Lock()
        self._current_image: bytes | None = None
        self._last_render_url: str | None = None
        self._last_render_cycle_ts: int | None = None
        self._job_running = False
        self._target_tz = timezone.utc
        self._tz_label = "UTC"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Storm Detector",
            "manufacturer": "Radar",
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
        self._draw_test_circles = config.get(
            CONF_TEST_DRAW_PROXIMITY_CIRCLES,
            DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES,
        )

        radar_url = data.get("last_radar_url")
        last_time = data.get("last_radar_time")
        if not radar_url:
            return

        with self._lock:
            if self._job_running:
                super()._handle_coordinator_update()
                return

        zoom   = config.get("zoom",      7)
        tile_x = config.get("tile_x",   28)
        tile_y = config.get("tile_y",   54)
        lat    = config.get("latitude",  0.0)
        lon    = config.get("longitude", 0.0)
        cycle_ts = data.get("timestamp")
        tz_name = config.get(CONF_TIMEZONE) or getattr(self.hass.config, "time_zone", None)
        resolved_tz, tz_label = _resolve_timezone(tz_name)
        with self._lock:
            self._target_tz = resolved_tz
            self._tz_label = tz_label
        map_style = config.get(CONF_MAP_STYLE, DEFAULT_MAP_STYLE)
        osm_url = MAP_TILE_URLS.get(map_style, MAP_TILE_URLS["day"]).format(
            zoom=zoom, x=tile_x, y=tile_y
        )
        home_px = _lat_lon_to_pixel(lat, lon, tile_x, tile_y, zoom)

        frame_meta = {}
        for fr in data.get("frames", []):
            ts = fr.get("timestamp")
            frame_meta[ts] = {
                "dist_mean": fr.get("dist_mean"),
                "dist_max": fr.get("dist_max"),
                "bearing_mean": fr.get("bearing_mean"),
            }

        with self._lock:
            if cycle_ts == self._last_render_cycle_ts and self._current_image is not None:
                super()._handle_coordinator_update()
                return
            self._job_running = True

        async def _run_job() -> None:
            try:
                await self.hass.async_add_executor_job(
                    self._fetch_and_store,
                    osm_url, radar_url, last_time, lat, lon, tile_x, tile_y, zoom,
                    home_px, frame_meta,
                )
                with self._lock:
                    self._last_render_url = radar_url
                    self._last_render_cycle_ts = cycle_ts
            finally:
                with self._lock:
                    self._job_running = False

        self.hass.async_create_task(_run_job())
        super()._handle_coordinator_update()

    def _fetch_and_store(self, osm_url: str, radar_url: str, timestamp,
                         lat: float, lon: float,
                         tile_x: int, tile_y: int, zoom: int,
                         home_px: tuple[int, int], frame_meta: dict) -> None:
        """Fetches base only if radar_url is new, then rebuilds GIF."""
        with self._lock:
            already = any(f["radar_url"] == radar_url for f in self._history)

        if not already:
            base_img = _build_base_image(osm_url, radar_url, lat, lon, tile_x, tile_y, zoom)
            if base_img is None:
                return
            with self._lock:
                # If deque is full, close oldest image before discarding
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
                    "home_px":    home_px,
                    "km_per_px":  _km_per_pixel(lat, zoom),
                    "meta":       frame_meta.get(timestamp, {}),
                })

        gif = self._build_gif()
        with self._lock:
            self._current_image = gif

        log.debug("Radar Storm Detector camera: GIF %d frames @ %dms (%d bytes)",
                  len(self._history), self._gif_speed, len(gif) if gif else 0)

    def _build_gif(self) -> bytes | None:
        """Builds GIF by applying HUD on cached images. No network."""
        with self._lock:
            frames = list(self._history)

        if not frames:
            return None

        total = len(frames)
        pil_frames = []
        with self._lock:
            target_tz = self._target_tz
            tz_label = self._tz_label

        for i, f in enumerate(frames):
            base = f.get("base_image")
            if base is None:
                continue
            meta = f.get("meta", {})
            framed = _apply_hud(
                base,
                f["timestamp"],
                i,
                total,
                draw_test_circles=self._draw_test_circles,
                home_px=f.get("home_px"),
                dist_mean=meta.get("dist_mean"),
                dist_max=meta.get("dist_max"),
                km_per_px=f.get("km_per_px", 1.0),
                bearing_mean=meta.get("bearing_mean"),
                target_tz=target_tz,
                tz_label=tz_label,
            )
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
            if self._job_running:
                return None

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
        map_style = config.get(CONF_MAP_STYLE, DEFAULT_MAP_STYLE)
        osm_url = MAP_TILE_URLS.get(map_style, MAP_TILE_URLS["day"]).format(
            zoom=zoom, x=tile_x, y=tile_y
        )

        with self._lock:
            self._job_running = True
        try:
            await self.hass.async_add_executor_job(
                self._fetch_and_store,
                osm_url, radar_url, data.get("last_radar_time"),
                lat, lon, tile_x, tile_y, zoom,
                _lat_lon_to_pixel(lat, lon, tile_x, tile_y, zoom),
                {
                    fr.get("timestamp"): {
                        "dist_mean": fr.get("dist_mean"),
                        "dist_max": fr.get("dist_max"),
                        "bearing_mean": fr.get("bearing_mean"),
                    }
                    for fr in data.get("frames", [])
                },
            )
            with self._lock:
                self._last_render_url = radar_url
                self._last_render_cycle_ts = data.get("timestamp")
        finally:
            with self._lock:
                self._job_running = False

        with self._lock:
            return self._current_image

    async def async_will_remove_from_hass(self) -> None:
        """Releases cached PIL images when removing the entity."""
        with self._lock:
            for f in self._history:
                try:
                    f["base_image"].close()
                except Exception:
                    pass
            self._history.clear()
            self._current_image = None
            self._last_render_url = None
            self._last_render_cycle_ts = None
            self._job_running = False


# ---------------------------------------------------------------------------
# Helper: dBZ scale bar
# ---------------------------------------------------------------------------

def _add_dbz_scale_bar(base: Image.Image, gray: bool = False) -> Image.Image:
    """
    Adds a vertical dBZ scale bar to the right of *base*.
    If gray=True, draws grayscale bar; otherwise LUT colors.
    Returns a new RGB image.
    """
    import numpy as np

    bw, bh = base.size
    bar_w  = 86
    canvas = Image.new("RGB", (bw + bar_w, bh), (0, 0, 0))
    canvas.paste(base.convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(canvas)

    bar_x0, bar_x1 = bw + 10, bw + 30
    y0, y1 = 6, bh - 7
    bar_range = max(1, y1 - y0)

    for y in range(y0, y1 + 1):
        z = 75.0 * (1.0 - (y - y0) / bar_range)
        if gray:
            gv = int(np.clip((z / 75.0) * 255.0, 0, 255))
            draw.line([(bar_x0, y), (bar_x1, y)], fill=(gv, gv, gv))
        else:
            idx = int(np.clip(round(z), 0, len(_LUT_RGB) - 1))
            rr, gg, bb = int(_LUT_RGB[idx][0]), int(_LUT_RGB[idx][1]), int(_LUT_RGB[idx][2])
            draw.line([(bar_x0, y), (bar_x1, y)], fill=(rr, gg, bb))

    outline = (200, 200, 200)
    draw.rectangle([(bar_x0, y0), (bar_x1, y1)], outline=outline, width=1)
    for tick in [0, 15, 30, 45, 55, 60, 75]:
        ty = int(y0 + (1.0 - tick / 75.0) * bar_range)
        draw.line([(bar_x1 + 1, ty), (bar_x1 + 5, ty)], fill=outline)
        draw.text((bar_x1 + 7, ty - 5), str(tick), fill=outline, font=_FONT_TINY)
    draw.text((bar_x0, 0), "dBZ", fill=outline, font=_FONT_BOLD)

    return canvas


# ---------------------------------------------------------------------------
# Camera: radar tile color image + dBZ scale
# ---------------------------------------------------------------------------

class RainViewerColorScaleCamera(CoordinatorEntity, Camera):
    """
    Static image of latest radar tile in original color
    with dBZ scale bar on the right.
    """

    def __init__(self, coordinator: RainViewerCoordinator, entry: ConfigEntry):
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._entry = entry
        self._attr_name = "Radar Color dBZ"
        self._attr_unique_id = f"radar_storm_detector_{entry.entry_id}_color_scale"
        self._attr_icon = "mdi:palette"
        self._attr_content_type = "image/png"
        self._lock = Lock()
        self._current_image: bytes | None = None
        self._last_url: str | None = None
        self._job_running = False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Storm Detector",
            "manufacturer": "Radar",
            "model": "Radar Storm Detector",
            "entry_type": "service",
        }

    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if not data:
            return
        radar_url = data.get("last_radar_url")
        if not radar_url or radar_url == self._last_url:
            super()._handle_coordinator_update()
            return
        with self._lock:
            if self._job_running:
                super()._handle_coordinator_update()
                return
        self._last_url = radar_url
        with self._lock:
            self._job_running = True

        async def _run_job() -> None:
            try:
                await self.hass.async_add_executor_job(self._fetch_and_render, radar_url)
            finally:
                with self._lock:
                    self._job_running = False

        self.hass.async_create_task(_run_job())
        super()._handle_coordinator_update()

    def _fetch_and_render(self, radar_url: str) -> None:
        radar = _fetch_image(radar_url)
        if radar is None:
            return
        composed = _add_dbz_scale_bar(radar, gray=False)
        radar.close()
        buf = io.BytesIO()
        composed.save(buf, format="PNG")
        composed.close()
        with self._lock:
            self._current_image = buf.getvalue()

    def camera_image(self, width=None, height=None) -> bytes | None:
        with self._lock:
            return self._current_image

    async def async_camera_image(self, width=None, height=None) -> bytes | None:
        with self._lock:
            if self._current_image:
                return self._current_image
            if self._job_running:
                return None
        data = self.coordinator.data
        if not data:
            return None
        radar_url = data.get("last_radar_url")
        if not radar_url:
            return None
        with self._lock:
            self._job_running = True
        try:
            await self.hass.async_add_executor_job(self._fetch_and_render, radar_url)
        finally:
            with self._lock:
                self._job_running = False
        with self._lock:
            return self._current_image


# ---------------------------------------------------------------------------
# Camera: grayscale dBZ image + dBZ scale
# ---------------------------------------------------------------------------

class RainViewerDbzGrayCamera(CoordinatorEntity, Camera):
    """
    Static image of the latest radar tile converted to grayscale,
    proportional to dBZ, with a scale bar on the right.
    """

    def __init__(self, coordinator: RainViewerCoordinator, entry: ConfigEntry):
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._entry = entry
        self._attr_name = "Radar dBZ Grayscale"
        self._attr_unique_id = f"radar_storm_detector_{entry.entry_id}_dbz_gray"
        self._attr_icon = "mdi:contrast-box"
        self._attr_content_type = "image/png"
        self._lock = Lock()
        self._current_image: bytes | None = None
        self._last_url: str | None = None
        self._job_running = False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Storm Detector",
            "manufacturer": "Radar",
            "model": "Radar Storm Detector",
            "entry_type": "service",
        }

    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        if not data:
            return
        radar_url = data.get("last_radar_url")
        if not radar_url or radar_url == self._last_url:
            super()._handle_coordinator_update()
            return
        with self._lock:
            if self._job_running:
                super()._handle_coordinator_update()
                return
        self._last_url = radar_url
        with self._lock:
            self._job_running = True

        async def _run_job() -> None:
            try:
                await self.hass.async_add_executor_job(self._fetch_and_render, radar_url)
            finally:
                with self._lock:
                    self._job_running = False

        self.hass.async_create_task(_run_job())
        super()._handle_coordinator_update()

    def _fetch_and_render(self, radar_url: str) -> None:
        import numpy as np

        radar = _fetch_image(radar_url)
        if radar is None:
            return

        arr = np.array(radar.convert("RGBA"))
        radar.close()

        z_adj = build_dbz_array(arr)
        if z_adj is None:
            return

        gray_arr = np.clip((z_adj / 75.0) * 255.0, 0, 255).astype(np.uint8)
        gray_img = Image.fromarray(gray_arr, mode="L").convert("RGB")

        composed = _add_dbz_scale_bar(gray_img, gray=True)
        gray_img.close()

        buf = io.BytesIO()
        composed.save(buf, format="PNG")
        composed.close()
        with self._lock:
            self._current_image = buf.getvalue()

    def camera_image(self, width=None, height=None) -> bytes | None:
        with self._lock:
            return self._current_image

    async def async_camera_image(self, width=None, height=None) -> bytes | None:
        with self._lock:
            if self._current_image:
                return self._current_image
            if self._job_running:
                return None
        data = self.coordinator.data
        if not data:
            return None
        radar_url = data.get("last_radar_url")
        if not radar_url:
            return None
        with self._lock:
            self._job_running = True
        try:
            await self.hass.async_add_executor_job(self._fetch_and_render, radar_url)
        finally:
            with self._lock:
                self._job_running = False
        with self._lock:
            return self._current_image
