"""Descarga y almacenamiento local de precios históricos diarios.

- Se guardan en CSV (``data/historico/SIMBOLO.csv``): se pueden abrir en Excel.
- La primera vez se baja toda la historia configurada; después solo las últimas
  ruedas, que se combinan con lo guardado (descarga incremental).
- Los precios están ajustados por splits y dividendos: sin ajuste, un split 4:1
  aparecería como una caída del 75% y arruinaría los indicadores.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd
import yfinance as yf
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from monitor_mercado.datos.modelos import ErrorDatos, SimboloSinDatos
from monitor_mercado.tecnico.indicadores import COLUMNAS_OHLCV

log = logging.getLogger(__name__)

_RENOMBRAR = {"Open": "apertura", "High": "maximo", "Low": "minimo", "Close": "cierre", "Volume": "volumen"}


class FuenteHistorica(Protocol):
    """Origen de precios históricos diarios (permite usar datos falsos en tests)."""

    def descargar(self, simbolo: str, desde: datetime | None, anios: int) -> pd.DataFrame:
        """OHLCV diario desde ``desde`` (o los últimos ``anios`` si es None)."""
        ...


class FuenteYahoo:
    """Históricos diarios ajustados desde Yahoo Finance."""

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=20),
        retry=retry_if_not_exception_type(SimboloSinDatos),
    )
    def descargar(self, simbolo: str, desde: datetime | None, anios: int) -> pd.DataFrame:
        """Descarga OHLCV diario ajustado.

        Raises:
            SimboloSinDatos: Si Yahoo no devuelve datos.
            ErrorDatos: Ante otros errores de la consulta.
        """
        try:
            ticker = yf.Ticker(simbolo)
            if desde is None:
                crudo = ticker.history(period=f"{anios}y", interval="1d", auto_adjust=True)
            else:
                crudo = ticker.history(start=desde.strftime("%Y-%m-%d"), interval="1d", auto_adjust=True)
        except Exception as e:  # noqa: BLE001
            raise ErrorDatos(f"{simbolo}: error descargando historial: {e}") from e
        if crudo is None or crudo.empty:
            raise SimboloSinDatos(f"{simbolo}: Yahoo no devolvió historial")
        return normalizar(crudo)


def normalizar(crudo: pd.DataFrame) -> pd.DataFrame:
    """Columnas en español, índice de fechas sin hora ni zona horaria, sin filas vacías."""
    df = crudo.rename(columns=_RENOMBRAR)[COLUMNAS_OHLCV].copy()
    indice = pd.DatetimeIndex(df.index)
    if indice.tz is not None:
        indice = indice.tz_localize(None)
    df.index = indice.normalize()
    df.index.name = "fecha"
    df = df.dropna(subset=["cierre"])
    return df[~df.index.duplicated(keep="last")].sort_index()


class AlmacenHistorico:
    """Caché local de históricos con actualización incremental."""

    def __init__(
        self, carpeta: Path, fuente: FuenteHistorica, anios: int = 10, refresco_horas: float = 6
    ) -> None:
        """
        Args:
            carpeta: Dónde guardar los CSV.
            fuente: De dónde descargar.
            anios: Años de historia en la primera descarga.
            refresco_horas: Antigüedad máxima del archivo antes de volver a actualizar.
        """
        self.carpeta = carpeta
        self._fuente = fuente
        self._anios = anios
        self._refresco = timedelta(hours=refresco_horas)

    def ruta(self, simbolo: str) -> Path:
        """Archivo CSV de un símbolo (``^IXIC`` -> ``INDICE_IXIC.csv``)."""
        nombre = simbolo.upper().replace("^", "INDICE_").replace("=", "_")
        return self.carpeta / f"{nombre}.csv"

    def leer(self, simbolo: str) -> pd.DataFrame | None:
        """Datos guardados, o None si no hay archivo."""
        ruta = self.ruta(simbolo)
        if not ruta.exists():
            return None
        return pd.read_csv(ruta, index_col="fecha", parse_dates=["fecha"])

    def obtener(self, simbolo: str, forzar: bool = False) -> pd.DataFrame:
        """Historial actualizado de ``simbolo``.

        Si el archivo local es reciente se usa tal cual; si no, se descargan las
        últimas ruedas y se combinan. Si la descarga falla pero hay datos locales,
        se devuelven esos (con una advertencia en el log) en vez de fallar.

        Raises:
            ErrorDatos: Si no hay datos locales y la descarga falla.
        """
        ruta = self.ruta(simbolo)
        guardado = self.leer(simbolo)
        if guardado is not None and not forzar:
            edad = datetime.now() - datetime.fromtimestamp(ruta.stat().st_mtime)
            if edad < self._refresco:
                return guardado

        try:
            if guardado is None or guardado.empty:
                nuevo = self._fuente.descargar(simbolo, None, self._anios)
                combinado = nuevo
            else:
                # Se vuelven a bajar ~10 días para corregir datos provisorios de las últimas ruedas.
                desde = guardado.index[-1].to_pydatetime() - timedelta(days=10)
                nuevo = self._fuente.descargar(simbolo, desde, self._anios)
                combinado = pd.concat([guardado[guardado.index < nuevo.index[0]], nuevo])
        except ErrorDatos as e:
            if guardado is not None:
                log.warning("%s: uso datos locales, no se pudo actualizar: %s", simbolo, e)
                return guardado
            raise

        self.carpeta.mkdir(parents=True, exist_ok=True)
        combinado.to_csv(ruta)
        log.info("%s: historial actualizado (%d ruedas).", simbolo, len(combinado))
        return combinado

    def actualizar_varios(self, simbolos: list[str], pausa_seg: float = 0.5) -> dict[str, str]:
        """Actualiza varios símbolos; devuelve un estado por símbolo ("ok" o el error)."""
        estados: dict[str, str] = {}
        for s in simbolos:
            try:
                df = self.obtener(s, forzar=True)
                estados[s] = f"ok ({len(df)} ruedas, hasta {df.index[-1].date()})"
            except ErrorDatos as e:
                estados[s] = f"error: {e}"
            time.sleep(pausa_seg)  # para no saturar a Yahoo y evitar bloqueos
        return estados
