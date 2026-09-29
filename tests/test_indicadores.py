import numpy as np
import pandas as pd
import pytest

from monitor_mercado.tecnico.indicadores import bollinger, calcular_indicadores, ema, macd, rsi, sma


def serie(valores) -> pd.Series:
    return pd.Series(valores, index=pd.date_range("2024-01-01", periods=len(valores), freq="B"), dtype=float)


def test_sma_simple():
    s = sma(serie([1, 2, 3, 4, 5]), 3)
    assert s.isna().sum() == 2
    assert s.iloc[-1] == pytest.approx(4)


def test_ema_pesa_mas_lo_reciente():
    s = serie([10] * 20 + [20])
    assert ema(s, 10).iloc[-1] > sma(s, 10).iloc[-1]


def test_rsi_extremos_y_rango():
    subiendo = serie(np.arange(1, 40))
    assert rsi(subiendo).iloc[-1] == pytest.approx(100)
    bajando = serie(np.arange(40, 1, -1))
    assert rsi(bajando).iloc[-1] == pytest.approx(0)
    ruido = serie(100 + np.random.default_rng(1).normal(0, 1, 300).cumsum())
    valores = rsi(ruido).dropna()
    assert valores.between(0, 100).all()


def test_rsi_con_subas_y_bajas_iguales_ronda_50():
    # Alterna +1 / -1: el RSI oscila alrededor de 50, un poco arriba tras una suba
    # y un poco abajo tras una baja (por el suavizado de Wilder).
    termina_subiendo = rsi(serie([10, 11] * 20)).iloc[-1]
    termina_bajando = rsi(serie([11, 10] * 20)).iloc[-1]
    assert 50 < termina_subiendo < 60
    assert 40 < termina_bajando < 50


def test_macd_histograma_es_la_diferencia():
    s = serie(100 + np.random.default_rng(2).normal(0, 1, 200).cumsum())
    m = macd(s).dropna()
    assert np.allclose(m["macd_hist"], m["macd"] - m["macd_senal"])


def test_bollinger_contiene_la_media():
    s = serie(100 + np.random.default_rng(3).normal(0, 1, 100).cumsum())
    b = bollinger(s).dropna()
    assert (b["bb_inferior"] <= b["bb_media"]).all() and (b["bb_media"] <= b["bb_superior"]).all()
    # %B = 0,5 cuando el precio está exactamente en la media.
    constante = bollinger(serie([10] * 19 + [10.0]))
    assert constante["bb_ancho"].iloc[-1] == 0


def test_calcular_indicadores_agrega_columnas(datos_ohlcv):
    df = calcular_indicadores(datos_ohlcv(300))
    for col in ("sma20", "sma50", "sma200", "rsi14", "macd", "bb_pct", "atr14", "vol_relativo"):
        assert col in df and df[col].notna().iloc[-1]
