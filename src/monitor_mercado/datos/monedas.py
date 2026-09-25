"""Conversión de precios a dólares y resolución de símbolos en pesos (BYMA).

Decisiones:
- Las alertas se expresan en USD por defecto. Un activo que cotiza en otra moneda
  (ALUA.BA en pesos, PETR4.SA en reales, VOW3.DE en euros, BARC.L en peniques)
  se convierte a USD con el tipo de cambio del momento.
- Para pasar pesos a dólares se usa por defecto el dólar CCL implícito
  (GGAL.BA * 10 / GGAL), que es el tipo de cambio que "usa" el mercado de
  acciones. El oficial se puede elegir en config.yaml.
- Una alerta en ARS sobre una acción de EE.UU. se evalúa sobre el precio de su
  CEDEAR en BYMA (ej. AAPL -> AAPL.BA). No hace falta el ratio del CEDEAR porque
  se compara directamente contra el precio en pesos que ves en tu broker.
"""

from __future__ import annotations

from monitor_mercado.configuracion import ConfigMonedas
from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.datos.proveedor import ProveedorPrecios

MONEDA_USD = "USD"
MONEDA_ARS = "ARS"

# Monedas que Yahoo informa en centavos (Londres cotiza en peniques).
_SUBUNIDADES: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 100.0),
    "GBX": ("GBP", 100.0),
    "ZAc": ("ZAR", 100.0),
    "ILA": ("ILS", 100.0),
}


def simbolo_para_moneda(simbolo: str, moneda: str, cfg: ConfigMonedas) -> str:
    """Devuelve el símbolo que hay que consultar para evaluar una alerta.

    Args:
        simbolo: Símbolo de la watchlist (ej. "AAPL", "BRK-B", "ALUA.BA").
        moneda: Moneda de la alerta ("USD" o "ARS").
        cfg: Configuración de monedas (reemplazos de símbolos en BYMA).

    Returns:
        Para USD, el mismo símbolo. Para ARS, el símbolo en BYMA: el propio si ya
        termina en ".BA", el reemplazo configurado, o "SIMBOLO.BA" sin guiones.

    Raises:
        ValueError: Si se pide ARS para un activo de otra bolsa no estadounidense.
    """
    simbolo = simbolo.upper()
    if moneda == MONEDA_USD:
        return simbolo
    if moneda != MONEDA_ARS:
        raise ValueError(f"Moneda no soportada: {moneda}")
    if simbolo.endswith(".BA"):
        return simbolo
    if simbolo in cfg.simbolos_byma:
        return cfg.simbolos_byma[simbolo].upper()
    if "." in simbolo or simbolo.startswith("^") or "=" in simbolo:
        raise ValueError(
            f"{simbolo} no cotiza en BYMA: las alertas en pesos son solo para "
            "acciones argentinas y CEDEARs."
        )
    return simbolo.replace("-", "") + ".BA"


class ConversorMonedas:
    """Convierte precios a USD. Guarda los tipos de cambio consultados (caché).

    Conviene crear una instancia nueva por cada ciclo de revisión, para que el
    tipo de cambio se actualice pero no se consulte una vez por alerta.
    """

    def __init__(self, proveedor: ProveedorPrecios, cfg: ConfigMonedas) -> None:
        self._proveedor = proveedor
        self._cfg = cfg
        self._cache: dict[str, float] = {}

    def dolar_ars(self) -> float:
        """Pesos por dólar según el tipo configurado (CCL u oficial)."""
        if "ARS" not in self._cache:
            if self._cfg.dolar_ars == "ccl":
                local = self._proveedor.cotizacion(self._cfg.ccl_accion_local).precio
                adr = self._proveedor.cotizacion(self._cfg.ccl_adr).precio
                self._cache["ARS"] = local * self._cfg.ccl_ratio / adr
            else:
                self._cache["ARS"] = self._proveedor.cotizacion("ARS=X").precio
        return self._cache["ARS"]

    def usd_por_unidad(self, moneda: str) -> float:
        """Cuántos USD vale una unidad de ``moneda`` (ej. EUR -> 1.14)."""
        if moneda == MONEDA_USD:
            return 1.0
        if moneda == MONEDA_ARS:
            return 1.0 / self.dolar_ars()
        if moneda not in self._cache:
            self._cache[moneda] = self._proveedor.cotizacion(f"{moneda}USD=X").precio
        return self._cache[moneda]

    def a_usd(self, precio: float, moneda: str) -> float:
        """Convierte ``precio`` expresado en ``moneda`` a dólares.

        Raises:
            ErrorDatos: Si no se pudo obtener el tipo de cambio.
        """
        if moneda in _SUBUNIDADES:
            moneda, divisor = _SUBUNIDADES[moneda]
            precio = precio / divisor
        try:
            return precio * self.usd_por_unidad(moneda)
        except ZeroDivisionError as e:
            raise ErrorDatos(f"Tipo de cambio inválido para {moneda}") from e
