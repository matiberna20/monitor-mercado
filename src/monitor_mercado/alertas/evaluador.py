"""Lógica pura de evaluación de alertas (sin red ni base de datos).

Está separada del resto a propósito: es la parte más importante de acertar y,
al ser funciones puras, se puede testear con cualquier combinación de precios.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from monitor_mercado.alertas.modelos import Alerta, Condicion


def condicion_cumplida(
    condicion: Condicion, umbral: float, precio: float, variacion_pct: float | None
) -> bool:
    """Indica si el precio (o la variación diaria) cumple la condición.

    Args:
        condicion: Tipo de condición.
        umbral: Precio objetivo, o porcentaje (positivo) para las variaciones.
        precio: Precio actual, en la misma moneda que el umbral.
        variacion_pct: Variación del día en %, o None si se desconoce.
    """
    if condicion is Condicion.SUBE_DE:
        return precio >= umbral
    if condicion is Condicion.BAJA_DE:
        return precio <= umbral
    if variacion_pct is None:
        return False
    if condicion is Condicion.VARIACION_SUBE:
        return variacion_pct >= abs(umbral)
    return variacion_pct <= -abs(umbral)


@dataclass(frozen=True)
class Decision:
    """Resultado de evaluar una alerta en una revisión."""

    disparar: bool
    armada: bool
    activa: bool


def evaluar(
    alerta: Alerta,
    precio: float,
    variacion_pct: float | None,
    ahora: datetime,
    enfriamiento: timedelta,
) -> Decision:
    """Decide si una alerta se dispara y cómo queda su estado.

    Reglas:
      1. Si la alerta está desarmada, solo se re-arma cuando la condición deja de
         cumplirse (el precio volvió al otro lado del umbral).
      2. Si está armada y la condición se cumple, se dispara; salvo que sea
         repetitiva y el último aviso haya sido hace menos que ``enfriamiento``.
      3. Al dispararse: una alerta de un solo uso se desactiva; una repetitiva
         queda desarmada hasta que el precio vuelva a cruzar.
    """
    cumple = condicion_cumplida(alerta.condicion, alerta.umbral, precio, variacion_pct)

    if not alerta.armada:
        return Decision(disparar=False, armada=not cumple, activa=alerta.activa)

    if not cumple:
        return Decision(disparar=False, armada=True, activa=alerta.activa)

    if alerta.repetir and alerta.ultimo_disparo is not None:
        ultimo = alerta.ultimo_disparo
        if ultimo.tzinfo is None:  # SQLite devuelve fechas sin zona; se guardan en UTC
            ultimo = ultimo.replace(tzinfo=ahora.tzinfo)
        if ahora - ultimo < enfriamiento:
            return Decision(disparar=False, armada=True, activa=True)

    return Decision(disparar=True, armada=False, activa=alerta.repetir)
