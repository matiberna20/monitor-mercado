"""Valuación básica: múltiplos de la empresa comparados con los de sus pares.

Un buen resultado no implica una buena compra: si el precio ya es muy alto en
relación con lo que gana la empresa, gran parte de lo bueno puede estar "en el
precio". Los múltiplos ayudan a ver eso:

- P/E (precio / ganancia por acción): cuántos años de ganancias actuales "pagás".
  El "forward" usa la ganancia esperada para los próximos 12 meses.
- EV/EBITDA: valor de la empresa (incluye deuda) sobre su generación operativa de caja.
  Sirve para comparar empresas con distinto nivel de deuda.
- P/B (precio / valor libro): útil sobre todo en bancos.
- P/S (precio / ventas): útil cuando la empresa todavía no gana dinero.

Solo tiene sentido comparar contra empresas parecidas (mismo sector) y ningún
múltiplo es "caro" o "barato" en absoluto: una empresa que crece mucho suele
tener múltiplos más altos.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.resultados.datos import FuenteResultadosYahoo

log = logging.getLogger(__name__)

MULTIPLOS = {
    "trailingPE": "P/E (últimos 12 meses)",
    "forwardPE": "P/E esperado (próximos 12 meses)",
    "enterpriseToEbitda": "EV/EBITDA",
    "priceToBook": "Precio / valor libro",
    "priceToSalesTrailing12Months": "Precio / ventas",
}
CAMPOS = [*MULTIPLOS, "sector", "industry", "currency", "financialCurrency", "shortName"]
# Múltiplos que dividen un precio por un dato del balance: se rompen si están en monedas distintas.
# (El P/E esperado usa la estimación de EPS, que viene en la misma moneda que el precio.)
SENSIBLES_A_MONEDA = {"trailingPE", "enterpriseToEbitda", "priceToBook", "priceToSalesTrailing12Months"}


def _moneda_distinta(info: dict) -> bool:
    return bool(info.get("currency") and info.get("financialCurrency")
                and info["currency"] != info["financialCurrency"])


def _num(v: object) -> float | None:
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None  # múltiplos negativos no se comparan


@dataclass(frozen=True)
class Multiplo:
    """Un múltiplo de la empresa, la mediana de sus pares y la lectura."""

    nombre: str
    empresa: float | None
    pares: float | None
    cantidad_pares: int

    @property
    def relacion(self) -> float | None:
        """empresa / mediana de pares (1 = igual que los pares)."""
        if self.empresa is None or self.pares is None:
            return None
        return self.empresa / self.pares

    @property
    def lectura(self) -> str:
        """Interpretación en palabras."""
        r = self.relacion
        if r is None:
            return "sin comparación"
        if r < 0.8:
            return "más barata que sus pares"
        if r > 1.2:
            return "más cara que sus pares"
        return "similar a sus pares"


@dataclass(frozen=True)
class Valuacion:
    """Múltiplos de la empresa y contra quién se comparó."""

    simbolo: str
    sector: str | None
    industria: str | None
    pares: list[str]
    multiplos: list[Multiplo]
    avisos: list[str]


class CacheInfo:
    """Guarda la información de Yahoo de cada símbolo un día, para no repetir consultas."""

    def __init__(self, archivo: Path, fuente: FuenteResultadosYahoo, horas: float = 24) -> None:
        self._archivo = archivo
        self._fuente = fuente
        self._vigencia = timedelta(hours=horas)
        self._datos: dict[str, dict] = {}
        if archivo.exists():
            try:
                self._datos = json.loads(archivo.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    def cacheado(self, simbolo: str) -> dict | None:
        """Datos guardados (aunque estén viejos), sin consultar."""
        return self._datos.get(simbolo.upper(), {}).get("info")

    def obtener(self, simbolo: str) -> dict:
        """Datos del símbolo, consultando Yahoo si no están o están viejos."""
        s = simbolo.upper()
        guardado = self._datos.get(s)
        if guardado and datetime.now() - datetime.fromisoformat(guardado["cuando"]) < self._vigencia:
            return guardado["info"]
        info = self._fuente.info(s)
        self._datos[s] = {"cuando": datetime.now().isoformat(), "info": {k: info.get(k) for k in CAMPOS}}
        self._archivo.parent.mkdir(parents=True, exist_ok=True)
        self._archivo.write_text(json.dumps(self._datos, ensure_ascii=False), encoding="utf-8")
        return self._datos[s]["info"]


def elegir_pares(
    simbolo: str, info: dict, configurados: dict[str, list[str]], watchlist: list[str], cache: CacheInfo,
    maximo: int = 8,
) -> list[str]:
    """Pares configurados; si no hay, los de la watchlist con la misma industria (o sector)."""
    s = simbolo.upper()
    if s in configurados:
        return [p.upper() for p in configurados[s]][:maximo]
    otros = [w for w in watchlist if w.upper() != s and not w.startswith("^")]
    conocidos = {w: cache.cacheado(w) for w in otros}
    for campo in ("industry", "sector"):
        valor = info.get(campo)
        if valor:
            iguales = [w for w, i in conocidos.items() if i and i.get(campo) == valor]
            if iguales:
                return iguales[:maximo]
    return []


def valuar(
    simbolo: str, cache: CacheInfo, configurados: dict[str, list[str]], watchlist: list[str]
) -> Valuacion:
    """Múltiplos de ``simbolo`` vs. la mediana de sus pares.

    Raises:
        ErrorDatos: Si no hay información de la empresa.
    """
    info = cache.obtener(simbolo)
    avisos: list[str] = []
    pares = elegir_pares(simbolo, info, configurados, watchlist, cache)
    infos_pares = []
    for p in pares:
        try:
            infos_pares.append(cache.obtener(p))
        except ErrorDatos as e:
            log.warning("Par %s sin datos: %s", p, e)
    if not pares:
        avisos.append("No hay pares para comparar: agregalos en config.yaml (resultados.pares) o corré "
                      "'monitor actualizar-sectores' para usar las empresas de tu watchlist del mismo sector.")

    if _moneda_distinta(info):
        avisos.append(f"Cotiza en {info['currency']} pero sus balances están en {info['financialCurrency']}: "
                      "los múltiplos que mezclan precio y balance pueden estar mal calculados y se omiten.")
    multiplos = []
    for clave, nombre in MULTIPLOS.items():
        sensible = clave in SENSIBLES_A_MONEDA
        if sensible and _moneda_distinta(info):
            continue
        # Los pares con el mismo problema de monedas tampoco se usan para esos múltiplos.
        valores = [v for i in infos_pares
                   if not (sensible and _moneda_distinta(i)) and (v := _num(i.get(clave))) is not None]
        multiplos.append(Multiplo(nombre, _num(info.get(clave)), statistics.median(valores) if valores else None,
                                  len(valores)))
    return Valuacion(simbolo.upper(), info.get("sector"), info.get("industry"), pares, multiplos, avisos)
