"""Lógica de análisis de radar RainViewer."""

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
def _build_lut():
    control = [
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
        for j in range(steps + 1):
            dbz_val = dbz0 + j
            if dbz_val > dbz1:
                break
            t = j / steps
            lut.append((
                int(r0 + t * (r1 - r0)),
                int(g0 + t * (g1 - g0)),
                int(b0 + t * (b1 - b0)),
                dbz_val,
            ))
    return lut

_LUT = _build_lut()


def classify(r, g, b, a):
    """Clasifica un píxel RGBA en tipo de precipitación."""
    if a < 50:
        return "none", 0
    if b > 80 and r < 60 and g < 180:
        return "light", 15
    if b > 100 and r < 20 and g > 60:
        return "rain", 30
    if r > 200 and g > 180 and b < 30:
        return "heavy", 45
    if r > 200 and g > 80 and g < 180 and b < 30:
        return "heavy", 50
    if r > 180 and g < 60 and b < 60:
        return "hail", 55
    if r > 120 and b > 120 and g < 80:
        return "hail", 60
    return "none", 0


def load_image(url):
    """Descarga imagen de radar y la retorna como array numpy RGBA."""
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGBA")
        arr = np.array(img)
        img.close()  # liberar PIL inmediatamente
        return arr
    except Exception as e:
        log.warning("No se pudo cargar imagen: %s → %s", url, e)
        return None


def analyze_frame(img: np.ndarray):
    """
    Analiza un frame de radar usando operaciones vectorizadas numpy.
    Evita el doble loop Python píxel a píxel.
    """
    if img is None:
        return None

    h, w, _ = img.shape
    total = h * w

    R = img[:, :, 0].astype(np.int16)
    G = img[:, :, 1].astype(np.int16)
    B = img[:, :, 2].astype(np.int16)
    A = img[:, :, 3].astype(np.int16)

    active = A >= 50

    light_mask = active & (B > 80) & (R < 60) & (G < 180)
    rain_mask  = active & (B > 100) & (R < 20) & (G > 60) & ~light_mask
    heavy_mask = active & (
        ((R > 200) & (G > 180) & (B < 30)) |
        ((R > 200) & (G > 80)  & (G < 180) & (B < 30))
    ) & ~light_mask & ~rain_mask
    hail_mask  = active & (
        ((R > 180) & (G < 60) & (B < 60)) |
        ((R > 120) & (B > 120) & (G < 80))
    ) & ~light_mask & ~rain_mask & ~heavy_mask

    counts = {
        "light": int(np.sum(light_mask)),
        "rain":  int(np.sum(rain_mask)),
        "heavy": int(np.sum(heavy_mask)),
        "hail":  int(np.sum(hail_mask)),
    }

    # Centroid de píxeles activos
    any_precip = light_mask | rain_mask | heavy_mask | hail_mask
    ys, xs = np.where(any_precip)
    centroid = (float(xs.mean()), float(ys.mean())) if len(xs) > 0 else None

    # dBZ estimado por clase
    dbz_map = np.zeros((h, w), dtype=np.float32)
    dbz_map[light_mask] = 15
    dbz_map[rain_mask]  = 30
    dbz_map[heavy_mask] = 47
    dbz_map[hail_mask]  = 57
    dbz_active = dbz_map[any_precip]

    if len(dbz_active) > 0:
        dbz_stats = {
            "mean": round(float(dbz_active.mean()), 1),
            "min":  round(float(dbz_active.min()),  1),
            "max":  round(float(dbz_active.max()),  1),
        }
    else:
        dbz_stats = {"mean": 0, "min": 0, "max": 0}

    return {
        "light":    counts["light"] / total,
        "rain":     counts["rain"]  / total,
        "heavy":    counts["heavy"] / total,
        "hail":     counts["hail"]  / total,
        "centroid": centroid,
        "dbz":      dbz_stats,
    }


def movement_vector(centers):
    """Calcula vector de movimiento promedio entre centroides."""
    valid = [c for c in centers if c is not None]
    if len(valid) < 2:
        return 0.0, 0.0
    dxs = [valid[i+1][0] - valid[i][0] for i in range(len(valid)-1)]
    dys = [valid[i+1][1] - valid[i][1] for i in range(len(valid)-1)]
    return sum(dxs)/len(dxs), sum(dys)/len(dys)


def pixel_distance(a, b):
    """Distancia euclidiana entre dos puntos."""
    if a is None or b is None:
        return -1.0
    return ((a[0] - b[0])**2 + (a[1] - b[1])**2) ** 0.5


def lat_lon_to_tile(lat, lon, zoom):
    """Convierte coordenadas geográficas a tile XY de OSM/RainViewer."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def determine_alert(rain_now, hail_now, heavy_now, distance, rain_trend,
                    rain_threshold, hail_threshold, dist_threshold):
    """Determina nivel de alerta y descripción."""
    if hail_now > hail_threshold:
        if distance != -1 and distance < dist_threshold:
            return "emergency", "Granizo detectado cerca de la zona"
        return "warning", "Granizo detectado en la región"
    if heavy_now > rain_threshold:
        if distance != -1 and distance < dist_threshold:
            return "warning", "Lluvia intensa aproximándose"
        return "watch", "Lluvia intensa en la región"
    if rain_now > rain_threshold:
        if rain_trend > 0.002:
            return "watch", "Lluvia moderada con tendencia creciente"
        return "watch", "Lluvia moderada detectada"
    return "none", "Sin precipitación significativa"


def run_analysis(lat, lon, zoom, tile_x, tile_y, frames_n,
                 rain_threshold, hail_threshold, dist_threshold):
    """
    Ejecuta análisis completo de radar para la ubicación dada.
    Retorna (payload, alert_level) o None si falla.
    """
    try:
        data = requests.get(RAINVIEWER_API, timeout=10).json()
    except Exception as e:
        log.error("Error obteniendo API RainViewer: %s", e)
        return None

    frames   = data["radar"]["past"]
    host     = data["host"]
    selected = frames[-frames_n:]

    results    = []
    centers    = []
    rain_vals  = []
    hail_vals  = []
    heavy_vals = []

    for i, f in enumerate(selected):
        url = f"{host}{f['path']}/256/{zoom}/{tile_x}/{tile_y}/8/1_1.png"
        log.debug("Frame %d/%d: %s", i+1, len(selected), url)
        img  = load_image(url)
        stat = analyze_frame(img)
        if stat is None:
            continue

        rain_vals.append(stat["rain"] + stat["heavy"])
        hail_vals.append(stat["hail"])
        heavy_vals.append(stat["heavy"])
        centers.append(stat["centroid"])

        results.append({
            "timestamp": f["time"],
            "rain":      round(stat["rain"],  5),
            "heavy":     round(stat["heavy"], 5),
            "hail":      round(stat["hail"],  5),
            "light":     round(stat["light"], 5),
            "dbz":       stat["dbz"],
        })

    if not results:
        log.warning("No se obtuvieron resultados de ningún frame")
        return None

    rain_now   = rain_vals[-1]  if rain_vals  else 0
    hail_now   = hail_vals[-1]  if hail_vals  else 0
    heavy_now  = heavy_vals[-1] if heavy_vals else 0
    rain_trend = rain_vals[-1] - rain_vals[0] if len(rain_vals) > 1 else 0
    hail_trend = hail_vals[-1] - hail_vals[0] if len(hail_vals) > 1 else 0

    vx, vy = movement_vector(centers)
    last_center = next((c for c in reversed(centers) if c is not None), None)
    home_px     = (128, 128)
    future_pos  = (last_center[0] + vx*3, last_center[1] + vy*3) if last_center else None
    distance    = pixel_distance(home_px, future_pos)

    alert_level, alert_msg = determine_alert(
        rain_now, hail_now, heavy_now, distance, rain_trend,
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
        "movement": {
            "vx":          round(vx, 3),
            "vy":          round(vy, 3),
            "distance":    round(distance, 2) if distance >= 0 else -1,
            "approaching": (distance != -1 and distance < dist_threshold),
        },
        "frames": results,
    }

    log.info(
        "Resultado → Alerta: [%s] | Lluvia: %.4f | Granizo: %.4f | Distancia: %.1fpx",
        alert_level.upper(), rain_now, hail_now, distance
    )

    return payload, alert_level
