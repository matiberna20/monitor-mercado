"""De dónde salen los dividendos: yfinance (Yahoo Finance).

Yahoo informa, por cada dividendo, la **fecha ex** (desde ese día la acción ya no da
derecho a cobrarlo) y el monto por acción, en la moneda en que cotiza el activo. Para
el próximo pago a veces trae el calendario anunciado por la empresa.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from monitor_mercado.datos.modelos import ErrorDatos

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Dividendo:
    """Un dividendo por acción, en la moneda del activo."""

    fecha_ex: date
    monto: float


@dataclass(frozen=True)
class Anunciado:
    """Próximo dividendo anunciado por la empresa (puede faltar cualquiera de las fechas)."""

    fecha_ex: date | None
    fecha_pago: date | None


class FuenteDividendos(Protocol):
    """Interfaz para poder usar una fuente falsa en los tests."""

    def historial(self, simbolo: str) -> list[Dividendo]:
        """Dividendos pagados (de más viejo a más nuevo). Lista vacía si no paga."""
        ...

    def anunciado(self, simbolo: str) -> Anunciado | None:
        """Próximo dividendo anunciado, si Yahoo lo tiene."""
        ...


def _a_fecha(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, list) and valor:
        return _a_fecha(valor[0])
    return None


class FuenteDividendosYahoo:
    """Dividendos de Yahoo, guardados en memoria unas horas (cambian poco)."""

    def __init__(self, horas_cache: float = 12) -> None:
        self._ttl = horas_cache * 3600
        self._cache: dict[tuple[str, str], tuple[float, object]] = {}

    def _cacheado(self, clave: tuple[str, str], obtener):
        ahora = time.monotonic()
        if clave in self._cache and ahora - self._cache[clave][0] < self._ttl:
            return self._cache[clave][1]
        valor = obtener()
        self._cache[clave] = (ahora, valor)
        return valor

    def historial(self, simbolo: str) -> list[Dividendo]:
        def obtener() -> list[Dividendo]:
            import yfinance as yf

            try:
                serie = yf.Ticker(simbolo).dividends
            except Exception as e:  # noqa: BLE001 - yfinance lanza errores variados
                raise ErrorDatos(f"{simbolo}: no se pudieron obtener los dividendos: {e}") from e
            return [Dividendo(f.date(), float(v)) for f, v in serie.items() if v and v > 0]

        return self._cacheado((simbolo, "historial"), obtener)

    def anunciado(self, simbolo: str) -> Anunciado | None:
        def obtener() -> Anunciado | None:
            import yfinance as yf

            try:
                cal = yf.Ticker(simbolo).calendar
            except Exception:  # noqa: BLE001 - el calendario es opcional
                log.info("%s: sin calendario de dividendos", simbolo)
                return None
            if not isinstance(cal, dict):
                return None
            ex, pago = _a_fecha(cal.get("Ex-Dividend Date")), _a_fecha(cal.get("Dividend Date"))
            return Anunciado(ex, pago) if ex or pago else None

        return self._cacheado((simbolo, "anunciado"), obtener)
