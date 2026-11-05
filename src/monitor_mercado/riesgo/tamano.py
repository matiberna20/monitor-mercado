"""Calculadora de tamaño de posición: cuántas acciones comprar para arriesgar lo que elegiste.

La idea: si comprás en ``entrada`` y vendés en ``stop``, perdés ``entrada - stop`` por
acción. Si estás dispuesto a perder ``riesgo`` en total, podés comprar
``riesgo / (entrada - stop)`` acciones. Así, una mala operación te cuesta siempre lo
mismo, sin importar lo volátil que sea la acción.

Formato del comando:

    SIMBOLO entrada PRECIO stop PRECIO riesgo VALOR [capital MONTO]

    AAPL entrada 200 stop 185 riesgo 1%          -> arriesgar el 1% del valor de tu cartera
    AAPL entrada 200 stop 185 riesgo 500         -> arriesgar US$ 500
    ALUA.BA entrada 820 stop 760 riesgo 1% capital 20000

Los precios van en la moneda del activo (pesos para ALUA.BA, como en tu broker); el
riesgo en monto y el capital, en dólares.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from monitor_mercado.alertas.parser import ErrorFormato, parsear_numero
from monitor_mercado.cartera.servicio import ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.monedas import ConversorMonedas
from monitor_mercado.datos.proveedor import ProveedorPrecios

AYUDA_TAMANO = (
    "Formato: SIMBOLO entrada PRECIO stop PRECIO riesgo VALOR [capital MONTO]\n"
    "Ejemplos:\n"
    "  AAPL entrada 200 stop 185 riesgo 1%      (1% del valor de tu cartera)\n"
    "  AAPL entrada 200 stop 185 riesgo 500     (US$ 500)\n"
    "  ALUA.BA entrada 820 stop 760 riesgo 1% capital 20000\n"
    "Los precios van en la moneda del activo; el riesgo en monto y el capital, en dólares."
)


@dataclass(frozen=True)
class SolicitudTamano:
    """Datos del cálculo, ya validados."""

    simbolo: str
    entrada: float  # moneda del activo
    stop: float  # moneda del activo
    riesgo: float  # fracción (0.01) si es porcentaje; USD si es monto
    riesgo_es_pct: bool
    capital: float | None = None  # USD; None = valor de la cartera


def parsear_tamano(argumentos: list[str]) -> SolicitudTamano:
    """Interpreta los argumentos de /tamano.

    Raises:
        ErrorFormato: Con un mensaje explicando qué falta o qué está mal.
    """
    if not argumentos:
        raise ErrorFormato("Faltan datos.\n" + AYUDA_TAMANO)
    simbolo, *resto = argumentos
    if len(resto) % 2:
        raise ErrorFormato("Cada dato va con su nombre (ej. 'entrada 200').\n" + AYUDA_TAMANO)
    valores = {resto[i].lower(): resto[i + 1] for i in range(0, len(resto), 2)}
    desconocidos = set(valores) - {"entrada", "stop", "riesgo", "capital"}
    if desconocidos:
        raise ErrorFormato(f"No entiendo '{', '.join(sorted(desconocidos))}'.\n" + AYUDA_TAMANO)
    faltan = [c for c in ("entrada", "stop", "riesgo") if c not in valores]
    if faltan:
        raise ErrorFormato(f"Falta: {', '.join(faltan)}.\n" + AYUDA_TAMANO)
    riesgo_txt = valores["riesgo"].strip()
    es_pct = riesgo_txt.endswith("%")
    riesgo = parsear_numero(riesgo_txt)
    if es_pct:
        if riesgo >= 100:
            raise ErrorFormato("El riesgo en % tiene que ser menor a 100 (lo usual es entre 0,5% y 2%).")
        riesgo /= 100
    entrada, stop = parsear_numero(valores["entrada"]), parsear_numero(valores["stop"])
    if stop >= entrada:
        raise ErrorFormato("El stop tiene que estar por debajo de la entrada (la calculadora es para compras).")
    capital = parsear_numero(valores["capital"]) if "capital" in valores else None
    return SolicitudTamano(simbolo.strip().upper(), entrada, stop, riesgo, es_pct, capital)


@dataclass(frozen=True)
class CalculoTamano:
    """Resultado de la calculadora (montos en USD)."""

    simbolo: str
    moneda: str  # moneda del activo
    entrada: float  # en la moneda del activo
    stop: float
    precio_actual: float | None  # en la moneda del activo
    capital: float
    capital_es_cartera: bool
    riesgo: float  # lo que estás dispuesto a perder
    acciones: int
    monto: float  # lo que hay que invertir
    perdida_maxima: float  # si toca el stop
    peso: float  # peso de ese símbolo en la cartera después de comprar
    valor_existente: float  # lo que ya tenías de ese símbolo
    limite: float
    limitado_por_capital: bool

    @property
    def supera_limite(self) -> bool:
        return self.peso > self.limite

    @property
    def distancia_stop(self) -> float:
        """Distancia de la entrada al stop (fracción)."""
        return 1 - self.stop / self.entrada


def calcular(
    entrada_usd: float, stop_usd: float, capital: float, riesgo_usd: float
) -> tuple[int, bool]:
    """Cantidad de acciones para arriesgar ``riesgo_usd`` (función pura).

    Returns:
        (acciones, limitado_por_capital). Si comprar todas costaría más que el capital,
        se compran las que alcancen.
    """
    por_accion = entrada_usd - stop_usd
    if por_accion <= 0:
        raise ValueError("el stop tiene que estar por debajo de la entrada")
    acciones = math.floor(riesgo_usd / por_accion + 1e-9)
    if acciones * entrada_usd > capital:
        return math.floor(capital / entrada_usd + 1e-9), True
    return acciones, False


class ServicioTamano:
    """Calcula el tamaño usando el precio, la moneda y el valor de tu cartera."""

    def __init__(self, proveedor: ProveedorPrecios, cfg: Configuracion, cartera: ServicioCartera | None) -> None:
        self._proveedor = proveedor
        self._cfg = cfg
        self._cartera = cartera

    def calcular(self, s: SolicitudTamano) -> CalculoTamano:
        """Hace el cálculo completo.

        Raises:
            ErrorDatos: Si no hay precio del símbolo o tipo de cambio.
            ValueError: Si no se puede saber el capital (sin cartera ni capital).
        """
        cot = self._proveedor.cotizacion(s.simbolo)
        factor = ConversorMonedas(self._proveedor, self._cfg.monedas).a_usd(1.0, cot.moneda)

        valor_existente, capital = 0.0, s.capital
        if self._cartera is not None:
            estado = self._cartera.estado()
            valor_existente = sum(f.valor or 0 for f in estado.posiciones if f.simbolo == s.simbolo)
            if capital is None:
                capital = estado.valor
        if not capital:
            raise ValueError("No hay cartera cargada: indicá el capital (ej. 'capital 20000').")

        riesgo = s.riesgo * capital if s.riesgo_es_pct else s.riesgo
        acciones, limitado = calcular(s.entrada * factor, s.stop * factor, capital, riesgo)
        monto = acciones * s.entrada * factor
        return CalculoTamano(
            simbolo=s.simbolo, moneda=cot.moneda, entrada=s.entrada, stop=s.stop, precio_actual=cot.precio,
            capital=capital, capital_es_cartera=s.capital is None, riesgo=riesgo, acciones=acciones,
            monto=monto, perdida_maxima=acciones * (s.entrada - s.stop) * factor,
            peso=(valor_existente + monto) / capital, valor_existente=valor_existente,
            limite=self._cfg.cartera.concentracion_maxima, limitado_por_capital=limitado,
        )
