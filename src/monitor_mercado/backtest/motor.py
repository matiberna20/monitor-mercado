"""Simulación de la estrategia y métricas (funciones puras, sin red).

Reglas de la simulación (pensadas para no hacer trampa):
1. La señal del día t se calcula con el cierre del día t.
2. La operación se ejecuta en la APERTURA del día t+1: nunca se usa un precio que
   todavía no se conocía al decidir (eso se llama "lookahead bias" y es el error más
   común de los backtests, que hace que todo parezca rentable).
3. Cada compra o venta paga comisión + slippage (diferencia entre el precio que
   esperabas y el que realmente conseguís).

Estrategia "solo compra" (long-only), como puede operar un inversor minorista:
- Entra (compra) cuando el puntaje de la señal supera ``entrada``.
- Sale (vende y queda en efectivo) cuando el puntaje cae por debajo de ``salida``.
- Entre ambos umbrales mantiene lo que tenía (evita comprar y vender por ruido).
Opcionalmente puede ir "corto" (apostar a la baja) cuando la señal es muy bajista.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DIAS_POR_ANIO = 252


def posiciones(puntajes: pd.Series, entrada: float, salida: float, corto: bool = False) -> pd.Series:
    """Posición decidida al cierre de cada día: 1 comprado, 0 afuera, -1 corto."""
    p = puntajes.to_numpy(dtype=float)
    pos = np.zeros(len(p))
    actual = 0.0
    for i, x in enumerate(p):
        if np.isnan(x):
            pass  # sin señal: se mantiene lo que había
        elif x >= entrada:
            actual = 1.0
        elif corto and x <= -entrada:
            actual = -1.0
        elif actual > 0 and x <= salida:
            actual = 0.0
        elif actual < 0 and x >= -salida:
            actual = 0.0
        pos[i] = actual
    return pd.Series(pos, index=puntajes.index, name="posicion")


def simular(datos: pd.DataFrame, pos: pd.Series, costo_por_lado: float) -> pd.DataFrame:
    """Retornos diarios de la estrategia y de "comprar y mantener".

    Args:
        datos: Precios con columnas ``apertura`` y ``cierre``.
        pos: Posición decidida al cierre de cada día (ver ``posiciones``).
        costo_por_lado: Comisión + slippage de cada compra o venta (0,001 = 0,1%).

    Returns:
        DataFrame con ``estrategia``, ``comprar_y_mantener``, ``posicion`` (la que se
        tiene durante ese día) y ``costo``.
    """
    cierre = datos["cierre"]
    apertura = datos["apertura"].where(datos["apertura"] > 0).fillna(cierre.shift())
    noche = (apertura / cierre.shift() - 1).fillna(0)  # del cierre anterior a la apertura
    dia = (cierre / apertura - 1).fillna(0)  # de la apertura al cierre

    antes_de_abrir = pos.shift(2).fillna(0)  # posición que se tenía durante la noche
    durante_el_dia = pos.shift(1).fillna(0)  # posición tomada en la apertura
    bruto = (1 + antes_de_abrir * noche) * (1 + durante_el_dia * dia) - 1
    costo = (durante_el_dia - antes_de_abrir).abs() * costo_por_lado
    return pd.DataFrame(
        {
            "estrategia": bruto - costo,
            "comprar_y_mantener": cierre.pct_change().fillna(0),
            "posicion": durante_el_dia,
            "costo": costo,
        }
    )


@dataclass(frozen=True)
class Metricas:
    """Métricas de una serie de retornos diarios."""

    retorno_total: float
    retorno_anual: float
    volatilidad: float
    sharpe: float
    max_drawdown: float
    exposicion: float  # fracción de días con posición abierta
    operaciones: int  # operaciones completas (entrada + salida)
    tasa_acierto: float | None  # fracción de operaciones con ganancia
    costos: float  # suma de costos pagados (en fracción del capital)


def curva(retornos: pd.Series) -> pd.Series:
    """Valor de $1 invertido al inicio."""
    return (1 + retornos).cumprod()


def max_drawdown(retornos: pd.Series) -> float:
    """Peor caída desde un máximo (ej. -0,35 = perdió 35% desde su pico)."""
    c = curva(retornos)
    return float((c / c.cummax() - 1).min()) if len(c) else 0.0


def sharpe(retornos: pd.Series) -> float:
    """Sharpe anualizado (tasa libre de riesgo = 0 para simplificar)."""
    desvio = retornos.std()
    if np.isnan(desvio) or desvio < 1e-12:  # sin volatilidad (o solo error de redondeo)
        return 0.0
    return float(retornos.mean() / desvio * np.sqrt(DIAS_POR_ANIO))


def operaciones(sim: pd.DataFrame) -> list[float]:
    """Retorno de cada operación completa (desde que entra hasta que sale)."""
    resultados, acumulado, abierta = [], 1.0, False
    for pos, r in zip(sim["posicion"], sim["estrategia"]):
        if pos != 0:
            acumulado *= 1 + r
            abierta = True
        elif abierta:
            acumulado *= 1 + r  # el día de la salida (incluye su costo)
            resultados.append(acumulado - 1)
            acumulado, abierta = 1.0, False
    if abierta:
        resultados.append(acumulado - 1)
    return resultados


def calcular_metricas(retornos: pd.Series, sim: pd.DataFrame | None = None) -> Metricas:
    """Métricas de una serie de retornos diarios (``sim`` agrega exposición y operaciones)."""
    anios = max(len(retornos) / DIAS_POR_ANIO, 1e-9)
    total = float(curva(retornos).iloc[-1] - 1) if len(retornos) else 0.0
    ops = operaciones(sim) if sim is not None else []
    return Metricas(
        retorno_total=total,
        retorno_anual=float((1 + total) ** (1 / anios) - 1) if total > -1 else -1.0,
        volatilidad=float(retornos.std() * np.sqrt(DIAS_POR_ANIO)),
        sharpe=sharpe(retornos),
        max_drawdown=max_drawdown(retornos),
        exposicion=float((sim["posicion"] != 0).mean()) if sim is not None else 1.0,
        operaciones=len(ops),
        tasa_acierto=float(np.mean([o > 0 for o in ops])) if ops else None,
        costos=float(sim["costo"].sum()) if sim is not None else 0.0,
    )
