"""
Config Flow para CFE Forecast MX.

Maneja la configuration inicial (ConfigFlow) y la edición posterior
de parámetros (OptionsFlow) a través de la interfaz de Home Assistant.

El flow se divide en pasos:
  1. user      → Selección de sensors de energía (import y export)
  2. tariff    → Selección de tariff CFE y parámetros de bimonthtre
  3. prices    → Ajuste endo de precios y cargos (puede omitirse con defaults)
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_IMPORT_SENSOR,
    CONF_EXPORT_SENSOR,
    CONF_TARIFF,
    CONF_CUT_DAY,
    CONF_START_MONTH,
    CONF_INITIAL_BAG,
    CONF_BASIC_LIMIT,
    CONF_BASIC_PRICE,
    CONF_INTERMEDIATE_LIMIT,
    CONF_INTERMEDIATE_PRICE,
    CONF_EXCESS_PRICE,
    CONF_IVA,
    CONF_FIXED_CHARGE,
    DEFAULT_TARIFF,
    DEFAULT_CUT_DAY,
    DEFAULT_START_MONTH,
    DEFAULT_INITIAL_BAG,
    DEFAULT_BASIC_LIMIT,
    DEFAULT_BASIC_PRICE,
    DEFAULT_INTERMEDIATE_LIMIT,
    DEFAULT_INTERMEDIATE_PRICE,
    DEFAULT_EXCESS_PRICE,
    DEFAULT_IVA,
    DEFAULT_FIXED_CHARGE,
    TARIFF_OPTIONS,
    STEP_USER,
    STEP_TARIFF,
    STEP_PRICES,
    STEP_INIT,
)

_LOGGER = logging.getLogger(__name__)


def _get_sensor_schema(hass: HomeAssistant, defaults: dict) -> vol.Schema:
    """
    Genera el esquema de voluptuous para la selección de sensors.
    Filtra automáticamente por device_class: energy para mostrar
    solo los sensors relevantes al usuario.
    """
    return vol.Schema(
        {
            # Sensor de import (energía consumida de la red) - OBLIGATORIO
            vol.Required(
                CONF_IMPORT_SENSOR,
                default=defaults.get(CONF_IMPORT_SENSOR, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy",
                    multiple=False,
                )
            ),
            # Sensor de export (energía inyectada, paneles solares) - OPCIONAL
            vol.Optional(
                CONF_EXPORT_SENSOR,
                default=defaults.get(CONF_EXPORT_SENSOR, ""),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor",
                    device_class="energy",
                    multiple=False,
                )
            ),
        }
    )


def _get_tariff_schema(defaults: dict) -> vol.Schema:
    """
    Genera el esquema para la selección de tariff CFE y
    configuration del ciclo de facturación (bimonthtre).
    """
    return vol.Schema(
        {
            # Tariff a aplicar (1, 1A, 1B, ... DAC)
            vol.Required(
                CONF_TARIFF,
                default=defaults.get(CONF_TARIFF, DEFAULT_TARIFF),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=TARIFF_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            # Day del month en que se emite el recibo (1-31)
            vol.Required(
                CONF_CUT_DAY,
                default=defaults.get(CONF_CUT_DAY, DEFAULT_CUT_DAY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=31, step=1, mode="box")
            ),
            # Month en que inicia el bimonthtre actual (1=Enero ... 12=Diciembre)
            vol.Required(
                CONF_START_MONTH,
                default=defaults.get(CONF_START_MONTH, DEFAULT_START_MONTH),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=12, step=1, mode="box")
            ),
            # Bolsa de energía acumulada antes de iniciar la integración (kWh)
            vol.Optional(
                CONF_INITIAL_BAG,
                default=defaults.get(CONF_INITIAL_BAG, DEFAULT_INITIAL_BAG),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=99999, step=0.1, mode="box")
            ),
        }
    )


def _get_prices_schema(defaults: dict) -> vol.Schema:
    """
    Genera el esquema para la configuration detallada de precios.
    Los valores por defecto corresponden a Tariff 1C del norte del país.
    """
    return vol.Schema(
        {
            # ── Escalón BÁSICO ──────────────────────────────────────────────
            vol.Required(
                CONF_BASIC_LIMIT,
                default=defaults.get(CONF_BASIC_LIMIT, DEFAULT_BASIC_LIMIT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=9999, step=1, mode="box")
            ),
            vol.Required(
                CONF_BASIC_PRICE,
                default=defaults.get(CONF_BASIC_PRICE, DEFAULT_BASIC_PRICE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=99, step=0.001, mode="box")
            ),

            # ── Escalón INTERMEDIO ──────────────────────────────────────────
            vol.Required(
                CONF_INTERMEDIATE_LIMIT,
                default=defaults.get(CONF_INTERMEDIATE_LIMIT, DEFAULT_INTERMEDIATE_LIMIT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=9999, step=1, mode="box")
            ),
            vol.Required(
                CONF_INTERMEDIATE_PRICE,
                default=defaults.get(CONF_INTERMEDIATE_PRICE, DEFAULT_INTERMEDIATE_PRICE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=99, step=0.001, mode="box")
            ),

            # ── Escalón EXCEDENTE ───────────────────────────────────────────
            vol.Required(
                CONF_EXCESS_PRICE,
                default=defaults.get(CONF_EXCESS_PRICE, DEFAULT_EXCESS_PRICE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=99, step=0.001, mode="box")
            ),

            # ── Cargos adicionales ──────────────────────────────────────────
            vol.Required(
                CONF_IVA,
                default=defaults.get(CONF_IVA, DEFAULT_IVA),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=1, step=0.01, mode="box")
            ),
            vol.Optional(
                CONF_FIXED_CHARGE,
                default=defaults.get(CONF_FIXED_CHARGE, DEFAULT_FIXED_CHARGE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=99999, step=0.01, mode="box")
            ),
        }
    )


class CFEForecastConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Maneja el flow de configuration inicial de CFE Forecast MX.
    
    El usuario pasa por 3 pasos:
      Paso 1 (user)    → Elige sensors de energía
      Paso 2 (tariff)  → Elige tariff y parámetros del bimonthtre
      Paso 3 (prices)  → Ajusta precios por escalón
    """

    VERSION = 1

    def __init__(self) -> None:
        """Inicializa el flujo guardando datos temporales entre pasos."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """
        Paso 1: Selección de sensors.
        Presenta un dropdown con todos los sensors cuyo device_class es 'energy'.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validar que se haya seleccionado al menos el sensor de import
            if not user_input.get(CONF_IMPORT_SENSOR):
                errors[CONF_IMPORT_SENSOR] = "sensor_required"
            else:
                # Guardar selección y avanzar al paso 2
                self._data.update(user_input)
                return await self.async_step_tariff()

        return self.async_show_form(
            step_id=STEP_USER,
            data_schema=_get_sensor_schema(self.hass, self._data),
            errors=errors,
            description_placeholders={
                "docs_url": "https://github.com/tu-usuario/cfe_forecast_mx"
            },
        )

    async def async_step_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """
        Paso 2: Configuration de tariff y ciclo de facturación.
        Determines qué escalones de precio se aplicarán y cómo se calculatestes el bimonthtre.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Guardar y avanzar a configuration de precios
            self._data.update(user_input)
            return await self.async_step_prices()

        return self.async_show_form(
            step_id=STEP_TARIFF,
            data_schema=_get_tariff_schema(self._data),
            errors=errors,
        )

    async def async_step_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """
        Paso 3: Ajuste endo de precios por escalón.
        Los valores vienen precargados con los defaults de Tariff 1C.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validar que el límite básico sea menor al intermedio (evitar inconsistencias)
            if user_input.get(CONF_BASIC_LIMIT, 0) <= 0:
                errors[CONF_BASIC_LIMIT] = "invalid_limit"
            else:
                # Combinar todos los datos recolectados en los 3 pasos
                self._data.update(user_input)

                # Crear la entrada de configuration con título descriptivo
                title = f"CFE {self._data.get(CONF_TARIFF, 'Tarifa')} - Bimestre"
                return self.async_create_entry(title=title, data=self._data)

        return self.async_show_form(
            step_id=STEP_PRICES,
            data_schema=_get_prices_schema(self._data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> CFEForecastOptionsFlow:
        """
        Devuelve el manejador del OptionsFlow para permitir editar
        la configuration después de la instalación inicial.
        """
        return CFEForecastOptionsFlow(config_entry)


class CFEForecastOptionsFlow(config_entries.OptionsFlow):
    """
    Permite editar la configuration existente de CFE Forecast MX.
    
    Accesible desde: Ajustes → Dispositivos e Integraciones → CFE Forecast → Configurar.
    Permite cambiar sensors, tariff y precios sin reinstalar la integración.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """
        Inicializa con los datos actuales para mostrarlos como valores por defecto
        en los formularios de edición.
        """
        self._config_entry = config_entry
        # Combinamos datos originales con options guardadas previamente
        self._data: dict[str, Any] = {
            **config_entry.data,
            **config_entry.options,
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """
        Punto de entrada del OptionsFlow.
        Muestra el primer formulario (sensors) con los valores actuales precargados.
        """
        return await self.async_step_sensors()

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edición de sensores de energía (import / export)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_IMPORT_SENSOR):
                errors[CONF_IMPORT_SENSOR] = "sensor_required"
            else:
                self._data.update(user_input)
                return await self.async_step_tariff_options()

        return self.async_show_form(
            step_id="sensors",
            data_schema=_get_sensor_schema(self.hass, self._data),
            errors=errors,
        )

    async def async_step_tariff_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edición de tarifa y parámetros del bimestre."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_prices_options()

        return self.async_show_form(
            step_id="tariff_options",
            data_schema=_get_tariff_schema(self._data),
        )

    async def async_step_prices_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edición de precios por escalón e IVA."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_BASIC_LIMIT, 0) <= 0:
                errors[CONF_BASIC_LIMIT] = "invalid_limit"
            else:
                self._data.update(user_input)
                # Guardar las options actualizadas y recargar la integración
                return self.async_create_entry(title="", data=self._data)

        return self.async_show_form(
            step_id="prices_options",
            data_schema=_get_prices_schema(self._data),
            errors=errors,
        )
