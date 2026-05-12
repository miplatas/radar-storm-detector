"""RainViewer radar analysis logic."""

import logging
import math
import time

import requests
import numpy as np
from PIL import Image
from io import BytesIO

from .const import RAINVIEWER_API

log = logging.getLogger(__name__)

# ==============================================================
# LUT DE dBZ — construida una sola vez al importar
# ==============================================================

# Quality filters for color conversion → dBZ
ALPHA_MIN           = 60
SATURATION_MIN      = 0.18
LUT_MAX_DIST2       = 2200
PURPLE_LUT_MAX_DIST2 = 10000
PURPLE_ALPHA_MIN    = 245
PURPLE_BOOST_MIN_DBZ = 50


def _build_lut():
    control = [
        (0,  0,   0,   0),
        (5,  4,   233, 231),
        (10, 1,   159, 244),
        (15, 3,   0,   244),
        (20, 2,   253, 2),
        (25, 1,   197, 1),
        (30, 0,   142, 0),
        (35, 253, 248, 2),
        (40, 229, 188, 0),
        (45, 253, 149, 0),
        (50, 253, 0,   0),
        (55, 212, 0,   0),
        (60, 188, 0,   0),
        (65, 248, 0,   253),
        (70, 152, 84,  198),
        (75, 255, 255, 255),
    ]
    lut = []
    for i in range(len(control) - 1):
        dbz0, r0, g0, b0 = control[i]
        dbz1, r1, g1, b1 = control[i + 1]
        steps = dbz1 - dbz0
        for j in range(steps):
            t = j / steps
            lut.append((
                int(r0 + t * (r1 - r0)),
                int(g0 + t * (g1 - g0)),
                int(b0 + t * (b1 - b0)),
                dbz0 + j,
            ))
    return lut

_LUT = _build_lut()
_LUT_RGB = np.array([(r, g, b) for r, g, b, _ in _LUT], dtype=np.int32)
_LUT_DBZ = np.array([dbz for _, _, _, dbz in _LUT], dtype=np.float32)


# ==============================================================
# dBZ CONVERSION
# ==============================================================
def dbz(r, g, b, a):
    """
    Converts a RainViewer RGBA pixel to dBZ using the global LUT.
    Returns float dBZ or None if the pixel is not valid precipitation.
    """
    if a < ALPHA_MIN:
        return None

    cmax = max(r, g, b)
    if cmax == 0:
        return None
    sat = (cmax - min(r, g, b)) / cmax
    if sat < SATURATION_MIN:
        return None

    best_dbz  = None
    best_dist = 1e9
    for r_l, g_l, b_l, dbz_l in _LUT:
        d = (r - r_l)**2 + (g - g_l)**2 + (b - b_l)**2
        if d < best_dist:
            best_dist = d
            best_dbz  = dbz_l

    purple_hint   = (r > 120 and b > 140 and g < 130 and (r + b) > 300)
    purple_strong = purple_hint and a >= PURPLE_ALPHA_MIN
    max_dist2 = PURPLE_LUT_MAX_DIST2 if purple_hint else LUT_MAX_DIST2

    if best_dist > max_dist2:
        return None
    if purple_strong and best_dbz >= PURPLE_BOOST_MIN_DBZ:
        return max(best_dbz, 60)
    return best_dbz


def classify(r, g, b, a):
    """
    Classifies an RGBA pixel into precipitation type using dBZ.
        Returns: (kind, dbz_value)
            kind: 'none' | 'light' | 'rain' | 'heavy' | 'hail'
    """
    z = dbz(r, g, b, a)
    if z is None:
        return "none", None
    if z >= 55:
        return "hail", z
    if z >= 45:
        return "heavy", z
    if z >= 30:
        return "rain", z
    if z >= 15:
        return "light", z
    return "none", z


def load_image(url):
    """Downloads a radar image and returns it as an RGBA numpy array."""
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGBA")
        arr = np.array(img)
        img.close()  # release PIL image immediately
        return arr
    except Exception as e:
        log.warning("Could not load image: %s -> %s", url, e)
        return None


def _lat_lon_to_pixel_in_tile(lat: float, lon: float, tile_x: int, tile_y: int,
                              zoom: int, tile_size: int = 256) -> tuple:
    """Converts geographic coordinates to a pixel within a tile."""
    n = 2 ** zoom
    gx = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    gy = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return ((gx - tile_x) * tile_size, (gy - tile_y) * tile_size)


def _nearest_storm(z_adj: np.ndarray, mask: np.ndarray,
                   home_x: float, home_y: float) -> tuple:
    """
    Expands a circle centered on (home_x, home_y) until it touches the first
    pixel in `mask`. Returns (distance_px, compass_bearing).
    Bearing: 0=N, 90=E, 180=S, 270=W.
    Returns (-1.0, None) if mask is empty.
    """
    if not np.any(mask):
        return -1.0, None
    ys, xs = np.where(mask)
    dx = xs.astype(np.float64) - home_x
    dy = ys.astype(np.float64) - home_y
    dists = np.sqrt(dx ** 2 + dy ** 2)
    idx = int(np.argmin(dists))
    bearing = float(np.degrees(np.arctan2(dx[idx], -dy[idx])) % 360)
    return float(dists[idx]), bearing


def analyze_frame(img: np.ndarray, home_px: tuple = (128, 128)):
    """
    Analyzes a radar frame using the dBZ LUT with numpy vectorized operations.
    Avoids a double Python pixel-by-pixel loop.
    """
    if img is None:
        return None

    h, w, _ = img.shape
    total = h * w

    rgba = img.astype(np.int32, copy=False)
    r = rgba[:, :, 0]
    g = rgba[:, :, 1]
    b = rgba[:, :, 2]
    a = rgba[:, :, 3]

    valid_alpha = a >= ALPHA_MIN

    rgb  = rgba[:, :, :3]
    maxc = np.max(rgb, axis=2)
    minc = np.min(rgb, axis=2)
    denom = np.where(maxc > 0, maxc, 1)
    sat = (maxc - minc) / denom
    valid_sat = sat >= SATURATION_MIN

    diff    = rgb[:, :, None, :] - _LUT_RGB[None, None, :, :]
    dist    = np.sum(diff * diff, axis=3, dtype=np.int64)
    lut_idx = np.argmin(dist, axis=2)
    min_dist = np.min(dist, axis=2)
    z = _LUT_DBZ[lut_idx]

    purple_hint   = (r > 120) & (b > 140) & (g < 130) & ((r + b) > 300)
    purple_strong = purple_hint & (a >= PURPLE_ALPHA_MIN)
    valid_lut = (
        (min_dist <= LUT_MAX_DIST2) |
        (purple_strong & (min_dist <= PURPLE_LUT_MAX_DIST2))
    )
    valid = valid_alpha & valid_sat & valid_lut

    z_adj = z.copy()
    purple_boost = purple_strong & valid & (z_adj >= PURPLE_BOOST_MIN_DBZ)
    z_adj[purple_boost] = np.maximum(z_adj[purple_boost], 60)

    hail  = valid & ((z_adj >= 55) | ((r > 160) & (b > 140) & (g < 110)))
    heavy = valid & (~hail) & (z_adj >= 45)
    rain  = valid & (~hail) & (~heavy) & (z_adj >= 30)
    light = valid & (~hail) & (~heavy) & (~rain) & (z_adj >= 15)
    precip = light | rain | heavy | hail

    home_x, home_y = float(home_px[0]), float(home_px[1])

    dbz_vals = z_adj[precip]
    if dbz_vals.size > 0:
        mean_val = float(dbz_vals.mean())
        max_val  = float(dbz_vals.max())
        dbz_stats = {
            "mean": round(mean_val, 2),
            "min":  round(float(dbz_vals.min()), 2),
            "max":  round(max_val,  2),
        }
        dist_mean, bearing_mean = _nearest_storm(
            z_adj, precip & (z_adj >= mean_val), home_x, home_y)
        dist_max,  bearing_max  = _nearest_storm(
            z_adj, precip & (z_adj >= max_val),  home_x, home_y)
    else:
        dbz_stats = {"mean": 0.0, "min": 0.0, "max": 0.0}
        dist_mean, bearing_mean = -1.0, None
        dist_max,  bearing_max  = -1.0, None

    return {
        "light":        float(np.count_nonzero(light)) / total,
        "rain":         float(np.count_nonzero(rain))  / total,
        "heavy":        float(np.count_nonzero(heavy)) / total,
        "hail":         float(np.count_nonzero(hail))  / total,
        "dbz":          dbz_stats,
        "dist_mean":    round(dist_mean, 2),
        "bearing_mean": round(bearing_mean, 1) if bearing_mean is not None else None,
        "dist_max":     round(dist_max, 2),
        "bearing_max":  round(bearing_max, 1) if bearing_max is not None else None,
    }


def build_dbz_array(img: np.ndarray) -> np.ndarray | None:
    """
    Given an RGBA radar tile array, returns a 2D float32 array
    with dBZ values (0.0 where the pixel is not valid precipitation).
    Useful for rendering visualization images.
    """
    if img is None:
        return None

    h, w, _ = img.shape
    rgba = img.astype(np.int32, copy=False)
    r = rgba[:, :, 0]
    g = rgba[:, :, 1]
    b = rgba[:, :, 2]
    a = rgba[:, :, 3]

    valid_alpha = a >= ALPHA_MIN
    rgb  = rgba[:, :, :3]
    maxc = np.max(rgb, axis=2)
    minc = np.min(rgb, axis=2)
    denom = np.where(maxc > 0, maxc, 1)
    sat = (maxc - minc) / denom
    valid_sat = sat >= SATURATION_MIN

    diff     = rgb[:, :, None, :] - _LUT_RGB[None, None, :, :]
    dist     = np.sum(diff * diff, axis=3, dtype=np.int64)
    lut_idx  = np.argmin(dist, axis=2)
    min_dist = np.min(dist, axis=2)
    z = _LUT_DBZ[lut_idx]

    purple_hint   = (r > 120) & (b > 140) & (g < 130) & ((r + b) > 300)
    purple_strong = purple_hint & (a >= PURPLE_ALPHA_MIN)
    valid_lut = (
        (min_dist <= LUT_MAX_DIST2) |
        (purple_strong & (min_dist <= PURPLE_LUT_MAX_DIST2))
    )
    valid = valid_alpha & valid_sat & valid_lut

    z_adj = z.copy()
    purple_boost = purple_strong & valid & (z_adj >= PURPLE_BOOST_MIN_DBZ)
    z_adj[purple_boost] = np.maximum(z_adj[purple_boost], 60)
    z_adj[~valid] = 0.0

    return z_adj


def pixel_distance(a, b):
    """Euclidean distance between two points."""
    if a is None or b is None:
        return -1.0
    return ((a[0] - b[0])**2 + (a[1] - b[1])**2) ** 0.5


def lat_lon_to_tile(lat, lon, zoom):
    """Converts geographic coordinates to OSM/RainViewer XY tile."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def determine_alert(rain_now, hail_now, heavy_now, distance, rain_trend,
                    rain_threshold, hail_threshold, dist_threshold):
    """Determines alert level and description."""
    if hail_now > hail_threshold:
        if distance != -1 and distance < dist_threshold:
            return "emergency", "Hail detected near the area"
        return "warning", "Hail detected in the region"
    if heavy_now > rain_threshold:
        if distance != -1 and distance < dist_threshold:
            return "warning", "Heavy rain approaching"
        return "watch", "Heavy rain in the region"
    if rain_now > rain_threshold:
        if rain_trend > 0.002:
            return "watch", "Moderate rain with increasing trend"
        return "watch", "Moderate rain detected"
    return "none", "No significant precipitation"


def run_analysis(lat, lon, zoom, tile_x, tile_y, frames_n,
                 rain_threshold, hail_threshold, dist_threshold):
    """
    Runs full radar analysis for the given location.
    Returns (payload, alert_level) or None on failure.
    """
    try:
        data = requests.get(RAINVIEWER_API, timeout=10).json()
    except Exception as e:
        log.error("Error fetching RainViewer API: %s", e)
        return None

    frames   = data["radar"]["past"]
    host     = data["host"]
    selected = frames[-frames_n:]

    home_px = _lat_lon_to_pixel_in_tile(lat, lon, tile_x, tile_y, zoom)

    results        = []
    rain_vals      = []
    hail_vals      = []
    heavy_vals     = []
    dist_mean_vals = []
    dist_max_vals  = []
    bearing_vals   = []

    for i, f in enumerate(selected):
        url = f"{host}{f['path']}/256/{zoom}/{tile_x}/{tile_y}/8/1_1.png"
        log.debug("Frame %d/%d: %s", i+1, len(selected), url)
        img  = load_image(url)
        stat = analyze_frame(img, home_px=home_px)
        if stat is None:
            continue

        rain_vals.append(stat["rain"] + stat["heavy"])
        hail_vals.append(stat["hail"])
        heavy_vals.append(stat["heavy"])
        dist_mean_vals.append(stat["dist_mean"])
        dist_max_vals.append(stat["dist_max"])
        bearing_vals.append(stat["bearing_mean"])

        results.append({
            "timestamp":    f["time"],
            "rain":         round(stat["rain"],  5),
            "heavy":        round(stat["heavy"], 5),
            "hail":         round(stat["hail"],  5),
            "light":        round(stat["light"], 5),
            "dbz":          stat["dbz"],
            "dist_mean":    stat["dist_mean"],
            "bearing_mean": stat["bearing_mean"],
            "dist_max":     stat["dist_max"],
            "bearing_max":  stat["bearing_max"],
        })

    if not results:
        log.warning("No results were obtained from any frame")
        return None

    rain_now   = rain_vals[-1]  if rain_vals  else 0
    hail_now   = hail_vals[-1]  if hail_vals  else 0
    heavy_now  = heavy_vals[-1] if heavy_vals else 0
    rain_trend = rain_vals[-1] - rain_vals[0] if len(rain_vals) > 1 else 0
    hail_trend = hail_vals[-1] - hail_vals[0] if len(hail_vals) > 1 else 0

    # Approach velocity: px/frame on dist_mean (negative = approaching)
    valid_dm = [(i, v) for i, v in enumerate(dist_mean_vals) if v >= 0]
    approach_vel = (
        (valid_dm[-1][1] - valid_dm[0][1]) / (valid_dm[-1][0] - valid_dm[0][0])
        if len(valid_dm) >= 2 else 0.0
    )

    # Intense core growth: px/frame on dist_max (negative = approaching)
    valid_dx = [(i, v) for i, v in enumerate(dist_max_vals) if v >= 0]
    core_growth = (
        (valid_dx[-1][1] - valid_dx[0][1]) / (valid_dx[-1][0] - valid_dx[0][0])
        if len(valid_dx) >= 2 else 0.0
    )

    dist_now     = dist_mean_vals[-1] if dist_mean_vals else -1.0
    dist_max_now = dist_max_vals[-1]  if dist_max_vals  else -1.0
    bearing_now  = bearing_vals[-1]   if bearing_vals   else None

    alert_level, alert_msg = determine_alert(
        rain_now, hail_now, heavy_now, dist_now, rain_trend,
        rain_threshold, hail_threshold, dist_threshold
    )

    last_frame      = selected[-1]
    last_radar_url  = f"{host}{last_frame['path']}/256/{zoom}/{tile_x}/{tile_y}/8/1_1.png"
    last_radar_time = last_frame["time"]

    payload = {
        "timestamp":       int(time.time()),
        "location":        {"lat": lat, "lon": lon},
        "alert":           alert_level,
        "alert_msg":       alert_msg,
        "last_radar_url":  last_radar_url,
        "last_radar_time": last_radar_time,
        "current": {
            "rain":  round(rain_now,  5),
            "hail":  round(hail_now,  5),
            "heavy": round(heavy_now, 5),
        },
        "trend": {
            "rain":  round(rain_trend, 5),
            "hail":  round(hail_trend, 5),
        },
        "proximity": {
            "dist_mean":    round(dist_now, 2) if dist_now >= 0 else -1,
            "bearing_mean": round(bearing_now, 1) if bearing_now is not None else None,
            "dist_max":     round(dist_max_now, 2) if dist_max_now >= 0 else -1,
            "approach_vel": round(approach_vel, 3),
            "core_growth":  round(core_growth, 3),
            "approaching":  (dist_now >= 0 and dist_now < dist_threshold),
        },
        "frames": results,
    }

    log.info(
        "Result -> Alert: [%s] | Rain: %.4f | Hail: %.4f | "
        "Dist: %.1fpx | Bearing: %s° | Approach: %.2fpx/frame",
        alert_level.upper(), rain_now, hail_now, dist_now,
        f"{bearing_now:.1f}" if bearing_now is not None else "—",
        approach_vel,
    )

    return payload, alert_level
