"""Interpretación del texto de los comandos para crear alertas.

Formato (el orden de las palabras opcionales no importa):

    SIMBOLO compra|venta sube|baja|var+|var- VALOR [ars] [repetir]

Ejemplos:
    AAPL compra baja 180          -> avisar si AAPL baja de 180 USD
    AAPL venta sube 27000 ars     -> avisar si el CEDEAR AAPL.BA sube de $27.000
    GGAL compra var- 5 repetir    -> avisar cada vez que GGAL caiga 5% en el día
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from monitor_mercado.alertas.modelos import Condicion, Moneda, Operacion


class ErrorFormato(ValueError):
    """El texto del comando no tiene el formato esperado."""


AYUDA_FORMATO = (
    "Formato: SIMBOLO compra|venta sube|baja|var+|var- VALOR [ars] [repetir]\n"
    "Ejemplos:\n"
    "  AAPL compra baja 180\n"
    "  AAPL venta sube 27000 ars   (precio del CEDEAR en pesos)\n"
    "  GGAL compra var- 5 repetir  (cae 5% en el día, avisa cada vez)"
)

_OPERACIONES = {"compra": Operacion.COMPRA, "venta": Operacion.VENTA}
_CONDICIONES = {
    "sube": Condicion.SUBE_DE,
    "sube_de": Condicion.SUBE_DE,
    "baja": Condicion.BAJA_DE,
    "baja_de": Condicion.BAJA_DE,
    "var+": Condicion.VARIACION_SUBE,
    "varsube": Condicion.VARIACION_SUBE,
    "var-": Condicion.VARIACION_BAJA,
    "varbaja": Condicion.VARIACION_BAJA,
}
_MONEDAS = {"ars": Moneda.ARS, "pesos": Moneda.ARS, "usd": Moneda.USD, "dolares": Moneda.USD}
_REPETIR = {"repetir", "rep", "siempre"}
_MILES = re.compile(r"\d{1,3}(\.\d{3})+")


@dataclass(frozen=True)
class SolicitudAlerta:
    """Datos de una alerta a crear, ya validados."""

    simbolo: str
    operacion: Operacion
    condicion: Condicion
    umbral: float
    moneda: Moneda = Moneda.USD
    repetir: bool = False
    nota: str | None = None


def parsear_numero(texto: str) -> float:
    """Convierte "180", "180.5", "180,5", "27.000" o "27.000,50" en número.

    Reglas (pensadas para el formato argentino):
      - Si aparecen punto y coma a la vez, el último es el separador decimal.
      - La coma sola es decimal ("180,5" = 180.5).
      - Puntos agrupando de a tres dígitos son miles ("27.000" = 27000).

    Raises:
        ErrorFormato: Si el texto no es un número positivo.
    """
    t = texto.strip().replace("$", "").replace("%", "")
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif _MILES.fullmatch(t):
        t = t.replace(".", "")
    try:
        valor = float(t)
    except ValueError as e:
        raise ErrorFormato(f"'{texto}' no es un número válido.") from e
    if valor <= 0:
        raise ErrorFormato("El valor tiene que ser mayor a cero.")
    return valor


def parsear_alerta(argumentos: list[str]) -> SolicitudAlerta:
    """Interpreta los argumentos de /alerta.

    Raises:
        ErrorFormato: Con un mensaje explicando qué falta o qué está mal.
    """
    if len(argumentos) < 4:
        raise ErrorFormato("Faltan datos.\n" + AYUDA_FORMATO)

    simbolo, operacion_txt, condicion_txt, valor_txt, *resto = argumentos
    operacion = _OPERACIONES.get(operacion_txt.lower())
    if operacion is None:
        raise ErrorFormato(f"'{operacion_txt}' no es válido: usá 'compra' o 'venta'.")
    condicion = _CONDICIONES.get(condicion_txt.lower())
    if condicion is None:
        raise ErrorFormato(f"'{condicion_txt}' no es válido: usá sube, baja, var+ o var-.")
    umbral = parsear_numero(valor_txt)

    moneda = Moneda.USD
    repetir = False
    for extra in resto:
        palabra = extra.lower()
        if palabra in _MONEDAS:
            moneda = _MONEDAS[palabra]
        elif palabra in _REPETIR:
            repetir = True
        else:
            raise ErrorFormato(f"No entiendo '{extra}'.\n" + AYUDA_FORMATO)

    return SolicitudAlerta(
        simbolo=simbolo.strip().upper(),
        operacion=operacion,
        condicion=condicion,
        umbral=umbral,
        moneda=moneda,
        repetir=repetir,
    )
