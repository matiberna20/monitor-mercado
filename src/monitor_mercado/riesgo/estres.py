"""Prueba de estrés: cuánto perdería la cartera en escenarios de caída del mercado o suba del dólar.

Modelo (simple a propósito, para que se entienda):

1. **Beta** de cada posición contra su mercado: SPY para lo que cotiza afuera y el Merval
   para lo que cotiza en BYMA. Se calcula con retornos semanales de los últimos 2 años
   (semanal y no diario porque las bolsas cierran a distinta hora). Una beta de 1,5
   significa que, en promedio, cuando el mercado cayó 1% esa acción cayó 1,5%.
2. **Escenario "mercado −X%":** pérdida de cada posición = valor × beta × X.
3. **Escenario "dólar +30%":** lo que cotiza en pesos pierde, medido en dólares,
   1 − 1/1,3 ≈ 23%, suponiendo que su precio en pesos no se mueve (el peor caso).
4. **Correlaciones:** con la matriz de covarianzas de los retornos semanales se estima la
   volatilidad de toda la cartera, una pérdida mensual "de 1 cada 20 meses" (VaR 95%) y
   cuánto aporta cada posición al riesgo total (una acción muy correlacionada con el resto
   aporta más que su peso).
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
import pandas as pd

from monitor_mercado.cartera.servicio import EstadoCartera, ServicioCartera
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.mercados import BYMA, mercado_de

log = logging.getLogger(__name__)

Z_95 = 1.645
SEMANAS_POR_MES = 52 / 12


@dataclass(frozen=True)
class RiesgoPosicion:
    """Datos de riesgo de una posición."""

    simbolo: str
    valor: float  # USD
    peso: float
    beta: float
    referencia: str  # contra qué se midió la beta
    beta_estimada: bool  # True = sin historia suficiente, se usó 1
    en_pesos: bool
    aporte_riesgo: float | None  # fracción del riesgo total de la cartera


@dataclass(frozen=True)
class Escenario:
    """Resultado de un escenario."""

    nombre: str
    perdida: float  # USD (negativo = pérdida)
    perdida_pct: float
    aportes: list[tuple[str, float]]  # (símbolo, USD), de mayor a menor pérdida


@dataclass(frozen=True)
class ResultadoEstres:
    """Todo el reporte."""

    valor: float
    posiciones: list[RiesgoPosicion]
    escenarios: list[Escenario]
    volatilidad_anual: float | None
    var_mensual_pct: float | None  # pérdida mensual que se supera 1 de cada 20 meses
    sin_precio: list[str]
    semanas: int


def retornos_semanales(cierre: pd.Series, semanas: int) -> pd.Series:
    """Retornos de viernes a viernes de las últimas ``semanas``."""
    semanal = cierre.resample("W-FRI").last().dropna()
    return semanal.pct_change().dropna().iloc[-semanas:]


def calcular_beta(activo: pd.Series, mercado: pd.Series, minimo: int = 26) -> float | None:
    """Beta = cov(activo, mercado) / var(mercado), con las semanas en común (None si son pocas)."""
    juntos = pd.concat([activo, mercado], axis=1, join="inner").dropna()
    if len(juntos) < minimo or juntos.iloc[:, 1].var() == 0:
        return None
    return float(juntos.cov().iloc[0, 1] / juntos.iloc[:, 1].var())


def calcular_estres(
    estado: EstadoCartera,
    retornos: dict[str, pd.Series],
    mercados: dict[str, pd.Series],
    monedas: dict[str, str],
    cfg: Configuracion,
) -> ResultadoEstres:
    """Calcula betas, escenarios y riesgo con correlaciones (función pura).

    Args:
        retornos: Retornos semanales de cada posición.
        mercados: Retornos semanales de los índices ("EEUU" y "LOCAL").
        monedas: Moneda de cotización de cada símbolo.
    """
    e = cfg.estres
    filas = [f for f in estado.posiciones if f.valor]
    total = sum(f.valor for f in filas)

    # Riesgo de la cartera con la matriz de covarianzas (correlaciones históricas).
    con_datos = [f.simbolo for f in filas if f.simbolo in retornos and len(retornos[f.simbolo]) >= 26]
    aportes_riesgo: dict[str, float] = {}
    vol_anual = var_pct = None
    if con_datos and total:
        matriz = pd.DataFrame({s: retornos[s] for s in con_datos}).cov().to_numpy()
        w = np.array([next(f.valor for f in filas if f.simbolo == s) / total for s in con_datos])
        varianza = float(max(w @ matriz @ w, 0.0))
        if varianza > 0:
            vol_anual = math.sqrt(varianza * 52)
            var_pct = -Z_95 * math.sqrt(varianza * SEMANAS_POR_MES)
            marginal = matriz @ w
            aportes_riesgo = {s: float(w[i] * marginal[i] / varianza) for i, s in enumerate(con_datos)}

    posiciones = []
    for f in filas:
        local = mercado_de(f.simbolo) is BYMA
        referencia = e.indice_local if local else e.indice_eeuu
        indice = mercados.get("LOCAL" if local else "EEUU")
        beta = calcular_beta(retornos[f.simbolo], indice) if f.simbolo in retornos and indice is not None else None
        posiciones.append(RiesgoPosicion(
            simbolo=f.simbolo, valor=f.valor, peso=f.valor / total if total else 0.0,
            beta=beta if beta is not None else 1.0, referencia=referencia, beta_estimada=beta is None,
            en_pesos=monedas.get(f.simbolo) == "ARS", aporte_riesgo=aportes_riesgo.get(f.simbolo),
        ))

    escenarios = []
    for caida in e.caidas_mercado:
        perdidas = [(p.simbolo, max(-p.beta * caida, -1.0) * p.valor) for p in posiciones]
        escenarios.append(_escenario(f"Mercado −{caida:.0%}", perdidas, total))
    factor = 1 - 1 / (1 + e.suba_dolar)
    perdidas = [(p.simbolo, -factor * p.valor) for p in posiciones if p.en_pesos]
    escenarios.append(_escenario(f"Dólar +{e.suba_dolar:.0%}", perdidas, total))

    return ResultadoEstres(
        valor=total, posiciones=sorted(posiciones, key=lambda p: -p.valor), escenarios=escenarios,
        volatilidad_anual=vol_anual, var_mensual_pct=var_pct, sin_precio=estado.sin_precio, semanas=e.semanas,
    )


def _escenario(nombre: str, perdidas: list[tuple[str, float]], total: float) -> Escenario:
    suma = sum(v for _, v in perdidas)
    return Escenario(nombre, suma, suma / total if total else 0.0,
                     sorted(((s, v) for s, v in perdidas if v), key=lambda x: x[1]))


class ServicioEstres:
    """Junta los precios históricos (los mismos del análisis técnico) y corre el cálculo."""

    def __init__(self, almacen, cartera: ServicioCartera, proveedor, cfg: Configuracion) -> None:
        self._almacen = almacen
        self._cartera = cartera
        self._proveedor = proveedor
        self._cfg = cfg

    def _retornos(self, simbolo: str) -> pd.Series | None:
        try:
            return retornos_semanales(self._almacen.obtener(simbolo)["cierre"], self._cfg.estres.semanas)
        except Exception as e:  # noqa: BLE001 - sin historia se usa beta 1 y se avisa
            log.warning("Estrés: sin historial de %s: %s", simbolo, e)
            return None

    def correr(self) -> ResultadoEstres:
        """Valúa la cartera, baja los históricos y calcula los escenarios."""
        estado = self._cartera.estado()
        simbolos = [f.simbolo for f in estado.posiciones if f.valor]
        e = self._cfg.estres
        with ThreadPoolExecutor(max_workers=4) as pool:
            series = dict(zip(simbolos, pool.map(self._retornos, simbolos)))
            hay_local = any(mercado_de(s) is BYMA for s in simbolos)
            indices = {"EEUU": pool.submit(self._retornos, e.indice_eeuu)}
            if hay_local:
                indices["LOCAL"] = pool.submit(self._retornos, e.indice_local)
            mercados = {k: v.result() for k, v in indices.items()}
        monedas = {s: c.moneda for s, c in self._proveedor.cotizaciones(simbolos).items()}
        return calcular_estres(
            estado, {s: r for s, r in series.items() if r is not None},
            {k: v for k, v in mercados.items() if v is not None}, monedas, self._cfg,
        )
