"""Datos de resultados desde Yahoo Finance: calendario, consenso, estados y valuación.

Qué hay gratis en Yahoo:
- Fechas de presentación (pasadas y la próxima), EPS estimado y reportado.
- Consenso de ingresos solo del PRÓXIMO trimestre: por eso el sistema lo guarda
  todos los días, para compararlo cuando salga el resultado.
- Estados contables trimestrales (últimos 5 a 7 trimestres).
- Múltiplos de valuación (P/E, EV/EBITDA, etc.), sector e industria.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from monitor_mercado.datos.modelos import ErrorDatos, SimboloSinDatos

log = logging.getLogger(__name__)
NY = ZoneInfo("America/New_York")

_reintentar = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_not_exception_type(SimboloSinDatos),
)


def _num(v: object) -> float | None:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


@dataclass(frozen=True)
class EventoResultados:
    """Una presentación de resultados (pasada o futura)."""

    fecha: datetime  # hora de Nueva York
    eps_estimado: float | None
    eps_reportado: float | None

    @property
    def publicado(self) -> bool:
        """True si ya salió el resultado."""
        return self.eps_reportado is not None


@dataclass(frozen=True)
class ConsensoProximo:
    """Lo que esperan los analistas para la próxima presentación."""

    fecha: date | None
    eps: float | None
    ingresos: float | None
    moneda_ingresos: str | None
    analistas: int | None


@dataclass(frozen=True)
class Estados:
    """Estados contables trimestrales."""

    resultados: pd.DataFrame
    balance: pd.DataFrame
    flujos: pd.DataFrame
    moneda: str | None


class FuenteResultadosYahoo:
    """Implementación con yfinance."""

    @_reintentar
    def eventos(self, simbolo: str, limite: int = 12) -> list[EventoResultados]:
        """Presentaciones de resultados, de la más reciente (o próxima) a la más vieja."""
        try:
            tabla = yf.Ticker(simbolo).get_earnings_dates(limit=limite)
        except Exception as e:  # noqa: BLE001
            raise ErrorDatos(f"{simbolo}: no se pudo obtener el calendario de resultados: {e}") from e
        if tabla is None or tabla.empty:
            raise SimboloSinDatos(f"{simbolo}: Yahoo no tiene fechas de resultados")
        eventos = []
        for fecha, fila in tabla.iterrows():
            ts = pd.Timestamp(fecha)
            ts = ts.tz_localize(NY) if ts.tzinfo is None else ts.tz_convert(NY)
            eventos.append(EventoResultados(ts.to_pydatetime(), _num(fila.get("EPS Estimate")),
                                            _num(fila.get("Reported EPS"))))
        return sorted(eventos, key=lambda e: e.fecha, reverse=True)

    @_reintentar
    def consenso(self, simbolo: str) -> ConsensoProximo:
        """Consenso de EPS e ingresos para la próxima presentación."""
        try:
            t = yf.Ticker(simbolo)
            cal = t.calendar or {}
            est = t.revenue_estimate
        except Exception as e:  # noqa: BLE001
            raise ErrorDatos(f"{simbolo}: no se pudo obtener el consenso: {e}") from e
        fechas = cal.get("Earnings Date") or []
        moneda = analistas = None
        ingresos = _num(cal.get("Revenue Average"))
        if est is not None and not est.empty and "0q" in est.index:
            fila = est.loc["0q"]
            moneda = fila.get("currency") if "currency" in est.columns else None
            analistas = int(fila["numberOfAnalysts"]) if _num(fila.get("numberOfAnalysts")) else None
            ingresos = ingresos or _num(fila.get("avg"))
        return ConsensoProximo(
            fecha=fechas[0] if fechas else None,
            eps=_num(cal.get("Earnings Average")),
            ingresos=ingresos if ingresos else None,
            moneda_ingresos=moneda,
            analistas=analistas,
        )

    @_reintentar
    def estados(self, simbolo: str) -> Estados:
        """Estados de resultados, balance y flujo de fondos trimestrales."""
        try:
            t = yf.Ticker(simbolo)
            resultados, balance, flujos = t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow
            moneda = (t.info or {}).get("financialCurrency")
        except Exception as e:  # noqa: BLE001
            raise ErrorDatos(f"{simbolo}: no se pudieron obtener los estados contables: {e}") from e
        if resultados is None or resultados.empty:
            raise SimboloSinDatos(f"{simbolo}: Yahoo no tiene estados contables")
        return Estados(resultados, balance, flujos, moneda)

    @_reintentar
    def info(self, simbolo: str) -> dict:
        """Datos generales y múltiplos de valuación."""
        try:
            return yf.Ticker(simbolo).info or {}
        except Exception as e:  # noqa: BLE001
            raise ErrorDatos(f"{simbolo}: no se pudo obtener la información: {e}") from e
