"""Horarios de las bolsas, para consultar precios solo cuando el mercado opera.

Simplificación consciente: no se contemplan feriados de cada país. En un feriado
el sistema consulta igual, pero el precio no cambia, así que no genera avisos
falsos; solo gasta algunas consultas de más.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Mercado:
    """Una bolsa con su huso horario y horario de la rueda regular."""

    nombre: str
    zona: str
    apertura: time
    cierre: time


EEUU = Mercado("EE.UU.", "America/New_York", time(9, 30), time(16, 0))
BYMA = Mercado("BYMA", "America/Argentina/Buenos_Aires", time(11, 0), time(17, 0))
B3 = Mercado("B3", "America/Sao_Paulo", time(10, 0), time(17, 0))
XETRA = Mercado("Xetra", "Europe/Berlin", time(9, 0), time(17, 30))
LONDRES = Mercado("Londres", "Europe/London", time(8, 0), time(16, 30))

_POR_SUFIJO: dict[str, Mercado] = {".BA": BYMA, ".SA": B3, ".DE": XETRA, ".L": LONDRES}


def mercado_de(simbolo: str) -> Mercado:
    """Bolsa de un símbolo según su sufijo de Yahoo (sin sufijo = EE.UU.)."""
    for sufijo, mercado in _POR_SUFIJO.items():
        if simbolo.upper().endswith(sufijo):
            return mercado
    return EEUU


def esta_abierto(simbolo: str, ahora: datetime, margen_minutos: int = 0) -> bool:
    """Indica si la bolsa del símbolo está operando en ``ahora``.

    Args:
        simbolo: Símbolo en formato Yahoo.
        ahora: Momento a evaluar, con zona horaria.
        margen_minutos: Minutos extra luego del cierre (por la demora de los datos).
    """
    mercado = mercado_de(simbolo)
    local = ahora.astimezone(ZoneInfo(mercado.zona))
    if local.weekday() >= 5:  # sábado o domingo
        return False
    apertura = datetime.combine(local.date(), mercado.apertura, local.tzinfo)
    cierre = datetime.combine(local.date(), mercado.cierre, local.tzinfo)
    return apertura <= local <= cierre + timedelta(minutes=margen_minutos)
