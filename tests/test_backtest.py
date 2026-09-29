import numpy as np
import pandas as pd
import pytest

from monitor_mercado.backtest.motor import calcular_metricas, max_drawdown, operaciones, posiciones, sharpe, simular
from monitor_mercado.backtest.reporte import explicacion_backtest, reporte_backtest, resumen_backtests
from monitor_mercado.backtest.servicio import Conclusion, ServicioBacktest
from monitor_mercado.backtest.validacion import bootstrap_sharpe, poder_predictivo, walk_forward
from monitor_mercado.configuracion import Configuracion
from monitor_mercado.datos.modelos import ErrorDatos


def precios(cierres, aperturas=None) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=len(cierres))
    c = pd.Series(cierres, index=idx, dtype=float)
    a = c.shift().fillna(c.iloc[0]) if aperturas is None else pd.Series(aperturas, index=idx, dtype=float)
    return pd.DataFrame({"apertura": a, "cierre": c})


# ------------------------------------------------------------------ posiciones
def test_histeresis_entre_umbrales():
    p = pd.Series([0.0, 0.3, 0.1, 0.05, -0.25, 0.1, 0.3])
    assert list(posiciones(p, 0.2, -0.2)) == [0, 1, 1, 1, 0, 0, 1]


def test_corto_opcional():
    p = pd.Series([0.3, -0.3, -0.1, 0.25])
    assert list(posiciones(p, 0.2, -0.2, corto=False)) == [1, 0, 0, 1]
    assert list(posiciones(p, 0.2, -0.2, corto=True)) == [1, -1, -1, 1]


# ----------------------------------------------------------------- simulación
def test_no_usa_informacion_del_futuro():
    """La señal del día t recién gana (o pierde) desde la apertura del día t+1."""
    d = precios([100, 100, 100, 110, 110], aperturas=[100, 100, 100, 110, 110])
    # La señal se enciende el MISMO día del salto (día 3): no debe capturarlo.
    pos = pd.Series([0, 0, 0, 1, 1], index=d.index, dtype=float)
    sim = simular(d, pos, costo_por_lado=0)
    assert sim["estrategia"].sum() == pytest.approx(0)
    # Encendida el día anterior (día 2): entra en la apertura del día 3 y gana el intradía.
    d2 = precios([100, 100, 100, 110, 110], aperturas=[100, 100, 100, 100, 110])
    pos2 = pd.Series([0, 0, 1, 1, 1], index=d.index, dtype=float)
    assert simular(d2, pos2, 0)["estrategia"].iloc[3] == pytest.approx(0.10)


def test_costos_por_cada_compra_y_venta():
    d = precios([100] * 8)
    pos = pd.Series([0, 1, 1, 0, 0, 1, 0, 0], index=d.index, dtype=float)
    sim = simular(d, pos, costo_por_lado=0.01)
    assert sim["costo"].sum() == pytest.approx(0.04)  # 2 compras + 2 ventas
    assert calcular_metricas(sim["estrategia"], sim).operaciones == 2


def test_metricas_basicas():
    r = pd.Series([0.10, -0.50, 0.20])
    assert max_drawdown(r) == pytest.approx(-0.5)
    assert sharpe(pd.Series([0.01] * 10)) == 0.0  # sin volatilidad no hay Sharpe
    m = calcular_metricas(pd.Series([0.001] * 252 + [0.002] * 252))
    assert m.retorno_anual == pytest.approx(np.sqrt(1.001 ** 252 * 1.002 ** 252) - 1, rel=1e-6)


def test_operaciones_ganadoras_y_perdedoras():
    sim = pd.DataFrame({"posicion": [0, 1, 1, 0, 1, 0], "estrategia": [0, 0.1, 0.1, 0, -0.2, 0]})
    ops = operaciones(sim)
    assert ops[0] == pytest.approx(0.21) and ops[1] == pytest.approx(-0.2)


# ----------------------------------------------------------------- validación
def test_walk_forward_solo_mide_fuera_de_muestra(datos_ohlcv):
    d = datos_ohlcv(252 * 6, tendencia=0.0005)
    puntajes = pd.Series(np.random.default_rng(0).normal(0, 0.3, len(d)), index=d.index)
    wf = walk_forward(d, puntajes, 0.001, anios_entrenamiento=3, anios_prueba=1)
    assert len(wf.ventanas) == 3
    assert wf.retornos.index[0] == d.index[252 * 3]  # los 3 primeros años nunca se miden
    assert not wf.retornos.index.duplicated().any()


def test_puntajes_al_azar_muestran_overfitting(datos_ohlcv):
    """Con una señal aleatoria, lo optimizado en entrenamiento no se sostiene en prueba."""
    d = datos_ohlcv(252 * 8, tendencia=0.0003, semilla=3)
    puntajes = pd.Series(np.random.default_rng(1).normal(0, 0.3, len(d)), index=d.index)
    wf = walk_forward(d, puntajes, 0.001)
    assert wf.sharpe_entrenamiento_medio > wf.sharpe_prueba_medio


def test_bootstrap():
    rng = np.random.default_rng(0)
    base = pd.Series(rng.normal(0.0003, 0.01, 2000))
    assert bootstrap_sharpe(base, base, 300) == 1.0  # idénticas: nunca la supera
    mejor = base + 0.002
    assert bootstrap_sharpe(mejor, base, 300) < 0.05


def test_poder_predictivo_de_una_senal_perfecta():
    rng = np.random.default_rng(0)
    cierres = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1000))))
    futuro = cierres.shift(-20) / cierres - 1
    perfecta = np.sign(futuro).fillna(0) * 0.5
    pp = poder_predictivo(perfecta, cierres, 0.2, 20)
    assert pp.acierto_alcista == 1.0 and pp.acierto_bajista == 1.0 and pp.correlacion > 0.8


# ------------------------------------------------------------------- servicio
class TecnicoFalso:
    def __init__(self, df):
        self.df = df

    def datos(self, simbolo):
        return self.df, "USD", False


def test_servicio_completo_y_reportes(datos_ohlcv):
    cfg = Configuracion.model_validate({"backtest": {"repeticiones_bootstrap": 200}})
    bt = ServicioBacktest(TecnicoFalso(datos_ohlcv(252 * 7, tendencia=0.0004)), cfg)
    r = bt.correr("AAPL")
    assert r.costo_por_lado == pytest.approx(0.0015)  # 0,1% EE.UU. + 0,05% slippage
    assert r.wf_estrategia is not None and len(r.wf.ventanas) >= 2
    assert isinstance(r.conclusion, Conclusion)
    texto = reporte_backtest(r)
    for parte in ("Walk-forward", "Overfitting", "Poder predictivo", "Conclusión", "no es una recomendación"):
        assert parte in texto
    assert "Supervivencia" in explicacion_backtest(r)
    assert "Conclusión general" in resumen_backtests([r], {"X": "sin datos"})


def test_costo_segun_mercado(datos_ohlcv):
    bt = ServicioBacktest(TecnicoFalso(datos_ohlcv(10)), Configuracion())
    assert bt.costo("ALUA.BA") == pytest.approx(0.0065)
    assert bt.costo("PETR4.SA") == pytest.approx(0.0035)


def test_historia_corta_da_error(datos_ohlcv):
    bt = ServicioBacktest(TecnicoFalso(datos_ohlcv(500)), Configuracion())
    with pytest.raises(ErrorDatos, match="necesita"):
        bt.correr("NUEVA")
