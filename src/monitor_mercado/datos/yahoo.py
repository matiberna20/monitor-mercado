"""Proveedor de precios basado en yfinance (Yahoo Finance).

Por qué yfinance: es gratis, no requiere clave y cubre todos los mercados de la
watchlist con un formato de símbolo uniforme (.BA, .SA, .DE, .L).
Limitaciones: no es una API oficial (puede cambiar o fallar sin aviso) y los
precios suelen tener 15-20 minutos de demora.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import yfinance as yf
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from monitor_mercado.datos.modelos import Cotizacion, ErrorDatos, SimboloSinDatos

log = logging.getLogger(__name__)

# Reintentos ante fallas transitorias (red, límite de consultas). No se reintenta
# si el símbolo directamente no tiene datos: eso no se arregla esperando.
_reintentar = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_not_exception_type(SimboloSinDatos),
)


def _numero_valido(valor: object) -> float | None:
    try:
        numero = float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) and numero > 0 else None


class ProveedorYahoo:
    """Implementación de ``ProveedorPrecios`` con yfinance."""

    def __init__(self, hilos: int = 8) -> None:
        """
        Args:
            hilos: Consultas simultáneas al pedir varios símbolos.
        """
        self._hilos = hilos

    @_reintentar
    def cotizacion(self, simbolo: str) -> Cotizacion:
        """Consulta el último precio de ``simbolo``."""
        try:
            info = yf.Ticker(simbolo).fast_info
            precio = _numero_valido(info.last_price)
            moneda = info.currency
            cierre_anterior = _numero_valido(info.previous_close)
        except KeyError as e:
            # yfinance lanza KeyError cuando Yahoo no devuelve metadatos del símbolo.
            raise SimboloSinDatos(f"{simbolo}: Yahoo no tiene datos (¿dejó de cotizar?)") from e
        except Exception as e:  # noqa: BLE001 - yfinance lanza errores variados
            raise ErrorDatos(f"{simbolo}: error consultando Yahoo: {e}") from e

        if precio is None or not moneda:
            raise SimboloSinDatos(f"{simbolo}: sin precio disponible")
        return Cotizacion(
            simbolo=simbolo,
            precio=precio,
            moneda=str(moneda),
            cierre_anterior=cierre_anterior,
            obtenida_en=datetime.now(timezone.utc),
        )

    def cotizaciones(self, simbolos: list[str]) -> dict[str, Cotizacion]:
        """Consulta varios símbolos en paralelo; los que fallan se registran y se omiten."""
        resultado: dict[str, Cotizacion] = {}
        unicos = list(dict.fromkeys(simbolos))
        if not unicos:
            return resultado

        def consultar(s: str) -> tuple[str, Cotizacion | None]:
            try:
                return s, self.cotizacion(s)
            except ErrorDatos as e:
                log.warning("No se pudo obtener %s: %s", s, e)
                return s, None

        with ThreadPoolExecutor(max_workers=self._hilos) as pool:
            for simbolo, cot in pool.map(consultar, unicos):
                if cot is not None:
                    resultado[simbolo] = cot
        return resultado

    @_reintentar
    def ultima_fecha_operada(self, simbolo: str) -> date | None:
        """Fecha de la última rueda con datos (sirve para detectar símbolos "muertos")."""
        try:
            historia = yf.Ticker(simbolo).history(period="1mo", auto_adjust=False)
        except Exception as e:  # noqa: BLE001
            raise ErrorDatos(f"{simbolo}: error consultando historial: {e}") from e
        if historia.empty:
            return None
        return historia.index[-1].date()
