"""Indicadores técnicos calculados con pandas (funciones puras, sin red).

Todas las funciones reciben series o un DataFrame con las columnas
``apertura, maximo, minimo, cierre, volumen`` indexado por fecha.

Guía rápida de cada indicador:
- Media móvil simple (SMA): promedio de los últimos N cierres. Suaviza el ruido;
  si el precio está arriba de su media, la tendencia de ese plazo es alcista.
- Media móvil exponencial (EMA): como la SMA, pero pesa más los datos recientes.
- RSI (índice de fuerza relativa, 0-100): compara subas y bajas recientes.
  Más de 70 suele leerse como "sobrecomprado", menos de 30 como "sobrevendido".
- MACD: diferencia entre una EMA rápida (12) y una lenta (26). Cuando cruza por
  encima de su propia media (señal, EMA 9) indica que el impulso se vuelve alcista.
- Bandas de Bollinger: media de 20 ± 2 desvíos estándar. Miden si el precio está
  "estirado" respecto de su rango habitual, y el ancho mide la volatilidad.
- Volumen relativo: volumen del día / promedio de 20 días. Movimientos con mucho
  volumen se consideran más "confirmados".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COLUMNAS_OHLCV = ["apertura", "maximo", "minimo", "cierre", "volumen"]


def sma(serie: pd.Series, periodo: int) -> pd.Series:
    """Media móvil simple de ``periodo`` datos (NaN hasta tener suficientes)."""
    return serie.rolling(periodo, min_periods=periodo).mean()


def ema(serie: pd.Series, periodo: int) -> pd.Series:
    """Media móvil exponencial con suavizado estándar 2/(periodo+1)."""
    return serie.ewm(span=periodo, adjust=False, min_periods=periodo).mean()


def rsi(cierre: pd.Series, periodo: int = 14) -> pd.Series:
    """RSI de Wilder (el cálculo que usan TradingView y la mayoría de plataformas)."""
    delta = cierre.diff()
    subas = delta.clip(lower=0)
    bajas = -delta.clip(upper=0)
    # Suavizado de Wilder = EMA con alpha 1/periodo.
    media_subas = subas.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()
    media_bajas = bajas.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()
    rs = media_subas / media_bajas
    resultado = 100 - 100 / (1 + rs)
    # Sin bajas en el período el RSI es 100 (rs infinito).
    return resultado.where(media_bajas != 0, 100.0).where(media_subas.notna())


def macd(
    cierre: pd.Series, rapida: int = 12, lenta: int = 26, senal: int = 9
) -> pd.DataFrame:
    """MACD, línea de señal e histograma (MACD - señal)."""
    linea = ema(cierre, rapida) - ema(cierre, lenta)
    linea_senal = linea.ewm(span=senal, adjust=False, min_periods=senal).mean()
    return pd.DataFrame(
        {"macd": linea, "macd_senal": linea_senal, "macd_hist": linea - linea_senal}
    )


def bollinger(cierre: pd.Series, periodo: int = 20, desvios: float = 2.0) -> pd.DataFrame:
    """Bandas de Bollinger, %B (posición dentro de las bandas) y ancho relativo."""
    media = sma(cierre, periodo)
    desvio = cierre.rolling(periodo, min_periods=periodo).std(ddof=0)
    superior = media + desvios * desvio
    inferior = media - desvios * desvio
    return pd.DataFrame(
        {
            "bb_media": media,
            "bb_superior": superior,
            "bb_inferior": inferior,
            # 0 = en la banda inferior, 1 = en la superior, >1 = por encima.
            "bb_pct": (cierre - inferior) / (superior - inferior),
            "bb_ancho": (superior - inferior) / media,
        }
    )


def atr(datos: pd.DataFrame, periodo: int = 14) -> pd.Series:
    """Average True Range: rango diario promedio (mide volatilidad en $)."""
    cierre_prev = datos["cierre"].shift()
    rango = pd.concat(
        [
            datos["maximo"] - datos["minimo"],
            (datos["maximo"] - cierre_prev).abs(),
            (datos["minimo"] - cierre_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return rango.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()


def calcular_indicadores(datos: pd.DataFrame) -> pd.DataFrame:
    """Agrega todas las columnas de indicadores a una copia de ``datos``."""
    df = datos.copy()
    c = df["cierre"]
    for n in (20, 50, 200):
        df[f"sma{n}"] = sma(c, n)
    df["ema20"] = ema(c, 20)
    df["rsi14"] = rsi(c)
    df = df.join(macd(c)).join(bollinger(c))
    df["atr14"] = atr(df)
    volumen_medio = sma(df["volumen"].astype(float), 20)
    df["vol_relativo"] = (df["volumen"] / volumen_medio).replace([np.inf, -np.inf], np.nan)
    df["retorno_1d"] = c.pct_change()
    df["retorno_63d"] = c.pct_change(63)  # ~3 meses de ruedas
    df["max_20d"] = df["maximo"].rolling(20).max()
    df["min_20d"] = df["minimo"].rolling(20).min()
    df["max_252d"] = df["maximo"].rolling(252, min_periods=200).max()  # ~1 año
    df["min_252d"] = df["minimo"].rolling(252, min_periods=200).min()
    return df
