"""Interfaz común de proveedores de precios.

Definimos un ``Protocol`` (una "interfaz") para que el resto del sistema no
dependa de yfinance directamente. Si mañana Yahoo cambia algo o querés usar
Finnhub, se escribe otro proveedor que cumpla esta interfaz y nada más cambia.
También permite usar un proveedor falso en los tests, sin internet.
"""

from __future__ import annotations

from typing import Protocol

from monitor_mercado.datos.modelos import Cotizacion


class ProveedorPrecios(Protocol):
    """Fuente de precios actuales."""

    def cotizacion(self, simbolo: str) -> Cotizacion:
        """Devuelve la cotización de un símbolo.

        Raises:
            SimboloSinDatos: Si el símbolo no existe o no tiene precio.
            ErrorDatos: Si la consulta falla por otros motivos.
        """
        ...

    def cotizaciones(self, simbolos: list[str]) -> dict[str, Cotizacion]:
        """Devuelve las cotizaciones disponibles; omite los símbolos que fallan."""
        ...
