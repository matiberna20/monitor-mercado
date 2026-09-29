"""Métricas de un trimestre a partir de los estados contables (funciones puras).

Los estados vienen como tablas con una fila por concepto ("Total Revenue",
"Net Income"...) y una columna por fecha de cierre de trimestre, de la más
reciente a la más vieja (formato de Yahoo Finance).

Conceptos:
- Crecimiento interanual (YoY): contra el mismo trimestre del año anterior. Es el
  más importante porque elimina la estacionalidad (ej. las ventas navideñas).
- Crecimiento trimestral (QoQ): contra el trimestre inmediatamente anterior.
- Margen bruto = ganancia bruta / ingresos: cuánto queda después del costo directo.
- Margen operativo = resultado operativo / ingresos: después de todos los gastos del negocio.
- Margen neto = ganancia neta / ingresos: lo que queda para los accionistas.
- Flujo de caja libre (FCF) = flujo operativo - inversiones en activos (capex).
- Deuda neta = deuda total - caja. Negativa significa que tiene más caja que deuda.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import pandas as pd


def _valor(tabla: pd.DataFrame | None, filas: tuple[str, ...], columna) -> float | None:
    """Primer concepto disponible de ``filas`` en ``columna`` (None si no hay dato)."""
    if tabla is None or tabla.empty or columna not in tabla.columns:
        return None
    for fila in filas:
        if fila in tabla.index:
            v = tabla.at[fila, columna]
            if v is not None and not (isinstance(v, float) and math.isnan(v)):
                return float(v)
    return None


def _variacion(actual: float | None, anterior: float | None) -> float | None:
    if actual is None or anterior is None or anterior == 0:
        return None
    return (actual - anterior) / abs(anterior)


def _cociente(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


INGRESOS = ("Total Revenue", "Operating Revenue")
BRUTA = ("Gross Profit",)
OPERATIVO = ("Operating Income", "Total Operating Income As Reported")
NETA = ("Net Income", "Net Income Common Stockholders")
EPS = ("Diluted EPS", "Basic EPS")
EBITDA = ("EBITDA", "Normalized EBITDA")
DEUDA = ("Total Debt",)
CAJA = ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
FLUJO_OPERATIVO = ("Operating Cash Flow",)
CAPEX = ("Capital Expenditure",)
FCF = ("Free Cash Flow",)


@dataclass(frozen=True)
class Metricas:
    """Números clave de un trimestre y sus comparaciones."""

    trimestre: date
    ingresos: float | None
    ganancia_neta: float | None
    eps: float | None
    ingresos_yoy: float | None
    ingresos_qoq: float | None
    ganancia_yoy: float | None
    eps_yoy: float | None
    margen_bruto: float | None
    margen_operativo: float | None
    margen_neto: float | None
    margen_bruto_hace_un_anio: float | None
    margen_operativo_hace_un_anio: float | None
    margen_neto_hace_un_anio: float | None
    deuda_total: float | None
    caja: float | None
    deuda_neta: float | None
    ebitda_12m: float | None
    deuda_neta_sobre_ebitda: float | None
    flujo_operativo: float | None
    capex: float | None
    fcf: float | None
    fcf_12m: float | None


def elegir_trimestre(columnas: list, fecha_presentacion: date) -> pd.Timestamp | None:
    """Trimestre al que corresponde una presentación de resultados.

    Es el último cierre de trimestre anterior a la fecha de presentación y dentro de
    los 120 días previos (las empresas publican entre 3 semanas y 3 meses después).
    """
    candidatos = [
        c for c in columnas
        if pd.Timestamp(c).date() < fecha_presentacion
        and (fecha_presentacion - pd.Timestamp(c).date()).days <= 120
    ]
    return max(candidatos) if candidatos else None


def _columna_desplazada(columnas: list, base, trimestres: int):
    """Columna que está ``trimestres`` trimestres antes de ``base`` (±25 días de tolerancia)."""
    objetivo = pd.Timestamp(base) - pd.DateOffset(months=3 * trimestres)
    cercanas = [c for c in columnas if abs((pd.Timestamp(c) - objetivo).days) <= 25]
    return cercanas[0] if cercanas else None


def _suma_12m(tabla: pd.DataFrame | None, filas: tuple[str, ...], base) -> float | None:
    """Suma de los últimos 4 trimestres hasta ``base`` (None si falta alguno)."""
    if tabla is None or tabla.empty:
        return None
    valores = []
    for k in range(4):
        col = _columna_desplazada(list(tabla.columns), base, k)
        v = _valor(tabla, filas, col) if col is not None else None
        if v is None:
            return None
        valores.append(v)
    return sum(valores)


def calcular_metricas(
    resultados: pd.DataFrame,
    balance: pd.DataFrame | None,
    flujos: pd.DataFrame | None,
    trimestre,
) -> Metricas:
    """Métricas del ``trimestre`` (una columna de ``resultados``)."""
    cols = list(resultados.columns)
    anio = _columna_desplazada(cols, trimestre, 4)
    previo = _columna_desplazada(cols, trimestre, 1)

    def v(filas, col=trimestre, tabla=resultados):
        return _valor(tabla, filas, col) if col is not None else None

    ingresos, ingresos_anio = v(INGRESOS), v(INGRESOS, anio)
    neta, neta_anio = v(NETA), v(NETA, anio)
    eps, eps_anio = v(EPS), v(EPS, anio)

    col_bal = trimestre if balance is not None and trimestre in balance.columns else None
    deuda = v(DEUDA, col_bal, balance)
    caja = v(CAJA, col_bal, balance)
    deuda_neta = deuda - caja if deuda is not None and caja is not None else None
    ebitda_12m = _suma_12m(resultados, EBITDA, trimestre)

    col_fl = trimestre if flujos is not None and trimestre in flujos.columns else None
    flujo_op = v(FLUJO_OPERATIVO, col_fl, flujos)
    capex = v(CAPEX, col_fl, flujos)
    fcf = v(FCF, col_fl, flujos)
    if fcf is None and flujo_op is not None and capex is not None:
        fcf = flujo_op + capex  # el capex viene con signo negativo

    return Metricas(
        trimestre=pd.Timestamp(trimestre).date(),
        ingresos=ingresos,
        ganancia_neta=neta,
        eps=eps,
        ingresos_yoy=_variacion(ingresos, ingresos_anio),
        ingresos_qoq=_variacion(ingresos, v(INGRESOS, previo)),
        ganancia_yoy=_variacion(neta, neta_anio),
        eps_yoy=_variacion(eps, eps_anio),
        margen_bruto=_cociente(v(BRUTA), ingresos),
        margen_operativo=_cociente(v(OPERATIVO), ingresos),
        margen_neto=_cociente(neta, ingresos),
        margen_bruto_hace_un_anio=_cociente(v(BRUTA, anio), ingresos_anio),
        margen_operativo_hace_un_anio=_cociente(v(OPERATIVO, anio), ingresos_anio),
        margen_neto_hace_un_anio=_cociente(neta_anio, ingresos_anio),
        deuda_total=deuda,
        caja=caja,
        deuda_neta=deuda_neta,
        ebitda_12m=ebitda_12m,
        deuda_neta_sobre_ebitda=_cociente(deuda_neta, ebitda_12m) if ebitda_12m and ebitda_12m > 0 else None,
        flujo_operativo=flujo_op,
        capex=capex,
        fcf=fcf,
        fcf_12m=_suma_12m(flujos, FCF, trimestre),
    )
