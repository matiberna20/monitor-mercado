"""Estructuras de datos comunes a todos los proveedores."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class ErrorDatos(Exception):
    """Falla al obtener datos (red, API caída, respuesta inválida)."""


class SimboloSinDatos(ErrorDatos):
    """El símbolo no existe, dejó de cotizar o no tiene precio disponible."""


@dataclass(frozen=True)
class Cotizacion:
    """Último precio conocido de un activo.

    Attributes:
        simbolo: Símbolo tal como se consultó (formato Yahoo, ej. "ALUA.BA").
        precio: Último precio, en la moneda nativa del activo.
        moneda: Moneda nativa informada por la fuente (ej. "USD", "ARS", "GBp").
        cierre_anterior: Cierre de la rueda anterior, si está disponible.
        obtenida_en: Momento (UTC) en que se consultó el dato. No es la hora de la
            última operación: con fuentes gratuitas el precio puede ser de 15-20
            minutos antes.
    """

    simbolo: str
    precio: float
    moneda: str
    cierre_anterior: float | None
    obtenida_en: datetime

    @property
    def variacion_pct(self) -> float | None:
        """Variación porcentual contra el cierre anterior (None si no hay dato)."""
        if not self.cierre_anterior:
            return None
        return (self.precio / self.cierre_anterior - 1) * 100
