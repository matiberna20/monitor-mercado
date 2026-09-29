import numpy as np
import pandas as pd

from monitor_mercado.tecnico.indicadores import calcular_indicadores
from monitor_mercado.tecnico.patrones import detectar_patrones, patrones_recientes
from monitor_mercado.tecnico.senal import SenalPorReglas, Tendencia, caracteristicas
from monitor_mercado.tecnico.reporte import reporte_completo


def test_tendencia_alcista_clara(datos_ohlcv):
    s = SenalPorReglas().generar(calcular_indicadores(datos_ohlcv(300, tendencia=0.004)))
    assert s.tendencia is Tendencia.ALCISTA
    assert s.confianza >= 65 and s.nivel_confianza == "alta"


def test_tendencia_bajista_clara(datos_ohlcv):
    s = SenalPorReglas().generar(calcular_indicadores(datos_ohlcv(300, tendencia=-0.004)))
    assert s.tendencia is Tendencia.BAJISTA and s.puntaje < -0.5


def test_mercado_lateral_no_da_senal_fuerte():
    # Precio que oscila en un rango (onda de 40 ruedas) sin tendencia de fondo.
    t = np.arange(300)
    precios = 100 + 3 * np.sin(2 * np.pi * t / 40) + np.random.default_rng(0).normal(0, 0.3, 300)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    df = pd.DataFrame({"apertura": precios, "maximo": precios + 0.5, "minimo": precios - 0.5,
                       "cierre": precios, "volumen": 1_000_000.0}, index=idx)
    ind = calcular_indicadores(df)
    # En ninguna de las últimas 100 ruedas los factores de fondo votan fuerte.
    votos = caracteristicas(ind).tail(100)
    assert votos["estructura_medias"].abs().max() < 0.3
    s = SenalPorReglas().generar(ind)
    assert s.confianza < 65


def test_misma_tendencia_relativa_misma_senal_con_distinta_volatilidad(datos_ohlcv):
    # Una tendencia de 0,4%/día es fuerte para un activo tranquilo; con mucho
    # ruido la misma suba pesa menos.
    tranquilo = SenalPorReglas().generar(calcular_indicadores(datos_ohlcv(300, 0.002, ruido=0.005)))
    volatil = SenalPorReglas().generar(calcular_indicadores(datos_ohlcv(300, 0.002, ruido=0.04)))
    assert tranquilo.puntaje > volatil.puntaje


def test_sin_historia_larga_baja_la_confianza(datos_ohlcv):
    # Con 100 ruedas no hay media de 200: faltan los factores de más peso.
    corta = SenalPorReglas().generar(calcular_indicadores(datos_ohlcv(100, tendencia=0.004)))
    larga = SenalPorReglas().generar(calcular_indicadores(datos_ohlcv(300, tendencia=0.004)))
    assert corta.confianza < larga.confianza
    assert "tendencia_largo" not in {f.clave for f in corta.factores}


def test_caracteristicas_existen_para_cada_fecha(datos_ohlcv):
    df = calcular_indicadores(datos_ohlcv(300))
    votos = caracteristicas(df)
    assert len(votos) == len(df)
    assert votos.dropna().abs().max().max() <= 1
    puntajes = SenalPorReglas().puntajes(votos).dropna()
    assert puntajes["puntaje"].between(-1, 1).all() and puntajes["confianza"].between(0, 100).all()


def test_cruce_dorado_detectado():
    # 250 ruedas bajando y luego una suba fuerte: la media de 50 cruza a la de 200.
    precios = np.concatenate([np.linspace(100, 60, 250), np.linspace(60, 140, 120)])
    idx = pd.date_range("2023-01-02", periods=len(precios), freq="B")
    df = pd.DataFrame({"apertura": precios, "maximo": precios * 1.01, "minimo": precios * 0.99,
                       "cierre": precios, "volumen": 1_000_000}, index=idx)
    tabla = detectar_patrones(calcular_indicadores(df))
    assert tabla["cruce_dorado"].sum() == 1
    assert not tabla["cruce_muerte"].any()


def test_envolvente_alcista():
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    df = pd.DataFrame({"apertura": 100.0, "maximo": 101.0, "minimo": 99.0, "cierre": 100.0,
                       "volumen": 1000}, index=idx)
    df.iloc[-2, :4] = [100, 100.5, 97.5, 98]  # vela roja
    df.iloc[-1, :4] = [97.8, 101.5, 97.5, 101]  # vela verde que la envuelve
    encontrados = {p.clave for p in patrones_recientes(calcular_indicadores(df), ruedas=1)}
    assert "envolvente_alcista" in encontrados


def test_reporte_incluye_aviso_y_factores(datos_ohlcv, cfg):
    from monitor_mercado.tecnico.servicio import Analisis

    df = calcular_indicadores(datos_ohlcv(300, tendencia=0.004))
    a = Analisis("TEST", "USD", df, SenalPorReglas().generar(df), patrones_recientes(df))
    texto = reporte_completo(a)
    assert "ALCISTA" in texto
    assert "no es una recomendación de inversión" in texto
    assert "no la probabilidad de acierto" in texto
