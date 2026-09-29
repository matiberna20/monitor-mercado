"""Detección básica de patrones y eventos técnicos.

Cada patrón se calcula como una columna booleana para todas las fechas
("¿ocurrió este evento en esta rueda?"). Así sirve tanto para el reporte de hoy
como para el backtest de la Etapa 5, que necesita saber qué pasó en cada día.

Son patrones simples y conocidos. Ninguno "predice" por sí solo: el valor real de
cada uno se mide recién en el backtest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DefinicionPatron:
    """Nombre legible, explicación y sesgo (+1 alcista, -1 bajista, 0 neutro)."""

    nombre: str
    descripcion: str
    sesgo: int


PATRONES: dict[str, DefinicionPatron] = {
    "cruce_dorado": DefinicionPatron(
        "Cruce dorado", "La media de 50 días cruzó por encima de la de 200.", +1),
    "cruce_muerte": DefinicionPatron(
        "Cruce de la muerte", "La media de 50 días cruzó por debajo de la de 200.", -1),
    "macd_cruce_alcista": DefinicionPatron(
        "Cruce alcista del MACD", "El MACD cruzó por encima de su línea de señal.", +1),
    "macd_cruce_bajista": DefinicionPatron(
        "Cruce bajista del MACD", "El MACD cruzó por debajo de su línea de señal.", -1),
    "ruptura_maximo_20d": DefinicionPatron(
        "Ruptura de máximo de 20 días", "Cerró por encima del máximo del último mes.", +1),
    "ruptura_minimo_20d": DefinicionPatron(
        "Ruptura de mínimo de 20 días", "Cerró por debajo del mínimo del último mes.", -1),
    "maximo_52s": DefinicionPatron(
        "Nuevo máximo de 52 semanas", "Tocó el precio más alto del último año.", +1),
    "minimo_52s": DefinicionPatron(
        "Nuevo mínimo de 52 semanas", "Tocó el precio más bajo del último año.", -1),
    "sobre_banda_superior": DefinicionPatron(
        "Cierre sobre la banda de Bollinger superior",
        "Movimiento fuerte, pero el precio está estirado respecto de su rango habitual.", 0),
    "bajo_banda_inferior": DefinicionPatron(
        "Cierre bajo la banda de Bollinger inferior",
        "Caída fuerte; el precio está estirado hacia abajo.", 0),
    "compresion_bollinger": DefinicionPatron(
        "Compresión de Bollinger",
        "La volatilidad está en su mínimo de 6 meses: suele anticipar un movimiento fuerte "
        "(sin indicar la dirección).", 0),
    "envolvente_alcista": DefinicionPatron(
        "Vela envolvente alcista",
        "Una vela verde cubrió por completo el cuerpo de la vela roja anterior.", +1),
    "envolvente_bajista": DefinicionPatron(
        "Vela envolvente bajista",
        "Una vela roja cubrió por completo el cuerpo de la vela verde anterior.", -1),
    "martillo": DefinicionPatron(
        "Martillo", "Vela con mecha inferior larga luego de una caída: posible rechazo de "
        "precios bajos.", +1),
    "estrella_fugaz": DefinicionPatron(
        "Estrella fugaz", "Vela con mecha superior larga luego de una suba: posible rechazo "
        "de precios altos.", -1),
    "rsi_sobrecompra": DefinicionPatron(
        "RSI en sobrecompra (>70)", "Subió mucho en poco tiempo; aumenta el riesgo de corrección.", 0),
    "rsi_sobreventa": DefinicionPatron(
        "RSI en sobreventa (<30)", "Cayó mucho en poco tiempo; puede haber rebote.", 0),
}


def _cruce_arriba(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift() <= b.shift())


def detectar_patrones(df: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una columna booleana por patrón para cada fecha.

    Args:
        df: Salida de ``calcular_indicadores``.
    """
    o, h, l, c = df["apertura"], df["maximo"], df["minimo"], df["cierre"]
    cuerpo = (c - o).abs()
    rango = (h - l).replace(0, np.nan)
    mecha_inf = pd.concat([o, c], axis=1).min(axis=1) - l
    mecha_sup = h - pd.concat([o, c], axis=1).max(axis=1)
    venia_bajando = c < df["sma20"]
    venia_subiendo = c > df["sma20"]
    verde, roja = c > o, c < o

    p = pd.DataFrame(index=df.index)
    p["cruce_dorado"] = _cruce_arriba(df["sma50"], df["sma200"])
    p["cruce_muerte"] = _cruce_arriba(df["sma200"], df["sma50"])
    p["macd_cruce_alcista"] = _cruce_arriba(df["macd"], df["macd_senal"])
    p["macd_cruce_bajista"] = _cruce_arriba(df["macd_senal"], df["macd"])
    # Se compara contra el máximo/mínimo de las 20 ruedas ANTERIORES (shift).
    p["ruptura_maximo_20d"] = c > df["max_20d"].shift()
    p["ruptura_minimo_20d"] = c < df["min_20d"].shift()
    p["maximo_52s"] = h >= df["max_252d"]
    p["minimo_52s"] = l <= df["min_252d"]
    p["sobre_banda_superior"] = df["bb_pct"] > 1
    p["bajo_banda_inferior"] = df["bb_pct"] < 0
    p["compresion_bollinger"] = df["bb_ancho"] <= df["bb_ancho"].rolling(126, min_periods=100).min()
    p["envolvente_alcista"] = verde & roja.shift(fill_value=False) & (c >= o.shift()) & (o <= c.shift())
    p["envolvente_bajista"] = roja & verde.shift(fill_value=False) & (c <= o.shift()) & (o >= c.shift())
    p["martillo"] = venia_bajando & (mecha_inf >= 2 * cuerpo) & (mecha_sup <= cuerpo) & (cuerpo / rango > 0.05)
    p["estrella_fugaz"] = venia_subiendo & (mecha_sup >= 2 * cuerpo) & (mecha_inf <= cuerpo) & (cuerpo / rango > 0.05)
    p["rsi_sobrecompra"] = df["rsi14"] > 70
    p["rsi_sobreventa"] = df["rsi14"] < 30
    return p.fillna(False).astype(bool)


@dataclass(frozen=True)
class PatronDetectado:
    """Un patrón que apareció en las últimas ruedas."""

    clave: str
    definicion: DefinicionPatron
    fecha: date


def patrones_recientes(df: pd.DataFrame, ruedas: int = 5) -> list[PatronDetectado]:
    """Patrones ocurridos en las últimas ``ruedas`` (el más reciente de cada tipo).

    Los estados (RSI extremo, sobre/bajo banda) solo se informan si siguen vigentes
    en la última rueda; los eventos (cruces, rupturas, velas) si ocurrieron en el período.
    """
    tabla = detectar_patrones(df)
    if tabla.empty:
        return []
    estados = {"rsi_sobrecompra", "rsi_sobreventa", "sobre_banda_superior",
               "bajo_banda_inferior", "compresion_bollinger"}
    ultimas = tabla.tail(ruedas)
    encontrados = []
    for clave, definicion in PATRONES.items():
        columna = tabla[clave].tail(1) if clave in estados else ultimas[clave]
        fechas = columna[columna].index
        if len(fechas):
            encontrados.append(PatronDetectado(clave, definicion, pd.Timestamp(fechas[-1]).date()))
    return sorted(encontrados, key=lambda p: p.fecha, reverse=True)
