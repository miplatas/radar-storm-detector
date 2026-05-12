# ⚡ CFE Forecast MX

Integración personalizada para Home Assistant que calcula el costo estimado de tu recibo de luz de la **Comisión Federal de Electricidad (CFE)** en México, con soporte completo para tarifas progresivas, bolsa de energía solar y proyección del recibo bimestral.

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2023.1%2B-blue.svg)](https://www.home-assistant.io)

---

## 🚀 Instalación con HACS

1. Abre HACS en tu Home Assistant.
2. Ve a **Integraciones** → menú ⋮ → **Repositorios personalizados**.
3. Agrega la URL de este repositorio y selecciona categoría **Integración**.
4. Busca **"CFE Forecast MX"** e instala.
5. Reinicia Home Assistant.
6. Ve a **Ajustes → Dispositivos e Integraciones → + Agregar integración → CFE Forecast MX**.

---

## ⚙️ Configuración

El asistente de configuración te guiará por 3 pasos:

### Paso 1: Sensores de Energía
- **Sensor de Importación** *(obligatorio)*: El sensor que mide la energía que consumes de la red CFE. Debe tener `device_class: energy`.
- **Sensor de Exportación** *(opcional)*: El sensor que mide la energía que inyectas a la red (paneles solares). También debe tener `device_class: energy`.

### Paso 2: Tarifa y Bimestre
| Campo | Descripción |
|-------|-------------|
| Tarifa CFE | Tu tarifa (1, 1A, 1B, 1C, 1D, 1E, 1F, DAC) |
| Día de corte | Día del mes en que se emite tu recibo |
| Mes de inicio | Mes inicial de tu ciclo bimestral |
| Bolsa inicial | kWh a tu favor antes de instalar la integración |

### Paso 3: Precios por Escalón
Configura los precios de tu tarifa. Los valores por defecto son para **Tarifa 1C** (válidos para Nuevo León y noreste de México).

| Escalón | Límite | Precio default |
|---------|--------|----------------|
| Básico | 150 kWh | $1.110 MXN/kWh |
| Intermedio | +200 kWh | $1.349 MXN/kWh |
| Excedente | Sin límite | $3.944 MXN/kWh |
| IVA | | 16% |

> ⚠️ **Actualiza los precios** según la tarifa vigente publicada por CFE en [cfe.mx](https://www.cfe.mx).

---

## 📊 Entidades Creadas

### Sensores Monetarios
| Entidad | Descripción |
|---------|-------------|
| `sensor.cfe_costo_actual_del_bimestre` | Costo acumulado del bimestre actual (con IVA) |
| `sensor.cfe_proyeccion_del_recibo_final` | Proyección del recibo al fin del bimestre |

### Sensores de Energía
| Entidad | Descripción |
|---------|-------------|
| `sensor.cfe_consumo_neto_del_bimestre` | kWh netos consumidos (import - export) |
| `sensor.cfe_bolsa_de_energia_disponible` | kWh disponibles en la bolsa de energía |

### Series Temporales (para gráficas)
| Entidad | Descripción |
|---------|-------------|
| `sensor.cfe_importacion_diaria_serie` | Serie diaria de importación con atributo `serie_diaria` |
| `sensor.cfe_exportacion_diaria_serie` | Serie diaria de exportación con atributo `serie_diaria` |
| `sensor.cfe_neto_diario_serie` | Serie diaria neta (positivo=consumo, negativo=generación) |

### Alertas (Binary Sensors)
| Entidad | Se activa cuando... |
|---------|---------------------|
| `binary_sensor.cfe_alerta_expiracion_de_bolsa` | Hay kWh en la bolsa que vencen en ≤30 días |
| `binary_sensor.cfe_riesgo_de_tarifa_dac` | El consumo proyectado supera el umbral DAC |

---

## 🔋 Bolsa de Energía

La bolsa de energía acumula los kWh que generas con tus paneles solares y no consumes. La integración:

- **Deposita** kWh cuando exportas más de lo que importas.
- **Consume** de la bolsa (FIFO) antes de cobrar en pesos.
- **Expira** depósitos con más de 12 meses de antigüedad.
- **Alerta** 30 días antes de que venzan kWh acumulados.

Los datos se **persisten automáticamente** en `.storage/cfe_forecast_energy_store` y sobreviven reinicios de Home Assistant.

---

## 📈 Gráficas con ApexCharts

Usa la tarjeta [apexcharts-card](https://github.com/RomRider/apexcharts-card) para visualizar el consumo diario:

```yaml
type: custom:apexcharts-card
header:
  title: Consumo Neto Diario CFE
graph_span: 60d
series:
  - entity: sensor.cfe_neto_diario_serie
    type: column
    name: kWh Neto
    data_generator: |
      return entity.attributes.serie_diaria.map(item => ({
        x: new Date(item.fecha).getTime(),
        y: item.kwh
      }));
```

---

## 🛠️ Lógica Técnica

### Cero Virtual
Los sensores físicos de energía son acumulativos y nunca se resetean. La integración captura la lectura al inicio de cada bimestre y calcula el delta:

```
Consumo_Bimestre = Lectura_Actual - Lectura_Inicio_Bimestre
```

### Cálculo Progresivo
```
Si Consumo_Neto > 0:
    kWh_a_Cobrar = max(0, Consumo_Neto - Bolsa_Disponible)
    
    Costo = (primeros 150 kWh × $1.110)
          + (siguientes 200 kWh × $1.349)
          + (excedente × $3.944)
    
    Total = (Costo + Cargo_Fijo) × (1 + IVA)
```

---

## 📋 Requisitos
- Home Assistant 2023.1 o superior
- HACS instalado
- Al menos un sensor de energía con `device_class: energy` (medidor de red, Shelly, Sonoff POW, etc.)

---

## 📄 Licencia
MIT License — Libre para uso personal y comercial.
