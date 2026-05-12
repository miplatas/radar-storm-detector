"""
Constants para la integración CFE Forecast MX.
Contiene todos los strings de configuration, valores por defecto y
defstartnes de tariffs de la CFE.
"""

# =============================================================================
# IDENTIFICADORES PRINCIPALES
# =============================================================================
DOMAIN = "cfe_forecast"
PLATFORMS = ["sensor", "binary_sensor"]

# Nombre del archivo donde se persiste la energy bank y el estado del bimonthtre
STORAGE_KEY = f"{DOMAIN}_energy_store"
STORAGE_VERSION = 1

# =============================================================================
# CLAVES DE CONFIGURACIÓN (Config Flow)
# =============================================================================
CONF_IMPORT_SENSOR = "import_sensor"        # Sensor de energía importada de la red
CONF_EXPORT_SENSOR = "export_sensor"        # Sensor de energía exportada (paneles)
CONF_TARIFF = "tariff"                      # Tarifa CFE seleccionada (1, 1A ... DAC)
CONF_CUT_DAY = "cut_day"                    # Día de corte del bimestre (1-31)
CONF_START_MONTH = "start_month"            # Mes de inicio del bimestre actual
CONF_INITIAL_BAG = "initial_bag"            # Bolsa inicial de kWh a favor
CONF_BASIC_LIMIT = "basic_limit"            # Límite de kWh en escalón básico
CONF_BASIC_PRICE = "basic_price"            # Precio por kWh en escalón básico
CONF_INTERMEDIATE_LIMIT = "intermediate_limit"  # Límite de kWh en escalón intermedio
CONF_INTERMEDIATE_PRICE = "intermediate_price"  # Precio por kWh en escalón intermedio
CONF_EXCESS_PRICE = "excess_price"          # Precio por kWh en excedente
CONF_IVA = "iva"                            # Porcentaje de IVA (0.16 = 16%)
CONF_FIXED_CHARGE = "fixed_charge"          # Cargo fijo / DAP en pesos

# =============================================================================
# VALORES POR DEFECTO (Tariff 1C - Ejemplo Noreste de México)
# =============================================================================
DEFAULT_TARIFF = "1C"
DEFAULT_CUT_DAY = 1
DEFAULT_START_MONTH = 1
DEFAULT_INITIAL_BAG = 0.0

# Precios base Tariff 1C (actualizar según tariffs vigentes de CFE)
DEFAULT_BASIC_LIMIT = 150          # kWh
DEFAULT_BASIC_PRICE = 1.110        # MXN/kWh
DEFAULT_INTERMEDIATE_LIMIT = 200   # kWh adicionales
DEFAULT_INTERMEDIATE_PRICE = 1.349 # MXN/kWh
DEFAULT_EXCESS_PRICE = 3.944       # MXN/kWh
DEFAULT_IVA = 0.16                 # 16%
DEFAULT_FIXED_CHARGE = 0.0         # Pesos por bimestre

# =============================================================================
# OPCIONES DE TARIFA
# =============================================================================
TARIFF_OPTIONS = ["1", "1A", "1B", "1C", "1D", "1E", "1F", "DAC"]

# =============================================================================
# NOMBRES DE ENTIDADES GENERADAS
# =============================================================================
# Sensors monetarios
SENSOR_COSTO_ACTUAL = "cfe_costo_actual"
SENSOR_PROYECCION = "cfe_proyeccion_recibo"

# Sensors de energía
SENSOR_CONSUMO_NETO = "cfe_consumo_neto_bimestre"
SENSOR_BOLSA = "cfe_bolsa_energia"

# Sensors de series temporales (para charts)
SENSOR_HISTORICO_IMPORT = "cfe_historico_importacion_diaria"
SENSOR_HISTORICO_EXPORT = "cfe_historico_exportacion_diaria"
SENSOR_HISTORICO_NETO = "cfe_historico_neto_diario"

# Sensors binarios de alerta
BINARY_SENSOR_EXPIRACION = "cfe_alerta_expiracion_bolsa"
BINARY_SENSOR_DAC = "cfe_riesgo_dac"

# =============================================================================
# PARÁMETROS DE ACTUALIZACIÓN
# =============================================================================
UPDATE_INTERVAL_MINUTES = 5   # Cada cuántos minutos se recalcula todo

# =============================================================================
# LÓGICA DE BOLSA DE ENERGÍA
# =============================================================================
# Los kWh en la bolsa expiran si tienen más de 12 monthes de antigüedad
BOLSA_EXPIRATION_MONTHS = 12

# Umbral de days para alertar sobre kWh próximos a vencer (alerta 30 days antes)
BOLSA_EXPIRATION_ALERT_DAYS = 30

# =============================================================================
# ESCALONES DE CONSUMO (nombres internos)
# =============================================================================
ESCALON_BASICO = "basico"
ESCALON_INTERMEDIO = "intermedio"
ESCALON_EXCEDENTE = "excedente"

# =============================================================================
# STRINGS DE INTERFAZ (para labels en Config Flow)
# =============================================================================
STEP_USER = "user"
STEP_SENSORS = "sensors"
STEP_TARIFF = "tariff"
STEP_PRICES = "prices"
STEP_INIT = "init"
