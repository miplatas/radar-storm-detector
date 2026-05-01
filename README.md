![logo](images/logo.png)

# 🌧 RainViewer Storm Detector — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/TU_USUARIO/rainviewer-hacs.svg)](https://github.com/TU_USUARIO/rainviewer-hacs/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Integración para Home Assistant que detecta condiciones de tormenta usando imágenes de radar de **RainViewer** y publica los datos automáticamente en **MQTT**.

---

## ✨ Características

- 📡 Análisis de imágenes de radar en tiempo real (RainViewer API — gratuita)
- ⚡ Publicación automática en MQTT (`rainviewer/status` y `rainviewer/alert`)
- 🏠 Sensores automáticos creados en Home Assistant sin configuración de YAML
- 🔧 Configurable desde la UI (no requiere editar `configuration.yaml`)
- 🌍 Calcula automáticamente el tile de radar según tu latitud/longitud
- 📊 12 sensores de estado + 4 sensores binarios

---

## 📦 Instalación via HACS

### Método recomendado

1. En Home Assistant, ve a **HACS → Integraciones → ⋮ → Repositorios personalizados**
2. Agrega la URL: `https://github.com/TU_USUARIO/rainviewer-hacs`
3. Categoría: **Integración**
4. Busca **RainViewer Storm Detector** e instala
5. Reinicia Home Assistant

### Método manual

1. Copia la carpeta `custom_components/rainviewer` a tu directorio `config/custom_components/`
2. Reinicia Home Assistant

---

## ⚙️ Configuración

1. Ve a **Configuración → Dispositivos y Servicios → Agregar integración**
2. Busca **RainViewer Storm Detector**
3. Completa el formulario:

| Campo | Descripción | Default |
|---|---|---|
| Latitud | Latitud de tu ubicación | Ubicación de HA |
| Longitud | Longitud de tu ubicación | Ubicación de HA |
| Broker MQTT | IP o hostname del broker | — |
| Puerto MQTT | Puerto del broker | 1883 |
| Usuario MQTT | (opcional) | — |
| Contraseña MQTT | (opcional) | — |
| Intervalo (seg) | Cada cuánto analizar | 300 |
| Zoom del radar | Nivel de zoom (6-8) | 7 |
| Umbral lluvia | Fracción mínima de píxeles | 0.005 |
| Umbral granizo | Fracción mínima de píxeles | 0.001 |
| Distancia alerta | Distancia máxima en píxeles | 30 |

---

## 🌡 Sensores creados automáticamente

### Sensores de estado (`sensor.*`)

| Entidad | Descripción |
|---|---|
| `sensor.rainviewer_alert_level` | Nivel de alerta: `none` / `watch` / `warning` / `emergency` |
| `sensor.rainviewer_alert_message` | Descripción textual de la alerta |
| `sensor.rainviewer_rain_coverage` | % de píxeles con lluvia |
| `sensor.rainviewer_heavy_rain_coverage` | % de píxeles con lluvia intensa |
| `sensor.rainviewer_hail_coverage` | % de píxeles con granizo |
| `sensor.rainviewer_rain_trend` | Tendencia de lluvia (+ = aumentando) |
| `sensor.rainviewer_hail_trend` | Tendencia de granizo |
| `sensor.rainviewer_storm_distance` | Distancia estimada de la tormenta |
| `sensor.rainviewer_dbz_mean` | dBZ promedio del último frame |
| `sensor.rainviewer_dbz_max` | dBZ máximo del último frame |
| `sensor.rainviewer_storm_movement_x` | Vector de movimiento horizontal |
| `sensor.rainviewer_storm_movement_y` | Vector de movimiento vertical |

### Sensores binarios (`binary_sensor.*`)

| Entidad | Descripción |
|---|---|
| `binary_sensor.rainviewer_rain_detected` | `on` cuando hay lluvia |
| `binary_sensor.rainviewer_hail_detected` | `on` cuando hay granizo |
| `binary_sensor.rainviewer_storm_approaching` | `on` cuando la tormenta se acerca |
| `binary_sensor.rainviewer_emergency_alert` | `on` en emergencia |

---

## 📨 Tópicos MQTT

| Tópico | Cuándo se publica |
|---|---|
| `rainviewer/status` | Cada ciclo de análisis |
| `rainviewer/alert` | Solo cuando `alert != "none"` |

### Ejemplo de payload JSON

```json
{
  "timestamp": 1746100000,
  "location": {"lat": 19.4326, "lon": -99.1332},
  "alert": "warning",
  "alert_msg": "Lluvia intensa aproximándose",
  "current": {"rain": 0.012, "hail": 0.002, "heavy": 0.008},
  "trend": {"rain": 0.003, "hail": 0.001},
  "movement": {"vx": -1.2, "vy": 0.8, "distance": 22.5, "approaching": true},
  "frames": [...]
}
```

---

## 🔔 Ejemplo de automatización

```yaml
automation:
  - alias: "Alerta de tormenta"
    trigger:
      - platform: state
        entity_id: binary_sensor.rainviewer_emergency_alert
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Tormenta"
          message: "{{ states('sensor.rainviewer_alert_message') }}"
```

---

## 📝 Niveles de alerta

| Nivel | Condición |
|---|---|
| `none` | Sin precipitación significativa |
| `watch` | Lluvia moderada detectada |
| `warning` | Lluvia intensa o granizo en la región |
| `emergency` | Granizo o lluvia intensa acercándose |

---

## 🛠 Dependencias

Las siguientes librerías se instalan automáticamente:
- `requests`
- `Pillow`
- `numpy`
- `paho-mqtt`

---

## 📄 Licencia

MIT License — ver [LICENSE](LICENSE)
