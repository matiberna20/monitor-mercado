"""Cálculos del diario (funciones puras): tenencias, costo promedio y resultado realizado.

Método: **costo promedio ponderado**, el que usan la mayoría de los brokers en Argentina.
Cada compra suma al costo (precio × cantidad + comisión). Cada venta saca del costo la
parte proporcional (costo promedio × cantidad vendida), y su resultado es lo cobrado
(precio × cantidad − comisión) menos esa parte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from monitor_mercado.diario.modelos import Movimiento, TipoMovimiento

_EPS = 1e-9


class ErrorDiario(ValueError):
    """El diario quedaría inconsistente (por ejemplo, vender más de lo que tenías)."""


@dataclass
class Tenencia:
    """Lo que tenés hoy de un símbolo según el diario."""

    simbolo: str
    cantidad: float = 0.0
    costo: float | None = 0.0  # costo total; None si alguna compra no tiene precio
    moneda: str = "USD"
    desde: date | None = None  # fecha de la primera compra de la tenencia actual

    @property
    def costo_promedio(self) -> float | None:
        return self.costo / self.cantidad if self.costo is not None and self.cantidad > _EPS else None


@dataclass(frozen=True)
class VentaCerrada:
    """Una venta con su resultado realizado (en la moneda de la operación)."""

    movimiento: Movimiento
    costo_promedio: float | None
    resultado: float | None
    resultado_pct: float | None


@dataclass
class Calculo:
    """Resultado de procesar todo el diario."""

    tenencias: dict[str, Tenencia] = field(default_factory=dict)
    cerradas: list[VentaCerrada] = field(default_factory=list)

    @property
    def abiertas(self) -> list[Tenencia]:
        return [t for t in self.tenencias.values() if t.cantidad > _EPS]


def calcular(movimientos: list[Movimiento]) -> Calculo:
    """Procesa los movimientos en orden cronológico.

    Raises:
        ErrorDiario: Si en algún momento se vende más de lo que se tenía.
    """
    c = Calculo()
    # Dentro del mismo día, en el orden en que se cargaron; una operación nueva (sin id) va al final.
    for m in sorted(movimientos, key=lambda m: (m.fecha, m.id if m.id is not None else float("inf"))):
        t = c.tenencias.setdefault(m.simbolo, Tenencia(m.simbolo, moneda=m.moneda))
        if m.tipo is TipoMovimiento.COMPRA:
            if t.cantidad <= _EPS:  # empieza una tenencia nueva
                t.cantidad, t.costo, t.desde, t.moneda = 0.0, 0.0, m.fecha, m.moneda
            t.cantidad += m.cantidad
            t.costo = (t.costo + m.cantidad * m.precio + m.comision
                       if t.costo is not None and m.precio is not None else None)
            continue

        if m.cantidad > t.cantidad + _EPS:
            raise ErrorDiario(f"#{m.id or 'nueva'}: vendés {m.cantidad:g} {m.simbolo} el {m.fecha:%d/%m/%Y}, "
                              f"pero en ese momento tenías {t.cantidad:g}.")
        promedio = t.costo_promedio
        vendido = promedio * m.cantidad if promedio is not None else None
        cobrado = m.cantidad * m.precio - m.comision if m.precio is not None else None
        resultado = cobrado - vendido if cobrado is not None and vendido is not None else None
        c.cerradas.append(VentaCerrada(m, promedio, resultado,
                                       resultado / vendido if resultado is not None and vendido else None))
        t.cantidad -= m.cantidad
        if t.costo is not None and vendido is not None:
            t.costo -= vendido
        if t.cantidad <= _EPS:
            t.cantidad, t.costo, t.desde = 0.0, 0.0, None
    return c
