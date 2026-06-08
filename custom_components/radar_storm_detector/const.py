"""Constants for the Radar Storm Detector integration."""

DOMAIN = "radar_storm_detector"
PLATFORMS = ["sensor", "binary_sensor", "camera"]

# Config keys
CONF_MQTT_BROKER = "mqtt_broker"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ZOOM = "zoom"
CONF_TILE_X = "tile_x"
CONF_TILE_Y = "tile_y"
CONF_RAIN_THRESHOLD = "rain_threshold"
CONF_HAIL_THRESHOLD = "hail_threshold"
CONF_DIST_THRESHOLD = "dist_threshold"
CONF_GIF_SPEED = "gif_speed"
CONF_MAP_STYLE = "map_style"
CONF_TEST_DRAW_PROXIMITY_CIRCLES = "test_draw_proximity_circles"
CONF_TIMEZONE = "timezone"

# Defaults
DEFAULT_MQTT_PORT = 1883
DEFAULT_SCAN_INTERVAL = 600
DEFAULT_ZOOM = 7
DEFAULT_TILE_X = 28
DEFAULT_TILE_Y = 54
DEFAULT_RAIN_THRESHOLD = 0.005
DEFAULT_HAIL_THRESHOLD = 0.001
DEFAULT_DIST_THRESHOLD = 30
DEFAULT_FRAMES_N = 6
DEFAULT_GIF_SPEED = 500  # milliseconds per frame
DEFAULT_MAP_STYLE = "day"
DEFAULT_TEST_DRAW_PROXIMITY_CIRCLES = True
DEFAULT_TIMEZONE = "GMT -6"

# Base map styles (tile URL with placeholders {zoom}, {x}, {y})
MAP_TILE_URLS = {
    "day":       "https://a.tile.openstreetmap.org/{zoom}/{x}/{y}.png",
    "night":     "https://a.basemaps.cartocdn.com/dark_all/{zoom}/{x}/{y}.png",
    "satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{y}/{x}",
}
MAP_STYLE_OPTIONS = ["day", "night", "satellite"]
TIMEZONE_OPTIONS = [f"GMT {offset:+d}" for offset in range(-12, 15)]

# RainViewer API
RAINVIEWER_API = "https://api.rainviewer.com/public/weather-maps.json"

# MQTT Topics
MQTT_TOPIC_STATUS = "radar_storm_detector/status"
MQTT_TOPIC_ALERT = "radar_storm_detector/alert"

# Alert levels
ALERT_NONE = "none"
ALERT_WATCH = "watch"
ALERT_WARNING = "warning"
ALERT_EMERGENCY = "emergency"

ALERT_ICONS = {
    ALERT_NONE: "mdi:weather-sunny",
    ALERT_WATCH: "mdi:weather-rainy",
    ALERT_WARNING: "mdi:weather-pouring",
    ALERT_EMERGENCY: "mdi:weather-hail",
}

ALERT_COLORS = {
    ALERT_NONE: "green",
    ALERT_WATCH: "yellow",
    ALERT_WARNING: "orange",
    ALERT_EMERGENCY: "red",
}
