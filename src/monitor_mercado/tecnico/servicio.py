"""Caso de uso del análisis técnico: datos -> indicadores -> patrones -> señal."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.modelos import ErrorDatos
from monitor_mercado.tecnico.historico import AlmacenHistorico
from monitor_mercado.tecnico.indicadores import calcular_indicadores
from monitor_mercado.tecnico.lectura import LecturaGrafico, leer_grafico
from monitor_mercado.tecnico.patrones import PatronDetectado, patrones_recientes
from monitor_mercado.tecnico.senal import GeneradorSenal, Senal, SenalPorReglas

log = logging.getLogger(__name__)

_MONEDA_POR_SUFIJO = {".BA": "ARS", ".SA": "BRL", ".DE": "EUR", ".L": "GBp"}
MINIMO_RUEDAS = 60  # con menos datos casi ningún indicador es confiable


def moneda_nativa(simbolo: str) -> str:
    """Moneda en que cotiza un símbolo, según su sufijo de Yahoo."""
    if simbolo.startswith("^"):
        return "puntos"
    for sufijo, moneda in _MONEDA_POR_SUFIJO.items():
        if simbolo.upper().endswith(sufijo):
            return moneda
    return "USD"


@dataclass(frozen=True)
class Analisis:
    """Resultado completo del análisis técnico de un activo."""

    simbolo: str
    moneda: str
    datos: pd.DataFrame  # OHLCV + indicadores
    senal: Senal
    patrones: list[PatronDetectado]
    en_ccl: bool = False
    lectura: LecturaGrafico | None = None  # lectura del gráfico "como un trader"

    @property
    def ultimo(self) -> pd.Series:
        """Última rueda con todos sus indicadores."""
        return self.datos.iloc[-1]


class ServicioTecnico:
    """Orquesta la obtención de datos y el análisis."""

    def __init__(
        self,
        almacen: AlmacenHistorico,
        cfg: Configuracion,
        generador: GeneradorSenal | None = None,
    ) -> None:
        self.almacen = almacen
        self._cfg = cfg
        self.generador = generador or SenalPorReglas(cfg.tecnico.umbral_tendencia)

    def serie_ccl(self) -> pd.Series:
        """Dólar CCL implícito diario: acción local * ratio / ADR."""
        m = self._cfg.monedas
        local = self.almacen.obtener(m.ccl_accion_local)["cierre"]
        adr = self.almacen.obtener(m.ccl_adr)["cierre"]
        ccl = (local * m.ccl_ratio / adr).dropna()
        return ccl[ccl > 0]

    def datos(self, simbolo: str) -> tuple[pd.DataFrame, str, bool]:
        """Precios diarios listos para analizar, su moneda y si se pasaron a CCL.

        Las acciones argentinas en pesos se convierten a dólares CCL (si está
        activado), para que la inflación no se confunda con tendencia alcista.
        """
        simbolo = simbolo.upper()
        df = self.almacen.obtener(simbolo)
        moneda = moneda_nativa(simbolo)
        if moneda == "ARS" and self._cfg.tecnico.ars_en_dolares_ccl:
            ccl = self.serie_ccl().reindex(df.index).ffill(limit=5)
            df = df.copy()
            for col in ("apertura", "maximo", "minimo", "cierre"):
                df[col] = df[col] / ccl
            df = df.dropna(subset=["cierre"])
            return df, "USD (CCL)", True
        return df, moneda, False

    def analizar(self, simbolo: str) -> Analisis:
        """Análisis técnico completo de un símbolo.

        Raises:
            ErrorDatos: Si no hay datos o la historia es demasiado corta.
        """
        simbolo = simbolo.upper()
        df, moneda, en_ccl = self.datos(simbolo)
        if len(df) < MINIMO_RUEDAS:
            raise ErrorDatos(f"{simbolo}: solo hay {len(df)} ruedas, se necesitan {MINIMO_RUEDAS}.")
        con_indicadores = calcular_indicadores(df)
        try:
            lectura = leer_grafico(con_indicadores)
        except Exception:  # noqa: BLE001 - la lectura es un complemento: no debe frenar el análisis
            log.exception("%s: no se pudo leer el gráfico", simbolo)
            lectura = None
        return Analisis(
            simbolo=simbolo,
            moneda=moneda,
            datos=con_indicadores,
            senal=self.generador.generar(con_indicadores),
            patrones=patrones_recientes(con_indicadores, self._cfg.tecnico.ruedas_patrones),
            en_ccl=en_ccl,
            lectura=lectura,
        )

    def resumen(self, simbolos: list[str]) -> tuple[list[Analisis], dict[str, str]]:
        """Analiza varios símbolos; devuelve los análisis y los errores por símbolo."""
        analisis: list[Analisis] = []
        errores: dict[str, str] = {}
        for s in simbolos:
            try:
                analisis.append(self.analizar(s))
            except ErrorDatos as e:
                log.warning("No se pudo analizar %s: %s", s, e)
                errores[s] = str(e)
        return analisis, errores
