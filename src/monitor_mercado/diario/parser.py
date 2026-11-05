"""Interpretación de /compre, /vendi y /editar_op.

    /compre SIMBOLO CANTIDAD PRECIO [comision X] [fecha AAAA-MM-DD] [moneda ARS] [nota TEXTO...]
    /vendi  SIMBOLO CANTIDAD PRECIO [comision X] [fecha DD/MM/AAAA] [nota TEXTO...]
    /editar_op ID CAMPO VALOR   (campos: fecha, simbolo, cantidad, precio, comision, moneda, nota)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from monitor_mercado.alertas.parser import ErrorFormato, parsear_numero
from monitor_mercado.cartera.archivo import normalizar_simbolo

AYUDA_MOVIMIENTO = (
    "Formato: SIMBOLO CANTIDAD PRECIO [comision X] [fecha AAAA-MM-DD] [moneda ARS] [nota TEXTO]\n"
    "Ejemplos:\n"
    "  /compre AAPL 10 180,50\n"
    "  /compre ALUA.BA 500 820 comision 2460 nota apuesta a la suba del aluminio\n"
    "  /vendi NVDA 20 210 fecha 2026-11-03 nota tomé ganancia\n"
    "El precio es por acción y en la moneda del activo (pesos para .BA). La fecha, por defecto, es hoy."
)

CAMPOS_EDITABLES = ("fecha", "simbolo", "cantidad", "precio", "comision", "moneda", "nota")

# Moneda por defecto según la bolsa (se puede cambiar con "moneda X").
_MONEDA_POR_SUFIJO = {".BA": "ARS", ".SA": "BRL", ".DE": "EUR", ".L": "GBp"}


def moneda_por_defecto(simbolo: str) -> str:
    for sufijo, moneda in _MONEDA_POR_SUFIJO.items():
        if simbolo.upper().endswith(sufijo):
            return moneda
    return "USD"


def parsear_fecha(texto: str) -> date:
    """Acepta AAAA-MM-DD o DD/MM/AAAA."""
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto.strip(), formato).date()
        except ValueError:
            continue
    raise ErrorFormato(f"'{texto}' no es una fecha válida: usá AAAA-MM-DD o DD/MM/AAAA.")


@dataclass(frozen=True)
class SolicitudMovimiento:
    """Datos de una compra o venta, ya validados."""

    simbolo: str
    cantidad: float
    precio: float
    comision: float = 0.0
    fecha: date | None = None
    moneda: str | None = None
    nota: str | None = None


def parsear_movimiento(argumentos: list[str]) -> SolicitudMovimiento:
    """Interpreta los argumentos de /compre y /vendi.

    Raises:
        ErrorFormato: Con un mensaje claro de qué falta.
    """
    if len(argumentos) < 3:
        raise ErrorFormato("Faltan datos.\n" + AYUDA_MOVIMIENTO)
    simbolo, cantidad_txt, precio_txt, *resto = argumentos
    cantidad, precio = parsear_numero(cantidad_txt), parsear_numero(precio_txt)
    comision, fecha, moneda, nota = 0.0, None, None, None
    i = 0
    while i < len(resto):
        palabra = resto[i].lower()
        if palabra in ("nota", "nota:"):
            nota = " ".join(resto[i + 1:]).strip()[:300] or None
            break
        if i + 1 >= len(resto):
            raise ErrorFormato(f"Falta el valor de '{resto[i]}'.\n" + AYUDA_MOVIMIENTO)
        valor = resto[i + 1]
        if palabra in ("comision", "comisión"):
            comision = float(valor.replace(",", ".")) if valor.strip() in ("0", "0,0", "0.0") else parsear_numero(valor)
        elif palabra == "fecha":
            fecha = parsear_fecha(valor)
        elif palabra == "moneda":
            moneda = valor.strip()
            moneda = "GBp" if moneda.lower() == "gbp" else moneda.upper()
        else:
            raise ErrorFormato(f"No entiendo '{resto[i]}'.\n" + AYUDA_MOVIMIENTO)
        i += 2
    return SolicitudMovimiento(normalizar_simbolo(simbolo), cantidad, precio, comision, fecha, moneda, nota)


def parsear_edicion(argumentos: list[str]) -> tuple[int, str, object]:
    """Interpreta /editar_op ID CAMPO VALOR y convierte el valor al tipo del campo.

    Raises:
        ErrorFormato: Si falta algo o el valor no es válido.
    """
    uso = "Uso: /editar_op ID CAMPO VALOR (campos: " + ", ".join(CAMPOS_EDITABLES) + ")"
    if len(argumentos) < 3:
        raise ErrorFormato(uso)
    try:
        id_mov = int(argumentos[0].lstrip("#"))
    except ValueError as e:
        raise ErrorFormato(uso) from e
    campo = argumentos[1].lower().replace("comisión", "comision").replace("símbolo", "simbolo")
    texto = " ".join(argumentos[2:]).strip()
    if campo not in CAMPOS_EDITABLES:
        raise ErrorFormato(f"No se puede editar '{argumentos[1]}'. " + uso)
    if campo == "fecha":
        return id_mov, campo, parsear_fecha(texto)
    if campo == "simbolo":
        return id_mov, campo, normalizar_simbolo(texto)
    if campo == "moneda":
        return id_mov, campo, "GBp" if texto.lower() == "gbp" else texto.upper()
    if campo == "nota":
        return id_mov, campo, texto[:300] or None
    if campo == "comision" and texto in ("0", "0,0", "0.0"):
        return id_mov, campo, 0.0
    return id_mov, campo, parsear_numero(texto)
