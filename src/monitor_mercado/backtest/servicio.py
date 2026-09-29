"""Caso de uso del backtest: prueba la señal técnica de un activo (o de varios)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from monitor_mercado.backtest.motor import DIAS_POR_ANIO, Metricas, calcular_metricas, posiciones, simular
from monitor_mercado.backtest.validacion import (
    PoderPredictivo, ResultadoWalkForward, bootstrap_sharpe, poder_predictivo, walk_forward,
)
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.mercados import mercado_de
from monitor_mercado.tecnico.indicadores import calcular_indicadores
from monitor_mercado.tecnico.senal import SenalPorReglas, caracteristicas
from monitor_mercado.tecnico.servicio import ServicioTecnico

log = logging.getLogger(__name__)
CALENTAMIENTO = 200  # ruedas necesarias para que existan todos los indicadores (media de 200)


class Conclusion(StrEnum):
    """Qué dice el backtest sobre la señal."""

    APORTA = "hay evidencia de que la señal aporta valor"
    DUDOSA = "rindió mejor, pero la diferencia puede ser azar"
    MENOS_RIESGO = "no rinde más, pero reduce las caídas"
    NO_APORTA = "la señal NO aporta valor frente a comprar y mantener"


@dataclass(frozen=True)
class ResultadoBacktest:
    """Resultado completo del backtest de un activo."""

    simbolo: str
    moneda: str
    desde: pd.Timestamp
    hasta: pd.Timestamp
    costo_por_lado: float
    fija: Metricas  # la señal tal como la usa el sistema, sin optimizar
    fija_bh: Metricas
    fija_retornos: pd.DataFrame
    wf: ResultadoWalkForward
    wf_estrategia: Metricas | None
    wf_bh: Metricas | None
    prob_azar_fija: float
    prob_azar_wf: float | None
    predictivo: PoderPredictivo
    conclusion: Conclusion


def _concluir(estrategia: Metricas, bh: Metricas, prob_azar: float) -> Conclusion:
    if estrategia.sharpe > bh.sharpe:
        return Conclusion.APORTA if prob_azar < 0.10 else Conclusion.DUDOSA
    if estrategia.max_drawdown > bh.max_drawdown + 0.10 and estrategia.sharpe > bh.sharpe - 0.15:
        return Conclusion.MENOS_RIESGO
    return Conclusion.NO_APORTA


class ServicioBacktest:
    """Corre el backtest con los mismos datos y la misma señal que usa el sistema."""

    def __init__(self, tecnico: ServicioTecnico, cfg: Configuracion) -> None:
        self._tecnico = tecnico
        self._cfg = cfg

    def costo(self, simbolo: str) -> float:
        """Comisión del mercado del símbolo + slippage, por cada compra o venta."""
        b = self._cfg.backtest
        return b.comisiones.get(mercado_de(simbolo).nombre, b.comision_por_defecto) + b.slippage

    def correr(self, simbolo: str) -> ResultadoBacktest:
        """Backtest completo de un activo.

        Raises:
            ErrorDatos: Si no hay historia suficiente.
        """
        b = self._cfg.backtest
        simbolo = simbolo.upper()
        datos, moneda, _ = self._tecnico.datos(simbolo)
        minimo = CALENTAMIENTO + (b.anios_entrenamiento + 1) * DIAS_POR_ANIO
        if len(datos) < minimo:
            raise ErrorDatos(f"{simbolo}: hay {len(datos)} ruedas y el backtest necesita al menos {minimo} "
                             f"(~{minimo // DIAS_POR_ANIO} años).")
        ind = calcular_indicadores(datos)
        generador = SenalPorReglas(self._cfg.tecnico.umbral_tendencia)
        puntajes = generador.puntajes(caracteristicas(ind))["puntaje"]
        # Se descartan las primeras ruedas, donde todavía no existen todos los indicadores.
        datos, puntajes = datos.iloc[CALENTAMIENTO:], puntajes.iloc[CALENTAMIENTO:]
        costo = self.costo(simbolo)

        # 1. La señal tal como la usa el sistema: compra si es alcista, sale si es bajista.
        u = self._cfg.tecnico.umbral_tendencia
        sim = simular(datos, posiciones(puntajes, u, -u, b.permitir_corto), costo)
        fija = calcular_metricas(sim["estrategia"], sim)
        fija_bh = calcular_metricas(sim["comprar_y_mantener"])
        prob_fija = bootstrap_sharpe(sim["estrategia"], sim["comprar_y_mantener"], b.repeticiones_bootstrap)

        # 2. Walk-forward: parámetros optimizados solo con el pasado y medidos en el futuro.
        wf = walk_forward(datos, puntajes, costo, b.anios_entrenamiento, b.anios_prueba, b.permitir_corto)
        wf_est = wf_bh = prob_wf = None
        if len(wf.retornos):
            wf_est = calcular_metricas(wf.retornos["estrategia"], wf.retornos)
            wf_bh = calcular_metricas(wf.retornos["comprar_y_mantener"])
            prob_wf = bootstrap_sharpe(wf.retornos["estrategia"], wf.retornos["comprar_y_mantener"],
                                       b.repeticiones_bootstrap)

        predictivo = poder_predictivo(puntajes, datos["cierre"], u, b.horizonte_dias)
        # La conclusión se basa en la prueba fuera de muestra si existe (es la más exigente).
        if wf_est is not None and wf_bh is not None and prob_wf is not None:
            conclusion = _concluir(wf_est, wf_bh, prob_wf)
        else:
            conclusion = _concluir(fija, fija_bh, prob_fija)
        return ResultadoBacktest(
            simbolo, moneda, datos.index[0], datos.index[-1], costo, fija, fija_bh, sim, wf, wf_est, wf_bh,
            prob_fija, prob_wf, predictivo, conclusion,
        )

    def correr_varios(self, simbolos: list[str]) -> tuple[list[ResultadoBacktest], dict[str, str]]:
        """Backtest de varios activos; devuelve resultados y errores por símbolo."""
        resultados, errores = [], {}
        for s in simbolos:
            try:
                resultados.append(self.correr(s))
            except ErrorDatos as e:
                errores[s] = str(e)
            except Exception as e:  # noqa: BLE001 - un activo con datos raros no frena al resto
                log.exception("Backtest de %s falló", s)
                errores[s] = f"error inesperado: {e}"
        return resultados, errores
