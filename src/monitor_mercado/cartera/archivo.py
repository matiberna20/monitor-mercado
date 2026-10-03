"""Lectura del archivo de cartera (mi_cartera.csv).

Formato (una fila por posición, las columnas opcionales pueden quedar vacías):

    simbolo,cantidad,precio_compra,moneda,fecha_compra,nota
    AAPL,120,302.46,USD,2025-03-15,
    BTC,100,,USD,,costo no informado

- ``precio_compra``: precio PROMEDIO pagado por acción. Vacío = desconocido (la
  posición se sigue igual, pero no entra en el cálculo de ganancia).
- Acepta símbolos como los muestra el broker: "AAPL.E" -> "AAPL", "BRK.B" -> "BRK-B".
- Números con punto o coma decimal ("302.46" o "302,46").
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class ErrorCartera(ValueError):
    """El archivo de cartera tiene un error (se indica la fila)."""


@dataclass(frozen=True)
class Posicion:
    """Una tenencia de tu cartera."""

    simbolo: str
    cantidad: float
    precio_compra: float | None
    moneda: str = "USD"
    fecha_compra: date | None = None
    nota: str = ""

    @property
    def costo(self) -> float | None:
        """Lo que pagaste por toda la posición (None si no se conoce el precio)."""
        return None if self.precio_compra is None else self.cantidad * self.precio_compra


def normalizar_simbolo(texto: str) -> str:
    """Pasa el símbolo del broker al formato de Yahoo."""
    s = texto.strip().upper()
    if s.endswith(".E"):  # sufijo de algunos brokers para acciones del exterior
        s = s[:-2]
    partes = s.split(".")
    # "BRK.B" -> "BRK-B" (clase de acción), pero "ALUA.BA" / "PETR4.SA" quedan igual.
    if len(partes) == 2 and len(partes[1]) == 1:
        s = f"{partes[0]}-{partes[1]}"
    return s


def _numero(texto: str, fila: int, campo: str) -> float | None:
    t = (texto or "").strip().replace("u$s", "").replace("$", "").strip()
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        valor = float(t)
    except ValueError as e:
        raise ErrorCartera(f"Fila {fila}: '{texto}' no es un número válido en '{campo}'.") from e
    return valor


def leer_cartera(ruta: Path) -> list[Posicion]:
    """Lee y valida el archivo de cartera.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        ErrorCartera: Si una fila tiene datos inválidos.
    """
    posiciones: dict[str, Posicion] = {}
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        for n, fila in enumerate(csv.DictReader(f), start=2):
            if not (fila.get("simbolo") or "").strip():
                continue
            simbolo = normalizar_simbolo(fila["simbolo"])
            cantidad = _numero(fila.get("cantidad", ""), n, "cantidad")
            if cantidad is None or cantidad <= 0:
                raise ErrorCartera(f"Fila {n} ({simbolo}): la cantidad tiene que ser mayor a cero.")
            precio = _numero(fila.get("precio_compra", ""), n, "precio_compra")
            if precio is not None and precio <= 0:
                precio = None  # el broker informa 0 cuando no conoce el costo
            fecha = None
            if (texto := (fila.get("fecha_compra") or "").strip()):
                try:
                    fecha = date.fromisoformat(texto)
                except ValueError as e:
                    raise ErrorCartera(f"Fila {n} ({simbolo}): la fecha debe ser AAAA-MM-DD.") from e
            if simbolo in posiciones:
                raise ErrorCartera(f"Fila {n}: {simbolo} aparece dos veces; unificá la posición en una fila.")
            posiciones[simbolo] = Posicion(
                simbolo, cantidad, precio, (fila.get("moneda") or "USD").strip().upper() or "USD",
                fecha, (fila.get("nota") or "").strip(),
            )
    return list(posiciones.values())
