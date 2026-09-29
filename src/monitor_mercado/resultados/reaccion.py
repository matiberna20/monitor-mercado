"""Reacción del precio en los días posteriores a la presentación de resultados.

Se compara contra el índice (SPY): si la acción subió 3% pero el mercado subió 3%
ese mismo día, la reacción "propia" a los resultados fue ~0%. A esa diferencia se
la llama retorno anormal.

Detalle importante: muchas empresas publican DESPUÉS del cierre (ej. 16:05 en Nueva
York). En ese caso el mercado reacciona recién en la rueda siguiente, así que el
precio de referencia es el cierre del mismo día de la presentación.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass(frozen=True)
class Reaccion:
    """Variación de la acción y del índice N ruedas después de la presentación."""

    ruedas: int
    accion: float
    indice: float | None

    @property
    def anormal(self) -> float:
        """Variación propia de la acción (descontando al mercado)."""
        return self.accion - (self.indice or 0.0)


def precio_base(cierres: pd.Series, presentacion: datetime) -> pd.Timestamp | None:
    """Última rueda cuyo cierre es ANTERIOR a que se conociera el resultado."""
    dia = pd.Timestamp(presentacion.date())
    # Antes de las 9:30 (hora NY) el resultado se conoció antes de abrir: la base es la rueda previa.
    antes_de_abrir = presentacion.hour < 9 or (presentacion.hour == 9 and presentacion.minute < 30)
    candidatas = cierres.index[cierres.index < dia] if antes_de_abrir else cierres.index[cierres.index <= dia]
    return candidatas[-1] if len(candidatas) else None


def calcular_reaccion(
    cierres: pd.Series,
    cierres_indice: pd.Series | None,
    presentacion: datetime,
    ruedas: tuple[int, ...] = (1, 3, 5),
) -> list[Reaccion]:
    """Reacciones a 1, 3 y 5 ruedas (solo las que ya ocurrieron).

    Args:
        cierres: Cierres diarios de la acción (índice = fecha).
        cierres_indice: Cierres diarios del índice de referencia (o None).
        presentacion: Fecha y hora de la presentación, en hora de Nueva York.
    """
    base = precio_base(cierres, presentacion)
    if base is None:
        return []
    posicion = cierres.index.get_loc(base)
    reacciones = []
    for n in ruedas:
        if posicion + n >= len(cierres):
            break
        fin = cierres.index[posicion + n]
        accion = cierres.iloc[posicion + n] / cierres.iloc[posicion] - 1
        indice = None
        if cierres_indice is not None and base in cierres_indice.index and fin in cierres_indice.index:
            indice = cierres_indice[fin] / cierres_indice[base] - 1
        reacciones.append(Reaccion(n, float(accion), None if indice is None else float(indice)))
    return reacciones
